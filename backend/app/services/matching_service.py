"""把一筆引用對應到一部法規，並決定它的狀態。

這是「查外部來源 -> 寫入法規主檔 -> 比對 -> 決定狀態」的編排層。
真正的比對邏輯在 matching/matching_engine.py，這裡只負責資料進出。

重要：單一筆引用查詢失敗，只會讓那一筆變成 UNKNOWN，
不會讓整份文件的分析失敗（docs/api.md 第 6 節）。
"""

import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMProvider
from app.core.config import settings
from app.core.enums import RegulationStatus, RegulationType
from app.core.errors import SourceQueryError
from app.core.logging import log_context
from app.matching.matching_engine import MatchCandidate, MatchingEngine
from app.matching.normalizer import clean_text
from app.models.base import utcnow
from app.models.reference import RegulationReference
from app.models.regulation import Regulation
from app.repositories.audit import AuditRepository
from app.repositories.regulations import RegulationRepository
from app.sources import RegulationSearchResult, get_sources, source_priority

logger = logging.getLogger(__name__)


def _merge_candidates(*groups: list[Regulation]) -> list[Regulation]:
    """合併多組候選法規，以 id 去重。"""
    merged: dict[uuid.UUID, Regulation] = {}
    for group in groups:
        for regulation in group:
            merged.setdefault(regulation.id, regulation)
    return list(merged.values())


def can_confirm_currency(regulation_type: str) -> bool:
    """這個類型的法規，公開來源能不能確認「目前是最新有效版本」？

    CNS / ISO / ASTM / JIS 這類標準多數是付費標準，公開來源通常只查得到
    「標準是否存在」，查不到最新版號與全文（docs/development-plan.md 第 3 節）。
    因此這類引用會被降級為 POSSIBLE_MATCH，明確要求人工查證，
    而不是承諾系統能自動判斷它的最新有效性。
    """
    return regulation_type != RegulationType.STANDARD


class MatchingService:
    def __init__(self, session: AsyncSession, llm_provider: LLMProvider | None = None):
        self.session = session
        self.regulations = RegulationRepository(session)
        self.audit = AuditRepository(session)
        self.engine = MatchingEngine(llm_provider)
        self.sources = get_sources()

    async def resolve(
        self,
        reference: RegulationReference,
        job_id: uuid.UUID | None = None,
        context: str = "",
    ) -> RegulationReference:
        """查詢 + 比對一筆引用，就地更新它的 regulation_id / status / 信心分數。

        context 是這筆引用所在段落的原文，只有在需要問 LLM 時才會用到；
        由呼叫端傳入而不是從 reference.section 讀，避免在 async session 觸發 lazy load。
        """
        query_name = reference.normalized_name or reference.raw_text

        # 1. 先看內部資料庫，資料夠新就不打外部來源
        candidates = await self.regulations.search(query_name)
        currency_overrides: dict[str, bool] = {}

        if self._needs_external_query(candidates):
            try:
                fetched, currency_overrides = await self._query_sources(reference, query_name)
            except SourceQueryError as exc:
                return self._mark_unknown(reference, exc)
            # 直接併入剛查回來的結果。
            # 不能只靠再查一次資料庫：資料庫是字串包含查詢，
            # 名稱順序不同（「混凝土結構施工規範」vs「結構混凝土施工規範」）就會漏掉。
            candidates = _merge_candidates(candidates, fetched)

        # 2. 比對（別名一次撈齊，避免逐筆 lazy load）
        alias_map = await self.regulations.aliases_for([r.id for r in candidates])
        decision = await self.engine.match(
            normalized_name=query_name,
            candidates=[
                self._to_match_candidate(r, alias_map.get(r.id, []), currency_overrides)
                for r in candidates
            ],
            standard_number=reference.standard_number,
            context=context,
        )

        # 3. 寫回結果（LLM 的輸出只會進 ai_invocation_log 與比對理由，不會寫進 regulations）
        if decision.ai_record is not None:
            await self.audit.log_ai_call(
                decision.ai_record, job_id=job_id, reference_id=reference.id
            )

        reference.match_confidence = decision.confidence
        reference.status = decision.status
        reference.match_reasons = "\n".join(decision.reasons)
        reference.regulation_id = (
            uuid.UUID(decision.candidate.key) if decision.candidate else None
        )
        await self.session.flush()
        return reference

    # --- 內部 ---

    def _needs_external_query(self, candidates: list[Regulation]) -> bool:
        """沒有候選、候選不是最優先來源寫的、或候選已經過期，就要重新查外部來源。"""
        if not candidates:
            return True

        # 快取只有在「最優先的來源已經對這個名稱表過態」時才可信。
        # 否則會發生：查 A 法規時，次要來源順帶回傳了 B 法規並寫進主檔，
        # 之後真正比對到 B 時，主檔已有一筆「很新」的次要來源資料，
        # TTL 就讓最優先的來源永遠沒機會被問到。
        # 代價是這類名稱每次都會重查一次；目前的來源都是本機索引，成本可忽略。
        enabled = settings.regulation_sources
        if enabled and all(r.source != enabled[0] for r in candidates):
            return True

        deadline = utcnow() - timedelta(days=settings.REGULATION_CACHE_TTL_DAYS)
        return all(
            r.updated_at.replace(tzinfo=r.updated_at.tzinfo or deadline.tzinfo) < deadline
            for r in candidates
        )

    async def _query_sources(
        self, reference: RegulationReference, query_name: str
    ) -> tuple[list[Regulation], dict[str, bool]]:
        """依序查詢所有已註冊來源，把結果寫進 regulations 與 regulation_queries。

        回傳 (查到並寫入的法規, {normalized_name: can_confirm_currency})，
        後者讓比對時採用來源自己對「能不能確認最新版」的宣告。
        """
        fetched: list[Regulation] = []
        overrides: dict[str, bool] = {}
        errors: list[SourceQueryError] = []

        for source in self.sources:
            started = time.perf_counter()
            try:
                results = await source.search(query_name)
            except SourceQueryError as exc:
                errors.append(exc)
                await self.audit.log_query(
                    reference_id=reference.id,
                    source=source.source_name,
                    query=query_name,
                    result={"error": exc.message},
                    http_status=exc.http_status or "ERROR",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                logger.warning(
                    "法規來源查詢失敗",
                    extra=log_context(source=source.source_name, error=exc.message),
                )
                continue

            latency_ms = int((time.perf_counter() - started) * 1000)
            await self.audit.log_query(
                reference_id=reference.id,
                source=source.source_name,
                query=query_name,
                result=[r.model_dump(mode="json") for r in results],
                raw_response={"count": len(results)},
                http_status="200",
                latency_ms=latency_ms,
            )

            for result in results:
                # 來源回傳的是「前幾名相似結果」，不是只有一筆。相關度太低的鄰居
                # 比對引擎本來就不會採用，卻會被寫進法規主檔造成兩個問題：
                #   1. 主檔被無關的法規灌滿
                #   2. 查「職業安全衛生法」時順帶寫入的「職業安全衛生設施規則」，
                #      會讓之後真正比對到那一筆時因為 TTL 快取而不再詢問官方來源
                # 所以低於比對門檻的結果只留查詢紀錄，不寫入主檔。
                if result.relevance < settings.MATCH_POSSIBLE_THRESHOLD:
                    continue
                regulation = await self._save_source_result(result)
                # 只有真正寫入的來源才有資格決定「能不能確認最新版」；
                # 被優先序擋掉時要沿用既有擁有者的判斷。
                if regulation.source == result.source:
                    overrides[regulation.normalized_name] = result.can_confirm_currency
                fetched.append(regulation)

        # 所有來源都失敗才算整體失敗
        if errors and not overrides:
            raise errors[0]
        return fetched, overrides

    async def _save_source_result(self, result: RegulationSearchResult) -> Regulation:
        """把來源回傳的官方資料寫入法規主檔。這是 regulations.status 唯一的自動寫入路徑。

        優先序保護：如果這筆法規已經由更優先的來源寫入過，就保留既有資料不覆蓋
        （例如 taiwan_law,mock 時，官方查到的狀態不該被 mock 假資料蓋掉）。
        """
        normalized_name = clean_text(result.name)
        existing = await self.regulations.get_by_name(normalized_name)
        if existing is not None and source_priority(existing.source) < source_priority(result.source):
            logger.debug(
                "略過低優先來源的覆蓋",
                extra=log_context(
                    regulation=existing.name, kept=existing.source, skipped=result.source
                ),
            )
            return existing

        regulation = await self.regulations.upsert(
            name=result.name,
            normalized_name=normalized_name,
            reg_type=result.type,
            status=result.status,
            source=result.source,
            authority=result.authority,
            effective_date=result.effective_date,
            last_amended_date=result.last_amended_date,
            official_url=result.official_url,
            tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID),
        )
        if result.standard_number:
            await self.regulations.add_aliases(regulation, [result.standard_number])
        return regulation

    def _to_match_candidate(
        self, regulation: Regulation, aliases: list[str], overrides: dict[str, bool]
    ) -> MatchCandidate:
        standard_number = next(
            (a for a in aliases if any(a.upper().startswith(p) for p in ("CNS", "ISO", "ASTM", "JIS"))),
            None,
        )
        return MatchCandidate(
            key=str(regulation.id),
            name=regulation.name,
            normalized_name=regulation.normalized_name,
            type=regulation.type,
            status=regulation.status,
            aliases=aliases,
            standard_number=standard_number,
            can_confirm_currency=overrides.get(
                regulation.normalized_name, can_confirm_currency(regulation.type)
            ),
        )

    def _mark_unknown(
        self, reference: RegulationReference, exc: SourceQueryError
    ) -> RegulationReference:
        reference.status = RegulationStatus.UNKNOWN
        reference.match_confidence = None
        # 來源有給補救命令（例如索引還沒同步）就直接寫出來——這種情況重試一百次也一樣。
        # 只有真正的暫時性失敗（timeout / 5xx）才叫使用者稍後再試。
        next_step = f"請執行：{exc.remedy}" if exc.remedy else "已記錄於查詢紀錄，可稍後重試"
        reference.match_reasons = f"外部來源查詢失敗：{exc.message}（{next_step}）"
        logger.warning(
            "引用查詢失敗，標記為 UNKNOWN",
            extra=log_context(reference_id=str(reference.id), error=exc.message),
        )
        return reference
