"""稽核紀錄：外部來源查詢、AI 呼叫與使用者操作（對應 docs/database.md 2.8 / 2.9 / 2.15）。

刻意分成三張表：
  - regulation_queries：外部法規資料來源（sources/ adapter）的查詢紀錄
  - ai_invocation_log ：LLM 呼叫紀錄
  - audit_log         ：誰在何時對什麼資源做了什麼操作

未來要分別稽核「AI 有沒有亂猜」「官方來源有沒有查到」「誰改了覆核結果」時，才拆得開。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonColumn, created_at_column, uuid_pk


class RegulationQuery(Base):
    """一次對外部法規來源的查詢，含原始回應，供除錯與稽核。"""

    __tablename__ = "regulation_queries"

    id: Mapped[uuid.UUID] = uuid_pk()
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regulation_references.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    result: Mapped[Any | None] = mapped_column(JsonColumn, nullable=True)
    raw_response: Mapped[Any | None] = mapped_column(JsonColumn, nullable=True)
    http_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queried_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_queries_reference_id", "reference_id"),)


class AIInvocationLog(Base):
    """每一次 LLM 呼叫都要留紀錄，任何一筆判斷都能回溯到模型與 prompt 版本。"""

    __tablename__ = "ai_invocation_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regulation_references.id", ondelete="SET NULL"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_json: Mapped[Any | None] = mapped_column(JsonColumn, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_ai_log_job_id", "job_id"),
        Index("ix_ai_log_reference_id", "reference_id"),
    )


class AuditLog(Base):
    """一次使用者操作。只記成功的寫入、匯出與登入事件；查詢不記（量太大，也不改變任何東西）。

    `username` 另存一份：帳號停用或刪除後，紀錄仍要看得出是誰做的。
    `tenant_id` 可為 NULL：用不存在的帳號登入失敗時，無從得知是哪個租戶。
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[Any | None] = mapped_column(JsonColumn, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_log_action", "action"),
    )
