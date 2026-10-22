"""租戶管理員可用的同租戶帳號管理 API。"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import CurrentUser, require_tenant_admin
from app.core.errors import PermissionDeniedError, UserNotFoundError
from app.schemas.user import UserCreateIn, UserListOut, UserOut, UserUpdateIn
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
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
):
    user = await AuthService(session).create_member(
        actor.tenant_id, payload.username, payload.initial_password
    )
    await session.commit()
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateIn,
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
):
    if payload.is_active:
        raise PermissionDeniedError("管理員只能停用帳號；重新啟用請重新建立帳號")
    user = await AuthService(session).deactivate_user(actor.tenant_id, actor.id, user_id)
    if user is None:
        raise UserNotFoundError("找不到使用者")
    await session.commit()
    return _user_out(user)
