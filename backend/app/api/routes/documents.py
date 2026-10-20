"""文件上傳與查詢的 API。"""

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import DocumentServiceDep, JobServiceDep
from app.schemas.document import DocumentListOut, DocumentOut
from app.schemas.job import JobCreatedOut

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(service: DocumentServiceDep, file: UploadFile = File(...)):
    """上傳工程文件。只做驗證與落檔，不做解析（解析由 /analyze 觸發的背景任務負責）。"""
    document = await service.upload_stream(file)
    return DocumentOut.from_model(document)


@router.get("", response_model=DocumentListOut)
async def list_documents(
    service: DocumentServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
):
    documents, total = await service.list_documents(page, page_size, status_filter)
    items = [
        DocumentOut.from_model(document, await service.latest_job(document.id))
        for document in documents
    ]
    return DocumentListOut(total=total, page=page, page_size=page_size, items=items)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, service: DocumentServiceDep):
    document = await service.get(document_id)
    return DocumentOut.from_model(document, await service.latest_job(document_id))


@router.post(
    "/{document_id}/analyze",
    response_model=JobCreatedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_document(document_id: uuid.UUID, service: JobServiceDep):
    """觸發背景分析。立即回傳 job_id，不等分析完成。可重複呼叫（重新分析）。"""
    job = await service.start_analysis(document_id)
    return JobCreatedOut(job_id=job.id, status=job.status)
