"""產生企業內部文件清單的 Excel：給品保／文管單位填寫的範本，或填好假資料的示範清單。

    python scripts/generate_enterprise_template.py          # 範本
    python scripts/generate_enterprise_template.py --demo   # 示範清單（假資料）

範本輸出到 data/templates/企業內部文件清單範本.xlsx；示範清單輸出到
data/samples/enterprise_documents_demo.xlsx，可以直接匯入系統試用：

    python scripts/import_enterprise_documents.py data/samples/enterprise_documents_demo.xlsx --tenant <租戶名稱>

系統只需要目錄（編號、名稱、版次、狀態），不需要文件全文。類型與狀態的選項
和匯入時的檢查用同一份定義（app/services/enterprise_document_service.py）。
"""

import argparse
import sys
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


def font(**kw):
    return Font(name=FONT, size=kw.pop("size", 11), **kw)


def build(path: Path, demo: bool = False) -> None:
    wb = Workbook()
    _guide(wb.active, demo)
    ws = wb.create_sheet(SHEET_NAME)
    _options(wb.create_sheet("選項"))
    _document_sheet(ws, demo)
    wb.active = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _guide(guide, demo: bool) -> None:
    guide.title = "說明"
    guide.sheet_view.showGridLines = False
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 90

    rows = [("企業內部文件清單（示範・假資料）" if demo else "企業內部文件清單（範本）", None)]
    if demo:
        rows.append(("注意", "這是虛構的「示範營造股份有限公司」的假資料，只用來試用系統，不可作為查核依據。"))
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


def _document_sheet(ws, demo: bool) -> None:
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

    data = DEMO_ROWS if demo else [tuple(example for *_, example in COLUMNS)]
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
    args = parser.parse_args()
    path = DEMO_PATH if args.demo else TEMPLATE_PATH
    build(path, demo=args.demo)
    print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
