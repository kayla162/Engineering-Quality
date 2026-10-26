"""法規異動監控 API 契約。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.regulation import RegulationChange
from app.services.regulation_change_service import AffectedDocument


class AffectedDocumentOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    references: int

    @classmethod
    def from_result(cls, row: AffectedDocument) -> "AffectedDocumentOut":
        return cls(document_id=row.document_id, filename=row.filename, references=row.references)


class RegulationChangeOut(BaseModel):
    change_id: uuid.UUID
    regulation_id: uuid.UUID
    regulation_name: str
    #: 法規主檔目前的狀態（已套用這次異動）
    current_status: str
    source: str
    #: {"status": {"old": "ACTIVE", "new": "REPEALED"}}；來源查不到時是 presence: missing
    changes: dict[str, dict[str, Any]]
    detected_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    #: 引用了這部法規的文件。這些文件的引用狀態仍是當時比對的結果，需重新分析才會更新
    affected_documents: list[AffectedDocumentOut]

    @classmethod
    def from_model(
        cls, change: RegulationChange, affected: list[AffectedDocument]
    ) -> "RegulationChangeOut":
        return cls(
            change_id=change.id,
            regulation_id=change.regulation_id,
            regulation_name=change.regulation.name,
            current_status=change.regulation.status,
            source=change.source,
            changes=change.changes,
            detected_at=change.detected_at,
            acknowledged_at=change.acknowledged_at,
            acknowledged_by=change.acknowledged_by,
            affected_documents=[AffectedDocumentOut.from_result(row) for row in affected],
        )


class RegulationChangeListOut(BaseModel):
    total: int
    items: list[RegulationChangeOut]


class SkippedRegulation(BaseModel):
    regulation_id: uuid.UUID
    name: str
    reason: str


class ChangeCheckOut(BaseModel):
    checked: int
    changed: int
    skipped: list[SkippedRegulation]
    new_changes: list[RegulationChangeOut]
