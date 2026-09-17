"""PDF 匯出（reportlab）。中文字型的解析見 reports/fonts.py。"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reports.fonts import ensure_font
from app.schemas.report import ReportData

# PDF 版面有限，只放最重要的欄位；完整欄位請匯出 Excel/CSV
PDF_COLUMNS: list[tuple[str, str]] = [
    ("原始文字", "raw_text"),
    ("正規化名稱", "normalized_name"),
    ("頁碼", "page"),
    ("狀態", "status_label"),
    ("信心", "match_confidence"),
    ("比對到的法規", "matched_name"),
    ("資料來源", "data_source"),
    ("人工覆核", "review_status"),
]


def build(report: ReportData) -> bytes:
    font = ensure_font()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"法規查核報告 - {report.filename}",
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CJKTitle", parent=base["Title"], fontName=font, fontSize=16, leading=22
    )
    body_style = ParagraphStyle(
        "CJKBody", parent=base["Normal"], fontName=font, fontSize=9, leading=13
    )
    cell_style = ParagraphStyle(
        "CJKCell", parent=base["Normal"], fontName=font, fontSize=7.5, leading=10
    )

    story = [
        Paragraph("工程文件法規引用查核報告", title_style),
        Spacer(1, 4 * mm),
        Paragraph(f"文件：{report.filename}", body_style),
        Paragraph(f"產生時間：{report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}", body_style),
        Paragraph(
            f"引用總數 {report.total_references}　｜　"
            f"現行有效 {report.summary.confirmed_active}　"
            f"已修正 {report.summary.possible_amended}　"
            f"已廢止 {report.summary.possible_repealed}　"
            f"疑似對應 {report.summary.possible_match}　"
            f"查無 {report.summary.not_found}　"
            f"未知 {report.summary.unknown}",
            body_style,
        ),
        Spacer(1, 3 * mm),
    ]
    if report.narrative:
        story += [Paragraph(report.narrative, body_style), Spacer(1, 3 * mm)]
    story += [Paragraph(report.disclaimer, body_style), Spacer(1, 5 * mm)]

    header = [Paragraph(f"<b>{title}</b>", cell_style) for title, _ in PDF_COLUMNS]
    table_data = [header]
    attention_rows = []
    for index, row in enumerate(report.rows, start=1):
        cells = []
        for _, field in PDF_COLUMNS:
            value = getattr(row, field)
            if field == "match_confidence" and value is not None:
                value = f"{value:.0%}"
            cells.append(Paragraph(str(value if value is not None else ""), cell_style))
        table_data.append(cells)
        if row.needs_attention:
            attention_rows.append(index)

    # 欄寬（points）。A4 橫式扣掉左右邊界大約還有 818pt
    table = Table(
        table_data,
        repeatRows=1,
        hAlign="LEFT",
        colWidths=[130, 150, 32, 105, 42, 205, 55, 70],
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B0B0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    style += [
        ("BACKGROUND", (0, index), (-1, index), colors.HexColor("#FFF2CC"))
        for index in attention_rows
    ]
    table.setStyle(TableStyle(style))
    story.append(table)

    document.build(story)
    return buffer.getvalue()
