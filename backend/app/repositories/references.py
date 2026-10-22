"""regulation_references 的資料存取。"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.reference import RegulationReference


class ReferenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_all(self, references: list[RegulationReference]) -> list[RegulationReference]:
        self.session.add_all(references)
        await self.session.flush()
        return references

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        """重新分析時清掉上一次的結果。"""
        await self.session.execute(
            delete(RegulationReference).where(RegulationReference.document_id == document_id)
        )
        await self.session.flush()

    async def get(
        self, reference_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> RegulationReference | None:
        result = await self.session.execute(
            select(RegulationReference)
            .join(Document, Document.id == RegulationReference.document_id)
            .where(RegulationReference.id == reference_id, Document.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_by_document(
        self,
        document_id: uuid.UUID,
        *,
        status: str | None = None,
        review_status: str | None = None,
        min_confidence: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[RegulationReference], int]:
        filters = [RegulationReference.document_id == document_id]
        if status:
            filters.append(RegulationReference.status == status)
        if review_status:
            filters.append(RegulationReference.review_status == review_status)
        if min_confidence is not None:
            filters.append(RegulationReference.match_confidence >= min_confidence)

        total = (
            await self.session.execute(
                select(func.count()).select_from(RegulationReference).where(*filters)
            )
        ).scalar_one()

        result = await self.session.execute(
            select(RegulationReference)
            .where(*filters)
            .order_by(RegulationReference.created_at, RegulationReference.raw_text)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def all_by_document(self, document_id: uuid.UUID) -> list[RegulationReference]:
        """報告與統計用，不分頁。"""
        result = await self.session.execute(
            select(RegulationReference)
            .where(RegulationReference.document_id == document_id)
            .order_by(RegulationReference.created_at, RegulationReference.raw_text)
        )
        return list(result.scalars().all())

    async def status_counts(self, document_id: uuid.UUID) -> dict[str, int]:
        result = await self.session.execute(
            select(RegulationReference.status, func.count())
            .where(RegulationReference.document_id == document_id)
            .group_by(RegulationReference.status)
        )
        return {status: count for status, count in result.all()}
