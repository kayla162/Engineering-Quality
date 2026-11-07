"""掃描的契約圖：用 OCR 讀標題欄的圖名與圖號（檢核表階段 2）。

秀山分隊的契約圖是用印後掃描的 PDF（建築 137 頁、結構 32 頁、水電 117 頁），沒有文字層。
標題欄是頁面右側的直條：「圖名 DRAWING」下面一兩行是圖名，再往下是簽名與設計事務所，
最底下「圖號 DWG NO.」右邊是圖號。實測（2026-11，三冊 286 頁，每頁約 2 秒）：

- 圖名約八成讀得到，但會混進雜字。
- 圖號原本只有約三分之一讀得到，還有讀錯的（「S2-02」讀成「S9-02」）。原因是整格連「圖號 DWG NO.」
  標籤和框線一起辨識；改成只框值那一格、先擦掉框線、用兩種解析度各讀一次，每頁得到幾個候選，
  再由整冊的圖號索引表投票決定（scanned_sheet_index）。
- 結果一律標示 OCR（DrawingSheetRow.is_ocr），圖號讀不到時用「第N頁」，不猜。

圖名只取「DRAWING」標籤正下方**連續**的幾行：中間空了一段（>15pt）或遇到事務所、電話這類
字就停——簽名就夾在那一段空白後面，這樣不必知道簽的是誰也能把它排除。
"""

import re

import numpy as np
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
#: 「DWG NO.」實際讀成「OWG NO.」「DWC. NO.」「DW NO.」「)WG_NO.」「WG NC.」「DWE NO,」
_NUMBER_LABEL = re.compile(r"[DO0Q)]?W[GCES6]?[.,]?\s*_?\s*N[O0CG]|圖\s*號")
_STOP = re.compile(r"聯合|建築師|事務所|技師|公司|電話|傳真|TEL|FAX|APRVD|CHECK|DESIGN|DRAWN", re.I)
_CJK = re.compile(r"[一-鿿]")
#: 圖號值那一格：依序用這幾種解析度讀（框線擦掉後），再讀一次含標籤的整格（舊讀法，偶爾只有它讀得到）
NUMBER_VALUE_DPIS = (400, 600)
#: 長於這個長度（吋）的直線、橫線是框線，OCR 前擦掉
LINE_MIN_INCH = 0.25

#: OCR 讀到的圖號：「S1-22」「A10-01」「00-01」（建築圖封面類沒有字母）。字母與數字常互相讀錯，
#: 所以字母段和數字段都先放寬，再在 sheet_numbers_in 裡換回來
_OCR_NUMBER = re.compile(
    r"(?<![A-Z0-9])([A-Z]{1,3})?([0-9OIL]{0,2})\s?[-—–~=]\s?([0-9OIL]{1,3})([A-Z]?)(?![0-9A-Z])"
)
#: 開頭沒有字母、卻是「5」的圖號（「50-08」）：S 被讀成 5
_S_AS_FIVE = re.compile(r"(?<![A-Z0-9])5(?=[0-9O]{0,2}\s?[-—–~])")
_DIGIT = str.maketrans("OIL", "011")


def read_title_block(page: pymupdf.Page, engine: OcrEngine) -> tuple[list[str], str]:
    """（圖號的幾種讀法，可能是空的、可能互相矛盾；圖名或空字串）。圖號由整冊一起決定。"""
    width, height = page.rect.width, page.rect.height
    strip = pymupdf.Rect(width * STRIP_FROM, 0, width, height)
    lines = _ocr_lines(page, strip, engine.dpi, engine)
    return _numbers(page, lines, engine), _title(page, strip, lines, engine)


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


def _numbers(page: pymupdf.Page, lines: list[tuple[pymupdf.Rect, str]], engine: OcrEngine) -> list[str]:
    """圖號格的幾種讀法。標籤取最下面那個（標題欄在直條底部）。

    秀山結構圖實測：連標籤一起框的舊讀法 32 頁讀對 16、讀錯 6（「S2-01」讀成「S7-01」）；只框值、
    擦掉框線後讀對的多很多、沒有讀錯。舊讀法仍留著當其中一票，偶爾只有它讀得到。
    """
    labels = [rect for rect, text in lines if _NUMBER_LABEL.search(text)]
    if not labels:
        return []
    label = max(labels, key=lambda rect: rect.y0)
    right = page.rect.width - 2
    value = pymupdf.Rect(label.x1 + 2, label.y0 - 16, right, label.y1 + 4) & page.rect
    whole = pymupdf.Rect(label.x0, label.y0 - 14, right, label.y1 + 4) & page.rect
    found = []
    if not value.is_empty:
        for dpi in NUMBER_VALUE_DPIS:
            found += _sheet_numbers(_ocr_lines(page, value, dpi, engine, language="eng", erase_lines=True))
    if not whole.is_empty:
        found += _sheet_numbers(_ocr_lines(page, whole, NUMBER_DPI, engine, language="eng"))
    return found


def _sheet_numbers(lines: list[tuple[pymupdf.Rect, str]]) -> list[str]:
    return [number for _, text in lines for number in sheet_numbers_in(text)]


def sheet_numbers_in(text: str) -> list[str]:
    """一行 OCR 文字裡所有像圖號的字，換回原本的寫法：「$2-1O」->「S2-10」、「SI-23」->「S1-23」、
    「AL0-01」「AIO-O3」->「A10-01」「A10-03」、「50-08」->「S0-08」。"""
    text = _S_AS_FIVE.sub("S", text.upper().replace("$", "S").replace("§", "S"))
    text = re.sub(r"(?<![A-Z])SS(?=\d)", "S", text)
    numbers = []
    for match in _OCR_NUMBER.finditer(text):
        letters, digits, serial, suffix = match.groups()
        letters = letters or ""
        # 字母段第一個字之後的 I、L、O 其實是數字（「AL0」是「A10」）
        while len(letters) > 1 and letters[-1] in "ILO":
            letters, digits = letters[:-1], letters[-1] + digits
        digits, serial = digits.translate(_DIGIT), serial.translate(_DIGIT)
        if len(digits) > 2 or (not letters and len(digits) != 2):
            continue
        numbers.append(f"{letters}{digits}-{serial}{suffix}")
    return numbers


def _ocr_lines(
    page: pymupdf.Page,
    clip: pymupdf.Rect,
    dpi: int,
    engine: OcrEngine,
    language: str | None = None,
    erase_lines: bool = False,
) -> list[tuple[pymupdf.Rect, str]]:
    """辨識頁面的一塊，回傳（頁面座標的框, 文字），由上而下。

    erase_lines：先把框線擦掉、四周留白。圖號格和索引表的字緊貼框線，Tesseract 會把線當成字的一部分，
    整格讀不出來（秀山結構圖 32 頁裡有 5 頁）。
    """
    pad = 0
    if erase_lines:
        pixmap, pad = _without_lines(page, clip, dpi)
    else:
        pixmap = page.get_pixmap(dpi=dpi, clip=clip)
    ocr_page = pymupdf.open(
        "pdf",
        pixmap.pdfocr_tobytes(language=language or engine.languages, tessdata=str(engine.tessdata)),
    )[0]
    # OCR 頁的座標是 pt；扣掉留白後換回頁面座標
    pad_pt = pad * 72 / dpi
    sx = clip.width / (ocr_page.rect.width - 2 * pad_pt)
    sy = clip.height / (ocr_page.rect.height - 2 * pad_pt)
    lines = []
    for block in ocr_page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                x0, y0, x1, y1 = (v - pad_pt for v in line["bbox"])
                lines.append((pymupdf.Rect(clip.x0 + x0 * sx, clip.y0 + y0 * sy, clip.x0 + x1 * sx, clip.y0 + y1 * sy), text))
    return sorted(lines, key=lambda item: (item[0].y0, item[0].x0))


def _without_lines(page: pymupdf.Page, clip: pymupdf.Rect, dpi: int, pad: int = 20) -> tuple[pymupdf.Pixmap, int]:
    """灰階算圖、擦掉長直線與長橫線、四周補白邊。回傳 RGB（Tesseract 不收灰階 pixmap，會什麼都不回）。"""
    gray = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csGRAY)
    image = np.frombuffer(gray.samples, dtype=np.uint8).reshape(gray.height, gray.stride)[:, : gray.width].copy()
    dark = image < 160
    length = max(int(dpi * LINE_MIN_INCH), 8)
    line = _long_runs(dark, length) | _long_runs(dark.T, length).T
    # 線旁邊的鋸齒一起擦
    grown = line.copy()
    grown[1:] |= line[:-1]
    grown[:-1] |= line[1:]
    grown[:, 1:] |= line[:, :-1]
    grown[:, :-1] |= line[:, 1:]
    image[grown] = 255
    image = np.pad(image, pad, constant_values=255)
    cleaned = pymupdf.Pixmap(pymupdf.csGRAY, image.shape[1], image.shape[0], image.tobytes(), False)
    cleaned.set_dpi(dpi, dpi)
    return pymupdf.Pixmap(pymupdf.csRGB, cleaned), pad


def _long_runs(dark: np.ndarray, length: int) -> np.ndarray:
    """每一列裡，屬於連續 length 個以上深色像素的位置。"""
    rows, width = dark.shape
    if width < length:
        return np.zeros_like(dark)
    total = np.zeros((rows, width + 1), dtype=np.int32)
    np.cumsum(dark, axis=1, out=total[:, 1:])
    # starts[:, i]：從 i 開始連續 length 個都是深色
    starts = (total[:, length:] - total[:, : width - length + 1]) == length
    count = starts.shape[1]
    started = np.zeros((rows, count + 1), dtype=np.int32)
    np.cumsum(starts, axis=1, out=started[:, 1:])
    # 像素 j 被覆蓋：某個起點 i 落在 [j-length+1, j]
    index = np.arange(width)
    low = np.clip(index - length + 1, 0, count)
    high = np.clip(index + 1, 0, count)
    return (started[:, high] - started[:, low]) > 0
