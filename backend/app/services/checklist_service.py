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
from app.core.errors import AppError, NotFoundError, ProjectNotFoundError
from app.core.logging import log_context
from app.extractors import ExtractionPipeline
from app.models.checklist import (
    DrawingSheet,
    SpecChapter,
    WorkItemBasis,
    WorkItemContractRef,
    WorkItemMethod,
)
from app.models.document import Document
from app.models.project import Project, WorkItem
from app.repositories.audit import AuditRepository
from app.repositories.checklist import ChecklistRepository
from app.repositories.documents import DocumentRepository
from app.repositories.projects import ProjectRepository
from app.services.basis_verifier import verify_names, verify_standards
from app.sources.pcces_source import PccesSource
from app.sources.standards_demo_source import DemoStandardsSource, standard_key
from app.sources.taiwan_law_source import TaiwanLawSource
from app.parsers import parse_document
from app.specs import basis_block, read_spec_chapters
from app.specs.contract_reader import contract_passages, item_keywords, mentions
from app.specs.cross_rules import CrossRuleReminder, remind
from app.specs.drawing_reader import read_drawing_sheets, related_sheets
from app.specs.function_test import FunctionTestDraft, draft_function_test, is_equipment_chapter
from app.specs.method_statement import MethodStatement, draft_method_statement
from app.specs.plan_review import PlanReview, review_plan
from app.specs.quality_standard import QualityStandardDraft, draft_quality_standard
from app.specs.method_reader import choose_method, method_options
from app.workitems.boq_reader import BoqLayout, boq_layout, read_boq

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
    #: 契約欄：契約書提到這個工項（或它所屬分項）的地方。只是指出處，不影響 result
    contract_refs: list[WorkItemContractRef] = field(default_factory=list)


@dataclass(frozen=True)
class Checklist:
    rows: list[ChecklistRow]
    #: 規範書解析品質不佳時的警告。依據可能殘缺，使用者必須知道。
    spec_warning: str | None = None
    #: 專案有沒有掛**讀得到圖號的**契約圖（有才判斷「標單有，契約圖沒有」）
    has_drawings: bool = False
    #: 掛了契約圖卻一張圖都讀不到（多半是掃描檔）時的說明
    drawing_warning: str | None = None
    #: 契約圖有、標單沒有：圖名對不到任何工項的圖（階段 2，專案層級）
    drawings_without_items: list[DrawingSheet] = field(default_factory=list)


DRAWING_PARTLY_UNREADABLE = (
    "這幾冊契約圖讀不到任何圖號與圖名（多半是掃描檔）：{files}。"
    "只用讀得到的幾冊判斷「標單有，契約圖沒有」，相關工項可能被誤判。"
)

DRAWING_UNREADABLE = (
    "契約圖讀不到任何圖號與圖名（多半是掃描檔），本次不判斷「標單有，契約圖沒有」。"
    "請改附 CAD 匯出的 PDF，或含圖說目錄（一行一張圖號與圖名）的 PDF。"
)

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
        sheets, unreadable = await self._build_drawing_sheets(project_id)
        methods = await self._build_methods(project_id, work_items, texts)
        layout = await self._boq_layout(project_id)
        contract_refs = await self._build_contract_refs(project_id, work_items, layout)

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
        return self._assemble(
            work_items, chapters, catalogued, bases, spec, sheets, methods, layout, unreadable, contract_refs
        )

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
        sheets, unreadable = None, []
        for drawing in await self._drawing_documents(project_id):
            stored = await self.checklist_repo.drawing_sheets_by_document(drawing.id)
            sheets = (sheets or []) + stored
            if not stored:
                unreadable.append(drawing.filename)
        methods = await self.checklist_repo.methods_by_project(project_id)
        layout = await self._boq_layout(project_id)
        contract_refs = await self.checklist_repo.contract_refs_by_project(project_id)
        return self._assemble(
            work_items, chapters, catalogued, bases, spec, sheets, methods, layout, unreadable, contract_refs
        )

    async def quality_standard_draft(self, project_id: uuid.UUID, chapter_code: str) -> QualityStandardDraft:
        """品質管理標準表初稿（橘框表單）：從本案施工規範那一章擷取。章節正文不存資料庫，
        每次重讀規範書（秀山 772 頁約數秒）；這是給人下載後修改的初稿，不需要快取。"""
        chapter = await self._spec_chapter(project_id, chapter_code)
        return draft_quality_standard(chapter.code, chapter.title, chapter.text)

    async def method_statement_draft(self, project_id: uuid.UUID, chapter_code: str) -> MethodStatement:
        """施工要領初稿：施工方法取自規範那一章的第3節，使用材料取自標單裡計價代碼屬於這一章的工項。"""
        chapter = await self._spec_chapter(project_id, chapter_code)
        materials = [
            item.name
            for item in await self.projects.work_items(project_id)
            if item.is_leaf and self._chapter_code(item) == chapter_code
        ]
        return draft_method_statement(chapter.code, chapter.title, chapter.text, materials)

    async def function_test_draft(self, project_id: uuid.UUID, chapter_code: str) -> FunctionTestDraft:
        """設備功能運轉檢測標準表／測試抽驗標準表初稿。只有機電章（11／13／14／15／16 開頭）有。"""
        if not is_equipment_chapter(chapter_code):
            raise AppError(f"第{chapter_code}章不是機電設備章，沒有設備功能運轉檢測")
        chapter = await self._spec_chapter(project_id, chapter_code)
        return draft_function_test(chapter.code, chapter.title, chapter.text)

    async def plan_review(self, project_id: uuid.UUID) -> PlanReview:
        """品質計畫審查（橘框對綠框）：掛成「品質計畫」的 docx 裡的品質管理標準表，漏了哪些規範的可檢查標準。"""
        await self._require_project(project_id)
        plan = await self._role_document(project_id, DocumentRole.QUALITY_PLAN)
        if plan is None:
            raise AppError("專案還沒有掛品質計畫（承攬廠商的整體品質計畫）")
        if not plan.filename.lower().endswith(".docx"):
            raise AppError("品質計畫審查目前只讀 Word（.docx）：PDF 的表格欄位讀不準")
        spec = await self._spec_document(project_id)
        if spec is None:
            raise AppError("專案還沒有掛施工規範，沒有綠框可以比對")
        review = review_plan(Path(plan.storage_path), read_spec_chapters(Path(spec.storage_path)))
        return PlanReview(plan.filename, review.tables)

    async def cross_rule_reminders(self, project_id: uuid.UUID) -> list[CrossRuleReminder]:
        """法規雙重規範提醒：標單工項與契約圖圖名裡出現目錄（data/cross_rules.json）的觸發詞。只讀已存的資料。"""
        await self._require_project(project_id)
        texts = [
            ("標單", f"{item.item_no} {item.name}")
            for item in await self.projects.work_items(project_id)
            if item.is_leaf
        ]
        for drawing in await self._drawing_documents(project_id):
            texts += [
                ("契約圖", f"{sheet.sheet_no} {sheet.title}")
                for sheet in await self.checklist_repo.drawing_sheets_by_document(drawing.id)
            ]
        return remind(texts)

    async def plan_sources(self, project_id: uuid.UUID) -> tuple[str, list, dict[str, list[str]]]:
        """組整份計畫用的材料：（工程名稱, 標單用到的規範章（依規範順序）, 每章的標單工項名稱）。"""
        project = await self._require_project(project_id)
        spec = await self._spec_document(project_id)
        if spec is None:
            raise AppError("專案還沒有掛施工規範，無法產生計畫初稿")
        materials: dict[str, list[str]] = {}
        for item in await self.projects.work_items(project_id):
            code = self._chapter_code(item)
            if item.is_leaf and code:
                materials.setdefault(code, []).append(item.name)
        chapters = [c for c in read_spec_chapters(Path(spec.storage_path)) if c.code in materials]
        if not chapters:
            raise AppError("標單的工項對不到本案施工規範的任何一章，先建立工項並確認規範書")
        return project.name, list({c.code: c for c in chapters}.values()), materials

    async def _spec_chapter(self, project_id: uuid.UUID, chapter_code: str):
        await self._require_project(project_id)
        spec = await self._spec_document(project_id)
        if spec is None:
            raise AppError("專案還沒有掛施工規範，無法產生橘框表單初稿")
        chapter = next((c for c in read_spec_chapters(Path(spec.storage_path)) if c.code == chapter_code), None)
        if chapter is None:
            raise NotFoundError(f"本案施工規範沒有第{chapter_code}章")
        return chapter

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

    async def _drawing_documents(self, project_id: uuid.UUID) -> list[Document]:
        """掛成契約圖的每一份文件。契約圖常分成建築、結構、水電好幾冊。"""
        documents = []
        for link in await self.projects.documents_by_role(project_id, DocumentRole.DRAWING):
            document = await self.documents.get(link.document_id, self.tenant_id)
            if document is not None:
                documents.append(document)
        return documents

    async def _build_drawing_sheets(
        self, project_id: uuid.UUID
    ) -> tuple[list[DrawingSheet] | None, list[str]]:
        """讀每一冊契約圖的圖號索引。沒掛契約圖回傳 (None, [])（不判斷階段 2）；
        第二個值是一張圖都讀不到的那幾冊檔名。"""
        documents = await self._drawing_documents(project_id)
        if not documents:
            return None, []
        sheets: list[DrawingSheet] = []
        unreadable: list[str] = []
        for drawing in documents:
            stored = await self.checklist_repo.drawing_sheets_by_document(drawing.id)
            if stored and all(sheet.is_ocr for sheet in stored):
                # 掃描冊 OCR 一頁約 2 秒（秀山三冊 286 頁約 10 分鐘），讀過就不重讀
                sheets.extend(stored)
                continue
            found = [
                DrawingSheet(
                    document_id=drawing.id,
                    sheet_no=row.sheet_no,
                    title=row.title,
                    page=row.page,
                    is_ocr=row.is_ocr,
                )
                for row in read_drawing_sheets(Path(drawing.storage_path))
            ]
            await self.checklist_repo.replace_drawing_sheets(drawing.id, found)
            sheets.extend(found)
            if not found:
                unreadable.append(drawing.filename)
        return sheets, unreadable

    async def _build_contract_refs(
        self, project_id: uuid.UUID, work_items: list[WorkItem], layout: BoqLayout
    ) -> dict[uuid.UUID, list[WorkItemContractRef]]:
        """契約欄：每個計價工項在契約書裡被提到的地方（工項主體，找不到再找所屬分項）。

        契約條號是 Word 自動編號、文字層沒有，出處寫頁碼與前面最近的小標題（contract_reader）。
        同一個詞會被很多工項用到，依詞快取。
        """
        passages = []
        for link in await self.projects.documents_by_role(project_id, DocumentRole.CONTRACT):
            document = await self.documents.get(link.document_id, self.tenant_id)
            if document is None:
                continue
            try:
                passages += contract_passages(parse_document(Path(document.storage_path)).sections)
            except AppError as exc:
                logger.warning(
                    "契約書讀取失敗，契約欄略過",
                    extra=log_context(document_id=str(document.id), error=exc.message),
                )
        found: dict[uuid.UUID, list[WorkItemContractRef]] = {}
        if passages:
            cache: dict[str, list] = {}
            for item in work_items:
                if not item.is_leaf:
                    continue
                for keyword in item_keywords(item.name, layout.sections_of(item.item_no)):
                    if keyword not in cache:
                        cache[keyword] = mentions(keyword, passages)
                    if cache[keyword]:
                        found[item.id] = [
                            WorkItemContractRef(
                                work_item_id=item.id,
                                page=m.page,
                                heading=m.heading,
                                excerpt=m.excerpt,
                                keyword=keyword,
                            )
                            for m in cache[keyword]
                        ]
                        break
        await self.checklist_repo.replace_contract_refs(
            [item.id for item in work_items], [ref for refs in found.values() for ref in refs]
        )
        return found

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

        # 帶標準編號的（CNS 3090、ASTM C39）是標準，只能拿去標準目錄查；其餘都送全國法規
        # 索引查完全同名。不能用 basis_type 分：它是看名稱字尾猜的，「營造安全衛生設施標準」
        # 以「標準」結尾被歸成 STANDARD，但它是法規命令，全國法規資料庫查得到。
        # verify_names 只採完全同名，多送幾個名稱不會產生模糊誤判。依相異名稱查一次。
        numbered = {b.reference for b in bases if standard_key(b.reference) is not None}
        candidates = {b.reference for b in bases} - numbered
        statuses = await verify_names(candidates, TaiwanLawSource())
        # 標準只有在啟用了有版次資料的標準目錄時才查（目前只有示範用的 standards_demo）
        if DemoStandardsSource.source_name in settings.regulation_sources:
            statuses |= await verify_standards(numbered, DemoStandardsSource())
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
        layout: BoqLayout | None = None,
        unreadable: list[str] | None = None,
        contract_refs: dict[uuid.UUID, list[WorkItemContractRef]] | None = None,
    ) -> Checklist:
        methods = methods or {}
        contract_refs = contract_refs or {}
        layout = layout or BoqLayout()
        drawing_warning = None
        if sheets == []:
            # 讀不到標題欄（掃描檔、OCR 不能用）。當成沒有契約圖，否則每個工項都會變成「標單有，契約圖沒有」
            sheets = None
            drawing_warning = DRAWING_UNREADABLE
        elif unreadable:
            drawing_warning = DRAWING_PARTLY_UNREADABLE.format(files="、".join(unreadable))
        rows = []
        matched_sheets: set[str] = set()
        for item in work_items:
            code = self._chapter_code(item)
            found = bases.get(item.id, [])
            drawings = self._related_drawings(item, layout, sheets) if sheets and item.is_leaf else []
            matched_sheets.update(sheet.sheet_no for sheet in drawings)
            method = methods.get(item.id)

            issues = []
            if sheets is not None and self._should_be_drawn(item, layout.direct_prefix) and not drawings:
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
                    contract_refs=contract_refs.get(item.id, []),
                )
            )

        warning = None
        if spec is not None and spec.parse_quality == ParseQuality.DEGRADED:
            warning = f"本案施工規範書的解析品質不佳：{spec.parse_quality_note}。依據可能不完整。"
        return Checklist(
            rows=rows,
            spec_warning=warning,
            has_drawings=sheets is not None,
            drawing_warning=drawing_warning,
            # 依圖號排：建表時 sheets 是頁碼順序、讀回時是圖號順序，兩條路要給同一張表
            drawings_without_items=sorted(
                (s for s in sheets or [] if s.sheet_no not in matched_sheets),
                key=lambda s: s.sheet_no,
            ),
        )

    @classmethod
    def _should_be_drawn(cls, item: WorkItem, direct_prefix: str | None = None) -> bool:
        """這個工項應該在契約圖上找得到嗎？

        只看實際工項（有單位的），並排除第 01 類章碼：01xxx 是一般要求（施工測量、
        安全衛生、品質管理），本來就不會畫在圖上，標成「契約圖沒有」只是雜訊。
        標單有「直接工程費」時，只看它底下的工項：環保清潔費、職安費、品管費、保險、
        利潤、稅捐這些間接工程費不會畫在圖上（秀山標單有 35 項）。
        """
        if direct_prefix is not None and not item.item_no.startswith(direct_prefix):
            return False
        code = cls._chapter_code(item)
        return item.is_leaf and not (code or "").startswith("01")

    async def _boq_layout(self, project_id: uuid.UUID) -> BoqLayout:
        """標單的群組結構（直接工程費、分項）。群組列不進資料庫，要從標單本身讀；
        讀不到標單就用空的（不限直接工程費、不用分項比對），維持舊行為。"""
        boq = await self._role_document(project_id, DocumentRole.BOQ)
        if boq is None:
            return BoqLayout()
        try:
            return boq_layout(read_boq(Path(boq.storage_path)))
        except AppError:
            return BoqLayout()

    @staticmethod
    def _related_drawings(item: WorkItem, layout: BoqLayout, sheets: list[DrawingSheet]) -> list[DrawingSheet]:
        """工項名稱或它所屬分項名稱對得上的圖。

        真實標單的計價工項多半對不到圖名（「KW-MP PANEL」），契約圖畫的是分項（「開關箱單線圖」）。
        秀山標單逐項比對時約 7 成對不到。
        """
        found: dict[str, DrawingSheet] = {}
        for name in (item.name, *layout.sections_of(item.item_no)):
            for sheet in related_sheets(name, sheets):
                found.setdefault(f"{sheet.document_id}:{sheet.sheet_no}", sheet)
        return sorted(found.values(), key=lambda s: s.sheet_no)

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
