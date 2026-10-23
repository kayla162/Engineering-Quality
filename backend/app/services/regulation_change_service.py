"""法規異動監控（Phase 3）。

對「這個租戶的文件有引用到」的每一部法規，重新問一次寫入它的那個來源，
比對狀態、生效日、最後修正日有沒有變。有變就更新法規主檔、留一筆異動紀錄。

刻意的限制：
- **只問擁有者來源，只認完全同名。** 不像分析時那樣模糊比對：這裡是要回答
  「同一部法規變了沒」，名稱相近的別部法規不是答案。
- **不回頭改引用。** 引用的狀態是當時比對的結果；法規廢止了，畫面要告訴人
  「哪些文件受影響」，要不要重新分析由人決定，不安靜地改掉已覆核過的結論。
- **來源查不到不等於廢止。** 記成 presence: missing，交給人判斷（可能是更名）。
- 同一筆未確認的異動不重複記：每天排程跑，不會每天多一筆一樣的。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RegulationChangeNotFoundError, SourceQueryError
from app.core.logging import log_context
from app.matching.normalizer import clean_text
from app.models.base import utcnow
from app.models.document import Document
from app.models.reference import RegulationReference
from app.models.regulation import Regulation, RegulationChange
from app.repositories.audit import AuditRepository
from app.sources import RegulationSource, get_sources

logger = logging.getLogger(__name__)

#: 會比對的欄位。名稱是比對鍵，不算變動。
TRACKED_FIELDS = ("status", "effective_date", "last_amended_date")


@dataclass
class CheckSummary:
    checked: int = 0
    changed: int = 0
    #: 沒有檢查到的法規與原因。讓人知道「沒有異動」是查過了，還是根本沒查
    skipped: list[dict] = field(default_factory=list)
    new_changes: list[RegulationChange] = field(default_factory=list)


@dataclass
class AffectedDocument:
    document_id: uuid.UUID
    filename: str
    references: int


class RegulationChangeService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        sources: list[RegulationSource] | None = None,
    ):
        self.session = session
        self.tenant_id = tenant_id
        self.sources = {s.source_name: s for s in (sources if sources is not None else get_sources())}
        self.audit = AuditRepository(session)

    async def check(self) -> CheckSummary:
        """檢查一輪。呼叫端負責 commit。"""
        summary = CheckSummary()
        unready: dict[str, str] = {}
        for name, source in self.sources.items():
            readiness = source.readiness()
            if not readiness.ready:
                unready[name] = readiness.detail or "來源尚未就緒"

        for regulation in await self._referenced_regulations():
            source = self.sources.get(regulation.source)
            if source is None:
                reason = (
                    "人工建立的法規沒有來源可以查"
                    if regulation.source == "manual"
                    else f"來源 {regulation.source} 未啟用"
                )
                summary.skipped.append(_skip(regulation, reason))
                continue
            if regulation.source in unready:
                summary.skipped.append(_skip(regulation, unready[regulation.source]))
                continue

            try:
                changes = await self._compare(regulation, source)
            except SourceQueryError as exc:
                summary.skipped.append(_skip(regulation, f"查詢失敗：{exc.message}"))
                continue

            summary.checked += 1
            if changes and not await self._already_open(regulation.id, changes):
                change = RegulationChange(
                    tenant_id=self.tenant_id,
                    regulation_id=regulation.id,
                    source=regulation.source,
                    changes=changes,
                )
                self.session.add(change)
                summary.new_changes.append(change)
                summary.changed += 1
                logger.info(
                    "偵測到法規異動",
                    extra=log_context(regulation=regulation.name, changes=changes),
                )
        await self.session.flush()
        return summary

    async def list_changes(self, *, include_acknowledged: bool = False) -> list[RegulationChange]:
        stmt = select(RegulationChange).where(RegulationChange.tenant_id == self.tenant_id)
        if not include_acknowledged:
            stmt = stmt.where(RegulationChange.acknowledged_at.is_(None))
        result = await self.session.execute(stmt.order_by(RegulationChange.detected_at.desc()))
        return list(result.scalars().all())

    async def affected_documents(self, regulation_id: uuid.UUID) -> list[AffectedDocument]:
        """引用了這部法規的文件（同租戶），附各引用了幾次。"""
        rows = await self.session.execute(
            select(Document.id, Document.filename, func.count(RegulationReference.id))
            .join(RegulationReference, RegulationReference.document_id == Document.id)
            .where(
                Document.tenant_id == self.tenant_id,
                RegulationReference.regulation_id == regulation_id,
            )
            .group_by(Document.id, Document.filename)
            .order_by(Document.filename)
        )
        return [AffectedDocument(document_id=i, filename=f, references=n) for i, f, n in rows.all()]

    async def get(self, change_id: uuid.UUID) -> RegulationChange:
        """重新從資料庫讀，連同法規一起載入（剛 add、剛 commit 的物件不能 lazy load）。"""
        change = await self.session.scalar(
            select(RegulationChange)
            .where(RegulationChange.id == change_id, RegulationChange.tenant_id == self.tenant_id)
            .execution_options(populate_existing=True)
        )
        if change is None:
            raise RegulationChangeNotFoundError("找不到指定的法規異動")
        return change

    async def acknowledge(self, change_id: uuid.UUID, username: str) -> RegulationChange:
        change = await self.get(change_id)
        if change.acknowledged_at is None:
            change.acknowledged_at = utcnow()
            change.acknowledged_by = username
            await self.session.flush()
        return change

    # --- 內部 ---

    async def _referenced_regulations(self) -> list[Regulation]:
        referenced = (
            select(RegulationReference.regulation_id)
            .join(Document, Document.id == RegulationReference.document_id)
            .where(Document.tenant_id == self.tenant_id)
        )
        result = await self.session.execute(
            select(Regulation)
            .where(Regulation.tenant_id == self.tenant_id, Regulation.id.in_(referenced))
            .order_by(Regulation.name)
        )
        return list(result.scalars().all())

    async def _compare(self, regulation: Regulation, source: RegulationSource) -> dict:
        """回傳變動的欄位；沒變回傳空 dict。有變時就地更新法規主檔。"""
        started = time.perf_counter()
        try:
            results = await source.search(regulation.name)
        except SourceQueryError as exc:
            await self._log_query(regulation, source, {"error": exc.message}, exc.http_status or "ERROR", started)
            raise
        await self._log_query(
            regulation, source, [r.model_dump(mode="json") for r in results], "200", started
        )

        match = next(
            (
                r
                for r in results
                if r.source == source.source_name
                and clean_text(r.name) == regulation.normalized_name
            ),
            None,
        )
        if match is None:
            return {"presence": {"old": "found", "new": "missing"}}

        changes = {}
        for name in TRACKED_FIELDS:
            old, new = getattr(regulation, name), getattr(match, name)
            if old != new:
                changes[name] = {"old": _jsonable(old), "new": _jsonable(new)}
                setattr(regulation, name, new)
        return changes

    async def _already_open(self, regulation_id: uuid.UUID, changes: dict) -> bool:
        result = await self.session.execute(
            select(RegulationChange.changes).where(
                RegulationChange.tenant_id == self.tenant_id,
                RegulationChange.regulation_id == regulation_id,
                RegulationChange.acknowledged_at.is_(None),
            )
        )
        return any(existing == changes for existing in result.scalars().all())

    async def _log_query(self, regulation, source, result, http_status, started) -> None:
        await self.audit.log_query(
            reference_id=None,
            source=source.source_name,
            query=regulation.name,
            result=result,
            http_status=http_status,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _skip(regulation: Regulation, reason: str) -> dict:
    return {"regulation_id": str(regulation.id), "name": regulation.name, "reason": reason}


def _jsonable(value):
    return value.isoformat() if isinstance(value, date) else value
