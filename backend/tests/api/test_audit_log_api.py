"""使用者操作稽核紀錄（audit_log）。

驗三件事：做了的事有記、沒做成的事不記（登入失敗例外，它本身就是事件）、
看得到紀錄的只有同租戶的管理員。
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.enums import AuditAction, ReviewStatus
from app.models.audit import AuditLog
from tests.factories import make_docx_bytes, make_pdf_bytes

MEMBER_PASSWORD = "member-password-1234"


async def actions(api_client) -> list[str]:
    body = (await api_client.get("/api/audit-logs", params={"page_size": 200})).json()
    return [item["action"] for item in body["items"]]


async def upload(api_client, filename="整體品質計畫.docx", data=None) -> str:
    files = {"file": (filename, data or make_docx_bytes(), "application/octet-stream")}
    response = await api_client.post("/api/documents/upload", files=files)
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


@pytest.fixture
async def member_client(api_client, db_session):
    """同租戶的一般成員。新帳號要先改密碼才能用業務 API。"""
    from app.main import app

    response = await api_client.post(
        "/api/users",
        json={"username": "member", "initial_password": "initial-password-123", "role": "member"},
    )
    assert response.status_code == 201, response.text
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": "http://localhost:3000"},
    ) as client:
        await client.post(
            "/api/auth/login", json={"username": "member", "password": "initial-password-123"}
        )
        await client.post(
            "/api/auth/change-password",
            json={"old_password": "initial-password-123", "new_password": MEMBER_PASSWORD},
        )
        response = await client.post(
            "/api/auth/login", json={"username": "member", "password": MEMBER_PASSWORD}
        )
        assert response.status_code == 200, response.text
        yield client


class TestRecording:
    async def test_login_is_recorded(self, api_client):
        assert AuditAction.LOGIN in await actions(api_client)

    async def test_upload_records_who_and_which_document(self, api_client):
        document_id = await upload(api_client)

        item = (await api_client.get("/api/audit-logs")).json()["items"][0]

        assert item["action"] == AuditAction.DOCUMENT_UPLOADED
        assert item["username"] == "test-admin"
        assert (item["resource_type"], item["resource_id"]) == ("document", document_id)
        assert item["detail"]["filename"] == "整體品質計畫.docx"

    async def test_newest_first(self, api_client):
        await upload(api_client)

        assert (await actions(api_client))[:2] == [AuditAction.DOCUMENT_UPLOADED, AuditAction.LOGIN]

    async def test_analysis_review_and_export_are_recorded(self, api_client):
        document_id = await upload(api_client)
        await api_client.post(f"/api/documents/{document_id}/analyze")
        reference = (await api_client.get(f"/api/documents/{document_id}/references")).json()[
            "items"
        ][0]
        await api_client.patch(
            f"/api/regulation-references/{reference['reference_id']}/review",
            json={"review_status": ReviewStatus.CONFIRMED, "review_note": "已查證"},
        )
        await api_client.get(f"/api/reports/{document_id}/export", params={"format": "csv"})

        recorded = await actions(api_client)

        for action in (
            AuditAction.ANALYSIS_STARTED,
            AuditAction.REFERENCE_REVIEWED,
            AuditAction.REPORT_EXPORTED,
        ):
            assert action in recorded

    async def test_review_detail_keeps_what_was_decided(self, api_client):
        """覆核紀錄要看得出「判定成什麼、為什麼」，不只是「有人按了」。"""
        document_id = await upload(api_client)
        await api_client.post(f"/api/documents/{document_id}/analyze")
        reference = (await api_client.get(f"/api/documents/{document_id}/references")).json()[
            "items"
        ][0]
        await api_client.patch(
            f"/api/regulation-references/{reference['reference_id']}/review",
            json={"review_status": ReviewStatus.REJECTED, "review_note": "不是法規"},
        )

        item = (
            await api_client.get(
                "/api/audit-logs", params={"action": AuditAction.REFERENCE_REVIEWED}
            )
        ).json()["items"][0]

        assert item["detail"]["review_status"] == ReviewStatus.REJECTED
        assert item["detail"]["review_note"] == "不是法規"
        assert item["detail"]["raw_text"] == reference["raw_text"]

    async def test_project_actions_are_recorded(self, api_client):
        project = (await api_client.post("/api/projects", json={"name": "測試工程"})).json()

        assert AuditAction.PROJECT_CREATED in await actions(api_client)
        assert project["project_id"]

    async def test_user_management_is_recorded(self, api_client, member_client):
        recorded = await actions(api_client)

        assert AuditAction.USER_CREATED in recorded
        assert AuditAction.PASSWORD_CHANGED in recorded


class TestNotRecorded:
    async def test_a_rejected_upload_leaves_no_record(self, api_client):
        """操作失敗就不該留下「做了」的紀錄。"""
        await upload(api_client)
        response = await api_client.post(
            "/api/documents/upload",
            files={"file": ("整體品質計畫.docx", make_docx_bytes(), "application/octet-stream")},
        )
        assert response.status_code == 409

        assert (await actions(api_client)).count(AuditAction.DOCUMENT_UPLOADED) == 1

    async def test_reads_are_not_recorded(self, api_client):
        await api_client.get("/api/documents")
        await api_client.get("/api/projects")

        assert await actions(api_client) == [AuditAction.LOGIN]


class TestFailedLogin:
    async def test_a_wrong_password_is_recorded_against_the_tenant(self, api_client):
        """帳號存在時要歸到它的租戶，管理員才看得到有人在試密碼。"""
        response = await api_client.post(
            "/api/auth/login", json={"username": "test-admin", "password": "wrong-password-0"}
        )
        assert response.status_code == 401

        item = (
            await api_client.get("/api/audit-logs", params={"action": AuditAction.LOGIN_FAILED})
        ).json()["items"][0]
        assert item["username"] == "test-admin"
        assert item["detail"] == {"reason": "invalid_credentials"}

    async def test_an_unknown_username_is_kept_out_of_every_tenant(self, api_client, db_session):
        await api_client.post(
            "/api/auth/login", json={"username": "nobody", "password": "wrong-password-0"}
        )

        assert AuditAction.LOGIN_FAILED not in await actions(api_client)
        row = await db_session.scalar(select(AuditLog).where(AuditLog.username == "nobody"))
        assert row is not None and row.tenant_id is None


class TestAccess:
    async def test_members_cannot_read_the_log(self, member_client):
        response = await member_client.get("/api/audit-logs")

        assert response.status_code == 403

    async def test_member_actions_show_up_for_the_admin(self, api_client, member_client):
        await upload(member_client, filename="成員上傳.pdf", data=make_pdf_bytes(text_pages=1))

        item = (
            await api_client.get(
                "/api/audit-logs", params={"action": AuditAction.DOCUMENT_UPLOADED}
            )
        ).json()["items"][0]
        assert item["username"] == "member"

    async def test_filter_by_username(self, api_client, member_client):
        body = (await api_client.get("/api/audit-logs", params={"username": "member"})).json()

        assert body["total"] > 0
        assert {item["username"] for item in body["items"]} == {"member"}

    async def test_an_unknown_action_filter_is_rejected(self, api_client):
        """本系統的驗證錯誤統一回 400（docs/api.md 第 6 節）。"""
        response = await api_client.get("/api/audit-logs", params={"action": "made_up"})

        assert response.status_code == 400
