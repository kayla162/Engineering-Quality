"""PDF 文字覆蓋率守門。

為什麼需要這一層：`PdfParser` 只在「整份文件一個字都沒有」時才報錯。設計圖說的
文字是壓在點陣圖裡的，parser 會成功回傳圖號與標題欄，然後安靜地把真正有資訊的
內容（尺寸標註、構件名稱）整批丟掉。實測 `10.建築物無障礙設施設計規範.pdf`：
105 頁裡 51 頁如此，p19 畫面上有四處「≧45」和「橫拉門」，抽出來只有圖號。

解析成功但內容幾乎是空的，比解析失敗更危險——那是「有信心的錯」。
這一層的工作是讓它浮到人眼前，不是擋下來。
"""

import pytest

from app.parsers import parse_document
from app.parsers.text_coverage import FIGURE_PAGE_RATIO, measure_pages
from tests.factories import make_docx_bytes, make_pdf_bytes


def pages(text: int = 0, figure: int = 0, sparse: int = 0) -> list[tuple[int, bool]]:
    """每頁的（文字長度, 有沒有圖）。sparse = 字少但沒有圖，例如扉頁。"""
    return [(900, False)] * text + [(12, True)] * figure + [(12, False)] * sparse


@pytest.fixture
def write(tmp_path):
    def _write(data: bytes, suffix: str = ".pdf"):
        path = tmp_path / f"文件{suffix}"
        path.write_bytes(data)
        return path

    return _write


class TestMeasurePages:
    def test_a_text_document_is_not_degraded(self):
        assert measure_pages(pages(text=10)).is_degraded is False

    def test_a_figure_heavy_document_is_degraded(self):
        """實測的 10.建築物無障礙設施設計規範.pdf 是 49%。"""
        assert measure_pages(pages(text=4, figure=6)).is_degraded is True

    def test_page_counts_are_reported(self):
        coverage = measure_pages(pages(text=4, figure=6))

        assert (coverage.pages, coverage.figure_pages) == (10, 6)

    def test_sparse_pages_without_images_are_not_figure_pages(self):
        """扉頁、目錄這種「字少但沒有圖」的頁不算——沒有東西被藏起來。"""
        coverage = measure_pages(pages(text=7, sparse=3))

        assert coverage.figure_pages == 0
        assert coverage.is_degraded is False

    def test_the_threshold_counts_as_degraded_when_reached(self):
        """門檻是「達到」就算，不是「超過」。1/10 = 10%。"""
        assert FIGURE_PAGE_RATIO == 0.10

        assert measure_pages(pages(text=9, figure=1)).is_degraded is True

    def test_just_under_the_threshold_is_clean(self):
        """1/12 ≈ 8%。實測乾淨文件是 0% 與 0.8%，離這裡還很遠。"""
        assert measure_pages(pages(text=11, figure=1)).is_degraded is False

    def test_a_short_document_with_two_figure_pages_is_degraded(self):
        """回歸：11.新北市政府建築工程施工管理要點.pdf 是 2/9 = 22%，門檻 25% 時被放過。

        那兩頁一頁是七張道路修復圖例、一頁是兩張工程告示牌規格表（法定必載欄位、
        尺寸、通報專線），抽出來只有標題 86 個字。漏報的代價是使用者拿著一份
        空結果以為沒問題；誤報的代價是多看一行警告。
        """
        assert measure_pages(pages(text=7, figure=2)).is_degraded is True

    def test_an_empty_document_is_not_degraded(self):
        """0 頁不能讓比例運算炸掉。"""
        assert measure_pages([]).is_degraded is False

    def test_the_note_says_what_was_lost(self):
        """守門的價值在於人看得懂，數字要出現在訊息裡。"""
        note = measure_pages(pages(text=4, figure=6)).note

        assert "10" in note and "6" in note


class TestPdfCoverage:
    """PdfParser 餵給 measure_pages 的統計要是對的——這是整合點。"""

    def test_a_figure_heavy_pdf_is_flagged(self, write):
        result = parse_document(write(make_pdf_bytes(text_pages=4, figure_pages=6)))

        assert result.coverage.is_degraded is True

    def test_a_text_pdf_is_clean(self, write):
        result = parse_document(write(make_pdf_bytes(text_pages=10)))

        assert result.coverage.is_degraded is False

    def test_sparse_pages_without_images_are_not_flagged(self, write):
        result = parse_document(write(make_pdf_bytes(text_pages=7, sparse_pages=3)))

        assert result.coverage.figure_pages == 0

    def test_sections_still_come_through_on_a_flagged_document(self, write):
        """標記不是擋下來——圖號和內文都還要照常回傳。"""
        result = parse_document(write(make_pdf_bytes(text_pages=4, figure_pages=6)))

        assert len(result.sections) > 0

    def test_other_formats_have_no_coverage(self, write):
        """docx 沒有「頁」的概念，也沒有這個失效模式。"""
        result = parse_document(write(make_docx_bytes(), suffix=".docx"))

        assert result.coverage is None
        assert len(result.sections) > 0
