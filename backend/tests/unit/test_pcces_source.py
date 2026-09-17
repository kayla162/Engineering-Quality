"""公共工程施工綱要規範（工程會）adapter 的單元測試。

這個來源和其他來源最大的不同：目錄裡存的是「工項/材料名」（卜特蘭水泥、鋼筋、
品質管理），不是文件名。用專案自己的比對器實測過，這些名稱對上帶編號的標準引用
會拿到 0.90 以上、被自動採信：

    CNS 61 卜特蘭水泥        -> 03052 卜特蘭水泥   0.90
    CNS 560 鋼筋混凝土用鋼筋 -> 03210 鋼筋         0.90
    ISO 9001 品質管理系統    -> 01450 品質管理     0.90

所以這個 adapter 不做裸的名稱模糊比對。只有「引用真的指向施工綱要規範」時才回答，
其餘一律回空——寧可讓它落在 NOT_FOUND，也不要製造有信心的錯誤對應。
"""

import json

import pytest

from app.core.enums import RegulationStatus, RegulationType
from app.core.errors import SourceQueryError
from app.sources.pcces_source import PccesSource

CHAPTERS = [
    {"code": "03310", "name": "結構用混凝土", "edition": "8.0"},
    {"code": "03052", "name": "卜特蘭水泥", "edition": "6.0"},
    {"code": "03210", "name": "鋼筋", "edition": "5.0"},
    {"code": "01450", "name": "品質管理", "edition": "8.0"},
    {"code": "10213", "name": "鋁質百葉窗", "edition": "本章已刪除"},
]


@pytest.fixture
def source(tmp_path) -> PccesSource:
    path = tmp_path / "pcces_index.json"
    path.write_text(
        json.dumps({"source": "pcces", "count": len(CHAPTERS), "chapters": CHAPTERS}),
        encoding="utf-8",
    )
    return PccesSource(index_path=path)


class TestChapterLookup:
    async def test_chapter_code_in_citation(self, source):
        results = await source.search("公共工程施工綱要規範第03310章")

        assert len(results) == 1
        assert results[0].external_id == "PCCES-03310"

    async def test_name_carries_both_the_citation_form_and_the_chapter_title(self, source):
        """名稱要照實際被引用的樣子存，否則引擎拿「第03310章」比「結構用混凝土」會比不中。"""
        result = (await source.search("施工綱要規範第03310章"))[0]

        assert "03310" in result.name
        assert "結構用混凝土" in result.name

    async def test_chapter_code_becomes_an_alias(self, source):
        assert (await source.search("施工綱要規範第03310章"))[0].standard_number == "03310"

    async def test_chapter_is_an_engineering_spec(self, source):
        assert (await source.search("施工綱要規範第03310章"))[0].type == RegulationType.ENGINEERING_SPEC

    async def test_bare_chapter_code(self, source):
        assert (await source.search("03310"))[0].external_id == "PCCES-03310"

    async def test_unknown_chapter_code_returns_nothing(self, source):
        """有章碼但目錄裡沒有，就是查無此章——不要退而給規範本體，那會假裝查到了。"""
        assert await source.search("施工綱要規範第99999章") == []


class TestUmbrella:
    async def test_the_specification_itself(self, source):
        results = await source.search("公共工程施工綱要規範")

        assert len(results) == 1
        assert results[0].external_id == "PCCES"
        assert results[0].name == "公共工程施工綱要規範"

    async def test_short_form(self, source):
        assert (await source.search("施工綱要規範"))[0].external_id == "PCCES"

    async def test_chapter_wins_over_the_umbrella(self, source):
        """兩者都符合時要回比較精確的那一個。"""
        assert (await source.search("公共工程施工綱要規範第01450章"))[0].external_id == "PCCES-01450"


class TestGate:
    """閘門：不指向施工綱要規範的引用，這個來源一律不回答。"""

    @pytest.mark.parametrize(
        "query",
        [
            "CNS 61 卜特蘭水泥",
            "CNS 560 鋼筋混凝土用鋼筋",
            "ISO 9001 品質管理系統－要求",
            "ASTM C39/C39M 混凝土圓柱試體抗壓強度試驗法",
            "JIS A 5308",
        ],
    )
    async def test_standard_citations_are_refused(self, source, query):
        """實測過的碰撞來源。標準編號一出現就退出，連比都不要比。"""
        assert await source.search(query) == []

    @pytest.mark.parametrize(
        "query",
        ["卜特蘭水泥", "鋼筋", "品質管理", "結構用混凝土", "公共工程施工品質管理作業要點"],
    )
    async def test_bare_chapter_titles_are_refused(self, source, query):
        """章名長得就像材料名。沒有章碼、也沒說是綱要規範，就不是在引用這份文件。"""
        assert await source.search(query) == []

    async def test_empty_query(self, source):
        assert await source.search("   ") == []


class TestStatus:
    async def test_current_chapter_is_active(self, source):
        result = (await source.search("施工綱要規範第03310章"))[0]

        assert result.status == RegulationStatus.ACTIVE
        assert "8.0" in result.note

    async def test_deleted_chapter_is_repealed(self, source):
        """版次欄不是數字就是官方在講狀態，例如「本章已刪除」。"""
        result = (await source.search("施工綱要規範第10213章"))[0]

        assert result.status == RegulationStatus.REPEALED
        assert "本章已刪除" in result.note

    async def test_official_version_means_currency_is_confirmable(self, source):
        """版次直接來自官方目錄，所以不必像付費標準那樣降級。"""
        assert (await source.search("施工綱要規範第03310章"))[0].can_confirm_currency is True


class TestReadiness:
    async def test_missing_index_is_actionable(self, tmp_path):
        source = PccesSource(index_path=tmp_path / "nope.json")

        with pytest.raises(SourceQueryError) as excinfo:
            await source.search("施工綱要規範")

        assert "nope.json" in excinfo.value.message
        assert "sync_pcces.py" in excinfo.value.remedy

    def test_missing_index_reports_not_ready(self, tmp_path):
        readiness = PccesSource(index_path=tmp_path / "nope.json").readiness()

        assert readiness.ready is False
        assert "sync_pcces.py" in readiness.remedy

    def test_present_index_reports_ready(self, source):
        assert source.readiness().ready is True


class TestDetail:
    async def test_detail_by_external_id(self, source):
        detail = await source.get_detail("PCCES-03310")

        assert detail is not None
        assert "結構用混凝土" in detail.name

    async def test_unknown_id(self, source):
        assert await source.get_detail("PCCES-99999") is None


class TestRegistration:
    def test_registered_so_env_can_enable_it(self):
        """沒註冊的話 REGULATION_SOURCES=pcces 只會被略過，而且只留一行 warning。"""
        from app.sources import _REGISTRY

        assert _REGISTRY["pcces"] is PccesSource
