"""總覽統計（Phase 3 Dashboard）。

只彙總既有資料，不另存統計表：數字永遠和清單一致，不會有「總覽說 3 筆、
清單裡是 5 筆」的落差。資料量變大到 GROUP BY 跑不動時再考慮快取。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus
from app.models.reference import RegulationReference
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import (
    DashboardOut,
    DocumentNeedingAction,
    DocumentStats,
    ReferenceStats,
    TopRegulation,
)

TOP_LIMIT = 10


class DashboardService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.repo = DashboardRepository(session, tenant_id)

    async def build(self) -> DashboardOut:
        document_counts = await self.repo.document_status_counts()
        by_status = await self.repo.reference_counts(RegulationReference.status)
        return DashboardOut(
            documents=DocumentStats(
                total=sum(document_counts.values()),
                by_status=document_counts,
                degraded=await self.repo.degraded_document_count(),
                failed=document_counts.get(DocumentStatus.FAILED, 0),
            ),
            references=ReferenceStats(
                total=sum(by_status.values()),
                by_status=by_status,
                by_review=await self.repo.reference_counts(RegulationReference.review_status),
                needs_action=await self.repo.needs_action_count(),
                by_source=await self.repo.source_counts(),
            ),
            projects=await self.repo.project_count(),
            open_regulation_changes=await self.repo.open_change_count(),
            top_regulations=[
                TopRegulation(
                    regulation_id=row.id,
                    name=row.name,
                    status=row.status,
                    source=row.source,
                    references=row.references,
                    documents=row.documents,
                )
                for row in await self.repo.top_regulations(TOP_LIMIT)
            ],
            documents_needing_action=[
                DocumentNeedingAction(
                    document_id=row.id,
                    filename=row.filename,
                    parse_quality=row.parse_quality,
                    references=row.references,
                    unreviewed=row.unreviewed,
                    needs_action=row.needs_action,
                )
                for row in await self.repo.documents_needing_action(TOP_LIMIT)
            ],
        )
