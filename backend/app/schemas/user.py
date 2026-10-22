"""租戶內使用者管理 API 契約。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import UserRole


class UserCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    initial_password: str = Field(min_length=12, max_length=256)
    role: UserRole = UserRole.MEMBER


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool
    initial_password: str | None = Field(default=None, min_length=12, max_length=256)

    @model_validator(mode="after")
    def validate_activation_password(self):
        if self.is_active and self.initial_password is None:
            raise ValueError("重新啟用帳號時必須設定初始密碼")
        if not self.is_active and self.initial_password is not None:
            raise ValueError("停用帳號時不可設定初始密碼")
        return self


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
