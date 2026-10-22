"""本機帳號、密碼與可撤銷工作階段的業務邏輯。"""

import hashlib
import secrets
import uuid
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import UserRole
from app.core.errors import (
    PasswordPolicyError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.models.base import utcnow
from app.models.session import AuthSession
from app.models.tenant import Tenant
from app.models.user import User

_password_hasher = PasswordHasher()
_dummy_password_hash = _password_hasher.hash(secrets.token_urlsafe(32))


def _is_username_uniqueness_violation(exc: IntegrityError) -> bool:
    # asyncpg may surface its constraint directly; psycopg exposes it via diag.
    for original in (exc.orig, getattr(exc.orig, "__cause__", None)):
        if original is None:
            continue
        constraint_name = getattr(original, "constraint_name", None) or getattr(
            getattr(original, "diag", None), "constraint_name", None
        )
        if constraint_name == "uq_users_username":
            return True
    # SQLite reports the constrained columns instead of a named constraint.
    message = str(exc.orig).lower()
    return "unique constraint failed: users.username" in message


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise PasswordPolicyError("密碼至少需要 12 個字元")
    if len(password) > 256:
        raise PasswordPolicyError("密碼不可超過 256 個字元")
    if not password.strip():
        raise PasswordPolicyError("密碼不可全為空白")


def hash_password(password: str) -> str:
    validate_password(password)
    return _password_hasher.hash(password)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def authenticate(self, username: str, password: str) -> User | None:
        normalized = normalize_username(username)
        user = await self.session.scalar(select(User).where(User.username == normalized))
        stored_hash = user.password_hash if user is not None else _dummy_password_hash
        try:
            password_matches = _password_hasher.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            password_matches = False

        if user is None or not password_matches or not user.is_active:
            return None

        tenant = await self.session.get(Tenant, user.tenant_id)
        if tenant is None or not tenant.is_active:
            return None
        return user

    async def create_session(self, user: User) -> tuple[str, AuthSession]:
        raw_secret = secrets.token_urlsafe(32)
        now = utcnow()
        session_row = AuthSession(
            user_id=user.id,
            secret_hash=hashlib.sha256(raw_secret.encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=now + timedelta(hours=settings.AUTH_SESSION_TTL_HOURS),
        )
        self.session.add(session_row)
        await self.session.flush()
        return raw_secret, session_row

    async def resolve_session(self, raw_secret: str) -> tuple[User, Tenant] | None:
        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        auth_session = await self.session.scalar(
            select(AuthSession).where(
                AuthSession.secret_hash == secret_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
        )
        if auth_session is None:
            return None
        user = await self.session.get(User, auth_session.user_id)
        if user is None or not user.is_active:
            auth_session.revoked_at = utcnow()
            return None
        tenant = await self.session.get(Tenant, user.tenant_id)
        if tenant is None or not tenant.is_active:
            auth_session.revoked_at = utcnow()
            return None
        return user, tenant

    async def revoke_session(self, raw_secret: str) -> None:
        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.secret_hash == secret_hash, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )

    async def change_password(
        self,
        user_id: uuid.UUID,
        old_password: str | None,
        new_password: str,
        *,
        must_change_password: bool,
    ) -> None:
        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            raise UserNotFoundError("找不到使用者")
        if not must_change_password:
            try:
                valid = _password_hasher.verify(user.password_hash, old_password or "")
            except (VerifyMismatchError, InvalidHashError):
                valid = False
            if not valid:
                raise PasswordPolicyError("目前密碼不正確")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.updated_at = utcnow()
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await self.session.flush()

    async def operator_reset_password(self, username: str, new_password: str) -> User:
        """由有資料庫操作權限的部署人員重設密碼，不啟用停用帳號。"""
        normalized = normalize_username(username)
        user = await self.session.scalar(
            select(User).where(User.username == normalized).with_for_update()
        )
        if user is None:
            raise UserNotFoundError("找不到使用者")

        user.password_hash = hash_password(new_password)
        user.must_change_password = True
        user.updated_at = utcnow()
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await self.session.flush()
        return user

    async def list_users(self, tenant_id: uuid.UUID) -> list[User]:
        result = await self.session.scalars(
            select(User).where(User.tenant_id == tenant_id).order_by(User.username)
        )
        return list(result)

    async def create_user(
        self,
        tenant_id: uuid.UUID,
        username: str,
        initial_password: str,
        role: UserRole = UserRole.MEMBER,
    ) -> User:
        normalized = normalize_username(username)
        if not normalized:
            raise PasswordPolicyError("登入名稱不可空白")
        if await self.session.scalar(select(User.id).where(User.username == normalized)):
            raise PasswordPolicyError("登入名稱已被使用")
        user = User(
            tenant_id=tenant_id,
            username=normalized,
            password_hash=hash_password(initial_password),
            role=role,
            is_active=True,
            must_change_password=True,
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # The preflight lookup improves the usual error; the unique DB
            # constraint remains the authority under concurrent requests.
            await self.session.rollback()
            if _is_username_uniqueness_violation(exc):
                raise UserAlreadyExistsError("登入名稱已被使用") from exc
            raise
        return user

    async def deactivate_user(
        self, tenant_id: uuid.UUID, actor_id: uuid.UUID, target_id: uuid.UUID
    ) -> User | None:
        tenant = await self.session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            return None
        user = await self.session.scalar(
            select(User).where(User.id == target_id, User.tenant_id == tenant_id)
        )
        if user is None or user.id == actor_id:
            return None
        if user.is_active and user.role == UserRole.TENANT_ADMIN:
            active_admins = await self.session.scalar(
                select(func.count(User.id)).where(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.TENANT_ADMIN,
                    User.is_active.is_(True),
                )
            )
            if (active_admins or 0) <= 1:
                raise PasswordPolicyError("不能停用租戶最後一位管理員")
        user.is_active = False
        user.updated_at = utcnow()
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await self.session.flush()
        return user

    async def reactivate_user(
        self, tenant_id: uuid.UUID, target_id: uuid.UUID, initial_password: str
    ) -> User | None:
        user = await self.session.scalar(
            select(User)
            .where(User.id == target_id, User.tenant_id == tenant_id)
            .with_for_update()
        )
        if user is None:
            return None
        if user.is_active:
            raise PasswordPolicyError("使用者帳號已啟用")

        user.password_hash = hash_password(initial_password)
        user.is_active = True
        user.must_change_password = True
        user.updated_at = utcnow()
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await self.session.flush()
        return user

    async def bootstrap_admin(
        self, tenant_name: str, username: str, password: str
    ) -> User:
        """在部署預設租戶建立第一位管理員；已有管理員時拒絕重複 bootstrap。"""
        normalized = normalize_username(username)
        if not normalized:
            raise PasswordPolicyError("登入名稱不可空白")
        if not tenant_name.strip():
            raise PasswordPolicyError("租戶名稱不可空白")
        if len(tenant_name.strip()) > 255:
            raise PasswordPolicyError("租戶名稱不可超過 255 個字元")
        if await self.session.scalar(select(User.id).where(User.username == normalized)):
            raise PasswordPolicyError("登入名稱已被使用")
        validate_password(password)

        default_id = uuid.UUID(settings.DEFAULT_TENANT_ID)
        tenant = await self.session.scalar(
            select(Tenant).where(Tenant.id == default_id).with_for_update()
        )
        if tenant is not None:
            active_admin_id = await self.session.scalar(
                select(User.id).where(
                    User.tenant_id == default_id,
                    User.role == UserRole.TENANT_ADMIN,
                    User.is_active.is_(True),
                )
            )
        else:
            active_admin_id = None

        if active_admin_id is not None:
            raise PasswordPolicyError("此部署已有有效管理員，請由管理員新增使用者")

        if tenant is None:
            tenant = Tenant(id=default_id, name=tenant_name.strip(), is_active=True)
            self.session.add(tenant)
        else:
            tenant.name = tenant_name.strip()
            tenant.is_active = True
        await self.session.flush()

        admin = User(
            tenant_id=tenant.id,
            username=normalized,
            password_hash=_password_hasher.hash(password),
            role=UserRole.TENANT_ADMIN,
            is_active=True,
            must_change_password=False,
        )
        self.session.add(admin)
        await self.session.flush()
        return admin
