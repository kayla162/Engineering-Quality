"""使用者操作稽核紀錄 API 契約。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.audit import AuditLog


class AuditLogOut(BaseModel):
    audit_id: uuid.UUID
    created_at: datetime
    username: str
    action: str
    resource_type: str | None
    resource_id: str | None
    detail: dict[str, Any] | None
    ip_address: str | None

    @classmethod
    def from_model(cls, row: AuditLog) -> "AuditLogOut":
        return cls(
            audit_id=row.id,
            created_at=row.created_at,
            username=row.username,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            detail=row.detail,
            ip_address=row.ip_address,
        )


class AuditLogListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AuditLogOut]
