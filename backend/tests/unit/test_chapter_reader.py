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
        document = pymupdf.open()
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 560, 760), "封面", fontsize=10, fontname="china-t")
        data = document.tobytes()
        document.close()

        with pytest.raises(SpecFormatError, match="章節頁首"):
            read_spec_chapters(write(data))

    def test_a_file_that_is_not_a_pdf_raises(self, write):
        """打不開的檔案要報成 SpecFormatError（422），不是讓 pymupdf 的例外直接冒出去。
        也讓上面那個測試的 match 只可能是「讀得開但沒有章節」這條路。"""
        with pytest.raises(SpecFormatError, match="無法開啟"):
            read_spec_chapters(write(b"this is not a pdf"))

    def test_an_encrypted_document_raises_instead_of_crashing(self, write):
        """加密的規範書翻不了頁，pymupdf 會丟 ValueError，API 會變成 500。
        要報成 SpecFormatError（422），和 PdfParser 的加密檢查是同一條原則。"""
        document = pymupdf.open()
        document.new_page()
        data = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner"
        )
        document.close()

        with pytest.raises(SpecFormatError, match="加密"):
            read_spec_chapters(write(data))


class TestChapterSplitting:
    """章與章之間怎麼切。

    實測 772 頁裡 748 頁有頁首，其中絕大多數是章的第 2 頁以後，所以「同一章的連續頁
    合併成一列」才是切章的主體。每頁各成一列的話，T4 的 {章碼: 內文} 只會留下每章
    最後一頁，而上面只有單章的測試全都還是綠的。
    """

    def test_pages_of_one_chapter_are_merged_and_the_next_chapter_starts_a_new_row(self, write):
        data = make_spec_pdf_bytes(
            [
                ("01725", "01725", "施工測量", "3.0", "章首頁的內文"),
                ("01725", "01725", "施工測量", "3.0", "續頁的內文"),
                ("05500", "05503", "建築用金屬製品", "5.0", "下一章的內文"),
            ]
        )

        rows = read_spec_chapters(write(data))

        assert [(r.code, r.title, r.version, r.first_page, r.last_page) for r in rows] == [
            ("01725", "施工測量", "3.0", 1, 2),
            ("05503", "建築用金屬製品", "5.0", 3, 3),
        ]
        # 內文跟著章走：兩頁都在第一章，也沒有漏到下一章
        assert "章首頁的內文" in rows[0].text and "續頁的內文" in rows[0].text
        assert "下一章的內文" not in rows[0].text
        assert "下一章的內文" in rows[1].text and "續頁的內文" not in rows[1].text

    def test_a_chapter_is_followed_by_its_chapter_code_not_its_group_code(self, write):
        """實測 p243-250：05503 整章 8 頁，每頁頁首的組碼都是 05500。
        合併要比章碼；誤比成組碼的話，這一章從第 2 頁起每頁各成一列。"""
        data = make_spec_pdf_bytes(
            [
                ("05500", "05503", "建築用金屬製品", "5.0", "章首頁的內文"),
                ("05500", "05503", "建築用金屬製品", "5.0", "續頁的內文"),
            ]
        )

        rows = read_spec_chapters(write(data))

        assert [(r.code, r.first_page, r.last_page) for r in rows] == [("05503", 1, 2)]


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


class TestSpecPdfFactory:
    """`make_spec_pdf_bytes` 是階段 3 後面幾個任務的測試地基，吐出來的 PDF 要像真的。
    沒有別處測 factory 本身，所以透過讀取器看它的輸出。"""

    def test_later_pages_of_a_chapter_get_the_next_page_number_and_no_title_line(self, write):
        """實測 p61-63（01725）：第 2 頁起頁首是 `01725 01725-2 V3.0 …`，
        `第01725 章` 這行只在第 1 頁。"""
        data = make_spec_pdf_bytes(
            [
                ("01725", "01725", "施工測量", "3.0", "章首頁的內文"),
                ("01725", "01725", "施工測量", "3.0", "續頁的內文"),
            ]
        )

        first, second = read_spec_chapters(write(data))[0].pages

        assert "01725-1" in first and "第01725 章" in first
        assert "01725-2" in second and "第01725 章" not in second

    def test_an_explicit_empty_chapter_list_is_not_replaced_by_the_default(self, write):
        """`chapters=[]` 是「沒有任何章節」。用預設的一章頂替的話，
        想測「沒有章節」這條路的人會拿到一份有章節的 PDF。"""
        data = make_spec_pdf_bytes([], trailing_pages=1)

        with pytest.raises(SpecFormatError, match="章節頁首"):
            read_spec_chapters(write(data))
