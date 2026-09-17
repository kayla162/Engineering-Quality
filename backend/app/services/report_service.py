"""報告組裝：把資料庫裡的結果整理成統一的 ReportData。

匯出格式（Excel/CSV/PDF）由 reports/ 負責，這裡只負責「報告內容是什麼」。
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.core.enums import NEEDS_ATTENTION_STATUSES, RegulationStatus
from app.models.base import utcnow
from app.models.reference import RegulationReference
from app.repositories.audit import AuditRepository
from app.repositories.references import ReferenceRepository
from app.schemas.reference import ReferenceSummary
from app.schemas.report import ReportData, ReportRow
from app.services.document_service import DocumentService
from app.services.reference_service import is_tentative

logger = logging.getLogger(__name__)

STATUS_LABELS: dict[str, str] = {
    RegulationStatus.ACTIVE: "現行有效",
    RegulationStatus.AMENDED: "已修正",
    RegulationStatus.REPEALED: "已廢止",
    RegulationStatus.NOT_FOUND: "查無此法規",
    RegulationStatus.POSSIBLE_MATCH: "疑似對應，需人工確認",
    RegulationStatus.UNKNOWN: "查詢失敗或尚未查詢",
}

DISCLAIMER = (
    "本報告的法規狀態來自系統已啟用的資料來源，僅供初步查核參考。"
    "標示為「已修正」「已廢止」「查無此法規」「疑似對應」「查詢失敗」的項目，"
    "以及所有 CNS/ISO/ASTM/JIS 等標準，都必須由人員向官方來源查證後才可採用。"
)


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.references = ReferenceRepository(session)
        self.documents = DocumentService(session)
        self.audit = AuditRepository(session)

    async def build(self, document_id: uuid.UUID, with_narrative: bool = False) -> ReportData:
        document = await self.documents.get(document_id)
        rows = await self.references.all_by_document(document_id)
        counts = await self.references.status_counts(document_id)
        summary = ReferenceSummary.from_counts(counts)

        report = ReportData(
            document_id=document.id,
            filename=document.filename,
            document_status=document.status,
            generated_at=utcnow(),
            total_references=len(rows),
            summary=summary,
            rows=[self._to_row(reference) for reference in rows],
            disclaimer=DISCLAIMER,
        )
        if with_narrative:
            report.narrative = await self._narrative(report)
        return report

    # --- 內部 ---

    def _to_row(self, reference: RegulationReference) -> ReportRow:
        regulation = reference.regulation
        label = STATUS_LABELS.get(reference.status, reference.status)
        # NOT_FOUND 與 POSSIBLE_MATCH 的說明本身就表達了不確定，不要再加一次「疑似」
        if is_tentative(reference) and reference.status not in (
            RegulationStatus.NOT_FOUND,
            RegulationStatus.POSSIBLE_MATCH,
        ):
            label = f"{label}（疑似）"

        return ReportRow(
            raw_text=reference.raw_text,
            normalized_name=reference.normalized_name,
            regulation_type=reference.regulation_type,
            article=reference.article,
            page=reference.section.page if reference.section else None,
            status=reference.status,
            status_label=label,
            match_confidence=reference.match_confidence,
            matched_name=regulation.name if regulation else None,
            authority=regulation.authority if regulation else None,
            last_amended_date=(
                regulation.last_amended_date.isoformat()
                if regulation and regulation.last_amended_date
                else None
            ),
            official_url=regulation.official_url if regulation else None,
            data_source=regulation.source if regulation else None,
            extraction_method=reference.extraction_method,
            review_status=reference.review_status,
            reviewed_by=reference.reviewed_by,
            match_reasons=" / ".join(reference.reason_list),
            needs_attention=reference.status in NEEDS_ATTENTION_STATUSES,
        )

    async def _narrative(self, report: ReportData) -> str | None:
        """請 LLM 把統計結果寫成一段說明。只負責語言表達，不做任何判斷。

        AI 關閉或呼叫失敗時回傳 None，報告照樣完整。
        """
        provider = get_llm_provider()
        findings = [
            f"文件「{report.filename}」共找到 {report.total_references} 筆法規引用",
            f"現行有效 {report.summary.confirmed_active} 筆",
            f"已修正 {report.summary.possible_amended} 筆",
            f"已廢止 {report.summary.possible_repealed} 筆",
            f"疑似對應需人工確認 {report.summary.possible_match} 筆",
            f"查無此法規 {report.summary.not_found} 筆",
            f"查詢失敗或尚未查詢 {report.summary.unknown} 筆",
        ]
        result = await provider.summarize_for_report(findings)
        if result.record is not None:
            await self.audit.log_ai_call(result.record)
            await self.session.commit()
        return result.value
