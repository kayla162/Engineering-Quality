"""健康檢查，供 docker-compose healthcheck 與未來監控使用。"""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.schemas.common import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: DbSession):
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        logger.exception("資料庫健康檢查失敗")
        database = "error"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        version=settings.APP_VERSION,
    )
