"""專案、專案文件角色與工項的資料模型。"""

import uuid

import pytest

from app.core.enums import DocumentRole
from app.models.project import Project, ProjectDocument, WorkItem


class TestDocumentRole:
    def test_covers_the_four_green_box_roles(self):
        """綠框：契約、契約圖、施工規範，加上工項來源的標單。"""
        assert {
            DocumentRole.BOQ,
            DocumentRole.CONTRACT,
            DocumentRole.DRAWING,
            DocumentRole.SPECIFICATION,
        } <= set(DocumentRole)

    def test_values_are_strings(self):
        """資料庫欄位存字串，不用原生 enum（enums.py 的規則）。"""
        assert DocumentRole.BOQ == "boq"


class TestModels:
    def test_project_holds_documents_and_work_items(self, db_session):
        project = Project(name="秀山分隊興建工程")

        assert project.documents == []
        assert project.work_items == []

    def test_work_item_leaf_flag_comes_from_unit(self):
        assert WorkItem(item_no="壹.一.1.1.1", name="施工測量", unit="式").is_leaf is True
        assert WorkItem(item_no="壹", name="發包工程費", unit="").is_leaf is False

    def test_project_document_records_a_role(self):
        link = ProjectDocument(
            project_id=uuid.uuid4(), document_id=uuid.uuid4(), role=DocumentRole.BOQ
        )

        assert link.role == "boq"
