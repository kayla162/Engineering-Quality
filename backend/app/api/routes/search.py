"""跨文件檢索 API（示範，Phase 2 RAG 的替身）。"""

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, DbSession
from app.services.search_service import METHOD_NOTE, SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


class SectionHitOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    page: int | None
    snippet: str
    score: float
    #: 查詢裡在這段出現的詞（中文是相鄰兩字）
    matched: list[str]


class RegulationHitOut(BaseModel):
    regulation_id: uuid.UUID
    name: str
    status: str
    source: str
    score: float


class SearchOut(BaseModel):
    query: str
    #: 檢索方式的說明。示範版是字詞相似度，不是語意搜尋
    method_note: str
    sections: list[SectionHitOut]
    regulations: list[RegulationHitOut]


@router.get("", response_model=SearchOut)
async def search(
    session: DbSession,
    user: CurrentUserDep,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
):
    sections, regulations = await SearchService(session, user.tenant_id).search(q.strip(), limit)
    return SearchOut(
        query=q,
        method_note=METHOD_NOTE,
        sections=[SectionHitOut(**vars(hit)) for hit in sections],
        regulations=[RegulationHitOut(**vars(hit)) for hit in regulations],
    )
