"""LLMProvider 介面與回傳格式。

換 AI 供應商時只需要新增一個實作這個介面的類別，再到 ai/factory.py 註冊一行，
services/ 以上完全不用改。

重要原則（docs/architecture.md 第 5 節）：
LLM 的輸出永遠只是「輔助訊號」，不會直接寫入 regulations.status。
每一次呼叫都會回傳一份 LLMCallRecord，由呼叫端寫入 ai_invocation_log。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.enums import AIPurpose


# --- LLM 結構化輸出的資料格式（同時是送給模型的 JSON Schema）---

class ExtractedItem(BaseModel):
    raw_text: str = Field(description="文件中出現的原始文字")
    regulation_type: str = Field(description="law/regulation/standard/engineering_spec/contract_spec/announcement/other")
    article: str | None = Field(default=None, description="條號，沒有就填 null")
    standard_number: str | None = Field(default=None, description="標準編號，例如 CNS 560")
    confidence: float = Field(ge=0.0, le=1.0, description="0 到 1 的信心分數")


class ExtractionResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)


class SimilarityJudgement(BaseModel):
    is_same: bool = Field(description="兩個名稱是否指向同一部法規")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="一句話說明判斷理由")


class Citation(BaseModel):
    ref: str = Field(description="引用的條文識別字，必須和提供的條文標題一字不差，例如「建築法 第 69 條」")
    quote: str = Field(description="從該條文原文逐字複製、直接支持回答的句子；不可改寫、不可摘要")


class RegulationAnswer(BaseModel):
    answerable: bool = Field(description="提供的條文是否足以回答問題；不足就填 false")
    answer: str = Field(description="繁體中文回答；answerable=false 時說明缺少什麼")
    citations: list[Citation] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Passage:
    """送給模型的一段條文（檢索結果）。"""

    ref: str
    text: str


# --- 呼叫紀錄 ---

@dataclass(slots=True)
class LLMCallRecord:
    """一次 LLM 呼叫的完整稽核資料，對應 ai_invocation_log 的欄位。"""

    purpose: AIPurpose
    model: str
    prompt_version: str
    input_text: str
    output_json: Any | None = None
    confidence: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    #: 實際用量：input_tokens / output_tokens / cache_read_input_tokens，用來算每次呼叫的成本
    usage: dict[str, int] | None = None


T = TypeVar("T")


@dataclass(slots=True)
class LLMResult(Generic[T]):
    """value 為 None 代表這次呼叫失敗或輸出驗證不通過，呼叫端必須能夠降級運作。"""

    value: T | None
    record: LLMCallRecord | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


class LLMProvider(ABC):
    """所有 AI 供應商的共同介面。"""

    name: str = "base"

    @property
    def enabled(self) -> bool:
        """AI 是否真的會被呼叫。NullProvider 回傳 False，呼叫端就不必到處寫 if。"""
        return True

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    async def extract_regulations(self, text: str) -> LLMResult[ExtractionResult]:
        """從一段文字抽取法規引用（規則與字典都抽不到時才呼叫）。"""

    @abstractmethod
    async def judge_similarity(
        self, name_a: str, name_b: str, context: str = ""
    ) -> LLMResult[SimilarityJudgement]:
        """判斷兩個法規名稱是否指向同一部法規（僅作為比對的補充訊號）。"""

    @abstractmethod
    async def summarize_for_report(self, findings: list[str]) -> LLMResult[str]:
        """把結構化的查核結果轉成人類可讀的說明文字（只負責語言表達，不做判斷）。"""

    async def answer_regulation_question(
        self, question: str, passages: list[Passage]
    ) -> LLMResult[RegulationAnswer]:
        """只根據 `passages` 回答法規問題並逐字引用。引用由呼叫端再驗證一次（app/search/grounding.py）。

        不是抽象方法：沒實作問答的 provider 直接回傳 value=None，呼叫端當成「AI 無法回答」。
        """
        return LLMResult(value=None)
