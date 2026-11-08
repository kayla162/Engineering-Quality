"""法規條文與規範章節的混合搜尋（app/search/hybrid.py）。

混合搜尋（hybrid）：
1. 精確比對：「建築法第 34 條」「03310」「CNS 14253」直接找到那一條，排最前面
2. 語意向量：PostgreSQL 由 pgvector（HNSW）算，SQLite 在記憶體算

沒有啟用 embedding（EMBEDDING_PROVIDER=none）或還沒建向量時，第 2 路改用字詞相似度
（和文件段落搜尋同一套 BigramIndex），回應的 `vector_enabled` 是 false，畫面會說明。
為什麼有向量時不再合併字詞相似度：見 app/search/hybrid.py 與 docs/semantic-search.md 的評估。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, delete, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import EMBEDDING_DIMENSION, KnowledgeChunk
from app.search.corpus import Chunk
from app.search.embeddings import Embedder
from app.search.hybrid import CANDIDATES, MODES, InMemoryIndex, fuse

SNIPPET_LENGTH = 160
#: 必須 ≥ CANDIDATES。語料只有幾千筆時 PostgreSQL 會直接全表掃描（精確），筆數多了才走 HNSW
HNSW_EF_SEARCH = 100

METHOD_NOTES = {
    "hybrid": "混合搜尋：指名的條號、章碼或標準編號優先，其餘依語意相近程度排序。",
    "lexical": "字詞相似度：依相鄰兩字的重疊程度排序，換個說法可能就找不到。",
    "vector": "純語意向量：依意思相近排序，條號、章碼這類數字不一定比得準。",
}
NO_VECTOR_NOTE = "語意模型沒有啟用，目前只依條號、標準編號與字詞相似度搜尋；換個說法可能就找不到。"


@dataclass(frozen=True)
class KnowledgeHit:
    ref: str
    kind: str
    source: str
    locator: str
    heading: str
    snippet: str
    score: float
    #: 這筆在各路的名次：exact／lexical／vector
    ranks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    mode: str
    vector_enabled: bool
    method_note: str
    hits: list[KnowledgeHit]


@dataclass
class _Cached:
    signature: tuple
    index: InMemoryIndex
    by_ref: dict[str, Chunk]
    has_vectors: bool


#: 語料幾千筆、只在重建索引時才變，載入一次放在記憶體；簽章（筆數＋最後建立時間）變了才重載
_cache: _Cached | None = None


class KnowledgeSearchService:
    def __init__(self, session: AsyncSession, embedder: Embedder | None, aliases: dict[str, str] | None = None):
        self.session = session
        self.embedder = embedder
        self.aliases = aliases or {}
        self._postgres = session.bind.dialect.name == "postgresql"

    # --- 建索引 ---

    async def rebuild(self, chunks: list[Chunk], vectors: np.ndarray | None = None) -> int:
        """整份取代。`vectors` 與 `chunks` 同順序；None 表示只建字詞索引。"""
        if vectors is not None:
            if len(vectors) != len(chunks):
                raise ValueError("向量筆數和語料筆數不同")
            if vectors.shape[1] != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"模型輸出 {vectors.shape[1]} 維，資料庫欄位是 {EMBEDDING_DIMENSION} 維；換模型要先改 migration"
                )
        model = self.embedder.name if (vectors is not None and self.embedder) else None
        await self.session.execute(delete(KnowledgeChunk))
        for i, chunk in enumerate(chunks):
            self.session.add(
                KnowledgeChunk(
                    ref=chunk.ref,
                    kind=chunk.kind,
                    source=chunk.source,
                    locator=chunk.locator,
                    heading=chunk.heading,
                    content=chunk.content,
                    embedding=None if vectors is None else vectors[i].tolist(),
                    embedding_model=model,
                )
            )
        await self.session.commit()
        if self._postgres:
            # 剛整批寫入的表沒有統計資料，規劃器會誤判而改走近似的 HNSW；更新統計後幾千筆會選精確的全表掃描
            await self.session.execute(text("ANALYZE knowledge_chunks"))
            await self.session.commit()
        global _cache
        _cache = None
        return len(chunks)

    # --- 查詢 ---

    async def chunks(self, refs: list[str]) -> list[Chunk]:
        """依 ref 取完整條文（搜尋結果只有摘錄）。順序和 `refs` 相同，找不到的略過。"""
        cached = await self._load()
        return [cached.by_ref[ref] for ref in refs if ref in cached.by_ref]

    async def search(self, query: str, mode: str = "hybrid", limit: int = 10) -> KnowledgeSearchResult:
        if mode not in MODES:
            raise ValueError(f"不支援的搜尋方式：{mode}")
        cached = await self._load()
        vector_enabled = self.embedder is not None and cached.has_vectors

        if not vector_enabled and mode == "vector":
            return KnowledgeSearchResult(mode, False, NO_VECTOR_NOTE, [])

        rankings: dict[str, list[str]] = {}
        if mode == "lexical" or (mode == "hybrid" and not vector_enabled):
            rankings["lexical"] = cached.index.lexical(query)
        if mode in ("vector", "hybrid") and vector_enabled:
            rankings["vector"] = await self._vector(cached.index, query)
        exact = cached.index.matcher.match(query) if mode == "hybrid" else []
        ranked = fuse(rankings, exact=exact, limit=limit)

        note = METHOD_NOTES[mode] if vector_enabled or mode == "lexical" else NO_VECTOR_NOTE
        hits = [
            KnowledgeHit(
                ref=r.ref,
                kind=(chunk := cached.by_ref[r.ref]).kind,
                source=chunk.source,
                locator=chunk.locator,
                heading=chunk.heading,
                snippet=chunk.content[:SNIPPET_LENGTH] + ("…" if len(chunk.content) > SNIPPET_LENGTH else ""),
                score=r.score,
                ranks=r.ranks,
            )
            for r in ranked
        ]
        return KnowledgeSearchResult(mode, vector_enabled, note, hits)

    async def _vector(self, index: InMemoryIndex, query: str) -> list[str]:
        # 模型推論吃 CPU（bge-m3 約 100 ms），丟到執行緒，不要卡住 event loop
        query_vector = await asyncio.to_thread(self.embedder.embed_query, query)
        if not self._postgres:
            return index.vector(query_vector)
        # 欄位是 JSON／Vector 的變體型別，pgvector 的 cosine_distance() 掛不上，直接寫 <=> 運算子
        query_literal = literal(query_vector.tolist(), type_=Vector(EMBEDDING_DIMENSION))
        distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(query_literal)
        # HNSW 一次最多回傳 ef_search 筆（預設 40），比要取的候選數少就會默默只拿到 40 筆
        await self.session.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}"))
        # 只能依距離排序：多一個排序鍵（例如 ref）索引就用不上，會變成全表排序
        rows = await self.session.execute(select(KnowledgeChunk.ref).order_by(distance).limit(CANDIDATES))
        return list(rows.scalars())

    async def _has_vectors(self) -> bool:
        found = await self.session.scalar(
            select(KnowledgeChunk.id).where(KnowledgeChunk.embedding.is_not(None)).limit(1)
        )
        return found is not None

    async def _signature(self) -> tuple[int, datetime | None]:
        row = (
            await self.session.execute(select(func.count(KnowledgeChunk.id), func.max(KnowledgeChunk.indexed_at)))
        ).one()
        return (row[0], row[1])

    async def _load(self) -> _Cached:
        global _cache
        signature = (await self._signature(), self._postgres, tuple(sorted(self.aliases.items())))
        if _cache is not None and _cache.signature == signature:
            return _cache
        # PostgreSQL 的向量留在資料庫給 pgvector 算，不讀進記憶體
        columns = [
            KnowledgeChunk.ref,
            KnowledgeChunk.kind,
            KnowledgeChunk.source,
            KnowledgeChunk.locator,
            KnowledgeChunk.heading,
            KnowledgeChunk.content,
        ]
        if not self._postgres:
            columns.append(KnowledgeChunk.embedding)
        rows = (await self.session.execute(select(*columns).order_by(KnowledgeChunk.ref))).all()
        chunks = [Chunk(r.ref, r.kind, r.source, r.locator, r.heading, r.content) for r in rows]
        embeddings = None
        if self._postgres:
            has_vectors = await self._has_vectors()
        else:
            has_vectors = bool(rows) and all(r.embedding is not None for r in rows)
            if has_vectors:
                embeddings = np.asarray([r.embedding for r in rows], dtype=np.float32)
        _cache = _Cached(
            signature, InMemoryIndex(chunks, embeddings, self.aliases), {c.ref: c for c in chunks}, has_vectors
        )
        return _cache
