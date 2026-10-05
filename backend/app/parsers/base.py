"""文件解析器的共同介面與輸出格式。

每個解析器把一份檔案轉成一個 ParseResult：一串 ParsedSection，之後由
DocumentService 原封不動寫進 document_sections 表；外加文件層級的品質訊號。
解析器本身不碰資料庫。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.enums import ContentType
from app.parsers.text_coverage import TextCoverage


@dataclass(slots=True)
class ParsedSection:
    """文件裡的一個段落 / 標題 / 表格儲存格。"""

    content: str
    order_index: int
    content_type: ContentType = ContentType.PARAGRAPH
    page: int | None = None
    section_title: str | None = None


@dataclass(slots=True)
class ParseResult:
    """一次解析的產出：段落，加上文件層級的品質訊號。

    `coverage` 只有 PDF 會有。其他格式沒有「頁」的概念，也沒有「內容被壓在
    圖裡抽不出來」這個失效模式，所以是 None。
    """

    sections: list[ParsedSection]
    coverage: TextCoverage | None = None


class DocumentParser(Protocol):
    """所有解析器都符合這個介面，新增格式時只要多寫一個模組。"""

    def parse(self, path: Path) -> ParseResult: ...
