"""由品質管理標準表初稿衍生的另外兩種橘框表單：承攬廠商的自主檢查表、監造單位的抽查標準表。

三種表從同一份初稿出來，檢查項目與標準才會一致（整體品質計畫與監造計畫要互相對應）。
自主檢查表照秀山整體品質計畫的格式：檢查項目｜設計圖說、規範之檢查標準｜實際檢查情形｜檢查結果。
"""

import io

from openpyxl import load_workbook

from app.specs.derived_forms import (
    self_inspection,
    self_inspection_xlsx,
    supervision_standard,
    supervision_xlsx,
)
from app.specs.quality_standard import QualityStandardDraft, StandardRow


def row(stage, item, standard, method="目視檢核", frequency="（待填）"):
    timing = {"材料": "材料進場時", "施工前": "施工前", "施工後": "完成後"}.get(stage, "施工中")
    return StandardRow(stage, item, standard, timing, method, frequency, "拆除或修改", "施工自主檢查表", f"第03210章 {item}")


DRAFT = QualityStandardDraft(
    chapter_code="03210",
    chapter_title="鋼筋",
    title="鋼筋工程品質管理標準表（初稿）",
    rows=[
        row("材料", "鋼筋", "鋼筋須符合CNS 560之規定。", "試驗（依規範送驗）", "每批取樣1組"),
        row("施工前", "準備工作", "施工前應依設計圖繪製鋼筋施工圖。"),
        row("施工中", "鋼筋加工", "所有鋼筋應在常溫下彎曲，不得加熱。"),
        row("施工中", "許可差", "梁、柱內鋼筋之橫向位置：±6mm。", "量測（米尺／捲尺）"),
        row("施工後", "檢驗", "排紮組立完成後應經工程司檢查。"),
    ],
)


class TestSelfInspection:
    def test_rows_are_grouped_by_construction_stage_without_materials(self):
        form = self_inspection(DRAFT)
        assert [section.stage for section in form.sections] == ["施工前", "施工中", "施工後"]
        assert [r.item for r in form.sections[1].rows] == ["鋼筋加工", "許可差"]
        assert all(r.item != "鋼筋" for s in form.sections for r in s.rows)

    def test_the_standard_column_is_filled_and_the_site_columns_are_blank(self):
        (first,) = self_inspection(DRAFT).sections[0].rows
        assert first.standard == "施工前應依設計圖繪製鋼筋施工圖。"

    def test_title_and_draft_notice(self):
        form = self_inspection(DRAFT)
        assert form.title == "鋼筋工程施工自主檢查表（初稿）"
        assert "初稿" in form.notice

    def test_excel_follows_the_quality_plan_layout(self):
        sheet = load_workbook(io.BytesIO(self_inspection_xlsx(self_inspection(DRAFT)))).active
        texts = [str(c.value) for r in sheet.iter_rows() for c in r if c.value]
        for expected in ("工程名稱", "分項工程名稱", "檢查位置", "設計圖說、規範之檢查標準（定量／定性）",
                         "實際檢查情形（敘述檢查值）", "檢查結果", "施工中", "許可差", "工地主任", "品管人員"):
            assert any(expected in t for t in texts), expected
        assert any("○檢查合格" in t for t in texts)


class TestSupervisionStandard:
    def test_construction_rows_become_inspection_standards(self):
        form = supervision_standard(DRAFT)
        assert form.title == "鋼筋工程施工抽查標準表（初稿）"
        assert [r.item for r in form.inspection_rows] == ["準備工作", "鋼筋加工", "許可差", "檢驗"]
        tolerance = form.inspection_rows[2]
        assert (tolerance.timing, tolerance.method, tolerance.basis) == ("施工中", "量測（米尺／捲尺）", "第03210章 許可差")

    def test_material_rows_become_material_sampling_standards(self):
        (material,) = supervision_standard(DRAFT).material_rows
        assert (material.item, material.frequency) == ("鋼筋", "每批取樣1組")

    def test_excel_has_both_sheets(self):
        book = load_workbook(io.BytesIO(supervision_xlsx(supervision_standard(DRAFT))))
        assert book.sheetnames == ["施工抽查標準表", "材料抽驗標準表"]
        header = [c.value for c in book["施工抽查標準表"][3]]
        assert header == ["管理項目", "抽查標準（定量／定性）", "抽查時機", "抽查方法", "抽查頻率", "依據"]
