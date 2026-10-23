"""報告摘要與檔案匯出。"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.api.deps import AuditServiceDep, CurrentUserDep, ReportServiceDep
from app.core.enums import AuditAction
from app.reports import EXPORTERS, export
from app.schemas.report import ReportData

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{document_id}", response_model=ReportData)
async def get_report(
    document_id: uuid.UUID,
    service: ReportServiceDep,
    narrative: bool = Query(False, description="是否請 AI 產生摘要說明文字"),
):
    return await service.build(document_id, with_narrative=narrative)


@router.get("/{document_id}/export")
async def export_report(
    document_id: uuid.UUID,
    request: Request,
    service: ReportServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
    format: str = Query("xlsx", description=f"可用格式：{', '.join(EXPORTERS)}"),
):
    report = await service.build(document_id)
    content, filename, media_type = export(report, format)
    # 匯出是讀取，但報告會離開系統，所以要記
    await audit.record(
        AuditAction.REPORT_EXPORTED,
        actor=user,
        resource_type="document",
        resource_id=document_id,
        detail={"format": format, "filename": filename},
        request=request,
        commit=True,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            # 中文檔名用 RFC 5987 編碼，瀏覽器才不會亂碼
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
