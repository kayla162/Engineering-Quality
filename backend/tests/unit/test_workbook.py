"""低階活頁簿讀取：ExcelParser 與標單讀取器共用。

和 ExcelParser 的差別：這一層**保留欄位位置**（空格留成 ""），
因為標單要知道「第 0 欄是項次、第 6 欄是計價代碼」。
"""

import pytest

from app.core.errors import UnprocessableDocumentError
from app.parsers.workbook import format_cell, read_workbook
from tests.factories import make_xls_bytes, make_xlsx_bytes


@pytest.fixture
def write(tmp_path):
    def _write(data: bytes, suffix: str = ".xlsx"):
        path = tmp_path / f"活頁簿{suffix}"
        path.write_bytes(data)
        return path

    return _write


class TestReadWorkbook:
    def test_empty_cells_keep_their_position(self, write):
        rows = read_workbook(write(make_xlsx_bytes(rows=[["甲", "", "丙"]])))

        assert rows[0].cells == ["甲", "", "丙"]

    def test_sheet_name_and_row_index(self, write):
        rows = read_workbook(write(make_xlsx_bytes(rows=[["一"], ["二"]])))

        assert [(r.sheet, r.index) for r in rows] == [("契約詳細表", 0), ("契約詳細表", 1)]

    def test_row_index_restarts_per_sheet(self, write):
        data = make_xlsx_bytes(rows=[["一"]], extra_sheet=("契約總表", [["甲"], ["乙"]]))
        rows = read_workbook(write(data))

        assert [(r.sheet, r.index) for r in rows] == [
            ("契約詳細表", 0), ("契約總表", 0), ("契約總表", 1),
        ]

    def test_legacy_xls(self, write):
        rows = read_workbook(write(make_xls_bytes(rows=[["甲", "", "丙"]]), suffix=".xls"))

        assert rows[0].cells == ["甲", "", "丙"]

    def test_corrupt_file_raises(self, write):
        with pytest.raises(UnprocessableDocumentError):
            read_workbook(write(b"not a workbook"))


class TestFormatCell:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, ""),
            (3090.0, "3090"),      # 整數型浮點數不可以留小數尾巴，否則 CNS 3090 抽不出來
            (12.5, "12.5"),
            ("  施工測量  ", "施工測量"),
            (1, "1"),
        ],
    )
    def test_formats(self, value, expected):
        assert format_cell(value) == expected
