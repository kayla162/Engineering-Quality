"""目錄同步接上法規異動監控：sync_catalogs 把官方頁面的廢止寫進行政規則目錄後，
check_regulation_changes 會把「文件引用到的那部」列成異動——和全國法規同步是同一條路。"""

import json

import pytest

from app.core.config import settings
from app.services import regulation_change_service
from app.sources import reset_sources
from app.sources.admin_rules_source import AdminRulesSource
from app.sources.catalog_sync import sync_admin_rules

RULE = "新北市樹木保護自治條例"
REPEALED_PAGE = (
    '<html><head><meta charset="big5"></head><body>'
    f"<p>法規名稱：{RULE}</p><p>公發布時間：民國 102 年 06 月 19 日</p><p>廢止時間：民國 115 年 12 月 01 日</p>"
    "</body></html>"
).encode("cp950")


@pytest.fixture(autouse=True)
def admin_rules_enabled(monkeypatch):
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "admin_rules,mock")
    reset_sources()
    yield
    reset_sources()


async def test_a_synced_repeal_shows_up_as_a_regulation_change(api_client, tmp_path, monkeypatch):
    files = {"file": ("規則.txt", f"移植樹木應依{RULE}辦理。".encode(), "text/plain")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
    await api_client.post(f"/api/documents/{document_id}/analyze")

    catalog = json.loads((settings.DATA_DIR / "admin_rules.json").read_text(encoding="utf-8"))
    target = next(r for r in catalog["rules"] if r["name"] == RULE)
    result = sync_admin_rules([target], fetcher=lambda url: REPEALED_PAGE)
    assert result.changed and target["status"] == "REPEALED"
    synced = tmp_path / "admin_rules.json"
    synced.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")

    async def synced_sources(session, tenant_id):
        return [AdminRulesSource(synced)]

    monkeypatch.setattr(regulation_change_service, "sources_for_tenant", synced_sources)
    response = await api_client.post("/api/regulation-changes/check")
    assert response.status_code == 200, response.text

    changes = (await api_client.get("/api/regulation-changes")).json()
    items = changes["items"] if isinstance(changes, dict) else changes
    (change,) = [c for c in items if c["regulation_name"] == RULE]
    assert change["changes"]["status"] == {"old": "ACTIVE", "new": "REPEALED"}
