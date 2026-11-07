"""掃描契約圖的圖號：讀圖號索引表當成白名單，再整冊一起決定每一頁的圖號。

每頁標題欄的圖號 OCR 會讀錯（「S2-02」讀成「S9-02」、「A10-17」讀成「NI0-17」），而讀錯的圖號比
沒有圖號更糟（spec 第 8 節）。同一冊通常有圖號索引表，字大、排得整齊，OCR 讀得比標題欄準。所以：

1. 索引表：圖名有「索引」「目錄」的頁，以及前三頁（秀山結構圖的索引頁圖名 OCR 讀不出來），
   讀到十張以上才算。擦掉框線、切成幾塊、用英文模型讀兩種解析度，收集像圖號的字。
   索引表只當**白名單**、不看它的排列順序：秀山建築圖的第 3、4 頁是別冊的索引表，多欄排版也讓
   OCR 排出來的順序不可靠（實測照索引表順序補圖號，補錯了好幾頁）。白名單要先清掉讀錯的字：
   流水號不是兩位數的（「E1-002」「A10-062R」）、字首太少見的（「S-01」）、和更常見的字首只差一個
   易混字的（「AS-10」之於「A5-10」）。
2. 每頁的幾種讀法投票：在白名單裡的一票算兩分；同一頁兩種以上讀法一模一樣、卻不在白名單的
   （索引表沒讀到的那一段，秀山水電圖的 AC、ES 整段），照它；只讀到一次、不在白名單的，差一個字、
   且白名單裡只有一張這麼接近的，算一分給那一張。「差一個字」只算少一個字、多一個字，或換成同類的字
   （字母換字母、數字換數字）與易混字——「F1-04」不會被拉到「01-04」。
   兩頁投出同一個圖號的，兩頁都不算（秀山結構圖第 12 頁兩種讀法都把 S2-13 讀成 S2-15）。
   有索引表時，白名單外的圖號整冊至少兩頁是同一種字首才收：孤零零一張「S-01」是讀錯（真的是 A5-01）。
3. 同一個字首的圖照編號順序裝訂：頁序和編號順序對不上的（第 8 頁讀成「S7-01」，前後是 S1-24、S2-02）丟掉。
4. 同字首的兩張已確定的圖之間，沒讀到的頁數剛好等於白名單裡編號介於兩者之間的張數，就照編號補上。

沒有索引表的冊子：白名單是空的，只剩「兩種讀法一致」與 3；4 不補。

秀山三冊實測（2026-11，fast 模型）見 docs/guide.md「掃描契約圖」。
"""

import re
from collections import Counter

import pymupdf
from rapidfuzz.distance import Levenshtein

from app.parsers.ocr import OcrEngine
from app.specs.scanned_title_block import STRIP_FROM, _ocr_lines, sheet_numbers_in

#: 圖名有這些字的頁是圖號索引表
INDEX_TITLE = re.compile(r"索\s*引|目\s*錄")
#: 圖名沒讀出「索引」也試讀的前幾頁；讀到這麼多張以上才當成索引表
FRONT_PAGES = 3
MIN_INDEX_ENTRIES = 10
#: 索引表切成幾欄幾列分塊辨識（整頁一次辨識時，表格線讓 Tesseract 幾乎什麼都讀不到）
TILE_COLUMNS, TILE_ROWS = 4, 2
TILE_OVERLAP = 20
INDEX_DPIS = (300, 400)
#: 同一種字首（字母＋數字位數：「S1」「A2」「TC0」「#2」）在索引表裡至少出現幾張，才不是讀錯
MIN_PREFIX_COUNT = 3
#: 同一個位置（pt 以內）讀到兩個不同的字，算同一格，取票多的
SAME_CELL = 6
#: OCR 常互相讀錯的字
CONFUSABLE = {frozenset(pair) for pair in ("S5", "O0", "I1", "B8", "G6", "Z2")}

_PARTS = re.compile(r"^([A-Z]*)(\d*)-(\d+)([A-Z]?)$")
_TWO_DIGIT_SERIAL = re.compile(r"-\d{2}[A-Z]?$")


def might_be_index(page_no: int, title: str) -> bool:
    return page_no <= FRONT_PAGES or bool(INDEX_TITLE.search(title))


def read_index(page: pymupdf.Page, engine: OcrEngine) -> list[str]:
    """索引表上讀到的圖號（未清理）。不到 MIN_INDEX_ENTRIES 張就不是索引表，回空清單。"""
    width, height = page.rect.width, page.rect.height
    area = pymupdf.Rect(0, 0, width * STRIP_FROM, height)
    readings: list[tuple[float, float, str]] = []
    for dpi in INDEX_DPIS:
        for column in range(TILE_COLUMNS):
            for row in range(TILE_ROWS):
                tile = pymupdf.Rect(
                    area.x0 + area.width * column / TILE_COLUMNS - TILE_OVERLAP,
                    area.y0 + area.height * row / TILE_ROWS - TILE_OVERLAP,
                    area.x0 + area.width * (column + 1) / TILE_COLUMNS + TILE_OVERLAP,
                    area.y0 + area.height * (row + 1) / TILE_ROWS + TILE_OVERLAP,
                ) & area
                for rect, text in _ocr_lines(page, tile, dpi, engine, language="eng", erase_lines=True):
                    readings += [(rect.x0, rect.y0, number) for number in sheet_numbers_in(text)]
    entries = _cell_entries(readings)
    return entries if len(entries) >= MIN_INDEX_ENTRIES else []


def _cell_entries(readings: list[tuple[float, float, str]]) -> list[str]:
    """兩種解析度、重疊分塊會把同一格讀好幾次：位置相近的歸成一格，取票多的那個寫法。"""
    counts = Counter(number for _, _, number in readings)
    cells: list[list[tuple[float, float, str]]] = []
    for reading in sorted(readings, key=lambda r: (r[1], r[0])):
        cell = next(
            (c for c in cells if abs(c[0][0] - reading[0]) < SAME_CELL and abs(c[0][1] - reading[1]) < SAME_CELL), None
        )
        if cell is None:
            cells.append([reading])
        else:
            cell.append(reading)
    chosen = [max(Counter(r[2] for r in cell).items(), key=lambda item: (item[1], counts[item[0]]))[0] for cell in cells]
    return sorted(set(chosen), key=_key)


def clean_index(entries: list[str]) -> set[str]:
    """索引表 OCR 讀到的字 -> 白名單。"""
    entries = {n for n in entries if _TWO_DIGIT_SERIAL.search(n) and _PARTS.match(n)}
    kinds = Counter(_kind(n) for n in entries)
    entries = {n for n in entries if kinds[_kind(n)] >= MIN_PREFIX_COUNT}
    return {
        n for n in entries
        if not any(kinds[_kind(other)] > kinds[_kind(n)] and _confusable(n, other) for other in entries)
    }


def _confusable(a: str, b: str) -> bool:
    """只差一個字，而且是 OCR 常讀錯的那種（S/5、O/0…）。「E1-02」與「F1-02」不算——兩個都可能是真的。"""
    if len(a) != len(b):
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diff) == 1 and frozenset(diff[0]) in CONFUSABLE


def _kind(number: str) -> str:
    """字首種類：「S1-22」->「S1」、「A10-01」->「A2」、「TC-01」->「TC0」、「00-01」->「#2」。"""
    letters, digits, _, _ = _PARTS.match(number).groups()
    return f"{letters or '#'}{len(digits)}"


def _letters(number: str) -> str:
    return _PARTS.match(number).group(1)


def _key(number: str) -> tuple:
    """同字首內的編號順序：「A2-01」<「A2-02」<「A10-01」。"""
    match = _PARTS.match(number)
    if not match:
        return ("~", number)
    letters, digits, serial, suffix = match.groups()
    return (letters, int(digits) if digits else -1, int(serial), suffix)


def assign(candidates: list[list[str]], index: list[str]) -> list[str | None]:
    """每一頁的圖號（或 None）。candidates[i] 是第 i 頁標題欄的幾種讀法；index 是索引表讀到的字（未清理）。"""
    known = clean_index(index)
    chosen = _without_repeats([_vote(readings, known) for readings in candidates])
    if known:
        kinds = Counter(_kind(n) for n in chosen if n)
        chosen = [n if n is None or n in known or kinds[_kind(n)] >= 2 else None for n in chosen]
    chosen = _in_order(chosen)
    return _fill_gaps(chosen, known)


def _vote(readings: list[str], known: set[str]) -> str | None:
    votes: Counter[str] = Counter()
    for reading, count in Counter(r for r in readings if _PARTS.match(r)).items():
        if reading in known:
            votes[reading] += 2 * count
        elif count >= 2:
            votes[reading] += count
        else:
            near = [number for number in known if _one_slip(reading, number)]
            if len(near) == 1:
                votes[near[0]] += 1
            elif not near:
                votes[reading] += 1
    if not votes:
        return None
    ranked = votes.most_common(2)
    if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
        return None
    number, score = ranked[0]
    # 白名單外的讀法：要兩種讀法一致
    return number if number in known or score >= 2 else None


def _one_slip(reading: str, number: str) -> bool:
    """reading 是 number 讀錯一個字：少一個、多一個，或換成同類的字、易混字。"""
    if Levenshtein.distance(reading, number, score_cutoff=1) != 1:
        return False
    op = Levenshtein.editops(reading, number)[0]
    if op.tag != "replace":
        return True
    a, b = reading[op.src_pos], number[op.dest_pos]
    return a.isdigit() == b.isdigit() or frozenset((a, b)) in CONFUSABLE


def _without_repeats(chosen: list[str | None]) -> list[str | None]:
    """同一個圖號投給兩頁以上：至少一頁是讀錯，又分不出是哪一頁，全部不算。"""
    repeated = {n for n, count in Counter(n for n in chosen if n).items() if count > 1}
    return [None if n in repeated else n for n in chosen]


def _in_order(chosen: list[str | None]) -> list[str | None]:
    """同一個字首裡，留下頁序和編號順序一致的最多張（最長遞增子序列），其餘的是讀錯。"""
    kept = list(chosen)
    for letters in {_letters(n) for n in chosen if n}:
        pages = [i for i, n in enumerate(chosen) if n and _letters(n) == letters]
        best: list[list[int]] = []  # best[k]：以 pages[k] 結尾的最長序列
        for k, page in enumerate(pages):
            chain = max(
                (best[j] for j in range(k) if _key(chosen[pages[j]]) < _key(chosen[page])), key=len, default=[]
            )
            best.append(chain + [page])
        longest = set(max(best, key=len, default=[]))
        for page in pages:
            if page not in longest:
                kept[page] = None
    return kept


def _fill_gaps(chosen: list[str | None], known: set[str]) -> list[str | None]:
    """同字首的兩張已確定的圖之間，沒讀到的頁數剛好等於白名單裡編號介於兩者之間的張數，就照編號補上。"""
    ordered = sorted(known, key=_key)
    used = {n for n in chosen if n}
    filled = list(chosen)
    anchors = [(page, n) for page, n in enumerate(chosen) if n]
    for (page_a, a), (page_b, b) in zip(anchors, anchors[1:]):
        if page_b - page_a < 2 or _letters(a) != _letters(b):
            continue
        between = [n for n in ordered if _letters(n) == _letters(a) and _key(a) < _key(n) < _key(b)]
        if len(between) == page_b - page_a - 1 and not used & set(between):
            for step, number in enumerate(between, start=1):
                filled[page_a + step] = number
    return filled
