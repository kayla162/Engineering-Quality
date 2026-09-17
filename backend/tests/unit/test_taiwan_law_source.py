"""全國法規資料庫 adapter 的單元測試。

用固定的假索引，不連網路。真實 API 的格式已於 2026-09 查證，
欄位名稱依 ZIP 內的官方 schema.csv。
"""

import json
from datetime import date

import pytest

from app.core.enums import RegulationStatus, RegulationType
from app.core.errors import SourceQueryError
from app.sources.taiwan_law_source import (
    TaiwanLawSource,
    authority_from_category,
    decide_status,
)

# 欄位形狀與 scripts/sync_taiwan_law.py 產出的索引一致
ENTRIES = [
    {
        "external_id": "A0030057", "name": "政府採購法", "level": "法律",
        "category": "行政＞行政院公共工程委員會＞通用目", "url": "https://law.moj.gov.tw/x?pcode=A0030057",
        "modified_date": "20190522", "effective_date": "", "effective_note": "",
        "abandoned": False, "eng_name": "Government Procurement Act",
    },
    {
        "external_id": "N0060009", "name": "職業安全衛生設施規則", "level": "命令",
        "category": "勞動＞安全衛生目", "url": "https://law.moj.gov.tw/x?pcode=N0060009",
        "modified_date": "20260630", "effective_date": "20270101",
        "effective_note": "一百十五年六月三十日修正之第 21-3 條，自一百十六年一月一日施行。",
        "abandoned": False, "eng_name": "",
    },
    {
        "external_id": "N0000009", "name": "勞工安全衛生諮詢委員會設置辦法", "level": "命令",
        "category": "勞動＞安全衛生目", "url": "https://law.moj.gov.tw/x?pcode=N0000009",
        "modified_date": "20100917", "effective_date": "", "effective_note": "",
        "abandoned": True, "eng_name": "",
    },
]


@pytest.fixture
def source(tmp_path) -> TaiwanLawSource:
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps({"source": "taiwan_law", "count": len(ENTRIES), "regulations": ENTRIES}),
        encoding="utf-8",
    )
    return TaiwanLawSource(index_path=path)


class TestStatusMapping:
    """官方欄位 -> 六種狀態。這是接真實資料後最關鍵的一段對應。"""

    def test_abandoned_note_means_repealed(self):
        status, note = decide_status({"abandoned": True})
        assert status is RegulationStatus.REPEALED
        assert "廢止" in note

    def test_future_effective_date_means_amended(self):
        status, note = decide_status(
            {"abandoned": False, "effective_date": "20270101"}, today=date(2026, 9, 9)
        )
        assert status is RegulationStatus.AMENDED
        assert "2027-01-01" in note

    def test_past_effective_date_is_active(self):
        status, note = decide_status(
            {"abandoned": False, "effective_date": "20200101"}, today=date(2026, 9, 9)
        )
        assert status is RegulationStatus.ACTIVE
        assert note is None

    def test_no_effective_date_is_active(self):
        status, _ = decide_status({"abandoned": False, "effective_date": ""})
        assert status is RegulationStatus.ACTIVE

    def test_amended_note_carries_official_wording(self):
        _, note = decide_status(
            {"abandoned": False, "effective_date": "20270101", "effective_note": "官方說明文字"},
            today=date(2026, 9, 9),
        )
        assert "官方說明文字" in note


class TestAuthority:
    """官方資料集沒有「發布機關」欄位，只能從法規類別的階層路徑推導。"""

    @pytest.mark.parametrize(
        "category, expected",
        [
            ("行政＞行政院公共工程委員會＞通用目", "行政院公共工程委員會"),
            ("行政＞勞動部＞職業安全衛生目", "勞動部"),
            ("廢止法規＞內政部", "內政部"),
            ("憲法", None),      # 只有一段，推不出來就不猜
            ("立法", None),
            ("", None),
        ],
    )
    def test_authority_from_category(self, category, expected):
        assert authority_from_category(category) == expected


class TestSearch:
    async def test_exact_name(self, source):
        results = await source.search("政府採購法")
        assert results[0].name == "政府採購法"
        assert results[0].external_id == "A0030057"
        assert results[0].status == RegulationStatus.ACTIVE
        assert results[0].source == "taiwan_law"

    async def test_authority_is_the_ministry_not_the_whole_path(self, source):
        result = (await source.search("政府採購法"))[0]
        assert result.authority == "行政院公共工程委員會"

    async def test_official_dates_are_parsed(self, source):
        result = (await source.search("政府採購法"))[0]
        assert result.last_amended_date == date(2019, 5, 22)
        assert result.official_url.endswith("pcode=A0030057")

    async def test_law_level_maps_to_type(self, source):
        assert (await source.search("政府採購法"))[0].type == RegulationType.LAW
        assert (await source.search("職業安全衛生設施規則"))[0].type == RegulationType.REGULATION

    async def test_official_source_can_confirm_currency(self, source):
        """官方來源查得到現行版本，所以不會像付費標準那樣被降級。"""
        assert (await source.search("政府採購法"))[0].can_confirm_currency is True

    async def test_unrelated_query_returns_nothing(self, source):
        assert await source.search("CNS 3090") == []

    async def test_empty_query_returns_nothing(self, source):
        assert await source.search("   ") == []

    async def test_missing_index_raises_actionable_error(self, tmp_path):
        """訊息說「缺什麼」，remedy 說「跑什麼」。分開放，呼叫端才能各自排版。"""
        source = TaiwanLawSource(index_path=tmp_path / "nope.json")
        with pytest.raises(SourceQueryError) as excinfo:
            await source.search("政府採購法")

        assert "nope.json" in excinfo.value.message
        assert "sync_taiwan_law.py" in excinfo.value.remedy


class TestDetail:
    async def test_detail_includes_version(self, source):
        detail = await source.get_detail("N0060009")
        assert detail.name == "職業安全衛生設施規則"
        assert detail.versions[0].amended_date == date(2026, 6, 30)
        assert detail.versions[0].effective_date == date(2027, 1, 1)

    async def test_unknown_id(self, source):
        assert await source.get_detail("NOPE") is None
