"""依副檔名挑選解析器。新增支援格式時，只要在這裡多註冊一行。"""

from pathlib import Path

from app.core.errors import InvalidFileTypeError
from app.parsers.base import DocumentParser, ParsedSection
from app.parsers.docx_parser import DocxParser
from app.parsers.excel_parser import ExcelParser
from app.parsers.pdf_parser import PdfParser
from app.parsers.txt_parser import TxtParser

_PARSERS: dict[str, DocumentParser] = {
    ".docx": DocxParser(),
    ".pdf": PdfParser(),
    ".txt": TxtParser(),
    # 標單是 Excel，而且真實檔案是 OLE2 格式的 .xls（openpyxl 讀不了）
    ".xls": ExcelParser(),
    ".xlsx": ExcelParser(),
}


def parse_document(path: Path) -> list[ParsedSection]:
    """把檔案解析成段落清單。"""
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        raise InvalidFileTypeError(f"沒有對應 {path.suffix} 的解析器")
    return parser.parse(path)


__all__ = ["DocumentParser", "ParsedSection", "parse_document"]
