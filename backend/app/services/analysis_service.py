"""分析管線：一份文件從解析到產出法規引用清單的完整流程。

    解析 -> 抽取 -> 正規化 -> 比對/查詢 -> 完成

每一步都會更新 jobs.progress 與 jobs.current_step，前端才能顯示進度。
任何一步整體失敗 -> job = FAILED；單一筆引用失敗 -> 只有那一筆變成 UNKNOWN。
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.core.config import settings
from app.core.enums import DocumentStatus, JobStatus, JobStep, ParseQuality, ReviewStatus
from app.core.errors import DocumentNotFoundError
from app.core.logging import log_context
from app.extractors import ExtractionPipeline
from app.extractors.dictionary_extractor import load_alias_entries
from app.matching.normalizer import NormalizationEngine
from app.models.document import Document, DocumentSection
from app.models.reference import RegulationReference
from app.parsers import parse_document
from app.repositories.audit import AuditRepository
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.repositories.references import ReferenceRepository
from app.services.enterprise_document_service import EnterpriseDocumentService
from app.services.matching_service import MatchingService

logger = logging.getLogger(__name__)

# 各步驟結束時的進度百分比，集中在這裡方便調整
_PROGRESS = {
    JobStep.PARSING: 15,
    JobStep.EXTRACTING: 40,
    JobStep.NORMALIZING: 50,
    JobStep.MATCHING: 55,
    JobStep.QUERYING: 95,
    JobStep.REPORTING: 100,
}


@dataclass(frozen=True)
class _PriorReview:
    status: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None


class AnalysisService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
        self.documents = DocumentRepository(session)
        self.jobs = JobRepository(session)
        self.references = ReferenceRepository(session)
        self.audit = AuditRepository(session)

        self.llm = get_llm_provider()
        self.extractor = ExtractionPipeline(self.llm)
        self.normalizer = NormalizationEngine()
        self.matcher = MatchingService(session, self.tenant_id, self.llm)

    async def run(self, document_id: uuid.UUID, job_id: uuid.UUID) -> None:
        """執行完整分析。這個方法由 JobRunner 在背景呼叫。"""
        job = await self.jobs.get(job_id, self.tenant_id)
        document = await self.documents.get(document_id, self.tenant_id)
        if job is None or document is None:
            raise DocumentNotFoundError("找不到要分析的文件或任務")

        try:
            await self._load_enterprise_terms()
            # 重新分析前先記下人工覆核：解析會換掉段落，舊引用的段落連結會被清空
            prior_reviews = await self._snapshot_reviews(document.id)
            sections = await self._parse(document, job)
            references = await self._extract(document, sections, job)
            await self._match(references, sections, job)
            self._restore_reviews(references, sections, prior_reviews)

            await self.documents.set_status(document, DocumentStatus.ANALYZED)
            await self.jobs.update_progress(
                job, status=JobStatus.PROCESSING, step=JobStep.REPORTING,
                progress=_PROGRESS[JobStep.REPORTING],
            )
            await self.jobs.finish(job, status=JobStatus.COMPLETED)
            await self.session.commit()
            logger.info(
                "分析完成",
                extra=log_context(document_id=str(document_id), references=len(references)),
            )
        except Exception as exc:
            await self.session.rollback()
            await self._fail(job_id, document_id, exc)
            raise

    # --- 各步驟 ---

    async def _parse(self, document: Document, job) -> list[DocumentSection]:
        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, step=JobStep.PARSING, progress=5
        )
        await self.documents.set_status(document, DocumentStatus.PARSING)
        await self.session.commit()

        # 解析是同步的 CPU 工作，掃描檔 OCR 每頁約半秒；放到執行緒裡跑，
        # 免得一份大檔案卡住整個服務的其他請求
        parsed = await asyncio.to_thread(parse_document, Path(document.storage_path))
        sections = [
            DocumentSection(
                document_id=document.id,
                content=item.content,
                order_index=item.order_index,
                content_type=item.content_type,
                page=item.page,
                section_title=item.section_title,
                is_ocr=item.is_ocr,
            )
            for item in parsed.sections
        ]
        await self.documents.replace_sections(document.id, sections)
        self._record_parse_quality(document, parsed.coverage)
        await self.documents.set_status(document, DocumentStatus.PARSED)
        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, progress=_PROGRESS[JobStep.PARSING]
        )
        await self.session.commit()
        return sections

    async def _load_enterprise_terms(self) -> None:
        """把這個租戶的企業內部文件加進字典。

        規則引擎只認得法規字尾（法、規範、標準…），「品質手冊」「程序書」與文件編號
        「QP-07-03」都抽不到，只能靠字典；正規化也要知道「QP-07-03」就是哪份文件。
        公用字典放在後面：同一個詞兩邊都有時，以官方法規為準。
        """
        terms = await EnterpriseDocumentService(self.session, self.tenant_id).alias_entries()
        if terms:
            self.extractor = ExtractionPipeline(self.llm, extra_entries=terms)
            self.normalizer = NormalizationEngine((*terms, *load_alias_entries()))

    def _record_parse_quality(self, document: Document, coverage) -> None:
        """把「有多少內容沒讀到」記在文件上。

        只寫 log 是不夠的——沒有人會去翻 log，使用者還是會拿到一份看起來乾淨的
        結果。要擋住「有信心的錯」，訊息必須跟著文件走到畫面上。
        """
        if coverage is None or not coverage.is_degraded:
            document.parse_quality = ParseQuality.OK
            document.parse_quality_note = None
            return

        document.parse_quality = ParseQuality.DEGRADED
        document.parse_quality_note = coverage.note
        logger.warning(
            "解析品質不佳",
            extra=log_context(document_id=str(document.id), note=coverage.note),
        )

    async def _extract(
        self, document: Document, sections: list[DocumentSection], job
    ) -> list[RegulationReference]:
        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, step=JobStep.EXTRACTING
        )
        await self.documents.set_status(document, DocumentStatus.ANALYZING)
        await self.session.commit()

        # 重新分析時先清掉上一次的結果
        await self.references.delete_by_document(document.id)

        references: list[RegulationReference] = []
        #: (呼叫紀錄, 這次呼叫抽出來的引用)。詳細面板依 reference_id 列出 AI 使用情形，
        #: 抽取的呼叫不連到引用的話，「這筆是 AI 抽的」在面板上就看不到
        ai_records: list[tuple] = []
        for section in sections:
            candidates, ai_record = await self.extractor.extract(section.content)
            produced: list[RegulationReference] = []
            if ai_record is not None:
                ai_records.append((ai_record, produced))
            for candidate in candidates:
                reference = RegulationReference(
                    document_id=document.id,
                    section_id=section.id,
                    raw_text=candidate.raw_text[:512],
                    regulation_type=candidate.regulation_type,
                    article=candidate.article,
                    standard_number=candidate.standard_number,
                    extraction_confidence=candidate.confidence,
                    extraction_method=candidate.method,
                )
                references.append(reference)
                produced.append(reference)

        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, progress=_PROGRESS[JobStep.EXTRACTING]
        )

        # 正規化：補上 normalized_name
        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, step=JobStep.NORMALIZING
        )
        for reference in references:
            result = self.normalizer.normalize(reference.raw_text)
            reference.normalized_name = result.normalized_name
            reference.match_reasons = "\n".join(result.reasons) or None

        await self.references.add_all(references)
        for record, produced in ai_records:
            # 一次呼叫只有一個 reference_id 欄位：連到它抽出的第一筆；沒抽到就只連到 job
            await self.audit.log_ai_call(
                record, job_id=job.id, reference_id=produced[0].id if produced else None
            )

        await self.jobs.update_progress(
            job, status=JobStatus.PROCESSING, progress=_PROGRESS[JobStep.NORMALIZING]
        )
        await self.session.commit()
        return references

    async def _match(
        self, references: list[RegulationReference], sections: list[DocumentSection], job
    ) -> None:
        await self.jobs.update_progress(
            job,
            status=JobStatus.PROCESSING,
            step=JobStep.MATCHING,
            progress=_PROGRESS[JobStep.MATCHING],
        )
        await self.session.commit()

        section_text = {section.id: section.content for section in sections}
        total = len(references) or 1
        span = _PROGRESS[JobStep.QUERYING] - _PROGRESS[JobStep.MATCHING]

        for index, reference in enumerate(references, start=1):
            await self.matcher.resolve(
                reference,
                job_id=job.id,
                context=section_text.get(reference.section_id, ""),
            )
            await self.jobs.update_progress(
                job,
                status=JobStatus.PROCESSING,
                step=JobStep.QUERYING,
                progress=_PROGRESS[JobStep.MATCHING] + int(span * index / total),
            )
            await self.session.commit()

    async def _snapshot_reviews(self, document_id: uuid.UUID) -> dict[tuple, list[_PriorReview]]:
        """上一次分析留下、有人覆核過的引用，依（原始文字, 所在段落全文）分組。"""
        prior: dict[tuple, list[_PriorReview]] = {}
        for reference in await self.references.all_by_document(document_id):
            if reference.review_status == ReviewStatus.UNREVIEWED:
                continue
            key = (reference.raw_text, reference.section.content if reference.section else None)
            prior.setdefault(key, []).append(
                _PriorReview(
                    status=reference.status,
                    review_status=reference.review_status,
                    reviewed_by=reference.reviewed_by,
                    reviewed_at=reference.reviewed_at,
                    review_note=reference.review_note,
                )
            )
        return prior

    def _restore_reviews(
        self,
        references: list[RegulationReference],
        sections: list[DocumentSection],
        prior: dict[tuple, list[_PriorReview]],
    ) -> None:
        """重新分析後，同一段落裡同一筆引用沿用原本的覆核。

        狀態沒變：覆核照舊——人確認過的結論，重跑一次比對不該讓人再確認一次。
        狀態變了：回到未覆核，比對理由寫明從什麼變成什麼、原本誰覆核過。人確認的是
        舊狀態，不能拿來背書新狀態。段落文字改過的引用對不上，一律重新覆核。
        """
        if not prior:
            return
        section_text = {section.id: section.content for section in sections}
        for reference in references:
            candidates = prior.get((reference.raw_text, section_text.get(reference.section_id)))
            if not candidates:
                continue
            old = candidates.pop(0)
            if old.status == reference.status:
                reference.review_status = old.review_status
                reference.reviewed_by = old.reviewed_by
                reference.reviewed_at = old.reviewed_at
                reference.review_note = old.review_note
            else:
                reason = (
                    f"重新分析後狀態由 {old.status} 變為 {reference.status}，"
                    f"原本的人工覆核（{old.review_status}，{old.reviewed_by or '未知'}）需要重新確認"
                )
                reference.match_reasons = "\n".join(filter(None, [reference.match_reasons, reason]))

    async def _fail(self, job_id: uuid.UUID, document_id: uuid.UUID, exc: Exception) -> None:
        """分析失敗：把錯誤寫進 job，讓前端看得到原因。"""
        logger.exception("分析失敗", extra=log_context(document_id=str(document_id)))
        job = await self.jobs.get(job_id, self.tenant_id)
        document = await self.documents.get(document_id, self.tenant_id)
        if job is not None:
            await self.jobs.finish(
                job, status=JobStatus.FAILED, error_message=f"{type(exc).__name__}: {exc}"
            )
        if document is not None:
            await self.documents.set_status(document, DocumentStatus.FAILED)
        await self.session.commit()
