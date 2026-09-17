"""分析任務的 response schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.job import Job


class JobCreatedOut(BaseModel):
    job_id: uuid.UUID
    status: str


class JobOut(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: str
    current_step: str | None
    progress: int
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None

    @classmethod
    def from_model(cls, job: Job) -> "JobOut":
        return cls(
            job_id=job.id,
            document_id=job.document_id,
            status=job.status,
            current_step=job.current_step,
            progress=job.progress,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_message=job.error_message,
        )
