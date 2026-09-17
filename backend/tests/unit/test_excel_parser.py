"""Excel 解析器。

存在的理由：真實標單是 **OLE2 格式的 .xls**（見 docs/superpowers/specs/
2026-09-11-工項檢核表-design.md 第 8 節）。系統原本只收 .docx/.pdf/.txt，
標單根本進不來，整條「工項檢核表」的路就斷在入口。

邊界：這個解析器只做「檔案 -> 段落」，**不認得標單的結構**（項次、計價代碼、
哪張工作表是詳細表）。那些是工項抽取的職責，它會另外讀同一份原始檔。
"""

import pytest

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.parsers.excel_parser import ExcelParser
from tests.factories import make_xls_bytes, make_xlsx_bytes


@pytest.fixture
def parse(tmp_path):
    def _parse(data: bytes, suffix: str = ".xlsx"):
        path = tmp_path / f"標單{suffix}"
        path.write_bytes(data)
        return ExcelParser().parse(path)

    return _parse


class TestRowsBecomeSections:
    """一列一個 section，不是一格一個。

    照 DOCX 那樣一格一段的話，真實標單（2669 列 x 7 欄）會產生近兩萬個 section，
    而且「壹.一.1.1.1」跟「施工測量，基地測量及鑑界費」會被拆散——
    法規抽取跑在完整的列上比跑在單格上準得多。
    """

    def test_one_section_per_row(self, parse):
        """SAMPLE_ROWS 有 4 列，其中第 3 列是續寫 -> 併進前一段，剩 3 段。"""
        sections = parse(make_xlsx_bytes())

        assert len(sections) == 3

    def test_cells_in_a_row_stay_in_one_section(self, parse):
        sections = parse(make_xlsx_bytes())
        row = next(s for s in sections if "施工測量" in s.content)

        assert "壹.一.1.1.1" in row.content
        assert "0172500004" in row.content

    def test_sheet_name_becomes_section_title(self, parse):
        assert all(s.section_title == "契約詳細表" for s in parse(make_xlsx_bytes()))

    def test_marked_as_table_content(self, parse):
        assert all(s.content_type == ContentType.TABLE for s in parse(make_xlsx_bytes()))

    def test_no_page_numbers(self, parse):
        """試算表沒有頁碼，跟 DOCX 一致留 None，不要編一個出來。"""
        assert all(s.page is None for s in parse(make_xlsx_bytes()))

    def test_order_index_is_sequential(self, parse):
        sections = parse(make_xlsx_bytes())

        assert [s.order_index for s in sections] == list(range(len(sections)))


class TestNumberFormatting:
    """數字不可以變成「3090.0」。

    這不是美觀問題：標準編號、數量、章碼在試算表裡常常是數值型別，
    浮點尾巴會讓「CNS 3090」抽不出來。
    """

    def test_integral_numbers_lose_the_decimal_tail(self, parse):
        sections = parse(make_xlsx_bytes(rows=[["CNS", 3090, "預拌混凝土"]]))

        assert "3090" in sections[0].content
        assert "3090.0" not in sections[0].content

    def test_real_decimals_are_kept(self, parse):
        sections = parse(make_xlsx_bytes(rows=[["坍度", 12.5, "cm"]]))

        assert "12.5" in sections[0].content


class TestEmptyCellsAndRows:
    def test_blank_rows_are_skipped(self, parse):
        rows = [["項次", "說明"], ["", ""], ["壹.一", "施工測量"], [None, None]]

        assert len(parse(make_xlsx_bytes(rows=rows))) == 2


class TestWrappedText:
    """標單的長說明會跨列續寫，而且是從詞中間斷開的。

    真實資料（新北市消防局秀山分隊標單，契約詳細表 列18-19）：
        列18  項次=''  「新北市建築物施工中管制要點及新北市建」
        列19  項次=''  「築工程施工圍籬綠美化推動實施計畫規定」

    一列一段的話，「新北市建築工程施工圍籬綠美化推動實施計畫」會被切成兩半，
    抽取器就會吐出「市建築物施工中管制要點」「勞安標準」這種半截詞。
    實測這樣會產生 39 筆 NOT_FOUND 的垃圾。

    判斷續寫的方式刻意不綁標單格式（不認得「項次」欄）：
    **只有一欄有內容，而且和前一列是同一欄** -> 那是換行造成的續寫。
    """

    def test_wrapped_rows_are_rejoined(self, parse):
        sections = parse(make_xlsx_bytes())
        merged = next(s for s in sections if "施工測量" in s.content)

        assert "施工中由承商建置" in merged.content

    def test_rejoined_without_separator(self, parse):
        """從詞中間斷開的，中間不能插分隔符號，否則名稱還是斷的。"""
        rows = [["壹.一", "符合新北市建"], ["", "築工程施工圍籬綠美化推動實施計畫"]]
        sections = parse(make_xlsx_bytes(rows=rows))

        assert "新北市建築工程施工圍籬綠美化推動實施計畫" in sections[0].content

    def test_a_row_with_its_own_key_starts_a_new_section(self, parse):
        """有項次就是新的一筆，不可以被併進去。"""
        rows = [["壹.一", "施工測量"], ["", "續寫"], ["壹.二", "施工安全"]]
        sections = parse(make_xlsx_bytes(rows=rows))

        assert len(sections) == 2
        assert "施工安全" in sections[1].content

    def test_different_column_is_not_a_continuation(self, parse):
        """同樣只有一欄，但不是同一欄 -> 不是續寫。"""
        rows = [["", "施工測量"], ["壹.二", ""]]
        sections = parse(make_xlsx_bytes(rows=rows))

        assert len(sections) == 2


class TestMultipleSheets:
    def test_every_sheet_is_parsed(self, parse):
        data = make_xlsx_bytes(extra_sheet=("契約總表", [["項次", "工作項目"], ["壹", "發包工程費"]]))
        sections = parse(data)

        assert {s.section_title for s in sections} == {"契約詳細表", "契約總表"}

    def test_order_index_continues_across_sheets(self, parse):
        data = make_xlsx_bytes(extra_sheet=("契約總表", [["壹", "發包工程費"]]))
        sections = parse(data)

        assert [s.order_index for s in sections] == list(range(len(sections)))


class TestLegacyXls:
    """真實標單的格式。openpyxl 讀不了 OLE2，必須走 xlrd。"""

    def test_xls_is_parsed(self, parse):
        sections = parse(make_xls_bytes(), suffix=".xls")

        assert len(sections) == 3

    def test_chinese_content_survives(self, parse):
        sections = parse(make_xls_bytes(), suffix=".xls")

        assert any("施工測量，基地測量及鑑界費" in s.content for s in sections)

    def test_sheet_name_survives(self, parse):
        assert parse(make_xls_bytes(), suffix=".xls")[0].section_title == "契約詳細表"

    def test_numbers_are_formatted_the_same_way(self, parse):
        """xlrd 把整數也給成 float，和 openpyxl 的處理要一致。"""
        sections = parse(make_xls_bytes(rows=[["CNS", 3090]]), suffix=".xls")

        assert "3090" in sections[0].content and "3090.0" not in sections[0].content


class TestErrors:
    def test_workbook_with_no_content_raises(self, parse):
        """跟 PDF 解析器一致：解析不到東西要明確報錯，不要安靜產出空清單。"""
        with pytest.raises(UnprocessableDocumentError, match="沒有"):
            parse(make_xlsx_bytes(rows=[["", ""], [None]]))

    def test_corrupt_file_raises(self, parse):
        with pytest.raises(UnprocessableDocumentError):
            parse(b"this is not a spreadsheet")


class TestRegistration:
    def test_both_extensions_are_registered(self):
        from app.parsers import _PARSERS

        assert isinstance(_PARSERS[".xls"], ExcelParser)
        assert isinstance(_PARSERS[".xlsx"], ExcelParser)

    def test_upload_accepts_excel(self):
        """沒有這一行，檔案會在上傳驗證就被擋掉，根本走不到解析器。"""
        from app.core.config import settings

        assert ".xls" in settings.allowed_extensions
        assert ".xlsx" in settings.allowed_extensions
