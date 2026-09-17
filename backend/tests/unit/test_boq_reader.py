"""標單讀取器。

真實標單（新北市消防局秀山分隊）的形狀：工作表「契約詳細表」，表頭在第 6 列，
欄位 `項 次 / 項目及說明 / 單 位 / 數 量 / 單 價 / 複 價 / 編碼(備註)`。

表頭用**文字定位**而不是寫死列號——各家標單的前置說明列數不一樣。
"""

import pytest

from app.workitems.boq_reader import BoqFormatError, read_boq
from tests.factories import BOQ_HEADER, make_boq_bytes


@pytest.fixture
def write(tmp_path):
    def _write(data: bytes, suffix: str = ".xlsx"):
        path = tmp_path / f"標單{suffix}"
        path.write_bytes(data)
        return path

    return _write


class TestHeaderLocation:
    def test_header_is_found_by_text_not_row_number(self, write):
        """表頭前面有幾列標題不固定，不可以寫死列號。"""
        rows = [["說明一", "", "", "", "", "", ""]] * 9 + [BOQ_HEADER] + [
            ["壹.一", "施工測量", "式", 1, 1, 1, "0172500004"]
        ]

        assert [r.item_no for r in read_boq(write(make_boq_bytes(rows=rows)))] == ["壹.一"]

    def test_full_width_spaces_in_header_are_ignored(self, write):
        """真實表頭寫成「項  目  及  說  明」，中間有全形空白。"""
        assert read_boq(write(make_boq_bytes()))

    def test_missing_header_raises(self, write):
        rows = [["甲", "乙"], ["丙", "丁"]]

        with pytest.raises(BoqFormatError, match="表頭"):
            read_boq(write(make_boq_bytes(rows=rows)))


class TestRows:
    def test_detail_rows_are_read(self, write):
        rows = read_boq(write(make_boq_bytes()))
        first = next(r for r in rows if r.item_no == "壹.一.1.1.1")

        assert first.name.startswith("施工測量，基地測量及鑑界費")
        assert first.unit == "式"
        assert first.quantity == "1"

    def test_group_rows_are_not_leaves(self, write):
        """「壹」這種群組列沒有單位，不是實際工項。"""
        rows = {r.item_no: r for r in read_boq(write(make_boq_bytes()))}

        assert rows["壹"].is_leaf is False
        assert rows["壹.一.1.1.1"].is_leaf is True

    def test_wrapped_name_is_rejoined(self, write):
        """說明跨列續寫，接起來時中間不能插分隔符號。"""
        rows = {r.item_no: r for r in read_boq(write(make_boq_bytes()))}

        assert rows["壹.一.1.1.1"].name == "施工測量，基地測量及鑑界費施工中由承商建置，採租用"

    def test_header_row_itself_is_not_a_work_item(self, write):
        assert all(r.item_no != "項 次" for r in read_boq(write(make_boq_bytes())))


class TestCostCode:
    def test_ten_digit_code_is_extracted(self, write):
        rows = {r.item_no: r for r in read_boq(write(make_boq_bytes()))}

        assert rows["壹.一.1.1.1"].cost_code == "0172500004"

    def test_trailing_marker_is_stripped(self, write):
        """真實資料寫成「0172500004,*」，逗號後面的記號不是代碼的一部分。"""
        rows = {r.item_no: r for r in read_boq(write(make_boq_bytes()))}

        assert "," not in rows["壹.一.1.1.1"].cost_code

    def test_missing_code_is_none(self, write):
        rows = {r.item_no: r for r in read_boq(write(make_boq_bytes()))}

        assert rows["壹.一.1.3.1"].cost_code is None


class TestLegacyXls:
    def test_xls_is_read(self, write):
        """真實標單就是 OLE2 格式的 .xls。"""
        path = write(make_boq_bytes(suffix=".xls"), suffix=".xls")

        assert any(r.item_no == "壹.一.1.1.1" for r in read_boq(path))
