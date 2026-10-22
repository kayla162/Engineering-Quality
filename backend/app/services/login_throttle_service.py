"""以資料庫協調多 worker 共用的登入嘗試限流。"""

import hashlib
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import utcnow
from app.models.login_throttle import LoginAttempt, LoginThrottleKey
from app.services.auth_service import normalize_username


# Keep opportunistic expiry cleanup from making a single login delete an
# unbounded number of rows. Repeated logins will drain the remaining backlog.
CLEANUP_BATCH_SIZE = 500


class LoginThrottleService:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _identity_hash(self, username: str, client_ip: str) -> str:
        identity = f"{normalize_username(username)}\0{client_ip}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _insert_for_dialect(self):
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            return postgresql_insert
        if dialect_name == "sqlite":
            return sqlite_insert
        raise RuntimeError(f"登入限流不支援資料庫類型：{dialect_name}")

    async def _lock_identity(self, identity_hash: str, now):
        insert = self._insert_for_dialect()
        statement = insert(LoginThrottleKey).values(
            identity_hash=identity_hash,
            last_seen_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[LoginThrottleKey.identity_hash],
            set_={"last_seen_at": now},
        )
        await self.session.execute(statement)
        key = await self.session.scalar(
            select(LoginThrottleKey)
            .where(LoginThrottleKey.identity_hash == identity_hash)
            .with_for_update()
        )
        if key is None:
            raise RuntimeError("無法建立登入限流識別資料")
        key.last_seen_at = now
        return key

    async def reserve(self, username: str, client_ip: str) -> bool:
        """短暫鎖定同一組帳號/IP，計數後預留一次登入嘗試並提交。"""
        now = utcnow()
        cutoff = now - timedelta(seconds=settings.AUTH_LOGIN_WINDOW_SECONDS)
        identity_hash = self._identity_hash(username, client_ip)

        # Remove a bounded slice of expired state on each request; repeated
        # logins drain any larger cleanup backlog without one oversized delete.
        expired_attempt_ids = (
            select(LoginAttempt.id)
            .where(LoginAttempt.attempted_at < cutoff)
            .order_by(LoginAttempt.attempted_at)
            .limit(CLEANUP_BATCH_SIZE)
        )
        await self.session.execute(
            delete(LoginAttempt).where(LoginAttempt.id.in_(expired_attempt_ids))
        )
        stale_key_hashes = (
            select(LoginThrottleKey.identity_hash)
            .where(LoginThrottleKey.last_seen_at < cutoff)
            .order_by(LoginThrottleKey.last_seen_at)
            .limit(CLEANUP_BATCH_SIZE)
        )
        await self.session.execute(
            delete(LoginThrottleKey).where(
                LoginThrottleKey.identity_hash.in_(stale_key_hashes),
                LoginThrottleKey.last_seen_at < cutoff,
            )
        )

        key = await self._lock_identity(identity_hash, now)
        count = await self.session.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.identity_hash == identity_hash,
                LoginAttempt.attempted_at >= cutoff,
            )
        )
        if (count or 0) >= settings.AUTH_MAX_LOGIN_ATTEMPTS:
            await self.session.commit()
            return False

        self.session.add(LoginAttempt(identity_hash=identity_hash, attempted_at=now))
        key.last_seen_at = now
        # Commit before password verification so concurrent workers observe the
        # reservation and no identity lock is held during Argon2 work.
        await self.session.commit()
        return True

    async def clear(self, username: str, client_ip: str) -> None:
        """Clear prior failures on successful login; caller commits with session creation."""
        now = utcnow()
        identity_hash = self._identity_hash(username, client_ip)
        await self._lock_identity(identity_hash, now)
        await self.session.execute(
            delete(LoginAttempt).where(LoginAttempt.identity_hash == identity_hash)
        )
