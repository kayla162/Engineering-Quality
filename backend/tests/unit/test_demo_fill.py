"""示範補正：把初稿裡的「（待填）」用 data/demo_fill.json 的示範內容補齊，給展示用。

補上的值一律標「（示範）」——展示時看得出哪些是系統擷取的、哪些是補上的。不補的版本完全不變。
"""

from app.specs.demo_fill import MARK, fill_function_test, fill_method, fill_standard, plan_sections
from app.specs.function_test import LISTED_ONLY, FunctionTestDraft, FunctionTestRow
from app.specs.method_statement import MethodStatement
from app.specs.quality_standard import QualityStandardDraft, StandardRow


def standard_row(stage, frequency):
    return StandardRow(stage, "鋼筋加工", "不得加熱。", "施工中", "目視檢核", frequency, "拆除或修改", "施工自主檢查表", "第03210章 3.2.1")


class TestStandard:
    def test_blank_frequencies_get_a_marked_demo_value_by_stage(self):
        draft = QualityStandardDraft("03210", "鋼筋", "鋼筋工程品質管理標準表（初稿）", rows=[
            standard_row("材料", "（待填）"),
            standard_row("施工中", "（待填）"),
            standard_row("施工中", "每滿200個取樣1個"),
        ])
        filled = fill_standard(draft)
        assert [r.frequency for r in filled.rows] == [
            f"每批進場1次{MARK}", f"每層／每區1次{MARK}", "每滿200個取樣1個",
        ]
        assert "示範補正" in filled.notice

    def test_the_original_draft_is_not_changed(self):
        draft = QualityStandardDraft("03210", "鋼筋", "t", rows=[standard_row("材料", "（待填）")])
        fill_standard(draft)
        assert draft.rows[0].frequency == "（待填）"


class TestFunctionTest:
    def test_listed_only_items_get_a_value_by_keyword(self):
        row = FunctionTestRow("火警警報設備", "絕緣試驗", LISTED_ONLY, "測試時", "試驗（依規範）", "（待填）",
                              "檢修調整或更換", "測試報告", "第13851章 3.2.1")
        (filled,) = fill_function_test(FunctionTestDraft("13851", "火警警報設備", [row])).rows
        assert filled.standard == f"以500V高阻計量測，絕緣電阻值≧0.1MΩ{MARK}"
        assert filled.frequency == f"每台／每回路1次{MARK}"

    def test_unknown_items_get_the_default_value(self):
        row = FunctionTestRow("中央監視", "連線檢查", LISTED_ONLY, "測試時", "目視", "每組",
                              "檢修調整或更換", "檢測紀錄", "第13801章 3.2.1")
        (filled,) = fill_function_test(FunctionTestDraft("13801", "中央監視", [row])).rows
        assert filled.standard == f"依設計圖說與設備型錄之規定值{MARK}"
        assert filled.frequency == "每組"


class TestMethodStatement:
    def test_tools_follow_the_chapter(self):
        statement = MethodStatement("03210", "鋼筋", "鋼筋工程施工要領（初稿）", materials=[])
        filled = fill_method(statement)
        assert filled.tools.startswith("鋼筋切斷機") and filled.tools.endswith(MARK)
        assert filled.materials == [f"依標單與設計圖說{MARK}"]

    def test_unknown_chapters_get_general_tools(self):
        filled = fill_method(MethodStatement("09999", "雜項", "t", materials=["既有材料"]))
        assert filled.tools == f"一般手工具、捲尺、水平儀{MARK}"
        assert filled.materials == ["既有材料"]


def test_plan_sections_cover_every_blank_chapter_without_real_names():
    quality = plan_sections("quality")
    supervision = plan_sections("supervision")
    assert set(quality) == {"一、計畫範圍", "二、管理權責及分工", "三、品管組織及工作職掌", "九、不合格品之管制",
                            "十、矯正與預防措施、內部品質稽核及文件紀錄管理"}
    assert set(supervision) == {"一、監造範圍", "二、監造組織及權責分工", "三、品質計畫與施工計畫審查作業程序",
                                "七、品質稽核及文件紀錄管理"}
    assert all(p.startswith("【示範】") for paragraphs in (*quality.values(), *supervision.values()) for p in paragraphs)
