"""documents / document_sections 的資料存取。不含業務判斷。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentSection


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def get(self, document_id: uuid.UUID, tenant_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, file_hash: str, tenant_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.file_hash == file_hash, Document.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def list_paged(
        self,
        tenant_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> tuple[list[Document], int]:
        query = select(Document).where(Document.tenant_id == tenant_id)
        count_query = select(func.count()).select_from(Document).where(
            Document.tenant_id == tenant_id
        )
        if status:
            query = query.where(Document.status == status)
            count_query = count_query.where(Document.status == status)

        total = (await self.session.execute(count_query)).scalar_one()
        query = (
            query.order_by(Document.uploaded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(query)).scalars().all()
        return list(rows), total

    async def set_status(self, document: Document, status: str) -> None:
        document.status = status
        await self.session.flush()

    # --- sections ---

    async def replace_sections(
        self, document_id: uuid.UUID, sections: list[DocumentSection]
    ) -> list[DocumentSection]:
        """重新分析時，先刪掉舊的段落再寫入新的，避免重複累積。"""
        existing = await self.list_sections(document_id)
        for section in existing:
            await self.session.delete(section)
        await self.session.flush()

        self.session.add_all(sections)
        await self.session.flush()
        return sections

    async def list_sections(self, document_id: uuid.UUID) -> list[DocumentSection]:
        result = await self.session.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.order_index)
        )
        return list(result.scalars().all())
