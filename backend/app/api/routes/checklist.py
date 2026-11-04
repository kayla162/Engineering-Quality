"""工項檢核表 API。

檢核結果不存在資料庫裡，每次查詢時由工項、章節索引與依據算出來
（docs/superpowers/specs/2026-10-05-工項檢核表-階段3-design.md 第 4 節）。

建與讀是兩條路，刻意分開：POST 重建（重讀整份規範書、對每個工項重新抽取），
GET 只讀已經建好的。GET 不能順手重建——重建很貴，而且有副作用的 GET 會讓人
無法回答「為什麼數字變了」。
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuditServiceDep, ChecklistServiceDep, CurrentUserDep
from app.core.enums import AuditAction
from app.schemas.checklist import ChecklistOut, QualityStandardOut
from app.specs.quality_standard import to_xlsx

router = APIRouter(prefix="/api/projects", tags=["checklist"])


@router.post(
    "/{project_id}/checklist",
    response_model=ChecklistOut,
    status_code=status.HTTP_201_CREATED,
)
async def build_checklist(
    project_id: uuid.UUID,
    request: Request,
    service: ChecklistServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    """重建依據並回傳檢核表。重跑取代，不累加。

    沒掛施工規範不會報錯：工項都在，只是依據欄空白（和沒掛標單是 400 刻意不對稱）。
    """
    checklist = ChecklistOut.from_checklist(await service.build(project_id))
    await audit.record(
        AuditAction.CHECKLIST_BUILT,
        actor=user,
        resource_type="project",
        resource_id=project_id,
        request=request,
        commit=True,
    )
    return checklist


@router.get("/{project_id}/checklist", response_model=ChecklistOut)
async def get_checklist(project_id: uuid.UUID, service: ChecklistServiceDep):
    """只讀已經建好的依據。要重建請用 POST。"""
    return ChecklistOut.from_checklist(await service.checklist(project_id))


@router.get("/{project_id}/quality-standards/{chapter_code}", response_model=QualityStandardOut)
async def get_quality_standard(project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep):
    """品質管理標準表初稿（橘框表單）：本案施工規範那一章擷取出的管理項目與管理標準。"""
    return QualityStandardOut.from_draft(await service.quality_standard_draft(project_id, chapter_code))


@router.get("/{project_id}/quality-standards/{chapter_code}/export")
async def export_quality_standard(project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep):
    draft = await service.quality_standard_draft(project_id, chapter_code)
    filename = f"{draft.title}.xlsx"
    return Response(
        content=to_xlsx(draft),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
