"""分析任務（對應 docs/database.md 2.3）。

一份文件可以有多筆 job：重新分析時新增一筆，不覆蓋歷史紀錄。
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import JobStatus
from app.models.base import Base, created_at_column, nullable_timestamp, uuid_pk


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.PENDING)
    current_step: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = nullable_timestamp()

    __table_args__ = (Index("ix_jobs_document_id", "document_id"),)
