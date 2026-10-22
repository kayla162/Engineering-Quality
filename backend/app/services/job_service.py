"""分析任務的業務邏輯：建立 job、丟進背景執行、查詢進度。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import JobNotFoundError
from app.jobs.base import JobRunner
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.services.document_service import DocumentService


class JobService:
    def __init__(
        self, session: AsyncSession, runner: JobRunner, tenant_id: uuid.UUID | None = None
    ):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
        self.jobs = JobRepository(session)
        self.documents = DocumentService(session, self.tenant_id)
        self.runner = runner

    async def start_analysis(self, document_id: uuid.UUID) -> Job:
        """建立一筆新的 job 並排進背景。可重複呼叫（重新分析），不覆蓋歷史紀錄。"""
        document = await self.documents.get(document_id)
        job = await self.jobs.create(document.id)
        await self.session.commit()

        await self.runner.enqueue(job.id, document.id)
        return job

    async def get(self, job_id: uuid.UUID) -> Job:
        job = await self.jobs.get(job_id, self.tenant_id)
        if job is None:
            raise JobNotFoundError("找不到指定的分析任務")
        return job
