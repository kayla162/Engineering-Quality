"""品質計畫審查（橘框對綠框）：承攬廠商品質計畫裡的品質管理標準表，漏了哪些本案施工規範的可檢查標準。

邏輯圖的「結果」：品管人員把資料整合成橘框，和綠框不符的話要改。這裡只回答一個判斷得了的問題：
**規範有、計畫沒寫**——規範那一章（`quality_standard` 擷取的列）某一列的關鍵值（CNS 560、±6mm、25D、
48 小時…）在計畫對應的那張表裡一次都沒出現，就列出來。

做不到、也不假裝做：
- 寫了但寫錯的值（計畫寫 ±10mm、規範 ±6mm）——同一個值可能出現在別的表或別的單位寫法。
- 沒有可比對值的條文（「不得以銲接為之」）——字面不同不代表沒寫到，不判斷。

秀山實測（2026-11，真實整體品質計畫 × 真實施工規範）：7 張品質管理標準表，4 張對得到規範章
（開挖及土方、筏基鋼筋、地上層鋼筋、混凝土）；總表、假設工程、基樁三張本案規範沒有對應的章。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.specs.chapter_reader import SpecChapterRow
from app.specs.quality_standard import StandardRow, draft_quality_standard

#: 可比對的關鍵值：標準編號、±容許差、帶單位的數值
_KEY_VALUE = re.compile(
    r"(?:CNS|ASTM|ACI|AWS|JIS)\s*[A-Z]?\s*\d+[A-Z\d.]*"
    r"|±\s*\d+(?:\.\d+)?\s*(?:mm|cm|%|m)?"
    r"|\d+(?:\.\d+)?\s*(?:mm|cm|kgf/cm2|MPa|%|D|℃|小時|天|日)"
)
_CAPTION = re.compile(r"^表\s*[一二三四五六七八九十\d-]+\s*")
_SUBJECT_TAIL = re.compile(r"(?:工程)?品質管理標準表$")
#: 計畫表的分項名稱帶的修飾：「筏基鋼筋」「地上層鋼筋」對的都是「鋼筋」那一章
_SUBJECT_PREFIX = re.compile(r"^(?:筏基|地上層|地下層|基礎|上部結構|外部)")


@dataclass(frozen=True)
class PlanTable:
    title: str
    text: str


@dataclass(frozen=True)
class PlanTableReview:
    title: str
    chapter_code: str | None
    chapter_title: str | None
    #: 規範那一章有可比對值的列數
    judged: int = 0
    #: 規範有、計畫這張表沒寫到的列
    missing: list[StandardRow] = field(default_factory=list)


@dataclass(frozen=True)
class PlanReview:
    plan_name: str
    tables: list[PlanTableReview]


def plan_standard_tables(path: Path) -> list[PlanTable]:
    """品質計畫（docx）裡表頭有「管理項目」與「管理標準」的表，標題是表上方最近的一段文字。"""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    tables, caption = [], ""
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, document).text.strip()
            if text:
                caption = text
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            header = " ".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
            if "管理項目" in header and "管理標準" in header:
                text = "".join(cell.text for row in table.rows for cell in row.cells)
                tables.append(PlanTable(_CAPTION.sub("", caption).split("\t")[0].strip(), _squash(text)))
    return tables


def review_plan(path: Path, chapters: list[SpecChapterRow]) -> PlanReview:
    reviews = []
    for table in plan_standard_tables(path):
        chapter = _chapter_for(table.title, chapters)
        if chapter is None:
            reviews.append(PlanTableReview(table.title, None, None))
            continue
        rows = draft_quality_standard(chapter.code, chapter.title, chapter.text).rows
        judged = [(row, _KEY_VALUE.findall(row.standard)) for row in rows]
        judged = [(row, values) for row, values in judged if values]
        missing = [row for row, values in judged if not any(_squash(v) in table.text for v in values)]
        reviews.append(PlanTableReview(table.title, chapter.code, chapter.title, len(judged), missing))
    return PlanReview(path.name, reviews)


def _chapter_for(title: str, chapters: list[SpecChapterRow]) -> SpecChapterRow | None:
    """「混凝土工程品質管理標準表」->「結構用混凝土」：章名含分項主體，以「章名以主體結尾、章名最短」優先。

    「模板組立」主體取前兩字「模板」——章名是「場鑄結構混凝土用模板」；「混凝土」不能對到這一章，
    所以優先章名以主體結尾的那一章。
    """
    subject = _SUBJECT_PREFIX.sub("", _SUBJECT_TAIL.sub("", title))
    for core in dict.fromkeys([subject, subject[:2], subject[-2:]]):
        if len(core) < 2:
            continue
        candidates = [c for c in chapters if core in c.title]
        if candidates:
            return sorted(candidates, key=lambda c: (not c.title.endswith(core), len(c.title)))[0]
    return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def plan_review_xlsx(review: PlanReview) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    summary = book.active
    summary.title = "審查摘要"
    summary.append([f"品質計畫審查（橘框對綠框）：{review.plan_name}"])
    summary.append(["只列「規範有可比對的值、計畫這張表沒寫到」的條文；寫了但值不同、沒有可比對值的條文不判斷，需人工審查。"])
    summary.append(["計畫的表", "對應規範章", "規範可比對列數", "計畫沒寫到"])
    for table in review.tables:
        chapter = f"第{table.chapter_code}章 {table.chapter_title}" if table.chapter_code else "本案規範沒有對應的章"
        summary.append([table.title, chapter, table.judged, len(table.missing)])
    detail = book.create_sheet("計畫沒寫到的規範標準")
    detail.append(["計畫的表", "施工流程", "管理項目", "規範的管理標準", "出處"])
    for table in review.tables:
        for row in table.missing:
            detail.append([table.title, row.stage, row.item, row.standard, row.note])
    summary["A1"].font = Font(bold=True, size=14)
    summary["A2"].font = Font(bold=True, color="C00000")
    for sheet, header_row, widths in ((summary, 3, (36, 28, 16, 12)), (detail, 1, (30, 10, 18, 60, 18))):
        for cell in sheet[header_row]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9E1F2")
        for column, width in zip("ABCDE", widths):
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=header_row + 1):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
