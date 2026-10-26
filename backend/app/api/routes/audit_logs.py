"""租戶管理員查詢同租戶操作紀錄的 API。紀錄只能看，不能改也不能刪。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.enums import AuditAction
from app.core.security import CurrentUser, require_tenant_admin
from app.schemas.audit import AuditLogListOut, AuditLogOut
from app.services.audit_service import AuditService

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogListOut)
async def list_audit_logs(
    actor: CurrentUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db),
    action: AuditAction | None = Query(None),
    username: str | None = Query(None, max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await AuditService(session).list_for_tenant(
        actor.tenant_id, action=action, username=username, page=page, page_size=page_size
    )
    return AuditLogListOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[AuditLogOut.from_model(row) for row in rows],
    )
