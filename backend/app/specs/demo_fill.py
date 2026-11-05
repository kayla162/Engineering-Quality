"""示範補正：把橘框表單與計畫初稿裡的「（待填）」用示範內容補齊，給展示用。

初稿刻意不編系統不知道的東西（檢查頻率、施工機具、範本只列項目的判定值、組織與程序章節），所以留「（待填）」。
展示時需要一份看起來完整的文件，就用 data/demo_fill.json 的示範內容補上：

- 補上的值一律標「（示範）」，計畫章節的段落以「【示範】」開頭——看得出哪些是補的。
- 不改原本的初稿物件（回傳新的），不補的版本完全不變。
- 示範內容不寫任何真實人名，組織只寫職稱。
"""

import json
from dataclasses import replace
from functools import cache

from app.core.config import settings
from app.specs.function_test import LISTED_ONLY, FunctionTestDraft
from app.specs.method_statement import MethodStatement
from app.specs.quality_standard import QualityStandardDraft

BLANK = "（待填）"
MARK = "（示範）"
NOTICE = "示範補正：「（示範）」標記的值與「【示範】」段落是展示用的示範內容，不是本案實際資料，不可提送。"


@cache
def _data() -> dict:
    with open(settings.DATA_DIR / "demo_fill.json", encoding="utf-8") as file:
        return json.load(file)


def fill_standard(draft: QualityStandardDraft) -> QualityStandardDraft:
    by_stage = _data()["frequency_by_stage"]
    rows = [
        replace(row, frequency=by_stage.get(row.stage, by_stage["施工中"]) + MARK) if row.frequency == BLANK else row
        for row in draft.rows
    ]
    return replace(draft, rows=rows, notice=f"{NOTICE}{draft.notice}")


def fill_function_test(draft: FunctionTestDraft) -> FunctionTestDraft:
    data = _data()
    values = data["function_test_values"]
    rows = []
    for row in draft.rows:
        if row.standard == LISTED_ONLY:
            key = next((k for k in values if k != "default" and k in row.item), "default")
            row = replace(row, standard=values[key] + MARK)
        if row.frequency == BLANK:
            row = replace(row, frequency=data["function_test_frequency"] + MARK)
        rows.append(row)
    return replace(draft, rows=rows, notice=f"{NOTICE}{draft.notice}")


def fill_method(statement: MethodStatement) -> MethodStatement:
    data = _data()
    tools = next((t for keyword, t in data["tools_by_keyword"] if keyword in statement.chapter_title), data["default_tools"])
    return replace(
        statement,
        tools=tools + MARK if statement.tools == BLANK else statement.tools,
        materials=statement.materials or [f"依標單與設計圖說{MARK}"],
        notice=f"{NOTICE}{statement.notice}",
    )


def plan_sections(kind: str) -> dict[str, list[str]]:
    """計畫裡系統產生不了的章節（kind: quality / supervision），每段以「【示範】」開頭。"""
    sections = _data()[f"{kind}_plan_sections"]
    return {heading: [f"【示範】{text}" for text in paragraphs] for heading, paragraphs in sections.items()}
