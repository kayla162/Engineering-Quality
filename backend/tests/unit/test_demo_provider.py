"""示範用的 AI（LLM_PROVIDER=demo）：固定規則，但紀錄與流程和真的 provider 一樣。"""

import pytest

from app.ai import factory
from app.ai.demo_provider import MODEL_NAME, DemoProvider
from app.core.config import settings
from app.core.enums import AIPurpose


@pytest.fixture
def provider():
    return DemoProvider()


class TestDemoProvider:
    async def test_extraction_finds_document_like_names(self, provider):
        result = await provider.extract_regulations("各分項工程依品質稽核程序書及公司工安手冊辦理。")

        assert [item.raw_text for item in result.value.items] == ["品質稽核程序書", "公司工安手冊"]

    async def test_extraction_with_nothing_found_is_still_recorded(self, provider):
        result = await provider.extract_regulations("本段只有一般敘述。")

        assert result.value.items == []
        assert result.record.purpose == AIPurpose.EXTRACTION

    async def test_every_record_says_it_is_not_real_ai(self, provider):
        result = await provider.judge_similarity("混凝土結構施工規範", "結構混凝土施工規範")

        assert result.record.model == MODEL_NAME
        assert "非真實 AI" in result.record.model
        assert "非 AI 判斷" in result.value.reason

    async def test_similar_names_are_judged_the_same(self, provider):
        result = await provider.judge_similarity("職業安全衛生設施規則", "職業安全衛生設施規則草案")

        assert result.value.is_same is True

    async def test_different_names_are_not(self, provider):
        result = await provider.judge_similarity("政府採購法", "建築法")

        assert result.value.is_same is False

    async def test_summary_lists_the_findings_and_says_it_is_a_template(self, provider):
        result = await provider.summarize_for_report(["2 筆已廢止", "3 筆查無此法規"])

        assert "非 AI 撰寫" in result.value
        assert "1. 2 筆已廢止" in result.value


class TestFactory:
    def test_demo_needs_no_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_LLM_FALLBACK", True)
        monkeypatch.setattr(settings, "LLM_PROVIDER", "demo")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
        factory.reset_llm_provider()
        try:
            provider = factory.get_llm_provider()
            assert isinstance(provider, DemoProvider)
            assert provider.enabled is True
        finally:
            factory.reset_llm_provider()


class TestThroughThePipeline:
    async def test_a_fallback_extraction_shows_up_on_the_reference(self, api_client, monkeypatch):
        """規則與字典都抽不到的段落交給 demo；結果與紀錄要一路走到詳細面板。"""
        monkeypatch.setattr(settings, "ENABLE_LLM_FALLBACK", True)
        monkeypatch.setattr(settings, "LLM_PROVIDER", "demo")
        factory.reset_llm_provider()
        try:
            files = {"file": ("內部稽核.txt", "各分項工程依品質稽核程序書辦理。".encode(), "text/plain")}
            document_id = (await api_client.post("/api/documents/upload", files=files)).json()[
                "document_id"
            ]
            await api_client.post(f"/api/documents/{document_id}/analyze")
            item = (await api_client.get(f"/api/documents/{document_id}/references")).json()[
                "items"
            ][0]
            detail = (await api_client.get(f"/api/regulation-references/{item['reference_id']}")).json()
        finally:
            factory.reset_llm_provider()

        assert detail["raw_text"] == "品質稽核程序書"
        assert detail["extraction_method"] == "llm_fallback"
        assert detail["ai_invocations"][0]["model"] == MODEL_NAME
