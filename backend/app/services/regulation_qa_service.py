"""法規問答：檢索條文 → 模型只根據這些條文回答並逐字引用 → 程式驗證引用。

流程：
1. 混合搜尋取前 QA_TOP_K 條（和「搜尋」分頁同一個 KnowledgeSearchService）
2. 把完整條文送給模型（AnthropicProvider.answer_regulation_question），要求逐字引用
3. `check_citations` 用字串比對驗證每一條引用
4. 依結果給狀態：
   - answered：至少一條引用通過驗證；沒通過的引用照樣列出、標示原因
   - insufficient：模型說條文不足以回答（這是正確行為，不是失敗）
   - unverified：模型有回答，但沒有任何一條引用通過驗證 → **不顯示回答**，只列出檢索到的條文
   - unavailable：AI 沒有啟用
   - failed：AI 有啟用，但這次呼叫失敗（逾時、額度不足、輸出格式錯誤…），原因在 ai_invocation_log

每一次呼叫都寫進 ai_invocation_log（含 token 用量），可以回溯是哪個模型、哪版 prompt 回答的。
評估見 scripts/eval_qa.py 與 docs/regulation-qa.md。
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider, Passage
from app.core.config import settings
from app.repositories.audit import AuditRepository
from app.search.grounding import CheckedCitation, check_citations
from app.services.knowledge_search_service import KnowledgeSearchService

ANSWERED = "answered"
INSUFFICIENT = "insufficient"
UNVERIFIED = "unverified"
UNAVAILABLE = "unavailable"
FAILED = "failed"
#: 檢索時多取幾倍的候選，去掉規範章節後仍湊得滿 top_k 條條文
CANDIDATE_FACTOR = 3


@dataclass(frozen=True)
class QAResult:
    question: str
    status: str
    #: unverified／unavailable 時是空字串：沒有通過驗證的回答不給人看
    answer: str
    citations: list[CheckedCitation] = field(default_factory=list)
    #: 送給模型的條文（混合搜尋的名次順序）
    retrieved: list[str] = field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None


def decide(answerable: bool, answer: str, checked: list[CheckedCitation]) -> tuple[str, str]:
    """模型輸出 + 驗證結果 → (狀態, 給人看的回答)。評估腳本也用這個，畫面和評估的判定才一致。"""
    if not answerable:
        return INSUFFICIENT, answer
    if not any(c.verified for c in checked):
        return UNVERIFIED, ""
    return ANSWERED, answer


class RegulationQAService:
    def __init__(self, session: AsyncSession, provider: LLMProvider, search: KnowledgeSearchService):
        self.session = session
        self.provider = provider
        self.search = search

    async def answer(self, question: str, top_k: int | None = None) -> QAResult:
        top_k = top_k or settings.QA_TOP_K
        # 規範章節目前只有章名、沒有內文，送給模型也無從引用。先多取候選、去掉章節，再取前 top_k 條：
        # 先取 top_k 再過濾的話，前幾名都是章節的問題（例如「施工日誌」）會一條條文都沒送出去
        hits = (await self.search.search(question, "hybrid", top_k * CANDIDATE_FACTOR)).hits
        refs = [hit.ref for hit in hits if hit.kind == "law_article"][:top_k]
        passages = [Passage(chunk.ref, chunk.content) for chunk in await self.search.chunks(refs)]

        if not self.provider.enabled:
            return QAResult(question, UNAVAILABLE, "", retrieved=refs)

        result = await self.provider.answer_regulation_question(question, passages)
        if result.record is not None:
            await AuditRepository(self.session).log_ai_call(result.record)
            await self.session.commit()
        if result.value is None:
            return QAResult(question, FAILED, "", retrieved=refs, model=self.provider.model)

        checked = check_citations(result.value.citations, passages)
        status, answer = decide(result.value.answerable, result.value.answer, checked)
        return QAResult(
            question,
            status,
            answer,
            citations=checked,
            retrieved=refs,
            model=result.record.model if result.record else self.provider.model,
            prompt_version=result.record.prompt_version if result.record else None,
        )
