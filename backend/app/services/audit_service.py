"""使用者操作的稽核紀錄（Phase 3：全域 audit_log）。

由 API 層在操作成功之後呼叫 `record`，和那次操作在同一個 transaction 裡 commit：
操作失敗就不會留下「做了」的紀錄。登入失敗例外——它本身就是要記的事件，
呼叫端會在丟出錯誤之前先 commit。

不在 middleware 統一攔截：middleware 看不到「改了哪一筆、改成什麼」，
而那正是稽核紀錄唯一有用的部分。
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuditAction
from app.core.security import CurrentUser
from app.models.audit import AuditLog
from app.repositories.audit import AuditLogRepository


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.logs = AuditLogRepository(session)

    async def record(
        self,
        action: AuditAction,
        *,
        actor: CurrentUser | None = None,
        tenant_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        username: str | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | str | None = None,
        detail: dict[str, Any] | None = None,
        request: Request | None = None,
        commit: bool = False,
    ) -> AuditLog:
        """新增一筆紀錄。有 actor 時，租戶與使用者一律以 actor 為準。

        `commit=True` 給「service 已經自己 commit 過」的路由用；否則由呼叫端
        跟它自己的寫入一起 commit。
        """
        if actor is not None:
            tenant_id, user_id, username = actor.tenant_id, actor.id, actor.username
        row = await self.logs.add(
            AuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                username=(username or "unknown")[:128],
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                detail=detail,
                ip_address=_client_ip(request),
            )
        )
        if commit:
            await self.session.commit()
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
        return await self.logs.list_for_tenant(
            tenant_id, action=action, username=username, page=page, page_size=page_size
        )


def _client_ip(request: Request | None) -> str | None:
    # 和登入限流用同一個來源：不信任 X-Forwarded-For（見 login throttling 設計）
    if request is None or request.client is None:
        return None
    return request.client.host[:64]
