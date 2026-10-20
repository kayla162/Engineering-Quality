import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DrawingMutation(BaseModel):
    expected_revision: int = Field(ge=0)


class IndexDrawing(DrawingMutation):
    document_id: uuid.UUID
    use_ocr: bool = False


class AddDrawingItem(DrawingMutation):
    sheet_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    evidence: str = Field(min_length=1, max_length=4000)

    @field_validator("name", "evidence")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("不可空白")
        return value.strip()


class ReviewDrawingItem(DrawingMutation):
    decision: Literal["confirmed", "rejected", "pending"]
    work_item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("請填寫覆核依據")
        return value.strip()


class EditDrawingSheet(DrawingMutation):
    number: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    source: Literal["manual", "assisted"] = "manual"

    @field_validator("number", "title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("不可空白")
        return value.strip()
