"""產生秀山分隊興建工程的**示範契約圖**（假資料）：data/samples/xiushan_contract_drawings_demo.pdf

    python scripts/generate_xiushan_drawings_demo.py

秀山分隊的真實契約圖沒有提供（工程文書/ 裡的兩份圖說是某宿舍統包工程的案子），所以檢核表
階段 2 只能用假的圖目錄跑。圖名照秀山標單的分項編（建築、結構、水電、消防、空調、景觀），
**版面照真實 CAD 匯出圖**（某宿舍統包工程竣工圖）：標題欄的標籤「圖號：」「DRG. NO.」和值是分開的
文字物件、值最後才寫入，第一張是圖號索引表——讀這份 PDF 走的是讀真實圖的同一條路
（app/specs/drawing_reader.py 的位置比對），不是示範專用的捷徑。

每一頁都印著「示範契約圖（假資料）」，設計單位一欄寫「示範」，不冒用任何真實事務所。
圖面中間只有圖名與幾行說明，沒有任何真實圖面內容。
"""

import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples" / "xiushan_contract_drawings_demo.pdf"
FONT = "china-t"
PROJECT = "秀山分隊興建工程"
FAKE_MARK = "示範契約圖（假資料），非本案正式圖說"

#: (圖號, 圖名)。照秀山標單的分項編，刻意沒有電梯與太陽能的圖（標單有這些工項）、
#: 刻意有景觀植栽配置圖（看標單有沒有對應工項）
SHEETS = [
    ("A0-01", "建築圖號索引表"),
    ("A1-01", "建築配置圖"),
    ("A2-01", "一層平面圖"),
    ("A2-02", "二層平面圖"),
    ("A2-03", "三層平面圖"),
    ("A2-04", "屋頂層平面圖"),
    ("A3-01", "立面圖(一)"),
    ("A3-02", "立面圖(二)"),
    ("A4-01", "剖面圖"),
    ("A5-01", "樓梯詳圖"),
    ("A6-01", "門窗詳圖(一)"),
    ("A6-02", "門窗詳圖(二)"),
    ("A7-01", "外牆磁磚詳圖"),
    ("A8-01", "輕隔間配置圖"),
    ("A8-02", "天花板詳圖"),
    ("A8-03", "地坪材料配置圖"),
    ("A9-01", "屋頂防水隔熱詳圖"),
    ("A10-01", "指標配置圖"),
    ("S1-01", "基礎平面圖"),
    ("S1-02", "基樁配置圖"),
    ("S2-01", "柱配筋詳圖"),
    ("S2-02", "梁配筋詳圖"),
    ("S2-03", "版配筋詳圖"),
    ("S3-01", "模板組立詳圖"),
    ("E1-01", "照明平面圖"),
    ("E1-02", "插座平面圖"),
    ("E2-01", "動力幹線昇位圖"),
    ("E3-01", "開關箱單線圖"),
    ("P1-01", "給水系統圖"),
    ("P1-02", "排水系統圖"),
    ("F1-01", "消防設備平面圖"),
    ("M1-01", "空調設備平面圖"),
    ("L1-01", "景觀植栽配置圖"),
]

WIDTH, HEIGHT = 1191, 842  # A3 橫式，和真實圖一樣


def build(path: Path = OUT) -> int:
    doc = pymupdf.open()
    for sheet_no, title in SHEETS:
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.draw_rect(pymupdf.Rect(20, 20, WIDTH - 20, HEIGHT - 4), width=1)
        if sheet_no == "A0-01":
            _index(page)
        else:
            _body(page, title)
        _title_block(page, sheet_no, title)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=3, deflate=True)
    return len(SHEETS)


def _index(page: pymupdf.Page) -> None:
    """圖號索引表：兩欄「圖號｜圖名」，和真實索引表一樣一行一張。"""
    page.insert_text((60, 60), "圖號", fontname=FONT, fontsize=9)
    page.insert_text((120, 60), "圖                名", fontname=FONT, fontsize=9)
    page.insert_text((500, 420), FAKE_MARK, fontname=FONT, fontsize=14, color=(0.8, 0, 0))
    for row, (sheet_no, title) in enumerate(SHEETS):
        y = 80 + 18 * row
        page.insert_text((60, y), sheet_no, fontsize=8)
        page.insert_text((120, y), title, fontname=FONT, fontsize=8)


def _body(page: pymupdf.Page, title: str) -> None:
    page.insert_text((400, 380), title, fontname=FONT, fontsize=28)
    page.insert_text((400, 420), FAKE_MARK, fontname=FONT, fontsize=14, color=(0.8, 0, 0))
    page.insert_text((60, 600), "說明", fontname=FONT, fontsize=9)
    page.insert_text((60, 615), "1.本圖為檢核表功能示範用，圖面內容從略。", fontname=FONT, fontsize=8)


def _title_block(page: pymupdf.Page, sheet_no: str, title: str) -> None:
    """右下角標題欄。標籤先寫、值最後寫，位置照真實竣工圖（值在標籤旁 20～30 pt）。"""
    page.draw_rect(pymupdf.Rect(20, 745, WIDTH - 20, HEIGHT - 4), width=0.5)
    labels = [
        ((40, 760), "工 程 名 稱"), ((40, 770), "PROJECT"),
        ((363, 760), "圖    名"), ((363, 770), "DRAWING TITLE"),
        ((560, 810), "圖號："), ((560, 818), "DRG. NO."),
        ((700, 810), "張數："), ((700, 818), "SHEET NO."),
        ((860, 760), "設計："), ((860, 790), "比例："),
    ]
    for point, text in labels:
        page.insert_text(point, text, fontname=FONT, fontsize=6)
    page.insert_text((40, 790), PROJECT, fontname=FONT, fontsize=9)
    page.insert_text((900, 760), "示範", fontname=FONT, fontsize=8)
    page.insert_text((900, 790), "N.S.", fontsize=7)
    page.insert_text((1000, 790), "示範（假資料）", fontname=FONT, fontsize=8, color=(0.8, 0, 0))
    page.insert_text((383, 790), title, fontname=FONT, fontsize=9)
    page.insert_text((565, 832), sheet_no, fontsize=8)


def main() -> int:
    count = build()
    print(f"已產生：{OUT}（{count} 張圖，假資料）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
