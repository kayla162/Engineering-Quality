"""產生示範用的工程文件（DOCX / TXT），放在 data/samples/。

    python scripts/generate_samples.py

文件內容刻意涵蓋六種比對結果，方便驗收整條流程：
  政府採購法              -> ACTIVE
  CNS 3090                -> POSSIBLE_MATCH（付費標準無法確認最新版）
  混凝土結構施工規範      -> AMENDED（疑似，名稱與官方全名顛倒）
  營建剩餘土石方處理辦法  -> NOT_FOUND（假資料庫裡沒有）
  勞工安全衛生法          -> REPEALED（已更名）
"""

import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "samples"

TITLE = "○○工程 整體品質計畫（範例）"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "一、計畫依據",
        [
            "本計畫依政府採購法第70條及政府採購法施行細則相關規定辦理，"
            "並參照公共工程施工品質管理作業要點訂定。",
            "施工安全管理依職業安全衛生法及職業安全衛生設施規則辦理；"
            "本工程並援引勞工安全衛生法之相關規定作為歷史沿革參考。",
            "營建剩餘土石方之處理，依營建剩餘土石方處理辦法辦理。",
        ],
    ),
    (
        "二、設計與施工規範",
        [
            "結構設計依建築技術規則建築構造編與建築物耐震設計規範及解說辦理。",
            "混凝土施工依混凝土結構施工規範辦理，並符合公共工程施工綱要規範第03050章之要求。",
            "水土保持相關工項依水土保持技術規範辦理。",
        ],
    ),
    (
        "三、材料檢驗標準",
        [
            "預拌混凝土應符合 CNS 3090 之規定，抗壓強度試驗依 ASTM C39 辦理。",
            "鋼筋材質應符合 CNS 560 規定，粒料應符合 CNS 1240 規定。",
            "水泥材料應符合 CNS 61 之規定。",
        ],
    ),
    (
        "四、品質管理系統",
        [
            "承包商應建立符合 ISO 9001 之品質管理系統，"
            "並依 ISO 45001 建立職業安全衛生管理系統。",
            "環境管理依 ISO 14001 辦理，環境影響評估依環境影響評估法規定辦理。",
        ],
    ),
]

# 表格：法規引用也常常出現在表格裡，用來驗證表格解析
TABLE_ROWS: list[tuple[str, str, str]] = [
    ("項次", "檢驗項目", "依據規範"),
    ("1", "混凝土抗壓強度", "CNS 3090、ASTM C39"),
    ("2", "鋼筋拉伸試驗", "CNS 560"),
    ("3", "施工安全查核", "營造安全衛生設施標準"),
    ("4", "採購作業查核", "採購法"),
]


def build_docx(path: Path) -> None:
    document = Document()
    document.add_heading(TITLE, level=0)

    for heading, paragraphs in SECTIONS:
        document.add_heading(heading, level=1)
        for text in paragraphs:
            document.add_paragraph(text)

    document.add_heading("五、檢驗項目對照表", level=1)
    table = document.add_table(rows=0, cols=3)
    table.style = "Table Grid"
    for row in TABLE_ROWS:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value

    document.save(str(path))


def build_txt(path: Path) -> None:
    lines = [TITLE, ""]
    for heading, paragraphs in SECTIONS:
        lines.append(heading)
        lines.extend(paragraphs)
        lines.append("")
    lines.append("五、檢驗項目對照表")
    lines.extend(" | ".join(row) for row in TABLE_ROWS)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    docx_path = OUTPUT_DIR / "sample_quality_plan.docx"
    txt_path = OUTPUT_DIR / "sample_quality_plan.txt"
    build_docx(docx_path)
    build_txt(txt_path)
    print(f"已產生：{docx_path}")
    print(f"已產生：{txt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
