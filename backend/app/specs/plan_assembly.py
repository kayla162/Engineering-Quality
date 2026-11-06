"""整體品質計畫與監造計畫初稿（Word）：把各章的橘框表單初稿組成一份計畫。

需求說明第 4 點：「因為可以產出 3. 了，其實就離完整的『整體品質計畫』、『監造計畫』不遠了，差在部分內容
需要使用者提供」。所以：

- 章節照秀山整體品質計畫的目錄（計畫範圍、管理權責、品管組織、施工要領、品質管理標準、材料及施工檢驗程序、
  設備功能運轉檢測程序及標準、自主檢查表、不合格品管制、矯正預防與稽核）；監造計畫照監造計畫的對應章節。
- 系統產生得了的章（施工要領、品質管理標準、檢驗、功能運轉、自主檢查、抽查抽驗）由本案標單用到的每一章
  施工規範產生，內容和單獨下載的各張初稿相同。
- 組織、權責、程序這些要公司與工地提供的章寫「（待填）」並說明要填什麼，不編。
"""

import io

from app.specs import contractor_procedures, demo_fill
from app.specs.chapter_reader import SpecChapterRow
from app.specs.derived_forms import self_inspection, supervision_standard
from app.specs.function_test import draft_function_test, is_equipment_chapter
from app.specs.method_statement import draft_method_statement
from app.specs.quality_standard import COLUMNS as STANDARD_COLUMNS
from app.specs.quality_standard import draft_quality_standard

NOTICE = (
    "AI 初稿：第四至八章由本案施工規範與標單產生，其餘章節須由承攬廠商（監造單位）依公司程序與工地編制填寫；"
    "全文須經品管（監造）人員檢討補正後提送。"
)


def quality_plan_docx(
    project_name: str, chapters: list[SpecChapterRow], materials: dict[str, list[str]], demo: bool = False
) -> bytes:
    """demo=True：系統產生不了的欄位與章節用示範內容補齊（demo_fill，標「（示範）」「【示範】」）。"""
    fill = _Fill(demo, "quality")
    document = _new(f"{project_name} 整體品質計畫（初稿{'・示範補正' if demo else ''}）", demo)
    _section(document, "一、計畫範圍", [
        f"工程名稱：{project_name}",
        f"本計畫涵蓋本案標單所列工項，對應本案施工規範 {len(chapters)} 章：" + "、".join(f"第{c.code}章{c.title}" for c in chapters) + "。",
    ] + fill.section("一、計畫範圍", "（待填：工程概要、主要施工項目及數量、適用對象、名詞定義）"))
    _section(document, "二、管理權責及分工", fill.section("二、管理權責及分工", "（待填：承攬廠商、協力廠商、監造單位與主辦機關之權責分工表）"))
    _section(document, "三、品管組織及工作職掌", fill.section("三、品管組織及工作職掌", "（待填：品管組織架構圖、品管人員資格與工作職掌）"))

    document.add_heading("四、施工要領", level=1)
    for chapter in chapters:
        statement = fill.method(draft_method_statement(chapter.code, chapter.title, chapter.text, materials.get(chapter.code, [])))
        document.add_heading(statement.title, level=2)
        document.add_paragraph("使用材料：" + ("、".join(statement.materials) or "（待填）"))
        document.add_paragraph(f"施工機具：{statement.tools}")
        for number, step in enumerate(statement.steps, start=1):
            document.add_paragraph(f"{number}. {step.title}" + ("（★檢驗停留點）" if step.hold_point else ""))
            for sentence in step.sentences:
                document.add_paragraph(sentence, style="List Bullet 2")
        if statement.flow:
            document.add_paragraph("施工流程：" + " → ".join(statement.flow) + "（★為檢驗停留點）")

    document.add_heading("五、品質管理標準", level=1)
    drafts = [fill.standard(draft_quality_standard(c.code, c.title, c.text)) for c in chapters]
    for draft in drafts:
        document.add_heading(draft.title, level=2)
        _table(document, STANDARD_COLUMNS, [
            (r.stage, r.item, r.standard, r.timing, r.method, r.frequency, r.handling, r.record, r.note)
            for r in draft.rows
        ])

    document.add_heading("六、材料及施工檢驗程序", level=1)
    fill.intro(document, "六、材料及施工檢驗程序")
    document.add_paragraph("材料進場與施工檢驗依第五章各表「檢查時機」辦理；材料檢驗項目如下（取自各章「2. 產品」）。")
    for draft in drafts:
        materials_rows = [r for r in draft.rows if r.stage == "材料"]
        if materials_rows:
            document.add_heading(f"{draft.chapter_title}材料檢驗", level=2)
            _table(document, ("材料", "檢驗標準", "檢驗方法", "頻率", "出處"),
                   [(r.item, r.standard, r.method, r.frequency, r.note) for r in materials_rows])

    document.add_heading("七、設備功能運轉檢測程序及標準", level=1)
    equipment = [c for c in chapters if is_equipment_chapter(c.code)]
    if not equipment:
        document.add_paragraph("本案標單沒有機電設備章。")
    for chapter in equipment:
        test = fill.function_test(draft_function_test(chapter.code, chapter.title, chapter.text))
        document.add_heading(test.title, level=2)
        _table(document, ("管理項目", "管理標準", "檢查方法", "檢查頻率", "出處"),
               [(r.item, r.standard, r.method, r.frequency, r.note) for r in test.rows])

    document.add_heading("八、自主檢查表", level=1)
    fill.intro(document, "八、自主檢查表")
    for draft in drafts:
        form = self_inspection(draft)
        document.add_heading(form.title, level=2)
        _table(document, ("施工階段", "檢查項目", "設計圖說、規範之檢查標準（定量／定性）", "實際檢查情形", "檢查結果"),
               [(s.stage, r.item, r.standard, "", "") for s in form.sections for r in s.rows])

    _section(document, "九、不合格品之管制",
             fill.section("九、不合格品之管制", "（待填：不合格材料及施工之標示、隔離、處置與複查程序，依公司程序書）"))
    _section(document, "十、矯正與預防措施、內部品質稽核及文件紀錄管理",
             fill.section("十、矯正與預防措施、內部品質稽核及文件紀錄管理",
                          "（待填：矯正預防處理流程、內部稽核頻率與查核表、文件紀錄分類與保存期限）"))
    return _save(document)


def supervision_plan_docx(
    project_name: str, chapters: list[SpecChapterRow], materials: dict[str, list[str]], demo: bool = False
) -> bytes:
    fill = _Fill(demo, "supervision")
    document = _new(f"{project_name} 監造計畫（初稿{'・示範補正' if demo else ''}）", demo)
    _section(document, "一、監造範圍", [
        f"工程名稱：{project_name}",
        "本計畫涵蓋本案施工規範：" + "、".join(f"第{c.code}章{c.title}" for c in chapters) + "。",
    ] + fill.section("一、監造範圍", "（待填：工程概要與監造範圍）"))
    _section(document, "二、監造組織及權責分工", fill.section("二、監造組織及權責分工", "（待填：監造組織架構、人員資格與權責）"))
    _section(document, "三、品質計畫與施工計畫審查作業程序",
             ["承攬廠商品質計畫可用系統的「品質計畫審查（橘框對綠框）」比對本案規範，列出計畫漏寫的可檢查標準。"]
             + fill.section("三、品質計畫與施工計畫審查作業程序", "（待填：審查流程與期限）"))
    forms = [supervision_standard(fill.standard(draft_quality_standard(c.code, c.title, c.text))) for c in chapters]
    columns = ("管理項目", "抽查標準（定量／定性）", "抽查時機", "抽查方法", "抽查頻率", "依據")

    document.add_heading("四、材料設備抽驗程序及標準", level=1)
    fill.intro(document, "四、材料設備抽驗程序及標準")
    for form in forms:
        if form.material_rows:
            document.add_heading(form.title.replace("施工抽查標準表", "材料抽驗標準表"), level=2)
            _table(document, columns, [(r.item, r.standard, r.timing, r.method, r.frequency, r.basis) for r in form.material_rows])

    document.add_heading("五、施工抽查程序及標準", level=1)
    fill.intro(document, "五、施工抽查程序及標準")
    for form in forms:
        document.add_heading(form.title, level=2)
        _table(document, columns, [(r.item, r.standard, r.timing, r.method, r.frequency, r.basis) for r in form.inspection_rows])

    document.add_heading("六、設備功能運轉測試抽驗程序及標準", level=1)
    equipment = [c for c in chapters if is_equipment_chapter(c.code)]
    if not equipment:
        document.add_paragraph("本案標單沒有機電設備章。")
    for chapter in equipment:
        test = fill.function_test(draft_function_test(chapter.code, chapter.title, chapter.text))
        document.add_heading(test.supervision_title, level=2)
        _table(document, ("抽驗項目", "抽驗標準", "抽驗方法", "抽驗頻率", "出處"),
               [(r.item, r.standard, r.method, r.frequency, r.note) for r in test.rows])

    _section(document, "七、品質稽核及文件紀錄管理",
             fill.section("七、品質稽核及文件紀錄管理", "（待填：監造日報、抽查紀錄、缺失追蹤與文件保存方式）"))
    return _save(document)


class _Fill:
    """組織與程序章節先用承攬廠商範本（contractor_procedures）；範本沒涵蓋的部分，demo=False 留「（待填）」，
    demo=True 用 demo_fill 補齊。表單類的欄位 demo=False 時原樣傳回。"""

    def __init__(self, demo: bool, kind: str):
        self.demo = demo
        self.sections = demo_fill.plan_sections(kind) if demo else {}
        self.procedures = contractor_procedures.sections(kind)

    def section(self, heading: str, blank: str) -> list[str]:
        procedure = self.procedures.get(heading)
        if procedure is None:
            return self.sections.get(heading, [blank])
        if procedure.still_blank is None:
            return list(procedure.paragraphs)
        return procedure.paragraphs + self.sections.get(heading, [procedure.still_blank])

    def intro(self, document, heading: str) -> None:
        """表單章（材料檢驗、自主檢查、抽驗、抽查）開頭的程序說明。"""
        procedure = self.procedures.get(heading)
        for text in procedure.paragraphs if procedure else []:
            document.add_paragraph(text)

    def standard(self, draft):
        return demo_fill.fill_standard(draft) if self.demo else draft

    def function_test(self, draft):
        return demo_fill.fill_function_test(draft) if self.demo else draft

    def method(self, statement):
        return demo_fill.fill_method(statement) if self.demo else statement


def _new(title: str, demo: bool = False):
    import docx
    from docx.shared import RGBColor

    document = docx.Document()
    document.add_heading(title, level=0)
    run = document.add_paragraph().add_run((demo_fill.NOTICE if demo else "") + NOTICE)
    run.bold = True
    run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    document.add_paragraph(contractor_procedures.provenance())
    return document


def _section(document, heading: str, paragraphs: list[str]) -> None:
    document.add_heading(heading, level=1)
    for text in paragraphs:
        document.add_paragraph(text)


def _table(document, columns, rows) -> None:
    rows = list(rows)
    if not rows:
        document.add_paragraph("（本章規範沒有可擷取的條文，待填）")
        return
    table = document.add_table(rows=1, cols=len(columns))
    table.style = "Table Grid"
    for cell, title in zip(table.rows[0].cells, columns):
        cell.text = title
    for row in rows:
        for cell, value in zip(table.add_row().cells, row):
            cell.text = str(value)


def _save(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
