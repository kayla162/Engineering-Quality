"""稽核紀錄（regulation_queries / ai_invocation_log / audit_log）的資料存取。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMCallRecord
from app.models.audit import AIInvocationLog, AuditLog, RegulationQuery


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_query(
        self,
        *,
        reference_id: uuid.UUID | None,
        source: str,
        query: str,
        result: Any | None = None,
        raw_response: Any | None = None,
        http_status: str | None = None,
        latency_ms: int | None = None,
    ) -> RegulationQuery:
        row = RegulationQuery(
            reference_id=reference_id,
            source=source,
            query=query[:512],
            result=result,
            raw_response=raw_response,
            http_status=http_status,
            latency_ms=latency_ms,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def log_ai_call(
        self,
        record: LLMCallRecord,
        *,
        job_id: uuid.UUID | None = None,
        reference_id: uuid.UUID | None = None,
    ) -> AIInvocationLog:
        output = record.output_json
        if record.error:
            output = {"error": record.error, **(output or {})}
        row = AIInvocationLog(
            job_id=job_id,
            reference_id=reference_id,
            purpose=record.purpose,
            model=record.model,
            prompt_version=record.prompt_version,
            input_text=record.input_text,
            output_json=output,
            confidence=record.confidence,
            latency_ms=record.latency_ms,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def queries_for_reference(self, reference_id: uuid.UUID) -> list[RegulationQuery]:
        result = await self.session.execute(
            select(RegulationQuery)
            .where(RegulationQuery.reference_id == reference_id)
            .order_by(RegulationQuery.queried_at.desc())
        )
        return list(result.scalars().all())

    async def ai_calls_for_reference(self, reference_id: uuid.UUID) -> list[AIInvocationLog]:
        result = await self.session.execute(
            select(AIInvocationLog)
            .where(AIInvocationLog.reference_id == reference_id)
            .order_by(AIInvocationLog.created_at.desc())
        )
        return list(result.scalars().all())


class AuditLogRepository:
    """使用者操作紀錄。只新增、不修改也不刪除。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, row: AuditLog) -> AuditLog:
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        action: str | None = None,
        username: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        filters = [AuditLog.tenant_id == tenant_id]
        if action:
            filters.append(AuditLog.action == action)
        if username:
            filters.append(AuditLog.username == username)

        total = (
            await self.session.execute(select(func.count()).select_from(AuditLog).where(*filters))
        ).scalar_one()
        result = await self.session.execute(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total
