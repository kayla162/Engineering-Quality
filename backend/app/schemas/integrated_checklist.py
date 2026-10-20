"""Additive read-only contract; drawing and regulatory conclusions stay separate."""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import CheckResult
from app.schemas.checklist import BasisOut, ChapterOut

CONTRACT_NOTE = (
    "契約文件的適用版本與優先順序，須依本案契約由人員確認。"
    "本表未判定契約優先順序；規範依據 OK 不代表工程全面合規。"
)


class IntegratedDrawingOut(BaseModel):
    id: uuid.UUID
    sheet_id: uuid.UUID
    document_id: uuid.UUID
    filename: str | None = None
    page: int
    number: str | None = None
    title: str | None = None
    evidence: str
    sheet_evidence: str
    review_status: str
    review_note: str
    warning: str | None = None


class MethodCandidateOut(BaseModel):
    text: str
    source: str
    evidence: str
    drawing_item_id: uuid.UUID | None = None


class IntegratedMethodOut(BaseModel):
    # Neither value constitutes a human selection.
    status: Literal["unspecified", "pending"] = "unspecified"
    candidates: list[MethodCandidateOut] = Field(default_factory=list)


class IntegratedItemOut(BaseModel):
    key: str
    work_item_id: uuid.UUID | None = None
    item_no: str | None = None
    name: str
    source_status: Literal["both", "needs_confirmation", "drawing_only", "drawing_candidate"]
    basis_result: CheckResult | None = None
    chapter_code: str | None = None
    chapter: ChapterOut | None = None
    bases: list[BasisOut] = Field(default_factory=list)
    drawings: list[IntegratedDrawingOut] = Field(default_factory=list)
    method: IntegratedMethodOut = Field(default_factory=IntegratedMethodOut)


class IntegratedSummaryOut(BaseModel):
    total: int = 0
    work_items: int = 0
    matched: int = 0
    needs_confirmation: int = 0
    drawing_candidates: int = 0
    drawing_only: int = 0
    rejected_items: int = 0
    pending_items: int = 0
    basis_ok: int = 0
    basis_spec_not_included: int = 0
    basis_needs_confirmation: int = 0


class IntegratedChecklistOut(BaseModel):
    project_id: uuid.UUID
    # Existing drawing revision only; this read-only endpoint is no write token.
    revision: int
    total: int
    summary: IntegratedSummaryOut
    warnings: list[str]
    contract_note: str = CONTRACT_NOTE
    items: list[IntegratedItemOut]
