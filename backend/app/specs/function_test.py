"""設備功能運轉檢測標準表（承攬廠商）與設備功能運轉測試抽驗標準表（監造）初稿。

邏輯圖兩個橘框都標了「※設備功能運轉檢測程序及標準，通常很制式，只是工程內有的工程要有」。
秀山整體品質計畫第六章的表：

    工程項目｜管理項目｜管理標準｜檢查時機｜檢查方法｜檢查頻率｜不合標準之處置方法｜管理紀錄｜備註

來源是機電章（11／13／14／15／16 開頭）「3. 施工」裡標題是測試、試驗、試運轉、試車、檢驗的小節
（含它底下的小節）。秀山規範 35 個機電章，例如 13851「3.2 現場試驗 3.2.1 絕緣試驗 3.2.2 動作試驗」、
16061「3.5 現場測試」。檢查方法、頻率、處置依關鍵字給預設值，句子沒寫頻率的留「（待填）」。
"""

import io
import json
import re
from dataclasses import dataclass, field
from functools import cache

from app.specs.quality_standard import (
    _FREQUENCY,
    _NOT_A_TITLE,
    _PAGE_HEADER,
    _PART,
    _SUBSECTION,
    _clean,
    _is_table,
    _sentences,
    _subsection_at,
)

NOTICE = "AI 初稿：取自本案施工規範機電章的測試、試驗小節，判定值與頻率須由品管（監造）人員依設計圖說補正。"
#: 機電章的章碼開頭：11 設備、13 特殊構造（消防）、14 輸送系統、15 機械、16 電機
EQUIPMENT_DIVISIONS = ("11", "13", "14", "15", "16")
_TEST_TITLE = re.compile(r"測試|試驗|試運轉|試車|檢驗")
_INSTRUMENT = re.compile(r"量測|測定|測量|電阻|電壓|電流|照度|壓力|噪音|風量|許可差|±|mm|MΩ|Ω|V|kgf|Hz")
_TEST_WORD = re.compile(r"試驗|測試|檢查|檢驗")
#: 綱要規範範本沒填的空格「[ ]」與待選的「[訓練]」
_BLANK = re.compile(r"\[\s*\]")
_BRACKETED = re.compile(r"\[([^\[\]]{1,80})\]")
LISTED_ONLY = "（規範只列項目，判定值待填）"
_OPERATE = re.compile(r"動作|操作|啟動|運轉|顯示|切換|連動")

COLUMNS = ("工程項目", "管理項目", "管理標準", "檢查時機", "檢查方法", "檢查頻率", "不合標準之處置方法", "管理紀錄", "備註")
SUPERVISION_COLUMNS = ("工程項目", "抽驗項目", "抽驗標準", "抽驗時機", "抽驗方法", "抽驗頻率", "不合標準之處置方法", "抽驗紀錄", "備註")


@dataclass(frozen=True)
class FunctionTestRow:
    equipment: str
    item: str
    standard: str
    timing: str
    method: str
    frequency: str
    handling: str
    record: str
    note: str


@dataclass(frozen=True)
class FunctionTestDraft:
    chapter_code: str
    chapter_title: str
    rows: list[FunctionTestRow] = field(default_factory=list)
    notice: str = NOTICE

    @property
    def title(self) -> str:
        return f"{self.chapter_title}功能運轉檢測標準表（初稿）"

    @property
    def supervision_title(self) -> str:
        return f"{self.chapter_title}功能運轉測試抽驗標準表（初稿）"


def is_equipment_chapter(chapter_code: str) -> bool:
    return chapter_code[:2] in EQUIPMENT_DIVISIONS


def draft_function_test(chapter_code: str, chapter_title: str, chapter_text: str) -> FunctionTestDraft:
    text = _PAGE_HEADER.sub(" ", chapter_text)
    start = next((m.end() for m in _PART.finditer(text) if m.group(1) == "3"), None)
    if start is None:
        return FunctionTestDraft(chapter_code, chapter_title)
    end = next((m.start() for m in _PART.finditer(text) if m.group(1) == "4"), len(text))
    body = _BRACKETED.sub(r"\1", _BLANK.sub(" ", text[start:end]))
    subsections = [(m.start(), m.group(1), m.group(2)) for m in _SUBSECTION.finditer(body)]
    # 只認真的標題：「在適當地方加裝接地測試裝」是句子開頭，含「測試」也不算測試小節
    # 同一個編號只認第一次（「3.3m 以上之水壓」不是 3.3 節）；「現場試驗：系統完成後應做…」標題取冒號前
    titles: dict[str, str] = {}
    for _, number, raw in subsections:
        title = re.split(r"[：:]", raw)[0].strip()
        if 2 <= len(title) < 12 and not _NOT_A_TITLE.search(title) and not title.endswith("。"):
            titles.setdefault(number, title)

    rows = []
    for sentence, position in _sentences(body):
        number, item = _subsection_at(subsections, position)
        if number is None or not _under_test_section(number, titles) or _is_table(sentence):
            continue
        item = titles.get(number) or item
        if _bare(sentence) == item:
            continue  # 「綜合檢查 3.2.5。」只是標題，留給下面「只列項目」處理
        frequency = _FREQUENCY.search(sentence.replace("[", "").replace("]", ""))
        each = re.search(r"每[一個組台具間處座迴回路]{1,4}", sentence)
        rows.append(
            FunctionTestRow(
                equipment=chapter_title,
                item=(item or chapter_title).rstrip("：:"),
                standard=_clean(sentence),
                timing="測試時",
                method=_method(sentence),
                frequency=re.sub(r"\s+", "", frequency.group(0)) if frequency else (each.group(0) if each else "（待填）"),
                handling="檢修調整或更換",
                record="測試報告" if re.search(r"試驗|測試|報告", sentence + item) else "檢測紀錄",
                note=f"第{chapter_code}章 {number}",
            )
        )
    # 句子切不出來的測試小節：範本只列了項目（「3.2.1 絕緣試驗」）就照列、判定值待填；
    # 條文沒有句號（「3.4 檢驗 3.4.1 依據契約及…」）就整段當管理標準
    covered = {row.note for row in rows}
    seen: set[str] = set()
    for index, (position, number, _raw) in enumerate(subsections):
        note = f"第{chapter_code}章 {number}"
        if number in seen or note in covered or not _under_test_section(number, titles):
            continue
        seen.add(number)
        has_children = any(other.startswith(number + ".") for _, other, _ in subsections)
        if has_children:
            continue
        following = subsections[index + 1][0] if index + 1 < len(subsections) else len(body)
        segment = _clean(re.sub(r"^\s*" + re.escape(number), "", body[position:following]).strip())
        title = titles.get(number)
        if title and _bare(segment) in ("", title):
            standard = LISTED_ONLY
        elif len(segment) >= 6:
            standard = segment[:150]
            title = title or next((titles[n] for n in _ancestors(number) if n in titles), chapter_title)
        else:
            continue
        rows.append(FunctionTestRow(
            chapter_title, (title or chapter_title).rstrip("：:"), standard, "測試時", _method(segment or title),
            "（待填）", "檢修調整或更換", "測試報告", note,
        ))
        covered.add(note)
    if not rows:
        rows = _template_rows(chapter_code, chapter_title)
    rows.sort(key=lambda r: [int(n) for n in r.note.split()[-1].split(".")] if r.note != TEMPLATE_NOTE else [0])
    return FunctionTestDraft(chapter_code, chapter_title, rows)


def _bare(text: str) -> str:
    """去掉編號、空白、句號與括號：「綜合檢查 3.2.5。」->「綜合檢查」。"""
    return re.sub(r"[\d.\s。:：\[\]]", "", text)


def _ancestors(number: str) -> list[str]:
    parts = number.split(".")
    return [".".join(parts[:depth]) for depth in range(len(parts) - 1, 1, -1)]


TEMPLATE_NOTE = "通用範本（本案規範沒有測試小節）"


def _template_rows(chapter_code: str, chapter_title: str) -> list[FunctionTestRow]:
    """規範這一章沒有任何測試小節：用 data/function_test_templates.json 依章碼（或前三碼的類別）列常見測試項目，
    判定值待填、備註標「通用範本」——讓品管人員知道這是範本、不是本案規範寫的。"""
    templates = _templates()
    items = templates.get(chapter_code) or templates.get(chapter_code[:3], [])
    return [
        FunctionTestRow(chapter_title, item, LISTED_ONLY, "測試時", method, "（待填）", "檢修調整或更換", "測試報告",
                        TEMPLATE_NOTE)
        for item, method in items
    ]


@cache
def _templates() -> dict[str, list[tuple[str, str]]]:
    from app.core.config import settings

    with open(settings.DATA_DIR / "function_test_templates.json", encoding="utf-8") as file:
        data = json.load(file)
    return {key: [tuple(item) for item in items] for key, items in data["templates"].items()}


def _method(sentence: str) -> str:
    if _INSTRUMENT.search(sentence):
        return "儀器量測"
    if _OPERATE.search(sentence):
        return "實際操作"
    return "試驗（依規範）" if _TEST_WORD.search(sentence) else "目視"


def _under_test_section(number: str, titles: dict[str, str]) -> bool:
    parts = number.split(".")
    return any(_TEST_TITLE.search(titles.get(".".join(parts[:depth]), "")) for depth in range(2, len(parts) + 1))


def function_test_xlsx(draft: FunctionTestDraft) -> bytes:
    """兩張工作表：承攬廠商的檢測標準表、監造的測試抽驗標準表。內容相同，用語照兩邊的計畫。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheets = (
        ("設備功能運轉檢測標準表", draft.title, COLUMNS),
        ("設備功能運轉測試抽驗標準表", draft.supervision_title, SUPERVISION_COLUMNS),
    )
    for index, (name, title, columns) in enumerate(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = name
        sheet.append([title])
        sheet.append([draft.notice])
        sheet.append(list(columns))
        for r in draft.rows:
            sheet.append([r.equipment, r.item, r.standard, r.timing, r.method, r.frequency, r.handling, r.record, r.note])
        sheet["A1"].font = Font(bold=True, size=14)
        sheet["A2"].font = Font(bold=True, color="C00000")
        for cell in sheet[3]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9E1F2")
        for column, width in zip("ABCDEFGHI", (16, 16, 48, 10, 12, 16, 16, 12, 18)):
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=4):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
