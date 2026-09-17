"""分析任務進度查詢。前端靠這支 API 輪詢。"""

import uuid

from fastapi import APIRouter

from app.api.deps import JobServiceDep
from app.schemas.job import JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, service: JobServiceDep):
    return JobOut.from_model(await service.get(job_id))
