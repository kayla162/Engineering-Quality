"""來源查不動時，那一筆引用要說清楚「為什麼」與「怎麼辦」。

背景：官方索引是本地檔案，要先跑同步腳本才會有。沒跑的話每一筆引用都會是
UNKNOWN。使用者看到的第一個線索就是這裡寫進 match_reasons 的理由，
所以它必須同時交代原因與下一步，而且不能叫人做沒用的事（例如索引根本沒同步
過時還叫人「稍後重試」）。
"""

import uuid

import pytest

from app.core.enums import ExtractionMethod, RegulationStatus, RegulationType
from app.core.errors import SourceQueryError
from app.models.reference import RegulationReference
from app.services.matching_service import MatchingService
from app.sources.base import RegulationSearchResult, RegulationSource

MISSING_INDEX = "找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）"
SYNC_COMMAND = "python scripts/sync_taiwan_law.py"
UNMATCHABLE = "完全不存在的某某某管理辦法"


class UnsyncedSource(RegulationSource):
    """模擬「索引還沒同步」的來源：查什麼都失敗，並附上補救命令。"""

    source_name = "unsynced"
    remedy: str | None = SYNC_COMMAND

    async def search(self, query: str) -> list[RegulationSearchResult]:
        raise SourceQueryError(self.source_name, MISSING_INDEX, remedy=self.remedy)

    async def get_detail(self, regulation_id: str):
        return None

    async def get_version_history(self, regulation_id: str):
        return []


class FlakySource(UnsyncedSource):
    """模擬暫時性失敗（timeout / 5xx）：沒有補救命令可以給。"""

    source_name = "flaky"
    remedy = None


@pytest.fixture
def only_source(monkeypatch):
    """把唯一啟用的來源換成指定的 adapter。"""

    def _use(source_class: type[RegulationSource]):
        from app.core.config import settings
        from app.sources import _REGISTRY, reset_sources

        monkeypatch.setitem(_REGISTRY, source_class.source_name, source_class)
        monkeypatch.setattr(settings, "REGULATION_SOURCES", source_class.source_name)
        reset_sources()

    yield _use
    from app.sources import reset_sources

    reset_sources()


async def _resolve(session, document_id: uuid.UUID) -> RegulationReference:
    reference = RegulationReference(
        document_id=document_id,
        raw_text=UNMATCHABLE,
        normalized_name=UNMATCHABLE,
        regulation_type=RegulationType.REGULATION,
        extraction_method=ExtractionMethod.DICTIONARY,
    )
    session.add(reference)
    await session.flush()
    await MatchingService(session).resolve(reference)
    await session.commit()
    return reference


class TestUnknownReason:
    async def test_reason_names_the_cause_and_the_command(
        self, db_session, uploaded_document, only_source
    ):
        only_source(UnsyncedSource)

        reference = await _resolve(db_session, uploaded_document.id)

        assert reference.status == RegulationStatus.UNKNOWN
        assert MISSING_INDEX in reference.match_reasons
        assert SYNC_COMMAND in reference.match_reasons

    async def test_reason_does_not_suggest_retrying_when_a_command_is_needed(
        self, db_session, uploaded_document, only_source
    ):
        """索引沒同步過，重試一百次也一樣——不要給沒有用的指示。"""
        only_source(UnsyncedSource)

        reference = await _resolve(db_session, uploaded_document.id)

        assert "重試" not in reference.match_reasons

    async def test_transient_failure_still_suggests_retrying(
        self, db_session, uploaded_document, only_source
    ):
        """沒有補救命令的失敗（timeout / 5xx）本來就該稍後再試。"""
        only_source(FlakySource)

        reference = await _resolve(db_session, uploaded_document.id)

        assert reference.status == RegulationStatus.UNKNOWN
        assert "重試" in reference.match_reasons
