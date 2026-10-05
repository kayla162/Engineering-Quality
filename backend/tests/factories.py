"""測試資料產生器。"""

import uuid
from io import BytesIO

import pymupdf

from docx import Document as DocxDocument
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.matching.normalizer import clean_text
from app.repositories.regulations import RegulationRepository
from app.sources.mock_source import MockRegulationSource

# 測試文件的內容，涵蓋六種比對結果
SAMPLE_PARAGRAPHS = [
    "本計畫依政府採購法第70條及政府採購法施行細則相關規定辦理。",
    "施工安全依職業安全衛生法辦理，早期文件曾引用勞工安全衛生法。",
    "混凝土施工依混凝土結構施工規範辦理。",
    "營建剩餘土石方之處理，依營建剩餘土石方處理辦法辦理。",
    "預拌混凝土應符合 CNS 3090 之規定。",
]
SAMPLE_TABLE = [("項次", "依據規範"), ("1", "採購法")]


def make_docx_bytes() -> bytes:
    """產生一份測試用 DOCX（含標題、段落與表格）。"""
    document = DocxDocument()
    document.add_heading("整體品質計畫（測試）", level=0)
    document.add_heading("一、計畫依據", level=1)
    for text in SAMPLE_PARAGRAPHS:
        document.add_paragraph(text)

    table = document.add_table(rows=0, cols=2)
    for row in SAMPLE_TABLE:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_txt_bytes() -> bytes:
    return "\n".join(SAMPLE_PARAGRAPHS).encode("utf-8")


async def seed_regulations(session: AsyncSession) -> int:
    """把 MockRegulationSource 的假資料寫進法規主檔（等同 scripts/seed_data.py）。"""
    source = MockRegulationSource()
    repo = RegulationRepository(session)
    tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    for record in source._load():  # noqa: SLF001
        detail = await source.get_detail(record["external_id"])
        regulation = await repo.upsert(
            name=detail.name,
            normalized_name=clean_text(detail.name),
            reg_type=detail.type,
            status=detail.status,
            source=detail.source,
            authority=detail.authority,
            effective_date=detail.effective_date,
            last_amended_date=detail.last_amended_date,
            official_url=detail.official_url,
            tenant_id=tenant_id,
        )
        if detail.standard_number:
            await repo.add_aliases(regulation, [detail.standard_number])

    # 別名字典（正規化引擎主要靠它）
    await repo.add_aliases(await repo.get_by_name("政府採購法"), ["採購法"])
    await repo.add_aliases(await repo.get_by_name("職業安全衛生法"), ["職安法"])
    await session.commit()
    return await repo.count()


# 標單的形狀：真實檔案是四張工作表，詳細表有「項次 / 項目及說明 / 單位 / 數量 /
# 單價 / 複價 / 編碼(備註)」，編碼前 5 碼是施工綱要規範章碼（2026-09 查證過）。
SAMPLE_SHEET = "契約詳細表"
SAMPLE_ROWS = [
    ["項 次", "項  目  及  說  明", "單 位", "數 量", "編碼(備註)"],
    ["壹.一.1.1.1", "施工測量，基地測量及鑑界費", "式", 1, "0172500004"],
    ["", "施工中由承商建置，採租用屬臨時設施", "", "", ""],
    ["壹.一.1.2.1", "預拌混凝土應符合 CNS 3090 之規定", "M3", 959, "0331000004"],
]


def make_xlsx_bytes(rows=None, sheet_name=SAMPLE_SHEET, extra_sheet=None) -> bytes:
    """產生測試用 .xlsx（openpyxl，已是專案相依）。"""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name
    for row in rows if rows is not None else SAMPLE_ROWS:
        sheet.append(row)
    if extra_sheet:
        second = book.create_sheet(extra_sheet[0])
        for row in extra_sheet[1]:
            second.append(row)

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def make_xls_bytes(rows=None, sheet_name=SAMPLE_SHEET) -> bytes:
    """產生測試用 .xls（OLE2 舊格式）。

    真實標單就是這個格式——不是 .xlsx，openpyxl 讀不了。
    xlrd 只能讀不能寫，所以這裡用 xlwt 產生；xlwt 只在測試用到，不是專案相依。
    """
    import xlwt

    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet(sheet_name)
    for r, row in enumerate(rows if rows is not None else SAMPLE_ROWS):
        for c, value in enumerate(row):
            sheet.write(r, c, value)

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# 真實標單的表頭（含全形空白，比對前要正規化）
BOQ_HEADER = ["項 次", "項  目  及  說  明", "單 位", "數 量", "單 價", "複 價", "編碼(備註)"]
BOQ_ROWS = [
    ["新北市政府消防局", "", "", "", "", "", ""],
    ["詳細價目表[契約]", "", "", "", "", "", ""],
    BOQ_HEADER,
    ["壹", "發包工程費", "", "", "", "", ""],
    ["壹.一.1.1.1", "施工測量，基地測量及鑑界費", "式", 1, 100000, 100000, "0172500004,*"],
    ["", "施工中由承商建置，採租用", "", "", "", "", ""],
    ["壹.一.1.2.1", "普通模板，普通模板含組立", "M2", 959, 500, 479500, "0311010002"],
    ["壹.一.1.3.1", "天花板，長條鋁企口天花板", "M2", 120, 800, 96000, ""],
]


def make_boq_bytes(rows=None, header_sheet="契約詳細表", suffix=".xlsx") -> bytes:
    """產生測試用標單。預設含標題列、表頭、群組列、明細列與續寫列。"""
    payload = rows if rows is not None else BOQ_ROWS
    if suffix == ".xls":
        return make_xls_bytes(rows=payload, sheet_name=header_sheet)
    return make_xlsx_bytes(rows=payload, sheet_name=header_sheet)


#: 一般內文頁的填充文字，字數遠超過守門門檻，確保不會被誤判成圖頁
_PDF_BODY = "本工程依政府採購法第七十條及公共工程施工品質管理作業要點辦理品質管理。" * 6


def make_pdf_bytes(text_pages: int = 2, figure_pages: int = 0, sparse_pages: int = 0) -> bytes:
    """產生測試用 PDF。不 commit binary fixture，所以用程式現做。

    - `text_pages`：正常內文頁。
    - `figure_pages`：以圖為主的頁——一張點陣圖加一行圖號，模擬設計圖說裡
      「尺寸標註壓在圖片裡」的情況。
    - `sparse_pages`：字少但**沒有圖**的頁（扉頁、目錄）。守門不該把它算成圖頁。
    """
    document = pymupdf.open()
    try:
        for _ in range(text_pages):
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(50, 50, 550, 750), _PDF_BODY, fontsize=11, fontname="china-t"
            )

        for index in range(figure_pages):
            page = document.new_page()
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 240, 240))
            pixmap.set_rect(pixmap.irect, (200, 200, 200))
            page.insert_image(pymupdf.Rect(100, 80, 460, 440), pixmap=pixmap)
            page.insert_textbox(
                pymupdf.Rect(100, 460, 460, 490),
                f"圖{index + 1}",
                fontsize=11,
                fontname="china-t",
            )

        for _ in range(sparse_pages):
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(50, 50, 550, 90), "目錄", fontsize=11, fontname="china-t"
            )

        return document.tobytes()
    finally:
        document.close()
