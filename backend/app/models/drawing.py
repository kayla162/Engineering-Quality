import uuid

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class DrawingSheet(Base):
    __tablename__ = "drawing_sheets"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page: Mapped[int]
    number: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))
    evidence: Mapped[str] = mapped_column(Text)
    warning: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("project_id", "document_id", "page", name="uq_drawing_page"),)


class DrawingItem(Base):
    __tablename__ = "drawing_items"
    id: Mapped[uuid.UUID] = uuid_pk()
    sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drawing_sheets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    evidence: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    work_item_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Any BOQ rebuild invalidates a review, including drawing-only decisions.
    review_fingerprint: Mapped[str | None] = mapped_column(String(64))
    review_note: Mapped[str] = mapped_column(Text, default="")
