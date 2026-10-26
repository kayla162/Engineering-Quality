"""總覽統計。

數字一律拿清單 API 來對：總覽和清單說的不一樣，比沒有總覽更糟。
"""

import uuid

import pytest

from app.core.enums import NEEDS_ATTENTION_STATUSES, ReviewStatus
from app.models.document import Document
from app.models.tenant import Tenant
from tests.factories import make_docx_bytes


async def dashboard(api_client) -> dict:
    response = await api_client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def analyzed(api_client) -> tuple[str, list[dict]]:
    files = {"file": ("整體品質計畫.docx", make_docx_bytes(), "application/octet-stream")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()[
        "document_id"
    ]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    references = (
        await api_client.get(f"/api/documents/{document_id}/references", params={"page_size": 500})
    ).json()["items"]
    return document_id, references


def needing_action(references: list[dict]) -> list[dict]:
    return [
        r
        for r in references
        if r["status"] in NEEDS_ATTENTION_STATUSES and r["review_status"] == ReviewStatus.UNREVIEWED
    ]


class TestEmpty:
    async def test_a_new_tenant_sees_zeros_not_an_error(self, api_client):
        body = await dashboard(api_client)

        assert body["documents"]["total"] == 0
        assert body["references"]["total"] == 0
        assert body["top_regulations"] == []
        assert body["documents_needing_action"] == []


class TestCountsMatchTheLists:
    async def test_reference_total_matches_the_list(self, api_client, analyzed):
        _, references = analyzed

        assert (await dashboard(api_client))["references"]["total"] == len(references)

    async def test_status_breakdown_matches_the_list(self, api_client, analyzed):
        _, references = analyzed
        expected: dict[str, int] = {}
        for r in references:
            expected[r["status"]] = expected.get(r["status"], 0) + 1

        assert (await dashboard(api_client))["references"]["by_status"] == expected

    async def test_needs_action_matches_the_list(self, api_client, analyzed):
        _, references = analyzed

        body = await dashboard(api_client)

        assert body["references"]["needs_action"] == len(needing_action(references)) > 0

    async def test_reviewing_one_lowers_needs_action(self, api_client, analyzed):
        _, references = analyzed
        before = (await dashboard(api_client))["references"]["needs_action"]
        target = needing_action(references)[0]

        await api_client.patch(
            f"/api/regulation-references/{target['reference_id']}/review",
            json={"review_status": ReviewStatus.CONFIRMED},
        )

        body = await dashboard(api_client)
        assert body["references"]["needs_action"] == before - 1
        assert body["references"]["by_review"][ReviewStatus.CONFIRMED] == 1

    async def test_document_list_counts_the_analyzed_document(self, api_client, analyzed):
        document_id, references = analyzed

        rows = (await dashboard(api_client))["documents_needing_action"]

        assert [row["document_id"] for row in rows] == [document_id]
        assert rows[0]["references"] == len(references)
        assert rows[0]["needs_action"] == len(needing_action(references))


class TestRegulations:
    async def test_most_cited_regulation_comes_first_with_its_count(self, api_client, analyzed):
        """範例文件在段落與表格各引用一次政府採購法，是引用次數最多的。"""
        _, references = analyzed
        expected = sum(1 for r in references if r["normalized_name"] == "政府採購法")

        top = (await dashboard(api_client))["top_regulations"][0]

        assert (top["name"], top["references"], top["documents"]) == ("政府採購法", expected, 1)

    async def test_source_breakdown_marks_mock_data(self, api_client, analyzed):
        """畫面要能看出有多少結論是假資料撐起來的。"""
        _, references = analyzed
        matched = sum(1 for r in references if r["regulation_id"])

        assert (await dashboard(api_client))["references"]["by_source"] == {"mock": matched}


class TestTenantScope:
    async def test_other_tenants_documents_are_not_counted(self, api_client, db_session):
        other = Tenant(id=uuid.uuid4(), name="別的租戶")
        db_session.add(other)
        db_session.add(
            Document(
                filename="別人的.docx",
                file_type="docx",
                storage_path="/nowhere",
                file_hash="0" * 64,
                tenant_id=other.id,
            )
        )
        await db_session.commit()

        assert (await dashboard(api_client))["documents"]["total"] == 0
