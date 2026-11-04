"""檢核表的 schema。"""

import uuid
from collections import Counter

from pydantic import BaseModel

from app.core.enums import CheckResult
from app.services.checklist_service import Checklist, ChecklistRow

#: 前半句出自 1.契約書.pdf 第 1 頁的契約文件優先順序（第八款），是專案層級的依據。
#: 2026-11 起逐工項的「契約」欄列出契約書提到該工項的頁碼；條號是 Word 自動編號、PDF 讀不到，
#: 這句話要跟著檢核表走到畫面與匯出，讓人知道契約欄是「提到的地方」，不是條號。
CONTRACT_NOTE = (
    "契約文件優先順序：招標文件內之標價清單，其品項名稱、規格、數量，"
    "優於招標文件內其他文件之內容。「契約」欄列出契約書提到該工項（或所屬分項）的頁碼與標題，"
    "不代表契約對該工項另有規定。"
)


class BasisOut(BaseModel):
    """一條依據：本案規範書某一章的「相關準則」裡寫了什麼，原樣引述。

    名稱是引述，不是查證過的事實；`verification_status` 才說明它查到什麼程度，
    而且只對法規查得到：標準（CNS／ASTM／ISO／JIS）沒有資料來源，法規則只採
    完全同名比對（見 `verification_status` 的說明）。`basis_type` 只說明名稱屬於
    哪一類，同樣不說明它被查證到什麼程度。
    """

    basis_type: str
    reference: str
    #: 出處，只寫到章（`第01725章 相關準則`）。不寫小節號：相關準則不一定在 1.4
    #: （實測 01523、01574、02786、03110 四章編在 1.3），不知道的小節號不能宣稱。
    detail: str | None
    #: 法規查證結果：`ACTIVE`、`AMENDED`、`REPEALED`，或 null。**null 代表未查證**——
    #: 標準沒有資料來源可查，法規則是在全國法規索引裡找不到完全同名。null 不等於
    #: 「查無此法規」：建築技術規則是真的法規，索引只以四編登錄它；屋內線路裝置規則是
    #: 2018 年已更名為用戶用電設備裝置規則的舊名稱，規範書還在引用。這裡永遠不會是
    #: `NOT_FOUND`，前端不要把 null 顯示成查無此法規。
    verification_status: str | None


class ChapterOut(BaseModel):
    code: str
    title: str
    #: 規範書頁首的版本，不含「V」字首，例如 `3.0`
    version: str


class DrawingOut(BaseModel):
    """契約圖的一張圖。只有圖號與圖名——圖面內容系統讀不懂，要人去翻。"""

    sheet_no: str
    title: str
    page: int
    #: 圖號圖名由 OCR 從掃描的標題欄讀出，可能有錯字；圖號讀不到時是「第N頁」
    is_ocr: bool = False


class MethodOut(BaseModel):
    """工法欄（階段 4）。施工規範列出多種工法時才有。"""

    options: list[str]
    #: 契約文件指定的工法；null = 未指定，要人看相關圖號決定
    selected: str | None
    #: 指定的出處，或未指定的原因
    evidence: str | None


class ContractRefOut(BaseModel):
    """契約書提到這個工項的一處。契約條號是 Word 自動編號、PDF 文字層沒有，所以只給頁碼與
    前面最近的小標題，不推算條號。只是「契約提到這裡」，不代表契約對這個工項有特別規定。"""

    page: int | None
    heading: str | None
    excerpt: str
    #: 用哪個詞找到的：工項主體（「模板」）或所屬分項（「開關箱」）
    keyword: str


class ChecklistItemOut(BaseModel):
    work_item_id: uuid.UUID
    item_no: str
    name: str
    result: CheckResult
    #: 計價代碼前 5 碼，沒有計價代碼時是 None。和 `chapter` 不同，它只取決於工項自己：
    #: 「本案規範未收錄」的列 `chapter` 是 None，要依章分流那些列就靠這個欄位。
    #: 它只是代碼的前 5 碼，不保證是施工綱要規範或本案規範書裡真有的章。
    chapter_code: str | None
    #: 本案規範書裡對得到的那一章。本案沒收錄、或根本沒有章碼時是 None
    chapter: ChapterOut | None
    bases: list[BasisOut]
    #: 所有成立的問題，依優先序；`result` 是第一個。沒有問題時是空清單
    issues: list[CheckResult]
    #: 圖名和工項相關的契約圖（階段 2、4）
    drawings: list[DrawingOut]
    method: MethodOut | None
    #: 契約欄：契約書提到這個工項（或它所屬分項）的地方，最多三處。不影響 result
    contract_refs: list[ContractRefOut]

    @classmethod
    def from_row(cls, row: ChecklistRow) -> "ChecklistItemOut":
        chapter = row.chapter
        return cls(
            work_item_id=row.work_item.id,
            item_no=row.work_item.item_no,
            name=row.work_item.name,
            result=row.result,
            chapter_code=row.chapter_code,
            chapter=(
                ChapterOut(code=chapter.code, title=chapter.title, version=chapter.version)
                if chapter is not None
                else None
            ),
            bases=[
                BasisOut(
                    basis_type=basis.basis_type,
                    reference=basis.reference,
                    detail=basis.detail,
                    verification_status=basis.verification_status,
                )
                for basis in row.bases
            ],
            issues=row.issues,
            drawings=[
                DrawingOut(sheet_no=d.sheet_no, title=d.title, page=d.page, is_ocr=d.is_ocr) for d in row.drawings
            ],
            method=(
                MethodOut(
                    options=list(row.method.options),
                    selected=row.method.selected,
                    evidence=row.method.evidence,
                )
                if row.method is not None
                else None
            ),
            contract_refs=[
                ContractRefOut(page=r.page, heading=r.heading, excerpt=r.excerpt, keyword=r.keyword)
                for r in row.contract_refs
            ],
        )


class ChecklistSummaryOut(BaseModel):
    ok: int
    spec_not_included: int
    needs_confirmation: int
    boq_not_in_drawings: int
    method_undecided: int


class ChecklistOut(BaseModel):
    total: int
    #: 五個值相加等於 total。CheckResult 新增值時這裡要同步加一欄，
    #: 否則新值會從摘要裡消失、總和對不上 total。
    summary: ChecklistSummaryOut
    contract_note: str
    #: 規範書解析品質不佳時的警告，依據可能殘缺。正常時是 null。
    spec_warning: str | None
    #: 專案有沒有掛讀得到圖號的契約圖。沒有時不判斷「標單有，契約圖沒有」
    has_drawings: bool
    #: 掛了契約圖卻讀不到任何一張（多半是掃描檔）時的說明。正常時是 null。
    drawing_warning: str | None
    #: 契約圖有、標單沒有：圖名對不到任何工項的圖（階段 2，專案層級，不逐工項列）
    drawings_without_items: list[DrawingOut]
    items: list[ChecklistItemOut]

    @classmethod
    def from_checklist(cls, checklist: Checklist) -> "ChecklistOut":
        rows = checklist.rows
        counts = Counter(row.result for row in rows)
        return cls(
            total=len(rows),
            summary=ChecklistSummaryOut(
                ok=counts[CheckResult.OK],
                spec_not_included=counts[CheckResult.SPEC_NOT_INCLUDED],
                needs_confirmation=counts[CheckResult.NEEDS_CONFIRMATION],
                boq_not_in_drawings=counts[CheckResult.BOQ_NOT_IN_DRAWINGS],
                method_undecided=counts[CheckResult.METHOD_UNDECIDED],
            ),
            contract_note=CONTRACT_NOTE,
            spec_warning=checklist.spec_warning,
            has_drawings=checklist.has_drawings,
            drawing_warning=checklist.drawing_warning,
            drawings_without_items=[
                DrawingOut(sheet_no=d.sheet_no, title=d.title, page=d.page, is_ocr=d.is_ocr)
                for d in checklist.drawings_without_items
            ],
            items=[ChecklistItemOut.from_row(row) for row in rows],
        )


class QualityStandardRowOut(BaseModel):
    stage: str
    item: str
    standard: str
    timing: str
    method: str
    frequency: str
    handling: str
    record: str
    #: 出處：第03210章 3.4.1
    note: str


class QualityStandardOut(BaseModel):
    """品質管理標準表初稿（橘框表單）。欄位照秀山整體品質計畫的品質管理標準表。"""

    chapter_code: str
    chapter_title: str
    title: str
    #: 一定要給人看到：這是初稿，要品管人員檢討補正
    notice: str
    columns: list[str]
    rows: list[QualityStandardRowOut]

    @classmethod
    def from_draft(cls, draft) -> "QualityStandardOut":
        from dataclasses import asdict

        from app.specs.quality_standard import COLUMNS

        return cls(
            chapter_code=draft.chapter_code,
            chapter_title=draft.chapter_title,
            title=draft.title,
            notice=draft.notice,
            columns=list(COLUMNS),
            rows=[QualityStandardRowOut(**asdict(row)) for row in draft.rows],
        )
