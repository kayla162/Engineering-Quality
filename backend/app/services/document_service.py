"""文件上傳與查詢的業務邏輯。"""

import logging
import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import DocumentStatus
from app.core.errors import DocumentNotFoundError, DuplicateFileError
from app.core.errors import FileTooLargeError
from app.core.logging import log_context
from app.core.security import build_storage_path, file_hash, sanitize_filename, validate_upload
from app.models.document import Document
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.documents = DocumentRepository(session)
        self.jobs = JobRepository(session)

    async def upload_stream(self, upload) -> Document:
        """分段寫入及雜湊，大型圖說不一次讀進記憶體。"""
        filename = upload.filename or "unnamed"
        first = await upload.read(1024 * 1024)
        ext = validate_upload(filename, first)
        path = build_storage_path(ext)
        digest = hashlib.sha256()
        total = 0
        try:
            with path.open("wb") as output:
                chunk = first
                while chunk:
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise FileTooLargeError(f"檔案大小超過上限 {settings.MAX_UPLOAD_SIZE_MB} MB")
                    output.write(chunk)
                    digest.update(chunk)
                    chunk = await upload.read(1024 * 1024)
            existing = await self.documents.get_by_hash(digest.hexdigest())
            if existing:
                raise DuplicateFileError(
                    f"這個檔案已經上傳過（{existing.filename}）",
                    details={"document_id": str(existing.id)},
                )
            document = Document(filename=sanitize_filename(filename),
                                file_type=ext.lstrip("."), storage_path=str(path),
                                file_hash=digest.hexdigest(), status=DocumentStatus.UPLOADED,
                                tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID))
            await self.documents.create(document)
            await self.session.commit()
            return document
        except BaseException:
            path.unlink(missing_ok=True)
            await self.session.rollback()
            raise

    async def upload(self, filename: str, content: bytes) -> Document:
        """驗證 -> 去重 -> 落檔 -> 建立 documents 紀錄。不做解析（解析在背景任務）。"""
        ext = validate_upload(filename, content)
        digest = file_hash(content)

        existing = await self.documents.get_by_hash(digest)
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
            tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID),
        )
        await self.documents.create(document)
        await self.session.commit()
        logger.info(
            "文件上傳完成",
            extra=log_context(document_id=str(document.id), filename=document.filename),
        )
        return document

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError("找不到指定的文件")
        return document

    async def list_documents(self, page: int, page_size: int, status: str | None):
        return await self.documents.list_paged(page=page, page_size=page_size, status=status)

    async def latest_job(self, document_id: uuid.UUID):
        return await self.jobs.get_latest_for_document(document_id)
