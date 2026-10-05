"""DOCX 解析（python-docx）。

保留段落順序、標題階層與表格內容。DOCX 沒有頁碼概念（頁碼由 Word 排版時決定），
因此 page 一律為 None，這點在報告上會誠實顯示為「未知」，不猜測。
"""

from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.parsers.base import ParsedSection, ParseResult


def _iter_blocks(document: DocxDocument):
    """依文件實際順序走訪段落與表格（python-docx 預設會把兩者分開）。"""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _is_heading(paragraph: Paragraph) -> bool:
    style = (paragraph.style.name or "") if paragraph.style else ""
    return style.startswith("Heading") or style.startswith("標題")


class DocxParser:
    def parse(self, path: Path) -> ParseResult:
        try:
            document = docx.Document(str(path))
        except Exception as exc:  # 檔案損毀、加密、其實不是 docx
            raise UnprocessableDocumentError(f"無法解析 DOCX 檔案：{exc}") from exc

        sections: list[ParsedSection] = []
        current_title: str | None = None
        order = 0

        for block in _iter_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                if _is_heading(block):
                    current_title = text
                    content_type = ContentType.HEADING
                else:
                    content_type = ContentType.PARAGRAPH
                sections.append(
                    ParsedSection(
                        content=text,
                        order_index=order,
                        content_type=content_type,
                        section_title=current_title,
                    )
                )
                order += 1
            else:  # Table：一個儲存格一筆，法規引用常常藏在表格裡
                for row in block.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if not text:
                            continue
                        sections.append(
                            ParsedSection(
                                content=text,
                                order_index=order,
                                content_type=ContentType.CELL,
                                section_title=current_title,
                            )
                        )
                        order += 1

        if not sections:
            raise UnprocessableDocumentError("DOCX 檔案裡沒有可讀取的文字內容")
        return ParseResult(sections)
