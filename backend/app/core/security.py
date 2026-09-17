"""上傳檔案驗證與（預留的）使用者驗證。

MVP 為單機使用，沒有登入機制。未來要加權限時，只需要實作
`get_current_user`，router 端的相依注入點不用改。
"""

import hashlib
import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.errors import FileTooLargeError, InvalidFileTypeError

#: 副檔名 -> 允許的 magic number 前綴。用來擋「改副檔名」的偽造檔案。
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".docx": (b"PK\x03\x04",),   # DOCX 實際上是 zip
    ".pdf": (b"%PDF",),
    ".txt": (),                   # 純文字沒有 magic number，不檢查
}

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff.\- ]+")


def validate_upload(filename: str, content: bytes) -> str:
    """驗證副檔名、大小與檔案內容，回傳正規化後的副檔名（含點）。"""
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise InvalidFileTypeError(
            f"不支援的檔案型別「{ext or '無副檔名'}」，僅接受 "
            f"{', '.join(settings.allowed_extensions)}"
        )

    if len(content) > settings.max_upload_bytes:
        raise FileTooLargeError(f"檔案大小超過上限 {settings.MAX_UPLOAD_SIZE_MB} MB")

    if not content:
        raise InvalidFileTypeError("檔案是空的")

    prefixes = _MAGIC_PREFIXES.get(ext, ())
    if prefixes and not any(content.startswith(p) for p in prefixes):
        raise InvalidFileTypeError(f"檔案內容與副檔名 {ext} 不符，可能是偽造的副檔名")

    return ext


def file_hash(content: bytes) -> str:
    """SHA-256，用於去重與完整性驗證。"""
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(filename: str) -> str:
    """只用於顯示；實際儲存路徑一律使用隨機檔名，避免 path traversal。"""
    return _SAFE_NAME.sub("_", Path(filename).name)[:255] or "unnamed"


def build_storage_path(ext: str) -> Path:
    """產生與原始檔名無關的儲存路徑。"""
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return settings.UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"


async def get_current_user() -> str | None:
    """預留的使用者相依注入點。MVP 永遠回傳 None（未登入）。"""
    return None
