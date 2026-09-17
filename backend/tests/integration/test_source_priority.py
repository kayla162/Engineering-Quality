"""多來源時的優先序行為。

背景：接上官方來源後，實務上會同時啟用 taiwan_law（官方）與 mock（補 CNS 等
官方沒有的項目）。來源回傳的是「前幾名相似結果」，因此低優先來源很容易在查
A 法規時順帶回傳 B 法規。如果放著不管，會出現：
    1. 低優先來源的資料覆蓋官方資料
    2. 低優先來源先建立的資料，讓官方來源永遠不會被詢問（被 TTL 快取擋住）
這兩種都會讓報告顯示錯誤的法規狀態，所以用測試釘住。
"""

import uuid

import pytest

from app.core.enums import ExtractionMethod, RegulationStatus, RegulationType
from app.models.reference import RegulationReference
from app.repositories.regulations import RegulationRepository
from app.services.matching_service import MatchingService
from app.sources import base as sources_base
from app.sources.base import RegulationSearchResult, RegulationSource

OFFICIAL = "官方法規"
NEIGHBOUR = "官方法規施行細則"


def result(name: str, source: str, status: RegulationStatus, relevance: float):
    return RegulationSearchResult(
        external_id=f"{source}-{name}",
        name=name,
        type=RegulationType.REGULATION,
        status=status,
        source=source,
        relevance=relevance,
    )


class PrimarySource(RegulationSource):
    """官方來源：只認得自己那兩部法規，而且 NEIGHBOUR 是 AMENDED。"""

    source_name = "primary"

    async def search(self, query: str) -> list[RegulationSearchResult]:
        if query == OFFICIAL:
            return [result(OFFICIAL, "primary", RegulationStatus.ACTIVE, 1.0)]
        if query == NEIGHBOUR:
            return [result(NEIGHBOUR, "primary", RegulationStatus.AMENDED, 1.0)]
        return []

    async def get_detail(self, regulation_id: str):
        return None

    async def get_version_history(self, regulation_id: str):
        return []


class SecondarySource(RegulationSource):
    """次要來源：查 OFFICIAL 時會順帶回傳 NEIGHBOUR，而且說它是 ACTIVE。"""

    source_name = "secondary"

    async def search(self, query: str) -> list[RegulationSearchResult]:
        if query == OFFICIAL:
            return [
                result(OFFICIAL, "secondary", RegulationStatus.ACTIVE, 1.0),
                result(NEIGHBOUR, "secondary", RegulationStatus.ACTIVE, 0.75),
            ]
        if query == NEIGHBOUR:
            return [result(NEIGHBOUR, "secondary", RegulationStatus.ACTIVE, 1.0)]
        return []

    async def get_detail(self, regulation_id: str):
        return None

    async def get_version_history(self, regulation_id: str):
        return []


@pytest.fixture
def two_sources(monkeypatch):
    from app.core.config import settings
    from app.sources import _REGISTRY, reset_sources

    monkeypatch.setitem(_REGISTRY, "primary", PrimarySource)
    monkeypatch.setitem(_REGISTRY, "secondary", SecondarySource)
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "primary,secondary")
    reset_sources()
    yield
    reset_sources()


async def _resolve(session, document_id: uuid.UUID, name: str) -> RegulationReference:
    reference = RegulationReference(
        document_id=document_id,
        raw_text=name,
        normalized_name=name,
        regulation_type=RegulationType.REGULATION,
        extraction_method=ExtractionMethod.DICTIONARY,
    )
    session.add(reference)
    await session.flush()
    await MatchingService(session).resolve(reference)
    await session.commit()
    return reference


class TestSourcePriority:
    async def test_higher_priority_source_owns_the_record(
        self, db_session, uploaded_document, two_sources
    ):
        reference = await _resolve(db_session, uploaded_document.id, OFFICIAL)
        assert reference.status == RegulationStatus.ACTIVE

        regulation = await RegulationRepository(db_session).get_by_name(OFFICIAL)
        assert regulation.source == "primary", "官方來源的資料不應該被次要來源覆蓋"

    async def test_secondary_side_result_does_not_block_the_primary_source(
        self, db_session, uploaded_document, two_sources
    ):
        """次要來源在查 A 時順帶寫入的 B，不能讓 B 之後查不到官方狀態。"""
        # 先查 OFFICIAL：次要來源會順帶把 NEIGHBOUR 以 ACTIVE 寫進主檔
        await _resolve(db_session, uploaded_document.id, OFFICIAL)
        repo = RegulationRepository(db_session)
        seeded = await repo.get_by_name(NEIGHBOUR)
        assert seeded is not None and seeded.source == "secondary"

        # 再查 NEIGHBOUR：必須實際去問官方來源，拿到 AMENDED
        reference = await _resolve(db_session, uploaded_document.id, NEIGHBOUR)
        assert reference.status == RegulationStatus.AMENDED

        regulation = await repo.get_by_name(NEIGHBOUR)
        assert regulation.source == "primary"
        assert regulation.status == RegulationStatus.AMENDED

    async def test_weak_neighbour_is_not_written_to_master(
        self, db_session, uploaded_document, two_sources, monkeypatch
    ):
        """相關度低於比對門檻的鄰居不該進主檔。"""
        from app.core.config import settings

        # 把門檻拉到 0.8，讓次要來源 0.75 的鄰居落在門檻之下
        monkeypatch.setattr(settings, "MATCH_POSSIBLE_THRESHOLD", 0.8)
        await _resolve(db_session, uploaded_document.id, OFFICIAL)
        assert await RegulationRepository(db_session).get_by_name(NEIGHBOUR) is None


def test_source_priority_helper(monkeypatch):
    from app.core.config import settings
    from app.sources import source_priority

    monkeypatch.setattr(settings, "REGULATION_SOURCES", "taiwan_law,mock")
    assert source_priority("taiwan_law") < source_priority("mock")
    # 沒啟用的來源排最後
    assert source_priority("nope") > source_priority("mock")


def test_base_module_is_importable():
    assert sources_base.RegulationSource is RegulationSource
