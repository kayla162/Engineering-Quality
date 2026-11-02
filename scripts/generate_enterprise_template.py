"""產生企業內部文件清單的 Excel：給品保／文管單位填寫的範本，或填好假資料的示範清單。

    python scripts/generate_enterprise_template.py          # 範本
    python scripts/generate_enterprise_template.py --demo   # 示範清單（假資料）
    python scripts/generate_enterprise_template.py --from-quality-plan <整體品質計畫.docx>

範本輸出到 data/templates/企業內部文件清單範本.xlsx；示範清單輸出到
data/samples/enterprise_documents_demo.xlsx；從整體品質計畫產生的清單輸出到
data/samples/enterprise_documents_xiushan.xlsx。都可以直接匯入系統試用：

    python scripts/import_enterprise_documents.py data/samples/enterprise_documents_demo.xlsx --tenant <租戶名稱>

系統只需要目錄（編號、名稱、版次、狀態），不需要文件全文。類型與狀態的選項
和匯入時的檢查用同一份定義（app/services/enterprise_document_service.py）。
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from openpyxl import Workbook  # noqa: E402
from openpyxl.comments import Comment  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from app.services.enterprise_document_service import (  # noqa: E402
    DOCUMENT_TYPES,
    EXAMPLE_MARK,
    SHEET_NAME,
    STATUS_MAP,
)

TEMPLATE_PATH = ROOT / "data" / "templates" / "企業內部文件清單範本.xlsx"
DEMO_PATH = ROOT / "data" / "samples" / "enterprise_documents_demo.xlsx"
XIUSHAN_PATH = ROOT / "data" / "samples" / "enterprise_documents_xiushan.xlsx"

#: Arial 沒有繁體中文字形，改用微軟正黑體
FONT = "Microsoft JhengHei"
NAVY = "1F3864"
REQUIRED_FILL = PatternFill("solid", fgColor="FFF2CC")   # 必填欄底色
EXAMPLE_FILL = PatternFill("solid", fgColor="EDEDED")
DEMO_FILL = PatternFill("solid", fgColor="FCE4D6")
thin = Side(style="thin", color="BFBFBF")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
LAST_ROW = 1000

# (標題, 必填, 欄寬, 說明, 範例值)
COLUMNS = [
    ("文件編號", True, 14, "公司文件管制的唯一編號，同一份文件改版時不變。", "QP-07-03"),
    ("文件名稱", True, 30, "完整名稱，和工程文件裡引用時的寫法越接近越好。", "混凝土澆置作業標準"),
    ("類型", True, 16, "從下拉選單選。", "作業標準（SOP）"),
    ("版次", True, 10, "目前生效的版次，寫法照公司慣例。", "第5版"),
    ("生效日", True, 13, "目前這一版開始生效的日期。", date(2025, 3, 1)),
    ("最後修訂日", False, 13, "最近一次改版的日期；沒改過版就留空。", date(2025, 2, 20)),
    ("狀態", True, 10, "現行＝有效；已修訂＝仍有效但版次有變動；作廢＝不可再引用。", "現行"),
    ("取代文件編號", False, 14, "狀態為「作廢」時，取代它的新文件編號。", ""),
    ("主管單位", False, 14, "負責維護這份文件的部門。", "品保部"),
    ("別名", False, 32, "簡稱、舊名、常見寫法，用「、」分隔。文件編號不必重複寫。", "混凝土澆置標準、澆置SOP"),
    ("備註", False, 24, "其他說明。", f"{EXAMPLE_MARK}，填寫時請刪除"),
]

#: 示範清單：虛構的「示範營造股份有限公司」。刻意涵蓋三種狀態、作廢後被取代、
#: 只用編號或別名引用的情況，對應 data/samples/sample_quality_plan_enterprise.txt。
DEMO_ROWS = [
    ("QM-01", "品質手冊", "品質手冊", "第8版", date(2024, 7, 1), date(2024, 6, 15), "現行", None, "品保部", "公司品質手冊", None),
    ("QP-04-01", "文件管制程序書", "程序書", "第4版", date(2023, 1, 1), None, "現行", None, "品保部", None, None),
    ("QP-07-01", "模板組立作業標準", "作業標準（SOP）", "第2版", date(2019, 5, 1), None, "作廢", "QP-07-06", "工務部", "模板作業標準", "2025 年起改用 QP-07-06"),
    ("QP-07-02", "鋼筋綁紮作業標準", "作業標準（SOP）", "第4版", date(2025, 9, 1), date(2025, 8, 20), "已修訂", None, "工務部", "鋼筋作業標準", "第4版新增續接器檢查"),
    ("QP-07-03", "混凝土澆置作業標準", "作業標準（SOP）", "第5版", date(2025, 3, 1), date(2025, 2, 20), "現行", None, "工務部", "混凝土澆置標準、澆置SOP", None),
    ("QP-07-06", "模板組立及拆除作業標準", "作業標準（SOP）", "第1版", date(2025, 1, 1), None, "現行", None, "工務部", None, "取代 QP-07-01"),
    ("QP-08-02", "材料進場檢驗程序書", "程序書", "第3版", date(2024, 2, 1), None, "現行", None, "品保部", "進場檢驗程序", None),
    ("QP-09-01", "自主檢查程序書", "程序書", "第6版", date(2024, 9, 1), date(2024, 8, 10), "現行", None, "品保部", "自主檢查作業程序", None),
    ("QI-03-05", "混凝土抗壓試體取樣檢驗標準", "檢驗標準", "第2版", date(2023, 6, 1), None, "現行", None, "品保部", "試體取樣標準", None),
    ("QS-12-01", "施工安全衛生管理程序書", "程序書", "第3版", date(2024, 1, 1), None, "現行", None, "工安室", None, None),
    ("CS-03310", "公司版結構用混凝土施工規範", "施工規範", "第2版", date(2025, 6, 1), date(2025, 5, 15), "已修訂", None, "工務部", None, "依 PCCES 03310 增補"),
    ("OC-2025-01", "示範市工程特訂條款", "業主特訂條款", "2025年版", date(2025, 1, 1), None, "現行", None, "採購部", None, "虛構業主，僅供示範"),
]


#: 整體品質計畫裡，承攬廠商自有文件都以編號標題列出：「表 四-3 假設工程品質管理標準表」
#: 「3.7鋼筋組立工程施工要領」。內文句子（「…將提出之品質管理標準」）沒有編號，不會被當成文件。
_PLAN_TITLE = re.compile(r"^(?:表\s*(?P<table>[一二三四五六七八九十]+-\d+)|\d+\.\d+)\s*(?P<name>\S.*?)\s*$")
#: 一覽表的備註指向單一一張表（「詳表 四-6」）時，那一列是該表的另一個叫法；「詳表 四-10~11」不算
_PLAN_SEE_TABLE = re.compile(r"^詳表\s*(?P<table>[一二三四五六七八九十]+-\d+)$")
_TOC_PAGE = re.compile(r"\t+\s*\d+\s*$")
#: (名稱結尾, 範本類型, 編號前綴)。排在前面的先比對
_PLAN_KINDS = [
    (re.compile(r"品質管理標準表?$"), "檢驗標準", "QS"),
    (re.compile(r"(檢測|抽驗)標準表$"), "檢驗標準", "QT"),
    (re.compile(r"施工要領$"), "作業標準（SOP）", "CM"),
    (re.compile(r"自主檢查表$"), "表單", "CK"),
    (re.compile(r"紀錄表$"), "表單", "RF"),
]
#: 只是類別名稱、不是哪一份文件（「表 七-2自主檢查表」是空白格式）
_PLAN_GENERIC = {"品質管理標準", "品質管理標準表", "施工要領", "自主檢查表", "紀錄表"}
#: 從計畫書取不到、只好用假資料的欄位
PLAN_REVISION = "第1版"
PLAN_EFFECTIVE = date(2026, 1, 5)
PLAN_NOTE = "名稱取自整體品質計畫；編號、版次、生效日為假資料"


@dataclass
class ContractorDocument:
    name: str
    doc_type: str
    prefix: str
    aliases: list[str] = field(default_factory=list)
    remark: str | None = None


def contractor_documents(plan: Path) -> list[ContractorDocument]:
    """整體品質計畫裡列出的承攬廠商自有文件（品質管理標準、施工要領、自主檢查表、紀錄表），依出現順序。

    先收編號標題（「表 四-3 …」「3.7 …」），再收一覽表（表頭「項次｜作業名稱｜備註」）——
    一覽表才列得出全部分項，多數寫著「於分項施工計畫內訂定」，只在那裡出現。
    """
    import docx

    document = docx.Document(plan)
    found: dict[str, ContractorDocument] = {}
    by_table: dict[str, ContractorDocument] = {}
    for paragraph in document.paragraphs:
        match = _PLAN_TITLE.match(_TOC_PAGE.sub("", paragraph.text).strip())
        if not match or not (doc := _contractor_document(match["name"])):
            continue
        doc = found.setdefault(doc.name, doc)
        if match["table"]:
            by_table.setdefault(match["table"], doc)

    known = {term for d in found.values() for term in (d.name, *d.aliases)}
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows or len(rows[0]) < 3 or rows[0][0] != "項次":
            continue
        for _, name, remark, *_ in rows[1:]:
            if name in known or not (doc := _contractor_document(name)):
                continue
            see = _PLAN_SEE_TABLE.match(remark)
            if see and see["table"] in by_table:
                by_table[see["table"]].aliases.append(name)
            else:
                doc.remark = None if remark.startswith(("詳表", "詳圖")) else remark or None
                found[name] = doc
            known.add(name)
    return list(found.values())


def _contractor_document(name: str) -> ContractorDocument | None:
    if name in _PLAN_GENERIC or "一覽表" in name:
        return None
    kind = next(((t, p) for pattern, t, p in _PLAN_KINDS if pattern.search(name)), None)
    if kind is None:
        return None
    # 標準「表」是格式，引用時常省略：「假設工程品質管理標準」
    aliases = [name[:-1]] if kind[0] == "檢驗標準" and name.endswith("表") else []
    return ContractorDocument(name, kind[0], kind[1], aliases)


def plan_rows(documents: list[ContractorDocument]) -> list[tuple]:
    counters: dict[str, int] = {}
    rows = []
    for d in documents:
        counters[d.prefix] = counters.get(d.prefix, 0) + 1
        number = f"XS-{d.prefix}-{counters[d.prefix]:02d}"
        note = f"{PLAN_NOTE}；計畫書註明：{d.remark}" if d.remark else PLAN_NOTE
        rows.append((number, d.name, d.doc_type, PLAN_REVISION, PLAN_EFFECTIVE, None, "現行", None, None,
                     "、".join(d.aliases) or None, note))
    return rows


def font(**kw):
    return Font(name=FONT, size=kw.pop("size", 11), **kw)


def build(path: Path, demo: bool = False) -> None:
    title = "企業內部文件清單（示範・假資料）" if demo else "企業內部文件清單（範本）"
    notice = "這是虛構的「示範營造股份有限公司」的假資料，只用來試用系統，不可作為查核依據。" if demo else None
    _save(path, title, notice, DEMO_ROWS if demo else None)


def build_from_quality_plan(plan: Path, path: Path) -> int:
    """從整體品質計畫產生清單。名稱是真的，編號、版次、生效日是假的。回傳文件數。"""
    rows = plan_rows(contractor_documents(plan))
    notice = (f"文件名稱取自「{plan.name}」列出的承攬廠商自有文件；計畫書沒有寫文件編號、版次與生效日，"
              "這三欄是假資料，狀態一律填「現行」。只用來試用系統，不可作為查核依據。")
    _save(path, "企業內部文件清單（名稱取自整體品質計畫・編號版次為假資料）", notice, rows)
    return len(rows)


def _save(path: Path, title: str, notice: str | None, rows: list[tuple] | None) -> None:
    wb = Workbook()
    _guide(wb.active, title, notice)
    ws = wb.create_sheet(SHEET_NAME)
    _options(wb.create_sheet("選項"))
    _document_sheet(ws, rows)
    wb.active = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _guide(guide, title: str, notice: str | None) -> None:
    guide.title = "說明"
    guide.sheet_view.showGridLines = False
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 90

    demo = notice is not None
    rows = [(title, None)]
    if demo:
        rows.append(("注意", notice))
    else:
        rows.append((None, None))
    rows += [
        ("用途", "提供給「工程法規符合性檢查平台」比對工程文件裡引用的內部文件（品質手冊、程序書、作業標準、公司版規範、業主特訂條款等）。"),
        ("要填什麼", "只需要清單，不需要文件全文。一份文件一列，填在「文件清單」工作表。"),
        ("怎麼填", "淺黃色標題的欄位必填，其餘選填。「類型」與「狀態」請用下拉選單。日期請填成日期格式（例：2025/3/1）。"),
        ("範例列", "「文件清單」第 2 列（灰底）是格式範例，填寫時請整列刪除；匯入時備註含「範例列」的列會自動略過。"),
        ("已有文件管制一覽表", "若公司已有 ISO 文件管制一覽表，可直接提供原檔，不必重抄。請一併告知各欄位對應到本範本的哪一欄。"),
        ("怎麼匯入", "租戶管理員在系統「總覽」的「企業內部文件」上傳本檔。匯入會整份取代舊清單；任何一列有錯，整份不會匯入，並列出錯在哪一列。"),
        ("誰來維護", "建議由品保／文管單位維護。每次改版或作廢都要重新匯入，否則系統會把作廢的文件判為「現行有效」。"),
        ("機密性", "本清單只含文件名稱與版次等目錄資訊，但仍屬公司資料，提供前請依公司規定取得同意。"),
        (None, None),
        ("欄位說明", None),
    ]
    for r, (label, text) in enumerate(rows, start=1):
        a, b = guide.cell(r, 1, label), guide.cell(r, 2, text)
        a.font = font(bold=True, color=NAVY)
        b.font = font(bold=demo and r == 2, color="C00000" if demo and r == 2 else None)
        b.alignment = Alignment(wrap_text=True, vertical="top")
        a.alignment = Alignment(vertical="top")
    guide["A1"].font = font(bold=True, size=16, color=NAVY)
    r = len(rows)
    guide.cell(r, 1).font = font(bold=True, size=13, color=NAVY)

    r += 1
    for title, required, _, desc, _ in COLUMNS:
        a = guide.cell(r, 1, title + ("（必填）" if required else ""))
        a.font = font(bold=required)
        if required:
            a.fill = REQUIRED_FILL
        b = guide.cell(r, 2, desc)
        b.font = font()
        b.alignment = Alignment(wrap_text=True)
        a.border = b.border = BORDER
        r += 1

    r += 1
    guide.cell(r, 1, "狀態對應").font = font(bold=True, size=13, color=NAVY)
    r += 1
    meanings = {
        "現行": "系統判為「現行有效」",
        "已修訂": "系統判為「已修正」：仍有效，但引用的版次可能過舊，需要人工確認",
        "作廢": "系統判為「已廢止」：不可再引用，報告會標示",
    }
    for label in STATUS_MAP:
        guide.cell(r, 1, label).font = font()
        guide.cell(r, 2, meanings[label]).font = font()
        guide.cell(r, 1).border = guide.cell(r, 2).border = BORDER
        r += 1


def _options(opts) -> None:
    opts["A1"], opts["B1"] = "類型", "狀態"
    for c in ("A1", "B1"):
        opts[c].font = font(bold=True, color="FFFFFF")
        opts[c].fill = PatternFill("solid", fgColor=NAVY)
    for i, t in enumerate(DOCUMENT_TYPES, start=2):
        opts.cell(i, 1, t).font = font()
    for i, s in enumerate(STATUS_MAP, start=2):
        opts.cell(i, 2, s).font = font()
    opts.column_dimensions["A"].width = 18
    opts.column_dimensions["B"].width = 10


def _document_sheet(ws, rows: list[tuple] | None) -> None:
    demo = rows is not None
    ws.freeze_panes = "A2"
    for col, (title, required, width, desc, _) in enumerate(COLUMNS, start=1):
        head = ws.cell(1, col, title + (" *" if required else ""))
        head.font = font(bold=True, color=NAVY if required else "FFFFFF")
        head.fill = REQUIRED_FILL if required else PatternFill("solid", fgColor=NAVY)
        head.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        head.border = BORDER
        head.comment = Comment(desc, "範本")
        ws.column_dimensions[head.column_letter].width = width
    ws.row_dimensions[1].height = 30

    data = rows if demo else [tuple(example for *_, example in COLUMNS)]
    for r, values in enumerate(data, start=2):
        for col, value in enumerate(values, start=1):
            cell = ws.cell(r, col, value if value != "" else None)
            cell.border = BORDER
            if demo:
                cell.font = font()
            else:
                cell.font = font(italic=True, color="595959")
                cell.fill = EXAMPLE_FILL
            if isinstance(value, date):
                cell.number_format = "yyyy/mm/dd"

    for row in range(len(data) + 2, LAST_ROW + 1):
        for col, (title, *_rest) in enumerate(COLUMNS, start=1):
            c = ws.cell(row, col)
            c.font = font()
            if title in ("生效日", "最後修訂日"):
                c.number_format = "yyyy/mm/dd"
    if demo:
        ws.sheet_properties.tabColor = DEMO_FILL.fgColor.rgb[-6:]
    last_col = ws.cell(1, len(COLUMNS)).column_letter
    ws.auto_filter.ref = f"A1:{last_col}{LAST_ROW}"

    validations = [
        (DataValidation(type="list", formula1=f"=選項!$A$2:$A${len(DOCUMENT_TYPES) + 1}", allow_blank=True,
                        showErrorMessage=True, errorTitle="類型", error="請從下拉選單選擇類型。"), "C"),
        (DataValidation(type="list", formula1=f"=選項!$B$2:$B${len(STATUS_MAP) + 1}", allow_blank=True,
                        showErrorMessage=True, errorTitle="狀態", error="狀態只能是：現行、已修訂、作廢。"), "G"),
    ]
    for dv, column in validations:
        ws.add_data_validation(dv)
        dv.add(f"{column}2:{column}{LAST_ROW}")
    date_dv = DataValidation(type="date", operator="greaterThan", formula1="DATE(1900,1,1)", allow_blank=True,
                             showErrorMessage=True, errorTitle="日期", error="請輸入日期，例如 2025/3/1。")
    ws.add_data_validation(date_dv)
    date_dv.add(f"E2:F{LAST_ROW}")


def main() -> int:
    parser = argparse.ArgumentParser(description="產生企業內部文件清單範本或示範清單")
    parser.add_argument("--demo", action="store_true", help="產生填好假資料的示範清單")
    parser.add_argument("--from-quality-plan", type=Path, metavar="DOCX",
                        help="從整體品質計畫抽出承攬廠商自有文件，產生清單（編號、版次為假資料）")
    args = parser.parse_args()
    if args.from_quality_plan:
        count = build_from_quality_plan(args.from_quality_plan, XIUSHAN_PATH)
        print(f"已產生：{XIUSHAN_PATH}（{count} 份文件）")
        return 0
    path = DEMO_PATH if args.demo else TEMPLATE_PATH
    build(path, demo=args.demo)
    print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
