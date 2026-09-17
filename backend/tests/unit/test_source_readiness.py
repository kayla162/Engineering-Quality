"""法規來源的就緒狀態。

背景：官方法規索引是由 scripts/sync_taiwan_law.py 同步下來的本地檔案，
「有沒有跑過 sync」是部署方的責任。沒跑就查不到任何法規，整份報告會變成
滿頁 UNKNOWN。所以系統要能在分析之前就講清楚：哪個來源沒就緒、為什麼、
要跑什麼命令才會就緒（docs/api.md 第 7 節）。
"""

import json

import pytest

from app.core.enums import SourceAvailability
from app.sources import readiness_report
from app.sources.base import RegulationSearchResult, RegulationSource, SourceReadiness
from app.sources.mock_source import MockRegulationSource
from app.sources.taiwan_law_source import TaiwanLawSource

ENTRY = {
    "external_id": "A0030057", "name": "政府採購法", "level": "法律",
    "category": "行政＞行政院公共工程委員會＞通用目", "url": "",
    "modified_date": "20190522", "effective_date": "", "effective_note": "",
    "abandoned": False, "eng_name": "",
}


@pytest.fixture
def index_path(tmp_path):
    path = tmp_path / "taiwan_law_index.json"
    path.write_text(
        json.dumps({"source": "taiwan_law", "count": 1, "regulations": [ENTRY]}),
        encoding="utf-8",
    )
    return path


class TestTaiwanLawReadiness:
    def test_missing_index_is_not_ready_and_says_what_to_run(self, tmp_path):
        """訊息要同時包含「缺哪個檔」與「跑什麼命令」，客戶才知道下一步。"""
        readiness = TaiwanLawSource(index_path=tmp_path / "nope.json").readiness()

        assert readiness.ready is False
        assert readiness.source == "taiwan_law"
        assert "nope.json" in readiness.detail
        assert "scripts/sync_taiwan_law.py" in readiness.remedy

    def test_present_index_is_ready(self, index_path):
        readiness = TaiwanLawSource(index_path=index_path).readiness()

        assert readiness.ready is True
        assert readiness.detail is None
        assert readiness.remedy is None

    def test_corrupt_index_is_not_ready(self, tmp_path):
        """檔案在、但內容壞掉，一樣查不到東西，不能報成就緒。"""
        path = tmp_path / "taiwan_law_index.json"
        path.write_text("{ 這不是 JSON", encoding="utf-8")

        readiness = TaiwanLawSource(index_path=path).readiness()

        assert readiness.ready is False
        assert "格式錯誤" in readiness.detail

    def test_readiness_does_not_raise(self, tmp_path):
        """就緒檢查本身不能丟例外，否則 /api/sources 會變成 500。"""
        assert TaiwanLawSource(index_path=tmp_path / "nope.json").readiness().ready is False


class TestMockReadiness:
    def test_missing_data_file_is_not_ready(self, tmp_path):
        readiness = MockRegulationSource(data_path=tmp_path / "nope.json").readiness()

        assert readiness.ready is False
        assert "nope.json" in readiness.detail

    def test_shipped_data_file_is_ready(self):
        assert MockRegulationSource().readiness().ready is True


class _FakeSource(RegulationSource):
    """只用來測聚合邏輯，不查任何東西。"""

    def __init__(self, name: str, ready: bool):
        self.source_name = name
        self._ready = ready

    def readiness(self) -> SourceReadiness:
        return SourceReadiness(
            source=self.source_name,
            ready=self._ready,
            detail=None if self._ready else "沒就緒",
            remedy=None if self._ready else "跑那個命令",
        )

    async def search(self, query: str) -> list[RegulationSearchResult]:
        return []

    async def get_detail(self, regulation_id: str):
        return None

    async def get_version_history(self, regulation_id: str):
        return []


class TestReadinessReport:
    """整體狀態決定前端要不要跳警告，以及跳多大聲。"""

    def test_all_ready_is_ok(self):
        report = readiness_report([_FakeSource("a", True), _FakeSource("b", True)])

        assert report.status is SourceAvailability.OK
        assert [s.source for s in report.sources] == ["a", "b"]

    def test_some_ready_is_degraded(self):
        """還有來源可用，查得到東西但涵蓋範圍縮小——要提醒，但不是全毀。"""
        report = readiness_report([_FakeSource("a", False), _FakeSource("b", True)])

        assert report.status is SourceAvailability.DEGRADED

    def test_none_ready_is_unavailable(self):
        """一個來源都沒就緒 = 之後每一筆引用都會是 UNKNOWN。"""
        report = readiness_report([_FakeSource("a", False), _FakeSource("b", False)])

        assert report.status is SourceAvailability.UNAVAILABLE

    def test_no_sources_configured_is_unavailable(self):
        """REGULATION_SOURCES 設成空字串時同樣是全部查不到，不能報成 ok。"""
        report = readiness_report([])

        assert report.status is SourceAvailability.UNAVAILABLE
        assert report.sources == []
