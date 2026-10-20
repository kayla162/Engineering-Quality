from pathlib import Path

import pymupdf


def make_drawing(path: Path, title="Waterproof detail", code="A8-09B"):
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=700)
    page.insert_text((250, 600), "DRAWING TITLE")
    page.insert_text((250, 630), title)
    page.insert_text((220, 665), "DRG. NO.")
    page.insert_text((280, 665), code)
    # An unrelated reference in the body must not replace the page's own number.
    page.insert_text((100, 100), "See A1-01")
    doc.save(path)
    doc.close()


def test_title_block_not_body_reference(tmp_path):
    from app.drawings.reader import read_drawings
    path = tmp_path / "drawing.pdf"
    make_drawing(path)
    rows = read_drawings(path)
    assert len(rows) == 1
    assert rows[0].number == "A8-09B"
    assert rows[0].title == "Waterproof detail"
    assert rows[0].page == 1
    assert rows[0].method == "text"


def test_blank_page_is_visible_not_absence(tmp_path):
    from app.drawings.reader import read_drawings
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    row = read_drawings(path)[0]
    assert row.number is None
    assert row.warning
    assert row.method == "unreadable"


def test_items_come_from_title_not_general_notes():
    from app.drawings.reader import item_names
    assert item_names("地下室外牆防水詳圖") == ["防水"]
    assert item_names("三至六層平面圖") == []
    assert item_names("鋼筋混凝土標準圖") == ["鋼筋", "混凝土"]


def test_explicit_reinforcement_and_steel_structure_title_variants():
    from app.drawings.reader import item_names
    assert item_names("一層梁配筋圖") == ["鋼筋"]
    assert item_names("鋼結構精準度標準圖") == ["鋼構"]
    assert item_names("鋼筋及配筋詳圖") == ["鋼筋"]  # one candidate per discipline
    assert item_names("三至六層結構平面圖") == []


def test_scan_uses_injected_ocr_without_inventing_text(tmp_path):
    from app.drawings.reader import read_drawings
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page(width=1000, height=700)
    doc.save(path)
    doc.close()
    calls = []
    def ocr(page):
        calls.append(page.number)
        return [
            (250, 600, 350, 610, "DRAWING TITLE"),
            (250, 630, 350, 640, "防水詳圖"),
            (220, 660, 270, 670, "DRG. NO."),
            (280, 660, 320, 670, "S0-01"),
        ]
    row = read_drawings(path, ocr=ocr)[0]
    assert calls == [0]
    assert (row.number, row.title, row.method) == ("S0-01", "防水詳圖", "ocr")
    assert row.warning  # OCR is not a reviewed fact.


def test_title_does_not_include_sheet_number_labels():
    from app.drawings.reader import title_block
    spans = [(375, 758, 407, 765, "DRAWING TITLE"), (234, 777, 324, 788, "混凝土詳圖"),
             (447, 799, 459, 807, "："), (445, 804, 468, 814, "SHEET NO."),
             (213, 806, 231, 814, "DRG. NO."), (244, 801, 265, 811, "S0-01")]
    number, title, _ = title_block(spans, 842)
    assert (number, title) == ("S0-01", "混凝土詳圖")


def test_ocr_number_label_variant_still_requires_nearby_value():
    from app.drawings.reader import title_block
    spans = [(220, 660, 270, 670, "DRG. ND."),
             (280, 660, 320, 670, "S0-02"),
             (500, 600, 550, 610, "S9-99")]
    assert title_block(spans, 700)[0] == "S0-02"


def test_compound_number_is_not_silently_truncated():
    from app.drawings.reader import title_block
    spans = [(220, 660, 270, 670, "DRG. NO."),
             (280, 660, 350, 670, "L1-01-4A")]
    assert title_block(spans, 700)[0] == "L1-01-4A"
    spans[-1] = (280, 660, 350, 670, "L1-01-123A")
    assert title_block(spans, 700)[0] is None  # unsupported suffix, not L1-01


def test_displaced_title_on_number_row_excludes_metadata_labels():
    from app.drawings.reader import title_block
    spans = [(363, 765, 409, 770, "DRAWING TITLE"),
             (345, 808, 427, 818, "一層樓板高程剖面圖(一)"),
             (202, 805, 216, 812, "圖號："), (202, 813, 217, 817, "DRG. NO."),
             (221, 807, 239, 815, "A2-15B"),
             (444, 805, 458, 812, "張數："), (444, 813, 459, 817, "SHEET NO."),
             (509, 805, 524, 812, "版次：")]
    assert title_block(spans, 842)[:2] == ("A2-15B", "一層樓板高程剖面圖(一)")
