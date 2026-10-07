"""spec_chapters / work_item_bases 的資料存取。不含業務判斷。"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import SpecChapter, WorkItemBasis
from app.models.project import WorkItem


class ChecklistRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_chapters(
        self, document_id: uuid.UUID, chapters: list[SpecChapter]
    ) -> list[SpecChapter]:
        """重建一份規範書的章節索引。重跑取代，不累加。

        只清這一份文件的索引：同一份規範書可能掛在好幾個專案，別份文件的索引不能動。
        """
        await self.session.execute(
            delete(SpecChapter).where(SpecChapter.document_id == document_id)
        )
        self.session.add_all(chapters)
        await self.session.flush()
        return chapters

    async def chapters_by_document(self, document_id: uuid.UUID) -> list[SpecChapter]:
        """依規範書裡的先後順序（頁碼）回傳，不靠資料庫碰巧的排列。"""
        result = await self.session.execute(
            select(SpecChapter)
            .where(SpecChapter.document_id == document_id)
            .order_by(SpecChapter.first_page)
        )
        return list(result.scalars().all())

    async def replace_bases(
        self, work_item_ids: list[uuid.UUID], bases: list[WorkItemBasis]
    ) -> list[WorkItemBasis]:
        """重建一批工項的依據。重跑取代，不累加。只清這批工項的，別的專案不能動。"""
        if work_item_ids:
            await self.session.execute(
                delete(WorkItemBasis).where(WorkItemBasis.work_item_id.in_(work_item_ids))
            )
        self.session.add_all(bases)
        await self.session.flush()
        return bases

    async def bases_by_project(
        self, project_id: uuid.UUID
    ) -> dict[uuid.UUID, list[WorkItemBasis]]:
        """專案所有工項的依據，依工項分組。沒有依據的工項不會出現在結果裡。

        每個工項的依據依建立先後（created_at）排，同一時刻建立的再依 id 排，所以同一份
        資料不管查幾次、用哪種資料庫，順序都一樣。SQL 沒有 ORDER BY 就不保證順序：
        SQLite 碰巧依寫入順序給，PostgreSQL 會隨查詢計畫與資料表狀態而變。

        限制：沒有位置欄位，所以「建立先後」只有在時間戳不同時才等於 build() 寫入的
        先後；同一時刻建立的以 id 打破平手，順序固定，但不一定是寫入的先後。
        """
        result = await self.session.execute(
            select(WorkItemBasis)
            .join(WorkItem, WorkItem.id == WorkItemBasis.work_item_id)
            .where(WorkItem.project_id == project_id)
            .order_by(WorkItemBasis.created_at, WorkItemBasis.id)
        )
        grouped: dict[uuid.UUID, list[WorkItemBasis]] = {}
        for basis in result.scalars().all():
            grouped.setdefault(basis.work_item_id, []).append(basis)
        return grouped
