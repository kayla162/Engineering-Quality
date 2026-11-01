"""示範標準目錄（standards_demo）：標準有資料來源可查時，版次與廢止怎麼判定。

data/demo_standards.json 是假資料：CNS 3090 最新 2022 年版、CNS 4750 已廢止。
"""

import pytest

from app.core.config import settings
from app.core.enums import RegulationStatus
from app.sources import reset_sources
from app.sources.standards_demo_source import DemoStandardsSource, standard_key
from tests.api.test_checklist_api import attach_spec, project_with_boq, url  # noqa: F401

TEXT = (
    "預拌混凝土應符合 CNS 3090 之規定。"
    "混凝土試驗依 CNS 3090:2015 辦理。"
    "鋼筋依 CNS 4750 規定。"
    "品質管理系統依 ISO 9001:2015 建立。"
    "另參考 CNS 99999 辦理。"
)


@pytest.fixture(autouse=True)
def standards_enabled(monkeypatch):
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "standards_demo,mock")
    reset_sources()
    yield
    reset_sources()


async def analyze(api_client, text: str) -> dict[str, dict]:
    files = {"file": ("標準.txt", text.encode(), "text/plain")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    items = (
        await api_client.get(f"/api/documents/{document_id}/references", params={"page_size": 500})
    ).json()["items"]
    return {item["raw_text"]: item for item in items}


class TestStandardKey:
    @pytest.mark.parametrize(
        "text,key",
        [
            ("CNS 3090", "CNS 3090"),
            ("CNS3090:2015", "CNS 3090"),
            ("cns 3090", "CNS 3090"),
            ("ASTM C39/C39M-23", "ASTM C39"),
            ("ISO 9001:2015", "ISO 9001"),
            ("政府採購法", None),
        ],
    )
    def test_numbers_are_normalized(self, text, key):
        assert standard_key(text) == key


class TestSource:
    async def test_a_number_finds_its_standard(self):
        results = await DemoStandardsSource().search("CNS 3090:2015")

        assert [r.name for r in results] == ["CNS 3090 預拌混凝土"]
        assert results[0].can_confirm_currency is True

    async def test_an_unknown_number_finds_nothing(self):
        assert await DemoStandardsSource().search("CNS 99999") == []


class TestMatching:
    async def test_a_current_standard_is_active_not_possible_match(self, api_client):
        """mock 只能說「存在」，所以永遠是疑似對應；有目錄就能確認現行。"""
        references = await analyze(api_client, TEXT)

        assert references["CNS 3090"]["status"] == RegulationStatus.ACTIVE

    async def test_an_old_edition_is_amended_with_the_reason(self, api_client):
        references = await analyze(api_client, TEXT)
        item = references["CNS 3090:2015"]
        detail = (await api_client.get(f"/api/regulation-references/{item['reference_id']}")).json()

        assert item["status"] == RegulationStatus.AMENDED
        assert any("2015 年版" in r and "2022 年版" in r for r in detail["match_reasons"])

    async def test_two_editions_do_not_overwrite_each_other(self, api_client):
        """同一部標準以兩個版次被引用：各自判定，不是誰最後寫誰贏。"""
        references = await analyze(api_client, TEXT)

        assert references["CNS 3090"]["regulation_id"] == references["CNS 3090:2015"]["regulation_id"]
        assert references["CNS 3090"]["status"] == RegulationStatus.ACTIVE
        assert references["CNS 3090:2015"]["status"] == RegulationStatus.AMENDED

    async def test_a_withdrawn_standard_is_repealed(self, api_client):
        references = await analyze(api_client, TEXT)

        assert references["CNS 4750"]["status"] == RegulationStatus.REPEALED

    async def test_a_current_edition_stays_active(self, api_client):
        references = await analyze(api_client, TEXT)

        assert references["ISO 9001:2015"]["status"] == RegulationStatus.ACTIVE

    async def test_a_standard_outside_the_catalogue_is_not_found(self, api_client):
        references = await analyze(api_client, TEXT)

        assert references["CNS 99999"]["status"] == RegulationStatus.NOT_FOUND


class TestChecklistBases:
    async def test_standard_bases_are_verified_when_the_catalogue_is_enabled(
        self, api_client, project_with_boq  # noqa: F811
    ):
        await attach_spec(
            api_client,
            project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) CNS 3090 預拌混凝土 (2) CNS 2473 鋼材 1.5 送審")],
        )

        body = (await api_client.post(url(project_with_boq))).json()

        statuses = {b["reference"]: b["verification_status"] for item in body["items"] for b in item["bases"]}
        # 規範書寫的是「CNS 3090 預拌混凝土」，依據照原文引述
        assert statuses["CNS 3090 預拌混凝土"] == RegulationStatus.ACTIVE
        # 目錄裡沒有的標準維持未查證，不說它不存在
        assert statuses["CNS 2473"] is None
