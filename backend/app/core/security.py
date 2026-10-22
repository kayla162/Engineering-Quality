"""上傳檔案驗證、登入 session 解析與瀏覽器寫入請求防護。"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import (
    AuthenticationRequiredError,
    FileTooLargeError,
    InvalidFileTypeError,
    PermissionDeniedError,
)

#: 副檔名 -> 允許的 magic number 前綴。用來擋「改副檔名」的偽造檔案。
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".docx": (b"PK\x03\x04",),   # DOCX 實際上是 zip
    ".pdf": (b"%PDF",),
    ".txt": (),                   # 純文字沒有 magic number，不檢查
}

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff.\- ]+")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    role: str
    must_change_password: bool


def enforce_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise PermissionDeniedError("請求來源未通過驗證")
    parsed = urlsplit(origin)
    normalized = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if normalized not in settings.cors_origins:
        raise PermissionDeniedError("請求來源未通過驗證")


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


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_db)
) -> CurrentUser | None:
    """從資料庫 session cookie 解析目前使用者；失效 cookie 視同未登入。"""
    raw_secret = request.cookies.get(settings.AUTH_SESSION_COOKIE)
    if not raw_secret:
        return None
    from app.services.auth_service import AuthService

    resolved = await AuthService(session).resolve_session(raw_secret)
    if resolved is None:
        return None
    user, tenant = resolved
    return CurrentUser(
        id=user.id,
        tenant_id=tenant.id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


async def require_current_user(
    user: CurrentUser | None = Depends(get_current_user),
) -> CurrentUser:
    if user is None:
        raise AuthenticationRequiredError("請先登入")
    return user


async def require_business_user(
    request: Request,
    user: CurrentUser = Depends(require_current_user),
) -> CurrentUser:
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        enforce_origin(request)
    if user.must_change_password and request.url.path not in {
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/change-password",
    }:
        raise PermissionDeniedError("請先變更初始密碼")
    return user


async def require_tenant_admin(
    request: Request,
    user: CurrentUser = Depends(require_business_user),
) -> CurrentUser:
    if user.role != "tenant_admin":
        raise PermissionDeniedError("只有租戶管理員可以管理使用者")
    return user


async def require_auth_write_origin(request: Request) -> None:
    enforce_origin(request)
