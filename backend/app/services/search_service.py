"""跨文件的段落與法規檢索（示範，見 app/search/retriever.py）。

範圍是這個租戶所有已解析的文件段落，以及法規主檔的名稱。每次查詢現讀現算。
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentSection
from app.models.regulation import Regulation
from app.search.retriever import BigramIndex

#: 告訴使用者這是什麼樣的檢索。畫面與 API 都要帶著，不能讓人以為是語意搜尋
METHOD_NOTE = "示範檢索：依字詞（相鄰兩字）相似度排序，不是語意模型；換個說法可能就找不到。"
SNIPPET_RADIUS = 60


@dataclass(frozen=True)
class SectionHit:
    document_id: uuid.UUID
    filename: str
    page: int | None
    snippet: str
    score: float
    matched: list[str]


@dataclass(frozen=True)
class RegulationHit:
    regulation_id: uuid.UUID
    name: str
    status: str
    source: str
    score: float


class SearchService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def search(self, query: str, limit: int = 10) -> tuple[list[SectionHit], list[RegulationHit]]:
        return await self._sections(query, limit), await self._regulations(query, min(limit, 5))

    async def _sections(self, query: str, limit: int) -> list[SectionHit]:
        rows = (
            await self.session.execute(
                select(DocumentSection.content, DocumentSection.page, Document.id, Document.filename)
                .join(Document, Document.id == DocumentSection.document_id)
                .where(Document.tenant_id == self.tenant_id)
                .order_by(Document.uploaded_at, DocumentSection.order_index)
            )
        ).all()
        if not rows:
            return []
        hits = BigramIndex([row.content for row in rows]).search(query, k=limit)
        return [
            SectionHit(
                document_id=rows[hit.index].id,
                filename=rows[hit.index].filename,
                page=rows[hit.index].page,
                snippet=_snippet(rows[hit.index].content, hit.matched),
                score=hit.score,
                matched=hit.matched,
            )
            for hit in hits
        ]

    async def _regulations(self, query: str, limit: int) -> list[RegulationHit]:
        regulations = (
            await self.session.execute(select(Regulation).where(Regulation.tenant_id == self.tenant_id))
        ).scalars().all()
        if not regulations:
            return []
        hits = BigramIndex([r.name for r in regulations]).search(query, k=limit, min_score=0.2)
        return [
            RegulationHit(
                regulation_id=regulations[hit.index].id,
                name=regulations[hit.index].name,
                status=regulations[hit.index].status,
                source=regulations[hit.index].source,
                score=hit.score,
            )
            for hit in hits
        ]


def _snippet(content: str, matched: list[str]) -> str:
    """以第一個命中的詞為中心，前後各取一段。"""
    positions = [p for term in matched if (p := content.upper().find(term.upper())) >= 0]
    if not positions or len(content) <= SNIPPET_RADIUS * 2:
        return content[: SNIPPET_RADIUS * 2]
    center = min(positions)
    start = max(0, center - SNIPPET_RADIUS)
    end = min(len(content), center + SNIPPET_RADIUS)
    return ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
