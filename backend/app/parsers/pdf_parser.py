"""PDF 解析（PyMuPDF）。可取得頁碼，因此每個段落都會帶 page。

MVP 只支援「文字可選取」的 PDF。掃描版 PDF 需要 OCR，屬於後續 Phase 的待辦，
這裡的做法是：解析不到任何文字就明確報錯，不會安靜地產出空清單。

但「抽得到字」不等於「抽得到內容」——設計圖說有圖號和標題欄，卻把尺寸標註
壓在點陣圖裡。那種文件會通過上面那道關，然後回傳一份近乎空白的結果。所以同一輪
迴圈裡順手統計每頁的文字量與有無圖片，交給 text_coverage 判斷（見該模組說明）。
"""

from pathlib import Path

import pymupdf

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.parsers.base import ParsedSection, ParseResult
from app.parsers.text_coverage import measure_pages


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
        #: 每頁的（文字長度, 有沒有圖片），餵給 measure_pages
        page_stats: list[tuple[int, bool]] = []
        order = 0
        try:
            for page_index, page in enumerate(document, start=1):
                page_chars = 0
                for block in page.get_text("blocks"):
                    # block = (x0, y0, x1, y1, text, block_no, block_type)
                    text = (block[4] or "").strip()
                    if not text:
                        continue
                    page_chars += len(text)
                    sections.append(
                        ParsedSection(
                            content=" ".join(text.split()),
                            order_index=order,
                            content_type=ContentType.PARAGRAPH,
                            page=page_index,
                        )
                    )
                    order += 1
                page_stats.append((page_chars, bool(page.get_images())))
        finally:
            document.close()

        if not sections:
            raise UnprocessableDocumentError(
                "PDF 檔案中找不到可選取的文字，可能是掃描檔（本版本尚不支援 OCR）"
            )
        return ParseResult(sections, measure_pages(page_stats))
