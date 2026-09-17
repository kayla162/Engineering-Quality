"""GET /api/sources：前端在畫面上提示「來源未就緒」的依據。

沒有這支 API 的話，使用者只會看到滿頁 UNKNOWN，卻不知道是因為部署方還沒跑
同步腳本。所以它必須在「還沒開始分析」的時候就能回答：現在查得到東西嗎？
"""

import pytest

from app.sources.base import RegulationSearchResult, RegulationSource, SourceReadiness

MISSING = "找不到全國法規資料庫索引 /app/data/taiwan_law_index.json（尚未同步官方資料）"
SYNC_COMMAND = "python scripts/sync_taiwan_law.py"


class UnsyncedSource(RegulationSource):
    source_name = "unsynced"

    def readiness(self) -> SourceReadiness:
        return SourceReadiness(
            source=self.source_name, ready=False, detail=MISSING, remedy=SYNC_COMMAND
        )

    async def search(self, query: str) -> list[RegulationSearchResult]:
        return []

    async def get_detail(self, regulation_id: str):
        return None

    async def get_version_history(self, regulation_id: str):
        return []


@pytest.fixture
def unsynced_only(monkeypatch):
    from app.core.config import settings
    from app.sources import _REGISTRY, reset_sources

    monkeypatch.setitem(_REGISTRY, "unsynced", UnsyncedSource)
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "unsynced")
    reset_sources()
    yield
    reset_sources()


class TestSourcesStatus:
    async def test_ready_sources_report_ok(self, api_client):
        """conftest 只啟用 mock，假資料檔隨專案提供，所以是就緒的。"""
        response = await api_client.get("/api/sources")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert [s["source"] for s in body["sources"]] == ["mock"]
        assert body["sources"][0]["ready"] is True

    async def test_unready_source_reports_cause_and_command(self, api_client, unsynced_only):
        """前端要能直接把 detail 與 remedy 印在畫面上，不用自己拼字串。"""
        response = await api_client.get("/api/sources")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["sources"][0]["detail"] == MISSING
        assert body["sources"][0]["remedy"] == SYNC_COMMAND
