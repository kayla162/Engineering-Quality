"""檢核表：把工項和它的依據組起來，並算出檢核結果。

依據來自本案施工規範書，不是全國共通的 PCCES 目錄——兩者的落差就是
SPEC_NOT_INCLUDED（實測 188 個工項）。

標準（CNS/ASTM/ISO/JIS）只引述不查證：系統沒有這個資料來源，走比對管線會
全部標成「查無此法規」，讓人以為規範引用了不存在的標準。實測把規範書全文
丟進管線，2429 筆引用裡 2263 筆（93%）是 NOT_FOUND，原因就是這個。
"""

import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.core.enums import CheckResult, DocumentRole, ParseQuality
from app.core.errors import AppError, ProjectNotFoundError
from app.core.logging import log_context
from app.extractors import ExtractionPipeline
from app.models.checklist import SpecChapter, WorkItemBasis
from app.models.document import Document
from app.models.project import Project, WorkItem
from app.repositories.audit import AuditRepository
from app.repositories.checklist import ChecklistRepository
from app.repositories.documents import DocumentRepository
from app.repositories.projects import ProjectRepository
from app.sources.pcces_source import PccesSource
from app.specs import basis_block, read_spec_chapters

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChecklistRow:
    work_item: WorkItem
    result: CheckResult
    chapter: SpecChapter | None
    bases: list[WorkItemBasis]


@dataclass(frozen=True)
class Checklist:
    rows: list[ChecklistRow]
    #: 規範書解析品質不佳時的警告。依據可能殘缺，使用者必須知道。
    spec_warning: str | None = None


class ChecklistService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.projects = ProjectRepository(session)
        self.documents = DocumentRepository(session)
        self.checklist_repo = ChecklistRepository(session)
        self.audit = AuditRepository(session)
        self.extractor = ExtractionPipeline(get_llm_provider())
        self._pcces = PccesSource()

    async def build(self, project_id: uuid.UUID) -> Checklist:
        """重建整個專案的依據並回傳檢核表。重跑取代，不累加。

        先把會失敗的讀完（規範書、綱要規範目錄）、再動資料庫：讀不懂規範書
        （SpecFormatError）時，上一次建好的索引與依據原封不動，不會因為重跑失敗
        而被清空。
        """
        await self._require_project(project_id)
        spec = await self._spec_document(project_id)
        chapter_rows = read_spec_chapters(Path(spec.storage_path)) if spec is not None else []
        work_items = await self.projects.work_items(project_id)
        catalogued = await self._catalogued(work_items, {row.code for row in chapter_rows})

        chapters: dict[str, SpecChapter] = {}
        if spec is not None:
            models = [
                SpecChapter(
                    document_id=spec.id,
                    code=row.code,
                    title=row.title,
                    version=row.version,
                    first_page=row.first_page,
                    last_page=row.last_page,
                )
                for row in chapter_rows
            ]
            await self.checklist_repo.replace_chapters(spec.id, models)
            chapters = self._by_code(models)

        # 章碼重複時和 _by_code 一樣取先出現的，依據才會和檢核表上顯示的章節同一章
        texts: dict[str, str] = {}
        for row in chapter_rows:
            texts.setdefault(row.code, row.text)

        bases = await self._build_bases(work_items, chapters, texts)

        await self.session.commit()
        logger.info(
            "建立檢核表",
            extra=log_context(
                project_id=str(project_id),
                work_items=len(work_items),
                chapters=len(chapters),
                bases=sum(len(found) for found in bases.values()),
            ),
        )
        return self._assemble(work_items, chapters, catalogued, bases, spec)

    async def checklist(self, project_id: uuid.UUID) -> Checklist:
        """只讀已經建好的依據，不重建。

        重建要重讀 772 頁的規範書並對 1028 個工項重跑，不是 GET 該做的事；
        而且有副作用的 GET 會讓人很難推理「為什麼數字變了」。
        """
        await self._require_project(project_id)
        spec = await self._spec_document(project_id)
        chapters = (
            self._by_code(await self.checklist_repo.chapters_by_document(spec.id))
            if spec is not None
            else {}
        )
        work_items = await self.projects.work_items(project_id)
        catalogued = await self._catalogued(work_items, chapters)
        bases = await self.checklist_repo.bases_by_project(project_id)
        return self._assemble(work_items, chapters, catalogued, bases, spec)

    # --- 內部 ---

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError("找不到指定的專案")
        return project

    async def _spec_document(self, project_id: uuid.UUID) -> Document | None:
        """專案的施工規範書。沒掛就回 None，不報錯——檢核表沒有依據仍然有價值
        （工項都在），報錯會讓使用者什麼都拿不到。這和階段 1「沒掛標單就報錯」
        刻意不對稱：沒有標單時表是空的。"""
        links = await self.projects.documents_by_role(project_id, DocumentRole.SPECIFICATION)
        if not links:
            return None

        document = await self.documents.get(links[0].document_id)
        if document is None:
            # 掛了但檔案紀錄不見了，和「沒掛」是兩回事：照沒掛處理會產出一張
            # 全部「請確認依據」的表，看起來像「這個案子沒有依據」。
            raise AppError("施工規範書文件不存在，可能已被刪除")
        return document

    async def _catalogued(
        self, work_items: list[WorkItem], spec_codes: Collection[str]
    ) -> set[str]:
        """工項的章碼裡，本案規範書沒有、但全國共通的施工綱要規範（PCCES）有的那些。

        只有這種章碼才說得上「本案規範未收錄」。章碼根本不是 PCCES 的任何一章
        （2026-10-06 實測 74 個工項、17 個章碼，例如 16050 就占 32 個），沒有任何依據說它
        「應該要有」——對它說「規範書漏收」是有信心的錯，該是「請確認依據」。
        反過來，本案規範書自己的章不一定在 PCCES 裡（實測 86 章有 12 章不在，
        例如 05503），所以「規範書有沒有這章」要先比，PCCES 只用來判斷漏收。

        沒有任何規範書章節時整個略過：那時什麼都不能說，也不必去讀目錄。
        """
        if not spec_codes:
            return set()
        missing = {
            code
            for item in work_items
            if (code := self._chapter_code(item)) is not None and code not in spec_codes
        }
        return {
            code for code in missing if await self._pcces.get_detail(f"PCCES-{code}") is not None
        }

    async def _build_bases(
        self,
        work_items: list[WorkItem],
        chapters: dict[str, SpecChapter],
        texts: dict[str, str],
    ) -> dict[uuid.UUID, list[WorkItemBasis]]:
        # 同一章會對到很多工項（實測 01271 一章就 83 個），抽取結果快取
        cache: dict[str, list[tuple[str, str]]] = {}
        bases: list[WorkItemBasis] = []

        for item in work_items:
            code = self._chapter_code(item)
            if code is None or code not in chapters:
                continue
            if code not in cache:
                cache[code] = await self._references_in(texts.get(code, ""))
            for basis_type, reference in cache[code]:
                bases.append(
                    WorkItemBasis(
                        work_item_id=item.id,
                        basis_type=basis_type,
                        reference=reference,
                        # 不寫小節號：basis_block 不回傳它，而規範書的相關準則不一定在
                        # 1.4（實測 01523、01574、02786、03110 四章是 1.3）。寫一個
                        # 看起來精確、實際是編造的出處，比不寫更糟。
                        detail=f"第{code}章 相關準則",
                    )
                )

        await self.checklist_repo.replace_bases([item.id for item in work_items], bases)
        grouped: dict[uuid.UUID, list[WorkItemBasis]] = {}
        for basis in bases:
            grouped.setdefault(basis.work_item_id, []).append(basis)
        return grouped

    async def _references_in(self, chapter_text: str) -> list[tuple[str, str]]:
        block = basis_block(chapter_text)
        if not block:
            return []
        candidates, record = await self.extractor.extract(block)
        if record is not None:
            # 規則與字典都抽不到時才會走到 LLM。每一次 LLM 呼叫都要留稽核紀錄
            # （docs/architecture.md 第 5 節），呼叫端不寫就沒有人會寫。
            await self.audit.log_ai_call(record)
        return [
            (str(candidate.regulation_type), candidate.raw_text[:512]) for candidate in candidates
        ]

    def _assemble(
        self,
        work_items: list[WorkItem],
        chapters: dict[str, SpecChapter],
        catalogued: set[str],
        bases: dict[uuid.UUID, list[WorkItemBasis]],
        spec: Document | None,
    ) -> Checklist:
        rows = []
        for item in work_items:
            code = self._chapter_code(item)
            found = bases.get(item.id, [])
            rows.append(
                ChecklistRow(
                    work_item=item,
                    result=self._result_for(item, chapters, catalogued, found),
                    chapter=chapters.get(code) if code is not None else None,
                    bases=found,
                )
            )

        warning = None
        if spec is not None and spec.parse_quality == ParseQuality.DEGRADED:
            warning = f"本案施工規範書的解析品質不佳：{spec.parse_quality_note}。依據可能不完整。"
        return Checklist(rows=rows, spec_warning=warning)

    @staticmethod
    def _by_code(chapters: list[SpecChapter]) -> dict[str, SpecChapter]:
        """依章碼索引。章碼在一份規範書裡應該唯一（實測 86 章無重複）；
        重複時取先出現的，build 與 checklist 兩條路徑才會挑到同一章。"""
        indexed: dict[str, SpecChapter] = {}
        for chapter in chapters:
            indexed.setdefault(chapter.code, chapter)
        return indexed

    @staticmethod
    def _chapter_code(item: WorkItem) -> str | None:
        """計價代碼前 5 碼 = 施工綱要規範章碼。"""
        if not item.cost_code or len(item.cost_code) < 5:
            return None
        return item.cost_code[:5]

    def _result_for(
        self,
        item: WorkItem,
        chapters: dict[str, SpecChapter],
        catalogued: set[str],
        bases: list[WorkItemBasis],
    ) -> CheckResult:
        code = self._chapter_code(item)
        if code is None:
            return CheckResult.NEEDS_CONFIRMATION
        if code in chapters:
            return CheckResult.OK if bases else CheckResult.NEEDS_CONFIRMATION
        # 本案規範書沒有這一章。只有「綱要規範有、本案沒收」才是漏收（見 _catalogued）；
        # 完全沒掛規範書時 catalogued 是空的，不會把「你還沒上傳規範書」指成「漏收這一章」。
        if code in catalogued:
            return CheckResult.SPEC_NOT_INCLUDED
        return CheckResult.NEEDS_CONFIRMATION
