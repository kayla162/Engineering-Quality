"""文件解析器的共同介面與輸出格式。

每個解析器把一份檔案轉成一串 ParsedSection，之後由 DocumentService
原封不動寫進 document_sections 表。解析器本身不碰資料庫。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.enums import ContentType


@dataclass(slots=True)
class ParsedSection:
    """文件裡的一個段落 / 標題 / 表格儲存格。"""

    content: str
    order_index: int
    content_type: ContentType = ContentType.PARAGRAPH
    page: int | None = None
    section_title: str | None = None


class DocumentParser(Protocol):
    """所有解析器都符合這個介面，新增格式時只要多寫一個模組。"""

    def parse(self, path: Path) -> list[ParsedSection]: ...
