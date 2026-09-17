"""報告資料結構。

這是 ReportService 的輸出，也是 reports/ 下所有匯出器的唯一輸入。
匯出器不碰資料庫，只認這個結構，因此新增匯出格式很容易。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.reference import ReferenceSummary


class ReportRow(BaseModel):
    """報告中的一列，對應一筆法規引用。"""

    raw_text: str
    normalized_name: str | None
    regulation_type: str
    article: str | None
    page: int | None
    status: str
    status_label: str
    match_confidence: float | None
    matched_name: str | None
    authority: str | None
    last_amended_date: str | None
    official_url: str | None
    data_source: str | None
    extraction_method: str
    review_status: str
    reviewed_by: str | None
    match_reasons: str
    needs_attention: bool


class ReportData(BaseModel):
    document_id: uuid.UUID
    filename: str
    document_status: str
    generated_at: datetime
    total_references: int
    summary: ReferenceSummary
    rows: list[ReportRow] = Field(default_factory=list)
    #: 系統對這份報告的整體說明（可能由 LLM 潤飾，內容仍來自結構化結果）
    narrative: str | None = None
    #: 資料來源可信度提醒，一定會出現在報告上
    disclaimer: str
