"""不呼叫任何 AI 的實作。

當 ENABLE_LLM_FALLBACK=false、或沒有設定 API key 時使用。
它讓「關掉 AI」不需要在呼叫端到處寫 if 判斷——系統照樣可以完整跑完，
只是抽取召回率與比對信心會下降（docs/architecture.md 1.5）。
"""

from app.ai.base import ExtractionResult, LLMProvider, LLMResult, SimilarityJudgement


class NullProvider(LLMProvider):
    name = "null"

    @property
    def enabled(self) -> bool:
        return False

    @property
    def model(self) -> str:
        return "disabled"

    async def extract_regulations(self, text: str) -> LLMResult[ExtractionResult]:
        return LLMResult(value=None)

    async def judge_similarity(
        self, name_a: str, name_b: str, context: str = ""
    ) -> LLMResult[SimilarityJudgement]:
        return LLMResult(value=None)

    async def summarize_for_report(self, findings: list[str]) -> LLMResult[str]:
        return LLMResult(value=None)
