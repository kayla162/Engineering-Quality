"""projects / project_documents / work_items 的資料存取。不含業務判斷。"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectDocument, WorkItem


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, name: str, tenant_id: uuid.UUID | None = None) -> Project:
        project = Project(name=name, tenant_id=tenant_id)
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def list_all(self, limit: int = 100) -> list[Project]:
        result = await self.session.execute(
            select(Project).order_by(Project.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def add_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID, role: str
    ) -> ProjectDocument:
        link = ProjectDocument(project_id=project_id, document_id=document_id, role=role)
        self.session.add(link)
        await self.session.flush()
        return link

    async def get_link(
        self, project_id: uuid.UUID, document_id: uuid.UUID
    ) -> ProjectDocument | None:
        result = await self.session.execute(
            select(ProjectDocument).where(
                ProjectDocument.project_id == project_id,
                ProjectDocument.document_id == document_id,
            )
        )
        return result.scalar_one_or_none()

    async def documents_by_role(
        self, project_id: uuid.UUID, role: str
    ) -> list[ProjectDocument]:
        """專案裡扮演某個角色的文件，依掛上去的先後（added_at）排，最早的在最前面。

        呼叫端取第一筆當「這個角色的那份文件」（標單、施工規範書）。SQL 沒有 ORDER BY 就不保證
        順序：SQLite 碰巧依寫入順序給，PostgreSQL 會隨查詢計畫與資料表狀態而變——同一個角色
        掛了兩份文件時，這次建工項或檢核表用甲、下次用乙。理由和
        `ChecklistRepository.bases_by_project` 相同。

        同一時刻掛上去的再依 id 排，所以順序固定；但那種情況下不一定是掛上去的先後。
        """
        result = await self.session.execute(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id, ProjectDocument.role == role)
            .order_by(ProjectDocument.added_at, ProjectDocument.id)
        )
        return list(result.scalars().all())

    async def replace_work_items(
        self, project_id: uuid.UUID, items: list[WorkItem]
    ) -> list[WorkItem]:
        """重建工項清單。重跑標單時要取代而不是累加。"""
        await self.session.execute(delete(WorkItem).where(WorkItem.project_id == project_id))
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def work_items(self, project_id: uuid.UUID) -> list[WorkItem]:
        result = await self.session.execute(
            select(WorkItem)
            .where(WorkItem.project_id == project_id)
            .order_by(WorkItem.order_index)
        )
        return list(result.scalars().all())
