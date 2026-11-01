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
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_llm_provider
from app.core.config import settings
from app.core.enums import CheckResult, DocumentRole, ParseQuality, RegulationType
from app.core.errors import AppError, ProjectNotFoundError
from app.core.logging import log_context
from app.extractors import ExtractionPipeline
from app.models.checklist import DrawingSheet, SpecChapter, WorkItemBasis, WorkItemMethod
from app.models.document import Document
from app.models.project import Project, WorkItem
from app.repositories.audit import AuditRepository
from app.repositories.checklist import ChecklistRepository
from app.repositories.documents import DocumentRepository
from app.repositories.projects import ProjectRepository
from app.services.basis_verifier import verify_names, verify_standards
from app.sources.pcces_source import PccesSource
from app.sources.standards_demo_source import DemoStandardsSource
from app.sources.taiwan_law_source import TaiwanLawSource
from app.parsers import parse_document
from app.specs import basis_block, read_spec_chapters
from app.specs.drawing_reader import read_drawing_sheets, related_sheets
from app.specs.method_reader import choose_method, method_options

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChecklistRow:
    work_item: WorkItem
    result: CheckResult
    #: 計價代碼前 5 碼（`_chapter_code` 的結果），沒有計價代碼時是 None。只取決於工項
    #: 自己，不管本案規範書有沒有這一章，所以「本案規範未收錄」的列也有；那種列的
    #: `chapter` 是 None，少了這個欄位就說不出缺的是哪一章。
    chapter_code: str | None
    chapter: SpecChapter | None
    bases: list[WorkItemBasis]
    #: 所有成立的問題，依優先序；result 是第一個（沒有問題時是 OK）
    issues: list[CheckResult] = field(default_factory=list)
    #: 圖名和工項相關的契約圖（階段 2、4）。沒掛契約圖時是空的
    drawings: list[DrawingSheet] = field(default_factory=list)
    #: 工法欄（階段 4）。施工規範沒列出多種工法時是 None
    method: WorkItemMethod | None = None


@dataclass(frozen=True)
class Checklist:
    rows: list[ChecklistRow]
    #: 規範書解析品質不佳時的警告。依據可能殘缺，使用者必須知道。
    spec_warning: str | None = None
    #: 專案有沒有掛契約圖（有掛才判斷「標單有，契約圖沒有」）
    has_drawings: bool = False
    #: 契約圖有、標單沒有：圖名對不到任何工項的圖（階段 2，專案層級）
    drawings_without_items: list[DrawingSheet] = field(default_factory=list)


#: 原 spec 第 6 節的優先序：工項來源不一致 > 工法未定 > 依據不全
_PRIORITY = (
    CheckResult.BOQ_NOT_IN_DRAWINGS,
    CheckResult.METHOD_UNDECIDED,
    CheckResult.SPEC_NOT_INCLUDED,
    CheckResult.NEEDS_CONFIRMATION,
)


class ChecklistService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None):
        self.session = session
        self.tenant_id = tenant_id or uuid.UUID(settings.DEFAULT_TENANT_ID)
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
        sheets = await self._build_drawing_sheets(project_id)
        methods = await self._build_methods(project_id, work_items, texts)

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
        return self._assemble(work_items, chapters, catalogued, bases, spec, sheets, methods)

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
        drawing = await self._role_document(project_id, DocumentRole.DRAWING)
        sheets = (
            await self.checklist_repo.drawing_sheets_by_document(drawing.id)
            if drawing is not None
            else None
        )
        methods = await self.checklist_repo.methods_by_project(project_id)
        return self._assemble(work_items, chapters, catalogued, bases, spec, sheets, methods)

    # --- 內部 ---

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self.projects.get(project_id, self.tenant_id)
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

        document = await self.documents.get(links[0].document_id, self.tenant_id)
        if document is None:
            # 掛了但檔案紀錄不見了，和「沒掛」是兩回事：照沒掛處理會產出一張
            # 全部「請確認依據」的表，看起來像「這個案子沒有依據」。
            raise AppError("施工規範書文件不存在，可能已被刪除")
        return document

    async def _role_document(self, project_id: uuid.UUID, role: str) -> Document | None:
        links = await self.projects.documents_by_role(project_id, role)
        if not links:
            return None
        return await self.documents.get(links[0].document_id, self.tenant_id)

    async def _build_drawing_sheets(self, project_id: uuid.UUID) -> list[DrawingSheet] | None:
        """讀契約圖的圖號索引。沒掛契約圖回傳 None（不判斷階段 2），讀到零張圖回傳空清單。"""
        drawing = await self._role_document(project_id, DocumentRole.DRAWING)
        if drawing is None:
            return None
        sheets = [
            DrawingSheet(document_id=drawing.id, sheet_no=row.sheet_no, title=row.title, page=row.page)
            for row in read_drawing_sheets(Path(drawing.storage_path))
        ]
        await self.checklist_repo.replace_drawing_sheets(drawing.id, sheets)
        return sheets

    async def _contract_texts(self, project_id: uuid.UUID) -> list[tuple[str, str]]:
        """契約書與其他附件（需求書等）的全文，用來找指定了哪種工法。讀不了的檔案略過。"""
        texts = []
        for role in (DocumentRole.CONTRACT, DocumentRole.OTHER):
            for link in await self.projects.documents_by_role(project_id, role):
                document = await self.documents.get(link.document_id, self.tenant_id)
                if document is None:
                    continue
                try:
                    parsed = parse_document(Path(document.storage_path))
                except AppError as exc:
                    logger.warning(
                        "契約文件讀取失敗，略過",
                        extra=log_context(document_id=str(document.id), error=exc.message),
                    )
                    continue
                texts.append((document.filename, "\n".join(s.content for s in parsed.sections)))
        return texts

    async def _build_methods(
        self, project_id: uuid.UUID, work_items: list[WorkItem], texts: dict[str, str]
    ) -> dict[uuid.UUID, WorkItemMethod]:
        """工法欄：本案規範書那一章列出多種工法的工項，才建一筆。"""
        choices: dict[str, object] = {}
        contract_texts: list[tuple[str, str]] | None = None
        methods: dict[uuid.UUID, WorkItemMethod] = {}
        for item in work_items:
            code = self._chapter_code(item)
            if code is None or code not in texts:
                continue
            if code not in choices:
                options = method_options(texts[code])
                if options and contract_texts is None:
                    contract_texts = await self._contract_texts(project_id)
                choices[code] = choose_method(options, contract_texts or []) if options else None
            choice = choices[code]
            if choice is not None:
                methods[item.id] = WorkItemMethod(
                    work_item_id=item.id,
                    options=choice.options,
                    selected=choice.selected,
                    evidence=choice.evidence,
                )
        await self.checklist_repo.replace_methods([item.id for item in work_items], list(methods.values()))
        return methods

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
        # 同一章會對到很多工項，抽取結果依章碼快取。實測（2026-10-07，真實標單與規範書）：
        # 251 個工項對到規範書的 31 章，最多的 16401 一章就有 97 個；其中 30 章宣告了相關
        # 準則，所以只抽取 30 次，不快取要 249 次。
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

        # 只送非標準的名稱去查：標準（CNS/ASTM/ISO/JIS）沒有資料來源可查，
        # 送去只會得到模糊候選。依相異名稱查一次，不是每筆依據查一次。
        candidates = {
            basis.reference
            for basis in bases
            if basis.basis_type != RegulationType.STANDARD
        }
        statuses = await verify_names(candidates, TaiwanLawSource())
        # 標準只有在啟用了有版次資料的標準目錄時才查（目前只有示範用的 standards_demo）
        if DemoStandardsSource.source_name in settings.regulation_sources:
            standards = {b.reference for b in bases if b.basis_type == RegulationType.STANDARD}
            statuses |= await verify_standards(standards, DemoStandardsSource())
        for basis in bases:
            basis.verification_status = statuses.get(basis.reference)

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
        sheets: list[DrawingSheet] | None = None,
        methods: dict[uuid.UUID, WorkItemMethod] | None = None,
    ) -> Checklist:
        methods = methods or {}
        rows = []
        matched_sheets: set[str] = set()
        for item in work_items:
            code = self._chapter_code(item)
            found = bases.get(item.id, [])
            drawings = related_sheets(item.name, sheets) if sheets and item.is_leaf else []
            matched_sheets.update(sheet.sheet_no for sheet in drawings)
            method = methods.get(item.id)

            issues = []
            if sheets is not None and self._should_be_drawn(item) and not drawings:
                issues.append(CheckResult.BOQ_NOT_IN_DRAWINGS)
            if method is not None and method.selected is None:
                issues.append(CheckResult.METHOD_UNDECIDED)
            basis_result = self._result_for(item, chapters, catalogued, found)
            if basis_result != CheckResult.OK:
                issues.append(basis_result)
            issues.sort(key=_PRIORITY.index)

            rows.append(
                ChecklistRow(
                    work_item=item,
                    result=issues[0] if issues else CheckResult.OK,
                    chapter_code=code,
                    chapter=chapters.get(code) if code is not None else None,
                    bases=found,
                    issues=issues,
                    drawings=drawings,
                    method=method,
                )
            )

        warning = None
        if spec is not None and spec.parse_quality == ParseQuality.DEGRADED:
            warning = f"本案施工規範書的解析品質不佳：{spec.parse_quality_note}。依據可能不完整。"
        return Checklist(
            rows=rows,
            spec_warning=warning,
            has_drawings=sheets is not None,
            # 依圖號排：建表時 sheets 是頁碼順序、讀回時是圖號順序，兩條路要給同一張表
            drawings_without_items=sorted(
                (s for s in sheets or [] if s.sheet_no not in matched_sheets),
                key=lambda s: s.sheet_no,
            ),
        )

    @classmethod
    def _should_be_drawn(cls, item: WorkItem) -> bool:
        """這個工項應該在契約圖上找得到嗎？

        只看實際工項（有單位的），並排除第 01 類章碼：01xxx 是一般要求（施工測量、
        安全衛生、品質管理），本來就不會畫在圖上，標成「契約圖沒有」只是雜訊。
        """
        code = cls._chapter_code(item)
        return item.is_leaf and not (code or "").startswith("01")

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
