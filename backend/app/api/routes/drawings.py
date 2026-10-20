import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.schemas.drawing import AddDrawingItem, EditDrawingSheet, IndexDrawing, ReviewDrawingItem
from app.services.drawing_service import DrawingService

router = APIRouter(prefix="/api/projects/{project_id}/drawings", tags=["drawings"])


@router.get("")
async def get_drawings(project_id: uuid.UUID, session: DbSession):
    return await DrawingService(session).snapshot(project_id)


@router.post("/index")
async def index_drawings(project_id: uuid.UUID, request: IndexDrawing, session: DbSession):
    return await DrawingService(session).index(project_id, request)


@router.post("/items", status_code=201)
async def add_item(project_id: uuid.UUID, request: AddDrawingItem, session: DbSession):
    return await DrawingService(session).add_item(project_id, request)


@router.patch("/items/{item_id}")
async def review_item(project_id: uuid.UUID, item_id: uuid.UUID,
                      request: ReviewDrawingItem, session: DbSession):
    return await DrawingService(session).review(project_id, item_id, request)


@router.patch("/sheets/{sheet_id}")
async def edit_sheet(project_id: uuid.UUID, sheet_id: uuid.UUID,
                     request: EditDrawingSheet, session: DbSession):
    return await DrawingService(session).edit_sheet(project_id, sheet_id, request)


@router.get("/documents/{document_id}/file")
async def drawing_file(project_id: uuid.UUID, document_id: uuid.UUID, session: DbSession):
    doc = await DrawingService(session).document(project_id, document_id)
    return FileResponse(doc.storage_path, media_type="application/pdf",
                        filename=doc.filename, content_disposition_type="inline")
