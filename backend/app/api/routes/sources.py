"""法規來源的就緒狀態（對應 docs/api.md 第 7 節）。

存在的理由：官方法規索引是由 scripts/sync_taiwan_law.py 同步下來的本地檔案，
「有沒有跑過同步」是部署方的責任。沒跑的話分析仍會完成，但每一筆引用都會是
UNKNOWN。前端在使用者按下「開始分析」之前就打這支 API，才能把原因講出來，
而不是讓人對著滿頁 UNKNOWN 猜。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.sources import SourcesReadiness, readiness_report, sources_for_tenant

router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources", response_model=SourcesReadiness)
async def get_sources_status(
    user: CurrentUser | None = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """回報每個已啟用來源現在查不查得動。

    每次呼叫都重新檢查（adapter 載入失敗時不會快取失敗結果），
    所以維運跑完同步腳本之後不需要重啟服務，前端重新整理就會變成就緒。
    """
    # 登入時用這個租戶的來源回報：企業內部文件有沒有匯入是各租戶自己的事
    if user is not None:
        return readiness_report(await sources_for_tenant(session, user.tenant_id))
    return readiness_report()
