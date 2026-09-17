"""專案 API：建立專案、掛文件、建立與查詢工項清單。"""

import pytest

from tests.factories import make_boq_bytes


@pytest.fixture
async def project_id(api_client):
    response = await api_client.post("/api/projects", json={"name": "秀山分隊興建工程"})
    return response.json()["project_id"]


@pytest.fixture
async def boq_id(api_client):
    files = {"file": ("標單.xlsx", make_boq_bytes(), "application/vnd.ms-excel")}
    response = await api_client.post("/api/documents/upload", files=files)
    return response.json()["document_id"]


class TestCreateProject:
    async def test_project_is_created(self, api_client):
        response = await api_client.post("/api/projects", json={"name": "秀山分隊興建工程"})

        assert response.status_code == 201
        assert response.json()["name"] == "秀山分隊興建工程"

    async def test_blank_name_is_rejected(self, api_client):
        response = await api_client.post("/api/projects", json={"name": "  "})

        assert response.status_code == 400

    async def test_projects_are_listed(self, api_client, project_id):
        response = await api_client.get("/api/projects")

        assert project_id in [p["project_id"] for p in response.json()["items"]]


class TestAttachDocument:
    async def test_document_is_attached(self, api_client, project_id, boq_id):
        response = await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": boq_id, "role": "boq"},
        )

        assert response.status_code == 201
        assert response.json()["role"] == "boq"

    async def test_unknown_role_is_rejected(self, api_client, project_id, boq_id):
        response = await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": boq_id, "role": "不存在的角色"},
        )

        assert response.status_code == 400

    async def test_unknown_project_is_404(self, api_client, boq_id):
        response = await api_client.post(
            "/api/projects/00000000-0000-0000-0000-000000000000/documents",
            json={"document_id": boq_id, "role": "boq"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


class TestWorkItems:
    async def test_work_items_are_built_from_the_boq(self, api_client, project_id, boq_id):
        await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": boq_id, "role": "boq"},
        )

        response = await api_client.post(f"/api/projects/{project_id}/work-items")

        assert response.status_code == 201
        assert response.json()["total"] >= 1

    async def test_listing_includes_the_spec_chapter(self, api_client, project_id, boq_id):
        """計價代碼前 5 碼對到綱要規範章節——這是檢核表「施工規範」欄的來源。"""
        await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": boq_id, "role": "boq"},
        )
        await api_client.post(f"/api/projects/{project_id}/work-items")

        items = (await api_client.get(f"/api/projects/{project_id}/work-items")).json()["items"]
        first = next(i for i in items if i["item_no"] == "壹.一.1.1.1")

        assert first["spec_chapter"]["code"] == "01725"
        assert "施工測量" in first["spec_chapter"]["name"]

    async def test_item_without_a_code_has_no_chapter(self, api_client, project_id, boq_id):
        await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": boq_id, "role": "boq"},
        )
        await api_client.post(f"/api/projects/{project_id}/work-items")

        items = (await api_client.get(f"/api/projects/{project_id}/work-items")).json()["items"]
        bare = next(i for i in items if i["item_no"] == "壹.一.1.3.1")

        assert bare["spec_chapter"] is None

    async def test_building_without_a_boq_explains_why(self, api_client, project_id):
        response = await api_client.post(f"/api/projects/{project_id}/work-items")

        assert response.status_code == 400
        assert "標單" in response.json()["error"]["message"]
