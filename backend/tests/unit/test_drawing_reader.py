"""契約圖標題欄的讀取（檢核表階段 2、4）。

真實的 CAD 匯出圖（某宿舍統包工程的建築竣工圖，331 頁）裡，標題欄的標籤「圖號：」「DRG. NO.」
和值「A2-08B」是分開的文字物件，文字順序也不照版面——舊版要求「圖號：S-12」連在一起，
整份只讀到 14 張而且圖號圖名配錯。這裡用小的合成 PDF 模擬那種版面，不依賴真實檔案；
真實檔案的回歸測試放在最後，沒有 工程文書/ 時略過。
"""

from pathlib import Path

import pymupdf
import pytest

from app.core.config import settings
from app.specs.drawing_reader import read_drawing_sheets

FONT = "china-t"  # PyMuPDF 內建的繁體中文字型
REAL_AS_BUILT = settings.DATA_DIR.parent / "工程文書" / "建築竣工圖0826.pdf"


def cad_page(doc, sheet_no: str, title: str, rotation: int = 0, noise: tuple[str, ...] = ()):
    """A3 橫式，右下角標題欄：標籤一組、值一組，各自是獨立的文字物件。"""
    page = doc.new_page(width=1191, height=842)
    for i, text in enumerate(noise):  # 圖面上散落的其他圖號（「詳A5-21-1A」）與文字
        page.insert_text((80 + 40 * i, 120 + 60 * i), text, fontname=FONT, fontsize=8)
    page.insert_text((360, 760), "圖    名", fontname=FONT, fontsize=7)
    page.insert_text((360, 770), "DRAWING TITLE", fontsize=5)
    page.insert_text((700, 810), "圖號：", fontname=FONT, fontsize=7)
    page.insert_text((700, 818), "DRG. NO.", fontsize=5)
    page.insert_text((420, 790), "竣  工  圖", fontname=FONT, fontsize=10)
    page.insert_text((360, 790), "工 程 名 稱", fontname=FONT, fontsize=7)
    # 值放在標籤旁邊，但寫入順序在最後（真實檔案的文字順序也是這樣）
    page.insert_text((380, 780), title, fontname=FONT, fontsize=9)
    page.insert_text((705, 830), sheet_no, fontsize=8)
    if rotation:
        page.set_rotation(rotation)
    return page


def save(doc, tmp_path, name="契約圖.pdf") -> Path:
    path = tmp_path / name
    doc.save(path)
    return path


class TestCadTitleBlocks:
    def test_values_are_read_from_next_to_their_labels(self, tmp_path):
        doc = pymupdf.open()
        cad_page(doc, "A2-08B", "八層放大平面圖(二)", noise=("詳A5-21-1A", "金屬格柵(詳A6-09)"))
        cad_page(doc, "L1-01-2", "一層景觀放樣配置圖")
        rows = read_drawing_sheets(save(doc, tmp_path))
        assert [(r.sheet_no, r.title, r.page) for r in rows] == [
            ("A2-08B", "八層放大平面圖(二)", 1),
            ("L1-01-2", "一層景觀放樣配置圖", 2),
        ]

    def test_a_rotated_sheet_is_read_the_same(self, tmp_path):
        doc = pymupdf.open()
        cad_page(doc, "A10-10E", "曬衣架詳圖", rotation=270)
        rows = read_drawing_sheets(save(doc, tmp_path))
        assert [(r.sheet_no, r.title) for r in rows] == [("A10-10E", "曬衣架詳圖")]

    def test_the_title_block_labels_are_never_taken_as_the_title(self, tmp_path):
        doc = pymupdf.open()
        cad_page(doc, "A0-01A", "建築圖號索引表(一)")
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert row.title == "建築圖號索引表(一)"

    def test_a_note_next_to_the_title_cell_is_not_the_title(self, tmp_path):
        doc = pymupdf.open()
        page = cad_page(doc, "A9-15A", "地下室頂版防水施工詳圖")
        page.insert_text((362, 752), "CNS 8644規範規定。", fontname=FONT, fontsize=7)
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert row.title == "地下室頂版防水施工詳圖"

    def test_a_title_with_engineering_in_it_is_kept(self, tmp_path):
        doc = pymupdf.open()
        cad_page(doc, "A0-04", "假設工程圖")
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert row.title == "假設工程圖"

    def test_a_repeated_sheet_number_keeps_the_first_page(self, tmp_path):
        doc = pymupdf.open()
        cad_page(doc, "A8-25", "屋突一層地坪平面圖")
        cad_page(doc, "A8-25", "屋突一層地坪平面圖")
        rows = read_drawing_sheets(save(doc, tmp_path))
        assert [(r.sheet_no, r.page) for r in rows] == [("A8-25", 1)]


class TestOtherLayouts:
    def test_label_and_value_on_one_line_still_work(self, tmp_path):
        doc = pymupdf.open()
        page = doc.new_page(width=842, height=595)
        page.insert_text((600, 540), "圖號：S-02", fontname=FONT, fontsize=9)
        page.insert_text((600, 555), "圖名：模板組立詳圖", fontname=FONT, fontsize=9)
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert (row.sheet_no, row.title) == ("S-02", "模板組立詳圖")

    def test_a_drawing_index_is_used_when_there_are_no_title_blocks(self, tmp_path):
        doc = pymupdf.open()
        page = doc.new_page(width=842, height=595)
        page.insert_text((60, 80), "S-01 結構平面圖", fontname=FONT, fontsize=9)
        page.insert_text((60, 95), "S-02 模板組立詳圖", fontname=FONT, fontsize=9)
        rows = read_drawing_sheets(save(doc, tmp_path))
        assert [(r.sheet_no, r.title) for r in rows] == [("S-01", "結構平面圖"), ("S-02", "模板組立詳圖")]

    def test_a_scanned_drawing_yields_nothing(self, tmp_path):
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 140), False)
        image.clear_with(200)
        doc = pymupdf.open()
        doc.new_page(width=1191, height=842).insert_image(pymupdf.Rect(0, 0, 1191, 842), pixmap=image)
        assert read_drawing_sheets(save(doc, tmp_path)) == []


@pytest.mark.skipif(not REAL_AS_BUILT.exists(), reason="沒有 工程文書/建築竣工圖0826.pdf（真實檔案不進版控）")
def test_the_real_as_built_set():
    rows = read_drawing_sheets(REAL_AS_BUILT)
    by_no = {r.sheet_no: r.title for r in rows}
    assert len(rows) >= 327
    assert by_no["A2-08B"] == "八層放大平面圖(二)"
    # 圖面上的「地下室頂版防水施工詳圖」是分圖標題，標題欄的圖名是這個
    assert by_no["A9-15A"] == "防水工程大樣詳圖(一)"
    assert by_no["A0-04"] == "假設工程圖"
    assert by_no["L1-01-2"] == "一層景觀放樣配置圖"
    assert by_no["G-01"] == "一層瓦斯管線平面配置圖"
    assert by_no["A0-01A"] == "建築圖號索引表(一)"


def test_the_xiushan_demo_drawings_are_read_like_real_ones(tmp_path):
    """示範契約圖（scripts/generate_xiushan_drawings_demo.py）的版面照真實 CAD 圖，要讀得到每一張。"""
    import importlib.util

    script = settings.DATA_DIR.parent / "scripts" / "generate_xiushan_drawings_demo.py"
    spec = importlib.util.spec_from_file_location("generate_xiushan_drawings_demo", script)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    path = tmp_path / "示範契約圖.pdf"
    generator.build(path)

    rows = read_drawing_sheets(path)
    assert [(r.sheet_no, r.title) for r in rows] == generator.SHEETS


def scanned_sheet(doc, sheet_no: str, title_rows: list[str]) -> None:
    """秀山契約圖（用印掃描檔）的版面：右側直條標題欄，圖名在「DRAWING」下面，
    簽名（這裡用虛構的人名）在圖名和事務所之間，圖號在最下面「DWG NO.」右邊。整頁存成圖片。"""
    source = pymupdf.open()
    page = source.new_page(width=1191, height=842)
    x = 1060
    page.insert_text((x, 470), "業主 CLIENT", fontname=FONT, fontsize=7)
    page.insert_text((x, 480), "示範市政府", fontname=FONT, fontsize=8)
    page.insert_text((x, 530), "圖名", fontname=FONT, fontsize=7)
    page.insert_text((x, 540), "DRAWING", fontsize=6)
    for i, row in enumerate(title_rows):
        page.insert_text((x, 556 + 13 * i), row, fontname=FONT, fontsize=9)
    page.insert_text((x + 20, 600), "王大明", fontname=FONT, fontsize=10)
    page.insert_text((x, 625), "示範聯合建築師事務所", fontname=FONT, fontsize=8)
    page.insert_text((x, 640), "電話：(02)0000-0000", fontname=FONT, fontsize=6)
    page.insert_text((x + 60, 800), "圖號", fontname=FONT, fontsize=7)
    page.insert_text((x + 60, 810), "DWG NO.", fontsize=5)
    page.insert_text((x + 90, 806), sheet_no, fontsize=10)
    pix = page.get_pixmap(dpi=300)
    scanned = doc.new_page(width=1191, height=842)
    scanned.insert_image(scanned.rect, pixmap=pix)


def _ocr_available() -> bool:
    from app.parsers import ocr

    original = settings.ENABLE_OCR
    settings.ENABLE_OCR = True
    try:
        return ocr.load_engine()[0] is not None
    finally:
        settings.ENABLE_OCR = original


@pytest.mark.skipif(not _ocr_available(), reason="這台機器沒有 Tesseract 繁中語言資料")
class TestScannedTitleBlocks:
    @pytest.fixture(autouse=True)
    def ocr_on(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_OCR", True)

    def test_a_scanned_set_is_read_by_ocr_and_marked(self, tmp_path):
        doc = pymupdf.open()
        scanned_sheet(doc, "A2-02", ["二層平面圖"])
        scanned_sheet(doc, "S1-03", ["基礎及地梁", "配筋詳圖"])
        rows = read_drawing_sheets(save(doc, tmp_path))

        assert [(r.sheet_no, r.title, r.page) for r in rows] == [
            ("A2-02", "二層平面圖", 1),
            ("S1-03", "基礎及地梁配筋詳圖", 2),
        ]
        assert all(r.is_ocr for r in rows)

    def test_the_signature_and_firm_are_not_part_of_the_title(self, tmp_path):
        doc = pymupdf.open()
        scanned_sheet(doc, "E1-01", ["燈具配置平面圖"])
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert "王大明" not in row.title and "事務所" not in row.title

    def test_a_signature_right_under_the_title_is_removed(self, tmp_path):
        """簽名離圖名很近（沒有空一段）時會被 OCR 讀進圖名；同一頁事務所那一行也有這個名字，就拿掉。"""
        doc = pymupdf.open()
        source = pymupdf.open()
        page = source.new_page(width=1191, height=842)
        x = 1060
        page.insert_text((x, 530), "圖名", fontname=FONT, fontsize=7)
        page.insert_text((x, 540), "DRAWING", fontsize=6)
        page.insert_text((x, 556), "屋突一層平面圖", fontname=FONT, fontsize=9)
        page.insert_text((x, 567), "王大明", fontname=FONT, fontsize=9)
        page.insert_text((x, 625), "王大明聯合建築師事務所", fontname=FONT, fontsize=8)
        page.insert_text((x + 60, 800), "圖號", fontname=FONT, fontsize=7)
        page.insert_text((x + 60, 810), "DWG NO.", fontsize=5)
        page.insert_text((x + 90, 806), "A2-05", fontsize=10)
        doc.new_page(width=1191, height=842).insert_image(pymupdf.Rect(0, 0, 1191, 842), pixmap=page.get_pixmap(dpi=300))
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert row.title == "屋突一層平面圖"

    def test_an_unreadable_number_falls_back_to_the_page(self, tmp_path):
        doc = pymupdf.open()
        scanned_sheet(doc, "", ["給水系統圖"])
        (row,) = read_drawing_sheets(save(doc, tmp_path))
        assert (row.sheet_no, row.title) == ("第1頁", "給水系統圖")


def test_repeated_signature_text_is_removed_from_ocr_titles():
    """同一冊每張圖的標題欄都簽同一個名字；OCR 把它黏進圖名時，整冊出現四分之一以上、
    又不含圖面用字的三字串當成簽名拿掉（不寫死任何人名）。"""
    from app.specs.drawing_reader import DrawingSheetRow, _without_repeated_signature

    rows = [
        DrawingSheetRow("A2-01", "一層平面圖王大明", 1, True),
        DrawingSheetRow("A2-02", "二層平面圖", 2, True),
        DrawingSheetRow("A2-03", "三層平面圖王大明", 3, True),
        DrawingSheetRow("A6-01", "門窗詳圖王大明", 4, True),
    ]
    assert [r.title for r in _without_repeated_signature(rows)] == [
        "一層平面圖", "二層平面圖", "三層平面圖", "門窗詳圖",
    ]


def test_a_set_with_a_few_text_pages_is_still_scanned(tmp_path):
    """秀山水電圖 117 頁裡有 2 頁帶文字層；整冊仍是掃描檔，要走 OCR。"""
    from app.specs.drawing_reader import _is_scanned

    assert _is_scanned(["", "", "", "", "", "", "", "", "", "有一頁帶著文字層，內容超過五十個字的說明頁" * 3])
    assert not _is_scanned(["圖號：S-01 圖名：結構平面圖，說明：依結構計算書辦理。" * 3] * 5)
