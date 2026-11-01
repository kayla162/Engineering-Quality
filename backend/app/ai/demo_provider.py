"""示範用的「AI」：不呼叫任何模型，用固定規則回應。

沒有 API key 時，AI 相關的流程（抽取後援、模糊比對輔助、報告摘要）與它們留下的
紀錄在畫面上永遠是空的，看不出系統會怎麼用 AI。設 `LLM_PROVIDER=demo` 就用這個：

- 每一次呼叫都照常寫進 ai_invocation_log，模型名稱是 `demo-rules（示範，非真實 AI）`，
  畫面上的「AI 使用情形」一眼看得出這不是真的模型。
- 輸出和真的 provider 一樣走 Pydantic 格式、一樣只當輔助訊號，系統其他部分不必知道差別。
- 規則刻意保守：抽取只認幾個內部文件常見的字尾；相似度判斷用字元重疊度。

這不是 AI，不能拿它的結果評估 AI 的效果。接上真的模型改設 `LLM_PROVIDER=anthropic` 並填 API key。
"""

import re
import time

from app.ai.base import (
    ExtractedItem,
    ExtractionResult,
    LLMCallRecord,
    LLMProvider,
    LLMResult,
    SimilarityJudgement,
)
from app.core.enums import AIPurpose, RegulationType
from app.extractors.rule_engine import _clean_name

MODEL_NAME = "demo-rules（示範，非真實 AI）"
PROMPT_VERSION = "demo_v1"

#: 規則與字典都不認得、但看起來像文件名稱的字尾。非貪婪：停在第一個字尾，
#: 前面多抓到的句子（「各分項工程依…」）交給規則引擎同一套 _clean_name 剝掉
_DOCUMENT_NAME = re.compile(r"(?P<name>[一-鿿]{2,20}?(?:程序書|手冊|規章|作業規定|管理辦法))")
#: 字元重疊度達到這個比例才說是同一份
SAME_THRESHOLD = 0.6


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)} or {cleaned}


class DemoProvider(LLMProvider):
    name = "demo"

    @property
    def model(self) -> str:
        return MODEL_NAME

    async def extract_regulations(self, text: str) -> LLMResult[ExtractionResult]:
        started = time.perf_counter()
        cleaned = (_clean_name(m.group("name")) for m in _DOCUMENT_NAME.finditer(text))
        names = list(dict.fromkeys(name for name in cleaned if len(name) >= 4))
        result = ExtractionResult(
            items=[
                ExtractedItem(raw_text=name, regulation_type=RegulationType.OTHER, confidence=0.6)
                for name in names
            ]
        )
        return LLMResult(
            value=result,
            record=self._record(AIPurpose.EXTRACTION, text, result.model_dump(), 0.6 if names else None, started),
        )

    async def judge_similarity(
        self, name_a: str, name_b: str, context: str = ""
    ) -> LLMResult[SimilarityJudgement]:
        started = time.perf_counter()
        a, b = _bigrams(name_a), _bigrams(name_b)
        overlap = len(a & b) / len(a | b)
        judgement = SimilarityJudgement(
            is_same=overlap >= SAME_THRESHOLD,
            confidence=round(overlap, 2),
            reason=f"示範規則：兩個名稱的字元重疊度 {overlap:.0%}"
            f"（{'達到' if overlap >= SAME_THRESHOLD else '未達'} {SAME_THRESHOLD:.0%}），非 AI 判斷",
        )
        return LLMResult(
            value=judgement,
            record=self._record(
                AIPurpose.SIMILARITY_JUDGEMENT,
                f"{name_a} / {name_b}",
                judgement.model_dump(),
                judgement.confidence,
                started,
            ),
        )

    async def summarize_for_report(self, findings: list[str]) -> LLMResult[str]:
        started = time.perf_counter()
        lines = [f"本報告共 {len(findings)} 項重點（示範摘要，依固定格式排列，非 AI 撰寫）："]
        lines += [f"{index}. {finding}" for index, finding in enumerate(findings, start=1)]
        summary = "\n".join(lines)
        return LLMResult(
            value=summary,
            record=self._record(AIPurpose.REPORT_SUMMARY, "\n".join(findings), {"summary": summary}, None, started),
        )

    def _record(self, purpose, input_text, output, confidence, started) -> LLMCallRecord:
        return LLMCallRecord(
            purpose=purpose,
            model=MODEL_NAME,
            prompt_version=PROMPT_VERSION,
            input_text=input_text,
            output_json=output,
            confidence=confidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
