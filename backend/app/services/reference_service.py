"""法規引用清單、詳細資料與人工覆核的業務邏輯。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config import settings
from app.core.enums import ReviewStatus
from app.core.errors import DocumentNotFoundError, ReferenceNotFoundError
from app.models.base import utcnow
from app.models.reference import RegulationReference
from app.repositories.audit import AuditRepository
from app.repositories.documents import DocumentRepository
from app.repositories.references import ReferenceRepository
from app.schemas.reference import (
    AIInvocationItem,
    MatchedRegulation,
    QueryHistoryItem,
    ReferenceDetail,
    ReferenceListItem,
    ReferenceListOut,
    ReferenceSummary,
)


def is_tentative(reference: RegulationReference) -> bool:
    """信心分數未達自動採信門檻 -> 前端顯示「疑似」。"""
    return (
        reference.match_confidence is not None
        and 0 < reference.match_confidence < settings.MATCH_AUTO_THRESHOLD
    )


class ReferenceService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
        self.references = ReferenceRepository(session)
        self.documents = DocumentRepository(session)
        self.audit = AuditRepository(session)

    async def list_for_document(
        self,
        document_id: uuid.UUID,
        *,
        status: str | None = None,
        review_status: str | None = None,
        min_confidence: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ReferenceListOut:
        await self._require_document(document_id)
        rows, total = await self.references.list_by_document(
            document_id,
            status=status,
            review_status=review_status,
            min_confidence=min_confidence,
            page=page,
            page_size=page_size,
        )
        counts = await self.references.status_counts(document_id)
        return ReferenceListOut(
            total=total,
            page=page,
            page_size=page_size,
            summary=ReferenceSummary.from_counts(counts),
            items=[ReferenceListItem.from_model(row, is_tentative(row)) for row in rows],
        )

    async def get(self, reference_id: uuid.UUID) -> RegulationReference:
        reference = await self.references.get(reference_id, self.tenant_id)
        if reference is None:
            raise ReferenceNotFoundError("找不到指定的法規引用")
        return reference

    async def get_detail(self, reference_id: uuid.UUID) -> ReferenceDetail:
        reference = await self.get(reference_id)
        document = await self.documents.get(reference.document_id, self.tenant_id)
        queries = await self.audit.queries_for_reference(reference_id)
        ai_calls = await self.audit.ai_calls_for_reference(reference_id)

        matched = None
        if reference.regulation is not None:
            regulation = reference.regulation
            matched = MatchedRegulation(
                regulation_id=regulation.id,
                name=regulation.name,
                type=regulation.type,
                status=regulation.status,
                authority=regulation.authority,
                effective_date=regulation.effective_date,
                last_amended_date=regulation.last_amended_date,
                official_url=regulation.official_url,
                source=regulation.source,
            )

        return ReferenceDetail(
            reference_id=reference.id,
            raw_text=reference.raw_text,
            normalized_name=reference.normalized_name,
            regulation_type=reference.regulation_type,
            article=reference.article,
            standard_number=reference.standard_number,
            source_document=document.filename if document else "",
            page=reference.section.page if reference.section else None,
            section_text=reference.section.content if reference.section else None,
            section_is_ocr=reference.section.is_ocr if reference.section else False,
            extraction_method=reference.extraction_method,
            extraction_confidence=reference.extraction_confidence,
            matched_regulation=matched,
            match_confidence=reference.match_confidence,
            match_reasons=reference.reason_list,
            status=reference.status,
            is_tentative=is_tentative(reference),
            review_status=reference.review_status,
            reviewed_by=reference.reviewed_by,
            reviewed_at=reference.reviewed_at,
            review_note=reference.review_note,
            query_history=[QueryHistoryItem.from_model(q) for q in queries],
            ai_invocations=[AIInvocationItem.from_model(a) for a in ai_calls],
        )

    async def review(
        self,
        reference_id: uuid.UUID,
        review_status: ReviewStatus,
        reviewed_by: str,
        review_note: str | None = None,
    ) -> ReferenceDetail:
        """人工覆核。只改覆核欄位，不會動到系統判斷出來的 status，兩者各自獨立可追溯。"""
        reference = await self.get(reference_id)
        reference.review_status = review_status
        reference.reviewed_by = reviewed_by
        reference.review_note = review_note
        reference.reviewed_at = utcnow()
        await self.session.commit()
        return await self.get_detail(reference_id)

    async def _require_document(self, document_id: uuid.UUID) -> None:
        if await self.documents.get(document_id, self.tenant_id) is None:
            raise DocumentNotFoundError("找不到指定的文件")
