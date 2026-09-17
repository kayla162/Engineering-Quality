"""jobs 的資料存取。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.job import Job


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, document_id: uuid.UUID) -> Job:
        job = Job(document_id=document_id)
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    async def get_latest_for_document(self, document_id: uuid.UUID) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(Job.document_id == document_id)
            .order_by(Job.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_progress(
        self, job: Job, *, status: str, step: str | None = None, progress: int | None = None
    ) -> Job:
        job.status = status
        if step is not None:
            job.current_step = step
        if progress is not None:
            job.progress = progress
        await self.session.flush()
        return job

    async def finish(self, job: Job, *, status: str, error_message: str | None = None) -> Job:
        job.status = status
        job.error_message = error_message
        job.finished_at = utcnow()
        if error_message is None:
            job.progress = 100
        await self.session.flush()
        return job
