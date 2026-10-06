"""章節裡「1.4 相關準則」區塊的定位。

為什麼只取這一段：整章內文丟進抽取器會抽到施工方法描述裡順帶提到的東西，
而「1.4 相關準則」是規範書**自己宣告**的依據清單，精確得多。
實測 86 章裡 74 章有這一段。
"""

from app.specs import basis_block

CHAPTER = (
    "01572 01572-1 V9.0 第01572 章V9.0 環境保護 "
    "1. 通則 1.1 本章概要 說明環境保護工作。 "
    "1.3 相關章節 1.3.1 第01330 章--資料送審 "
    "1.4 相關準則 1.4.1 環境保護相關法規 (1) 噪音管制法 (2) 空氣污染防制法 "
    "1.5 資料送審 承包商應提出施工環境保護執行計畫。 "
    "2. 產品 2.1 材料 水泥混凝土材料規格應符合第03050 章之規定。"
)


class TestBasisBlock:
    def test_the_block_between_1_4_and_1_5_is_returned(self):
        block = basis_block(CHAPTER)

        assert "噪音管制法" in block
        assert "空氣污染防制法" in block

    def test_later_sections_are_not_included(self):
        """1.5 資料送審與 2. 產品 的內容不是依據，混進來會抽到不相干的東西。"""
        block = basis_block(CHAPTER)

        assert "施工環境保護執行計畫" not in block
        assert "水泥混凝土" not in block

    def test_the_block_can_end_at_section_two(self):
        """有些章沒有 1.5，1.4 之後直接進 2. 產品。"""
        text = "1.4 相關準則 (1) 建築技術規則 2. 產品 2.1 材料 鋼筋應符合規定。"

        block = basis_block(text)

        assert "建築技術規則" in block
        assert "鋼筋" not in block

    def test_a_chapter_without_the_section_returns_none(self):
        """實測 86 章裡有 12 章沒有這一段。回 None，不要回空字串假裝有。"""
        assert basis_block("1. 通則 1.1 本章概要 說明施工測量。 3. 執行") is None
