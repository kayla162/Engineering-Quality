"""法規問答：引用驗證、狀態判定、Anthropic 請求格式（不呼叫真的 API）。"""

import json
from types import SimpleNamespace

import pytest

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import Citation, Passage
from app.ai.demo_provider import DemoProvider
from app.core.config import settings
from app.search.grounding import check_citations, normalize
from app.services.regulation_qa_service import ANSWERED, INSUFFICIENT, UNVERIFIED, decide

PASSAGES = [
    Passage(
        "營造安全衛生設施標準 第 71 條",
        "雇主僱用勞工從事露天開挖作業，其開挖垂直最大深度應妥為設計；其深度在一點五公尺以上，"
        "使勞工進入開挖面作業者，應設擋土支撐。",
    ),
    Passage("建築法 第 69 條", "建築物在施工中，鄰接其他建築物施行挖土工程時，對該鄰接建築物應視需要作防護其傾斜或倒壞之措施。"),
]


class TestGrounding:
    def test_exact_quote_passes(self):
        [checked] = check_citations([Citation(ref=PASSAGES[0].ref, quote="其深度在一點五公尺以上")], PASSAGES)
        assert checked.verified and checked.problem is None

    def test_whitespace_and_full_width_differences_are_ignored(self):
        quote = "其深度在一點五公尺以上， 使勞工進入開挖面作業者"
        assert normalize("ａ，ｂ") == normalize("a,b")
        assert check_citations([Citation(ref=PASSAGES[0].ref, quote=quote)], PASSAGES)[0].verified

    def test_paraphrase_is_rejected(self):
        [checked] = check_citations([Citation(ref=PASSAGES[0].ref, quote="挖超過 1.5 公尺要做擋土支撐")], PASSAGES)
        assert not checked.verified
        assert "原文" in checked.problem

    def test_quote_from_another_article_is_rejected(self):
        """引文是真的，但掛錯條：張冠李戴也要擋下來。"""
        [checked] = check_citations([Citation(ref=PASSAGES[1].ref, quote="應設擋土支撐")], PASSAGES)
        assert not checked.verified

    def test_article_not_provided_is_rejected(self):
        [checked] = check_citations([Citation(ref="建築法 第 999 條", quote="應設擋土支撐")], PASSAGES)
        assert not checked.verified
        assert "範圍" in checked.problem

    def test_too_short_quote_is_rejected(self):
        assert not check_citations([Citation(ref=PASSAGES[0].ref, quote="雇主")], PASSAGES)[0].verified


class TestDecide:
    def test_not_answerable_is_insufficient(self):
        assert decide(False, "條文沒有規定", []) == (INSUFFICIENT, "條文沒有規定")

    def test_answer_without_any_verified_citation_is_hidden(self):
        checked = check_citations([Citation(ref=PASSAGES[0].ref, quote="捏造的句子內容")], PASSAGES)
        assert decide(True, "要做擋土支撐", checked) == (UNVERIFIED, "")

    def test_one_verified_citation_is_enough_to_show(self):
        checked = check_citations(
            [
                Citation(ref=PASSAGES[0].ref, quote="應設擋土支撐"),
                Citation(ref=PASSAGES[1].ref, quote="捏造的句子內容"),
            ],
            PASSAGES,
        )
        status, answer = decide(True, "深度一點五公尺以上要設擋土支撐", checked)
        assert status == ANSWERED and answer
        assert [c.verified for c in checked] == [True, False]


class TestDemoProvider:
    async def test_quotes_top_passage_verbatim(self):
        result = await DemoProvider().answer_regulation_question("挖多深要支撐", PASSAGES)

        assert result.value.answerable
        assert check_citations(result.value.citations, PASSAGES)[0].verified
        assert "非 AI" in result.value.answer

    async def test_nothing_retrieved(self):
        result = await DemoProvider().answer_regulation_question("任何問題", [])
        assert not result.value.answerable


class _FakeMessages:
    def __init__(self, payload: dict):
        self.payload = payload
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0),
        )


class _FakeClient:
    def __init__(self, payload):
        self.beta = SimpleNamespace(messages=_FakeMessages(payload))
        self.messages = _FakeMessages(payload)

    def with_options(self, **_):
        return self


class TestAnthropicRequest:
    @pytest.fixture
    def provider(self):
        provider = AnthropicProvider(api_key="test-key")
        provider._client = _FakeClient(
            {"answerable": True, "answer": "要設擋土支撐", "citations": [{"ref": PASSAGES[0].ref, "quote": "應設擋土支撐"}]}
        )
        return provider

    async def test_request_uses_qa_model_effort_fallbacks_and_schema(self, provider):
        result = await provider.answer_regulation_question("挖多深要支撐", PASSAGES)

        sent = provider._client.beta.messages.kwargs
        assert sent["model"] == settings.QA_MODEL
        assert sent["output_config"]["effort"] == settings.QA_EFFORT
        assert sent["output_config"]["format"]["type"] == "json_schema"
        assert sent["fallbacks"] == "default"
        assert "server-side-fallback-2026-07-01" in sent["betas"]
        assert "<question>" in sent["messages"][0]["content"]
        assert result.value.citations[0].ref == PASSAGES[0].ref
        assert result.record.usage["input_tokens"] == 1200

    async def test_other_calls_are_unchanged(self, provider):
        """抽取等既有呼叫仍走一般 endpoint、沿用 ANTHROPIC_MODEL。"""
        provider._client.messages.payload = {"items": []}
        await provider.extract_regulations("依建築法辦理")

        sent = provider._client.messages.kwargs
        assert sent["model"] == settings.ANTHROPIC_MODEL
        assert "fallbacks" not in sent


def test_schema_closes_nested_objects():
    """巢狀模型（$defs 裡的 Citation）也要 additionalProperties: false，否則 API 回 400。"""
    from app.ai.anthropic_provider import _json_schema
    from app.ai.base import RegulationAnswer

    schema = _json_schema(RegulationAnswer)

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Citation"]["additionalProperties"] is False


async def test_models_without_server_fallbacks_do_not_send_them(monkeypatch):
    """Haiku 5.5 不支援伺服器端 fallbacks，送了會 400：改走一般 endpoint、不帶這個參數。"""
    monkeypatch.setattr(settings, "QA_MODEL", "claude-haiku-5-5")
    provider = AnthropicProvider(api_key="test-key")
    provider._client = _FakeClient({"answerable": False, "answer": "不足", "citations": []})

    await provider.answer_regulation_question("任何問題", PASSAGES)

    assert provider._client.beta.messages.kwargs is None
    sent = provider._client.messages.kwargs
    assert sent["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in sent
