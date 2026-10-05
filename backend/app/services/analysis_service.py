"""分析管線：一份文件從解析到產出法規引用清單的完整流程。

    解析 -> 抽取 -> 正規化 -> 比對/查詢 -> 完成

每一步都會更新 jobs.progress 與 jobs.current_step，前端才能顯示進度。
任何一步整體失敗 -> job = FAILED；單一筆引用失敗 -> 只有那一筆變成 UNKNOWN。
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.core.enums import DocumentStatus, JobStatus, JobStep, ParseQuality
from app.core.errors import DocumentNotFoundError
from app.core.logging import log_context
from app.extractors import ExtractionPipeline
from app.matching.normalizer import NormalizationEngine
from app.models.document import Document, DocumentSection
from app.models.reference import RegulationReference
from app.parsers import parse_document
from app.repositories.audit import AuditRepository
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.repositories.references import ReferenceRepository
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


class AnalysisService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.documents = DocumentRepository(session)
        self.jobs = JobRepository(session)
        self.references = ReferenceRepository(session)
        self.audit = AuditRepository(session)

        self.llm = get_llm_provider()
        self.extractor = ExtractionPipeline(self.llm)
        self.normalizer = NormalizationEngine()
        self.matcher = MatchingService(session, self.llm)

    async def run(self, document_id: uuid.UUID, job_id: uuid.UUID) -> None:
        """執行完整分析。這個方法由 JobRunner 在背景呼叫。"""
        job = await self.jobs.get(job_id)
        document = await self.documents.get(document_id)
        if job is None or document is None:
            raise DocumentNotFoundError("找不到要分析的文件或任務")

        try:
            sections = await self._parse(document, job)
            references = await self._extract(document, sections, job)
            await self._match(references, sections, job)

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

        parsed = parse_document(Path(document.storage_path))
        sections = [
            DocumentSection(
                document_id=document.id,
                content=item.content,
                order_index=item.order_index,
                content_type=item.content_type,
                page=item.page,
                section_title=item.section_title,
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
        ai_records = []
        for section in sections:
            candidates, ai_record = await self.extractor.extract(section.content)
            if ai_record is not None:
                ai_records.append(ai_record)
            for candidate in candidates:
                references.append(
                    RegulationReference(
                        document_id=document.id,
                        section_id=section.id,
                        raw_text=candidate.raw_text[:512],
                        regulation_type=candidate.regulation_type,
                        article=candidate.article,
                        standard_number=candidate.standard_number,
                        extraction_confidence=candidate.confidence,
                        extraction_method=candidate.method,
                    )
                )

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
        for record in ai_records:
            await self.audit.log_ai_call(record, job_id=job.id)

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

    async def _fail(self, job_id: uuid.UUID, document_id: uuid.UUID, exc: Exception) -> None:
        """分析失敗：把錯誤寫進 job，讓前端看得到原因。"""
        logger.exception("分析失敗", extra=log_context(document_id=str(document_id)))
        job = await self.jobs.get(job_id)
        document = await self.documents.get(document_id)
        if job is not None:
            await self.jobs.finish(
                job, status=JobStatus.FAILED, error_message=f"{type(exc).__name__}: {exc}"
            )
        if document is not None:
            await self.documents.set_status(document, DocumentStatus.FAILED)
        await self.session.commit()
