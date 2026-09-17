"""文件中的法規引用（對應 docs/database.md 2.4）。

這是整個系統的核心產出：一筆 reference = 文件裡出現過的一個法規引用，
連同它是被哪一層抽取出來的、比對到哪一筆法規、目前狀態、以及有沒有被人工覆核過。
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RegulationStatus, ReviewStatus
from app.models.base import Base, created_at_column, nullable_timestamp, uuid_pk
from app.models.document import DocumentSection
from app.models.regulation import Regulation


class RegulationReference(Base):
    __tablename__ = "regulation_references"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_sections.id", ondelete="SET NULL"), nullable=True
    )
    regulation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regulations.id", ondelete="SET NULL"), nullable=True
    )

    # --- 抽取階段 ---
    raw_text: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    regulation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    article: Mapped[str | None] = mapped_column(String(128), nullable=True)
    standard_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    extraction_method: Mapped[str] = mapped_column(String(24), nullable=False)

    # --- 比對階段 ---
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 比對理由（人可讀的字串，一行一則），讓比對過程不是黑箱
    match_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RegulationStatus.UNKNOWN)

    # --- 人工覆核：與系統判斷是兩個獨立且都可追溯的狀態 ---
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ReviewStatus.UNREVIEWED
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = nullable_timestamp()
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    section: Mapped[DocumentSection | None] = relationship(lazy="selectin")
    regulation: Mapped[Regulation | None] = relationship(lazy="selectin")

    __table_args__ = (
        Index("ix_refs_document_id", "document_id"),
        Index("ix_refs_regulation_id", "regulation_id"),
        Index("ix_refs_status", "status"),
        Index("ix_refs_review_status", "review_status"),
    )

    @property
    def reason_list(self) -> list[str]:
        return [line for line in (self.match_reasons or "").split("\n") if line]
