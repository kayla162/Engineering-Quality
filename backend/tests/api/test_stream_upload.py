import io

import pytest
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.errors import DuplicateFileError, FileTooLargeError
from app.services.document_service import DocumentService


async def test_stream_upload_bounded_reads_and_duplicate_cleanup(db_session):
    class BoundedUpload(UploadFile):
        async def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            return await super().read(size)
    service = DocumentService(db_session)
    content = b"%PDF-" + b"x" * (1024 * 1024 + 7)
    first = await service.upload_stream(BoundedUpload(io.BytesIO(content), filename="large.pdf"))
    from pathlib import Path
    assert Path(first.storage_path).read_bytes() == content
    before = set(settings.UPLOAD_DIR.iterdir())
    with pytest.raises(DuplicateFileError):
        await service.upload_stream(BoundedUpload(io.BytesIO(content), filename="again.pdf"))
    assert set(settings.UPLOAD_DIR.iterdir()) == before


async def test_stream_oversize_leaves_no_file(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    before = set(settings.UPLOAD_DIR.iterdir())
    with pytest.raises(FileTooLargeError):
        await DocumentService(db_session).upload_stream(
            UploadFile(io.BytesIO(b"%PDF" + b"x" * 1024 * 1024), filename="large.pdf")
        )
    assert set(settings.UPLOAD_DIR.iterdir()) == before
