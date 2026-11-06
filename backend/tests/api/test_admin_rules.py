"""行政規則與地方法規目錄（admin_rules）：全國法規資料庫沒有的「要點」「自治條例」怎麼查。

data/admin_rules.json 的名稱取自秀山分隊的契約書與整體品質計畫；狀態與日期 2026-11 依官方法規資料庫查證，
每筆寫明官方網址與未查到的部分。
"""

import pytest

from app.core.config import settings
from app.core.enums import RegulationStatus, RegulationType
from app.sources import reset_sources
from app.sources.admin_rules_source import AdminRulesSource


@pytest.fixture
def source():
    return AdminRulesSource()


class TestSearch:
    @pytest.mark.parametrize(
        "query",
        [
            "加強公共工程職業安全衛生管理作業要點",
            "新北市樹木保護自治條例",
            "建築物無障礙設施設計規範",
        ],
    )
    async def test_exact_name_is_found(self, source, query):
        results = await source.search(query)
        assert [r.name for r in results] == [query]
        assert results[0].status == RegulationStatus.ACTIVE
        assert results[0].source == "admin_rules"

    async def test_alias_finds_the_current_name(self, source):
        results = await source.search("臺北縣政府建築工程施工中管制要點")
        assert [r.name for r in results] == ["新北市政府建築工程施工管理要點"]

    @pytest.mark.parametrize(
        "query, expected",
        [
            # PDF 斷行留下的空白
            ("栽培介質防範紅火蟻移動管理作 業要點", "花卉與種苗及栽培介質防範紅火蟻移動管理作業要點"),
            ("營建混合物資源處理場 設置管理要點", "新北市營建工程剩餘土石方處理及營建混合物資源處理場設置管理要點"),
        ],
    )
    async def test_line_break_spaces_are_ignored(self, source, query, expected):
        assert [r.name for r in await source.search(query)] == [expected]

    @pytest.mark.parametrize("query", ["品質管理標準", "作業要點", "管理要點", "施工規範", "自治條例"])
    async def test_generic_words_find_nothing(self, source, query):
        assert await source.search(query) == []

    async def test_level_decides_the_type(self, source):
        (rule,) = await source.search("加強公共工程職業安全衛生管理作業要點")
        (local_law,) = await source.search("新北市樹木保護自治條例")
        assert rule.type == RegulationType.ANNOUNCEMENT
        assert local_law.type == RegulationType.LAW


class TestProvenance:
    async def test_checked_dates_say_which_pdf(self, source):
        (rule,) = await source.search("建築物無障礙設施設計規範")
        assert str(rule.last_amended_date) == "2019-01-04"
        assert "10.建築物無障礙設施設計規範.pdf" in rule.note

    async def test_verified_records_cite_the_official_page(self, source):
        (rule,) = await source.search("新北市樹木保護自治條例")
        assert "2026-11 查證" in rule.note and "web.law.ntpc.gov.tw" in rule.note
        assert str(rule.effective_date) == "2013-06-19"

    async def test_a_repealed_rule_is_repealed_and_a_renamed_one_is_found_by_its_old_name(self, source):
        (repealed,) = await source.search("營建混合物資源處理場設置管理要點")
        assert repealed.status == RegulationStatus.REPEALED
        (renamed,) = await source.search("栽培介質防範紅火蟻移動管理作業要點")
        assert renamed.name == "花卉與種苗及栽培介質防範紅火蟻移動管理作業要點"

    async def test_every_record_states_where_it_came_from(self, source):
        for record in source._load():
            assert record["provenance"], record["name"]


class TestAnalysis:
    @pytest.fixture(autouse=True)
    def admin_rules_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "REGULATION_SOURCES", "admin_rules,mock")
        reset_sources()
        yield
        reset_sources()

    async def test_cited_rules_become_active(self, api_client):
        text = (
            "工地安全衛生依加強公共工程職業安全衛生管理作業要點辦理。"
            "移植樹木應依新北市樹木保護自治條例辦理。"
        )
        files = {"file": ("規則.txt", text.encode(), "text/plain")}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        await api_client.post(f"/api/documents/{document_id}/analyze")
        items = (
            await api_client.get(f"/api/documents/{document_id}/references", params={"page_size": 500})
        ).json()["items"]
        by_name = {item["raw_text"]: item for item in items}

        assert by_name["加強公共工程職業安全衛生管理作業要點"]["status"] == "ACTIVE"
        assert by_name["新北市樹木保護自治條例"]["status"] == "ACTIVE"

        reference_id = by_name["新北市樹木保護自治條例"]["reference_id"]
        detail = (await api_client.get(f"/api/regulation-references/{reference_id}")).json()
        assert detail["matched_regulation"]["source"] == "admin_rules"
        assert "2026-11 查證" in detail["matched_regulation"]["source_note"]
