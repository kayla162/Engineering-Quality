"""法規查詢 API。"""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import RegulationServiceDep
from app.schemas.regulation import (
    RegulationDetailOut,
    RegulationOut,
    RegulationSearchOut,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(prefix="/api/regulations", tags=["regulations"])


@router.get("/search", response_model=RegulationSearchOut)
async def search_regulations(
    service: RegulationServiceDep,
    q: str = Query(min_length=1),
    type: str | None = Query(None),
    force_external: bool = Query(False),
):
    """先查內部資料庫，找不到（或指定 force_external）才即時查外部來源。"""
    rows, queried_external = await service.search(q, type, force_external)
    return RegulationSearchOut(
        total=len(rows),
        items=[RegulationOut.from_model(row) for row in rows],
        queried_external=queried_external,
    )


@router.get("/{regulation_id}", response_model=RegulationDetailOut)
async def get_regulation(regulation_id: uuid.UUID, service: RegulationServiceDep):
    return RegulationDetailOut.from_model(await service.get(regulation_id))


@router.post("/verify", response_model=VerifyResponse)
async def verify_regulation(payload: VerifyRequest, service: RegulationServiceDep):
    """手動觸發重新查詢外部來源（例如懷疑資料過期時）。"""
    result = await service.verify(payload.regulation_id, payload.source)
    return VerifyResponse(
        regulation=RegulationDetailOut.from_model(result["regulation"]),
        sources_queried=result["sources_queried"],
        changed=result["changed"],
        message=result["message"],
    )
