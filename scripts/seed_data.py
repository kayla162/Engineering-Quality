"""載入種子資料：別名字典，以及（只在啟用 mock 時）假法規資料。

    python scripts/seed_data.py

兩種資料的分工：
  - 別名字典（data/alias_dictionary.json）永遠會載入。它是「我們自己的對應知識」，
    負責把簡稱、舊名對應到官方全名，官方 API 不會提供這種東西。
  - 假法規（data/mock_regulations.json）只在 REGULATION_SOURCES 含 mock 時才載入，
    避免假資料混進已經接了官方來源的環境。

接官方來源請改用：python scripts/sync_taiwan_law.py

種子資料刻意不寫在 Alembic migration 裡，方便日後直接替換（docs/database.md 第 5 節）。
"""

import asyncio
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.matching.normalizer import clean_text  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.repositories.regulations import RegulationRepository  # noqa: E402
from app.sources.mock_source import MockRegulationSource  # noqa: E402


def load_alias_entries() -> list[dict]:
    path = settings.DATA_DIR / "alias_dictionary.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("entries", [])


async def seed_mock_regulations(repo: RegulationRepository, tenant_id: uuid.UUID) -> int:
    """載入假法規。

    seed 進來的資料會被標記成「已過期」（updated_at 設在 TTL 之前），
    這樣第一次分析仍然會實際呼叫一次資料來源，在 regulation_queries 留下查詢紀錄。
    """
    stale_at = utcnow() - timedelta(days=settings.REGULATION_CACHE_TTL_DAYS + 1)
    source = MockRegulationSource()
    count = 0

    for record in source._load():  # noqa: SLF001 - 種子腳本刻意讀取完整清單
        detail = await source.get_detail(record["external_id"])
        regulation = await repo.upsert(
            name=detail.name,
            normalized_name=clean_text(detail.name),
            reg_type=detail.type,
            status=detail.status,
            source=detail.source,
            authority=detail.authority,
            effective_date=detail.effective_date,
            last_amended_date=detail.last_amended_date,
            official_url=detail.official_url,
            tenant_id=tenant_id,
        )
        if detail.standard_number:
            await repo.add_aliases(regulation, [detail.standard_number])
        if detail.versions:
            await repo.replace_versions(regulation, [v.model_dump() for v in detail.versions])
        regulation.updated_at = stale_at
        count += 1
    return count


async def seed_aliases(repo: RegulationRepository, entries: list[dict]) -> tuple[int, list[str]]:
    """把別名掛到資料庫裡已存在的法規上。

    找不到對應法規的別名先略過——接官方來源時，法規是在比對過程中才被寫進來的，
    等它出現之後重跑一次這個腳本即可。正規化本身直接讀 JSON 字典，不受影響。
    """
    attached = 0
    missing: list[str] = []
    for entry in entries:
        canonical = entry["canonical"]
        regulation = await repo.get_by_name(clean_text(canonical))
        if regulation is None:
            missing.append(canonical)
            continue
        await repo.add_aliases(regulation, entry.get("aliases", []))
        attached += 1
    return attached, missing


async def seed() -> None:
    tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)
    entries = load_alias_entries()
    use_mock = "mock" in settings.regulation_sources

    async with get_session_factory()() as session:
        repo = RegulationRepository(session)

        if use_mock:
            seeded = await seed_mock_regulations(repo, tenant_id)
            print(f"假法規：載入 {seeded} 筆（REGULATION_SOURCES 含 mock）")
        else:
            print("假法規：略過（REGULATION_SOURCES 未啟用 mock）")

        attached, missing = await seed_aliases(repo, entries)
        await session.commit()
        total = await repo.count()

    print(f"別名字典：{len(entries)} 組，已掛上 {attached} 組")
    if missing:
        preview = "、".join(missing[:5])
        more = f" 等 {len(missing)} 組" if len(missing) > 5 else ""
        print(f"  尚未對應到法規（之後比對到就會補上）：{preview}{more}")
    print(f"法規主檔目前共 {total} 筆")
    print(f"資料庫：{settings.DATABASE_URL}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed())
