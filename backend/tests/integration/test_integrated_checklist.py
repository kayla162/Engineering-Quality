"""Read-only integration contract; fixture databases never touch live project data."""
import uuid

import pytest
from sqlalchemy import event, select

from app.core.enums import DocumentRole
from app.models.document import Document
from app.models.drawing import DrawingItem, DrawingSheet
from app.models.project import Project, ProjectDocument, WorkItem
from app.services.drawing_service import fingerprint


async def seed(session, *, with_work=False):
    project = Project(name="唯讀整合測試")
    document = Document(filename="契約圖.pdf", file_type="pdf", storage_path="unused.pdf",
                        file_hash=uuid.uuid4().hex)
    session.add_all([project, document])
    await session.flush()
    session.add(ProjectDocument(project_id=project.id, document_id=document.id,
                                role=DocumentRole.DRAWING))
    sheet = DrawingSheet(project_id=project.id, document_id=document.id, page=7,
                         number="A-07", title="防水詳圖", method="manual",
                         evidence="圖框原文", warning="圖名待核對")
    session.add(sheet)
    work = []
    if with_work:
        work = [WorkItem(project_id=project.id, item_no=str(n), name="防水工程",
                         unit="m2", order_index=n) for n in (1, 2)]
        session.add_all(work)
    await session.flush()
    item = DrawingItem(sheet_id=sheet.id, name="防水", evidence="工法：熱熔工法；原圖註記",
                       review_note="人工備註不可覆寫")
    session.add(item)
    await session.commit()
    return project.id, sheet.id, item.id, [w.id for w in work]


async def test_no_boq_returns_candidate_with_evidence_and_no_missing_claim(db_session):
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, sheet, item, _ = await seed(db_session)
    result = await IntegratedChecklistService(db_session).snapshot(project)
    assert result.total == 1
    row = result.items[0]
    assert row.key == f"drawing:{item}"
    assert row.source_status == "drawing_candidate"
    assert row.work_item_id is None and row.basis_result is None
    assert row.drawings[0].page == 7
    assert row.drawings[0].filename == "契約圖.pdf"
    assert row.drawings[0].review_note == "人工備註不可覆寫"
    assert row.method.status == "pending"
    assert row.method.candidates[0].text == "熱熔工法"
    assert any("標單" in warning for warning in result.warnings)
    assert "優於" not in result.contract_note


async def test_pending_suggestions_never_become_confirmed_matches(db_session):
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, _, _, work = await seed(db_session, with_work=True)
    result = await IntegratedChecklistService(db_session).snapshot(project)
    assert [row.source_status for row in result.items] == [
        "needs_confirmation", "needs_confirmation", "drawing_candidate"]
    assert all(not row.drawings for row in result.items[:2])
    assert all(row.basis_result == "NEEDS_CONFIRMATION" for row in result.items[:2])
    assert result.summary.matched == 0
    assert result.summary.total == result.total == 3


async def test_confirmed_many_to_many_and_excluded_items_preserve_database(db_session):
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, sheet_id, item_id, work_ids = await seed(db_session, with_work=True)
    work = list((await db_session.scalars(select(WorkItem).where(
        WorkItem.project_id == project).order_by(WorkItem.order_index))).all())
    item = await db_session.get(DrawingItem, item_id)
    item.review_status, item.work_item_ids = "confirmed", [str(w) for w in work_ids]
    item.review_fingerprint = fingerprint(work)
    rejected = DrawingItem(sheet_id=sheet_id, name="目錄文字", evidence="保留原文",
                           review_status="rejected", review_note="人員排除",
                           review_fingerprint=fingerprint(work))
    db_session.add(rejected)
    await db_session.commit()
    before = (await db_session.execute(select(DrawingItem.__table__))).mappings().all()
    writes = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        result = await IntegratedChecklistService(db_session).snapshot(project)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    after = (await db_session.execute(select(DrawingItem.__table__))).mappings().all()
    assert before == after and writes == []
    assert result.total == 2
    assert [row.source_status for row in result.items] == ["both", "both"]
    assert all(row.drawings[0].id == item_id for row in result.items)
    assert result.summary.rejected_items == 1
    assert result.summary.matched == 2


async def test_stale_review_returns_to_candidate_without_erasing_note(db_session):
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, _, item_id, work_ids = await seed(db_session, with_work=True)
    item = await db_session.get(DrawingItem, item_id)
    item.review_status, item.work_item_ids = "confirmed", [str(work_ids[0])]
    item.review_fingerprint = "old-fingerprint"
    await db_session.commit()
    result = await IntegratedChecklistService(db_session).snapshot(project)
    assert result.summary.matched == 0
    assert result.items[-1].drawings[0].review_status == "stale"
    assert result.items[-1].drawings[0].review_note == "人工備註不可覆寫"


async def test_project_isolation_and_unknown_project(db_session):
    from app.core.errors import ProjectNotFoundError
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, _, _, _ = await seed(db_session)
    other, _, other_item, _ = await seed(db_session)
    result = await IntegratedChecklistService(db_session).snapshot(project)
    assert all(row.key != f"drawing:{other_item}" for row in result.items)
    with pytest.raises(ProjectNotFoundError):
        await IntegratedChecklistService(db_session).snapshot(uuid.uuid4())


async def test_unavailable_catalog_keeps_stored_bases_and_drawing_candidates(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.checklist import SpecChapter, WorkItemBasis
    from app.services.integrated_checklist_service import IntegratedChecklistService
    project, _, _, work_ids = await seed(db_session, with_work=True)
    spec = Document(filename="本案規範.pdf", file_type="pdf", storage_path="unused-spec.pdf",
                    file_hash=uuid.uuid4().hex)
    db_session.add(spec)
    await db_session.flush()
    db_session.add(ProjectDocument(project_id=project, document_id=spec.id,
                                   role=DocumentRole.SPECIFICATION))
    db_session.add(SpecChapter(document_id=spec.id, code="01725", title="施工測量",
                              version="3.0", first_page=1, last_page=2))
    first = await db_session.get(WorkItem, work_ids[0])
    second = await db_session.get(WorkItem, work_ids[1])
    first.cost_code = "017250001"
    second.cost_code = "033100001"
    db_session.add(WorkItemBasis(work_item_id=first.id, basis_type="law",
                                reference="測量法", detail="第01725章 相關準則",
                                verification_status=None))
    await db_session.commit()
    monkeypatch.setattr(settings, "PCCES_INDEX_PATH", tmp_path / "missing-catalog.json")
    result = await IntegratedChecklistService(db_session).snapshot(project)
    assert result.total == 3
    assert result.items[0].basis_result == "OK"
    assert result.items[0].bases[0].reference == "測量法"
    assert result.items[0].bases[0].verification_status is None
    assert result.items[1].basis_result == "NEEDS_CONFIRMATION"
    assert result.items[-1].source_status == "drawing_candidate"
    assert any("PCCES" in warning and "無法" in warning for warning in result.warnings)
