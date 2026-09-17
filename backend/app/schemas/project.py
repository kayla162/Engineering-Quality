"""專案與工項的 schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.enums import DocumentRole
from app.models.project import Project, ProjectDocument, WorkItem


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """`min_length` 擋不掉「  」——長度是 2 但去掉空白就沒東西了。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("專案名稱不可以只有空白")
        return stripped


class ProjectOut(BaseModel):
    project_id: uuid.UUID
    name: str
    created_at: datetime

    @classmethod
    def from_model(cls, project: Project) -> "ProjectOut":
        return cls(project_id=project.id, name=project.name, created_at=project.created_at)


class ProjectListOut(BaseModel):
    total: int
    items: list[ProjectOut]


class AttachDocumentRequest(BaseModel):
    document_id: uuid.UUID
    role: DocumentRole


class ProjectDocumentOut(BaseModel):
    document_id: uuid.UUID
    role: str
    added_at: datetime

    @classmethod
    def from_model(cls, link: ProjectDocument) -> "ProjectDocumentOut":
        return cls(document_id=link.document_id, role=link.role, added_at=link.added_at)


class SpecChapterOut(BaseModel):
    code: str
    name: str


class WorkItemOut(BaseModel):
    work_item_id: uuid.UUID
    item_no: str
    name: str
    unit: str
    quantity: str
    cost_code: str | None
    #: 由計價代碼前 5 碼查出來的施工綱要規範章節。對不到就是 None，不硬湊。
    #: 實測：一半的工項有代碼，其中 85% 對得到章節（全部工項的 43%）。
    spec_chapter: SpecChapterOut | None = None

    @classmethod
    def from_model(cls, item: WorkItem, chapter=None) -> "WorkItemOut":
        return cls(
            work_item_id=item.id,
            item_no=item.item_no,
            name=item.name,
            unit=item.unit,
            quantity=item.quantity,
            cost_code=item.cost_code,
            spec_chapter=(
                SpecChapterOut(code=chapter.code, name=chapter.name) if chapter else None
            ),
        )


class WorkItemListOut(BaseModel):
    total: int
    #: 有對到綱要規範章節的筆數。實測真實標單 438/1028 ≈ 43%。
    with_spec_chapter: int
    items: list[WorkItemOut]
