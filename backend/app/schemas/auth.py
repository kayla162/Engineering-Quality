"""登入與密碼變更 API 契約。"""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str | None = Field(default=None, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class SessionUserOut(BaseModel):
    user_id: uuid.UUID
    username: str
    role: str
    tenant_id: uuid.UUID
    tenant_name: str
    must_change_password: bool
