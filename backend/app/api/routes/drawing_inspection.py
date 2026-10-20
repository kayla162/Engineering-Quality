import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.schemas.drawing_inspection import DrawingInspectionResponse
from app.services.drawing_inspection_service import DrawingInspectionService

router = APIRouter(prefix="/api/projects/{project_id}/drawing-inspection", tags=["drawing-inspection"])


@router.get("", response_model=DrawingInspectionResponse)
async def inspect_drawings(project_id: uuid.UUID, session: DbSession):
    return await DrawingInspectionService(session).snapshot(project_id)


@router.get("/images/{image_id}")
async def inspection_image(project_id: uuid.UUID, image_id: str, session: DbSession):
    path = await DrawingInspectionService(session).image(project_id, image_id)
    return FileResponse(path, media_type="image/png",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
