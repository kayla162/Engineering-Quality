"""契約圖的圖號索引，以及工項對到哪幾張圖（檢核表階段 2、4）。

圖面內容系統讀不懂（尺寸、線條），能可靠讀到的只有**文字**：每張圖標題欄的
「圖號：S-12」「圖名：模板組立詳圖」，或圖說目錄頁一行一張的「S-12 模板組立詳圖」。
所以這裡只做兩件事：列出有哪些圖，以及用圖名找出和工項相關的圖號——給人去翻圖，
不替人判斷圖上畫了什麼（spec 第 7 節）。

**以示範資料驗證，尚未用真實契約圖驗證。** spec 第 8 節把「契約圖多半是掃描或 CAD 匯出的
PDF，可能抽不到文字」列為風險：真實圖面若是掃描檔，要先經過 OCR（parsers/ocr.py）
才讀得到標題欄。

圖名比對刻意保守：對錯圖號比沒有圖號更糟（spec 第 8 節）。只比圖名去掉「詳圖」
「平面圖」這類圖種字尾之後的主體，兩個條件都要成立才算相關：

- 主體開頭兩個字（通常是主要名詞：模板、鋼筋、屋頂）出現在工項名稱裡；
- 主體的字有一半以上出現在工項名稱裡。

只看第二條的話，「鋼筋，含加工及組立」會因為「組立」兩字對到「模板組立詳圖」。
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

#: 標題欄：「圖號：S-12」「圖名：模板組立詳圖」
_TITLE_BLOCK_NO = re.compile(r"圖\s*號\s*[:：]\s*(?P<no>[A-Z]{1,3}-?\d{1,3}[A-Z]?)")
_TITLE_BLOCK_NAME = re.compile(r"圖\s*名\s*[:：]\s*(?P<title>[^\s:：]{2,40})")
#: 圖說目錄：一行「S-12 模板組立詳圖」
_INDEX_LINE = re.compile(r"^\s*(?P<no>[A-Z]{1,3}-\d{1,3}[A-Z]?)\s+(?P<title>[^\s]{2,40})\s*$", re.MULTILINE)

#: 圖種字尾：比對時去掉，只留下「畫的是什麼」
_DRAWING_KIND = re.compile(r"(?:詳圖|大樣圖|平面圖|立面圖|剖面圖|配置圖|系統圖|示意圖|圖說|圖)$")
#: 圖名主體的字至少要有這個比例出現在工項名稱裡
MIN_OVERLAP = 0.5


@dataclass(frozen=True)
class DrawingSheetRow:
    sheet_no: str
    title: str
    page: int


def read_drawing_sheets(path: Path) -> list[DrawingSheetRow]:
    """讀出契約圖裡的每一張圖。標題欄優先；整份都沒有標題欄時改讀圖說目錄。"""
    with pymupdf.open(str(path)) as document:
        pages = [(index, page.get_text()) for index, page in enumerate(document, start=1)]

    sheets: dict[str, DrawingSheetRow] = {}
    for page_no, text in pages:
        number, name = _TITLE_BLOCK_NO.search(text), _TITLE_BLOCK_NAME.search(text)
        if number and name:
            sheets.setdefault(number.group("no"), DrawingSheetRow(number.group("no"), name.group("title"), page_no))
    if sheets:
        return list(sheets.values())

    for page_no, text in pages:
        for match in _INDEX_LINE.finditer(text):
            sheets.setdefault(match.group("no"), DrawingSheetRow(match.group("no"), match.group("title"), page_no))
    return list(sheets.values())


def drawing_subject(title: str) -> str:
    """「模板組立詳圖」->「模板組立」。"""
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
