"""施工要領與施工流程圖初稿（橘框表單）。

秀山整體品質計畫的「3.7鋼筋組立工程施工要領」就是：施工機具、使用材料、施工方法步驟（施工規範
「3. 施工」各小節的條文，「工程司」改成「監造單位」）與施工流程圖（★為檢驗停留點）。初稿照這個結構：

- 使用材料：標單裡屬於這一章的工項名稱（真實資料，不是規範的通用材料表）。
- 施工方法、步驟：「3. 施工」各小節依序排，小節標題是句子開頭時用上一層的標題（和品質管理標準表同一套規則）。
- 流程圖：步驟標題依序；小節是檢驗、試驗、許可差，或條文要求檢驗、試驗、檢查認可的，標★。
- 施工機具：規範不寫，留「（待填）」。
"""

import io
import re
from dataclasses import dataclass, field

from app.specs.quality_standard import (
    _PAGE_HEADER,
    _PART,
    _SUBSECTION,
    _is_table,
    _subsection_at,
)

NOTICE = "AI 初稿：施工方法取自本案施工規範第3節、使用材料取自標單，須由工地主任與品管人員依契約圖說及施工計畫補正。"
#: 這種步驟是檢驗停留點（★）
_HOLD_TITLE = re.compile(r"檢驗|試驗|許可差|檢查|驗收")
_HOLD_SENTENCE = re.compile(r"檢驗|試驗|檢查認可|抽驗|取樣")


@dataclass(frozen=True)
class MethodStep:
    title: str
    sentences: list[str]
    hold_point: bool


@dataclass(frozen=True)
class MethodStatement:
    chapter_code: str
    chapter_title: str
    title: str
    materials: list[str]
    steps: list[MethodStep] = field(default_factory=list)
    tools: str = "（待填）"
    notice: str = NOTICE

    @property
    def flow(self) -> list[str]:
        return [("★" if step.hold_point else "") + step.title for step in self.steps]


def draft_method_statement(
    chapter_code: str, chapter_title: str, chapter_text: str, materials: list[str]
) -> MethodStatement:
    text = _PAGE_HEADER.sub(" ", chapter_text)
    construction = next((m.end() for m in _PART.finditer(text) if m.group(1) == "3"), None)
    end = next((m.start() for m in _PART.finditer(text) if m.group(1) == "4"), len(text))
    steps: list[MethodStep] = []
    if construction is not None:
        body = text[construction:end]
        subsections = [(m.start(), m.group(1), m.group(2)) for m in _SUBSECTION.finditer(body)]
        # 同名小節合成一步（中間被別的小節隔開時也是），順序取第一次出現
        grouped: dict[str, list[str]] = {}
        for sentence, position in _sentences(body):
            _, title = _subsection_at(subsections, position)
            if title:
                grouped.setdefault(title, []).append(sentence)
        steps = [
            MethodStep(
                title=title,
                sentences=sentences,
                hold_point=bool(_HOLD_TITLE.search(title) or any(_HOLD_SENTENCE.search(s) for s in sentences)),
            )
            for title, sentences in grouped.items()
        ]
    return MethodStatement(
        chapter_code=chapter_code,
        chapter_title=chapter_title,
        title=f"{chapter_title}工程施工要領（初稿）",
        materials=list(dict.fromkeys(m.strip() for m in materials if m.strip())),
        steps=steps,
    )


def _sentences(body: str):
    """（條文, 位置）。去掉句首小節編號與項次，「工程司」改成「監造單位」，不截斷——施工要領要整句。"""
    position = 0
    for piece in body.split("。"):
        sentence = re.sub(r"^\s*(?:[3]\.\d+(?:\.\d+)*\s+\S{1,12}\s+)+", "", piece).strip()
        sentence = re.sub(r"^\s*[3]\.\d+(?:\.\d+)*\s*", "", sentence)
        sentence = re.sub(r"^\s*(?:[（(]\d+[)）]|[A-Za-z]\.)\s*", "", sentence)
        sentence = re.sub(r"\s+", " ", sentence).replace("[", "").replace("]", "")
        sentence = re.sub(r"(?<=[一-鿿]) (?=[一-鿿])", "", sentence).replace("工程司", "監造單位")
        if len(sentence) >= 6 and not _is_table(sentence):
            yield sentence + "。", position + max(piece.find(sentence[:8]), 0)
        position += len(piece) + 1


def method_statement_docx(statement: MethodStatement) -> bytes:
    """Word 檔：標題、初稿聲明、四個部分；流程圖用一欄的表格由上而下畫，★為檢驗停留點。"""
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import RGBColor

    document = docx.Document()
    document.add_heading(statement.title, level=1)
    notice = document.add_paragraph().add_run(statement.notice)
    notice.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    notice.bold = True

    document.add_heading("一、施工機具", level=2)
    document.add_paragraph(statement.tools)
    document.add_heading("二、使用材料", level=2)
    for material in statement.materials or ["（待填）"]:
        document.add_paragraph(material, style="List Bullet")
    document.add_heading("三、施工方法、步驟", level=2)
    for number, step in enumerate(statement.steps, start=1):
        document.add_paragraph(f"{number}. {step.title}" + ("（★檢驗停留點）" if step.hold_point else ""))
        for sentence in step.sentences:
            document.add_paragraph(sentence, style="List Bullet 2")
    document.add_heading("四、施工流程圖", level=2)
    table = document.add_table(rows=0, cols=1)
    table.style = "Table Grid"
    for index, box in enumerate(["開始", *statement.flow, "完成"]):
        if index:
            arrow = table.add_row().cells[0]
            arrow.text = "↓"
            arrow.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        cell = table.add_row().cells[0]
        cell.text = box
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph("★為檢驗停留點：須經檢查合格後方可進行下一步驟。")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
