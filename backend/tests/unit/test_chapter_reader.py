"""施工規範的章節切分。

為什麼要切章：工項靠計價代碼前 5 碼對到章碼，依據就在那一章的「1.4 相關準則」裡。
切不出章節就等於沒有依據可用。

頁首格式是 `<組碼> <章碼>-<頁次> V<版本> <日期>`，實測 13.施工規範.pdf
772 頁裡 748 頁（97%）符合。剩下的是封面目錄與跨頁大表——後者屬於前一章。
"""

import pymupdf
import pytest

from app.specs import SpecFormatError, read_spec_chapters
from tests.factories import make_spec_pdf_bytes


@pytest.fixture
def write(tmp_path):
    def _write(data: bytes):
        path = tmp_path / "施工規範.pdf"
        path.write_bytes(data)
        return path

    return _write


def _real_layout_pdf(title_line: str, body: str = "") -> bytes:
    """照真實規範書的版面造一頁：頁首每個欄位各佔一行，章名在 `第… 章` 的下一行。

    `make_spec_pdf_bytes` 把 `第… 章V… 章名` 寫在同一行，真實規範書不是——
    實測 86 章裡章名行有三種寫法（見 TestChapterTitle）。
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(40, 40, 560, 760),
        f"02220\n02220-1\nV3.0 2005/10/17\n{title_line}\n\n1.\n通則\n{body}",
        fontsize=10,
        fontname="china-t",
    )
    data = document.tobytes()
    document.close()
    return data


class TestReadSpecChapters:
    def test_chapter_code_title_and_version_are_read(self, write):
        rows = read_spec_chapters(write(make_spec_pdf_bytes()))

        assert (rows[0].code, rows[0].title, rows[0].version) == ("01725", "施工測量", "3.0")

    def test_group_code_is_not_mistaken_for_the_chapter_code(self, write):
        """實測 p243：頁首是 `05500 05503-1 V5.0`，章碼是 05503 不是 05500。"""
        data = make_spec_pdf_bytes([("05500", "05503", "建築用金屬製品", "5.0", "內文")])

        rows = read_spec_chapters(write(data))

        assert rows[0].code == "05503"

    def test_pages_without_a_header_belong_to_the_previous_chapter(self, write):
        """跨頁大表沒有頁首。丟掉它們等於丟掉那一章的一部分內容。"""
        data = make_spec_pdf_bytes(trailing_pages=2)

        rows = read_spec_chapters(write(data))

        assert len(rows) == 1
        assert rows[0].last_page == 3
        assert "附表" in rows[0].text

    def test_chapter_text_is_collected(self, write):
        data = make_spec_pdf_bytes([("01572", "01572", "環境保護", "9.0", "1.4 相關準則 (1) 噪音管制法")])

        rows = read_spec_chapters(write(data))

        assert "噪音管制法" in rows[0].text

    def test_a_document_without_any_chapter_raises(self, write):
        """安靜回空清單的話，檢核表會變成「這個案子沒有依據」——
        但事實是「我們沒讀懂規範書」。和標單找不到表頭要報錯是同一條原則。"""
        import pymupdf

        document = pymupdf.open()
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 560, 760), "封面", fontsize=10, fontname="china-t")
        data = document.tobytes()
        document.close()

        with pytest.raises(SpecFormatError):
            read_spec_chapters(write(data))


class TestChapterTitle:
    """章名行有三種寫法（實測 13.施工規範.pdf 的 86 章）。

    只認其中一種的話，其餘的章會變成沒有章名——不影響比對，但檢核表上看得到。
    """

    @pytest.mark.parametrize(
        "title_line",
        [
            "第02220 章V3.0\n工地拆除",
            "第02220 章\n工地拆除",
            "第02220 章 V 1.0\n工地拆除",
        ],
        ids=["title-on-next-line", "no-version-on-title-line", "spaced-version"],
    )
    def test_title_is_read_from_every_layout_seen_in_the_real_document(self, write, title_line):
        """74 章是第一種，11 章章名行沒有版本，1 章（16742）版本中間有空白。"""
        rows = read_spec_chapters(write(_real_layout_pdf(title_line)))

        assert rows[0].title == "工地拆除"

    def test_a_cross_reference_is_not_mistaken_for_the_title(self, write):
        """內文的「第01330 章--資料送審」長得像章名行，但章碼不是本章的。
        找不到本章的章名行就該回空字串，不是別章的名字。"""
        data = _real_layout_pdf("", body="1.3.1 第01330 章--資料送審")

        rows = read_spec_chapters(write(data))

        assert rows[0].title == ""
