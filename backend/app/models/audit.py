"""稽核紀錄：外部來源查詢與 AI 呼叫（對應 docs/database.md 2.8 / 2.9）。

刻意分成兩張表：
  - regulation_queries：外部法規資料來源（sources/ adapter）的查詢紀錄
  - ai_invocation_log ：LLM 呼叫紀錄

未來要分別稽核「AI 有沒有亂猜」與「官方來源有沒有查到」時，才拆得開。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
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
