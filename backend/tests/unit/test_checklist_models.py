"""spec_chapters 與 work_item_bases 的模型。"""

import uuid

import app.models as m
from app.core.config import settings
from app.core.enums import CheckResult, RegulationType
from app.models.checklist import SpecChapter, WorkItemBasis
from app.models.project import Project
from sqlalchemy import delete, select, text


class TestSpecChapter:
    async def test_a_chapter_columns_are_persisted(self, db_session):
        """SpecChapter 欄位持久化後能被重新查出。驗證外鍵、nullable、默認值等都正確。"""
        doc_id = uuid.uuid4()
        chapter = SpecChapter(
            document_id=doc_id,
            code="01725",
            title="施工測量",
            version="3.0",
            first_page=61,
            last_page=63,
        )
        db_session.add(chapter)
        await db_session.flush()
        chapter_id = chapter.id

        # 重新從資料庫查出
        db_session.expire_all()
        result = await db_session.execute(select(SpecChapter).where(SpecChapter.id == chapter_id))
        reloaded = result.scalar_one()

        assert reloaded.code == "01725"
        assert reloaded.title == "施工測量"
        assert reloaded.version == "3.0"
        assert reloaded.first_page == 61
        assert reloaded.last_page == 63

    async def test_chapter_defaults_are_applied(self, db_session):
        """title 和 version 的默認值是空字串。"""
        chapter = SpecChapter(
            document_id=uuid.uuid4(),
            code="01725",
            first_page=61,
            last_page=63,
        )
        db_session.add(chapter)
        await db_session.flush()

        assert chapter.title == ""
        assert chapter.version == ""

    async def test_spec_chapter_cascade_delete(self, db_session):
        """刪除 Document 時，對應的 SpecChapter 行也會被級聯刪除。"""
        # 啟用 SQLite 外鍵約束
        await db_session.execute(text("PRAGMA foreign_keys=ON"))

        # 建立測試用 Document
        from app.models import Document

        doc = Document(
            filename="spec.pdf",
            file_type="pdf",
            storage_path="/tmp/spec.pdf",
            file_hash="abc123",
            tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID),
        )
        db_session.add(doc)
        await db_session.flush()

        chapter = SpecChapter(
            document_id=doc.id,
            code="01725",
            title="施工測量",
            version="3.0",
            first_page=61,
            last_page=63,
        )
        db_session.add(chapter)
        await db_session.flush()

        # 驗證建立成功
        result = await db_session.execute(select(SpecChapter).where(SpecChapter.document_id == doc.id))
        assert result.scalar_one() is not None

        # 刪除 Document（鏡像 ProjectRepository.replace_work_items 的 bulk delete 模式）
        await db_session.execute(delete(Document).where(Document.id == doc.id))
        await db_session.flush()

        # 驗證 SpecChapter 也被刪除
        result = await db_session.execute(select(SpecChapter).where(SpecChapter.document_id == doc.id))
        assert result.scalar() is None


class TestWorkItemBasis:
    async def test_a_basis_columns_are_persisted(self, db_session):
        """WorkItemBasis 欄位持久化後能被重新查出。驗證外鍵、Text 欄位等都正確。"""
        work_item_id = uuid.uuid4()
        basis = WorkItemBasis(
            work_item_id=work_item_id,
            basis_type=RegulationType.STANDARD,
            reference="CNS 2473",
            detail="第01725章 1.4.1",
        )
        db_session.add(basis)
        await db_session.flush()
        basis_id = basis.id

        # 重新從資料庫查出
        db_session.expire_all()
        result = await db_session.execute(select(WorkItemBasis).where(WorkItemBasis.id == basis_id))
        reloaded = result.scalar_one()

        assert reloaded.basis_type == RegulationType.STANDARD
        assert reloaded.reference == "CNS 2473"
        assert reloaded.detail == "第01725章 1.4.1"

    async def test_basis_cascade_delete(self, db_session):
        """刪除 WorkItem 時，對應的 WorkItemBasis 行也會被級聯刪除。"""
        # 啟用 SQLite 外鍵約束
        await db_session.execute(text("PRAGMA foreign_keys=ON"))

        # 建立測試用 Project 和 WorkItem
        project = Project(name="test", tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID))
        db_session.add(project)
        await db_session.flush()

        from app.models import WorkItem

        work_item = WorkItem(
            project_id=project.id,
            item_no="壹.一.1.1.1",
            name="施工測量",
        )
        db_session.add(work_item)
        await db_session.flush()

        basis = WorkItemBasis(
            work_item_id=work_item.id,
            basis_type=RegulationType.STANDARD,
            reference="CNS 2473",
            detail="第01725章 1.4.1",
        )
        db_session.add(basis)
        await db_session.flush()

        # 驗證建立成功
        result = await db_session.execute(
            select(WorkItemBasis).where(WorkItemBasis.work_item_id == work_item.id)
        )
        assert result.scalar_one() is not None

        # 刪除 WorkItem（鏡像 ProjectRepository.replace_work_items 的 bulk delete 模式）
        await db_session.execute(delete(WorkItem).where(WorkItem.id == work_item.id))
        await db_session.flush()

        # 驗證 WorkItemBasis 也被刪除
        result = await db_session.execute(
            select(WorkItemBasis).where(WorkItemBasis.work_item_id == work_item.id)
        )
        assert result.scalar() is None


class TestCheckResult:
    def test_check_result_values_are_exactly_three(self):
        """階段 3 可達的三個值。另兩個（標單有契約圖沒有、請檢討工法）屬階段 2/4。"""
        assert {m.value for m in CheckResult} == {"OK", "SPEC_NOT_INCLUDED", "NEEDS_CONFIRMATION"}


class TestRegistration:
    def test_models_are_registered_in_app_models(self):
        """SpecChapter 和 WorkItemBasis 在 app.models 中註冊，Alembic 才看得到。"""
        assert m.SpecChapter is SpecChapter
        assert m.WorkItemBasis is WorkItemBasis
        assert {"SpecChapter", "WorkItemBasis"} <= set(m.__all__)
