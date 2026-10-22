"""法規主檔、別名、版本（對應 docs/database.md 2.5 / 2.6 / 2.7）。"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RegulationStatus
from app.models.base import Base, created_at_column, utcnow, uuid_pk


class Regulation(Base):
    """一筆已知的法規/標準。

    status 只能來自官方來源查詢結果或人工建立，LLM 不得直接寫入（見 docs/architecture.md 第 5 節）。
    """

    __tablename__ = "regulations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RegulationStatus.UNKNOWN)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_amended_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    official_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 最後一次確認資料的來源 adapter 名稱，或 manual（人工建立）
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    aliases: Mapped[list["RegulationAlias"]] = relationship(
        back_populates="regulation", cascade="all, delete-orphan", lazy="selectin"
    )
    versions: Mapped[list["RegulationVersion"]] = relationship(
        back_populates="regulation", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_regulations_normalized_name", "normalized_name"),
        Index("ix_regulations_type", "type"),
        Index("ix_regulations_status", "status"),
    )


class RegulationAlias(Base):
    """法規的別名 / 簡稱 / 舊名，是 Normalization Engine 的主要資料來源。"""

    __tablename__ = "regulation_aliases"

    id: Mapped[uuid.UUID] = uuid_pk()
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(512), nullable=False)

    regulation: Mapped[Regulation] = relationship(back_populates="aliases")

    __table_args__ = (UniqueConstraint("regulation_id", "alias", name="uq_regulation_alias"),)


class RegulationVersion(Base):
    __tablename__ = "regulation_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amended_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 條文內容雜湊，用於偵測條文是否變動（Phase 3 法規異動監控會用到）
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    regulation: Mapped[Regulation] = relationship(back_populates="versions")
