"""工項檢核表 API。

檢核結果不存在資料庫裡，每次查詢時由工項、章節索引與依據算出來
（docs/superpowers/specs/2026-10-05-工項檢核表-階段3-design.md 第 4 節）。

建與讀是兩條路，刻意分開：POST 重建（重讀整份規範書、對每個工項重新抽取），
GET 只讀已經建好的。GET 不能順手重建——重建很貴，而且有副作用的 GET 會讓人
無法回答「為什麼數字變了」。
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import ChecklistServiceDep
from app.schemas.checklist import ChecklistOut

router = APIRouter(prefix="/api/projects", tags=["checklist"])


@router.post(
    "/{project_id}/checklist",
    response_model=ChecklistOut,
    status_code=status.HTTP_201_CREATED,
)
async def build_checklist(project_id: uuid.UUID, service: ChecklistServiceDep):
    """重建依據並回傳檢核表。重跑取代，不累加。

    沒掛施工規範不會報錯：工項都在，只是依據欄空白（和沒掛標單是 400 刻意不對稱）。
    """
    return ChecklistOut.from_checklist(await service.build(project_id))


@router.get("/{project_id}/checklist", response_model=ChecklistOut)
async def get_checklist(project_id: uuid.UUID, service: ChecklistServiceDep):
    """只讀已經建好的依據。要重建請用 POST。"""
    return ChecklistOut.from_checklist(await service.checklist(project_id))
