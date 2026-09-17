"""報告匯出格式的註冊表。新增格式時只要多寫一個模組、在這裡加一行。"""

from collections.abc import Callable

from app.core.errors import AppError
from app.reports import csv_report, excel_report, pdf_report
from app.schemas.report import ReportData

#: format -> (產生函式, 副檔名, MIME type)
EXPORTERS: dict[str, tuple[Callable[[ReportData], bytes], str, str]] = {
    "xlsx": (
        excel_report.build,
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "csv": (csv_report.build, "csv", "text/csv; charset=utf-8"),
    "pdf": (pdf_report.build, "pdf", "application/pdf"),
}


def export(report: ReportData, fmt: str) -> tuple[bytes, str, str]:
    """回傳 (檔案內容, 檔名, MIME type)。"""
    entry = EXPORTERS.get(fmt.lower())
    if entry is None:
        raise AppError(f"不支援的匯出格式「{fmt}」，可用格式：{', '.join(EXPORTERS)}")

    builder, extension, media_type = entry
    stem = report.filename.rsplit(".", 1)[0]
    filename = f"{stem}_法規查核報告.{extension}"
    return builder(report), filename, media_type


__all__ = ["EXPORTERS", "export"]
