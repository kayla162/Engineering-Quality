"""專案編排：掛文件、從標單建工項、連到施工綱要規範章節。"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import DocumentRole
from app.core.errors import AppError, DocumentNotFoundError, ProjectNotFoundError
from app.core.logging import log_context
from app.models.project import Project, ProjectDocument, WorkItem
from app.repositories.documents import DocumentRepository
from app.repositories.projects import ProjectRepository
from app.sources.pcces_source import PccesSource
from app.workitems import read_boq

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpecChapter:
    code: str
    name: str


class ProjectService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
        self.projects = ProjectRepository(session)
        self.documents = DocumentRepository(session)
        self._pcces = PccesSource()

    async def create_project(self, name: str) -> Project:
        project = await self.projects.create(name, self.tenant_id)
        await self.session.commit()
        return project

    async def attach_document(
        self, project_id: uuid.UUID, document_id: uuid.UUID, role: DocumentRole
    ) -> ProjectDocument:
        await self._require_project(project_id)
        if await self.documents.get(document_id, self.tenant_id) is None:
            raise DocumentNotFoundError("找不到指定的文件")
        if await self.projects.get_link(project_id, document_id) is not None:
            raise AppError("這份文件已經掛在這個專案裡了，要換角色請先移除")
        link = await self.projects.add_document(project_id, document_id, role)
        await self.session.commit()
        return link

    async def build_work_items(self, project_id: uuid.UUID) -> list[WorkItem]:
        """從專案的標單重建工項清單。

        只收有單位的明細列——「壹」「壹.一」這種群組列是金額小計，不是工作項目。
        """
        await self._require_project(project_id)

        links = await self.projects.documents_by_role(project_id, DocumentRole.BOQ)
        if not links:
            raise AppError("這個專案還沒有掛標單，沒有工項來源")

        document = await self.documents.get(links[0].document_id, self.tenant_id)
        if document is None:
            raise AppError("標單文件不存在，可能已被刪除")

        rows = [row for row in read_boq(Path(document.storage_path)) if row.is_leaf]
        items = [
            WorkItem(
                project_id=project_id,
                item_no=row.item_no,
                name=row.name,
                unit=row.unit,
                quantity=row.quantity,
                cost_code=row.cost_code,
                order_index=index,
            )
            for index, row in enumerate(rows)
        ]
        logger.info(
            "從標單建立工項",
            extra=log_context(project_id=str(project_id), work_items=len(items)),
        )
        result = await self.projects.replace_work_items(project_id, items)
        await self.session.commit()
        return result

    async def list_projects(self) -> list[Project]:
        return await self.projects.list_all(self.tenant_id)

    async def work_items(self, project_id: uuid.UUID) -> list[WorkItem]:
        await self._require_project(project_id)
        return await self.projects.work_items(project_id)

    async def spec_chapter_for(self, cost_code: str | None) -> SpecChapter | None:
        """計價代碼前 5 碼 = 施工綱要規範章碼（實測：有代碼的工項裡 85% 對得到）。

        對不到就回 None——各機關自訂的專業工項不在共通性工項目錄裡，
        硬湊一個章節出來會是「有信心的錯」。
        """
        if not cost_code or len(cost_code) < 5:
            return None
        detail = await self._pcces.get_detail(f"PCCES-{cost_code[:5]}")
        if detail is None:
            return None
        return SpecChapter(code=cost_code[:5], name=detail.name)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self.projects.get(project_id, self.tenant_id)
        if project is None:
            raise ProjectNotFoundError("找不到指定的專案")
        return project
