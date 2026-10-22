"""文件上傳與查詢的業務邏輯。"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import DocumentStatus
from app.core.errors import DocumentNotFoundError, DuplicateFileError
from app.core.logging import log_context
from app.core.security import build_storage_path, file_hash, sanitize_filename, validate_upload
from app.models.document import Document
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
        self.documents = DocumentRepository(session)
        self.jobs = JobRepository(session)

    async def upload(self, filename: str, content: bytes) -> Document:
        """驗證 -> 去重 -> 落檔 -> 建立 documents 紀錄。不做解析（解析在背景任務）。"""
        ext = validate_upload(filename, content)
        digest = file_hash(content)

        existing = await self.documents.get_by_hash(digest, self.tenant_id)
        if existing is not None:
            raise DuplicateFileError(
                f"這個檔案已經上傳過（{existing.filename}）",
                details={"document_id": str(existing.id)},
            )

        path = build_storage_path(ext)
        path.write_bytes(content)

        document = Document(
            filename=sanitize_filename(filename),
            file_type=ext.lstrip("."),
            storage_path=str(path),
            file_hash=digest,
            status=DocumentStatus.UPLOADED,
            tenant_id=self.tenant_id,
        )
        await self.documents.create(document)
        await self.session.commit()
        logger.info(
            "文件上傳完成",
            extra=log_context(document_id=str(document.id), filename=document.filename),
        )
        return document

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(document_id, self.tenant_id)
        if document is None:
            raise DocumentNotFoundError("找不到指定的文件")
        return document

    async def list_documents(self, page: int, page_size: int, status: str | None):
        return await self.documents.list_paged(
            tenant_id=self.tenant_id, page=page, page_size=page_size, status=status
        )

    async def latest_job(self, document_id: uuid.UUID):
        await self.get(document_id)
        return await self.jobs.get_latest_for_document(document_id, self.tenant_id)
