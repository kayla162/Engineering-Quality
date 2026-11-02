"""品質管理標準表初稿（橘框表單的第一種）：從本案施工規範的一章擷取管理項目與管理標準。

欄位照秀山分隊整體品質計畫裡的「○○工程品質管理標準表」（表四-3 起）：

    施工流程｜管理項目｜管理標準｜檢查時機｜檢查方法｜檢查頻率｜不合格之處理｜管理紀錄｜備註

做法刻意簡單、可追溯：「2. 產品」與「3. 施工」節裡，**寫得出可檢查標準**的句子（應符合 CNS、
不得…、±6mm、每批取樣…）才成為一列，管理項目是它所在小節的標題，備註寫出處（第03210章 3.4.1）。
檢查方法、時機、處理方式依關鍵字給預設值，句子沒寫的檢查頻率留「（待填）」——不編。

這是**初稿**：規範書是通用條文，本案的數量、圖號、判定值要由品管人員依圖說補正。
"""

import re
from dataclasses import dataclass, field

NOTICE = "AI 初稿：依本案施工規範擷取，管理標準與頻率須由品管人員依契約圖說檢討補正後使用。"
MAX_STANDARD = 90

#: 頁首「03210 03210-13 V5.0 2018/01/17」
_PAGE_HEADER = re.compile(r"\d{5}\s+\d{5}-\d+\s+V[\d.]+\s+\d{4}/\d{2}/\d{2}")
_PART = re.compile(r"(?:^|\s)([1-4])\.\s*(通\s*則|產\s*品|施\s*工|計\s*量)")
#: 小節「3.2.3 鋼筋續接」：編號後面接的標題（到下一個空白為止，最多 12 字）
_SUBSECTION = re.compile(r"(?:^|\s)([23]\.\d+(?:\.\d+)?)\s+([^\s\d(（\[][^\s(（\[]{0,11})")
#: 寫得出可檢查標準的句子
_CRITERION = re.compile(
    r"不得|應符合|須符合|容許|誤差|許可差|以內|以上|以下|≧|≦|±|％|%|mm|cm|試驗|檢驗|抽驗|取樣|CNS|ASTM"
)
#: 不是品管：計量計價、送審程序
_NOT_QC = re.compile(r"計價|計量|單價|付款")
_FREQUENCY = re.compile(r"每[^，,。；]{0,14}?(?:批|個|次|組|層|處|車)[^。；]{0,16}?(?:取樣|試驗|檢驗)\s*\d*\s*[個組次]?")
_MEASURE = re.compile(r"mm|cm|±|許可差|誤差|間距|長度|厚度|位置|尺寸")
_TEST = re.compile(r"試驗|抗拉|抗壓|強度|檢測|取樣")
#: 小節「標題」其實是句子開頭
_NOT_A_TITLE = re.compile(r"[，,、；]|應|如|在|之規定|者|得|於")


@dataclass(frozen=True)
class StandardRow:
    stage: str
    item: str
    standard: str
    timing: str
    method: str
    frequency: str
    handling: str
    record: str
    note: str


@dataclass(frozen=True)
class QualityStandardDraft:
    chapter_code: str
    chapter_title: str
    title: str
    notice: str = NOTICE
    rows: list[StandardRow] = field(default_factory=list)


COLUMNS = ("施工流程", "管理項目", "管理標準", "檢查時機", "檢查方法", "檢查頻率", "不合格之處理", "管理紀錄", "備註")


def draft_quality_standard(chapter_code: str, chapter_title: str, chapter_text: str) -> QualityStandardDraft:
    text = _PAGE_HEADER.sub(" ", chapter_text)
    parts = {m.group(1): m.end() for m in _PART.finditer(text)}
    start = parts.get("2", parts.get("3", 0))
    end = next((m.start() for m in _PART.finditer(text) if m.group(1) == "4"), len(text))
    body = text[start:end]

    subsections = [(m.start(), m.group(1), m.group(2)) for m in _SUBSECTION.finditer(body)]
    rows = []
    for sentence, position in _sentences(body):
        if not _CRITERION.search(sentence) or _NOT_QC.search(sentence):
            continue
        number, item = _subsection_at(subsections, position)
        if number is None:
            continue
        stage = _stage(number, item)
        rows.append(
            StandardRow(
                stage=stage,
                item=item,
                standard=_clean(sentence),
                timing={"材料": "材料進場時", "施工前": "施工前", "施工後": "完成後"}.get(stage, "施工中"),
                method=_method(sentence),
                frequency=_frequency(sentence),
                handling=_handling(stage, sentence),
                record="材料進場檢驗紀錄" if stage == "材料" else ("試驗報告" if "試驗" in sentence else "施工自主檢查表"),
                note=f"第{chapter_code}章 {number}",
            )
        )
    return QualityStandardDraft(
        chapter_code=chapter_code,
        chapter_title=chapter_title,
        title=f"{chapter_title}工程品質管理標準表（初稿）",
        rows=rows,
    )


def _sentences(body: str):
    """（句子, 句子在 body 裡的位置）。句子以「。」結尾；小節編號留在句首時去掉。"""
    position = 0
    for piece in body.split("。"):
        sentence = re.sub(r"^\s*(?:[23]\.\d+(?:\.\d+)*\s+\S{1,12}\s+)+", "", piece).strip()
        sentence = re.sub(r"^\s*[23]\.\d+(?:\.\d+)*\s*", "", sentence)
        sentence = re.sub(r"^\s*(?:[（(]\d+[)）]|[A-Za-z]\.)\s*", "", sentence)
        if len(sentence) >= 6 and not _is_table(sentence):
            # 句子本身的位置（跳過句首的小節編號），才對得到它所在的最深小節
            yield sentence, position + max(piece.find(sentence[:8]), 0)
        position += len(piece) + 1


def _subsection_at(subsections, position: int) -> tuple[str | None, str]:
    """句子所在的最深小節編號，與最近一個像標題的標題。

    「2.1.1 鋼筋」取「鋼筋」；「2.1.2 鋼筋直徑在9mm 以上者…」的「標題」其實是句子開頭，
    改用上一層「2.1 材料」。編號仍寫最深那一層，出處才準。
    """
    titles: dict[str, str] = {}
    number = None
    for start, sub_number, title in subsections:
        if start > position + 1:
            break
        number = sub_number
        titles[sub_number] = title
    if number is None:
        return None, ""
    parts = number.split(".")
    for depth in range(len(parts), 1, -1):
        title = titles.get(".".join(parts[:depth]), "")
        if title and not _NOT_A_TITLE.search(title):
            return number, title
    return number, ""


def _is_table(sentence: str) -> bool:
    """表格標題或表格內容攤平的一串數字：「表一竹節鋼筋…D10 0.560 9.53」。"""
    if re.match(r"表[一二三四五六七八九十\d]", sentence):
        return True
    digits = sum(ch.isdigit() for ch in sentence)
    return digits / len(sentence) > 0.25


def _stage(number: str, item: str) -> str:
    if number.startswith("2."):
        return "材料"
    if number.startswith("3.1") or re.search(r"準備|放樣", item):
        return "施工前"
    if re.search(r"驗收|清理|養護|完成", item):
        return "施工後"
    return "施工中"


def _clean(sentence: str) -> str:
    sentence = re.sub(r"\s+", " ", sentence).replace("[", "").replace("]", "")
    sentence = re.sub(r"(?<=[一-鿿]) (?=[一-鿿])", "", sentence)
    sentence = sentence if sentence.endswith("。") else sentence + "。"
    return sentence if len(sentence) <= MAX_STANDARD else sentence[: MAX_STANDARD - 1] + "…"


def _method(sentence: str) -> str:
    if _MEASURE.search(sentence):
        return "量測（米尺／捲尺）"
    if _TEST.search(sentence):
        return "試驗（依規範送驗）"
    return "目視檢核"


def _frequency(sentence: str) -> str:
    match = _FREQUENCY.search(sentence.replace("[", "").replace("]", ""))
    return re.sub(r"\s+", "", match.group(0)) if match else "（待填）"


def _handling(stage: str, sentence: str) -> str:
    if stage == "材料":
        return "退貨，運離工地"
    if "拒收" in sentence:
        return "該批拒收"
    if "重驗" in sentence:
        return "依規定重驗，不合格拒收"
    return "拆除或修改"


def to_xlsx(draft: QualityStandardDraft) -> bytes:
    """匯出成 Excel：標題、初稿聲明、表頭、各列。版面照整體品質計畫的品質管理標準表。"""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = draft.chapter_code
    sheet.append([draft.title])
    sheet.append([draft.notice])
    sheet.append(list(COLUMNS))
    for row in draft.rows:
        sheet.append([row.stage, row.item, row.standard, row.timing, row.method, row.frequency,
                      row.handling, row.record, row.note])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"].font = Font(bold=True, color="C00000")
    for cell in sheet[3]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9E1F2")
    for column, width in zip("ABCDEFGHI", (8, 16, 48, 12, 16, 22, 16, 16, 18)):
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A4"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
