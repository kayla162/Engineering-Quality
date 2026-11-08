"""Anthropic Claude 實作。

設計重點：
1. 一律要求 structured output（JSON Schema），回來的 JSON 再用 Pydantic 驗證一次；
   驗證失敗就丟棄該次結果並記錄，不重試、也不讓模型自由發揮修正。
2. 任何失敗（API 錯誤、逾時、模型拒絕回答、JSON 壞掉）都只會讓這次呼叫回傳
   value=None，不會讓整份文件的分析失敗。
3. 每次呼叫都產生 LLMCallRecord，由呼叫端寫入 ai_invocation_log。
"""

import json
import logging
import time
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.ai import prompts
from app.ai.base import (
    ExtractionResult,
    LLMCallRecord,
    LLMProvider,
    LLMResult,
    Passage,
    RegulationAnswer,
    SimilarityJudgement,
)
from app.core.config import settings
from app.core.enums import AIPurpose
from app.core.logging import log_context

logger = logging.getLogger(__name__)


#: 支援伺服器端 `fallbacks: "default"` 的模型。其他模型（例如 Haiku）送這個參數會 400，就不送
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic model -> Anthropic structured output 需要的 JSON Schema。

    API 要求**每一層** object（包含 $defs 裡的巢狀模型）都明確寫 additionalProperties: false，
    只設最外層會被 400 擋下。
    """
    schema = model.model_json_schema()
    _close_objects(schema)
    return schema


def _close_objects(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node["additionalProperties"] = False
        for value in node.values():
            _close_objects(value)
    elif isinstance(node, list):
        for item in node:
            _close_objects(item)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._model = model or settings.ANTHROPIC_MODEL
        self._client = AsyncAnthropic(
            api_key=api_key or settings.ANTHROPIC_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

    @property
    def model(self) -> str:
        return self._model

    # --- 公開方法 ---

    async def extract_regulations(self, text: str) -> LLMResult[ExtractionResult]:
        return await self._call(
            purpose=AIPurpose.EXTRACTION,
            prompt_version=prompts.EXTRACTOR_PROMPT_VERSION,
            system=prompts.EXTRACTOR_SYSTEM,
            user=prompts.extraction_user_prompt(text),
            output_model=ExtractionResult,
        )

    async def judge_similarity(
        self, name_a: str, name_b: str, context: str = ""
    ) -> LLMResult[SimilarityJudgement]:
        result = await self._call(
            purpose=AIPurpose.SIMILARITY_JUDGEMENT,
            prompt_version=prompts.MATCHER_PROMPT_VERSION,
            system=prompts.MATCHER_SYSTEM,
            user=prompts.similarity_user_prompt(name_a, name_b, context),
            output_model=SimilarityJudgement,
        )
        if result.value is not None and result.record is not None:
            result.record.confidence = result.value.confidence
        return result

    async def summarize_for_report(self, findings: list[str]) -> LLMResult[str]:
        class _Summary(BaseModel):
            summary: str

        result = await self._call(
            purpose=AIPurpose.REPORT_SUMMARY,
            prompt_version=prompts.REPORT_PROMPT_VERSION,
            system=prompts.REPORT_SYSTEM,
            user=prompts.report_user_prompt(findings),
            output_model=_Summary,
        )
        return LLMResult(
            value=result.value.summary if result.value else None, record=result.record
        )

    async def answer_regulation_question(
        self, question: str, passages: list[Passage]
    ) -> LLMResult[RegulationAnswer]:
        return await self._call(
            purpose=AIPurpose.REGULATION_QA,
            prompt_version=prompts.QA_PROMPT_VERSION,
            system=prompts.QA_SYSTEM,
            user=prompts.qa_user_prompt(question, passages),
            output_model=RegulationAnswer,
            model=settings.QA_MODEL,
            effort=settings.QA_EFFORT,
            # 要讀多條條文、可能思考較久：給足輸出空間與時間
            max_tokens=16000,
            timeout=180.0,
            fallbacks=settings.QA_MODEL in FALLBACK_MODELS,
        )

    # --- 共用的呼叫流程 ---

    async def _call(
        self,
        purpose: AIPurpose,
        prompt_version: str,
        system: str,
        user: str,
        output_model: type[BaseModel],
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        fallbacks: bool = False,
    ) -> LLMResult[Any]:
        model = model or self._model
        record = LLMCallRecord(
            purpose=purpose,
            model=model,
            prompt_version=prompt_version,
            input_text=user,
        )
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": _json_schema(output_model)}
        }
        if effort:
            output_config["effort"] = effort
        request = {
            "model": model,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        client = self._client.with_options(timeout=timeout) if timeout else self._client
        started = time.perf_counter()
        try:
            if fallbacks:
                # 安全分類器誤擋（stop_reason=refusal）時，伺服器端依類別改由其他模型接手，
                # 不用自己維護備援模型清單；實際由哪個模型回答記在 record.model
                response = await client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request
                )
            else:
                response = await client.messages.create(**request)
        except Exception as exc:  # API 錯誤 / 逾時 / 網路問題
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            record.error = f"{type(exc).__name__}: {exc}"
            logger.warning("LLM 呼叫失敗", extra=log_context(purpose=purpose, error=record.error))
            return LLMResult(value=None, record=record)

        record.latency_ms = int((time.perf_counter() - started) * 1000)
        record.model = getattr(response, "model", None) or model
        usage = getattr(response, "usage", None)
        if usage is not None:
            record.usage = {
                key: int(getattr(usage, key, 0) or 0)
                for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            }

        # 模型拒絕回答時 stop_reason 會是 refusal，content 不可信任
        if getattr(response, "stop_reason", None) == "refusal":
            record.error = "模型拒絕回應此請求（stop_reason=refusal）"
            logger.warning("LLM 拒絕回應", extra=log_context(purpose=purpose))
            return LLMResult(value=None, record=record)

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            payload = json.loads(text)
            record.output_json = payload
            return LLMResult(value=output_model.model_validate(payload), record=record)
        except (json.JSONDecodeError, ValidationError) as exc:
            record.error = f"輸出驗證失敗：{exc}"
            record.output_json = {"raw_text": text[:2000]}
            logger.warning("LLM 輸出驗證失敗", extra=log_context(purpose=purpose))
            return LLMResult(value=None, record=record)
