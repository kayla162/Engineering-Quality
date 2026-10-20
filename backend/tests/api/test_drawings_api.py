import uuid
from pathlib import Path

from app.models.project import WorkItem
from tests.unit.test_drawings import make_drawing


async def current_request(client, method, url, **kwargs):
    """Normal mutations submit the version the client just read; stale tests override it."""
    if "/drawings/" in url and "json" in kwargs:
        base = url.split("/drawings/")[0] + "/drawings"
        body = (await client.get(base)).json()
        kwargs["json"].setdefault("expected_revision", body["revision"])
    return await client.request(method, url, **kwargs)


async def post(client, url, **kwargs):
    return await current_request(client, "POST", url, **kwargs)


async def patch(client, url, **kwargs):
    return await current_request(client, "PATCH", url, **kwargs)


async def test_snapshot_never_labels_earlier_content_with_later_revision(api_client, db_session, tmp_path, monkeypatch):
    from app.services.drawing_service import DrawingService
    project, _ = await setup_project(api_client, tmp_path)
    service = DrawingService(db_session)
    project_id = uuid.UUID(project)
    previous = await service.snapshot(project_id)
    original = service.projects.work_items
    async def concurrent_change(pid):
        rows = await original(pid)
        await service.projects.advance_drawing_revision(pid)
        await db_session.commit()
        return rows
    monkeypatch.setattr(service.projects, "work_items", concurrent_change)
    snapshot = await service.snapshot(project_id)
    assert snapshot["revision"] == previous["revision"]


async def test_stale_review_cannot_confirm_changed_evidence(api_client, db_session, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    db_session.add(WorkItem(project_id=uuid.UUID(project), item_no="1", name="防水", unit="m2"))
    await db_session.commit()
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    sheet_id = body["sheets"][0]["id"]
    body = (await post(api_client, base + "/items", json={
        "sheet_id": sheet_id, "name": "防水", "evidence": "原圖"
    })).json()
    stale = body.get("revision", 0)
    await patch(api_client, base + f"/sheets/{sheet_id}", json={
        "number": "A2-01", "title": "修改的圖", "expected_revision": stale
    })
    r = await patch(api_client, base + f"/items/{body['items'][0]['id']}", json={
        "decision": "confirmed", "work_item_ids": [], "note": "舊畫面的圖說獨有",
        "expected_revision": stale,
    })
    assert r.status_code == 409


async def setup_project(client, tmp_path):
    path = tmp_path / "drawing.pdf"
    make_drawing(path)
    document = (await client.post("/api/documents/upload", files={
        "file": ("drawing.pdf", path.read_bytes(), "application/pdf")
    })).json()["document_id"]
    project = (await client.post("/api/projects", json={"name": "drawing-test"})).json()["project_id"]
    await client.post(f"/api/projects/{project}/documents", json={"document_id": document, "role": "drawing"})
    return project, document


async def test_index_manual_item_review_and_union(api_client, db_session, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    response = await post(api_client, base + "/index", json={"document_id": document})
    assert response.status_code == 200
    sheet = response.json()["sheets"][0]
    assert sheet["number"] == "A8-09B"
    assert sheet["page"] == 1
    item = WorkItem(project_id=uuid.UUID(project), item_no="1.1", name="外牆防水", unit="m2")
    db_session.add(item)
    await db_session.commit()
    response = await post(api_client, base + "/items", json={
        "sheet_id": sheet["id"], "name": "防水", "evidence": "人工核對第 1 頁防水詳圖"
    })
    assert response.status_code == 201
    candidate = response.json()["items"][0]
    assert candidate["review_status"] == "pending"
    assert candidate["suggested_work_item_ids"] == [str(item.id)]
    body = (await api_client.get(base)).json()
    assert body["union"][0]["status"] == "needs_confirmation"
    reviewed = await patch(api_client, base + f"/items/{candidate['id']}", json={
        "decision": "confirmed", "work_item_ids": [str(item.id)], "note": "依原圖核對"
    })
    assert reviewed.status_code == 200
    body = reviewed.json()
    assert body["union"][0]["status"] == "both"
    assert body["union"][0]["drawing_item_ids"] == [candidate["id"]]
    # BOQ rebuild must invalidate old review, not silently reattach by name.
    await db_session.delete(item)
    db_session.add(WorkItem(project_id=uuid.UUID(project), item_no="1.1", name="外牆防水", unit="m2"))
    await db_session.commit()
    body = (await api_client.get(base)).json()
    assert body["items"][0]["review_status"] == "stale"
    assert body["union"][0]["status"] == "needs_confirmation"


async def test_cross_project_document_and_item_rejected(api_client, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    other = (await post(api_client, "/api/projects", json={"name": "other"})).json()["project_id"]
    r = await post(api_client, f"/api/projects/{other}/drawings/index", json={"document_id": document})
    assert r.status_code == 400
    body = (await post(api_client, f"/api/projects/{project}/drawings/index",
                                  json={"document_id": document})).json()
    r = await post(api_client, f"/api/projects/{other}/drawings/items", json={
        "sheet_id": body["sheets"][0]["id"], "name": "防水", "evidence": "page evidence"
    })
    assert r.status_code == 400


async def test_reindex_resets_reviews_and_does_not_duplicate(api_client, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    first = (await post(api_client, base + "/index", json={"document_id": document})).json()
    await post(api_client, base + "/items", json={
        "sheet_id": first["sheets"][0]["id"], "name": "防水", "evidence": "核對原圖"
    })
    second = (await post(api_client, base + "/index", json={"document_id": document})).json()
    assert len(second["sheets"]) == 1
    assert second["items"] == []


async def test_unreadable_pages_not_reported_as_missing(api_client, tmp_path):
    import pymupdf
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    document = (await post(api_client, "/api/documents/upload", files={
        "file": ("scan.pdf", path.read_bytes(), "application/pdf")
    })).json()["document_id"]
    project = (await post(api_client, "/api/projects", json={"name": "scan"})).json()["project_id"]
    base = f"/api/projects/{project}"
    await post(api_client, base + "/documents", json={"document_id": document, "role": "drawing"})
    r = await post(api_client, base + "/drawings/index", json={"document_id": document})
    assert r.status_code == 200
    assert r.json()["sheets"][0]["warning"]
    assert r.json()["summary"]["unreadable_pages"] == 1
    assert r.json()["union"] == []


async def test_missing_boq_cannot_be_confirmed_as_drawing_only(api_client, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    body = (await post(api_client, base + "/items", json={
        "sheet_id": body["sheets"][0]["id"], "name": "防水", "evidence": "原圖"
    })).json()
    r = await patch(api_client, base + f"/items/{body['items'][0]['id']}", json={
        "decision": "confirmed", "work_item_ids": [], "note": "沒有標單"
    })
    assert r.status_code == 400


async def test_foreign_work_item_and_file_access_rejected(api_client, db_session, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    other = (await post(api_client, "/api/projects", json={"name": "other"})).json()["project_id"]
    foreign = WorkItem(project_id=uuid.UUID(other), item_no="1", name="防水", unit="m2")
    db_session.add(foreign)
    await db_session.commit()
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    body = (await post(api_client, base + "/items", json={
        "sheet_id": body["sheets"][0]["id"], "name": "防水", "evidence": "原圖"
    })).json()
    r = await patch(api_client, base + f"/items/{body['items'][0]['id']}", json={
        "decision": "confirmed", "work_item_ids": [str(foreign.id)], "note": "別案"
    })
    assert r.status_code == 400
    assert (await api_client.get(f"/api/projects/{other}/drawings/documents/{document}/file")).status_code == 400
    assert (await api_client.get(base + f"/documents/{document}/file")).status_code == 200


async def test_failed_reindex_retains_previous_index(api_client, tmp_path, monkeypatch):
    from app.services import drawing_service
    from app.core.errors import UnprocessableDocumentError
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    original = (await post(api_client, base + "/index", json={"document_id": document})).json()
    def fail(*args, **kwargs):
        raise UnprocessableDocumentError("test corrupt file")
    monkeypatch.setattr(drawing_service, "read_drawings", fail)
    r = await post(api_client, base + "/index", json={"document_id": document})
    assert r.status_code >= 400
    assert (await api_client.get(base)).json()["sheets"] == original["sheets"]


async def test_many_to_many_review_and_title_edit_invalidates_page(api_client, db_session, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    work = [WorkItem(project_id=uuid.UUID(project), item_no=str(n), name="防水", unit="m2") for n in range(2)]
    db_session.add_all(work)
    await db_session.commit()
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    sheet_id = body["sheets"][0]["id"]
    body = (await post(api_client, base + "/items", json={
        "sheet_id": sheet_id, "name": "防水", "evidence": "圖面位置"
    })).json()
    item_id = body["items"][0]["id"]
    body = (await patch(api_client, base + f"/items/{item_id}", json={
        "decision": "confirmed", "work_item_ids": [str(w.id) for w in work], "note": "同圖不同樓層"
    })).json()
    assert [r["status"] for r in body["union"]] == ["both", "both"]
    body = (await patch(api_client, base + f"/sheets/{sheet_id}", json={
        "number": "A1-02", "title": "另一張圖"
    })).json()
    assert body["items"][0]["review_status"] == "pending"
    assert all(r["status"] != "both" for r in body["union"])


async def test_snapshot_refreshes_retained_orm_objects(api_client, db_session, tmp_path):
    from sqlalchemy import update
    from app.models.drawing import DrawingSheet
    from app.models.project import Project
    from app.services.drawing_service import DrawingService
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    sheet_id = uuid.UUID(body["sheets"][0]["id"])
    retained = await db_session.get(DrawingSheet, sheet_id)
    # Represent a second writer changing committed DB state without refreshing
    # objects retained by the first writer's expire_on_commit=False session.
    await db_session.execute(update(DrawingSheet).where(DrawingSheet.id == sheet_id)
        .values(title="new committed title").execution_options(synchronize_session=False))
    await db_session.execute(update(Project).where(Project.id == uuid.UUID(project))
        .values(drawing_revision=Project.drawing_revision + 1)
        .execution_options(synchronize_session=False))
    await db_session.commit()
    assert retained.title != "new committed title"
    snapshot = await DrawingService(db_session).snapshot(uuid.UUID(project))
    assert snapshot["revision"] == body["revision"] + 1
    assert snapshot["sheets"][0]["title"] == "new committed title"


async def test_assisted_transcription_preserves_evidence_and_pending_review(api_client, tmp_path):
    project, document = await setup_project(api_client, tmp_path)
    base = f"/api/projects/{project}/drawings"
    body = (await post(api_client, base + "/index", json={"document_id": document})).json()
    original = body["sheets"][0]
    body = (await post(api_client, base + "/items", json={
        "sheet_id": original["id"], "name": "防水", "evidence": "舊圖名候選"
    })).json()
    result = await patch(api_client, base + f"/sheets/{original['id']}", json={
        "number": "A1-02", "title": "防水詳圖", "source": "assisted"
    })
    assert result.status_code == 200
    sheet = result.json()["sheets"][0]
    assert sheet["method"] == "assisted"
    assert "AI" in sheet["warning"] and "人工" in sheet["warning"]
    assert sheet["evidence"] == original["evidence"]
    assert all(i["review_status"] == "pending" for i in result.json()["items"])
