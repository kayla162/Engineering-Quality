from io import BytesIO
import uuid

import openpyxl
import pytest

from tests.integration.test_integrated_checklist import seed


@pytest.fixture
async def integrated_client(db_session):
    # The root integrator registers this router in the production router. A
    # focused app allows independent implementation before that registration.
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api.routes.integrated_checklist import router
    from app.core.errors import register_exception_handlers
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_json_and_export_share_project_snapshot(integrated_client, db_session):
    project, _, item, _ = await seed(db_session)
    base = f"/api/projects/{project}/integrated-checklist"
    response = await integrated_client.get(base)
    assert response.status_code == 200
    assert response.json()["items"][0]["key"] == f"drawing:{item}"
    for format, content_type in [
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("csv", "text/csv"), ("pdf", "application/pdf"),
    ]:
        exported = await integrated_client.get(base + "/export", params={"format": format})
        assert exported.status_code == 200
        assert content_type in exported.headers["content-type"]
        assert "attachment;" in exported.headers["content-disposition"]
        if format == "xlsx":
            book = openpyxl.load_workbook(BytesIO(exported.content))
            assert book["整合檢核"]["A2"].value == f"drawing:{item}"
        elif format == "csv":
            assert f"drawing:{item}" in exported.content.decode("utf-8-sig")
        else:
            assert exported.content.startswith(b"%PDF")


async def test_unknown_project_and_unsupported_export_fail_cleanly(integrated_client, db_session):
    base = f"/api/projects/{uuid.uuid4()}/integrated-checklist"
    assert (await integrated_client.get(base)).status_code == 404
    project, _, _, _ = await seed(db_session)
    response = await integrated_client.get(
        f"/api/projects/{project}/integrated-checklist/export?format=html")
    # Existing application error contract maps validation errors to HTTP 400.
    assert response.status_code == 400
