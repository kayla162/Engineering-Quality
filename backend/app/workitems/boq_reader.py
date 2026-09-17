"""標單（詳細價目表）讀取。

真實標單的形狀（新北市消防局秀山分隊，2026-09 查證）：
    工作表「契約詳細表」，表頭在第 6 列
    項 次 | 項  目  及  說  明 | 單 位 | 數 量 | 單 價 | 複 價 | 編碼(備註)
    壹.一.1.1.1 | 施工測量，基地測量及鑑界費 | 式 | 1 | 100000 | 100000 | 0172500004,*

兩個關鍵設計：

1. **表頭用文字定位，不寫死列號。** 各家標單前面的標題列數不一樣，寫死會全錯。
   找不到表頭就明確報錯，不要產出空清單——那會讓人以為標單裡沒有工項。

2. **說明會跨列續寫，而且從詞中間斷開。** 續寫列只有說明欄有字，項次是空的；
   接起來時中間不能插分隔符號，否則名稱還是斷的。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import UnprocessableDocumentError
from app.parsers.workbook import read_workbook

#: 表頭必須同時出現這兩欄才算數（比對前會去掉所有空白）
_REQUIRED_HEADERS = ("項次", "項目及說明")

#: 表頭文字 -> 我們的欄位名。key 是去掉空白後的形式。
_COLUMN_KEYS: dict[str, str] = {
    "項次": "item_no",
    "項目及說明": "name",
    "單位": "unit",
    "數量": "quantity",
    "編碼(備註)": "cost_code",
    "編碼": "cost_code",
}

#: 計價代碼是 10 碼數字，後面可能跟著「,*」之類的記號
_COST_CODE = re.compile(r"(?<!\d)(\d{10})(?!\d)")


class BoqFormatError(UnprocessableDocumentError):
    """標單格式不符預期。"""


@dataclass(slots=True)
class BoqRow:
    item_no: str
    name: str
    unit: str = ""
    quantity: str = ""
    cost_code: str | None = None

    @property
    def is_leaf(self) -> bool:
        """有單位的才是實際工項；「壹」「壹.一」這種是群組列。"""
        return bool(self.unit)


def _normalise(text: str) -> str:
    """去掉所有空白（含全形），表頭才比對得到。"""
    return re.sub(r"\s+", "", text.replace("　", ""))


def _find_header(rows) -> tuple[str, int, dict[str, int]]:
    """回傳 (工作表名, 表頭列號, {欄位名: 欄索引})。"""
    for row in rows:
        normalised = [_normalise(cell) for cell in row.cells]
        if not all(any(key == cell for cell in normalised) for key in _REQUIRED_HEADERS):
            continue
        columns: dict[str, int] = {}
        for index, cell in enumerate(normalised):
            field = _COLUMN_KEYS.get(cell)
            if field is not None and field not in columns:
                columns[field] = index
        return row.sheet, row.index, columns
    raise BoqFormatError(
        "在標單裡找不到表頭（需要同時有「項次」與「項目及說明」兩欄）。"
        "請確認上傳的是詳細價目表，不是總表或單價分析表"
    )


def _cell(cells: list[str], columns: dict[str, int], field: str) -> str:
    index = columns.get(field)
    if index is None or index >= len(cells):
        return ""
    return cells[index]


def read_boq(path: Path) -> list[BoqRow]:
    rows = read_workbook(path)
    sheet, header_index, columns = _find_header(rows)

    items: list[BoqRow] = []
    for row in rows:
        if row.sheet != sheet or row.index <= header_index:
            continue

        item_no = _cell(row.cells, columns, "item_no")
        name = _cell(row.cells, columns, "name")
        if not item_no and not name:
            continue

        if not item_no:
            # 續寫列：只有說明欄有字。從詞中間斷開的，中間不能插分隔符號。
            if items:
                items[-1].name += name
            continue

        raw_code = _cell(row.cells, columns, "cost_code")
        match = _COST_CODE.search(raw_code)
        items.append(
            BoqRow(
                item_no=item_no,
                name=name,
                unit=_cell(row.cells, columns, "unit"),
                quantity=_cell(row.cells, columns, "quantity"),
                cost_code=match.group(1) if match else None,
            )
        )
    return items
