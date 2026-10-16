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
