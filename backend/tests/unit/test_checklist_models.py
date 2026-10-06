"""spec_chapters 與 work_item_bases 的模型。"""

import uuid

from app.core.enums import CheckResult, RegulationType
from app.models.checklist import SpecChapter, WorkItemBasis


class TestSpecChapter:
    async def test_a_chapter_is_persisted(self, db_session):
        chapter = SpecChapter(
            document_id=uuid.uuid4(),
            code="01725",
            title="施工測量",
            version="3.0",
            first_page=61,
            last_page=63,
        )
        db_session.add(chapter)
        await db_session.flush()

        assert chapter.id is not None


class TestWorkItemBasis:
    async def test_a_basis_is_persisted(self, db_session):
        basis = WorkItemBasis(
            work_item_id=uuid.uuid4(),
            basis_type=RegulationType.STANDARD,
            reference="CNS 2473",
            detail="第01725章 1.4.1",
        )
        db_session.add(basis)
        await db_session.flush()

        assert basis.id is not None


class TestCheckResult:
    def test_the_three_reachable_values_exist(self):
        """階段 3 可達的三個值。另兩個（標單有契約圖沒有、請檢討工法）屬階段 2/4。"""
        assert CheckResult.OK == "OK"
        assert CheckResult.SPEC_NOT_INCLUDED == "SPEC_NOT_INCLUDED"
        assert CheckResult.NEEDS_CONFIRMATION == "NEEDS_CONFIRMATION"
