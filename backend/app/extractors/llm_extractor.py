"""LLM fallback 抽取：規則與字典都抽不到東西時，才把段落交給 LLM。

這一層是「加分項」，不是必要條件。ENABLE_LLM_FALLBACK=false 時整層會靜默略過。
"""

import logging

from app.ai.base import LLMCallRecord, LLMProvider
from app.core.enums import ExtractionMethod, RegulationType
from app.core.logging import log_context
from app.extractors.base import Candidate

logger = logging.getLogger(__name__)

# 太短的段落丟給 LLM 只是浪費錢，也容易產生幻覺
MIN_TEXT_LENGTH = 12


class LLMExtractor:
    method = ExtractionMethod.LLM_FALLBACK

    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def extract(self, text: str) -> tuple[list[Candidate], LLMCallRecord | None]:
        """回傳 (候選清單, 呼叫紀錄)。呼叫紀錄要由上層寫入 ai_invocation_log。"""
        if len(text.strip()) < MIN_TEXT_LENGTH:
            return [], None

        result = await self._provider.extract_regulations(text)
        if not result.ok:
            return [], result.record

        candidates: list[Candidate] = []
        for item in result.value.items:
            # LLM 有可能回傳文件裡根本沒有的字串（幻覺），這裡直接擋掉
            position = text.find(item.raw_text)
            if position < 0:
                logger.info("LLM 抽取結果不在原文中，已忽略", extra=log_context(raw_text=item.raw_text))
                continue
            candidates.append(
                Candidate(
                    raw_text=item.raw_text,
                    regulation_type=_safe_type(item.regulation_type),
                    method=self.method,
                    confidence=item.confidence,
                    article=item.article,
                    standard_number=item.standard_number,
                    start=position,
                    end=position + len(item.raw_text),
                    notes=["由 LLM fallback 抽取，建議人工覆核"],
                )
            )
        return candidates, result.record


def _safe_type(value: str) -> RegulationType:
    try:
        return RegulationType(value)
    except ValueError:
        return RegulationType.OTHER
