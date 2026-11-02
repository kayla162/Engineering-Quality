"""品質管理標準表初稿（橘框表單的第一種）：從本案施工規範的一章擷取管理項目與管理標準。

欄位照秀山整體品質計畫的「品質管理標準表」：施工流程｜管理項目｜管理標準｜檢查時機｜檢查方法｜
檢查頻率｜不合格之處理｜管理紀錄｜備註。句子取自秀山施工規範第 03210 章（鋼筋）。
"""

from app.specs.quality_standard import draft_quality_standard

REBAR = (
    "03210 V5.0 第03210章 鋼筋 1. 通則 1.1 本章概要 說明鋼筋之材料、施工及檢驗等相關規定。 "
    "2. 產品 2.1 材料 2.1.1 鋼筋 鋼筋應符合CNS 560之規定，進場時每批應附出廠證明。 "
    "3. 施工 3.1 準備工作 施工前應依設計圖繪製鋼筋施工圖，送請工程司審查。 "
    "3.2 施工方法 3.2.1 鋼筋加工 (4) 所有鋼筋應在常溫下彎曲，非經工程司准許不得加熱為之。 "
    "03210 03210-13 V5.0 2018/01/17 "
    "3.2.3 鋼筋續接 現場銲接完成品，每滿[200 個]對銲接頭為一批，每批取樣1 個，依CNS 12455執行拉伸試驗。 "
    "B. 拉伸試驗之結果，所有試體之抗拉強度，均須符合CNS 560 之規定。 "
    "3.3 檢驗 3.3.3 若試驗結果不合格時，應即停止施工更換材料或改善施工方法。 "
    "3.4 許可差 3.4.1 鋼筋加工及排置之許可差如下：梁、柱內鋼筋之橫向位置：[±6mm]。 "
    "4. 計量與計價 4.1 計量 鋼筋以公噸計量，單價內已包括一切人工、材料不得另行計價。"
)


def rows():
    return draft_quality_standard("03210", "鋼筋", REBAR).rows


def row_with(text: str):
    return next(r for r in rows() if text in r.standard)


class TestWhatBecomesARow:
    def test_sentences_with_a_measurable_criterion_become_rows(self):
        standards = [r.standard for r in rows()]
        assert any("CNS 560" in s for s in standards)
        assert any("±6mm" in s for s in standards)
        assert any("不得加熱" in s for s in standards)

    def test_measurement_and_payment_is_not_quality_control(self):
        assert not any("計價" in r.standard or "公噸" in r.standard for r in rows())

    def test_page_headers_are_removed(self):
        assert not any("2018/01/17" in r.standard for r in rows())

    def test_general_part_is_not_used(self):
        assert not any("本章概要" in r.standard for r in rows())


class TestColumns:
    def test_product_part_is_material(self):
        row = row_with("每批應附出廠證明")
        assert (row.stage, row.item, row.timing) == ("材料", "鋼筋", "材料進場時")
        assert row.record == "材料進場檢驗紀錄"

    def test_construction_subsections_name_the_item(self):
        row = row_with("不得加熱")
        assert (row.stage, row.item) == ("施工中", "鋼筋加工")

    def test_frequency_is_taken_from_the_sentence(self):
        assert row_with("對銲接頭").frequency == "每滿200個對銲接頭為一批，每批取樣1個"

    def test_frequency_left_for_the_qc_staff_when_not_written(self):
        assert row_with("不得加熱").frequency == "（待填）"

    def test_method_follows_the_criterion(self):
        assert row_with("±6mm").method == "量測（米尺／捲尺）"
        assert row_with("抗拉強度").method == "試驗（依規範送驗）"
        assert row_with("不得加熱").method == "目視檢核"

    def test_every_row_cites_its_spec_section(self):
        assert row_with("±6mm").note == "第03210章 3.4.1"
        assert row_with("每批應附出廠證明").note == "第03210章 2.1.1"


def test_the_draft_says_it_is_a_draft():
    draft = draft_quality_standard("03210", "鋼筋", REBAR)
    assert "初稿" in draft.notice and "品管人員" in draft.notice
    assert draft.title == "鋼筋工程品質管理標準表（初稿）"


class TestNoise:
    TEXT = (
        "2. 產品 2.1 材料 2.1.2 鋼筋直徑在9mm 以上者均應使用竹節鋼筋，其他得使用光面鋼筋。 "
        "2.1.6 竹節鋼筋之標示代號、單位 表一竹節鋼筋之標示代號、單位質量及標稱尺度表 D10 0.560 9.53 D13 0.994 12.7。 "
        "2.2 鋼筋機械式續接 2.2.1 模板組立，應符合契約設計圖說所示之位置及尺度等要求。 "
        "3. 施工 3.4 許可差 鋼筋排置之許可差：[±6mm]。 4. 計量與計價"
    )

    def rows(self):
        return draft_quality_standard("03210", "鋼筋", self.TEXT).rows

    def test_tables_are_not_rows(self):
        assert not any(r.standard.startswith("表") or "D10 0.560" in r.standard for r in self.rows())

    def test_a_sentence_start_is_not_an_item_name(self):
        row = next(r for r in self.rows() if "竹節鋼筋" in r.standard)
        assert row.item == "材料"

    def test_section_numbers_are_not_part_of_the_standard(self):
        row = next(r for r in self.rows() if "契約設計圖說" in r.standard)
        assert row.standard.startswith("模板組立")
        assert row.item == "鋼筋機械式續接"
