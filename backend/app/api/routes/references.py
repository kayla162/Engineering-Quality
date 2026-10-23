"""法規引用清單、詳細資料與人工覆核的 API。"""

import uuid

from fastapi import APIRouter, Query, Request

from app.api.deps import AuditServiceDep, CurrentUserDep, ReferenceServiceDep
from app.core.enums import AuditAction, RegulationStatus, ReviewStatus
from app.schemas.reference import ReferenceDetail, ReferenceListOut, ReviewRequest

router = APIRouter(tags=["references"])


@router.get("/api/documents/{document_id}/references", response_model=ReferenceListOut)
async def list_references(
    document_id: uuid.UUID,
    service: ReferenceServiceDep,
    status: RegulationStatus | None = Query(None),
    review_status: ReviewStatus | None = Query(None),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    return await service.list_for_document(
        document_id,
        status=status,
        review_status=review_status,
        min_confidence=min_confidence,
        page=page,
        page_size=page_size,
    )


@router.get("/api/regulation-references/{reference_id}", response_model=ReferenceDetail)
async def get_reference(reference_id: uuid.UUID, service: ReferenceServiceDep):
    return await service.get_detail(reference_id)


@router.patch("/api/regulation-references/{reference_id}/review", response_model=ReferenceDetail)
async def review_reference(
    reference_id: uuid.UUID,
    payload: ReviewRequest,
    request: Request,
    service: ReferenceServiceDep,
    audit: AuditServiceDep,
    user: CurrentUserDep,
):
    """人工覆核。只更新覆核欄位，不會覆蓋系統判斷出來的 status。"""
    detail = await service.review(
        reference_id, payload.review_status, user.username, payload.review_note
    )
    await audit.record(
        AuditAction.REFERENCE_REVIEWED,
        actor=user,
        resource_type="reference",
        resource_id=reference_id,
        detail={
            "raw_text": detail.raw_text,
            "review_status": payload.review_status,
            "review_note": payload.review_note,
        },
        request=request,
        commit=True,
    )
    return detail
