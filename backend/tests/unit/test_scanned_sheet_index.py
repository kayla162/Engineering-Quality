"""掃描契約圖的圖號：OCR 讀法還原、索引表白名單、整冊投票（scanned_sheet_index）。

案例都取自秀山三冊實測時讀到的寫法。
"""

import numpy as np
import pymupdf

from app.specs.scanned_sheet_index import _cell_entries, assign, clean_index, might_be_index
from app.specs.scanned_title_block import _long_runs, _without_lines, sheet_numbers_in

INDEX = ["S1-01", "S1-11", "S1-12", "S2-01", "S2-02", "S2-11", "S2-12", "S2-13", "S5-02", "S7-01"]


def test_ocr_spellings_are_turned_back_into_sheet_numbers():
    assert sheet_numbers_in("SI-23") == ["S1-23"]
    assert sheet_numbers_in("AL0-01 AIO-O3") == ["A10-01", "A10-03"]
    assert sheet_numbers_in("$2-1O") == ["S2-10"]
    assert sheet_numbers_in("Sl=12") == ["S1-12"]
    assert sheet_numbers_in("00-01") == ["00-01"]
    # 沒有字母時要剛好兩位數字，「1-2」「4-14」是雜訊
    assert sheet_numbers_in("1-2") == [] and sheet_numbers_in("4-14") == []


def test_the_whitelist_drops_misread_index_entries():
    entries = [
        "A5-01", "A5-02", "A5-03", "A5-10", "A4-01", "A4-02",
        "AS-02", "AS-03", "AS-10",  # 5 讀成 S：和更常見的 A5-xx 只差一個易混字
        "E1-002", "A10-062R",  # 流水號不是兩位數
        "S-01", "S-04",  # 這種字首只有兩張
        "E1-01", "E1-02", "E1-03", "F1-01", "F1-02", "F1-03",  # E 與 F 只差一個字，但不是易混字：都留
    ]
    assert clean_index(entries) == {
        "A5-01", "A5-02", "A5-03", "A5-10", "A4-01", "A4-02", "E1-01", "E1-02", "E1-03", "F1-01", "F1-02", "F1-03",
    }


def test_every_page_read_correctly_is_kept():
    readings = [[n, n] for n in INDEX]
    assert assign(readings, INDEX) == INDEX


def test_a_single_reading_one_slip_off_counts_only_when_unambiguous():
    # 「NS1-12」多一個字、只接近 S1-12；「S9-02」同時接近 S2-02 與 S5-02，不收
    readings = [["S1-01"], ["S1-11"], ["NS1-12"], ["S2-01"], ["S9-02"]]
    assert assign(readings, INDEX) == ["S1-01", "S1-11", "S1-12", "S2-01", None]


def test_a_letter_misread_as_a_digit_is_not_snapped():
    """「F1-04」和白名單的「01-04」只差一個字，但 F 換成 0 不是易混字：不拉過去。"""
    index = ["01-02", "01-03", "01-04", "00-01", "00-02"]
    assert assign([["F1-04"]], index) == [None]


def test_repeated_readings_outside_the_index_are_taken_when_they_form_a_run():
    """索引表沒讀到 AC 那一段：每頁兩種讀法一致就收；孤零零一張「S-01」不收。"""
    readings = [["AC-01", "AC-01"], ["AC-02", "AC-02", "AG-02"], ["S-01", "S-01"]]
    assert assign(readings, INDEX) == ["AC-01", "AC-02", None]


def test_a_number_out_of_order_within_its_prefix_is_dropped():
    """第 4 頁讀成 S7-01（真的是 S2-01）：前後是 S1-12、S2-02，編號順序對不上，丟掉；張數剛好，補回 S2-01。"""
    readings = [["S1-01"], ["S1-11"], ["S1-12"], ["S7-01", "S7-01"], ["S2-02"], ["S2-11"]]
    assert assign(readings, INDEX) == ["S1-01", "S1-11", "S1-12", "S2-01", "S2-02", "S2-11"]


def test_a_number_voted_by_two_pages_is_dropped_from_both():
    """兩頁都投 S2-12：分不出哪一頁讀錯，兩頁都不算；前後確定、張數剛好，照編號補上。"""
    readings = [["S2-01"], ["S2-12", "S2-12"], ["S2-11"], ["S2-12"], ["S2-13"]]
    assert assign(readings, INDEX) == ["S2-01", "S2-02", "S2-11", "S2-12", "S2-13"]


def test_gaps_are_filled_only_when_the_page_count_matches():
    index = ["S1-01", "S1-11", "S1-12", "S2-01"]
    # 第 1、4 頁確定，中間兩頁沒讀到：白名單裡夾在中間的剛好兩張，補上（照編號，不照索引表的排列）
    assert assign([["S1-01"], [], [], ["S2-01"]], list(reversed(index))) == index
    # 中間多了一頁（例如插頁）：對不上，不補
    assert assign([["S1-01"], [], [], [], ["S2-01"]], index) == ["S1-01", None, None, None, "S2-01"]
    # 不同字首之間不補
    with_e = index + ["E1-01", "E1-02", "E1-03"]
    assert assign([["S1-01"], [], ["E1-01", "E1-01"]], with_e) == ["S1-01", None, "E1-01"]


def test_without_an_index_two_agreeing_readings_are_needed():
    readings = [["E1-01", "E1-01"], ["E1-02"], ["E1-03", "E1-03", "E1-08"], ["E1-01", "E1-01"]]
    # 第 1、4 頁都讀成 E1-01：至少一頁讀錯，都不收
    assert assign(readings, []) == [None, None, "E1-03", None]


def test_the_same_index_cell_read_twice_counts_once():
    """兩種解析度、重疊分塊讀到同一格：位置相近的取票多的寫法。"""
    readings = [(100, 50, "A5-08"), (101, 51, "AS5-08"), (100, 52, "A5-08"), (300, 50, "A5-09")]
    assert _cell_entries(readings) == ["A5-08", "A5-09"]


def test_index_pages_are_the_front_pages_or_titled_as_an_index():
    assert might_be_index(1, "") and might_be_index(3, "一層平面圖")
    assert might_be_index(40, "給水圖號索引") and not might_be_index(40, "一層平面圖")


def test_long_runs_marks_only_lines():
    dark = np.zeros((3, 10), dtype=bool)
    dark[0, 1:9] = True  # 8 個連續：是線
    dark[1, 2:5] = True  # 3 個：是字
    marked = _long_runs(dark, 5)
    assert marked[0, 1:9].all() and not marked[0, 0] and not marked[0, 9]
    assert not marked[1].any()


def test_table_lines_are_erased_before_ocr():
    """框線擦掉、字留著；回傳 RGB（Tesseract 不收灰階）。"""
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    page.draw_rect(pymupdf.Rect(10, 10, 190, 90), color=(0, 0, 0), width=1.5)
    page.insert_text((60, 55), "S1-11", fontsize=14)
    pixmap, pad = _without_lines(page, page.rect, 200)
    assert pixmap.n == 3
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)[..., 0]
    border_row = pad + int(10 * 200 / 72)
    assert (image[border_row - 2 : border_row + 3, pad + 100] > 200).all()
    assert (image < 100).sum() > 50  # 字還在
