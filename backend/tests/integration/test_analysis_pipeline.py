"""整合測試：DOCX -> 解析 -> 抽取 -> 正規化 -> 比對 -> 資料庫的完整鏈路。"""

import pytest

from app.core.enums import DocumentStatus, JobStatus, ParseQuality, RegulationStatus
from app.repositories.audit import AuditRepository
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.repositories.references import ReferenceRepository
from app.services.analysis_service import AnalysisService
from app.services.document_service import DocumentService
from app.services.report_service import ReportService
from tests.factories import make_pdf_bytes


@pytest.fixture
async def analyzed(db_session, uploaded_document):
    job = await JobRepository(db_session).create(uploaded_document.id)
    await db_session.commit()
    await AnalysisService(db_session).run(uploaded_document.id, job.id)
    return uploaded_document, job


class TestPipeline:
    async def test_document_and_job_reach_completed_state(self, db_session, analyzed):
        document, job = analyzed
        assert (await DocumentRepository(db_session).get(document.id)).status == DocumentStatus.ANALYZED
        refreshed = await JobRepository(db_session).get(job.id)
        assert refreshed.status == JobStatus.COMPLETED
        assert refreshed.progress == 100
        assert refreshed.finished_at is not None
        assert refreshed.error_message is None

    async def test_sections_are_persisted_with_order(self, db_session, analyzed):
        document, _ = analyzed
        sections = await DocumentRepository(db_session).list_sections(document.id)
        assert sections
        assert [s.order_index for s in sections] == sorted(s.order_index for s in sections)

    async def test_expected_references_with_expected_statuses(self, db_session, analyzed):
        document, _ = analyzed
        rows = await ReferenceRepository(db_session).all_by_document(document.id)
        # 同一部法規可能在文件中出現多次（段落一次、表格一次），所以用清單存
        by_name: dict[str, list] = {}
        for row in rows:
            by_name.setdefault(row.normalized_name, []).append(row)

        # 完全命中的現行法規（段落與表格各出現一次）
        procurement = by_name["政府採購法"]
        assert len(procurement) == 2
        assert all(row.status == RegulationStatus.ACTIVE for row in procurement)
        assert all(row.match_confidence == 1.0 for row in procurement)
        # 條號要被保留下來
        assert any(row.article == "第70條" for row in procurement)
        # 已廢止的舊法
        assert by_name["勞工安全衛生法"][0].status == RegulationStatus.REPEALED
        # 假資料庫裡沒有的法規
        assert by_name["營建剩餘土石方處理辦法"][0].status == RegulationStatus.NOT_FOUND
        # 名稱順序顛倒：仍比對得到，但信心不足以自動採信
        amended = by_name["混凝土結構施工規範"][0]
        assert amended.status == RegulationStatus.AMENDED
        assert 0.7 <= amended.match_confidence < 0.9
        # 付費標準：即使名稱完全命中也只能是疑似對應
        assert by_name["CNS 3090 預拌混凝土"][0].status == RegulationStatus.POSSIBLE_MATCH

    async def test_every_reference_is_traceable(self, db_session, analyzed):
        """每一筆都要能追溯到來源段落、抽取方式與比對理由。"""
        document, _ = analyzed
        rows = await ReferenceRepository(db_session).all_by_document(document.id)
        assert rows
        for row in rows:
            assert row.section_id is not None
            assert row.extraction_method
            assert row.reason_list, f"{row.raw_text} 沒有比對理由"

    async def test_external_queries_are_logged(self, db_session, analyzed):
        document, _ = analyzed
        rows = await ReferenceRepository(db_session).all_by_document(document.id)
        audit = AuditRepository(db_session)
        logged = [await audit.queries_for_reference(row.id) for row in rows]
        assert any(logged), "至少要有一筆外部來源查詢紀錄"

    async def test_no_ai_calls_when_llm_disabled(self, db_session, analyzed):
        """ENABLE_LLM_FALLBACK=false 時，整條流程不得呼叫任何 LLM。"""
        document, _ = analyzed
        rows = await ReferenceRepository(db_session).all_by_document(document.id)
        audit = AuditRepository(db_session)
        for row in rows:
            assert await audit.ai_calls_for_reference(row.id) == []

    async def test_reanalysis_replaces_previous_results(self, db_session, analyzed):
        """重新分析不會累積重複資料，但會留下新的 job 紀錄。"""
        document, first_job = analyzed
        references = ReferenceRepository(db_session)
        before = len(await references.all_by_document(document.id))

        second_job = await JobRepository(db_session).create(document.id)
        await db_session.commit()
        await AnalysisService(db_session).run(document.id, second_job.id)

        assert len(await references.all_by_document(document.id)) == before
        assert second_job.id != first_job.id
        assert (await JobRepository(db_session).get(first_job.id)) is not None


class TestReport:
    async def test_report_summary_matches_reference_counts(self, db_session, analyzed):
        document, _ = analyzed
        report = await ReportService(db_session).build(document.id)
        summary = report.summary
        assert report.total_references == len(report.rows)
        assert report.total_references == (
            summary.confirmed_active
            + summary.possible_amended
            + summary.possible_repealed
            + summary.possible_match
            + summary.not_found
            + summary.unknown
        )

    async def test_tentative_rows_are_labelled(self, db_session, analyzed):
        document, _ = analyzed
        report = await ReportService(db_session).build(document.id)
        row = next(r for r in report.rows if r.normalized_name == "混凝土結構施工規範")
        assert "疑似" in row.status_label
        assert row.needs_attention is True

    async def test_disclaimer_is_always_present(self, db_session, analyzed):
        document, _ = analyzed
        report = await ReportService(db_session).build(document.id)
        assert "查證" in report.disclaimer and "人員" in report.disclaimer

    @pytest.mark.parametrize("fmt", ["xlsx", "csv", "pdf"])
    async def test_export_formats(self, db_session, analyzed, fmt):
        from app.reports import export

        document, _ = analyzed
        report = await ReportService(db_session).build(document.id)
        content, filename, media_type = export(report, fmt)
        assert content and filename.endswith(f".{fmt}") and media_type


class TestEmptyRegulationTable:
    """法規主檔是空的時候也要能跑完。

    背景：接上真實資料來源時，regulations 一開始是空的，法規是在比對過程中
    才由來源查詢寫進去的。這些「剛建立、還沒被 SELECT 載入過」的物件如果被
    當成一般 ORM 物件存取關聯欄位，會在 async session 觸發 lazy load 而整個炸掉。
    先前的測試都預先 seed 過，所以測不到這條路徑。
    """

    async def test_analysis_works_without_preseeded_regulations(self, db_session, uploaded_document):
        from sqlalchemy import delete

        from app.models.regulation import Regulation
        from app.repositories.regulations import RegulationRepository

        await db_session.execute(delete(Regulation))
        await db_session.commit()
        assert await RegulationRepository(db_session).count() == 0

        job = await JobRepository(db_session).create(uploaded_document.id)
        await db_session.commit()
        await AnalysisService(db_session).run(uploaded_document.id, job.id)

        assert (await JobRepository(db_session).get(job.id)).status == JobStatus.COMPLETED
        rows = await ReferenceRepository(db_session).all_by_document(uploaded_document.id)
        assert rows
        # 法規是在比對過程中被寫進來的
        assert await RegulationRepository(db_session).count() > 0
        assert any(row.regulation_id is not None for row in rows)


class TestParseQuality:
    """解析品質要被記下來，不是只在 log 裡閃一下。

    會踩到這一關的是設計圖說：parser 不會報錯，但圖裡的尺寸標註抽不出來。
    使用者必須看得到「這份有多少沒讀到」，否則會把一份空結果當成「查無問題」。
    """

    @staticmethod
    async def _analyze(db_session, filename: str, data: bytes):
        document = await DocumentService(db_session).upload(filename, data)
        await db_session.commit()
        job = await JobRepository(db_session).create(document.id)
        await db_session.commit()
        await AnalysisService(db_session).run(document.id, job.id)
        return await DocumentRepository(db_session).get(document.id)

    async def test_a_figure_heavy_pdf_is_marked_degraded(self, db_session):
        document = await self._analyze(
            db_session, "設計規範.pdf", make_pdf_bytes(text_pages=4, figure_pages=6)
        )

        assert document.parse_quality == ParseQuality.DEGRADED

    async def test_the_note_says_how_much_was_lost(self, db_session):
        document = await self._analyze(
            db_session, "設計規範.pdf", make_pdf_bytes(text_pages=4, figure_pages=6)
        )

        assert "以圖為主" in document.parse_quality_note

    async def test_a_text_pdf_is_marked_ok(self, db_session):
        document = await self._analyze(db_session, "契約書.pdf", make_pdf_bytes(text_pages=10))

        assert document.parse_quality == ParseQuality.OK
        assert document.parse_quality_note is None

    async def test_formats_without_pages_are_marked_ok(self, db_session, uploaded_document):
        """docx 沒有這個失效模式，不該被標記，也不該是 None。"""
        job = await JobRepository(db_session).create(uploaded_document.id)
        await db_session.commit()
        await AnalysisService(db_session).run(uploaded_document.id, job.id)

        document = await DocumentRepository(db_session).get(uploaded_document.id)
        assert document.parse_quality == ParseQuality.OK
