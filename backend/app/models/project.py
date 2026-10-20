"""專案、專案文件角色與工項。

專案是加在既有 documents 之上的一層，不取代它：同一份文件仍然走原本的
上傳→解析→抽取流程，專案只是記錄「這份文件在這個專案裡扮演什麼角色」。
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentRole
from app.models.base import Base, created_at_column, uuid_pk


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    drawing_revision: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    documents: Mapped[list["ProjectDocument"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    work_items: Mapped[list["WorkItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="WorkItem.order_index",
    )

    __table_args__ = (Index("ix_projects_tenant_id", "tenant_id"),)


class ProjectDocument(Base):
    """一份文件在一個專案裡的角色。同一份文件在同一個專案裡只能有一個角色。"""

    __tablename__ = "project_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentRole.OTHER)
    added_at: Mapped[datetime] = created_at_column()

    project: Mapped[Project] = relationship(back_populates="documents")

    __table_args__ = (
        UniqueConstraint("project_id", "document_id", name="uq_project_document"),
        Index("ix_project_documents_project", "project_id"),
    )


class WorkItem(Base):
    """專案的一個工作項目，來自標單的詳細價目表。"""

    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: 標單的階層項次，例如「壹.一.1.1.1」。品質計畫書用同一套，是精確的對接鍵。
    item_no: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    quantity: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: 10 碼計價代碼。前 5 碼是施工綱要規範章碼——不存解析結果，讀取時再查，
    #: 免得同步過綱要規範之後這裡變成過期資料。
    cost_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    order_index: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped[Project] = relationship(back_populates="work_items")

    __table_args__ = (
        Index("ix_work_items_project_order", "project_id", "order_index"),
        Index("ix_work_items_cost_code", "cost_code"),
    )

    @property
    def is_leaf(self) -> bool:
        """有單位的才是實際工項；「壹」「壹.一」這種是群組列。"""
        return bool(self.unit)
