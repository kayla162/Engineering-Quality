"""企業內部文件清單（Phase 3 企業知識庫）。

每個租戶一份，由品保／文管單位提供的文件管制一覽表匯入。只存目錄（編號、名稱、
版次、狀態），不存全文。匯入是「整份取代」：清單上沒有的文件就是不存在了，
法規異動監控會把它記成「來源已查不到」。
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonColumn, created_at_column, uuid_pk


class EnterpriseDocument(Base):
    __tablename__ = "enterprise_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    doc_number: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 範本的「類型」原文（品質手冊、程序書…），顯示用
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_revised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: RegulationStatus：現行 ACTIVE / 已修訂 AMENDED / 作廢 REPEALED
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    replaced_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    aliases: Mapped[Any] = mapped_column(JsonColumn, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imported_at: Mapped[datetime] = created_at_column()
    imported_by: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "doc_number", name="uq_enterprise_documents_number"),
        Index("ix_enterprise_documents_tenant", "tenant_id"),
    )
