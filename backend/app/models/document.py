"""文件與文件段落（對應 docs/database.md 2.1 / 2.2）。"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ContentType, DocumentStatus
from app.models.base import Base, created_at_column, uuid_pk


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # docx / pdf / txt
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.UPLOADED
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    uploaded_at: Mapped[datetime] = created_at_column()

    sections: Mapped[list["DocumentSection"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentSection.order_index"
    )

    __table_args__ = (Index("ix_documents_tenant_id", "tenant_id"),)


class DocumentSection(Base):
    """解析後的一個段落／標題／表格儲存格，保留頁碼與原始順序。"""

    __tablename__ = "document_sections"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContentType.PARAGRAPH
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[Document] = relationship(back_populates="sections")

    __table_args__ = (Index("ix_document_sections_doc_order", "document_id", "order_index"),)
