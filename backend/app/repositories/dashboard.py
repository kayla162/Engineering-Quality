"""總覽統計的彙總查詢。全部是唯讀的 GROUP BY，資料來源就是既有的結構化表。

每個查詢都以租戶範圍收斂：引用透過文件的 tenant_id、法規異動透過自己的 tenant_id。
"""

import uuid

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    NEEDS_ATTENTION_STATUSES,
    ParseQuality,
    ReviewStatus,
)
from app.models.document import Document
from app.models.project import Project
from app.models.reference import RegulationReference
from app.models.regulation import Regulation, RegulationChange

#: 「需要處理」= 狀態需要人工介入，而且還沒有人覆核過
_NEEDS_ACTION = and_(
    RegulationReference.status.in_(NEEDS_ATTENTION_STATUSES),
    RegulationReference.review_status == ReviewStatus.UNREVIEWED,
)


class DashboardRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def document_status_counts(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Document.status, func.count())
            .where(Document.tenant_id == self.tenant_id)
            .group_by(Document.status)
        )
        return dict(rows.all())

    async def degraded_document_count(self) -> int:
        return await self._scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.tenant_id == self.tenant_id,
                Document.parse_quality == ParseQuality.DEGRADED,
            )
        )

    async def reference_counts(self, column) -> dict[str, int]:
        rows = await self.session.execute(
            select(column, func.count())
            .join(Document, Document.id == RegulationReference.document_id)
            .where(Document.tenant_id == self.tenant_id)
            .group_by(column)
        )
        return dict(rows.all())

    async def needs_action_count(self) -> int:
        return await self._scalar(
            select(func.count())
            .select_from(RegulationReference)
            .join(Document, Document.id == RegulationReference.document_id)
            .where(Document.tenant_id == self.tenant_id, _NEEDS_ACTION)
        )

    async def source_counts(self) -> dict[str, int]:
        """比對到的法規，資料來自哪個來源。沒比對到的不算（它們沒有來源）。"""
        rows = await self.session.execute(
            select(Regulation.source, func.count())
            .select_from(RegulationReference)
            .join(Document, Document.id == RegulationReference.document_id)
            .join(Regulation, Regulation.id == RegulationReference.regulation_id)
            .where(Document.tenant_id == self.tenant_id)
            .group_by(Regulation.source)
        )
        return dict(rows.all())

    async def top_regulations(self, limit: int) -> list:
        """被引用最多次的法規，附被幾份文件引用。"""
        references = func.count(RegulationReference.id).label("references")
        rows = await self.session.execute(
            select(
                Regulation.id,
                Regulation.name,
                Regulation.status,
                Regulation.source,
                references,
                func.count(distinct(RegulationReference.document_id)).label("documents"),
            )
            .select_from(RegulationReference)
            .join(Document, Document.id == RegulationReference.document_id)
            .join(Regulation, Regulation.id == RegulationReference.regulation_id)
            .where(Document.tenant_id == self.tenant_id)
            .group_by(Regulation.id, Regulation.name, Regulation.status, Regulation.source)
            .order_by(references.desc(), Regulation.name)
            .limit(limit)
        )
        return list(rows.all())

    async def documents_needing_action(self, limit: int) -> list:
        """還有待處理引用的文件，待處理最多的排前面。"""
        pending = func.sum(case((_NEEDS_ACTION, 1), else_=0)).label("needs_action")
        unreviewed = func.sum(
            case((RegulationReference.review_status == ReviewStatus.UNREVIEWED, 1), else_=0)
        ).label("unreviewed")
        rows = await self.session.execute(
            select(
                Document.id,
                Document.filename,
                Document.parse_quality,
                func.count(RegulationReference.id).label("references"),
                unreviewed,
                pending,
            )
            .join(RegulationReference, RegulationReference.document_id == Document.id)
            .where(Document.tenant_id == self.tenant_id)
            .group_by(Document.id, Document.filename, Document.parse_quality)
            .having(pending > 0)
            .order_by(pending.desc(), Document.filename)
            .limit(limit)
        )
        return list(rows.all())

    async def project_count(self) -> int:
        return await self._scalar(
            select(func.count()).select_from(Project).where(Project.tenant_id == self.tenant_id)
        )

    async def open_change_count(self) -> int:
        return await self._scalar(
            select(func.count())
            .select_from(RegulationChange)
            .where(
                RegulationChange.tenant_id == self.tenant_id,
                RegulationChange.acknowledged_at.is_(None),
            )
        )

    async def _scalar(self, stmt) -> int:
        return (await self.session.execute(stmt)).scalar_one() or 0
