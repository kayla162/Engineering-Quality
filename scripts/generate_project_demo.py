"""產生工項檢核表的示範專案文件（全部是假資料），放在 data/samples/project_demo/。

    python scripts/generate_project_demo.py

四份文件，掛到同一個專案、分別設成對應的角色，就能走完檢核表的所有結果：

    標單_示範.xlsx        角色：標單       6 個工項
    施工規範_示範.pdf      角色：施工規範   4 章，其中 03110、03210 列出多種工法
    契約圖_示範.pdf        角色：契約圖     5 張圖，標題欄有圖號與圖名
    需求書_示範.txt        角色：其他       指定模板採系統模板，沒提鋼筋續接方式

預期結果（docs 與測試以此為準）：
    普通模板        OK                       相關圖 S-02，工法：系統模板（需求書指定）
    鋼筋            請檢討使用何種工法         相關圖 S-03，契約文件沒有指定續接方式
    預拌混凝土       標單有，契約圖沒有         沒有圖名提到混凝土
    施工測量、安全衛生 不判斷契約圖              01 類一般要求本來就不畫在圖上
    景觀植栽配置圖（A-08） 契約圖有、標單沒有    專案層級，列在檢核表下方

圖面是文字示意，不是真實圖說；真實契約圖多半是 CAD 匯出或掃描檔，尚未驗證。
"""

import sys
from pathlib import Path

import pymupdf
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples" / "project_demo"

BOQ_HEADER = ["項 次", "項  目  及  說  明", "單 位", "數 量", "單 價", "複 價", "編碼(備註)"]
BOQ_ROWS = [
    ["示範市政府（假資料）", "", "", "", "", "", ""],
    ["詳細價目表[契約]", "", "", "", "", "", ""],
    BOQ_HEADER,
    ["壹", "發包工程費", "", "", "", "", ""],
    ["壹.一", "建築工程", "", "", "", "", ""],
    ["壹.一.1.1.1", "施工測量，基地測量及鑑界費", "式", 1, 100000, 100000, "0172500004"],
    ["壹.一.1.1.2", "施工安全衛生及管理，安全警示設施", "式", 1, 250000, 250000, "0152300004"],
    ["壹.一.1.2.1", "普通模板，普通模板含組立", "M2", 959, 500, 479500, "0311010002"],
    ["壹.一.1.2.2", "鋼筋，SD420W 含加工及組立", "T", 85, 32000, 2720000, "0321010003"],
    ["壹.一.1.2.3", "預拌混凝土，210kgf/cm2", "M3", 420, 2600, 1092000, "0331000004"],
    ["壹.一.1.3.1", "屋頂防水，PU防水塗膜", "M2", 300, 900, 270000, "0713200002"],
]

SPEC_HEADER = "{group} {code}-{page} V{version} 2020/08/19"
SPEC_CHAPTERS = [
    ("01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審 依監造單位規定辦理。"),
    ("03110", "場鑄結構混凝土用模板", "6.0",
     "1.4 相關準則 (1) 營造安全衛生設施標準 (2) CNS 3090 預拌混凝土 1.5 資料送審 "
     "3.2 模板組立 承包商得採用下列工法之一：(1) 鋼模 (2) 木模 (3) 系統模板。3.3 拆模 依結構強度辦理。"),
    ("03210", "鋼筋", "5.0",
     "1.4 相關準則 (1) CNS 560 鋼筋混凝土用鋼筋 1.5 資料送審 "
     "3.4 鋼筋續接 得採用下列方法之一：(1) 搭接 (2) 續接器 (3) 銲接。3.5 保護層 依設計圖辦理。"),
    ("03310", "結構用混凝土", "8.0", "1.4 相關準則 (1) CNS 3090 預拌混凝土 (2) CNS 1232 混凝土圓柱試體抗壓強度檢驗法 1.5 資料送審"),
]

DRAWINGS = [
    ("S-01", "結構平面圖"),
    ("S-02", "模板組立詳圖"),
    ("S-03", "鋼筋續接詳圖"),
    ("A-05", "屋頂防水詳圖"),
    ("A-08", "景觀植栽配置圖"),
]

REQUIREMENTS = """需求書（示範・假資料）

一、工程概要
本工程為示範用的假資料，用來說明系統怎麼從契約文件找出指定的工法。

二、施工要求
1. 地下室外牆及各樓層樓板模板採系統模板施作，以提高轉用次數。
2. 混凝土澆置前應會同監造單位檢查。
3. 鋼筋加工及組立依施工規範辦理。
"""


def build_boq(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "契約詳細表"
    for row in BOQ_ROWS:
        sheet.append(row)
    book.save(path)


def _textbox_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=10, fontname="china-t")
        document.save(str(path))
    finally:
        document.close()


def build_spec(path: Path) -> None:
    pages = []
    for code, title, version, body in SPEC_CHAPTERS:
        header = SPEC_HEADER.format(group=code, code=code, page=1, version=version)
        pages.append("\n".join([header, f"第{code} 章V{version} {title}", body]))
    _textbox_pdf(path, pages)


def build_drawings(path: Path) -> None:
    pages = []
    for number, title in DRAWINGS:
        pages.append(
            "\n".join(
                [
                    "（示範圖面，非真實圖說）",
                    "",
                    f"[{title}]",
                    "",
                    "工程名稱：示範工程（假資料）",
                    f"圖號：{number}",
                    f"圖名：{title}",
                    "比例：1/50",
                ]
            )
        )
    _textbox_pdf(path, pages)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    build_boq(OUT / "標單_示範.xlsx")
    build_spec(OUT / "施工規範_示範.pdf")
    build_drawings(OUT / "契約圖_示範.pdf")
    (OUT / "需求書_示範.txt").write_text(REQUIREMENTS, encoding="utf-8")
    for path in sorted(OUT.iterdir()):
        print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
