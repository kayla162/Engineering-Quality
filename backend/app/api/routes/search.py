"""檢索 API。

- `GET /api/search`：這個租戶上傳文件的段落（字詞相似度）
- `GET /api/search/knowledge`：法規條文與施工綱要規範章節（混合搜尋，見 app/search/hybrid.py）
"""

import asyncio
import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, DbSession
from app.search.corpus import default_aliases
from app.search.embeddings import get_embedder
from app.search.hybrid import MODES
from app.services.knowledge_search_service import KnowledgeSearchService
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


class KnowledgeHitOut(BaseModel):
    ref: str
    #: law_article | spec_chapter
    kind: str
    source: str
    locator: str
    heading: str
    snippet: str
    score: float
    #: 這筆在各路的名次：exact（指名條號）／lexical（字詞）／vector（語意）
    ranks: dict[str, int]


class KnowledgeSearchOut(BaseModel):
    query: str
    mode: str
    #: false：語意模型沒有啟用或還沒建向量，結果只依條號與字詞相似度
    vector_enabled: bool
    method_note: str
    hits: list[KnowledgeHitOut]


@router.get("/knowledge", response_model=KnowledgeSearchOut)
async def search_knowledge(
    session: DbSession,
    user: CurrentUserDep,
    q: str = Query(..., min_length=1, max_length=200),
    mode: str = Query("hybrid", pattern="^(" + "|".join(MODES) + ")$"),
    limit: int = Query(10, ge=1, le=50),
):
    # 第一次呼叫會載入模型（數秒），放到執行緒避免卡住其他請求
    embedder = await asyncio.to_thread(get_embedder)
    result = await KnowledgeSearchService(session, embedder, default_aliases()).search(q.strip(), mode, limit)
    return KnowledgeSearchOut(
        query=q,
        mode=result.mode,
        vector_enabled=result.vector_enabled,
        method_note=result.method_note,
        hits=[KnowledgeHitOut(**vars(hit)) for hit in result.hits],
    )
