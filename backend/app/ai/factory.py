"""依設定挑選 LLMProvider。新增供應商時，只要在 _PROVIDERS 加一行。"""

import logging
from collections.abc import Callable

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import LLMProvider
from app.ai.null_provider import NullProvider
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, Callable[[], LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "null": NullProvider,
}

_cached: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """回傳目前設定的 provider。以下任一情況都會退回 NullProvider（系統仍可完整運作）：

    - ENABLE_LLM_FALLBACK=false
    - 設定了未知的 provider 名稱
    - Anthropic 沒有設定 API key
    """
    global _cached
    if _cached is not None:
        return _cached

    if not settings.ENABLE_LLM_FALLBACK:
        logger.info("ENABLE_LLM_FALLBACK=false，AI 功能已關閉")
        _cached = NullProvider()
        return _cached

    name = settings.LLM_PROVIDER.lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        logger.warning("未知的 LLM_PROVIDER=%s，改用 NullProvider", name)
        _cached = NullProvider()
        return _cached

    if name == "anthropic" and not settings.ANTHROPIC_API_KEY:
        logger.warning("未設定 ANTHROPIC_API_KEY，AI 功能停用（系統仍可完整運作）")
        _cached = NullProvider()
        return _cached

    _cached = factory()
    logger.info("LLM provider = %s (%s)", _cached.name, _cached.model)
    return _cached


def reset_llm_provider() -> None:
    """測試用：清掉快取，讓下次呼叫重新依設定建立。"""
    global _cached
    _cached = None
