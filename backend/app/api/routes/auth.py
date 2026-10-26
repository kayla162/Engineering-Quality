"""本機帳號登入、登出與密碼管理 API。"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.enums import AuditAction
from app.core.errors import InvalidCredentialsError, LoginRateLimitError
from app.core.security import CurrentUser, require_auth_write_origin, require_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import ChangePasswordIn, LoginIn, SessionUserOut
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.login_throttle_service import LoginThrottleService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _session_user(user: User, tenant: Tenant) -> SessionUserOut:
    return SessionUserOut(
        user_id=user.id,
        username=user.username,
        role=user.role,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=SessionUserOut, dependencies=[Depends(require_auth_write_origin)])
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    throttle = LoginThrottleService(session)
    service = AuthService(session)
    if not await throttle.reserve(payload.username, client_ip):
        await _record_failed_login(session, service, payload.username, request, "rate_limited")
        raise LoginRateLimitError("登入嘗試次數過多，請稍後再試")

    user = await service.authenticate(payload.username, payload.password)
    tenant = await session.get(Tenant, user.tenant_id) if user is not None else None
    if user is None or tenant is None:
        await _record_failed_login(session, service, payload.username, request, "invalid_credentials")
        raise InvalidCredentialsError("登入名稱或密碼不正確")

    raw_secret, _ = await service.create_session(user)
    await throttle.clear(payload.username, client_ip)
    await AuditService(session).record(
        AuditAction.LOGIN,
        tenant_id=user.tenant_id,
        user_id=user.id,
        username=user.username,
        request=request,
    )
    await session.commit()
    response.set_cookie(
        key=settings.AUTH_SESSION_COOKIE,
        value=raw_secret,
        max_age=settings.AUTH_SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return _session_user(user, tenant)


async def _record_failed_login(
    session: AsyncSession, service: AuthService, username: str, request: Request, reason: str
) -> None:
    """登入失敗要在丟出錯誤之前就 commit，否則紀錄會跟著 rollback。

    帳號存在就歸到它的租戶，讓租戶管理員看得到有人在試自己成員的密碼；
    帳號不存在時 tenant_id 為 NULL，只留在資料庫裡。
    """
    known = await service.find_user(username)
    await AuditService(session).record(
        AuditAction.LOGIN_FAILED,
        tenant_id=known.tenant_id if known else None,
        user_id=known.id if known else None,
        username=username,
        detail={"reason": reason},
        request=request,
    )
    await session.commit()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    actor: CurrentUser = Depends(require_current_user),
    __: None = Depends(require_auth_write_origin),
):
    raw_secret = request.cookies.get(settings.AUTH_SESSION_COOKIE)
    if raw_secret:
        await AuthService(session).revoke_session(raw_secret)
        await AuditService(session).record(AuditAction.LOGOUT, actor=actor, request=request)
        await session.commit()
    response.delete_cookie(
        settings.AUTH_SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=SessionUserOut)
async def me(
    user: CurrentUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db),
):
    user_row = await session.get(User, user.id)
    tenant = await session.get(Tenant, user.tenant_id)
    if user_row is None or tenant is None:
        raise InvalidCredentialsError("登入狀態已失效，請重新登入")
    return _session_user(user_row, tenant)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_auth_write_origin)],
)
async def change_password(
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_current_user),
    session: AsyncSession = Depends(get_db),
):
    await AuthService(session).change_password(
        user.id,
        payload.old_password,
        payload.new_password,
        must_change_password=user.must_change_password,
    )
    await AuditService(session).record(AuditAction.PASSWORD_CHANGED, actor=user, request=request)
    await session.commit()
    response.delete_cookie(
        settings.AUTH_SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
