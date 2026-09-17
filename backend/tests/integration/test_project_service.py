"""專案服務：掛文件、從標單建工項、連到施工綱要規範章節。"""

import pytest

from app.core.enums import DocumentRole
from app.core.errors import AppError, ProjectNotFoundError
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
from tests.factories import make_boq_bytes


@pytest.fixture
async def project(db_session):
    return await ProjectService(db_session).create_project("秀山分隊興建工程")


@pytest.fixture
async def boq_document(db_session):
    return await DocumentService(db_session).upload("標單.xlsx", make_boq_bytes())


class TestCreateProject:
    async def test_project_is_created(self, db_session):
        created = await ProjectService(db_session).create_project("秀山分隊興建工程")

        assert created.name == "秀山分隊興建工程"
        assert created.id is not None

    async def test_unknown_project_raises(self, db_session):
        import uuid

        with pytest.raises(ProjectNotFoundError):
            await ProjectService(db_session).build_work_items(uuid.uuid4())


class TestAttachDocument:
    async def test_document_is_attached_with_a_role(self, db_session, project, boq_document):
        link = await ProjectService(db_session).attach_document(
            project.id, boq_document.id, DocumentRole.BOQ
        )

        assert link.role == DocumentRole.BOQ

    async def test_same_document_twice_is_rejected(self, db_session, project, boq_document):
        service = ProjectService(db_session)
        await service.attach_document(project.id, boq_document.id, DocumentRole.BOQ)

        with pytest.raises(AppError, match="已經"):
            await service.attach_document(project.id, boq_document.id, DocumentRole.CONTRACT)


class TestBuildWorkItems:
    async def test_work_items_come_from_the_boq(self, db_session, project, boq_document):
        service = ProjectService(db_session)
        await service.attach_document(project.id, boq_document.id, DocumentRole.BOQ)

        items = await service.build_work_items(project.id)

        assert any(i.item_no == "壹.一.1.1.1" for i in items)

    async def test_group_rows_are_excluded(self, db_session, project, boq_document):
        """「壹 發包工程費」是群組列，不是工項。"""
        service = ProjectService(db_session)
        await service.attach_document(project.id, boq_document.id, DocumentRole.BOQ)

        items = await service.build_work_items(project.id)

        assert all(i.item_no != "壹" for i in items)

    async def test_cost_code_is_kept(self, db_session, project, boq_document):
        service = ProjectService(db_session)
        await service.attach_document(project.id, boq_document.id, DocumentRole.BOQ)

        items = {i.item_no: i for i in await service.build_work_items(project.id)}

        assert items["壹.一.1.1.1"].cost_code == "0172500004"

    async def test_rebuilding_replaces_instead_of_duplicating(
        self, db_session, project, boq_document
    ):
        """重跑第二次之後要向資料庫重新查詢，不能只比對記憶體裡回傳的清單——
        兩次都是從同一份標單新建出來的，就算沒有先刪除舊資料，長度也會恆等。
        """
        service = ProjectService(db_session)
        await service.attach_document(project.id, boq_document.id, DocumentRole.BOQ)
        first = await service.build_work_items(project.id)

        await service.build_work_items(project.id)

        stored = await service.work_items(project.id)
        assert len(stored) == len(first)

    async def test_project_without_a_boq_says_so(self, db_session, project):
        """沒掛標單就沒有工項來源——要明確講，不要回空清單讓人以為標單裡沒東西。"""
        with pytest.raises(AppError, match="標單"):
            await ProjectService(db_session).build_work_items(project.id)


class TestListProjects:
    async def test_returns_created_projects(self, db_session):
        service = ProjectService(db_session)
        first = await service.create_project("專案一")
        second = await service.create_project("專案二")

        projects = await service.list_projects()

        assert {p.id for p in projects} == {first.id, second.id}


class TestWorkItemsQuery:
    async def test_unknown_project_raises(self, db_session):
        """對不存在的專案要回 404（ProjectNotFoundError），不是空清單。"""
        import uuid

        with pytest.raises(ProjectNotFoundError):
            await ProjectService(db_session).work_items(uuid.uuid4())


class TestSpecChapterLink:
    async def test_cost_code_resolves_to_a_chapter(self, db_session):
        """計價代碼前 5 碼就是施工綱要規範章碼（實測：有代碼的工項裡 85% 對得到）。"""
        chapter = await ProjectService(db_session).spec_chapter_for("0172500004")

        assert chapter is not None
        assert chapter.code == "01725"
        assert "施工測量" in chapter.name

    async def test_unknown_code_returns_none(self, db_session):
        """各機關自訂的專業工項不在共通性工項目錄裡——回 None，不要硬湊。"""
        assert await ProjectService(db_session).spec_chapter_for("9999900001") is None

    async def test_missing_code_returns_none(self, db_session):
        assert await ProjectService(db_session).spec_chapter_for(None) is None
