"""施工要領與施工流程圖初稿（橘框表單）。

秀山整體品質計畫的「3.7鋼筋組立工程施工要領」是：施工機具、使用材料、施工方法步驟（施工規範第3節
各小節改寫，「工程司」換成「監造單位」）與流程圖（★為檢驗停留點）。初稿照這個結構組。
"""

import io

import docx

from app.specs.method_statement import draft_method_statement, method_statement_docx

SPEC = (
    "第03210章 鋼筋 1. 通則 1.1 本章概要 說明鋼筋之材料、施工及檢驗。 "
    "2. 產品 2.1 材料 2.1.1 鋼筋 鋼筋須符合CNS 560之規定。 "
    "3. 施工 3.1 準備工作 3.1.1 施工前應依設計圖繪製鋼筋施工圖，送請工程司審查。 "
    "3.2 施工方法 3.2.1 鋼筋加工 所有鋼筋應在常溫下彎曲，非經工程司准許不得加熱為之。"
    "鋼筋有一部分已埋入混凝土中者，其外露部分不得再行彎曲。 "
    "03210 03210-13 V5.0 2018/01/17 "
    "3.2.2 鋼筋排紮及組立 鋼筋交叉點應以黑鐵絲結紮牢固。 "
    "3.2.3 鋼筋續接 鋼筋之續接，應依下列規定辦理。 "
    "3.3 檢驗 3.3.1 鋼筋排紮組立完成後，應經工程司檢查認可後始得澆置混凝土。 "
    "3.4 許可差 3.4.1 梁、柱內鋼筋之橫向位置：[±6mm]。 "
    "4. 計量與計價 4.1 計量 鋼筋以公噸計量。"
)
MATERIALS = ["鋼筋，SD280W，中拉力鋼筋及彎紮組立(#3)", "鋼筋，SD420W，高拉力鋼筋及彎紮組立(#4~#8)", "鋼筋，SD280W，中拉力鋼筋及彎紮組立(#3)"]


def draft():
    return draft_method_statement("03210", "鋼筋", SPEC, MATERIALS)


class TestSteps:
    def test_steps_follow_the_construction_part_in_order(self):
        assert [s.title for s in draft().steps] == ["準備工作", "鋼筋加工", "鋼筋排紮及組立", "鋼筋續接", "檢驗", "許可差"]

    def test_the_engineer_becomes_the_supervisor(self):
        cutting = next(s for s in draft().steps if s.title == "鋼筋加工")
        assert cutting.sentences[0] == "所有鋼筋應在常溫下彎曲，非經監造單位准許不得加熱為之。"
        assert all("工程司" not in s for step in draft().steps for s in step.sentences)

    def test_inspection_steps_are_hold_points(self):
        holds = {s.title: s.hold_point for s in draft().steps}
        assert holds["檢驗"] and holds["許可差"]
        assert not holds["鋼筋加工"]

    def test_page_headers_and_measurement_are_not_steps(self):
        text = " ".join(s for step in draft().steps for s in step.sentences)
        assert "2018/01/17" not in text and "公噸" not in text


class TestOtherParts:
    def test_materials_come_from_the_boq_items_of_the_chapter(self):
        assert draft().materials == ["鋼筋，SD280W，中拉力鋼筋及彎紮組立(#3)", "鋼筋，SD420W，高拉力鋼筋及彎紮組立(#4~#8)"]

    def test_tools_are_left_for_the_site(self):
        assert draft().tools == "（待填）"

    def test_title_and_notice(self):
        assert draft().title == "鋼筋工程施工要領（初稿）"
        assert "初稿" in draft().notice

    def test_the_flowchart_marks_hold_points(self):
        assert draft().flow == ["準備工作", "鋼筋加工", "鋼筋排紮及組立", "鋼筋續接", "★檢驗", "★許可差"]


def test_word_export_has_the_four_parts_and_the_flow():
    document = docx.Document(io.BytesIO(method_statement_docx(draft())))
    text = "\n".join(p.text for p in document.paragraphs)
    text += "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
    for expected in ("鋼筋工程施工要領（初稿）", "施工機具", "使用材料", "施工方法、步驟", "施工流程圖",
                     "鋼筋，SD420W", "監造單位准許", "★檢驗", "★為檢驗停留點"):
        assert expected in text, expected


def test_fragments_and_repeated_titles_do_not_make_extra_steps():
    """真實規範的雜訊：「本章之第 2.2.2 款」切出的一個字「款」、12 字截斷的句子開頭、被別的小節隔開的同名小節。"""
    spec = (
        "3. 施工 3.3 檢驗 3.3.1 鋼筋排紮組立完成後，應經工程司檢查認可。 "
        "本章之第 2.2.2 款 每滿200個取樣1個做試驗。 "
        "3.3.2 鋼筋機械式續接後之外觀檢查係視其續接部位之形狀是否合於規定。 "
        "3.3 檢驗 試驗結果不合格時應即停止施工。 4. 計量與計價"
    )
    steps = draft_method_statement("03210", "鋼筋", spec, []).steps
    assert [s.title for s in steps] == ["檢驗"]
    # 「本章之第 2.2.2 款 每滿200個…」在真實規範裡是抽樣表攤平的一列，數字多，當表格略過
    assert len(steps[0].sentences) == 3
