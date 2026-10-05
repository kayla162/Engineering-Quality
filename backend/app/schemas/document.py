"""文件相關的 request / response schema。"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import Document
from app.models.job import Job


class JobBrief(BaseModel):
    job_id: uuid.UUID
    status: str
    progress: int
    finished_at: datetime | None = None

    @classmethod
    def from_model(cls, job: Job) -> "JobBrief":
        return cls(
            job_id=job.id, status=job.status, progress=job.progress, finished_at=job.finished_at
        )


class DocumentOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    file_type: str
    status: str
    #: 解析品質。DEGRADED 表示有一部分內容讀不到（圖說的尺寸標註壓在點陣圖裡是
    #: 典型案例），結果不可盡信。note 只有 DEGRADED 時才有值。
    parse_quality: str
    parse_quality_note: str | None = None
    uploaded_at: datetime
    latest_job: JobBrief | None = None

    @classmethod
    def from_model(cls, document: Document, latest_job: Job | None = None) -> "DocumentOut":
        return cls(
            document_id=document.id,
            filename=document.filename,
            file_type=document.file_type,
            status=document.status,
            parse_quality=document.parse_quality,
            parse_quality_note=document.parse_quality_note,
            uploaded_at=document.uploaded_at,
            latest_job=JobBrief.from_model(latest_job) if latest_job else None,
        )


class DocumentListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentOut]
