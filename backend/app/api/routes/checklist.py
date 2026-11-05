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
from app.core.errors import NotFoundError
from app.schemas.checklist import ChecklistOut, CrossRuleReminderOut, QualityStandardOut
from app.specs import demo_fill
from app.specs.derived_forms import self_inspection, self_inspection_xlsx, supervision_standard, supervision_xlsx
from app.specs.function_test import function_test_xlsx
from app.specs.method_statement import method_statement_docx
from app.specs.plan_assembly import quality_plan_docx, supervision_plan_docx
from app.specs.plan_review import plan_review_xlsx
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
async def get_quality_standard(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    """品質管理標準表初稿（橘框表單）：本案施工規範那一章擷取出的管理項目與管理標準。"""
    return QualityStandardOut.from_draft(_standard(await service.quality_standard_draft(project_id, chapter_code), demo))


@router.get("/{project_id}/quality-standards/{chapter_code}/export")
async def export_quality_standard(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    draft = _standard(await service.quality_standard_draft(project_id, chapter_code), demo)
    return _xlsx(to_xlsx(draft), draft.title)


@router.get("/{project_id}/quality-standards/{chapter_code}/self-inspection/export")
async def export_self_inspection(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    """承攬廠商的施工自主檢查表初稿，由同一章的品質管理標準表初稿衍生。"""
    form = self_inspection(_standard(await service.quality_standard_draft(project_id, chapter_code), demo))
    return _xlsx(self_inspection_xlsx(form), form.title)


@router.get("/{project_id}/quality-standards/{chapter_code}/supervision/export")
async def export_supervision(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    """監造單位的施工抽查標準表與材料抽驗標準表初稿，由同一章的品質管理標準表初稿衍生。"""
    form = supervision_standard(_standard(await service.quality_standard_draft(project_id, chapter_code), demo))
    return _xlsx(supervision_xlsx(form), form.title)


@router.get("/{project_id}/quality-standards/{chapter_code}/method-statement/export")
async def export_method_statement(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    """施工要領與施工流程圖初稿（Word）：規範第3節的施工方法、標單裡這一章的材料、★檢驗停留點。"""
    statement = await service.method_statement_draft(project_id, chapter_code)
    statement = demo_fill.fill_method(statement) if demo else statement
    return Response(
        content=method_statement_docx(statement),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(statement.title + '.docx')}"},
    )


@router.get("/{project_id}/quality-standards/{chapter_code}/function-test/export")
async def export_function_test(
    project_id: uuid.UUID, chapter_code: str, service: ChecklistServiceDep, demo: bool = False
):
    """機電章的設備功能運轉檢測標準表（承攬廠商）與測試抽驗標準表（監造）初稿，同一份 Excel 兩張工作表。"""
    draft = await service.function_test_draft(project_id, chapter_code)
    draft = demo_fill.fill_function_test(draft) if demo else draft
    return _xlsx(function_test_xlsx(draft), draft.title)


@router.get("/{project_id}/quality-plan-review/export")
async def export_plan_review(project_id: uuid.UUID, service: ChecklistServiceDep):
    """品質計畫審查（橘框對綠框）：計畫的品質管理標準表漏了哪些本案施工規範的可檢查標準。"""
    review = await service.plan_review(project_id)
    return _xlsx(plan_review_xlsx(review), f"品質計畫審查_{review.plan_name.rsplit('.', 1)[0]}")


@router.get("/{project_id}/cross-rule-reminders", response_model=list[CrossRuleReminderOut])
async def get_cross_rule_reminders(project_id: uuid.UUID, service: ChecklistServiceDep):
    """法規雙重規範提醒：本案標單工項與契約圖圖名觸發了哪些「要同時滿足兩部規定」的提醒（示範目錄）。"""
    return [CrossRuleReminderOut(**vars(r)) for r in await service.cross_rule_reminders(project_id)]


@router.get("/{project_id}/plans/{kind}/export")
async def export_plan(project_id: uuid.UUID, kind: str, service: ChecklistServiceDep, demo: bool = False):
    """整體品質計畫（quality-plan）或監造計畫（supervision-plan）初稿：各章橘框表單組成一份 Word。"""
    builders = {"quality-plan": (quality_plan_docx, "整體品質計畫"), "supervision-plan": (supervision_plan_docx, "監造計畫")}
    if kind not in builders:
        raise NotFoundError("只有 quality-plan 與 supervision-plan")
    build, name = builders[kind]
    project_name, chapters, materials = await service.plan_sources(project_id)
    filename = f"{project_name}{name}（初稿{'・示範補正' if demo else ''}）.docx"
    return Response(
        content=build(project_name, chapters, materials, demo=demo),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _standard(draft, demo: bool):
    """?demo=true：初稿的「（待填）」用示範內容補齊（demo_fill，標「（示範）」），給展示用。"""
    return demo_fill.fill_standard(draft) if demo else draft


def _xlsx(content: bytes, title: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(title + '.xlsx')}"},
    )
