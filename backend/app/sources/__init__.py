"""已註冊的法規資料來源。

REGULATION_SOURCES 的順序就是優先順序：**排在前面的來源優先**。
同一個法規被多個來源查到時，以最前面那個來源的資料為準。

要再接其他來源（CNS、企業內部規範…）：
1. 新增 sources/xxx_source.py，實作 RegulationSource
2. 在下面的 _REGISTRY 加一行
3. 在 .env 把 REGULATION_SOURCES 加上該名稱
其他程式碼完全不用改。
"""

import logging
from collections.abc import Callable

from app.core.config import settings
from app.core.enums import SourceAvailability
from app.sources.base import (
    RegulationDetail,
    RegulationSearchResult,
    RegulationSource,
    RegulationVersionInfo,
    SourceReadiness,
    SourcesReadiness,
)
from app.sources.mock_source import MockRegulationSource
from app.sources.pcces_source import PccesSource
from app.sources.taiwan_law_source import TaiwanLawSource

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Callable[[], RegulationSource]] = {
    "taiwan_law": TaiwanLawSource,   # 法務部全國法規資料庫（法律 + 法規命令）
    "pcces": PccesSource,            # 工程會公共工程施工綱要規範（315 章）
    "mock": MockRegulationSource,    # 離線 Demo 用的假資料
}

_cached: list[RegulationSource] | None = None


def get_sources() -> list[RegulationSource]:
    """依 settings.REGULATION_SOURCES 的順序回傳已啟用的來源。"""
    global _cached
    if _cached is not None:
        return _cached

    sources: list[RegulationSource] = []
    for name in settings.regulation_sources:
        factory = _REGISTRY.get(name)
        if factory is None:
            logger.warning("未知的法規來源 %s，已略過", name)
            continue
        sources.append(factory())

    if not sources:
        logger.warning("沒有啟用任何法規來源，所有引用都會是 UNKNOWN")
    _cached = sources
    return _cached


def source_priority(source_name: str) -> int:
    """來源的優先序，數字越小越優先。未啟用的來源排在最後。

    用途：同一部法規被多個來源查到時，不讓低優先的來源覆蓋高優先來源已寫入的資料。
    只比較「同一次查詢」不夠——A 引用讓官方寫入某部法規後，B 引用的模糊查詢
    可能讓假資料來源回傳同一部法規並蓋掉它。
    """
    names = settings.regulation_sources
    return names.index(source_name) if source_name in names else len(names)


def readiness_report(sources: list[RegulationSource] | None = None) -> SourcesReadiness:
    """彙整已啟用來源的就緒狀態，給 GET /api/sources 用。

    分級的判準是「使用者會看到什麼」：
      - 全部就緒            -> OK
      - 有就緒也有沒就緒的  -> DEGRADED，查得到東西但涵蓋範圍比預期小
      - 一個都沒就緒        -> UNAVAILABLE，之後每一筆引用都會是 UNKNOWN

    「一個來源都沒啟用」也算 UNAVAILABLE：結果一樣是滿頁 UNKNOWN，
    不能因為沒有失敗的來源就報成 OK。
    """
    # 注意 sources=[] 是有意義的輸入（沒啟用任何來源），不能用 falsy 判斷
    active = get_sources() if sources is None else sources
    readiness = [source.readiness() for source in active]
    ready_count = sum(1 for item in readiness if item.ready)

    if ready_count == 0:
        status = SourceAvailability.UNAVAILABLE
    elif ready_count < len(readiness):
        status = SourceAvailability.DEGRADED
    else:
        status = SourceAvailability.OK
    return SourcesReadiness(status=status, sources=readiness)


def reset_sources() -> None:
    """測試用：清掉快取。"""
    global _cached
    _cached = None


__all__ = [
    "RegulationDetail",
    "RegulationSearchResult",
    "RegulationSource",
    "RegulationVersionInfo",
    "SourceReadiness",
    "SourcesReadiness",
    "get_sources",
    "readiness_report",
    "source_priority",
    "reset_sources",
]
