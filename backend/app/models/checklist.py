"""本案施工規範的章節索引，與每個工項找到的依據。

`spec_chapters` 是**對一份文件建的索引**，不是另一份真相——和 work_items
由標單建出來同一個模式：有明確的 build 步驟，重跑取代。

`work_item_bases` **只存找到的**。不存 found=false 的列，因為「沒找到」的三種
原因全部算得出來（沒有章節／本案規範未收錄／章節無相關準則），存起來就變成
可能過期的欄位——違反 enums.py 開頭和原 spec 第 4 節的規則。
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, uuid_pk


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
    #: 沿用 RegulationType。STANDARD（CNS/ASTM/ISO/JIS）沒有資料來源可查證，
    #: 只引述；其餘走既有的 taiwan_law 查證。
    basis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    #: 出處，例如「第01725章 1.4.1」
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (Index("ix_work_item_bases_work_item", "work_item_id"),)
