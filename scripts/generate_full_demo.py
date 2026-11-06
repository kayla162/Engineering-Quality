"""產生「完整示範專案」的文件（全部是假資料），放在 data/samples/full_demo/。

    python scripts/generate_full_demo.py

一個專案就能看到系統每一項功能（比 project_demo 的四份文件完整；project_demo 留著當測試的固定樣本）：

    標單_完整示範.xlsx          標單       16 個工項，分建築、結構、機電、間接費
    施工規範_完整示範.pdf        施工規範   13 章：工法選項、可檢查的數值、機電測試小節
    契約書_完整示範.docx         契約       Word，條號寫在段落裡（「第11條　履約品管」）→ 契約欄引到條
    需求書_完整示範.txt          其他       指定模板採系統模板，沒指定鋼筋續接
    建築結構圖_完整示範.pdf      契約圖     CAD 版面（標籤與值分開），第一張是圖號索引表
    水電圖_完整示範.pdf          契約圖     用印後掃描的版面（整頁是圖片），要 OCR → 標示「OCR」
    整體品質計畫_完整示範.docx    品質計畫   三張品質管理標準表，鋼筋、混凝土兩張故意漏寫幾個規範值

會看到的結果：
    - 普通模板 OK（需求書指定系統模板）；鋼筋「請檢討使用何種工法」；預拌混凝土「標單有，契約圖沒有」
    - 開關箱（KW-MP PANEL）對到水電圖的電氣單線圖（開關箱畫在單線圖上）
    - 景觀植栽配置圖「契約圖有、標單沒有」
    - 法規雙重規範提醒：女兒牆、樓梯扶手、防火門、昇降機、透水鋪面、綠建材六條都觸發
    - 契約欄「第11條 履約品管」；功能運轉檢測：昇降機、給水、配電盤取自規範，無熔線斷路器用通用範本
    - 品質計畫審查：鋼筋表漏 40D、±6mm；混凝土表漏 CNS 1232；假設工程表本案規範沒有對應章

所有文件都印「示範（假資料）」；業主、設計單位、人名都是虛構的。
"""

import re
import sys
from pathlib import Path

import pymupdf
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples" / "full_demo"
FONT = "china-t"
PROJECT = "示範活動中心新建工程（假資料）"
MARK = "示範（假資料），非正式文件"
WIDTH, HEIGHT = 1191, 842

BOQ_HEADER = ["項 次", "項  目  及  說  明", "單 位", "數 量", "單 價", "複 價", "編碼(備註)"]
BOQ_ROWS = [
    ["示範市政府（假資料）", "", "", "", "", "", ""],
    ["詳細價目表[契約]", "", "", "", "", "", ""],
    BOQ_HEADER,
    ["壹", "發包工程費", "", "", "", "", ""],
    ["壹.一", "直接工程費", "", "", "", "", ""],
    ["壹.一.1", "建築工程", "", "", "", "", ""],
    ["壹.一.1.1", "一般需求", "", "", "", "", ""],
    ["壹.一.1.1.1", "施工測量，基地測量及鑑界費", "式", 1, 100000, 100000, "0172500004"],
    ["壹.一.1.1.2", "施工安全衛生及管理，安全警示設施", "式", 1, 250000, 250000, "0152300004"],
    ["壹.一.1.2", "結構體工程", "", "", "", "", ""],
    ["壹.一.1.2.1", "普通模板，普通模板含組立", "M2", 959, 500, 479500, "0311010002"],
    ["壹.一.1.2.2", "鋼筋，SD420W 含加工及組立", "T", 85, 32000, 2720000, "0321010003"],
    ["壹.一.1.2.3", "預拌混凝土，280kgf/cm2", "M3", 420, 2800, 1176000, "0331000004"],
    ["壹.一.1.3", "裝修工程", "", "", "", "", ""],
    ["壹.一.1.3.1", "女兒牆，RC 造 H=1.2m", "M", 120, 3500, 420000, "0331000005"],
    ["壹.一.1.3.2", "樓梯扶手，不銹鋼 φ40mm", "M", 60, 2500, 150000, "0552000002"],
    ["壹.一.1.3.3", "防火門，甲種防火鐵門 W90xH210", "樘", 8, 28000, 224000, "0811000003"],
    ["壹.一.1.3.4", "透水鋪面，植草磚", "M2", 300, 900, 270000, "0278000002"],
    ["壹.一.1.3.5", "地坪磁磚，綠建材標章 30x30cm", "M2", 650, 1200, 780000, "0931000001"],
    ["壹.一.2", "機電工程", "", "", "", "", ""],
    ["壹.一.2.1", "開關箱設備工程", "", "", "", "", ""],
    ["壹.一.2.1.1", "KW-MP PANEL", "面", 1, 180000, 180000, "1647000001"],
    ["壹.一.2.1.2", "L-1F PANEL", "面", 2, 45000, 90000, "1647000002"],
    ["壹.一.2.2", "電力設備工程", "", "", "", "", ""],
    ["壹.一.2.2.1", "無熔線斷路器，3P 100AF", "只", 12, 3500, 42000, "1641100001"],
    ["壹.一.2.3", "給水設備工程", "", "", "", "", ""],
    ["壹.一.2.3.1", "給水管，不銹鋼管 25mm", "M", 240, 650, 156000, "1514000001"],
    ["壹.一.2.4", "昇降設備工程", "", "", "", "", ""],
    ["壹.一.2.4.1", "昇降機，電動乘客電梯 11 人 60m/min", "台", 1, 1800000, 1800000, "1421000001"],
    ["壹.二", "間接工程費", "", "", "", "", ""],
    ["壹.二.1", "品管費，品質管理作業費", "式", 1, 300000, 300000, ""],
]

SPEC_HEADER = "{code} {code}-1 V{version} 2020/08/19"
#: (章碼, 章名, 版次, 內容)。「2. 產品」「3. 施工」裡有數值的句子會變成品質管理標準表的列
SPEC_CHAPTERS = [
    ("01725", "施工測量", "3.0", "1. 通則 1.1 本章概要 說明施工測量之規定。 1.4 相關準則 (1) 測量法 "
     "3. 施工 3.1 測量 3.1.1 控制點檢測 控制點應於開工前會同監造單位檢測，閉合差不得大於 1/5000。 4. 計量與計價 依契約。"),
    ("01523", "安全衛生", "2.0", "1. 通則 1.4 相關準則 (1) 職業安全衛生法 (2) 營造安全衛生設施標準 "
     "3. 施工 3.1 安全設施 3.1.1 護欄 開口部分應設置高度 90cm 以上之護欄。 4. 計量與計價 依契約。"),
    ("03110", "場鑄結構混凝土用模板", "6.0",
     "1. 通則 1.4 相關準則 (1) 營造安全衛生設施標準 2. 產品 2.1 材料 2.1.1 合板 模板用合板厚度不得小於 12mm。 "
     "3. 施工 3.2 模板組立 3.2.1 工法 承包商得採用下列工法之一：(1) 鋼模 (2) 木模 (3) 系統模板。 "
     "3.2.2 許可差 模板垂直度許可差為 ±6mm。 3.3 拆模 3.3.1 拆模時間 樓版底模應於混凝土澆置 14 天後始得拆除。 "
     "4. 計量與計價 依契約。"),
    ("03210", "鋼筋", "5.0",
     "1. 通則 1.4 相關準則 (1) CNS 560 鋼筋混凝土用鋼筋 2. 產品 2.1 材料 2.1.1 鋼筋 鋼筋應符合 CNS 560 SD420W 之規定。 "
     "3. 施工 3.3 鋼筋組立 3.3.1 保護層 鋼筋保護層許可差為 ±6mm。 3.4 鋼筋續接 3.4.1 續接方法 得採用下列方法之一："
     "(1) 搭接 (2) 續接器 (3) 銲接。 3.4.2 搭接長度 搭接長度不得小於 40D。 4. 計量與計價 依契約。"),
    ("03310", "結構用混凝土", "8.0",
     "1. 通則 1.4 相關準則 (1) CNS 3090 預拌混凝土 (2) CNS 1232 混凝土圓柱試體抗壓強度檢驗法 2. 產品 2.1 材料 "
     "2.1.1 預拌混凝土 預拌混凝土應符合 CNS 3090 之規定。 3. 施工 3.5 試驗 3.5.1 抗壓試驗 圓柱試體依 CNS 1232 試驗，"
     "每 100m3 取樣試驗 1 組，28 天抗壓強度不得低於設計強度。 3.5.2 坍度 坍度許可差為 ±2.5cm。 "
     "3.6 養護 3.6.1 濕治養護 混凝土澆置後應連續濕治養護 7 天以上。 4. 計量與計價 依契約。"),
    ("05520", "扶手及欄杆", "3.0",
     "1. 通則 1.4 相關準則 (1) 建築技術規則 (2) 建築物無障礙設施設計規範 2. 產品 2.1 材料 2.1.1 管徑 扶手管徑 2.8cm 至 4cm。 "
     "3. 施工 3.1 安裝 3.1.1 高度 扶手上緣高度 75cm，樓梯兩端水平延伸 30cm 以上。 4. 計量與計價 依契約。"),
    ("08110", "鋼門及門框", "4.0",
     "1. 通則 1.4 相關準則 (1) 建築技術規則 2. 產品 2.1 防火門 2.1.1 防火時效 防火時效 1 小時以上，附自動關門器。 "
     "3. 施工 3.1 安裝 3.1.1 垂直度 門框垂直度許可差為 ±3mm。 4. 計量與計價 依契約。"),
    ("02780", "單元鋪面", "2.0",
     "1. 通則 1.4 相關準則 (1) 建築技術規則 2. 產品 2.1 植草磚 2.1.1 強度 抗壓強度 210kgf/cm2 以上。 "
     "3. 施工 3.1 鋪設 3.1.1 基層 基層級配厚度 15cm 以上，壓實度 95% 以上。 4. 計量與計價 依契約。"),
    ("09310", "磁磚", "3.0",
     "1. 通則 1.4 相關準則 (1) 綠建材標章 2. 產品 2.1 地磚 2.1.1 規格 應取得綠建材標章，吸水率 3% 以下。 "
     "3. 施工 3.1 鋪貼 3.1.1 平整度 平整度許可差為 ±3mm。 4. 計量與計價 依契約。"),
    ("16470", "配電盤", "4.0",
     "1. 通則 1.4 相關準則 (1) 用戶用電設備裝置規則 2. 產品 2.1 盤體 2.1.1 鋼板 鋼板厚度 1.6mm 以上。 "
     "3. 施工 3.1 安裝 3.1.1 固定 盤體應水平固定。 3.2 現場測試 3.2.1 絕緣試驗 絕緣電阻應在 1MΩ 以上。 "
     "3.2.2 動作試驗 盤內各迴路應做動作測試。 4. 計量與計價 依契約。"),
    ("16411", "無熔線斷路器", "3.0",
     "1. 通則 1.4 相關準則 (1) 用戶用電設備裝置規則 2. 產品 2.1 規格 2.1.1 啟斷容量 啟斷容量依設計圖說。 "
     "3. 施工 3.1 安裝 3.1.1 安裝 依製造廠說明書安裝。 4. 計量與計價 依契約。"),
    ("15140", "給水管路系統", "5.0",
     "1. 通則 1.4 相關準則 (1) 自來水用戶用水設備標準 2. 產品 2.1 管材 2.1.1 不銹鋼管 不銹鋼管管厚 1.2mm 以上。 "
     "3. 施工 3.2 安裝 3.2.1 吊架 管線應以吊架固定，間距 2m 以內。 3.3 檢驗 3.3.1 水壓試驗 "
     "以 10kgf/cm2 保持 60 分鐘無滲漏為合格。 4. 計量與計價 依契約。"),
    ("14210", "電動升降機", "6.0",
     "1. 通則 1.4 相關準則 (1) 建築技術規則建築設備編 (2) 建築物無障礙設施設計規範 2. 產品 2.1 機廂 "
     "2.1.1 尺寸 機廂深度 135cm 以上。 3. 施工 3.3 測試 3.3.1 著樓試驗 著樓許可差在 ±5mm 以內。 "
     "3.3.2 安全裝置試驗 各安全裝置應動作正常。 3.3.3 載重試驗 以額定載重 110% 運轉。 4. 計量與計價 依契約。"),
]

#: 建築結構圖（CAD 版面）：(圖號, 圖名)。故意沒有混凝土的圖、多一張景觀植栽配置圖（標單沒有植栽）
CAD_SHEETS = [
    ("A0-01", "建築圖號索引表"),
    ("A2-01", "一層平面圖"),
    ("A3-01", "女兒牆詳圖"),
    ("A4-01", "地坪磁磚詳圖"),
    ("A5-01", "樓梯扶手詳圖"),
    ("A6-01", "防火門詳圖"),
    ("A7-01", "透水鋪面詳圖"),
    ("A8-01", "景觀植栽配置圖"),
    ("S-02", "模板組立詳圖"),
    ("S-03", "鋼筋續接詳圖"),
]
#: 水電圖（掃描版面）：(圖號, 圖名分行)
SCANNED_SHEETS = [
    ("E-01", ["電氣單線圖", "負載表(1)"]),
    ("E-02", ["電力平面圖"]),
    ("P-01", ["給水系統圖"]),
    ("L-01", ["昇降機平面詳圖"]),
]

CONTRACT = [
    ("第1條　契約文件及效力", [
        "(一)契約包括下列文件：招標文件及其變更或補充、投標文件、決標文件、契約本文、附件。",
        "(二)本契約為示範用假資料，非任何機關之正式契約。",
        "(三)本契約未規定者，依政府採購法及其主管機關訂定之規定辦理。",
    ]),
    ("第2條　履約標的", [
        "(一)廠商應給付之標的：示範活動中心新建工程，包括結構體、女兒牆、樓梯扶手、防火門、透水鋪面及機電設備。",
        "(二)昇降機應符合無障礙昇降機之規定。",
    ]),
    ("第7條　履約期限", ["(一)廠商應於開工之日起 300 日曆天內竣工。"]),
    ("第11條　履約品管", [
        "(一)廠商應對模板、鋼筋及混凝土施工品質負責，並依核定之品質計畫執行。",
        "(二)廠商應依「公共工程施工品質管理作業要點」辦理三級品管。",
        "品質計畫： 一、 廠商應於開工前提送品質計畫，鋼筋續接方式應於施工計畫載明。",
        "材料檢驗： 一、 預拌混凝土進場時應會同監造單位取樣。",
    ]),
    ("第12條　機電設備", [
        "(一)開關箱及給水設備完成後，應會同監造單位辦理功能運轉測試。",
        "(二)昇降機應取得使用許可後始得驗收。",
    ]),
]

REQUIREMENTS = """需求書（完整示範・假資料）

一、工程概要
示範活動中心新建工程，地上三層，本文件為示範用假資料。

二、施工要求
1. 各樓層樓板及牆模板採系統模板施作，以提高轉用次數。
2. 混凝土澆置前應會同監造單位檢查。
3. 鋼筋加工及組立依施工規範辦理。
4. 屋頂女兒牆高度 1.2m，樓梯扶手採不銹鋼管。
"""

#: 品質計畫的品質管理標準表：(表名, [(管理項目, 管理標準)])。鋼筋漏 40D 與 ±6mm、混凝土漏 CNS 1232
PLAN_TABLES = [
    ("鋼筋品質管理標準表", [
        ("鋼筋材料", "符合 CNS 560 SD420W"),
        ("鋼筋續接", "依施工計畫"),
        ("保護層", "依設計圖說"),
    ]),
    ("混凝土品質管理標準表", [
        ("預拌混凝土", "符合 CNS 3090"),
        ("坍度", "許可差 ±2.5cm"),
        ("養護", "濕治養護 7 天以上"),
    ]),
    ("假設工程品質管理標準表", [
        ("施工架", "依營造安全衛生設施標準"),
    ]),
]


def build_boq(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "契約詳細表"
    for row in BOQ_ROWS:
        sheet.append(row)
    book.save(path)


def build_spec(path: Path) -> None:
    document = pymupdf.open()
    for code, title, version, body in SPEC_CHAPTERS:
        page = document.new_page()
        # 真實規範每個編號（「3.2.1」「3. 施工」）都在新的一行
        lines = re.sub(r"\s+(?=(?:[1-4]\.\s|\d\.\d))", "\n", body)
        text = "\n".join([SPEC_HEADER.format(code=code, version=version), f"第{code} 章V{version} {title}", lines])
        page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=10, fontname=FONT)
    document.save(str(path))
    document.close()


def build_contract(path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_heading(f"{PROJECT} 工程採購契約（{MARK}）", level=0)
    for article, paragraphs in CONTRACT:
        document.add_paragraph(article)
        for text in paragraphs:
            document.add_paragraph(text)
    document.save(path)


def build_quality_plan(path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_heading(f"{PROJECT} 整體品質計畫（{MARK}）", level=0)
    document.add_heading("五、品質管理標準", level=1)
    for title, rows in PLAN_TABLES:
        document.add_paragraph(title)
        table = document.add_table(rows=1, cols=5)
        for cell, text in zip(table.rows[0].cells, ("管理項目", "管理標準", "檢查時機", "檢查方法", "檢查頻率")):
            cell.text = text
        for item, standard in rows:
            cells = table.add_row().cells
            for cell, text in zip(cells, (item, standard, "施工中", "目視、量測", "每批")):
                cell.text = text
    document.save(path)


def build_cad_drawings(path: Path) -> None:
    """CAD 匯出的版面：右下角標題欄，標籤與值是分開的文字物件；第一張是圖號索引表。"""
    document = pymupdf.open()
    for sheet_no, title in CAD_SHEETS:
        page = document.new_page(width=WIDTH, height=HEIGHT)
        page.draw_rect(pymupdf.Rect(20, 20, WIDTH - 20, HEIGHT - 4), width=1)
        if sheet_no.endswith("-01") and "索引" in title:
            page.insert_text((60, 60), "圖號", fontname=FONT, fontsize=9)
            page.insert_text((120, 60), "圖                名", fontname=FONT, fontsize=9)
            for row, (number, name) in enumerate(CAD_SHEETS):
                page.insert_text((60, 80 + 18 * row), number, fontsize=8)
                page.insert_text((120, 80 + 18 * row), name, fontname=FONT, fontsize=8)
        else:
            page.insert_text((400, 380), title, fontname=FONT, fontsize=28)
        page.insert_text((400, 420), MARK, fontname=FONT, fontsize=14, color=(0.8, 0, 0))
        page.draw_rect(pymupdf.Rect(20, 745, WIDTH - 20, HEIGHT - 4), width=0.5)
        for point, text in (
            ((40, 760), "工 程 名 稱"), ((40, 770), "PROJECT"),
            ((363, 760), "圖    名"), ((363, 770), "DRAWING TITLE"),
            ((560, 810), "圖號："), ((560, 818), "DRG. NO."),
            ((860, 760), "設計："), ((860, 790), "比例："),
        ):
            page.insert_text(point, text, fontname=FONT, fontsize=6)
        page.insert_text((40, 790), PROJECT, fontname=FONT, fontsize=9)
        page.insert_text((900, 760), "示範設計（假資料）", fontname=FONT, fontsize=8)
        page.insert_text((383, 790), title, fontname=FONT, fontsize=9)
        page.insert_text((565, 832), sheet_no, fontsize=8)
    document.save(str(path), garbage=3, deflate=True)
    document.close()


def build_scanned_drawings(path: Path) -> None:
    """用印後掃描的版面：右側直條標題欄（圖名在「DRAWING」下面，圖號在最下面「DWG NO.」右邊），
    整頁存成圖片、沒有文字層——讀的時候要 OCR。簽名是虛構的人名。"""
    document = pymupdf.open()
    for sheet_no, rows in SCANNED_SHEETS:
        source = pymupdf.open()
        page = source.new_page(width=WIDTH, height=HEIGHT)
        page.draw_rect(pymupdf.Rect(20, 20, 1040, HEIGHT - 20), width=1)
        page.insert_text((300, 400), "".join(rows), fontname=FONT, fontsize=28)
        page.insert_text((300, 440), MARK, fontname=FONT, fontsize=14, color=(0.8, 0, 0))
        x = 1060
        page.insert_text((x, 470), "業主 CLIENT", fontname=FONT, fontsize=7)
        page.insert_text((x, 480), "示範市政府", fontname=FONT, fontsize=8)
        page.insert_text((x, 530), "圖名", fontname=FONT, fontsize=7)
        page.insert_text((x, 540), "DRAWING", fontsize=6)
        for i, row in enumerate(rows):
            page.insert_text((x, 556 + 13 * i), row, fontname=FONT, fontsize=9)
        page.insert_text((x + 20, 600), "王大明", fontname=FONT, fontsize=10)
        page.insert_text((x, 625), "示範聯合建築師事務所", fontname=FONT, fontsize=8)
        page.insert_text((x + 60, 800), "圖號", fontname=FONT, fontsize=7)
        page.insert_text((x + 60, 810), "DWG NO.", fontsize=5)
        page.insert_text((x + 90, 806), sheet_no, fontsize=10)
        scanned = document.new_page(width=WIDTH, height=HEIGHT)
        scanned.insert_image(scanned.rect, pixmap=page.get_pixmap(dpi=300))
        source.close()
    document.save(str(path), garbage=3, deflate=True)
    document.close()


FILES = {
    "標單_完整示範.xlsx": ("boq", build_boq),
    "施工規範_完整示範.pdf": ("specification", build_spec),
    "契約書_完整示範.docx": ("contract", build_contract),
    "需求書_完整示範.txt": ("other", lambda path: path.write_text(REQUIREMENTS, encoding="utf-8")),
    "建築結構圖_完整示範.pdf": ("drawing", build_cad_drawings),
    "水電圖_完整示範.pdf": ("drawing", build_scanned_drawings),
    "整體品質計畫_完整示範.docx": ("quality_plan", build_quality_plan),
}


def build(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (_role, builder) in FILES.items():
        builder(out / name)
        paths.append(out / name)
    return paths


def main() -> int:
    for path in build():
        print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
