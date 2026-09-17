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
    SimilarityJudgement,
)
from app.core.config import settings
from app.core.enums import AIPurpose
from app.core.logging import log_context

logger = logging.getLogger(__name__)


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic model -> Anthropic structured output 需要的 JSON Schema。"""
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    return schema


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

    # --- 共用的呼叫流程 ---

    async def _call(
        self,
        purpose: AIPurpose,
        prompt_version: str,
        system: str,
        user: str,
        output_model: type[BaseModel],
    ) -> LLMResult[Any]:
        record = LLMCallRecord(
            purpose=purpose,
            model=self._model,
            prompt_version=prompt_version,
            input_text=user,
        )
        started = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=settings.LLM_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "format": {"type": "json_schema", "schema": _json_schema(output_model)}
                },
            )
        except Exception as exc:  # API 錯誤 / 逾時 / 網路問題
            record.latency_ms = int((time.perf_counter() - started) * 1000)
            record.error = f"{type(exc).__name__}: {exc}"
            logger.warning("LLM 呼叫失敗", extra=log_context(purpose=purpose, error=record.error))
            return LLMResult(value=None, record=record)

        record.latency_ms = int((time.perf_counter() - started) * 1000)

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
