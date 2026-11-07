"""法規條文與規範章節的混合搜尋 API（GET /api/search/knowledge），在 SQLite 上走記憶體向量。"""

import numpy as np
import pytest

from app.api.routes import search as search_routes
from app.models.knowledge import EMBEDDING_DIMENSION
from app.search.corpus import Chunk
from app.services import knowledge_search_service
from app.services.knowledge_search_service import KnowledgeSearchService

CHUNKS = [
    Chunk("建築法 第 34 條", "law_article", "建築法", "第 34 條", "", "主管建築機關審查建築物工程圖樣及說明書"),
    Chunk("建築法 第 69 條", "law_article", "建築法", "第 69 條", "", "鄰接其他建築物施行挖土工程時，應作防護措施"),
    Chunk("政府採購法 第 65 條", "law_article", "政府採購法", "第 65 條", "", "得標廠商應自行履行工程，不得轉包"),
    Chunk("PCCES 03310", "spec_chapter", "施工綱要規範", "03310", "結構用混凝土", ""),
]
CONCEPTS = [["鄰接", "隔壁"], ["轉包", "丟給別家"], ["混凝土", "灌漿"]]


class FakeEmbedder:
    name = "fake"
    dimension = EMBEDDING_DIMENSION

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
        for i, words in enumerate(CONCEPTS):
            vector[i] = float(any(word in text for word in words))
        vector[-1] = 0.1
        return vector / np.linalg.norm(vector)

    def embed_documents(self, texts, show_progress=False):
        return np.stack([self._vector(t) for t in texts])

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture(autouse=True)
def fresh_cache():
    knowledge_search_service._cache = None
    yield
    knowledge_search_service._cache = None


async def build(db_session, embedder):
    vectors = embedder.embed_documents([c.text for c in CHUNKS]) if embedder else None
    await KnowledgeSearchService(db_session, embedder).rebuild(CHUNKS, vectors)


class TestKnowledgeSearchApi:
    async def test_hybrid_finds_paraphrase_and_reports_channels(self, api_client, db_session, monkeypatch):
        embedder = FakeEmbedder()
        await build(db_session, embedder)
        monkeypatch.setattr(search_routes, "get_embedder", lambda: embedder)

        body = (await api_client.get("/api/search/knowledge", params={"q": "包商把工程丟給別家"})).json()

        assert body["vector_enabled"] is True
        assert body["hits"][0]["ref"] == "政府採購法 第 65 條"
        assert "vector" in body["hits"][0]["ranks"]

    async def test_named_article_comes_first(self, api_client, db_session, monkeypatch):
        embedder = FakeEmbedder()
        await build(db_session, embedder)
        monkeypatch.setattr(search_routes, "get_embedder", lambda: embedder)

        body = (await api_client.get("/api/search/knowledge", params={"q": "建築法第三十四條"})).json()

        assert body["hits"][0]["ref"] == "建築法 第 34 條"
        assert body["hits"][0]["ranks"]["exact"] == 1

    async def test_without_embeddings_it_falls_back_and_says_so(self, api_client, db_session, monkeypatch):
        await build(db_session, None)
        monkeypatch.setattr(search_routes, "get_embedder", lambda: None)

        body = (await api_client.get("/api/search/knowledge", params={"q": "轉包"})).json()

        assert body["vector_enabled"] is False
        assert "沒有啟用" in body["method_note"]
        assert body["hits"][0]["ref"] == "政府採購法 第 65 條"

    async def test_vector_mode_without_embeddings_returns_nothing(self, api_client, db_session, monkeypatch):
        await build(db_session, None)
        monkeypatch.setattr(search_routes, "get_embedder", lambda: None)

        body = (await api_client.get("/api/search/knowledge", params={"q": "轉包", "mode": "vector"})).json()

        assert body["hits"] == []

    async def test_lexical_mode_ignores_vectors(self, api_client, db_session, monkeypatch):
        embedder = FakeEmbedder()
        await build(db_session, embedder)
        monkeypatch.setattr(search_routes, "get_embedder", lambda: embedder)

        body = (
            await api_client.get("/api/search/knowledge", params={"q": "隔壁房子", "mode": "lexical"})
        ).json()

        assert all("vector" not in hit["ranks"] for hit in body["hits"])

    async def test_unknown_mode_is_rejected(self, api_client):
        response = await api_client.get("/api/search/knowledge", params={"q": "x", "mode": "magic"})
        assert response.status_code == 400

    async def test_wrong_dimension_is_refused(self, db_session):
        with pytest.raises(ValueError, match="維"):
            await KnowledgeSearchService(db_session, FakeEmbedder()).rebuild(CHUNKS, np.zeros((len(CHUNKS), 384)))

    async def test_requires_login(self, db_session):
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/search/knowledge", params={"q": "轉包"})
        assert response.status_code == 401
