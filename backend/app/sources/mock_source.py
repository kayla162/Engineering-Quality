"""MockRegulationSource：從 data/mock_regulations.json 讀假資料。

用途有兩個：
1. 讓開發 / 測試 / Demo 在完全沒有網路與真實官方 API 的情況下跑通全流程。
2. 作為未來真實 adapter 的行為規格範本——真實來源接上後，除了 source 欄位與
   查詢結果之外，整個流程與 UI 都不需要改動。
"""

import json
import logging
from pathlib import Path

from rapidfuzz import fuzz

from app.core.config import settings
from app.core.errors import SourceQueryError
from app.sources.base import (
    RegulationDetail,
    RegulationSearchResult,
    RegulationSource,
    RegulationVersionInfo,
    SourceReadiness,
)

logger = logging.getLogger(__name__)

#: 低於這個相關度的結果不回傳，避免把整個資料庫都當成候選
MIN_RELEVANCE = 0.55
MAX_RESULTS = 5


class MockRegulationSource(RegulationSource):
    source_name = "mock"

    def __init__(self, data_path: Path | None = None):
        self._path = data_path or (settings.DATA_DIR / "mock_regulations.json")
        self._records: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._records is None:
            if not self._path.exists():
                raise SourceQueryError(self.source_name, f"找不到假資料檔案：{self._path}")
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SourceQueryError(self.source_name, f"假資料檔案格式錯誤：{exc}") from exc
            self._records = payload.get("regulations", [])
        return self._records

    def readiness(self) -> SourceReadiness:
        """假資料檔隨專案一起提供，缺了就是安裝不完整，沒有腳本可以補（remedy 留空）。"""
        return self._readiness_from(self._load)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        query = (query or "").strip()
        if not query:
            return []

        scored: list[tuple[float, dict]] = []
        for record in self._load():
            score = self._relevance(query, record)
            if score >= MIN_RELEVANCE:
                scored.append((score, record))

        scored.sort(key=lambda pair: -pair[0])
        return [
            self._to_result(record, relevance=score) for score, record in scored[:MAX_RESULTS]
        ]

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        for record in self._load():
            if record["external_id"] == regulation_id:
                base = self._to_result(record, relevance=1.0)
                return RegulationDetail(
                    **base.model_dump(),
                    versions=[
                        RegulationVersionInfo(**version) for version in record.get("versions", [])
                    ],
                )
        return None

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        detail = await self.get_detail(regulation_id)
        return detail.versions if detail else []

    # --- 內部 ---

    def _relevance(self, query: str, record: dict) -> float:
        """名稱相似度 + 標準編號完全命中。"""
        name_score = fuzz.token_set_ratio(query, record["name"]) / 100.0
        standard_number = record.get("standard_number")
        if standard_number and standard_number.upper() in query.upper():
            return 1.0
        return name_score

    def _to_result(self, record: dict, relevance: float) -> RegulationSearchResult:
        return RegulationSearchResult(
            external_id=record["external_id"],
            name=record["name"],
            type=record["type"],
            status=record["status"],
            source=self.source_name,
            authority=record.get("authority"),
            effective_date=record.get("effective_date"),
            last_amended_date=record.get("last_amended_date"),
            official_url=record.get("official_url"),
            standard_number=record.get("standard_number"),
            note=record.get("note"),
            relevance=round(relevance, 4),
            can_confirm_currency=record.get("can_confirm_currency", True),
        )
