"""法規引用清單與詳細資料的 schema。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RegulationStatus, ReviewStatus
from app.models.audit import AIInvocationLog, RegulationQuery
from app.models.reference import RegulationReference


class ReferenceSummary(BaseModel):
    """清單上方的統計。六種狀態都列出來，避免 NOT_FOUND / POSSIBLE_MATCH 被藏起來。"""

    confirmed_active: int = 0
    possible_amended: int = 0
    possible_repealed: int = 0
    possible_match: int = 0
    not_found: int = 0
    unknown: int = 0

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> "ReferenceSummary":
        return cls(
            confirmed_active=counts.get(RegulationStatus.ACTIVE, 0),
            possible_amended=counts.get(RegulationStatus.AMENDED, 0),
            possible_repealed=counts.get(RegulationStatus.REPEALED, 0),
            possible_match=counts.get(RegulationStatus.POSSIBLE_MATCH, 0),
            not_found=counts.get(RegulationStatus.NOT_FOUND, 0),
            unknown=counts.get(RegulationStatus.UNKNOWN, 0),
        )


class ReferenceListItem(BaseModel):
    reference_id: uuid.UUID
    raw_text: str
    normalized_name: str | None
    regulation_type: str
    article: str | None
    page: int | None
    status: str
    match_confidence: float | None
    review_status: str
    regulation_id: uuid.UUID | None
    #: 信心未達自動採信門檻，前端顯示「疑似」
    is_tentative: bool = False

    @classmethod
    def from_model(cls, reference: RegulationReference, tentative: bool) -> "ReferenceListItem":
        return cls(
            reference_id=reference.id,
            raw_text=reference.raw_text,
            normalized_name=reference.normalized_name,
            regulation_type=reference.regulation_type,
            article=reference.article,
            page=reference.section.page if reference.section else None,
            status=reference.status,
            match_confidence=reference.match_confidence,
            review_status=reference.review_status,
            regulation_id=reference.regulation_id,
            is_tentative=tentative,
        )


class ReferenceListOut(BaseModel):
    total: int
    page: int
    page_size: int
    summary: ReferenceSummary
    items: list[ReferenceListItem]


class MatchedRegulation(BaseModel):
    regulation_id: uuid.UUID
    name: str
    type: str
    status: str
    authority: str | None
    effective_date: date | None
    last_amended_date: date | None
    official_url: str | None
    source: str


class QueryHistoryItem(BaseModel):
    source: str
    query: str
    http_status: str | None
    latency_ms: int | None
    queried_at: datetime

    @classmethod
    def from_model(cls, row: RegulationQuery) -> "QueryHistoryItem":
        return cls(
            source=row.source,
            query=row.query,
            http_status=row.http_status,
            latency_ms=row.latency_ms,
            queried_at=row.queried_at,
        )


class AIInvocationItem(BaseModel):
    purpose: str
    model: str
    prompt_version: str
    confidence: float | None
    latency_ms: int | None
    created_at: datetime

    @classmethod
    def from_model(cls, row: AIInvocationLog) -> "AIInvocationItem":
        return cls(
            purpose=row.purpose,
            model=row.model,
            prompt_version=row.prompt_version,
            confidence=row.confidence,
            latency_ms=row.latency_ms,
            created_at=row.created_at,
        )


class ReferenceDetail(BaseModel):
    """前端「詳細資訊」面板。每一筆都可追溯到來源文件、頁碼、查詢紀錄與 AI 使用情形。"""

    reference_id: uuid.UUID
    raw_text: str
    normalized_name: str | None
    regulation_type: str
    article: str | None
    standard_number: str | None
    source_document: str
    page: int | None
    section_text: str | None
    #: 原始段落由 OCR 辨識而來，可能有錯字
    section_is_ocr: bool = False
    extraction_method: str
    extraction_confidence: float
    matched_regulation: MatchedRegulation | None
    match_confidence: float | None
    match_reasons: list[str]
    status: str
    is_tentative: bool
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    query_history: list[QueryHistoryItem]
    ai_invocations: list[AIInvocationItem]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: ReviewStatus
    review_note: str | None = None
