"""契約圖的圖號索引，以及工項對到哪幾張圖（檢核表階段 2、4）。

圖面內容系統讀不懂（尺寸、線條），能可靠讀到的只有**文字**：每張圖標題欄的
「圖號：S-12」「圖名：模板組立詳圖」，或圖說目錄頁一行一張的「S-12 模板組立詳圖」。
所以這裡只做兩件事：列出有哪些圖，以及用圖名找出和工項相關的圖號——給人去翻圖，
不替人判斷圖上畫了什麼（spec 第 7 節）。

**用真實圖驗證過（2026-11）**：某宿舍統包工程的建築竣工圖（CAD 匯出，331 頁）讀到 330 頁。
CAD 匯出的標題欄裡，標籤「圖號：」「DRG. NO.」和值「A2-08B」是**分開的文字物件**，文字順序
也不照版面，所以標題欄靠位置讀：離「圖號」標籤最近、長得像圖號的那一行，和離「圖名」標籤
最近的中文那一行。同案的結構圖是掃描檔，OCR 讀得到部分圖名、讀不到圖號（每頁約 5 秒），
不支援——讀到零張時檢核表會說明原因，不判斷階段 2。

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
    with pymupdf.open(str(path)) as document:
        for page_no, page in enumerate(document, start=1):
            text = page.get_text()
            pages.append((page_no, text))
            found = _title_block_inline(text) or _title_block_by_position(page)
            if found:
                sheets.setdefault(found[0], DrawingSheetRow(found[0], found[1], page_no))
    if sheets:
        return list(sheets.values())

    for page_no, text in pages:
        for match in _INDEX_LINE.finditer(text):
            sheets.setdefault(match.group("no"), DrawingSheetRow(match.group("no"), match.group("title"), page_no))
    if sheets or not _is_scanned([text for _, text in pages]):
        return list(sheets.values())
    return _without_repeated_signature(_read_scanned(path))


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
        if count >= len(rows) / 4 and _CJK.fullmatch(gram[0]) and not _DRAWING_WORD.search(gram)
    ]
    cleaned = []
    for row in rows:
        title = row.title
        for gram in sorted(noise, key=len, reverse=True):
            title = title.replace(gram, "")
        cleaned.append(DrawingSheetRow(row.sheet_no, title.strip("=|/、,，") or row.title, row.page, row.is_ocr))
    return cleaned


def _read_scanned(path: Path) -> list[DrawingSheetRow]:
    """整份都沒有文字層（用印後掃描）：OCR 讀每一頁的標題欄。OCR 不能用時回空清單，
    檢核表會說明這一冊讀不到。"""
    from app.parsers import ocr
    from app.specs.scanned_title_block import read_title_block

    engine, reason = ocr.load_engine()
    if engine is None:
        logger.warning("掃描的契約圖需要 OCR，但 OCR 不能用：%s", reason)
        return []
    sheets: dict[str, DrawingSheetRow] = {}
    with pymupdf.open(str(path)) as document:
        for page_no, page in enumerate(document, start=1):
            number, title = read_title_block(page, engine)
            if not title:
                continue
            sheet_no = number or f"第{page_no}頁"
            sheets.setdefault(sheet_no, DrawingSheetRow(sheet_no, title[:255], page_no, is_ocr=True))
    return list(sheets.values())


def _title_block_inline(text: str) -> tuple[str, str] | None:
    number, name = _TITLE_BLOCK_NO.search(text), _TITLE_BLOCK_NAME.search(text)
    return (number.group("no"), name.group("title")) if number and name else None


def _title_block_by_position(page: pymupdf.Page) -> tuple[str, str] | None:
    lines = _lines(page)
    no_label = next((rect for rect, text in lines if _NO_LABEL.match(text)), None)
    name_label = next((rect for rect, text in lines if _NAME_LABEL.match(text)), None)
    if no_label is None or name_label is None:
        return None
    number = _nearest(no_label, [(r, t) for r, t in lines if _NO_VALUE.match(t)])
    titles = [(r, t) for r, t in lines if len(t) >= 2 and _CJK.search(t) and not _NOT_A_TITLE.search(t)]
    title = _nearest(name_label, [(r, t) for r, t in titles if _LOOKS_LIKE_TITLE.search(t)]) or _nearest(
        name_label, titles
    )
    return (number, title) if number and title else None


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


def is_related(item_name: str, sheet_title: str) -> bool:
    subject = drawing_subject(sheet_title)
    if len(subject) < 2 or subject[:2] not in item_name:
        return False
    hits = sum(1 for char in set(subject) if char in item_name)
    return hits / len(set(subject)) >= MIN_OVERLAP and hits >= 2


def related_sheets(item_name: str, sheets) -> list:
    """和工項名稱相關的圖，依圖號排序。sheets 可以是 DrawingSheetRow 或 DrawingSheet。"""
    return sorted((s for s in sheets if is_related(item_name, s.title)), key=lambda s: s.sheet_no)
