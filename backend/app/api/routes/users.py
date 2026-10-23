"""租戶管理員可用的同租戶帳號管理 API。"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.enums import AuditAction
from app.core.security import CurrentUser, require_tenant_admin
from app.core.errors import UserNotFoundError
from app.schemas.user import UserCreateIn, UserListOut, UserOut, UserUpdateIn
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_out(user) -> UserOut:
    return UserOut(
        user_id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


@router.get("", response_model=UserListOut)
async def list_users(
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
):
    users = await AuthService(session).list_users(actor.tenant_id)
    return UserListOut(total=len(users), items=[_user_out(user) for user in users])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateIn,
    request: Request,
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
):
    user = await AuthService(session).create_user(
        actor.tenant_id, payload.username, payload.initial_password, payload.role
    )
    await AuditService(session).record(
        AuditAction.USER_CREATED,
        actor=actor,
        resource_type="user",
        resource_id=user.id,
        detail={"username": user.username, "role": user.role},
        request=request,
    )
    await session.commit()
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateIn,
    request: Request,
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
):
    if payload.is_active:
        user = await AuthService(session).reactivate_user(
            actor.tenant_id, user_id, payload.initial_password or ""
        )
    else:
        user = await AuthService(session).deactivate_user(actor.tenant_id, actor.id, user_id)
    if user is None:
        raise UserNotFoundError("找不到使用者")
    await AuditService(session).record(
        AuditAction.USER_REACTIVATED if payload.is_active else AuditAction.USER_DEACTIVATED,
        actor=actor,
        resource_type="user",
        resource_id=user.id,
        detail={"username": user.username},
        request=request,
    )
    await session.commit()
    return _user_out(user)
