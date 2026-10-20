"""把所有 router 集中掛載。新增 API 時在這裡加一行。"""

from fastapi import APIRouter

from app.api.routes import (
    checklist,
    documents,
    drawings,
    drawing_inspection,
    integrated_checklist,
    health,
    jobs,
    projects,
    references,
    regulations,
    reports,
    sources,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(jobs.router)
api_router.include_router(references.router)
api_router.include_router(regulations.router)
api_router.include_router(reports.router)
api_router.include_router(sources.router)
api_router.include_router(projects.router)
api_router.include_router(checklist.router)
api_router.include_router(drawings.router)
api_router.include_router(drawing_inspection.router)
api_router.include_router(integrated_checklist.router)
