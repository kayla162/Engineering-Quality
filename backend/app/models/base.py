"""SQLAlchemy 宣告式基底與共用欄位型別。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.types import JSON

#: PostgreSQL 用 JSONB（可索引），SQLite 用一般 JSON，兩邊程式碼相同
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_column():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def nullable_timestamp():
    return mapped_column(DateTime(timezone=True), nullable=True)
