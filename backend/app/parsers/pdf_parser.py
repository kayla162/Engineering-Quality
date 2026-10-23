"""PDF 解析（PyMuPDF）。可取得頁碼，因此每個段落都會帶 page。

可選取文字不足（少於 text_coverage.MIN_PAGE_CHARS）又有圖片的頁，會送 OCR
（見 ocr.py）。掃描檔每一頁都是這樣；設計圖說的圖頁也是，OCR 至少能讀回一部分
圖內文字。OCR 讀出來的段落一律標記 `is_ocr`，讓畫面告訴人要對照原檔。

OCR 不能用（沒裝語言資料、或被關掉）時不會安靜地跳過：整份沒有文字就報錯，
錯誤訊息帶原因；只有部分頁讀不到，就照常解析，原因寫進解析品質說明。

「抽得到字」不等於「抽得到內容」——設計圖說有圖號和標題欄，卻把尺寸標註
壓在點陣圖裡。所以同一輪迴圈裡順手統計每頁的文字量、有無圖片、有沒有用 OCR，
交給 text_coverage 判斷（見該模組說明）。
"""

import logging
from pathlib import Path

import pymupdf

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.core.logging import log_context
from app.parsers import ocr
from app.parsers.base import ParsedSection, ParseResult
from app.parsers.text_coverage import MIN_PAGE_CHARS, measure_pages

logger = logging.getLogger(__name__)


class PdfParser:
    def parse(self, path: Path) -> ParseResult:
        try:
            document = pymupdf.open(str(path))
        except Exception as exc:
            raise UnprocessableDocumentError(f"無法開啟 PDF 檔案：{exc}") from exc

        if document.needs_pass:
            document.close()
            raise UnprocessableDocumentError("PDF 檔案已加密，無法解析")

        sections: list[ParsedSection] = []
        #: 每頁的（文字長度, 有沒有圖片, 有沒有用 OCR），餵給 measure_pages
        page_stats: list[tuple[int, bool, bool]] = []
        #: 第一次碰到需要 OCR 的頁才載入，純文字 PDF 不必去找語言資料
        engine: ocr.OcrEngine | None = None
        ocr_unavailable: str | None = None
        try:
            for page_index, page in enumerate(document, start=1):
                texts = _clean(block[4] for block in page.get_text("blocks"))
                has_image = bool(page.get_images())
                used_ocr = False

                if sum(map(len, texts)) < MIN_PAGE_CHARS and has_image:
                    if engine is None and ocr_unavailable is None:
                        engine, ocr_unavailable = ocr.load_engine()
                    if engine is not None:
                        ocr_texts = _ocr_page(engine, page, path, page_index)
                        # 辨識結果比原本的字多才採用；圖號這種向量文字已經包含在內
                        if sum(map(len, ocr_texts)) > sum(map(len, texts)):
                            texts, used_ocr = ocr_texts, True

                for text in texts:
                    sections.append(
                        ParsedSection(
                            content=text,
                            order_index=len(sections),
                            content_type=ContentType.PARAGRAPH,
                            page=page_index,
                            is_ocr=used_ocr,
                        )
                    )
                page_stats.append((sum(map(len, texts)), has_image, used_ocr))
        finally:
            document.close()

        if not sections:
            if ocr_unavailable:
                raise UnprocessableDocumentError(
                    f"PDF 檔案中找不到可選取的文字，可能是掃描檔，且無法進行 OCR：{ocr_unavailable}"
                )
            raise UnprocessableDocumentError("PDF 檔案中找不到文字（已嘗試 OCR）")
        return ParseResult(sections, measure_pages(page_stats, ocr_unavailable))


def _clean(raw_texts) -> list[str]:
    """去掉空區塊，並把區塊內的換行與連續空白壓成一個空白。"""
    return [" ".join(text.split()) for text in raw_texts if text and text.strip()]


def _ocr_page(engine: ocr.OcrEngine, page: pymupdf.Page, path: Path, page_index: int) -> list[str]:
    """辨識一頁。單頁失敗只記 log、當作沒辨識，不讓整份文件失敗。"""
    try:
        return _clean(engine.page_blocks(page))
    except Exception as exc:
        logger.warning(
            "OCR 辨識失敗",
            extra=log_context(file=path.name, page=page_index, error=str(exc)),
        )
        return []
