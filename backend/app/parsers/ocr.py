"""掃描版 PDF 的 OCR（PyMuPDF 內建的 Tesseract 介面）。

PyMuPDF 自己帶了 Tesseract 引擎，不需要另外裝 `tesseract` 執行檔或 Python 套件，
只需要語言資料檔（`chi_tra.traineddata` 等）。找不到語言資料時，這裡回報「為什麼
不能用」，讓呼叫端把原因寫進錯誤訊息——不要讓人以為系統讀過那幾頁。

OCR 的結果一定會被標記（`ParsedSection.is_ocr`），因為辨識錯字是常態：
「施工規範」被讀成「施丄規範」，比對引擎就會給出一個看起來合理的 NOT_FOUND。
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class OcrEngine:
    """已確認可用的 OCR 設定。"""

    tessdata: Path
    languages: str
    dpi: int

    def page_blocks(self, page: pymupdf.Page) -> list[str]:
        """辨識一頁，回傳每個文字區塊的內容。

        `full=False`：原本就可選取的文字照用，只辨識圖片區域——圖號、標題欄這些
        向量文字不必冒著讀錯的風險重新辨識一次。
        """
        textpage = page.get_textpage_ocr(
            language=self.languages, dpi=self.dpi, full=False, tessdata=str(self.tessdata)
        )
        return [block[4] for block in page.get_text("blocks", textpage=textpage)]


def load_engine() -> tuple[OcrEngine | None, str | None]:
    """回傳（引擎, None），或（None, 不能用的原因）。

    每次解析呼叫一次，不快取：使用者裝好語言資料後重新分析就會生效，不必重啟服務。
    """
    if not settings.ENABLE_OCR:
        return None, "OCR 已關閉（ENABLE_OCR=false）"

    tessdata = _find_tessdata()
    if tessdata is None:
        return None, "找不到 Tesseract 語言資料，請安裝 Tesseract 或設定 TESSDATA_PATH"

    languages = [lang for lang in settings.OCR_LANGUAGES.split("+") if lang]
    missing = [lang for lang in languages if not (tessdata / f"{lang}.traineddata").is_file()]
    if missing:
        return None, f"Tesseract 語言資料缺少 {', '.join(missing)}（目錄：{tessdata}）"

    return OcrEngine(tessdata=tessdata, languages="+".join(languages), dpi=settings.OCR_DPI), None


def _find_tessdata() -> Path | None:
    """`TESSDATA_PATH` 優先；否則交給 PyMuPDF 找（TESSDATA_PREFIX 環境變數或系統安裝）。"""
    if settings.TESSDATA_PATH:
        path = Path(settings.TESSDATA_PATH)
        return path if path.is_dir() else None
    try:
        found = pymupdf.get_tessdata()
    except Exception:
        return None
    return Path(found) if found else None
