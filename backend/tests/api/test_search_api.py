"""跨文件檢索（示範）：字詞相似度，不是語意。"""

import uuid

from app.models.document import Document, DocumentSection
from app.models.tenant import Tenant
from app.search.retriever import BigramIndex, tokens
from tests.factories import make_docx_bytes

DOCS = [
    "混凝土澆置依 QP-07-03 辦理",
    "模板組立依模板組立作業標準辦理",
    "預拌混凝土應符合 CNS 3090 之規定",
    "施工安全依職業安全衛生法辦理",
]


class TestRetriever:
    def test_chinese_is_split_into_character_pairs(self):
        assert tokens("澆置作業") == ["澆置", "置作", "作業"]

    def test_codes_stay_whole(self):
        assert "QP-07-03" in tokens("依 QP-07-03 辦理")

    def test_the_closest_paragraph_ranks_first(self):
        hits = BigramIndex(DOCS).search("混凝土澆置")

        assert hits[0].index == 0
        assert hits[0].score > hits[1].score

    def test_a_standard_number_finds_its_paragraph(self):
        assert [hit.index for hit in BigramIndex(DOCS).search("CNS 3090")] == [2]

    def test_it_is_literal_not_semantic(self):
        """「灌漿」意思接近「澆置」，但字面不同，就找不到——這是示範版的已知限制。"""
        assert BigramIndex(DOCS).search("灌漿") == []

    def test_matched_terms_are_reported(self):
        hit = BigramIndex(DOCS).search("安全衛生")[0]

        assert set(hit.matched) == {"安全", "全衛", "衛生"}


async def analyze(api_client, name: str, data: bytes) -> str:
    files = {"file": (name, data, "application/octet-stream")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    return document_id


class TestSearchApi:
    async def test_paragraphs_from_analyzed_documents_are_found(self, api_client):
        document_id = await analyze(api_client, "整體品質計畫.docx", make_docx_bytes())

        body = (await api_client.get("/api/search", params={"q": "營建剩餘土石方"})).json()

        top = body["sections"][0]
        assert top["document_id"] == document_id
        assert "營建剩餘土石方" in top["snippet"]
        assert "不是語意模型" in body["method_note"]

    async def test_regulations_are_searched_by_name(self, api_client):
        await analyze(api_client, "整體品質計畫.docx", make_docx_bytes())

        body = (await api_client.get("/api/search", params={"q": "採購法"})).json()

        assert body["regulations"][0]["name"] == "政府採購法"

    async def test_nothing_found_is_an_empty_list_not_an_error(self, api_client):
        body = (await api_client.get("/api/search", params={"q": "完全無關的查詢詞"})).json()

        assert (body["sections"], body["regulations"]) == ([], [])

    async def test_an_empty_query_is_rejected(self, api_client):
        response = await api_client.get("/api/search", params={"q": ""})

        assert response.status_code == 400

    async def test_other_tenants_paragraphs_are_not_searched(self, api_client, db_session):
        other = Tenant(id=uuid.uuid4(), name="別的公司")
        document = Document(
            filename="別人的.txt", file_type="txt", storage_path="/nowhere", file_hash="1" * 64,
            tenant_id=other.id,
        )
        db_session.add_all([other, document])
        await db_session.flush()
        db_session.add(
            DocumentSection(document_id=document.id, content="機密的帷幕牆工程說明", order_index=0)
        )
        await db_session.commit()

        body = (await api_client.get("/api/search", params={"q": "帷幕牆"})).json()

        assert body["sections"] == []
