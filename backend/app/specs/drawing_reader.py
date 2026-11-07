"""契約圖的圖號索引，以及工項對到哪幾張圖（檢核表階段 2、4）。

圖面內容系統讀不懂（尺寸、線條），能可靠讀到的只有**文字**：每張圖標題欄的
「圖號：S-12」「圖名：模板組立詳圖」，或圖說目錄頁一行一張的「S-12 模板組立詳圖」。
所以這裡只做兩件事：列出有哪些圖，以及用圖名找出和工項相關的圖號——給人去翻圖，
不替人判斷圖上畫了什麼（spec 第 7 節）。

**用真實圖驗證過（2026-11）**：某宿舍統包工程的建築竣工圖（CAD 匯出，331 頁）讀到 330 頁。
CAD 匯出的標題欄裡，標籤「圖號：」「DRG. NO.」和值「A2-08B」是**分開的文字物件**，文字順序
也不照版面，所以標題欄靠位置讀：離「圖號」標籤最近、長得像圖號的那一行，和離「圖名」標籤
最近的中文那一行。同案的結構圖是掃描檔，整份沒有文字層時改走 _read_scanned
（OCR 標題欄，圖號由同冊的掃描索引表整冊決定，見 scanned_sheet_index）。同案的結構**竣工**圖是 CAD 匯出，但圖號（與部分圖名）
被轉成淡灰髮絲線、不在文字層，標題欄那兩格加粗線寬後 OCR（_OutlinedTitleBlock）。

圖名比對刻意保守：對錯圖號比沒有圖號更糟（spec 第 8 節）。只比圖名去掉「詳圖」
「平面圖」這類圖種字尾之後的主體，兩個條件都要成立才算相關：

- 主體開頭兩個字（通常是主要名詞：模板、鋼筋、屋頂）出現在工項名稱裡；
- 主體的字有一半以上出現在工項名稱裡。

只看第二條的話，「鋼筋，含加工及組立」會因為「組立」兩字對到「模板組立詳圖」。
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

#: 圖號：S-12、A2-08B、A10-10E、L1-01-2
_SHEET_NO = r"[A-Z]{1,3}\d{0,2}-\d{1,3}[A-Z]?(?:-\d{1,2}[A-Z]?)?"
#: 標題欄，標籤和值寫在同一行：「圖號：S-12」「圖名：模板組立詳圖」
_TITLE_BLOCK_NO = re.compile(rf"圖\s*號\s*[:：]\s*(?P<no>{_SHEET_NO})")
_TITLE_BLOCK_NAME = re.compile(r"圖\s*名\s*[:：]\s*(?P<title>[^\s:：]{2,40})")
#: 圖說目錄：一行「S-12 模板組立詳圖」
_INDEX_LINE = re.compile(rf"^\s*(?P<no>{_SHEET_NO})\s+(?P<title>[^\s]{{2,40}})\s*$", re.MULTILINE)

#: 標題欄，標籤和值分開擺（CAD 匯出）：值是離標籤最近的那一行
_NO_LABEL = re.compile(r"^圖\s*號")
_NAME_LABEL = re.compile(r"^圖\s*名$")
_NO_VALUE = re.compile(rf"^{_SHEET_NO}$")
_CJK = re.compile(r"[一-鿿]")
#: 標題欄裡不是圖名的中文：標籤、工程名稱（「…統包工程」）、單位名稱、「竣工圖」字樣。
#: 只擋「工程」結尾——「假設工程圖」是圖名
_NOT_A_TITLE = re.compile(
    r"^圖\s*名$|^張\s*數|^說\s*明$|^圖\s*例$|[:：]|竣\s*工\s*圖|工\s*程\s*名\s*稱|工程$|事務所|公司|工程處"
    # 圖面註解的句子：「2. 為使結構體之高度…」「…的範圍。」
    r"|^\d+\s*[.、．]|。$"
)
#: 像圖名的寫法。圖名欄旁邊偶爾有圖面註解（「CNS 8644規範規定。」）比圖名更靠近標籤，
#: 所以距離內有像圖名的就取它，沒有才取最近的（「東北向立面瓦斯管線位置」這種沒寫「圖」的）
_LOOKS_LIKE_TITLE = re.compile(r"(?:圖|表)(?:[（(][一二三四五六七八九十\d]+[)）])?$")
#: 值離標籤超過這個距離（pt）就不算：沒有值的空欄位不能撿到圖面上的字。
#: 真實圖的圖名欄最遠量到 168 pt
MAX_LABEL_DISTANCE = 200

#: 圖名常用字：含這些字的三字串不會被當成簽名拿掉
_DRAWING_WORD = re.compile(r"圖|面|詳|配|層|系統|表|樓梯|門窗|地坪|版|柱|梁|牆|筋|索引|說明")
#: 每頁文字少於這個字數，就當成掃描頁（只有頁碼或印章字樣）
_SCANNED_TEXT_LIMIT = 50

#: 圖種字尾：比對時去掉，只留下「畫的是什麼」。前面先去掉分張編號「(二)」
_SHEET_PART = re.compile(r"[（(][一二三四五六七八九十\d]+[)）]$")
_DRAWING_KIND = re.compile(r"(?:詳圖|大樣圖|平面圖|立面圖|剖面圖|配置圖|系統圖|示意圖|圖說|圖)$")
#: 圖名主體的字至少要有這個比例出現在工項名稱裡
MIN_OVERLAP = 0.5


@dataclass(frozen=True)
class DrawingSheetRow:
    sheet_no: str
    title: str
    page: int
    #: 由 OCR 從掃描的標題欄讀出，可能有錯字（scanned_title_block）
    is_ocr: bool = False


def read_drawing_sheets(path: Path) -> list[DrawingSheetRow]:
    """讀出契約圖裡的每一張圖。標題欄優先；整份都沒有標題欄時改讀圖說目錄。"""
    sheets: dict[str, DrawingSheetRow] = {}
    pages: list[tuple[int, str]] = []
    #: 圖號索引表（文字層）的「圖號 → 圖名」；OCR 讀到圖號的頁拿它校正圖名
    index: dict[str, str] = {}
    #: OCR 讀到圖號、圖名卻讀不出來的頁
    untitled: list[tuple[str, int]] = []
    outlined = _OutlinedTitleBlock()
    with pymupdf.open(str(path)) as document:
        for page_no, page in enumerate(document, start=1):
            text = page.get_text()
            pages.append((page_no, text))
            index.update((number, title) for number, title in _index_entries(page) if number not in index)
            inline = _title_block_inline(text)
            if inline:
                number, title, is_ocr = *inline, False
            else:
                block = _title_block_by_position(page)
                if block is None:
                    continue
                number, title, is_ocr = block.number, block.title, False
                if number is None:
                    # 圖號被轉成線條（另一冊真實結構竣工圖）：圖號格 OCR。這種頁圖名多半也是線條，
                    # 文字層裡離表頭最近的中文常是圖面註解，所以圖名格也 OCR，讀不到才用文字層的
                    number = outlined.number(page, block.no_label)
                    ocr_title = outlined.title(page, block.no_label, block.name_label)
                    is_ocr = number is not None or ocr_title is not None
                    title = ocr_title or title
                    if number and not title:
                        untitled.append((number, page_no))
                        continue
                if not title:
                    continue
            sheet_no = number or f"第{page_no}頁"
            sheets.setdefault(sheet_no, DrawingSheetRow(sheet_no, title[:255], page_no, is_ocr))
    if sheets or untitled:
        return _titles_from_index(sheets, untitled, index)

    for page_no, text in pages:
        for match in _INDEX_LINE.finditer(text):
            sheets.setdefault(match.group("no"), DrawingSheetRow(match.group("no"), match.group("title"), page_no))
    if sheets or not _is_scanned([text for _, text in pages]):
        return list(sheets.values())
    return _without_repeated_signature(_read_scanned(path))


def _index_entries(page: pymupdf.Page) -> list[tuple[str, str]]:
    """圖號索引表的列：圖號右邊同一行緊貼的中文（「S1-02　地下二層結構平面圖」）。"""
    lines = _lines(page)
    entries = []
    for rect, number in lines:
        if not _NO_VALUE.match(number):
            continue
        middle = (rect.y0 + rect.y1) / 2
        beside = [
            (other.x0 - rect.x1, text) for other, text in lines
            if _CJK.search(text) and abs((other.y0 + other.y1) / 2 - middle) < 4 and 0 <= other.x0 - rect.x1 < 80
        ]
        if beside:
            entries.append((number, min(beside)[1]))
    return entries


def _titles_from_index(
    sheets: dict[str, DrawingSheetRow], untitled: list[tuple[str, int]], index: dict[str, str]
) -> list[DrawingSheetRow]:
    """OCR 讀到圖號的頁，圖名改用同一冊圖號索引表（文字層，沒有錯字）的寫法；圖名 OCR 讀不出來的頁，
    圖號在索引表裡就照索引表列出；圖號讀不到、圖名和索引表某一張一字不差的，補上那張的圖號。
    圖號仍是 OCR 讀的，所以照樣標 OCR。"""
    by_title: dict[str, list[str]] = {}
    for number, title in index.items():
        by_title.setdefault(title, []).append(number)
    fixed: dict[str, DrawingSheetRow] = {}
    for number, row in sheets.items():
        if row.is_ocr and number in index:
            row = DrawingSheetRow(number, index[number], row.page, True)
        elif row.is_ocr and number.startswith("第") and len(by_title.get(row.title, [])) == 1:
            # 圖號讀不到、圖名 OCR 讀得一字不差：索引表裡只有一張叫這個名字，就用它的圖號
            row = DrawingSheetRow(by_title[row.title][0], row.title, row.page, True)
        fixed.setdefault(row.sheet_no, row)
    for number, page_no in untitled:
        if number in index and number not in fixed:
            fixed[number] = DrawingSheetRow(number, index[number], page_no, True)
    return sorted(fixed.values(), key=lambda row: row.page)


def _is_scanned(page_texts: list[str]) -> bool:
    """八成以上的頁沒有文字層就是掃描冊。秀山水電圖 117 頁裡有 2 頁帶文字，仍是掃描冊。"""
    if not page_texts:
        return False
    empty = sum(1 for text in page_texts if len(text.strip()) <= _SCANNED_TEXT_LIMIT)
    return empty / len(page_texts) >= 0.8


def _without_repeated_signature(rows: list[DrawingSheetRow]) -> list[DrawingSheetRow]:
    """OCR 會把標題欄的簽名黏進圖名。同一冊每張都簽同一個名字，所以整冊四分之一以上的圖名都有、
    又不含圖面用字（圖、面、詳、配、層…）的三字串，就當成簽名拿掉——不寫死任何人名。"""
    if len(rows) < 4:
        return rows
    counts: dict[str, int] = {}
    for row in rows:
        for gram in {row.title[i:i + 3] for i in range(len(row.title) - 2)}:
            counts[gram] = counts.get(gram, 0) + 1
    noise = [
        gram for gram, count in counts.items()
        if count >= max(2, len(rows) / 4) and _CJK.fullmatch(gram[0]) and not _DRAWING_WORD.search(gram)
    ]
    signatures = _trailing_signatures(rows)
    cleaned = []
    for row in rows:
        title = row.title
        for gram in sorted(noise, key=len, reverse=True):
            title = title.replace(gram, "")
        title = _without_near(title, signatures)
        title = re.sub(r"[^一-鿿)）]+$", "", title)
        cleaned.append(DrawingSheetRow(row.sheet_no, title.strip("=|/、,，") or row.title, row.page, row.is_ocr))
    return cleaned


#: 圖名已經完整結束（「…配置圖」「…數量表」），後面又多出三個中文字：多半是簽名
_AFTER_COMPLETE_TITLE = re.compile(r"(?:圖|表)[^一-鿿]{0,2}([一-鿿]{3})$")


def _trailing_signatures(rows: list[DrawingSheetRow]) -> list[str]:
    """簽名的讀法會變（同一個名字讀成兩三種），整冊四分之一的門檻抓不到。改看「完整圖名後面多出來的
    三個字」：兩張以上圖出現同一組（三個字有兩個相同就算同一組）、又不含圖面用字，就是簽名。"""
    tails = [m.group(1) for row in rows if (m := _AFTER_COMPLETE_TITLE.search(row.title))]
    tails = [tail for tail in tails if not _DRAWING_WORD.search(tail)]
    return sorted({tail for tail in tails if sum(_near(tail, other) for other in tails) >= 2})


def _near(a: str, b: str) -> bool:
    return len(a) == len(b) == 3 and sum(x == y for x, y in zip(a, b)) >= 2


def _without_near(title: str, signatures: list[str]) -> str:
    """拿掉圖名裡和簽名只差一個字的三字串（「王太明」之於「王大明」這類 OCR 變體）。"""
    if not signatures:
        return title
    i = 0
    while i <= len(title) - 3:
        gram = title[i:i + 3]
        if not _DRAWING_WORD.search(gram) and any(_near(gram, signature) for signature in signatures):
            title = title[:i] + title[i + 3:]
        else:
            i += 1
    return title


def _read_scanned(path: Path) -> list[DrawingSheetRow]:
    """整份都沒有文字層（用印後掃描）：OCR 讀每一頁的標題欄，圖號再由同一冊的圖號索引表整冊一起決定
    （scanned_sheet_index）。OCR 不能用時回空清單，檢核表會說明這一冊讀不到。"""
    from app.parsers import ocr
    from app.specs.scanned_sheet_index import assign, best_title, might_be_index, read_index
    from app.specs.scanned_title_block import read_title_block

    engine, reason = ocr.load_engine()
    if engine is None:
        logger.warning("掃描的契約圖需要 OCR，但 OCR 不能用：%s", reason)
        return []
    best = ocr.load_best_engine()
    titles: list[str] = []
    readings: list[list[str]] = []
    #: 索引表上的圖號 -> 它的圖名的幾種讀法
    index: dict[str, list[str]] = {}
    with pymupdf.open(str(path)) as document:
        for page_no, page in enumerate(document, start=1):
            numbers, title = read_title_block(page, engine)
            if best is not None and not _good_scanned_title(title):
                # fast 模型讀不出像圖名的：best 模型補讀，取比較像圖名的那個（秀山水電圖實測各有勝負）
                better_numbers, better_title = read_title_block(page, best)
                if _scanned_title_score(better_title) > _scanned_title_score(title):
                    title = better_title
                numbers = numbers + better_numbers
            if might_be_index(page_no, title):
                for number, readings_of_title in read_index(page, engine).items():
                    index.setdefault(number, []).extend(readings_of_title)
            titles.append(title)
            readings.append(numbers)
    sheets: dict[str, DrawingSheetRow] = {}
    for page_no, (title, number) in enumerate(zip(titles, assign(readings, list(index))), start=1):
        if number in index:
            # 索引表的圖名和標題欄的一起投票；標題欄讀不出圖名的頁也因此列得出來
            title = best_title(index[number], title)
        if not title:
            continue
        sheet_no = number or f"第{page_no}頁"
        sheets.setdefault(sheet_no, DrawingSheetRow(sheet_no, title[:255], page_no, is_ocr=True))
    return list(sheets.values())


#: 掃描圖名「像樣」的結尾：「…圖」「…圖(2)」「…表」「…說明」
_SCANNED_TITLE_END = re.compile(r"(?:圖|表|說明)(?:[（(][一二三四五六七八九十\d]+[)）])?$")


def _scanned_title_score(title: str) -> int:
    """中文字數，結尾像圖名再加 10。用來在兩個模型的讀法之間挑一個。"""
    return len(_CJK.findall(title)) + (10 if _SCANNED_TITLE_END.search(title) else 0)


def _good_scanned_title(title: str) -> bool:
    return len(_CJK.findall(title)) >= 4 and bool(_SCANNED_TITLE_END.search(title))


def _title_block_inline(text: str) -> tuple[str, str] | None:
    number, name = _TITLE_BLOCK_NO.search(text), _TITLE_BLOCK_NAME.search(text)
    return (number.group("no"), name.group("title")) if number and name else None


@dataclass(frozen=True)
class _TitleBlock:
    no_label: pymupdf.Rect
    name_label: pymupdf.Rect
    #: 文字層讀不到時是 None，讓呼叫端去 OCR
    number: str | None
    title: str | None


def _title_block_by_position(page: pymupdf.Page) -> _TitleBlock | None:
    """有「圖號」「圖名」兩個標籤的頁：標籤位置，與文字層裡讀得到的圖號、圖名。"""
    lines = _lines(page)
    no_labels = [rect for rect, text in lines if _NO_LABEL.match(text)]
    name_labels = [rect for rect, text in lines if _NAME_LABEL.match(text)]
    if not no_labels or not name_labels:
        return None
    # 圖號索引表的表頭也有「圖號」「圖名」兩欄；標題欄的標籤有冒號（「圖號：」），以它為準，
    # 圖名標籤取離它最近的那一個
    no_label = next((rect for rect, text in lines if _NO_LABEL.match(text) and re.search(r"[:：]", text)), no_labels[0])
    name_label = min(name_labels, key=lambda rect: abs((rect.tl + rect.br) / 2 - (no_label.tl + no_label.br) / 2))
    number = _nearest(no_label, [(r, t) for r, t in lines if _NO_VALUE.match(t)])
    numbers = [r for r, t in lines if _NO_VALUE.match(t)]
    titles = [
        (r, t) for r, t in lines
        if len(t) >= 2 and _CJK.search(t) and not _NOT_A_TITLE.search(t) and not _is_index_entry(r, numbers)
    ]
    title = _nearest(name_label, [(r, t) for r, t in titles if _LOOKS_LIKE_TITLE.search(t)]) or _nearest(
        name_label, titles
    )
    return _TitleBlock(no_label, name_label, number, title)


def _is_index_entry(rect: pymupdf.Rect, numbers: list[pymupdf.Rect]) -> bool:
    """圖號索引表的一列：同一行左邊緊貼著一個圖號（「A2-08B　八層放大平面圖(二)」）。它不是這一頁的圖名。"""
    middle = (rect.y0 + rect.y1) / 2
    return any(abs((n.y0 + n.y1) / 2 - middle) < 4 and 0 <= rect.x0 - n.x1 < 40 for n in numbers)


class _OutlinedTitleBlock:
    """CAD 圖的圖號、圖名被轉成線條時，用 OCR 讀標題欄那兩格。OCR 引擎只在第一次需要時載入。

    真實結構竣工圖的圖號、圖名是寬度 0 的淡灰髮絲線，照常算圖時筆畫只剩斷續的灰點，OCR 讀不到；
    所以算圖時把最細線寬拉到幾個像素（OUTLINE_*_TRIES）。圖號格要把「圖號：」標籤一起框進去
    （只框值那一小格時 Tesseract 反而什麼都不回）。
    """

    def __init__(self):
        self._engine = None
        #: TESSDATA_BEST_PATH 設了才有：fast 模型每組參數都讀不出來時，再用 best 模型試一輪
        self._best = None
        self._loaded = False

    def _ready(self) -> bool:
        if not self._loaded:
            from app.parsers import ocr

            self._engine, _ = ocr.load_engine()
            self._best = ocr.load_best_engine() if self._engine is not None else None
            self._loaded = True
        return self._engine is not None

    def _engines(self):
        return [engine for engine in (self._engine, self._best) if engine is not None]

    def number(self, page: pymupdf.Page, label: pymupdf.Rect) -> str | None:
        if not self._ready():
            return None
        cell = pymupdf.Rect(label.x0 - 14, label.y0 - 14, label.x1 + OUTLINE_CELL_WIDTH, label.y1 + 14) & page.rect
        for engine in self._engines():
            for width, dpi in OUTLINE_NUMBER_TRIES:
                for _, text in self._ocr(engine, page, cell, "eng", width, dpi):
                    number = _outlined_number(text)
                    if number:
                        return number
        return None

    def title(self, page: pymupdf.Page, no_label: pymupdf.Rect, name_label: pymupdf.Rect) -> str | None:
        """圖名格：「圖名」表頭下方到「圖號」那一列上方，左邊從圖號標籤起、以表頭為中心左右對稱。

        同一格換個線寬、解析度或框緊一點，Tesseract 的結果就不一樣（真實結構竣工圖實測），所以輪流試幾組，
        只收長得像圖名的（「…圖」「…圖(一)」「…說明」）；都沒有就回 None，這一頁不列——錯的圖名比沒有更糟。
        """
        if not self._ready() or name_label.y1 >= no_label.y0:
            return None
        center = (name_label.x0 + name_label.x1) / 2
        for engine in self._engines():
            for inset, width, dpi in OUTLINE_TITLE_TRIES:
                left = no_label.x0 - 14 + inset
                cell = pymupdf.Rect(
                    left, name_label.y1 + 12 + inset, 2 * center - left, no_label.y0 - 2 - inset
                ) & page.rect
                if cell.is_empty:
                    continue
                for _, text in self._ocr(engine, page, cell, None, width, dpi):
                    title = "".join(text.split()).strip("|")
                    if _looks_like_ocr_title(title):
                        return title
        return None

    @staticmethod
    def _ocr(engine, page: pymupdf.Page, cell: pymupdf.Rect, language: str | None, width: float, dpi: int):
        from app.specs.scanned_title_block import _ocr_lines

        pymupdf.TOOLS.set_graphics_min_line_width(width)
        try:
            return _ocr_lines(page, cell, dpi, engine, language=language)
        finally:
            pymupdf.TOOLS.set_graphics_min_line_width(0)


#: 圖號那一格的寬度（pt，從標籤右緣算）
OUTLINE_CELL_WIDTH = 300
#: 依序試的（最細線寬 像素, 解析度）與（圖名格內縮 pt, 線寬, 解析度）
OUTLINE_NUMBER_TRIES = ((3, 200), (3, 300), (2, 300))
OUTLINE_TITLE_TRIES = ((0, 3, 200), (0, 2, 300), (8, 3, 200), (8, 2, 300), (0, 3, 300))
#: OCR 讀出的圖名要長這樣才收：「…圖」「…圖(一)」「…表」「…說明」
_OCR_TITLE = re.compile(r"(?:圖|表)(?:[（(][一二三四五六七八九十\d—–=-]+[)）])?$|說明$")


def _looks_like_ocr_title(title: str) -> bool:
    """中文佔八成以上（括號不算），結尾像圖名。擋掉「BERTI,剖面圖」這種半截英文雜訊。"""
    body = re.sub(r"[（()）一二三四五六七八九十—–=-]+$", "", title)
    cjk = len(_CJK.findall(body))
    return cjk >= 2 and cjk >= 0.8 * len(body) and bool(_OCR_TITLE.search(title)) and not _NOT_A_TITLE.search(title)


def _outlined_number(text: str) -> str | None:
    """OCR 讀到的一行裡的圖號（換回原本寫法的規則見 scanned_title_block.sheet_numbers_in）。
    CAD 圖的圖號一定有字母開頭，所以「00-01」這種不收。"""
    from app.specs.scanned_title_block import sheet_numbers_in

    return next((number for number in sheet_numbers_in(text) if _NO_VALUE.match(number)), None)


def _lines(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(line["bbox"]), text))
    return lines


def _nearest(label: pymupdf.Rect, candidates: list[tuple[pymupdf.Rect, str]]) -> str | None:
    def distance(rect: pymupdf.Rect) -> float:
        a, b = (label.tl + label.br) / 2, (rect.tl + rect.br) / 2
        return abs(a - b)

    scored = [(distance(rect), text) for rect, text in candidates]
    best = min(scored, default=None)
    return best[1] if best and best[0] <= MAX_LABEL_DISTANCE else None


def drawing_subject(title: str) -> str:
    """「模板組立詳圖」->「模板組立」；「八層放大平面圖(二)」->「八層放大」。"""
    title = _SHEET_PART.sub("", title) or title
    return _DRAWING_KIND.sub("", title) or title


#: 圖名裡不會出現、但固定畫在某幾種圖上的東西。秀山水電圖沒有一張叫「開關箱」：每個開關箱、配電盤
#: 畫在電氣單線圖與負載表上（圖說索引的說明也這樣寫），所以名稱對不到也算相關。
SHOWN_ON = {
    ("開關箱", "配電盤", "分電盤", "電錶箱", "電表箱"): ("單線圖", "負載表"),
}


def is_related(item_name: str, sheet_title: str) -> bool:
    for things, kinds in SHOWN_ON.items():
        if any(thing in item_name for thing in things) and any(kind in sheet_title for kind in kinds):
            return True
    subject = drawing_subject(sheet_title)
    if len(subject) < 2 or subject[:2] not in item_name:
        return False
    hits = sum(1 for char in set(subject) if char in item_name)
    return hits / len(set(subject)) >= MIN_OVERLAP and hits >= 2


def related_sheets(item_name: str, sheets) -> list:
    """和工項名稱相關的圖，依圖號排序。sheets 可以是 DrawingSheetRow 或 DrawingSheet。"""
    return sorted((s for s in sheets if is_related(item_name, s.title)), key=lambda s: s.sheet_no)
