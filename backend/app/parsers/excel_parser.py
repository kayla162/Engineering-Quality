"""Excel 解析（文字化輸出，給法規抽取用）。

為什麼需要這個：工程標單是 Excel，而且真實檔案是 **OLE2 格式的 .xls**——
不是 .xlsx，openpyxl 讀不了。

**一列一個 section，不是一格一個。** DOCX 的表格是一格一段，Excel 照抄的話
真實標單（2669 列 x 7 欄）會產生近兩萬個 section，而且把「壹.一.1.1.1」跟
「施工測量，基地測量及鑑界費」拆散。法規抽取跑在完整的列上準得多。

**邊界：這裡不認得標單的結構。** 項次、計價代碼、哪張工作表是詳細表——那些是
`app/workitems/boq_reader.py` 的職責，它走同一個 `parsers/workbook.py` 讀同一份檔，
但要的是保留欄位位置的結構化資料。
"""

from pathlib import Path

from app.core.enums import ContentType
from app.core.errors import UnprocessableDocumentError
from app.parsers.base import ParsedSection, ParseResult
from app.parsers.workbook import read_workbook

#: 同一列的儲存格用這個串起來。用非中文字元，抽取時才不會把兩格黏成一個法規名稱。
_CELL_SEPARATOR = " | "


def _filled(cells: list[str]) -> list[tuple[int, str]]:
    """回傳 [(欄索引, 文字)]，只留有內容的格子。"""
    return [(index, text) for index, text in enumerate(cells) if text]


def _is_continuation(current: list[tuple[int, str]], previous: list[tuple[int, str]]) -> bool:
    """這一列是不是前一列的換行續寫？

    標單的長說明會跨列續寫，而且是**從詞中間斷開**的（真實資料）：
        列18  項次=''  「新北市建築物施工中管制要點及新北市建」
        列19  項次=''  「築工程施工圍籬綠美化推動實施計畫規定」

    各自成段的話，「新北市建築工程施工圍籬綠美化推動實施計畫」會被切成兩半，
    抽取器就吐出「市建築物施工中管制要點」「勞安標準」這種半截詞。

    判準刻意不綁標單格式（這裡不該認得「項次」欄是什麼）：
    **只有一欄有內容，而且和前一列是同一欄**——那就是換行造成的，不是新的一筆。
    """
    return (
        len(current) == 1
        and len(previous) >= 1
        and current[0][0] in {column for column, _ in previous}
    )


class ExcelParser:
    def parse(self, path: Path) -> ParseResult:
        sections: list[ParsedSection] = []
        previous_sheet: str | None = None
        previous_cells: list[tuple[int, str]] = []

        for row in read_workbook(path):
            filled = _filled(row.cells)
            if not filled:
                continue

            same_sheet = row.sheet == previous_sheet
            if sections and same_sheet and _is_continuation(filled, previous_cells):
                # 從詞中間斷開的，中間不能插分隔符號，否則名稱還是斷的
                sections[-1].content += filled[0][1]
            else:
                sections.append(
                    ParsedSection(
                        content=_CELL_SEPARATOR.join(text for _, text in filled),
                        order_index=len(sections),
                        content_type=ContentType.TABLE,
                        # 試算表沒有頁碼，跟 DOCX 一樣留 None，不要編一個出來
                        page=None,
                        section_title=row.sheet,
                    )
                )
                previous_cells = filled
            previous_sheet = row.sheet

        if not sections:
            raise UnprocessableDocumentError("試算表裡沒有任何內容")
        return ParseResult(sections)
