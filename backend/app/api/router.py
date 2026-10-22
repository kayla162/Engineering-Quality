"""把所有 router 集中掛載。新增 API 時在這裡加一行。"""

from fastapi import APIRouter, Depends

from app.api.routes import (
    checklist,
    documents,
    health,
    jobs,
    projects,
    references,
    regulations,
    reports,
    sources,
    auth,
    users,
)
from app.core.security import require_business_user

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(sources.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)

for business_router in (
    documents.router,
    jobs.router,
    references.router,
    regulations.router,
    reports.router,
    projects.router,
    checklist.router,
):
    api_router.include_router(
        business_router, dependencies=[Depends(require_business_user)]
    )
