"""AdminRulesSource：行政規則與地方法規目錄（示範）。

全國法規資料庫（taiwan_law）只收「法律」與「法規命令」。工程文件大量引用的「要點」
「綱要」（工程會、內政部的行政規則）與「自治條例」「市府要點」（地方法規）都不在裡面，
於是「加強公共工程職業安全衛生管理作業要點」這種真實存在的規則會被判成查無此法規。

資料檔 data/admin_rules.json 的名稱是真的（取自秀山分隊的契約書、整體品質計畫與隨附
法規 PDF），但多數規則的狀態是假設的現行、日期未查證——每筆都在 provenance 寫明出處，
並帶進查詢結果的 note。接上真實的行政規則／地方法規資料庫時，換掉這個 adapter 即可。

比對刻意保守：名稱或別名（去掉空白後）完全相等優先；模糊比對只收很像的長名稱，
用來吃掉 PDF 斷行留下的空白與被切掉的一兩個字（「北市政府處理人行道…」）。
「作業要點」「管理要點」這種泛稱太短、也和任何一筆都不夠像，查不到東西。
"""

import json
import re
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from app.core.config import settings
from app.core.enums import RegulationStatus, RegulationType
from app.core.errors import SourceQueryError
from app.sources.base import (
    RegulationDetail,
    RegulationSearchResult,
    RegulationSource,
    RegulationVersionInfo,
    SourceReadiness,
)

#: 模糊比對的門檻與最短長度。比 mock 的 0.55 嚴格得多：這裡回傳的結果會被當成現行。
MIN_RATIO = 0.92
MIN_FUZZY_LENGTH = 8
_SPACES = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _SPACES.sub("", text or "")


class AdminRulesSource(RegulationSource):
    source_name = "admin_rules"

    def __init__(self, data_path: Path | None = None):
        self._path = data_path or (settings.DATA_DIR / "admin_rules.json")
        self._records: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._records is None:
            if not self._path.exists():
                raise SourceQueryError(self.source_name, f"找不到行政規則目錄：{self._path}")
            try:
                self._records = json.loads(self._path.read_text(encoding="utf-8"))["rules"]
            except (ValueError, KeyError) as exc:
                raise SourceQueryError(self.source_name, f"行政規則目錄格式錯誤：{exc}") from exc
        return self._records

    def readiness(self) -> SourceReadiness:
        return self._readiness_from(self._load)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        wanted = _squash(query)
        if not wanted:
            return []
        records = self._load()
        for record in records:
            if wanted in {_squash(term) for term in self._terms(record)}:
                return [self._to_result(record, 1.0)]
        if len(wanted) < MIN_FUZZY_LENGTH:
            return []
        best, best_score = None, 0.0
        for record in records:
            score = max(fuzz.ratio(wanted, _squash(term)) / 100.0 for term in self._terms(record))
            if score > best_score:
                best, best_score = record, score
        return [self._to_result(best, best_score)] if best and best_score >= MIN_RATIO else []

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        record = next((r for r in self._load() if r["id"] == regulation_id), None)
        if record is None:
            return None
        return RegulationDetail(**self._to_result(record, 1.0).model_dump(), versions=self._versions(record))

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        record = next((r for r in self._load() if r["id"] == regulation_id), None)
        return self._versions(record) if record else []

    @staticmethod
    def _terms(record: dict) -> list[str]:
        return [record["name"], *record.get("aliases", [])]

    def _to_result(self, record: dict, relevance: float) -> RegulationSearchResult:
        return RegulationSearchResult(
            external_id=record["id"],
            name=record["name"],
            type=RegulationType(record["type"]),
            status=RegulationStatus(record["status"]),
            source=self.source_name,
            authority=record.get("authority"),
            effective_date=_date(record.get("issued_date")),
            last_amended_date=_date(record.get("last_amended_date")),
            note=f"{record['level']}（示範目錄）：{record['provenance']}",
            relevance=round(relevance, 4),
        )

    @staticmethod
    def _versions(record: dict) -> list[RegulationVersionInfo]:
        amended = _date(record.get("last_amended_date"))
        if amended is None:
            return []
        return [RegulationVersionInfo(version=f"{amended.isoformat()} 修正", amended_date=amended)]


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
