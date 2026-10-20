"""API 測試：走完一次完整流程 upload -> analyze -> 輪詢 -> references -> review -> report。"""

import pytest

from app.core.enums import JobStatus, ReviewStatus
from tests.factories import make_docx_bytes


def upload_payload(filename: str = "整體品質計畫.docx", content: bytes | None = None):
    return {
        "file": (
            filename,
            content if content is not None else make_docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }


class TestHealth:
    async def test_health(self, api_client):
        response = await api_client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"


class TestFullFlow:
    async def test_end_to_end(self, api_client):
        # 1. 上傳
        upload = await api_client.post("/api/documents/upload", files=upload_payload())
        assert upload.status_code == 201
        document_id = upload.json()["document_id"]
        assert upload.json()["status"] == "UPLOADED"

        # 2. 觸發分析（背景任務會在 request 結束後執行）
        analyze = await api_client.post(f"/api/documents/{document_id}/analyze")
        assert analyze.status_code == 202
        job_id = analyze.json()["job_id"]

        # 3. 輪詢進度
        job = (await api_client.get(f"/api/jobs/{job_id}")).json()
        assert job["status"] == JobStatus.COMPLETED
        assert job["progress"] == 100
        assert job["error_message"] is None

        # 4. 取得清單
        listing = (await api_client.get(f"/api/documents/{document_id}/references")).json()
        assert listing["total"] > 0
        assert listing["summary"]["confirmed_active"] > 0
        assert listing["summary"]["not_found"] > 0

        item = next(i for i in listing["items"] if i["normalized_name"] == "政府採購法")
        assert item["status"] == "ACTIVE"
        assert item["review_status"] == ReviewStatus.UNREVIEWED

        # 5. 單筆詳細資料（可追溯性）
        detail = (
            await api_client.get(f"/api/regulation-references/{item['reference_id']}")
        ).json()
        assert detail["source_document"] == "整體品質計畫.docx"
        assert detail["matched_regulation"]["source"] == "mock"
        assert detail["match_reasons"]
        assert detail["extraction_method"]

        # 6. 人工覆核
        review = await api_client.patch(
            f"/api/regulation-references/{item['reference_id']}/review",
            json={
                "review_status": "CONFIRMED",
                "reviewed_by": "kayla3377@gmail.com",
                "review_note": "已人工核對官網條文",
            },
        )
        assert review.status_code == 200
        assert review.json()["review_status"] == "CONFIRMED"
        assert review.json()["reviewed_at"] is not None
        # 人工覆核不會覆蓋系統判斷
        assert review.json()["status"] == "ACTIVE"

        # 7. 報告
        report = (await api_client.get(f"/api/reports/{document_id}")).json()
        assert report["total_references"] == listing["total"]
        assert report["disclaimer"]

        export = await api_client.get(f"/api/reports/{document_id}/export?format=xlsx")
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        assert len(export.content) > 0


class TestFiltersAndPaging:
    @pytest.fixture
    async def analyzed_document(self, api_client):
        upload = await api_client.post("/api/documents/upload", files=upload_payload())
        document_id = upload.json()["document_id"]
        await api_client.post(f"/api/documents/{document_id}/analyze")
        return document_id

    async def test_filter_by_status(self, api_client, analyzed_document):
        response = await api_client.get(
            f"/api/documents/{analyzed_document}/references?status=NOT_FOUND"
        )
        items = response.json()["items"]
        assert items
        assert all(item["status"] == "NOT_FOUND" for item in items)

    async def test_filter_by_min_confidence(self, api_client, analyzed_document):
        response = await api_client.get(
            f"/api/documents/{analyzed_document}/references?min_confidence=0.95"
        )
        assert all(item["match_confidence"] >= 0.95 for item in response.json()["items"])

    async def test_paging(self, api_client, analyzed_document):
        response = await api_client.get(
            f"/api/documents/{analyzed_document}/references?page=1&page_size=2"
        )
        body = response.json()
        assert len(body["items"]) <= 2
        assert body["page_size"] == 2
        # 統計是整份文件的，不受分頁影響
        assert body["total"] > len(body["items"])

    async def test_invalid_status_is_rejected(self, api_client, analyzed_document):
        response = await api_client.get(
            f"/api/documents/{analyzed_document}/references?status=NOPE"
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestErrors:
    async def test_unknown_document_returns_structured_error(self, api_client):
        response = await api_client.get(
            "/api/documents/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    async def test_invalid_file_type(self, api_client):
        response = await api_client.post(
            "/api/documents/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"

    async def test_duplicate_upload_returns_409(self, api_client):
        payload = upload_payload()
        assert (await api_client.post("/api/documents/upload", files=payload)).status_code == 201
        # Reuse identical bytes: re-creating a DOCX can change ZIP timestamps.
        second = await api_client.post("/api/documents/upload", files=payload)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DUPLICATE_FILE"

    async def test_unknown_job(self, api_client):
        response = await api_client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


class TestRegulations:
    async def test_search_finds_seeded_regulation(self, api_client):
        response = await api_client.get("/api/regulations/search?q=政府採購法")
        body = response.json()
        assert body["total"] >= 1
        assert body["items"][0]["name"] == "政府採購法"
        assert body["items"][0]["source"] == "mock"

    async def test_detail_includes_aliases(self, api_client):
        search = (await api_client.get("/api/regulations/search?q=政府採購法")).json()
        regulation_id = search["items"][0]["regulation_id"]
        detail = (await api_client.get(f"/api/regulations/{regulation_id}")).json()
        assert "採購法" in detail["aliases"]

    async def test_verify_requeries_source(self, api_client):
        search = (await api_client.get("/api/regulations/search?q=政府採購法")).json()
        regulation_id = search["items"][0]["regulation_id"]
        response = await api_client.post(
            "/api/regulations/verify", json={"regulation_id": regulation_id, "source": "mock"}
        )
        assert response.status_code == 200
        assert response.json()["sources_queried"] == ["mock"]

    async def test_verify_unknown_source(self, api_client):
        search = (await api_client.get("/api/regulations/search?q=政府採購法")).json()
        regulation_id = search["items"][0]["regulation_id"]
        response = await api_client.post(
            "/api/regulations/verify",
            json={"regulation_id": regulation_id, "source": "does_not_exist"},
        )
        assert response.status_code == 400
