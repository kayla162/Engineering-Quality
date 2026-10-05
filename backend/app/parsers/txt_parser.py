"""TXT 解析：以空行切段落。"""

from pathlib import Path

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.parsers.base import ParsedSection, ParseResult

# 工程文件常見的中文編碼，依序嘗試
_ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5")


class TxtParser:
    def parse(self, path: Path) -> ParseResult:
        raw = path.read_bytes()
        text = None
        for encoding in _ENCODINGS:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise UnprocessableDocumentError("無法判斷文字檔編碼（已嘗試 UTF-8 / CP950 / Big5）")

        sections = [
            ParsedSection(
                content=" ".join(line.split()),
                order_index=index,
                content_type=ContentType.PARAGRAPH,
            )
            for index, line in enumerate(
                [line for line in text.splitlines() if line.strip()]
            )
        ]
        if not sections:
            raise UnprocessableDocumentError("文字檔是空的")
        return ParseResult(sections)
