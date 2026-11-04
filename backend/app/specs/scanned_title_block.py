"""掃描的契約圖：用 OCR 讀標題欄的圖名與圖號（檢核表階段 2）。

秀山分隊的契約圖是用印後掃描的 PDF（建築 137 頁、結構 32 頁、水電 117 頁），沒有文字層。
標題欄是頁面右側的直條：「圖名 DRAWING」下面一兩行是圖名，再往下是簽名與設計事務所，
最底下「圖號 DWG NO.」右邊是圖號。實測（2026-11，三冊 286 頁，每頁約 2 秒）：

- 圖名約八成讀得到，但會混進雜字；圖號只有約三分之一讀得到（「A12-07」常讀成「TAI2-07」）。
- 所以結果一律標示 OCR（DrawingSheetRow.is_ocr），圖號讀不到時用「第N頁」，不猜。

圖名只取「DRAWING」標籤正下方**連續**的幾行：中間空了一段（>15pt）或遇到事務所、電話這類
字就停——簽名就夾在那一段空白後面，這樣不必知道簽的是誰也能把它排除。
"""

import re

import pymupdf

from app.parsers.ocr import OcrEngine

#: 標題欄直條：頁寬右側這個比例以內（秀山三冊都是 0.885 以右）
STRIP_FROM = 0.885
#: 圖名最多往下讀這麼遠（pt），行與行之間空超過 ROW_GAP 就停
TITLE_SPAN = 45
ROW_GAP = 15
NUMBER_DPI = 600
TITLE_DPI = 400
#: 簽名在事務所那一行上方這個距離以內（pt）
SIGNATURE_ABOVE = 30

_DRAWING_LABEL = re.compile(r"DRAWING|圖\s*名")
_NUMBER_LABEL = re.compile(r"DWG|圖\s*號")
_STOP = re.compile(r"聯合|建築師|事務所|技師|公司|電話|傳真|TEL|FAX|APRVD|CHECK|DESIGN|DRAWN", re.I)
_CJK = re.compile(r"[一-鿿]")
_NUMBER = re.compile(r"([A-Z]{1,3}\d{0,2})\s?[-—–~]\s?(\d{1,3}[A-Z]?(?:-\d{1,2})?)")


def read_title_block(page: pymupdf.Page, engine: OcrEngine) -> tuple[str | None, str]:
    """（圖號或 None, 圖名或空字串）。"""
    width, height = page.rect.width, page.rect.height
    strip = pymupdf.Rect(width * STRIP_FROM, 0, width, height)
    lines = _ocr_lines(page, strip, engine.dpi, engine)
    return _number(page, lines, engine), _title(page, strip, lines, engine)


def _title(
    page: pymupdf.Page, strip: pymupdf.Rect, lines: list[tuple[pymupdf.Rect, str]], engine: OcrEngine
) -> str:
    label = next((rect for rect, text in lines if _DRAWING_LABEL.search(text)), None)
    if label is None:
        return ""
    # 整條辨識常漏掉短短一行圖名；標籤下面那一塊單獨放大再讀
    area = pymupdf.Rect(strip.x0, label.y1 + 1, strip.x1, label.y1 + TITLE_SPAN + 10)
    found = [(r, t) for r, t in _ocr_lines(page, area, TITLE_DPI, engine) if not _DRAWING_LABEL.search(t)]
    kept: list[tuple[pymupdf.Rect, str]] = []
    for rect, text in sorted(found, key=lambda item: _middle(item[0])):
        if _STOP.search(text):
            break
        if kept and rect.y0 - max(r.y1 for r, _ in kept) > ROW_GAP:
            break  # 空了一段：後面是簽名
        kept.append((rect, text))
    # 依行由上而下、行內由左而右。同一行的框高矮不一，用「和這一行垂直重疊」判斷，不用中線取整
    rows: list[list[tuple[pymupdf.Rect, str]]] = []
    for rect, text in kept:
        if rows and rect.y0 < max(r.y1 for r, _ in rows[-1]) - rect.height * 0.3:
            rows[-1].append((rect, text))
        else:
            rows.append([(rect, text)])
    ordered = [item for row in rows for item in sorted(row, key=lambda item: item[0].x0)]
    title = re.sub(r"\s+", "", "".join(text for _, text in ordered if _CJK.search(text)))
    # 讀錯的英文標籤（「URAWING」）黏在圖名前面；圖名本身的英文代號（PVC、LED、AC）都在三個字母以內
    title = re.sub(r"[A-Za-z]{4,}", "", title)
    for gram in _signature_grams(lines):
        title = title.replace(gram, "")
    return title.strip(",，、=|/")


def _signature_grams(lines: list[tuple[pymupdf.Rect, str]]) -> set[str]:
    """事務所那一行與它上方 30pt 內各行的三字串。簽名離圖名太近時會被讀進圖名，
    而同一頁的事務所名稱、簽名欄裡一定也有這個名字——不必知道是誰就能拿掉。"""
    firm = next((rect for rect, text in lines if _STOP.search(text) and _CJK.search(text)), None)
    if firm is None:
        return set()
    grams = set()
    for rect, text in lines:
        if firm.y0 - SIGNATURE_ABOVE <= rect.y0 <= firm.y1:
            chars = "".join(_CJK.findall(text))
            grams |= {chars[i:i + 3] for i in range(len(chars) - 2)}
    return grams


def _middle(rect: pymupdf.Rect) -> float:
    return (rect.y0 + rect.y1) / 2


def _number(page: pymupdf.Page, lines: list[tuple[pymupdf.Rect, str]], engine: OcrEngine) -> str | None:
    label = next((rect for rect, text in lines if _NUMBER_LABEL.search(text)), None)
    if label is None:
        return None
    # 圖號字小、又擠在框線旁，整條辨識常漏掉；只框標籤右邊那一格，放大再讀一次
    cell = pymupdf.Rect(label.x0, label.y0 - 14, page.rect.width - 2, label.y1 + 4)
    for _, text in _ocr_lines(page, cell, NUMBER_DPI, engine, language="eng"):
        # 「S」常被讀成「$」「§」
        match = _NUMBER.search(text.upper().replace("$", "S").replace("§", "S"))
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return None


def _ocr_lines(
    page: pymupdf.Page, clip: pymupdf.Rect, dpi: int, engine: OcrEngine, language: str | None = None
) -> list[tuple[pymupdf.Rect, str]]:
    """辨識頁面的一塊，回傳（頁面座標的框, 文字），由上而下。"""
    pixmap = page.get_pixmap(dpi=dpi, clip=clip)
    ocr_page = pymupdf.open(
        "pdf",
        pixmap.pdfocr_tobytes(language=language or engine.languages, tessdata=str(engine.tessdata)),
    )[0]
    sx, sy = clip.width / ocr_page.rect.width, clip.height / ocr_page.rect.height
    lines = []
    for block in ocr_page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                x0, y0, x1, y1 = line["bbox"]
                lines.append((pymupdf.Rect(clip.x0 + x0 * sx, clip.y0 + y0 * sy, clip.x0 + x1 * sx, clip.y0 + y1 * sy), text))
    return sorted(lines, key=lambda item: (item[0].y0, item[0].x0))
