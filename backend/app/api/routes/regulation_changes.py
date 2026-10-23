"""法規異動監控 API。

檢查會重新查詢外部來源並寫入法規主檔，影響整個租戶，所以限租戶管理員；
看異動和確認「已處理」是每個成員都會做的事。排程執行用
`scripts/check_regulation_changes.py`。
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import AuditServiceDep, CurrentUserDep, DbSession
from app.core.enums import AuditAction
from app.core.security import CurrentUser, require_tenant_admin
from app.schemas.regulation_change import (
    ChangeCheckOut,
    RegulationChangeListOut,
    RegulationChangeOut,
    SkippedRegulation,
)
from app.services.regulation_change_service import RegulationChangeService

router = APIRouter(prefix="/api/regulation-changes", tags=["regulation-changes"])


async def _out(service: RegulationChangeService, change_id: uuid.UUID) -> RegulationChangeOut:
    change = await service.get(change_id)
    return RegulationChangeOut.from_model(
        change, await service.affected_documents(change.regulation_id)
    )


@router.get("", response_model=RegulationChangeListOut)
async def list_changes(
    session: DbSession,
    user: CurrentUserDep,
    include_acknowledged: bool = Query(False, description="是否包含已確認的異動"),
):
    service = RegulationChangeService(session, user.tenant_id)
    changes = await service.list_changes(include_acknowledged=include_acknowledged)
    return RegulationChangeListOut(
        total=len(changes), items=[await _out(service, change.id) for change in changes]
    )


@router.post("/check", response_model=ChangeCheckOut)
async def check_changes(
    request: Request,
    session: DbSession,
    audit: AuditServiceDep,
    actor: CurrentUser = Depends(require_tenant_admin),
):
    service = RegulationChangeService(session, actor.tenant_id)
    summary = await service.check()
    new_ids = [change.id for change in summary.new_changes]
    await audit.record(
        AuditAction.REGULATION_CHANGES_CHECKED,
        actor=actor,
        detail={
            "checked": summary.checked,
            "changed": summary.changed,
            "skipped": len(summary.skipped),
        },
        request=request,
    )
    await session.commit()
    return ChangeCheckOut(
        checked=summary.checked,
        changed=summary.changed,
        skipped=[SkippedRegulation(**row) for row in summary.skipped],
        new_changes=[await _out(service, change_id) for change_id in new_ids],
    )


@router.post("/{change_id}/acknowledge", response_model=RegulationChangeOut)
async def acknowledge_change(
    change_id: uuid.UUID,
    request: Request,
    session: DbSession,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    service = RegulationChangeService(session, user.tenant_id)
    change = await service.acknowledge(change_id, user.username)
    await audit.record(
        AuditAction.REGULATION_CHANGE_ACKNOWLEDGED,
        actor=user,
        resource_type="regulation",
        resource_id=change.regulation_id,
        detail={"change_id": str(change_id), "changes": change.changes},
        request=request,
    )
    await session.commit()
    return await _out(service, change_id)
