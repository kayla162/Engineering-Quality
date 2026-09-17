"""API 共用的 schema。"""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    """所有錯誤回應的統一格式（docs/api.md 第 6 節）。"""

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str
