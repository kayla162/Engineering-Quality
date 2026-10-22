"""租戶內使用者管理 API 契約。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    initial_password: str = Field(min_length=12, max_length=256)


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class UserOut(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime


class UserListOut(BaseModel):
    total: int
    items: list[UserOut]
