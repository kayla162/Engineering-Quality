"""章節裡「1.4 相關準則」區塊的定位。

為什麼只取這一段：整章內文丟進抽取器會抽到施工方法描述裡順帶提到的東西，
而「1.4 相關準則」是規範書**自己宣告**的依據清單，精確得多。
實測 86 章裡 75 章有此宣告。
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
        """精確檢查提取的區塊內容。"""
        block = basis_block(CHAPTER)

        assert block == "1.4.1 環境保護相關法規 (1) 噪音管制法 (2) 空氣污染防制法"

    def test_later_sections_are_not_included(self):
        """1.5 資料送審與 2. 產品 的內容不是依據，混進來會抽到不相干的東西。"""
        block = basis_block(CHAPTER)

        assert "施工環境保護執行計畫" not in block
        assert "水泥混凝土" not in block

    def test_the_block_can_end_at_section_two(self):
        """有些章沒有 1.5，1.4 之後直接進 2. 產品。精確檢查內容。"""
        text = "1.4 相關準則 (1) 建築技術規則 2. 產品 2.1 材料 鋼筋應符合規定。"

        block = basis_block(text)

        assert block == "(1) 建築技術規則"
        assert "鋼筋" not in block

    def test_a_chapter_without_the_section_returns_none(self):
        """實測 86 章裡有 11 章沒有此宣告。回 None，不要回空字串假裝有。"""
        assert basis_block("1. 通則 1.1 本章概要 說明施工測量。 3. 執行") is None

    def test_empty_block_returns_none(self):
        """1.4 相關準則 後直接是 1.5，中間沒有內容。"""
        assert basis_block("1.4 相關準則 1.5 資料送審 x") is None

    def test_block_at_end_of_text(self):
        """1.4 相關準則 是章節的最後一部分，沒有 1.5 或 2. 產品。"""
        block = basis_block("1.4 相關準則 (1) 建築技術規則")
        assert block == "(1) 建築技術規則"

    def test_multiple_items_in_single_block(self):
        """正常情況：單一區塊包含多個依據。"""
        block = basis_block("1.4 相關準則 (1) CNS 產品驗證 (2) 建築技術規則 1.5 資料送審 x")
        assert block == "(1) CNS 產品驗證 (2) 建築技術規則"

    def test_no_false_match_for_text_containing_related_standards(self):
        """相關準則 這個詞出現在敘述文字中，不應該被誤認為是區塊頭。"""
        assert basis_block("1.1 本章概要 依相關準則辦理。 3. 執行") is None

    def test_newlines_in_block(self):
        """測試跨行的區塊（實際中 SpecChapterRow.text 會折疊換行，但測試直接驗證邏輯）。"""
        block = basis_block("1.4 相關準則\n(1) A\n1.5 資料送審\nx")
        assert block == "(1) A"

    # 迴歸測試：三個重大缺陷修復驗證
    def test_regression_fractional_number_false_positive(self):
        r"""迴歸：內文有「螺距1.5 」（實際是規格描述，不是小節號）。舊 regex 1\.5\s 無邊界檢查，會誤觸。"""
        # 舊 regex (?=1\.5\s|...) 無左邊界，會在「螺距1.5 」停止，丟失之後的標準代號
        text = "1.4 相關準則 (1) ASTM A108 (2) ASTM A123 螺距1.5 公釐 (3) ASTM A456 1.5 資料送審"
        block = basis_block(text)
        # 新 regex 用 (?<!\S)1\.\d+\s 確保小節號有左邊界，所以會正確捕到所有內容
        assert "ASTM A108" in block
        assert "ASTM A123" in block
        assert "ASTM A456" in block

    def test_regression_alternative_section_number_1_3(self):
        """迴歸：章 01574 職業安全衛生，相關準則 block 編號為 1.3 而非 1.4。舊 regex 硬編 1.4 會漏掉。"""
        text = "1.2 適用範圍 施工安全。 1.3 相關準則 (1) 勞動基準法 (2) 勞動檢查法 1.4 其他 xyz"
        block = basis_block(text)
        # 新 regex 用 1\.\d+ 可以匹配任何小節號
        assert block == "(1) 勞動基準法 (2) 勞動檢查法"
        assert "其他" not in block

    def test_regression_multiple_blocks_same_or_different_numbers(self):
        """迴歸：章 15105/16401 等有多個相關準則區塊。舊 .search() 只取第一個，丟失後面的區塊。"""
        text = "1.4 相關準則 (1) 法規 A 1.5 資料送審 xxx 1.4 相關準則 (2) 法規 B 2. 產品"
        block = basis_block(text)
        # 新版用 finditer 合併所有區塊
        assert "(1) 法規 A" in block
        assert "(2) 法規 B" in block
        # 檢查合併方式
        assert block == "(1) 法規 A (2) 法規 B"
