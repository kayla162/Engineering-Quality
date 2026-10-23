"""總覽統計 API。"""

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, DbSession
from app.schemas.dashboard import DashboardOut
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
async def get_dashboard(session: DbSession, user: CurrentUserDep):
    return await DashboardService(session, user.tenant_id).build()
