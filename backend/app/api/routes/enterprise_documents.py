"""企業內部文件清單 API。

清單誰都看得到（覆核時要知道公司有哪些內部文件）；匯入會整份取代、影響之後所有
分析，所以限租戶管理員。範本檔讓使用者不必另外找格式。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import AuditServiceDep, CurrentUserDep, DbSession
from app.core.config import settings
from app.core.enums import AuditAction
from app.core.errors import FileTooLargeError, InvalidFileTypeError, NotFoundError
from app.core.security import CurrentUser, require_tenant_admin
from app.schemas.enterprise import EnterpriseDocumentListOut, EnterpriseDocumentOut
from app.services.enterprise_document_service import EnterpriseDocumentService, parse_workbook

router = APIRouter(prefix="/api/enterprise-documents", tags=["enterprise-documents"])

TEMPLATE_NAME = "企業內部文件清單範本.xlsx"


async def _list_out(service: EnterpriseDocumentService) -> EnterpriseDocumentListOut:
    rows = await service.list_documents()
    latest = max(rows, key=lambda row: row.imported_at, default=None)
    return EnterpriseDocumentListOut(
        total=len(rows),
        imported_at=latest.imported_at if latest else None,
        imported_by=latest.imported_by if latest else None,
        items=[EnterpriseDocumentOut.from_model(row) for row in rows],
    )


@router.get("", response_model=EnterpriseDocumentListOut)
async def list_enterprise_documents(session: DbSession, user: CurrentUserDep):
    return await _list_out(EnterpriseDocumentService(session, user.tenant_id))


@router.post("/import", response_model=EnterpriseDocumentListOut)
async def import_enterprise_documents(
    request: Request,
    session: DbSession,
    audit: AuditServiceDep,
    actor: CurrentUser = Depends(require_tenant_admin),
    file: UploadFile = File(...),
):
    """上傳 Excel 清單，整份取代這個租戶的企業內部文件。有任何一列錯就整份不收。"""
    content = await file.read()
    if not (file.filename or "").lower().endswith(".xlsx") or not content.startswith(b"PK"):
        raise InvalidFileTypeError("請上傳 .xlsx 格式的清單（可先下載範本）")
    if len(content) > settings.max_upload_bytes:
        raise FileTooLargeError(f"檔案大小超過上限 {settings.MAX_UPLOAD_SIZE_MB} MB")

    documents = parse_workbook(content)
    service = EnterpriseDocumentService(session, actor.tenant_id)
    count = await service.replace_all(documents, actor.username)
    await audit.record(
        AuditAction.ENTERPRISE_DOCUMENTS_IMPORTED,
        actor=actor,
        detail={"filename": file.filename, "total": count},
        request=request,
    )
    await session.commit()
    return await _list_out(service)


@router.get("/template")
async def download_template(user: CurrentUserDep):
    path = settings.DATA_DIR / "templates" / TEMPLATE_NAME
    if not path.exists():
        raise NotFoundError("找不到範本檔，請執行 python scripts/generate_enterprise_template.py")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(TEMPLATE_NAME)}"},
    )
