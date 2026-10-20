"""Private manifest format and public read-only inspection response."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArtifactBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImageBinding(ArtifactBinding):
    label: str


class DocumentBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    file_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    book: Literal["architecture", "structure"]


class InspectionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    project_id: UUID
    historical_revision: int = Field(ge=0)
    documents: list[DocumentBinding] = Field(min_length=1)
    artifacts: dict[str, ArtifactBinding]
    images: dict[str, ImageBinding] = Field(default_factory=dict)


class DrawingInspectionResponse(BaseModel):
    project_id: str
    available: bool
    revision: int
    historical_revision: int | None
    warnings: list[str]
    summary: dict
    historical_summary: dict
    groups: list[dict]
    similar_hints: list[dict]
    findings: list[dict]
    images: list[dict]
