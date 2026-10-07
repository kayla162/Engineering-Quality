"""檢核表的 schema。"""

import uuid
from collections import Counter

from pydantic import BaseModel

from app.core.enums import CheckResult
from app.services.checklist_service import Checklist, ChecklistRow

#: 契約是專案層級的依據，不逐工項列——理由見階段 3 spec 第 3.1 節。
#: 前半句出自 1.契約書.pdf 第 1 頁的契約文件優先順序（第八款）。
#: 這句話要跟著檢核表走到畫面與匯出，否則沒有人知道契約欄去哪了。
CONTRACT_NOTE = (
    "契約文件優先順序：招標文件內之標價清單，其品項名稱、規格、數量，"
    "優於招標文件內其他文件之內容。契約依據為專案層級，不逐工項列出。"
)


class BasisOut(BaseModel):
    """一條依據：本案規範書某一章的「相關準則」裡寫了什麼，原樣引述。

    刻意沒有「是否查證過」這類欄位：本階段沒有任何一筆依據被查證過——標準
    （CNS／ASTM／ISO／JIS）沒有資料來源，法規也還沒接上 taiwan_law（階段 3 spec
    第 3.3 節承諾了、尚未落地）。有這個欄位就得填 true 或 false，兩個值都是在宣稱
    一件沒有人檢查過的事。`basis_type` 只說明它屬於哪一類，不說明它被查證到什麼程度。
    """

    basis_type: str
    reference: str
    #: 出處，只寫到章（`第01725章 相關準則`）。不寫小節號：相關準則不一定在 1.4
    #: （實測 01523、01574、02786、03110 四章編在 1.3），不知道的小節號不能宣稱。
    detail: str | None


class ChapterOut(BaseModel):
    code: str
    title: str
    #: 規範書頁首的版本，不含「V」字首，例如 `3.0`
    version: str


class ChecklistItemOut(BaseModel):
    work_item_id: uuid.UUID
    item_no: str
    name: str
    result: CheckResult
    #: 本案規範書裡對得到的那一章。本案沒收錄、或根本沒有章碼時是 None
    chapter: ChapterOut | None
    bases: list[BasisOut]

    @classmethod
    def from_row(cls, row: ChecklistRow) -> "ChecklistItemOut":
        chapter = row.chapter
        return cls(
            work_item_id=row.work_item.id,
            item_no=row.work_item.item_no,
            name=row.work_item.name,
            result=row.result,
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
                )
                for basis in row.bases
            ],
        )


class ChecklistSummaryOut(BaseModel):
    ok: int
    spec_not_included: int
    needs_confirmation: int


class ChecklistOut(BaseModel):
    total: int
    #: 三個值相加等於 total。日後 CheckResult 新增值（階段 2、4）時，這裡要同步加一欄，
    #: 否則新值會從摘要裡消失、總和對不上 total。
    summary: ChecklistSummaryOut
    contract_note: str
    #: 規範書解析品質不佳時的警告，依據可能殘缺。正常時是 null。
    spec_warning: str | None
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
            ),
            contract_note=CONTRACT_NOTE,
            spec_warning=checklist.spec_warning,
            items=[ChecklistItemOut.from_row(row) for row in rows],
        )
