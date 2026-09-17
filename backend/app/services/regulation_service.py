"""法規查詢與重新查證。"""

import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, RegulationNotFoundError, SourceQueryError
from app.core.logging import log_context
from app.matching.normalizer import clean_text
from app.models.regulation import Regulation
from app.repositories.audit import AuditRepository
from app.repositories.regulations import RegulationRepository
from app.sources import get_sources

logger = logging.getLogger(__name__)


class RegulationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.regulations = RegulationRepository(session)
        self.audit = AuditRepository(session)

    async def search(
        self, query: str, reg_type: str | None = None, force_external: bool = False
    ) -> tuple[list[Regulation], bool]:
        """先查內部資料庫；找不到（或指定 force_external）才打外部來源。"""
        rows = await self.regulations.search(query, reg_type)
        if rows and not force_external:
            return rows, False

        await self._query_external(query)
        return await self.regulations.search(query, reg_type), True

    async def get(self, regulation_id: uuid.UUID) -> Regulation:
        regulation = await self.regulations.get(regulation_id)
        if regulation is None:
            raise RegulationNotFoundError("找不到指定的法規")
        return regulation

    async def verify(self, regulation_id: uuid.UUID, source_name: str | None = None) -> dict:
        """手動重新查詢外部來源，更新法規主檔。"""
        regulation = await self.get(regulation_id)
        sources = get_sources()
        if source_name:
            sources = [s for s in sources if s.source_name == source_name]
            if not sources:
                raise AppError(f"沒有註冊名為「{source_name}」的資料來源")

        before = (regulation.status, regulation.last_amended_date)
        queried = await self._query_external(regulation.name, sources)
        await self.session.refresh(regulation)
        after = (regulation.status, regulation.last_amended_date)

        changed = before != after
        message = (
            f"資料已更新：狀態 {before[0]} -> {after[0]}"
            if changed
            else "重新查詢完成，資料沒有變動"
        )
        if not queried:
            message = "所有已註冊的資料來源都查詢失敗，資料維持不變"
        return {"regulation": regulation, "sources_queried": queried, "changed": changed,
                "message": message}

    # --- 內部 ---

    async def _query_external(self, query: str, sources=None) -> list[str]:
        """查詢外部來源並把結果寫入法規主檔，回傳成功查詢的來源名稱。"""
        queried: list[str] = []
        for source in sources if sources is not None else get_sources():
            started = time.perf_counter()
            try:
                results = await source.search(query)
            except SourceQueryError as exc:
                logger.warning(
                    "法規來源查詢失敗",
                    extra=log_context(source=source.source_name, error=exc.message),
                )
                await self.audit.log_query(
                    reference_id=None,
                    source=source.source_name,
                    query=query,
                    result={"error": exc.message},
                    http_status=exc.http_status or "ERROR",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                continue

            await self.audit.log_query(
                reference_id=None,
                source=source.source_name,
                query=query,
                result=[r.model_dump(mode="json") for r in results],
                http_status="200",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            for result in results:
                regulation = await self.regulations.upsert(
                    name=result.name,
                    normalized_name=clean_text(result.name),
                    reg_type=result.type,
                    status=result.status,
                    source=result.source,
                    authority=result.authority,
                    effective_date=result.effective_date,
                    last_amended_date=result.last_amended_date,
                    official_url=result.official_url,
                    tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID),
                )
                detail = await source.get_detail(result.external_id)
                if detail and detail.versions:
                    await self.regulations.replace_versions(
                        regulation,
                        [v.model_dump(exclude_none=False) for v in detail.versions],
                    )
            queried.append(source.source_name)

        await self.session.commit()
        return queried
