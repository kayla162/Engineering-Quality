"""本案施工規範的章節索引，與每個工項找到的依據。

`spec_chapters` 是**對一份文件建的索引**，不是另一份真相——和 work_items
由標單建出來同一個模式：有明確的 build 步驟，重跑取代。

`work_item_bases` **只存找到的**。不存 found=false 的列，因為「沒找到」的三種
原因全部算得出來（沒有章節／本案規範未收錄／章節無相關準則），存起來就變成
可能過期的欄位——違反 `app/core/enums.py` 的 `CheckResult`（狀態由資料算出來、不存成
欄位）的設計與原 spec 第 4 節的規則。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonColumn, created_at_column, uuid_pk


class SpecChapter(Base):
    """本案施工規範書裡的一章。"""

    __tablename__ = "spec_chapters"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: 指向 role = specification 的那份文件
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    #: 5 碼章碼，和計價代碼前 5 碼對接
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: 版本，例如「3.0」——不含「V」字首（chapter_reader.py 產生的格式）
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    first_page: Mapped[int] = mapped_column(Integer, nullable=False)
    last_page: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_spec_chapters_document_code", "document_id", "code"),)


class WorkItemBasis(Base):
    """一個工項找到的一條依據。"""

    __tablename__ = "work_item_bases"

    id: Mapped[uuid.UUID] = uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    #: 沿用 RegulationType，由抽取器依名稱字尾判定（`extractors/rule_engine.py` 的
    #: `_SUFFIX_TYPES`），這個判定本身也沒被查證。STANDARD（CNS/ASTM/ISO/JIS）沒有
    #: 資料來源可查證，只引述；其餘由 `ChecklistService.build` 拿去 `taiwan_law`
    #: 查完全同名，結果存在 `verification_status`。讀取檢核表不會重查。
    basis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    #: 出處，只寫到章，例如「第01725章 相關準則」（`checklist_service` 寫入）。不寫小節號：
    #: 相關準則不一定在 1.4（實測 01523、01574、02786、03110 四章編在 1.3），系統不宣稱
    #: 它不知道的小節號。
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: 法規查證結果。**None 代表未查證**——沒有送查（標準），或查不到完全同名。
    #: 永遠不存 NOT_FOUND：那個值的意思是「我們查過，這部法規不存在」，而依據
    #: 來自規範書自己宣告的清單，我們沒有立場那樣說。建築技術規則是真法規，只是索引把
    #: 它拆成四編登錄；屋內線路裝置規則則是 2018 年已更名為用戶用電設備裝置規則的舊
    #: 名稱，規範書還在引用它。兩者都查不到完全同名，維持 None。
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_work_item_bases_work_item", "work_item_id"),)


class DrawingSheet(Base):
    """契約圖裡的一張圖（檢核表階段 2、4）。和 spec_chapters 一樣是對一份文件建的索引，
    重建檢核表時重讀、取代。只有圖號、圖名、頁碼——圖面內容系統讀不懂。"""

    __tablename__ = "drawing_sheets"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: 指向 role = drawing 的那份文件
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    sheet_no: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 圖號圖名由 OCR 從掃描的標題欄讀出，可能有錯字。這一冊重建檢核表時不重讀（OCR 每頁約 1 秒）
    is_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_drawing_sheets_document", "document_id"),)


class WorkItemMethod(Base):
    """工項的工法欄（檢核表階段 4）。只存「要選」的工項：施工規範列出兩種以上工法。

    `selected` 是契約文件文字裡恰好出現一種的那個選項；None 代表未指定，
    檢核結果就是「請檢討使用何種工法」，並附相關圖號。不從圖面猜。
    """

    __tablename__ = "work_item_methods"

    id: Mapped[uuid.UUID] = uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    options: Mapped[Any] = mapped_column(JsonColumn, nullable=False)
    selected: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 指定的出處（文件與前後文），或未指定的原因
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_work_item_methods_work_item", "work_item_id"),)


class WorkItemContractRef(Base):
    """檢核表的「契約」欄：契約書裡提到這個工項（或它所屬分項）的地方。

    契約書的條號是 Word 自動編號，PDF 文字層裡沒有，所以出處寫頁碼與前面最近的小標題，
    不寫推算出來的條號。只是「契約提到這裡」，不代表契約對這個工項有特別規定——要人去看。
    """

    __tablename__ = "work_item_contract_refs"

    id: Mapped[uuid.UUID] = uuid_pk()
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 前面最近的小標題（「假設工程之組立及拆除」）；找不到時 None
    heading: Mapped[str | None] = mapped_column(String(64), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    #: 用哪個詞找到的（工項或分項的主體：「模板」「開關箱」）
    keyword: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_work_item_contract_refs_work_item", "work_item_id"),)
