"""抽取管線：Rule -> Dictionary -> (可選) LLM fallback。

順序固定，前一層抽到東西就不會往下一層送，理由是規則與字典的結果可解釋、可重現，
LLM 只在前兩層都沒有收穫時才介入（docs/architecture.md 第 5 節）。

NER 層在 MVP 未實作（development-plan.md Phase 4 明確說先不做），
要加的時候在這裡多插一層即可，Candidate 格式不變。
"""

from app.ai.base import LLMCallRecord, LLMProvider
from app.extractors.base import Candidate, dedupe
from app.extractors.dictionary_extractor import DictionaryExtractor
from app.extractors.llm_extractor import LLMExtractor
from app.extractors.rule_engine import RuleEngine


class ExtractionPipeline:
    def __init__(self, llm_provider: LLMProvider | None = None):
        self._rule = RuleEngine()
        self._dictionary = DictionaryExtractor()
        # AI 關閉時整層不建立，管線就完全不會走到 LLM
        self._llm = (
            LLMExtractor(llm_provider)
            if llm_provider is not None and llm_provider.enabled
            else None
        )

    async def extract(self, text: str) -> tuple[list[Candidate], LLMCallRecord | None]:
        """對一段文字抽取法規引用，回傳 (候選清單, LLM 呼叫紀錄或 None)。"""
        candidates = dedupe(self._rule.extract(text) + self._dictionary.extract(text))
        if candidates or self._llm is None:
            return candidates, None

        llm_candidates, record = await self._llm.extract(text)
        return dedupe(llm_candidates), record


__all__ = ["Candidate", "DictionaryExtractor", "ExtractionPipeline", "RuleEngine", "dedupe"]
