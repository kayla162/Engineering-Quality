"""工法欄的「要不要選」：真實施工規範（秀山分隊，772 頁）的寫法。

舊版只認「得採用下列工法之一：(1)…(2)…」，真實規範一次都沒有這樣寫，整本讀到 0 筆。
真實的寫法有三種（句子取自真實規範）：

1. 「下列…之一」接方括號清單（工程會綱要規範的慣例：方括號是設計單位該挑的選項）
2. 同一句裡用「或」連接的方括號選項
3. 「續接，應依下列規定辦理」接 (1)(2)(3) 小節，每節一種做法
"""

import pytest

from app.specs.method_reader import method_options

REBAR_SPLICE = (
    "3.2.3 鋼筋續接 鋼筋之續接，應依下列規定辦理。 (1) 搭接 A. 除設計圖說上註明或經工程司核可者外，"
    "鋼筋不得任意搭接。 B. 鋼筋之搭接長度應依鋼筋直徑而定，均應以[混凝土結構設計規範][結構 混凝土施工規範]"
    "規定為準。 (2) 銲接(鋼筋對銲續接) 鋼筋銲接程序應符合[AWS D1.4M]之規定。 "
    "(3) 機械式續接施工要求 承包商應依設計圖說辦理機械式續接。 "
    "3.2.4 鋼筋保護層 (1) 鋼筋保護層厚度，即最外層鋼筋外面與混凝土表面間之淨距離。 (2) 為正確保持鋼筋保護層厚度"
)


class TestRealSpecWording:
    def test_one_of_the_following_with_a_bracket_list(self):
        text = (
            "2.2.1 操作控制方式依升降機之台數、排列方式選擇下列控制方式之一：[單台選擇性集合式控制]"
            "[二台連動選擇性集合式控制][群管理系統控制][單機按鈕控制]。2.2.2 控制設備"
        )
        assert method_options(text) == [
            "單台選擇性集合式控制", "二台連動選擇性集合式控制", "群管理系統控制", "單機按鈕控制",
        ]

    def test_bracket_alternatives_joined_by_or_in_a_sentence_about_method(self):
        text = "開挖施工方式得採[人工開挖][機械開挖]或[人工配合機械開挖]，並應保護既有管線。"
        assert method_options(text) == ["人工開挖", "機械開挖", "人工配合機械開挖"]

    @pytest.mark.parametrize(
        "text",
        [
            # 「3. 施工」節裡的材料選擇：句子沒在講做法，不算工法（真實規範 16132、16010）
            "F.膨脹水泥螺栓應為[鋼質]或[鐵質]。",
            "導管、電纜架、匯流排、盤箱及設備需使用[“U”型槽鐵]或[錨碇螺 栓]固定。",
            "吊掛一支以上導線管時，應使用較大直徑之吊桿，吊桿可採用[全牙式][電鍍螺桿]或[熱浸鍍鋅螺桿]。",
        ],
    )
    def test_bracket_alternatives_of_material_are_not_methods(self, text):
        assert method_options(text) == []

    def test_line_break_spaces_inside_an_option_are_removed(self):
        assert method_options("固定方式採[“U”型槽鐵]或[錨碇螺 栓]。") == ["“U”型槽鐵", "錨碇螺栓"]
        assert method_options("啟動方式為[分相型]或[隱 極型(Shaded Pole Type)]") == ["分相型", "隱極型(Shaded Pole Type)"]

    def test_numbered_sections_after_according_to_the_following(self):
        assert method_options(REBAR_SPLICE) == ["搭接", "銲接", "機械式續接"]

    @pytest.mark.parametrize(
        "text",
        [
            # 方括號裡是標準編號：不是工法
            "導體應符合[CNS 1364][ASTM B3]或[IEC 60228]規定。",
            # 數值
            "再生粒料使用量不得超過全部粒料之[20%]或[30%]。",
            # 只有一個方括號，沒有可以選的
            "鋼筋銲接程序應符合[AWS D1.4M]之規定。",
            # 「下列規定」但不是續接或工法
            "3.2.4 鋼筋保護層 鋼筋保護層應依下列規定辦理。 (1) 保護層厚度 (2) 墊塊",
        ],
    )
    def test_things_that_are_not_a_choice_of_method(self, text):
        assert method_options(text) == []

    def test_the_original_sentence_form_still_works(self):
        assert method_options("3.2 承包商得採用下列工法之一：(1) 鋼模 (2) 木模 (3) 系統模板。3.3 拆模") == [
            "鋼模", "木模", "系統模板",
        ]


class TestOnlyTheConstructionPart:
    """工法是施工方法，只從「3. 施工」節讀。

    真實規範 86 章有 72 章分成「1. 通則／2. 產品／3. 施工／4. 計量與計價」。「2. 產品」的方括號是
    材料或設備的選擇（火警照景盤用[燈泡]或[LED]），讀進來會讓整章的工項都顯示「請檢討使用何種工法」。
    """

    PRODUCT_CHOICE = "1. 通則 1.1 本章概要 2. 產品 2.1 材料 D.照景盤應具[燈泡]或[LED]指示。 "

    def test_a_product_choice_is_not_a_method(self):
        chapter = self.PRODUCT_CHOICE + "3. 施工 3.1 安裝 依設計圖說辦理。 4. 計量與計價 4.1 計量"
        assert method_options(chapter) == []

    def test_a_construction_choice_is_read(self):
        chapter = self.PRODUCT_CHOICE + "3. 施工 " + REBAR_SPLICE + " 4. 計量與計價 4.1 計量"
        assert method_options(chapter) == ["搭接", "銲接", "機械式續接"]

    def test_a_choice_after_the_measurement_part_is_ignored(self):
        chapter = "3. 施工 3.1 依設計圖說辦理。 4. 計量與計價 4.1 施工方式採[人工]或[機械]者分別計價。"
        assert method_options(chapter) == []

    def test_a_chapter_without_parts_is_read_whole(self):
        assert method_options("3.2 承包商得採用下列工法之一：(1) 鋼模 (2) 木模。3.3 拆模") == ["鋼模", "木模"]
