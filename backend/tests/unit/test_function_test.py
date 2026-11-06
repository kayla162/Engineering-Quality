"""設備功能運轉檢測標準表（承攬廠商）與測試抽驗標準表（監造）初稿。

邏輯圖兩個橘框都標了「※設備功能運轉檢測程序及標準」。秀山整體品質計畫第六章的表：
工程項目｜管理項目｜管理標準｜檢查時機｜檢查方法｜檢查頻率｜不合標準之處置方法｜管理紀錄｜備註。
來源是機電章（11／13／14／15／16 開頭）「3. 施工」裡的測試、試驗、試運轉、檢驗小節。
"""

import io

from openpyxl import load_workbook

from app.specs.function_test import EQUIPMENT_DIVISIONS, draft_function_test, function_test_xlsx

FIRE_ALARM = (
    "第13851章 火警警報設備 2. 產品 2.1 受信總機 受信總機應符合CNS規定。 "
    "3. 施工 3.1 安裝 3.1.1 受信總機應垂直裝設於中控室。 "
    "3.2 現場試驗 3.2.1 絕緣試驗 以直流500V高阻計測定，絕緣電阻值應在0.1MΩ以上。 "
    "3.2.2 動作試驗 每一回路之探測器均應測試，受信總機應正確顯示火警區域。 "
    "4. 計量與計價 4.1 計量 以組計量。"
)


def rows():
    return draft_function_test("13851", "火警警報設備", FIRE_ALARM).rows


class TestRows:
    def test_only_test_subsections_become_rows(self):
        items = [r.item for r in rows()]
        assert items == ["絕緣試驗", "動作試驗"]

    def test_columns_follow_the_quality_plan(self):
        insulation, action = rows()
        assert insulation.equipment == "火警警報設備"
        assert insulation.timing == "測試時"
        assert insulation.method == "儀器量測"
        assert action.method == "實際操作"
        assert action.frequency == "每一回路"
        assert insulation.handling == "檢修調整或更換"
        assert insulation.record == "測試報告"
        assert insulation.note == "第13851章 3.2.1"

    def test_the_standard_is_the_sentence(self):
        assert "0.1MΩ以上" in rows()[0].standard


def test_only_equipment_chapters_have_function_tests():
    assert {"11", "13", "14", "15", "16"} == set(EQUIPMENT_DIVISIONS)


def test_excel_has_the_contractor_and_supervisor_sheets():
    draft = draft_function_test("13851", "火警警報設備", FIRE_ALARM)
    book = load_workbook(io.BytesIO(function_test_xlsx(draft)))
    assert book.sheetnames == ["設備功能運轉檢測標準表", "設備功能運轉測試抽驗標準表"]
    own, supervision = book.worksheets
    assert own["A1"].value == "火警警報設備功能運轉檢測標準表（初稿）"
    assert [c.value for c in own[3]][:3] == ["工程項目", "管理項目", "管理標準"]
    assert supervision["A1"].value == "火警警報設備功能運轉測試抽驗標準表（初稿）"
    assert [c.value for c in supervision[3]][:3] == ["工程項目", "抽驗項目", "抽驗標準"]
    assert "初稿" in own["A2"].value


class TestRealSpecTemplates:
    """秀山規範的機電章多是沒改過的綱要規範範本：只列測試項目，判定值空著。"""

    TEMPLATE = (
        "3. 施工 3.2 現場試驗： 設備安裝後應施行現場試驗。 "
        "3.2.1 絕緣試驗 3.2.2 動作試驗 3.2.3 性能檢查 3.2.4 綜合檢查 3.2.5 [ ] "
        "3.3 [訓練] 3.3.1 [承包商於本工程測試完畢經洽業主決定適當時間，負責提供人員訓練]。 4. 計量與計價"
    )

    def rows(self):
        return draft_function_test("13851", "火警警報設備", self.TEMPLATE).rows

    def test_listed_test_items_become_rows_waiting_for_values(self):
        listed = {r.item: r.standard for r in self.rows()}
        for item in ("絕緣試驗", "動作試驗", "性能檢查", "綜合檢查"):
            assert listed[item] == "（規範只列項目，判定值待填）"

    def test_training_is_not_a_test(self):
        assert not any("訓練" in r.standard for r in self.rows())


def test_a_sentence_like_title_does_not_make_a_test_section():
    """16061「3.3.6 在適當地方加裝接地測試裝置」的「標題」是句子開頭，含「測試」也不是測試小節。"""
    spec = "3. 施工 3.3 接地之安裝 3.3.6 在適當地方加裝接地測試裝置。 3.5 現場測試 3.5.1 接地電阻應小於10Ω。 4. 計量"
    assert [r.item for r in draft_function_test("16061", "接地", spec).rows] == ["現場測試"]


def test_tolerances_are_measured_and_tests_are_not_visual():
    spec = "3. 施工 3.2 測試 3.2.1 著樓試驗：許可差在±5mm 以內。 3.2.2 安全裝置試驗。 4. 計量"
    landing, safety = draft_function_test("14210", "電動升降機", spec).rows
    assert landing.method == "儀器量測"
    assert safety.method == "試驗（依規範）"


def test_bracketed_choices_are_kept_without_brackets():
    """「[500V]」是綱要規範待確認的值：拿掉括號、內容要留下。"""
    spec = "3. 施工 3.2 現場測試 3.2.1 以直流[500V]高阻計測定絕緣電阻。 4. 計量"
    (row,) = draft_function_test("16010", "基本電氣規則", spec).rows
    assert "直流500V高阻計" in row.standard


class TestSectionsTheOldReaderMissed:
    """秀山規範 35 個機電章原本有 8 章產生不出列（2026-11 實測）。"""

    def test_a_measurement_like_3_3m_does_not_replace_the_section_title(self):
        spec = ("3. 施工 3.3 檢驗 3.3.1 污水管路系統應施以水壓試驗。 "
                "分層試驗時，使管路任一點均能受到 3.3m 以上之水壓。 4. 計量")
        rows = draft_function_test("15151", "污水管路系統", spec).rows
        assert rows and {r.item for r in rows} == {"檢驗"}

    def test_a_title_followed_by_a_colon_and_a_sentence_is_still_a_test_section(self):
        spec = "3. 施工 3.1 安裝 3.1.1 現場配線依規則辦理。 3.2 現場試驗：系統完成後應做絕緣測試及紀錄。 4. 計量"
        (row,) = draft_function_test("16120", "電線及電纜", spec).rows
        assert row.item == "現場試驗" and "絕緣測試" in row.standard

    def test_a_test_clause_without_a_full_stop_is_kept_whole(self):
        spec = "3. 施工 3.3 竣工 3.3.1 提送竣工圖 3.4 檢驗 3.4.1 依據契約及主管機關技術規範之規定辦理檢驗 3.5 訓練 4. 計量"
        (row,) = draft_function_test("16711", "建築物電信電纜", spec).rows
        assert row.item == "檢驗" and row.standard.startswith("依據契約") and row.note == "第16711章 3.4.1"

    def test_a_chapter_without_any_test_section_uses_the_generic_template(self):
        spec = "3. 施工 3.1 安裝 3.1.1 依製造廠說明書安裝。 4. 計量"
        rows = draft_function_test("16413", "漏電斷路器", spec).rows
        assert [r.item for r in rows][0] == "漏電跳脫動作測試（測試按鈕）"
        assert all(r.note.startswith("通用範本") and r.standard == "（規範只列項目，判定值待填）" for r in rows)

    def test_an_unknown_chapter_without_tests_stays_empty(self):
        assert draft_function_test("11999", "其他設備", "3. 施工 3.1 安裝。 4. 計量").rows == []
