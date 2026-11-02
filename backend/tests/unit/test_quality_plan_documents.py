"""從整體品質計畫抽出承攬廠商自有文件，產生企業內部文件清單（scripts/generate_enterprise_template.py）。

真實計畫書（秀山分隊整體品質計畫）不進版控，這裡用同樣寫法的小 docx 代替：
各分項工程的品質管理標準、施工要領、自主檢查表都以「表 四-3 ○○」這類標題列出。
"""

import importlib.util
import io
from pathlib import Path

import docx
import pytest

from app.core.enums import RegulationStatus
from app.services.enterprise_document_service import parse_workbook

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "generate_enterprise_template.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_enterprise_template", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plan(tmp_path):
    doc = docx.Document()
    # 目錄（表格目錄）：同一個標題帶 tab 與頁碼，不能重複算
    doc.add_paragraph("表 四-3 假設工程品質管理標準表\t38")
    doc.add_paragraph("本工程日後於各分項工程施工前將提出之品質管理標準")
    doc.add_paragraph("3.7鋼筋組立工程施工要領")
    doc.add_paragraph("圖 三-7鋼筋組立工程施工步驟流程圖", style="Caption")
    doc.add_paragraph("表 四-1各分項工程品質管理標準一覽表", style="Caption")
    doc.add_paragraph("表 四-2 品質管理標準表")
    doc.add_paragraph("表 四-3 假設工程品質管理標準表")
    doc.add_paragraph("表 六-8電梯設備功能運轉測試抽驗標準表", style="Caption")
    doc.add_paragraph("表 七-2自主檢查表", style="Caption")
    doc.add_paragraph("表 七-11 FS版鋼筋組立工程施工自主檢查表", style="Caption")
    doc.add_paragraph("表 八-2不合格品改正紀錄表", style="Caption")
    doc.add_paragraph("表 八-4合格品標籤", style="Caption")
    doc.add_paragraph("表 四-6 開挖及土方工程品質管理標準表")
    # 一覽表：大部分分項「於分項施工計畫內訂定」，只出現在這裡
    overview = doc.add_table(rows=0, cols=3)
    for row in [
        ("項次", "作業名稱", "備註"),
        ("", "假設工程品質管理標準", "詳表 四-3"),
        ("", "開挖擋土及土方工程品質管理標準", "詳表 四-6"),
        ("", "鋼筋組立工程品質管理標準", "詳表 四-10~11"),
        ("", "門窗工程品質管理標準", "於分項施工計畫內訂定"),
    ]:
        cells = overview.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value
    path = tmp_path / "整體品質計畫.docx"
    doc.save(path)
    return path


class TestContractorDocuments:
    def test_names_come_from_numbered_titles(self, generator, plan):
        names = [d.name for d in generator.contractor_documents(plan)]
        assert names == [
            "假設工程品質管理標準表",
            "鋼筋組立工程施工要領",
            "電梯設備功能運轉測試抽驗標準表",
            "FS版鋼筋組立工程施工自主檢查表",
            "不合格品改正紀錄表",
            "開挖及土方工程品質管理標準表",
            "鋼筋組立工程品質管理標準",
            "門窗工程品質管理標準",
        ]

    def test_an_overview_row_pointing_at_a_table_is_an_alias_of_it(self, generator, plan):
        docs = {d.name: d for d in generator.contractor_documents(plan)}
        assert "開挖擋土及土方工程品質管理標準" in docs["開挖及土方工程品質管理標準表"].aliases
        assert "開挖擋土及土方工程品質管理標準" not in docs

    def test_an_overview_row_keeps_its_remark(self, generator, plan):
        docs = {d.name: d for d in generator.contractor_documents(plan)}
        assert docs["門窗工程品質管理標準"].remark == "於分項施工計畫內訂定"
        assert docs["門窗工程品質管理標準"].doc_type == "檢驗標準"

    def test_overviews_flowcharts_and_body_text_are_not_documents(self, generator, plan):
        names = {d.name for d in generator.contractor_documents(plan)}
        assert not any("一覽表" in n or "流程圖" in n or "標籤" in n for n in names)
        assert "自主檢查表" not in names
        assert "品質管理標準表" not in names

    def test_each_kind_maps_to_a_template_type(self, generator, plan):
        types = {d.name: d.doc_type for d in generator.contractor_documents(plan)}
        assert types["假設工程品質管理標準表"] == "檢驗標準"
        assert types["電梯設備功能運轉測試抽驗標準表"] == "檢驗標準"
        assert types["鋼筋組立工程施工要領"] == "作業標準（SOP）"
        assert types["FS版鋼筋組立工程施工自主檢查表"] == "表單"
        assert types["不合格品改正紀錄表"] == "表單"

    def test_a_trailing_table_word_becomes_an_alias(self, generator, plan):
        docs = {d.name: d for d in generator.contractor_documents(plan)}
        assert "假設工程品質管理標準" in docs["假設工程品質管理標準表"].aliases


class TestQualityPlanList:
    def test_the_list_imports_and_is_marked_as_partly_fake(self, generator, plan, tmp_path):
        out = tmp_path / "清單.xlsx"
        generator.build_from_quality_plan(plan, out)

        parsed = parse_workbook(out.read_bytes())
        assert [p.name for p in parsed] == [d.name for d in generator.contractor_documents(plan)]
        assert len({p.doc_number for p in parsed}) == len(parsed)
        assert all(p.status == RegulationStatus.ACTIVE for p in parsed)
        assert all("假資料" in (p.note or "") for p in parsed)
        door = next(p for p in parsed if p.name == "門窗工程品質管理標準")
        assert "於分項施工計畫內訂定" in door.note

    def test_the_guide_sheet_says_where_the_names_came_from(self, generator, plan, tmp_path):
        out = tmp_path / "清單.xlsx"
        generator.build_from_quality_plan(plan, out)

        from openpyxl import load_workbook

        guide = load_workbook(io.BytesIO(out.read_bytes()))["說明"]
        text = " ".join(str(c.value) for row in guide.iter_rows() for c in row if c.value)
        assert "整體品質計畫.docx" in text
        assert "假資料" in text
