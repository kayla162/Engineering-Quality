"""POST /api/search/answer：檢索 → 回答 → 驗證引用 → 留下 AI 呼叫紀錄（用假的 provider，不呼叫 API）。"""

import pytest
from sqlalchemy import select

from app.ai.base import Citation, LLMCallRecord, LLMProvider, LLMResult, RegulationAnswer
from app.ai.demo_provider import DemoProvider
from app.ai.null_provider import NullProvider
from app.api.routes import search as search_routes
from app.core.enums import AIPurpose
from app.models.audit import AIInvocationLog
from app.services import knowledge_search_service
from tests.api.test_knowledge_search_api import FakeEmbedder, build


class ScriptedProvider(LLMProvider):
    """照劇本回答的假模型，順便記下收到的條文。"""

    name = "scripted"

    def __init__(self, answer: RegulationAnswer):
        self.answer = answer
        self.passages = None

    @property
    def model(self) -> str:
        return "scripted-model"

    async def extract_regulations(self, text):  # pragma: no cover - 不會用到
        return LLMResult(value=None)

    async def judge_similarity(self, name_a, name_b, context=""):  # pragma: no cover
        return LLMResult(value=None)

    async def summarize_for_report(self, findings):  # pragma: no cover
        return LLMResult(value=None)

    async def answer_regulation_question(self, question, passages):
        self.passages = passages
        record = LLMCallRecord(
            purpose=AIPurpose.REGULATION_QA, model=self.model, prompt_version="qa_test", input_text=question,
            output_json=self.answer.model_dump(), usage={"input_tokens": 100, "output_tokens": 20},
        )
        return LLMResult(value=self.answer, record=record)


@pytest.fixture(autouse=True)
def fresh_cache():
    knowledge_search_service._cache = None
    yield
    knowledge_search_service._cache = None


@pytest.fixture
async def indexed(db_session, monkeypatch):
    embedder = FakeEmbedder()
    await build(db_session, embedder)
    monkeypatch.setattr(search_routes, "get_embedder", lambda: embedder)


def use(monkeypatch, provider):
    monkeypatch.setattr(search_routes, "get_llm_provider", lambda: provider)


async def ask(api_client, question="包商可以把工程丟給別家嗎"):
    response = await api_client.post("/api/search/answer", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


class TestAnswerApi:
    async def test_verified_answer_is_shown_and_logged(self, api_client, db_session, indexed, monkeypatch):
        provider = ScriptedProvider(
            RegulationAnswer(
                answerable=True,
                answer="不行，得標廠商應自行履行，不得轉包。",
                citations=[Citation(ref="政府採購法 第 65 條", quote="得標廠商應自行履行工程，不得轉包")],
            )
        )
        use(monkeypatch, provider)

        body = await ask(api_client)

        assert body["status"] == "answered"
        assert body["answer"].startswith("不行")
        assert body["citations"] == [
            {"ref": "政府採購法 第 65 條", "quote": "得標廠商應自行履行工程，不得轉包", "verified": True, "problem": None}
        ]
        assert body["retrieved"][0] == "政府採購法 第 65 條"
        # 規範章節沒有內文，不送給模型
        assert all(not p.ref.startswith("PCCES") for p in provider.passages)
        [log] = (await db_session.execute(select(AIInvocationLog))).scalars().all()
        assert log.purpose == "regulation_qa"
        assert log.output_json["_usage"]["input_tokens"] == 100

    async def test_fabricated_quote_hides_the_answer(self, api_client, indexed, monkeypatch):
        use(monkeypatch, ScriptedProvider(
            RegulationAnswer(
                answerable=True,
                answer="可以，只要經機關同意。",
                citations=[Citation(ref="政府採購法 第 65 條", quote="經機關同意者得轉包他人")],
            )
        ))

        body = await ask(api_client)

        assert body["status"] == "unverified"
        assert body["answer"] == ""
        assert body["citations"][0]["verified"] is False

    async def test_insufficient_is_passed_through(self, api_client, indexed, monkeypatch):
        use(monkeypatch, ScriptedProvider(
            RegulationAnswer(answerable=False, answer="提供的條文沒有規定加班時數。", citations=[])
        ))

        body = await ask(api_client, "工人每天加班幾小時算違法")

        assert body["status"] == "insufficient"
        assert "沒有規定" in body["answer"]

    async def test_without_ai_it_says_unavailable(self, api_client, indexed, monkeypatch):
        use(monkeypatch, NullProvider())

        body = await ask(api_client)

        assert body["status"] == "unavailable"
        assert body["retrieved"]

    async def test_demo_provider_flow(self, api_client, indexed, monkeypatch):
        use(monkeypatch, DemoProvider())

        body = await ask(api_client)

        assert body["status"] == "answered"
        assert body["citations"][0]["verified"] is True
        assert "非 AI" in body["answer"]

    async def test_question_is_validated(self, api_client):
        response = await api_client.post("/api/search/answer", json={"question": "x"})
        assert response.status_code == 400


async def test_spec_chapters_do_not_crowd_out_articles(api_client, indexed, monkeypatch):
    """前幾名都是規範章節時，仍要送滿條文給模型（曾經因先取前幾名再過濾而一條都沒送）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "QA_TOP_K", 1)
    provider = ScriptedProvider(RegulationAnswer(answerable=False, answer="不足", citations=[]))
    use(monkeypatch, provider)

    await ask(api_client, "結構用混凝土 03310")

    assert len(provider.passages) == 1
    assert not provider.passages[0].ref.startswith("PCCES")
