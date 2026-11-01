"""企業內部文件清單 API 契約。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enterprise import EnterpriseDocument
from app.services.enterprise_document_service import STATUS_LABELS


class EnterpriseDocumentOut(BaseModel):
    document_id: uuid.UUID
    doc_number: str
    name: str
    doc_type: str
    revision: str
    effective_date: date
    last_revised_date: date | None
    #: RegulationStatus（ACTIVE / AMENDED / REPEALED）
    status: str
    #: 範本上的原文（現行 / 已修訂 / 作廢）
    status_label: str
    replaced_by: str | None
    owner: str | None
    aliases: list[str]
    note: str | None

    @classmethod
    def from_model(cls, row: EnterpriseDocument) -> "EnterpriseDocumentOut":
        return cls(
            document_id=row.id,
            doc_number=row.doc_number,
            name=row.name,
            doc_type=row.doc_type,
            revision=row.revision,
            effective_date=row.effective_date,
            last_revised_date=row.last_revised_date,
            status=row.status,
            status_label=STATUS_LABELS.get(row.status, row.status),
            replaced_by=row.replaced_by,
            owner=row.owner,
            aliases=list(row.aliases or []),
            note=row.note,
        )


class EnterpriseDocumentListOut(BaseModel):
    total: int
    #: 最近一次匯入的時間與使用者；沒匯入過是 None
    imported_at: datetime | None
    imported_by: str | None
    items: list[EnterpriseDocumentOut]
