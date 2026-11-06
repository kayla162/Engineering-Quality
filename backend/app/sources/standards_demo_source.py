"""DemoStandardsSource：示範用的標準目錄（CNS／ISO／ASTM…），全部是假資料。

真實的 CNS 等標準多是付費標準，公開來源只查得到「存不存在」，所以 mock 來源一律回報
can_confirm_currency=False，比對結果固定是「疑似對應」。這個來源示範的是**有一份標準
目錄可查時**系統會怎麼做：

- 只比標準編號（「CNS 3090」），不比名稱——名稱相近的別號標準是不同的東西。
- 目錄有最新版次與廢止資訊，所以能確認是否現行（can_confirm_currency=True）。
- 最新版的年份放在 last_amended_date（該年 1 月 1 日）。文件引用了較舊的年份時，
  MatchingService 會把**那一筆引用**判為已修正；法規主檔本身照目錄維持現行。

資料檔 data/demo_standards.json 是虛構的，不可作為查核依據。接上真實標準目錄時，
換掉這個 adapter 即可，比對邏輯不用動。
"""

import json
import re
from datetime import date
from pathlib import Path

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

_NUMBER = re.compile(
    r"(?P<org>CNS|ISO|IEC|ASTM|JIS|EN|OHSAS)[\s\-]*(?P<core>[A-Z]{0,4}\s?\d{1,6}(?:/[A-Z0-9]+)?)",
    re.IGNORECASE,
)


def standard_key(text: str) -> str | None:
    """「CNS3090:2015」「cns 3090」都變成「CNS 3090」；不是標準編號回傳 None。"""
    match = _NUMBER.search(text or "")
    if match is None:
        return None
    core = re.sub(r"\s+", "", match.group("core").upper()).split("/")[0]
    return f"{match.group('org').upper()} {core}"


class DemoStandardsSource(RegulationSource):
    source_name = "standards_demo"
    confirms_standard_currency = True

    def __init__(self, data_path: Path | None = None):
        self._path = data_path or (settings.DATA_DIR / "demo_standards.json")
        self._records: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._records is None:
            if not self._path.exists():
                raise SourceQueryError(self.source_name, f"找不到示範標準目錄：{self._path}")
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            self._records = {
                standard_key(record["number"]): record for record in payload.get("standards", [])
            }
        return self._records

    def readiness(self) -> SourceReadiness:
        return self._readiness_from(self._load)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        key = standard_key(query)
        record = self._load().get(key) if key else None
        return [self._to_result(record)] if record else []

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        record = self._load().get(standard_key(regulation_id) or "")
        if record is None:
            return None
        return RegulationDetail(**self._to_result(record).model_dump(), versions=self._versions(record))

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        record = self._load().get(standard_key(regulation_id) or "")
        return self._versions(record) if record else []

    def _to_result(self, record: dict) -> RegulationSearchResult:
        note = f"最新版 {record['latest_edition']} 年（{record.get('provenance', '來源未註明')}）"
        if record.get("synced_at"):
            note += f"；{record['synced_at']} 自動同步官方頁面"
        if record.get("replaced_by"):
            note += f"；已由 {record['replaced_by']} 取代"
        return RegulationSearchResult(
            external_id=record["number"],
            name=f"{record['number']} {record['title']}",
            type=RegulationType.STANDARD,
            status=RegulationStatus(record["status"]),
            source=self.source_name,
            authority=record.get("authority"),
            last_amended_date=date(int(record["latest_edition"]), 1, 1),
            standard_number=record["number"],
            note=note,
            relevance=1.0,
            can_confirm_currency=True,
        )

    @staticmethod
    def _versions(record: dict) -> list[RegulationVersionInfo]:
        return [
            RegulationVersionInfo(
                version=f"{record['latest_edition']} 年版",
                amended_date=date(int(record["latest_edition"]), 1, 1),
            )
        ]
