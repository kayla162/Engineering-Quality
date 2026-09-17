"""法規查詢的 schema。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.regulation import Regulation


class RegulationVersionOut(BaseModel):
    version: str
    effective_date: date | None
    amended_date: date | None
    source_url: str | None


class RegulationOut(BaseModel):
    regulation_id: uuid.UUID
    name: str
    normalized_name: str
    type: str
    status: str
    authority: str | None
    effective_date: date | None
    last_amended_date: date | None
    official_url: str | None
    source: str
    updated_at: datetime

    @classmethod
    def from_model(cls, regulation: Regulation) -> "RegulationOut":
        return cls(
            regulation_id=regulation.id,
            name=regulation.name,
            normalized_name=regulation.normalized_name,
            type=regulation.type,
            status=regulation.status,
            authority=regulation.authority,
            effective_date=regulation.effective_date,
            last_amended_date=regulation.last_amended_date,
            official_url=regulation.official_url,
            source=regulation.source,
            updated_at=regulation.updated_at,
        )


class RegulationDetailOut(RegulationOut):
    aliases: list[str] = []
    versions: list[RegulationVersionOut] = []

    @classmethod
    def from_model(cls, regulation: Regulation) -> "RegulationDetailOut":
        base = RegulationOut.from_model(regulation)
        return cls(
            **base.model_dump(),
            aliases=[alias.alias for alias in regulation.aliases],
            versions=[
                RegulationVersionOut(
                    version=v.version,
                    effective_date=v.effective_date,
                    amended_date=v.amended_date,
                    source_url=v.source_url,
                )
                for v in regulation.versions
            ],
        )


class RegulationSearchOut(BaseModel):
    total: int
    items: list[RegulationOut]
    #: 這次結果是否包含即時向外部來源查詢的資料
    queried_external: bool = False


class VerifyRequest(BaseModel):
    regulation_id: uuid.UUID
    #: 省略則查詢所有已註冊的來源
    source: str | None = None


class VerifyResponse(BaseModel):
    regulation: RegulationDetailOut
    sources_queried: list[str]
    changed: bool
    message: str
