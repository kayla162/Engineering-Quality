"""CSV 匯出。用 UTF-8 BOM，Excel 直接開啟不會變亂碼。"""

import csv
from io import StringIO

from app.reports.columns import headers, row_values
from app.schemas.report import ReportData


def build(report: ReportData) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["# 文件", report.filename])
    writer.writerow(["# 產生時間", report.generated_at.isoformat()])
    writer.writerow(["# 引用總數", report.total_references])
    writer.writerow(["# 資料來源聲明", report.disclaimer])
    writer.writerow([])

    writer.writerow(headers())
    for row in report.rows:
        writer.writerow(row_values(row))

    return buffer.getvalue().encode("utf-8-sig")
