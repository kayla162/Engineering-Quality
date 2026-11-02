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

    def test_bracket_alternatives_joined_by_or(self):
        text = "吊掛一支以上導線管時，應使用較大直徑之吊桿，吊桿可採用[全牙式][電鍍螺桿]或[熱浸鍍鋅螺桿]。"
        assert method_options(text) == ["全牙式", "電鍍螺桿", "熱浸鍍鋅螺桿"]

    def test_line_break_spaces_inside_an_option_are_removed(self):
        text = "需使用[“U”型槽鐵]或[錨碇螺 栓]，電動機須為[分相型(Split-phase)]或[隱 極型(Shaded Pole Type)]。"
        assert method_options(text) == ["“U”型槽鐵", "錨碇螺栓"]
        assert method_options("須為[分相型]或[隱 極型(Shaded Pole Type)]") == ["分相型", "隱極型(Shaded Pole Type)"]

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
