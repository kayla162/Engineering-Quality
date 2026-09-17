"""報告欄位定義。三種匯出格式共用同一份，欄位要調整只改這裡。"""

from app.schemas.report import ReportRow

# (欄位標題, ReportRow 的屬性名稱)
COLUMNS: list[tuple[str, str]] = [
    ("原始文字", "raw_text"),
    ("正規化名稱", "normalized_name"),
    ("類型", "regulation_type"),
    ("條號", "article"),
    ("頁碼", "page"),
    ("狀態", "status_label"),
    ("比對信心", "match_confidence"),
    ("比對到的法規", "matched_name"),
    ("發布機關", "authority"),
    ("最近修正日期", "last_amended_date"),
    ("資料來源", "data_source"),
    ("抽取方式", "extraction_method"),
    ("人工覆核", "review_status"),
    ("覆核人", "reviewed_by"),
    ("比對理由", "match_reasons"),
    ("官方連結", "official_url"),
]


def row_values(row: ReportRow) -> list:
    values = []
    for _, field in COLUMNS:
        value = getattr(row, field)
        if field == "match_confidence" and value is not None:
            value = round(value, 4)
        values.append("" if value is None else value)
    return values


def headers() -> list[str]:
    return [title for title, _ in COLUMNS]
