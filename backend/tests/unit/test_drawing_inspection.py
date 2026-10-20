import hashlib
import json
import uuid

import pytest

from app.models.document import Document
from app.models.drawing import DrawingItem, DrawingSheet
from app.models.project import Project, ProjectDocument


@pytest.fixture
async def inspection_case(db_session, tmp_path):
    project = Project(name="synthetic inspection", drawing_revision=8)
    doc = Document(filename="synthetic.pdf", file_type="pdf", storage_path="unused",
                   file_hash="a" * 64)
    db_session.add_all([project, doc])
    await db_session.flush()
    db_session.add(ProjectDocument(project_id=project.id, document_id=doc.id, role="drawing"))
    sheet = DrawingSheet(project_id=project.id, document_id=doc.id, page=1,
                         number="A1", title="Synthetic", method="manual", evidence="source")
    db_session.add(sheet)
    await db_session.flush()
    item = DrawingItem(sheet_id=sheet.id, name="Test A", evidence="source",
                       review_status="pending", review_note="current note")
    db_session.add(item)
    await db_session.commit()
    pid, did = project.id, doc.id
    root = tmp_path / "inspection"
    root.mkdir()
    reports = {
        "candidates": ("candidate-register/candidate-register.json",
                       {"summary": {"revision": 7, "normalized_name_groups": 1},
                        "groups": [], "suggestions": []}),
        "cross_check": ("cross-check/cross-check.json",
                        {"index": {"rows": [{"source_page": 1, "number": "A1",
                          "index_title": "Index", "title_comparison": "different_text_requires_review",
                          "targets": [], "quote": "source"}]},
                         "references": [{"source_page": 1, "source_number": "A1", "token": "A2",
                                         "classification": "not_located_requires_review",
                                         "explanation": "needs review", "targets": []}],
                         "reference_counts": {"not_located_requires_review": 1}}),
        "architecture": ("architecture-review/reviewed-pages.json", {"rows": []}),
        "structure": ("structure-review/reviewed-pages.json", {"rows": []}),
    }
    artifacts = {}
    for key, (name, body) in reports.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
        artifacts[key] = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    png = root / "cross-check" / "sample.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    manifest = {"version": 1, "project_id": str(pid), "historical_revision": 7,
                "documents": [{"id": str(did), "file_hash": doc.file_hash, "book": "architecture"}],
                "artifacts": artifacts,
                "images": {"sample": {"path": "cross-check/sample.png", "label": "sample",
                                     "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}}}
    path = root / str(pid) / "manifest.json"
    path.parent.mkdir()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return pid, did, root, path, manifest


async def test_snapshot_combines_history_with_live_reviews_without_writes(db_session, inspection_case):
    from app.services.drawing_inspection_service import DrawingInspectionService
    pid, _, root, _, _ = inspection_case
    service = DrawingInspectionService(db_session, root=root)
    result = await service.snapshot(pid)
    assert result["available"] is True
    assert (result["revision"], result["historical_revision"]) == (8, 7)
    assert result["summary"]["current_statuses"] == {"pending": 1}
    assert result["groups"][0]["items"][0]["review_note"] == "current note"
    assert result["summary"]["index_title_differences"] == 1
    assert result["summary"]["references"] == 1
    assert result["findings"][1]["priority"] == "high"
    assert not db_session.new and not db_session.dirty and not db_session.deleted


@pytest.mark.parametrize("damage", ["missing", "hash", "project", "document", "traversal", "corrupt"])
async def test_invalid_manifest_is_absent_without_leaking_history(db_session, inspection_case, damage):
    from app.services.drawing_inspection_service import DrawingInspectionService
    pid, _, root, path, manifest = inspection_case
    if damage == "missing":
        (root / manifest["artifacts"]["cross_check"]["path"]).unlink()
    elif damage == "hash":
        manifest["artifacts"]["cross_check"]["sha256"] = "0" * 64
    elif damage == "project":
        manifest["project_id"] = str(uuid.uuid4())
    elif damage == "document":
        manifest["documents"][0]["file_hash"] = "0" * 64
    elif damage == "traversal":
        manifest["artifacts"]["cross_check"]["path"] = "../outside.json"
    if damage == "corrupt":
        path.write_text("[]", encoding="utf-8")
    else:
        path.write_text(json.dumps(manifest), encoding="utf-8")
    result = await DrawingInspectionService(db_session, root=root).snapshot(pid)
    assert result["available"] is False
    assert result["warnings"] and not result["findings"] and not result["images"]
    assert result["summary"]["current_candidates"] == 1


async def test_images_require_manifest_and_safe_exact_id(db_session, inspection_case):
    from app.services.drawing_inspection_service import DrawingInspectionService
    from fastapi import HTTPException
    pid, _, root, path, manifest = inspection_case
    service = DrawingInspectionService(db_session, root=root)
    assert (await service.image(pid, "sample")).name == "sample.png"
    for name in ["../sample", "manifest.json", "not-listed"]:
        with pytest.raises(HTTPException) as error:
            await service.image(pid, name)
        assert error.value.status_code == 404
    manifest["images"]["sample"]["path"] = "../outside.png"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(HTTPException):
        await service.image(pid, "sample")


@pytest.mark.parametrize("damage", ["targets", "image", "image_type"])
async def test_malformed_bound_artifact_returns_absent(db_session, inspection_case, damage):
    from app.services.drawing_inspection_service import DrawingInspectionService
    pid, _, root, manifest_path, manifest = inspection_case
    if damage == "targets":
        binding = manifest["artifacts"]["cross_check"]
        path = root / binding["path"]
        content = json.loads(path.read_text("utf-8"))
        content["references"][0]["targets"] = None
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        binding = manifest["images"]["sample"]
        path = root / binding["path"]
        if damage == "image":
            path.unlink()
        else:
            path.write_text("<html>active content</html>", encoding="utf-8")
    if path.exists():
        binding["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = await DrawingInspectionService(db_session, root=root).snapshot(pid)
    assert result["available"] is False
    assert result["warnings"] and not result["images"]


async def test_http_contract_project_isolation_and_current_review_refresh(
        db_session, inspection_case, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select
    from app.api.routes.drawing_inspection import router
    from app.core.db import get_db
    from app.services import drawing_inspection_service
    from app.services.drawing_service import fingerprint

    pid, _, root, _, _ = inspection_case
    monkeypatch.setattr(drawing_inspection_service, "INSPECTION_ROOT", root)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_session
    other = Project(name="unrelated")
    db_session.add(other)
    await db_session.commit()
    other_id = other.id
    base = f"/api/projects/{pid}/drawing-inspection"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(base)
        assert response.status_code == 200 and response.json()["available"]
        image = await client.get(base + "/images/sample")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.headers["x-content-type-options"] == "nosniff"
        other_base = f"/api/projects/{other_id}/drawing-inspection"
        assert not (await client.get(other_base)).json()["available"]
        assert (await client.get(other_base + "/images/sample")).status_code == 404
        assert (await client.get(base + "/images/%2E%2E%2Fsample")).status_code == 404
        item = await db_session.scalar(select(DrawingItem))
        item.review_status = "rejected"
        item.review_fingerprint = fingerprint([])
        item.review_note = "new manual note"
        await db_session.commit()
        refreshed = (await client.get(base)).json()
        assert refreshed["summary"]["current_statuses"] == {"rejected": 1}
        assert refreshed["groups"][0]["items"][0]["review_note"] == "new manual note"
