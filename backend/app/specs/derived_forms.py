"""由品質管理標準表初稿衍生的另外兩種橘框表單（邏輯圖的兩個橘框）：

- 承攬廠商：**施工自主檢查表**，格式照秀山整體品質計畫第七章（檢查項目｜設計圖說、規範之檢查標準｜
  實際檢查情形｜檢查結果，分施工前／施工中／施工後）。實際檢查情形與檢查結果留白給現場填。
- 監造單位：**施工抽查標準表**與**材料抽驗標準表**（監造計畫的兩張表），欄位照工程會監造計畫製作綱要的用語。

三種表都從同一份初稿（`quality_standard.draft_quality_standard`）出來，檢查項目與標準一致——
整體品質計畫與監造計畫本來就要互相對應，各自從規範重抄一次只會對不起來。
"""

import io
from dataclasses import dataclass, field

from app.specs.quality_standard import QualityStandardDraft

NOTICE = "AI 初稿：檢查項目與標準取自本案施工規範，須由品管（監造）人員依契約圖說檢討補正後使用。"
STAGES = ("施工前", "施工中", "施工後")
RESULT_LEGEND = "○檢查合格　　╳有缺失需改正　　／無此檢查項目"
SITE_NOTE = "備註：1.檢查標準及實際檢查情形應具體明確（如：鋼筋間距 15cm±1cm、實測 15.5cm）。2.缺失改正後應複查。"


@dataclass(frozen=True)
class InspectionRow:
    item: str
    standard: str


@dataclass(frozen=True)
class InspectionSection:
    stage: str
    rows: list[InspectionRow]


@dataclass(frozen=True)
class SelfInspectionForm:
    title: str
    chapter_code: str
    sections: list[InspectionSection]
    notice: str = NOTICE


@dataclass(frozen=True)
class SupervisionRow:
    item: str
    standard: str
    timing: str
    method: str
    frequency: str
    basis: str


@dataclass(frozen=True)
class SupervisionForm:
    title: str
    chapter_code: str
    inspection_rows: list[SupervisionRow] = field(default_factory=list)
    material_rows: list[SupervisionRow] = field(default_factory=list)
    notice: str = NOTICE


def self_inspection(draft: QualityStandardDraft) -> SelfInspectionForm:
    """施工自主檢查表：施工前／中／後的列；材料進場另有材料檢驗表，不放這裡。"""
    sections = []
    for stage in STAGES:
        rows = [InspectionRow(r.item, r.standard) for r in draft.rows if r.stage == stage]
        if rows:
            sections.append(InspectionSection(stage, rows))
    return SelfInspectionForm(
        title=f"{draft.chapter_title}工程施工自主檢查表（初稿）",
        chapter_code=draft.chapter_code,
        sections=sections,
    )


def supervision_standard(draft: QualityStandardDraft) -> SupervisionForm:
    def to_row(r) -> SupervisionRow:
        return SupervisionRow(r.item, r.standard, r.timing, r.method, r.frequency, r.note)

    return SupervisionForm(
        title=f"{draft.chapter_title}工程施工抽查標準表（初稿）",
        chapter_code=draft.chapter_code,
        inspection_rows=[to_row(r) for r in draft.rows if r.stage != "材料"],
        material_rows=[to_row(r) for r in draft.rows if r.stage == "材料"],
    )


def self_inspection_xlsx(form: SelfInspectionForm) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "自主檢查表"
    sheet.append([form.title])
    sheet.append([form.notice])
    sheet.append(["工程名稱", "", "分項工程名稱", ""])
    sheet.append(["檢查位置", "", "檢查日期", "　　年　　月　　日"])
    sheet.append(["檢查結果", RESULT_LEGEND])
    sheet.append(["檢查項目", "設計圖說、規範之檢查標準（定量／定性）", "實際檢查情形（敘述檢查值）", "檢查結果"])
    header_row = sheet.max_row
    for section in form.sections:
        sheet.append([section.stage])
        sheet.cell(sheet.max_row, 1).font = Font(bold=True)
        sheet.cell(sheet.max_row, 1).fill = PatternFill("solid", fgColor="EDEDED")
        for row in section.rows:
            sheet.append([row.item, row.standard, "", ""])
    sheet.append(["缺失複查結果：□已完成改善　□未完成改善，填至「不合格管制總表」"])
    sheet.append([SITE_NOTE])
    sheet.append(["承攬廠商", "工地主任：", "品管人員：", ""])
    _style(sheet, header_row, (18, 52, 30, 12))
    return _save(book)


def supervision_xlsx(form: SupervisionForm) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    columns = ["管理項目", "抽查標準（定量／定性）", "抽查時機", "抽查方法", "抽查頻率", "依據"]
    for index, (name, rows, title) in enumerate((
        ("施工抽查標準表", form.inspection_rows, form.title),
        ("材料抽驗標準表", form.material_rows, form.title.replace("施工抽查標準表", "材料抽驗標準表")),
    )):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = name
        sheet.append([title])
        sheet.append([form.notice])
        sheet.append(columns)
        for r in rows:
            sheet.append([r.item, r.standard, r.timing, r.method, r.frequency, r.basis])
        _style(sheet, 3, (18, 52, 12, 18, 22, 18))
    return _save(book)


def _style(sheet, header_row: int, widths: tuple[int, ...]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"].font = Font(bold=True, color="C00000")
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9E1F2")
    for column, width in zip("ABCDEF", widths):
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=header_row + 1):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _save(book) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
