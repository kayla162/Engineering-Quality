"""企業內部文件清單：匯入、查詢，以及提供給抽取器與資料來源的資料。

清單來自 `data/templates/企業內部文件清單範本.xlsx` 格式的 Excel（品保／文管單位的
文件管制一覽表）。匯入是「整份取代」，而且全有或全無：任何一列有錯就整份不收，
錯誤逐列回報——匯入一半的清單會讓系統把漏掉的文件判成「查無此法規」，比不匯入更糟。
"""

import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RegulationStatus, RegulationType
from app.core.errors import AppError
from app.extractors.dictionary_extractor import AliasEntry
from app.models.enterprise import EnterpriseDocument

#: 範本「類型」下拉選單的選項（scripts/generate_enterprise_template.py 也用這份）
DOCUMENT_TYPES = (
    "品質手冊", "程序書", "作業標準（SOP）", "施工規範", "檢驗標準", "表單", "業主特訂條款", "其他",
)
#: 範本「狀態」-> 系統狀態
STATUS_MAP = {
    "現行": RegulationStatus.ACTIVE,
    "已修訂": RegulationStatus.AMENDED,
    "作廢": RegulationStatus.REPEALED,
}
STATUS_LABELS = {value: label for label, value in STATUS_MAP.items()}

SHEET_NAME = "文件清單"
#: 範本欄位標題（去掉必填記號「 *」之後）-> 內部欄位
COLUMNS = {
    "文件編號": "doc_number",
    "文件名稱": "name",
    "類型": "doc_type",
    "版次": "revision",
    "生效日": "effective_date",
    "最後修訂日": "last_revised_date",
    "狀態": "status",
    "取代文件編號": "replaced_by",
    "主管單位": "owner",
    "別名": "aliases",
    "備註": "note",
}
REQUIRED = ("doc_number", "name", "doc_type", "revision", "effective_date", "status")
#: 範本第 2 列是範例，備註寫著這句；匯入時自動略過
EXAMPLE_MARK = "範例列"
MAX_ROWS = 5000
_ALIAS_SPLIT = re.compile(r"[、，,;；\n]+")
_DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d")


class EnterpriseImportError(AppError):
    code = "ENTERPRISE_IMPORT_INVALID"


@dataclass
class ParsedDocument:
    doc_number: str
    name: str
    doc_type: str
    revision: str
    effective_date: date
    status: str
    last_revised_date: date | None = None
    replaced_by: str | None = None
    owner: str | None = None
    aliases: list[str] = field(default_factory=list)
    note: str | None = None


def parse_workbook(content: bytes) -> list[ParsedDocument]:
    """讀 Excel，回傳文件清單。有任何錯誤就丟 EnterpriseImportError，details 是逐列錯誤。"""
    try:
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise EnterpriseImportError(f"無法讀取 Excel 檔案：{exc}") from exc

    sheet = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None) or ()
    positions: dict[str, int] = {}
    for index, title in enumerate(header):
        key = COLUMNS.get(str(title or "").replace("*", "").strip())
        if key:
            positions[key] = index
    missing = [title for title, key in COLUMNS.items() if key in REQUIRED and key not in positions]
    if missing:
        raise EnterpriseImportError(
            f"工作表「{sheet.title}」缺少必要欄位：{'、'.join(missing)}。請使用系統提供的範本。"
        )

    documents: list[ParsedDocument] = []
    errors: list[dict] = []
    for row_number, values in enumerate(rows, start=2):
        record = {key: _cell(values, index) for key, index in positions.items()}
        if not any(record.values()) or EXAMPLE_MARK in str(record.get("note") or ""):
            continue
        if len(documents) >= MAX_ROWS:
            raise EnterpriseImportError(f"清單超過 {MAX_ROWS} 列上限")
        parsed, row_errors = _parse_row(record)
        errors.extend({"row": row_number, "message": message} for message in row_errors)
        if parsed is not None:
            documents.append(parsed)

    seen: dict[str, int] = {}
    for document in documents:
        key = document.doc_number.casefold()
        seen[key] = seen.get(key, 0) + 1
    duplicates = sorted(number for number, count in seen.items() if count > 1)
    if duplicates:
        errors.append({"row": None, "message": f"文件編號重複：{'、'.join(duplicates)}"})

    if errors:
        raise EnterpriseImportError(f"清單有 {len(errors)} 處錯誤，整份未匯入", details=errors)
    if not documents:
        raise EnterpriseImportError("清單是空的（範例列不算），整份未匯入")
    return documents


def _cell(values: tuple, index: int):
    value = values[index] if index < len(values) else None
    if isinstance(value, str):
        value = value.strip() or None
    return value


def _parse_row(record: dict) -> tuple[ParsedDocument | None, list[str]]:
    errors = [f"「{_title(key)}」必填" for key in REQUIRED if record.get(key) in (None, "")]

    status_label = str(record.get("status") or "")
    status = STATUS_MAP.get(status_label)
    if status_label and status is None:
        errors.append(f"狀態「{status_label}」無效，只能是：{'、'.join(STATUS_MAP)}")

    doc_type = str(record.get("doc_type") or "")
    if doc_type and doc_type not in DOCUMENT_TYPES:
        errors.append(f"類型「{doc_type}」無效，請用下拉選單的選項")

    effective = _to_date(record.get("effective_date"), "生效日", errors)
    revised = _to_date(record.get("last_revised_date"), "最後修訂日", errors)
    if errors:
        return None, errors

    number = str(record["doc_number"])
    aliases = [a.strip() for a in _ALIAS_SPLIT.split(str(record.get("aliases") or "")) if a.strip()]
    return (
        ParsedDocument(
            doc_number=number,
            name=str(record["name"]),
            doc_type=doc_type,
            revision=str(record["revision"]),
            effective_date=effective,
            last_revised_date=revised,
            status=status,
            replaced_by=_text(record.get("replaced_by")),
            owner=_text(record.get("owner")),
            aliases=[a for a in dict.fromkeys(aliases) if a not in (number, record["name"])],
            note=_text(record.get("note")),
        ),
        [],
    )


def _to_date(value, title: str, errors: list[str]) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    errors.append(f"「{title}」不是日期：{value}")
    return None


def _text(value) -> str | None:
    return str(value)[:255] if value not in (None, "") else None


def _title(key: str) -> str:
    return next(title for title, k in COLUMNS.items() if k == key)


class EnterpriseDocumentService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def list_documents(self) -> list[EnterpriseDocument]:
        result = await self.session.execute(
            select(EnterpriseDocument)
            .where(EnterpriseDocument.tenant_id == self.tenant_id)
            .order_by(EnterpriseDocument.doc_number)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        return (
            await self.session.execute(
                select(func.count())
                .select_from(EnterpriseDocument)
                .where(EnterpriseDocument.tenant_id == self.tenant_id)
            )
        ).scalar_one()

    async def replace_all(self, documents: list[ParsedDocument], username: str) -> int:
        """整份取代這個租戶的清單。呼叫端負責 commit。"""
        await self.session.execute(
            delete(EnterpriseDocument).where(EnterpriseDocument.tenant_id == self.tenant_id)
        )
        for document in documents:
            self.session.add(
                EnterpriseDocument(
                    tenant_id=self.tenant_id,
                    doc_number=document.doc_number,
                    name=document.name,
                    doc_type=document.doc_type,
                    revision=document.revision,
                    effective_date=document.effective_date,
                    last_revised_date=document.last_revised_date,
                    status=document.status,
                    replaced_by=document.replaced_by,
                    owner=document.owner,
                    aliases=document.aliases,
                    note=document.note,
                    imported_by=username,
                )
            )
        await self.session.flush()
        return len(documents)

    async def alias_entries(self) -> tuple[AliasEntry, ...]:
        """給字典抽取器與正規化引擎：名稱、別名、文件編號都對應到文件名稱。"""
        entries: list[AliasEntry] = []
        for document in await self.list_documents():
            for term in (document.name, document.doc_number, *document.aliases):
                entries.append(
                    AliasEntry(term=term, canonical=document.name, type=RegulationType.INTERNAL)
                )
        return tuple(entries)
