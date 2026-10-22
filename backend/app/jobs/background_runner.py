"""用 FastAPI BackgroundTasks 執行分析。

背景工作不能沿用 request 的 DB session（request 結束時會關閉），
所以這裡自己開一個新的 session。
"""

import logging
import uuid

from fastapi import BackgroundTasks

from app.core.db import get_session_factory
from app.core.logging import log_context
from app.jobs.base import JobRunner
from app.models.document import Document
from app.models.job import Job
from app.repositories.jobs import JobRepository
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def run_analysis(job_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """背景任務的進入點。例外在這裡吞掉，失敗狀態已經寫進 jobs 表。"""
    from app.services.analysis_service import AnalysisService

    async with get_session_factory()() as session:
        try:
            document = await session.get(Document, document_id)
            if document is None:
                return
            await AnalysisService(session, document.tenant_id).run(document_id, job_id)
        except Exception:
            logger.exception("背景分析任務結束於失敗", extra=log_context(job_id=str(job_id)))


class BackgroundTasksJobRunner(JobRunner):
    def __init__(self, background_tasks: BackgroundTasks):
        self._background_tasks = background_tasks

    async def enqueue(self, job_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self._background_tasks.add_task(run_analysis, job_id, document_id)

    async def get_status(self, job_id: uuid.UUID) -> str | None:
        async with get_session_factory()() as session:
            job = await session.scalar(select(Job).where(Job.id == job_id))
            return job.status if job else None
