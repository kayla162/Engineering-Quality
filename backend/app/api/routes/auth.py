"""本機帳號登入、登出與密碼管理 API。"""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import InvalidCredentialsError, LoginRateLimitError
from app.core.security import CurrentUser, require_auth_write_origin, require_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import ChangePasswordIn, LoginIn, SessionUserOut
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
    if not await throttle.reserve(payload.username, client_ip):
        raise LoginRateLimitError("登入嘗試次數過多，請稍後再試")

    service = AuthService(session)
    user = await service.authenticate(payload.username, payload.password)
    if user is None:
        raise InvalidCredentialsError("登入名稱或密碼不正確")

    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise InvalidCredentialsError("登入名稱或密碼不正確")
    raw_secret, _ = await service.create_session(user)
    await throttle.clear(payload.username, client_ip)
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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_current_user),
    __: None = Depends(require_auth_write_origin),
):
    raw_secret = request.cookies.get(settings.AUTH_SESSION_COOKIE)
    if raw_secret:
        await AuthService(session).revoke_session(raw_secret)
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
