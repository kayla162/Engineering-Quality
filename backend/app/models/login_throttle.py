"""跨 worker 共用的登入限流鎖與短期嘗試紀錄。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow, uuid_pk


class LoginThrottleKey(Base):
    __tablename__ = "auth_login_throttle_keys"

    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (Index("ix_auth_login_throttle_keys_last_seen", "last_seen_at"),)


class LoginAttempt(Base):
    __tablename__ = "auth_login_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    identity_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("auth_login_throttle_keys.identity_hash", ondelete="CASCADE"),
        nullable=False,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_auth_login_attempts_identity_time", "identity_hash", "attempted_at"),
        Index("ix_auth_login_attempts_attempted_at", "attempted_at"),
    )
