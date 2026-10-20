"""Read-only integrated checklist and exports; no rebuild or review mutations."""
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import DbSession
from app.reports.integrated_checklist import build_csv, build_pdf, build_xlsx
from app.schemas.integrated_checklist import IntegratedChecklistOut
from app.services.integrated_checklist_service import IntegratedChecklistService

router = APIRouter(prefix="/api/projects/{project_id}/integrated-checklist",
                   tags=["integrated-checklist"])
_EXPORTERS = {
    "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": (build_csv, "text/csv; charset=utf-8"),
    "pdf": (build_pdf, "application/pdf"),
}


@router.get("", response_model=IntegratedChecklistOut)
async def get_integrated_checklist(project_id: uuid.UUID, session: DbSession):
    return await IntegratedChecklistService(session).snapshot(project_id)


@router.get("/export")
async def export_integrated_checklist(
    project_id: uuid.UUID,
    session: DbSession,
    format: Literal["xlsx", "csv", "pdf"] = Query("xlsx"),
):
    report = await IntegratedChecklistService(session).snapshot(project_id)
    build, media_type = _EXPORTERS[format]
    content = await run_in_threadpool(build, report)
    filename = f"整合檢核-{project_id}.{format}"
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    })
