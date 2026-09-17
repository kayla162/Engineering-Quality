"""regulations / aliases / versions 的資料存取。"""

import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.regulation import Regulation, RegulationAlias, RegulationVersion


class RegulationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, regulation_id: uuid.UUID) -> Regulation | None:
        return await self.session.get(Regulation, regulation_id)

    async def get_by_name(self, normalized_name: str) -> Regulation | None:
        result = await self.session.execute(
            select(Regulation).where(Regulation.normalized_name == normalized_name)
        )
        return result.scalars().first()

    async def search(
        self, query: str, reg_type: str | None = None, limit: int = 20
    ) -> list[Regulation]:
        """名稱 / 別名的模糊查詢（SQL LIKE，精細比對交給 MatchingEngine）。"""
        pattern = f"%{query}%"
        alias_subquery = select(RegulationAlias.regulation_id).where(
            RegulationAlias.alias.ilike(pattern)
        )
        stmt = select(Regulation).where(
            or_(
                Regulation.name.ilike(pattern),
                Regulation.normalized_name.ilike(pattern),
                Regulation.id.in_(alias_subquery),
            )
        )
        if reg_type:
            stmt = stmt.where(Regulation.type == reg_type)
        result = await self.session.execute(stmt.limit(limit))
        return list(result.scalars().all())

    async def list_all(self, limit: int = 1000) -> list[Regulation]:
        """比對時載入候選集合。資料量大時應改成先用 search 縮小範圍。"""
        result = await self.session.execute(select(Regulation).limit(limit))
        return list(result.scalars().all())

    async def count(self) -> int:
        return (await self.session.execute(select(func.count()).select_from(Regulation))).scalar_one()

    async def upsert(
        self,
        *,
        name: str,
        normalized_name: str,
        reg_type: str,
        status: str,
        source: str,
        authority: str | None = None,
        effective_date=None,
        last_amended_date=None,
        official_url: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> Regulation:
        """以 normalized_name 為鍵建立或更新法規主檔。

        注意：status 只能由外部來源查詢結果或人工建立寫入，LLM 不得經由這裡寫入。
        """
        regulation = await self.get_by_name(normalized_name)
        if regulation is None:
            regulation = Regulation(normalized_name=normalized_name, tenant_id=tenant_id)
            self.session.add(regulation)

        regulation.name = name
        regulation.type = reg_type
        regulation.status = status
        regulation.source = source
        regulation.authority = authority
        regulation.effective_date = effective_date
        regulation.last_amended_date = last_amended_date
        regulation.official_url = official_url
        await self.session.flush()
        return regulation

    async def aliases_for(self, regulation_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        """一次撈出多筆法規的別名。

        不要走 regulation.aliases：剛用 upsert 建立、還沒被 SELECT 載入過的物件
        會在 async session 觸發 lazy load 而爆掉。順便也省掉 N+1 查詢。
        """
        if not regulation_ids:
            return {}
        result = await self.session.execute(
            select(RegulationAlias.regulation_id, RegulationAlias.alias).where(
                RegulationAlias.regulation_id.in_(regulation_ids)
            )
        )
        mapping: dict[uuid.UUID, list[str]] = {}
        for regulation_id, alias in result.all():
            mapping.setdefault(regulation_id, []).append(alias)
        return mapping

    async def add_aliases(self, regulation: Regulation, aliases: list[str]) -> None:
        # 直接查資料庫而不是走 regulation.aliases，避免在 async session 觸發 lazy load
        result = await self.session.execute(
            select(RegulationAlias.alias).where(RegulationAlias.regulation_id == regulation.id)
        )
        existing = set(result.scalars().all())
        for alias in aliases:
            if alias and alias not in existing:
                self.session.add(RegulationAlias(regulation_id=regulation.id, alias=alias))
                existing.add(alias)
        await self.session.flush()

    async def replace_versions(self, regulation: Regulation, versions: list[dict]) -> None:
        await self.session.execute(
            delete(RegulationVersion).where(RegulationVersion.regulation_id == regulation.id)
        )
        for version in versions:
            self.session.add(RegulationVersion(regulation_id=regulation.id, **version))
        await self.session.flush()
