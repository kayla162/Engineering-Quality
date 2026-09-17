"""全國法規資料庫（法務部）資料來源。

資料不是即時打 API 拿的，而是由 scripts/sync_taiwan_law.py 先同步成本地索引
（原因見該腳本的說明：官方只提供整包 ZIP 下載，沒有單筆查詢 endpoint）。
這個 adapter 只負責「從索引查詢 + 轉成統一格式」。

涵蓋範圍（實際查證過，2026-09）：
    ✓ 法律 約 1,346 筆、法規命令（辦法／細則／規則／標準）約 10,447 筆
    ✗ 行政規則、作業要點（例如「公共工程施工品質管理作業要點」）
    ✗ 工程規範（例如「結構混凝土施工規範」）
    ✗ CNS / ISO / ASTM / JIS 標準
    不在範圍內的引用仍然會是 NOT_FOUND，需要其他來源或人工查證。
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

from rapidfuzz import fuzz, process

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

logger = logging.getLogger(__name__)

#: 低於這個相關度就不回傳，避免把整個法規庫都當成候選
MIN_RELEVANCE = 0.60
MAX_RESULTS = 5

#: 官方法規位階 -> 本系統的法規類型
_LEVEL_TYPES: dict[str, RegulationType] = {
    "憲法": RegulationType.LAW,
    "法律": RegulationType.LAW,
    "命令": RegulationType.REGULATION,
}


def _parse_date(value: str) -> date | None:
    """官方日期是 YYYYMMDD 字串，沒有值時是空字串。"""
    value = (value or "").strip()
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def authority_from_category(category: str) -> str | None:
    """從官方的「法規類別」推導主管機關。

    LawCategory 是階層路徑，第 2 段就是主管機關，例如：
        行政＞行政院公共工程委員會＞通用目  -> 行政院公共工程委員會
        行政＞勞動部＞職業安全衛生目        -> 勞動部
        廢止法規＞內政部                   -> 內政部
        憲法 / 立法（只有一段）             -> None（無法判斷，不猜）

    官方資料集沒有獨立的「發布機關」欄位，所以只能這樣推導；
    推不出來就回 None，不要把整條類別路徑當成機關名稱顯示給使用者。
    """
    segments = [s.strip() for s in (category or "").split("＞") if s.strip()]
    return segments[1] if len(segments) >= 2 else None


def decide_status(entry: dict, today: date | None = None) -> tuple[RegulationStatus, str | None]:
    """把官方欄位轉成本系統的法規狀態，並回傳給人看的說明。

    對應規則（欄位定義來自 ZIP 內的 schema.csv）：
        LawAbandonNote == "廢"    -> REPEALED
        LawEffectiveDate 在未來    -> AMENDED（修正條文尚未生效，引用時要確認適用版本）
        其餘                       -> ACTIVE

    刻意不把「曾經修正過」一律當成 AMENDED——幾乎每部法規都修正過，
    那樣標示等於沒有標示。只有「現在有一個版本落差需要人去確認」才標 AMENDED。
    """
    today = today or date.today()

    if entry.get("abandoned"):
        return RegulationStatus.REPEALED, "官方標示為已廢止"

    effective = _parse_date(entry.get("effective_date", ""))
    if effective and effective > today:
        note = f"修正條文自 {effective.isoformat()} 起生效，目前引用需確認適用版本"
        if entry.get("effective_note"):
            note = f"{note}；官方生效內容：{entry['effective_note'][:120]}"
        return RegulationStatus.AMENDED, note

    return RegulationStatus.ACTIVE, None


#: 索引缺檔或壞檔時唯一的補救動作。錯誤訊息只描述問題，動作放這裡，
#: 前端與報告才能分開排版，不會把同一句話印兩次。
SYNC_COMMAND = "python scripts/sync_taiwan_law.py"


class TaiwanLawSource(RegulationSource):
    source_name = "taiwan_law"

    def __init__(self, index_path: Path | None = None):
        self._path = index_path or settings.TAIWAN_LAW_INDEX_PATH
        self._entries: list[dict] | None = None
        self._names: list[str] = []
        self._by_id: dict[str, dict] = {}

    def _load(self) -> list[dict]:
        if self._entries is None:
            if not self._path.exists():
                raise SourceQueryError(
                    self.source_name,
                    f"找不到全國法規資料庫索引 {self._path}（尚未同步官方資料）",
                    remedy=SYNC_COMMAND,
                )
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SourceQueryError(
                    self.source_name,
                    f"法規索引 {self._path} 格式錯誤：{exc}",
                    remedy=SYNC_COMMAND,
                ) from exc

            self._entries = payload.get("regulations", [])
            self._names = [entry["name"] for entry in self._entries]
            self._by_id = {entry["external_id"]: entry for entry in self._entries}
            logger.info(
                "載入全國法規資料庫索引：%d 筆（%s）",
                len(self._entries),
                payload.get("update_dates", {}),
            )
        return self._entries

    def readiness(self) -> SourceReadiness:
        """索引檔要存在且讀得起來，這個來源才查得到東西。"""
        return self._readiness_from(self._load)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        entries = self._load()

        # rapidfuzz 的 process.extract 是 C++ 實作，一萬多筆也在毫秒等級
        matches = process.extract(
            query,
            self._names,
            scorer=fuzz.WRatio,
            limit=MAX_RESULTS,
            score_cutoff=MIN_RELEVANCE * 100,
        )
        return [
            self._to_result(entries[index], relevance=score / 100.0)
            for _, score, index in matches
        ]

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        self._load()
        entry = self._by_id.get(regulation_id.upper())
        if entry is None:
            return None
        base = self._to_result(entry, relevance=1.0)
        return RegulationDetail(**base.model_dump(), versions=self._versions(entry))

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        detail = await self.get_detail(regulation_id)
        return detail.versions if detail else []

    # --- 內部 ---

    def _versions(self, entry: dict) -> list[RegulationVersionInfo]:
        """索引只保留最近一次異動；完整沿革在原始 ZIP 的 LawHistories，Phase 2 再處理。"""
        modified = _parse_date(entry.get("modified_date", ""))
        if modified is None:
            return []
        return [
            RegulationVersionInfo(
                version=f"{modified.isoformat()} 異動",
                effective_date=_parse_date(entry.get("effective_date", "")),
                amended_date=modified,
                source_url=entry.get("url") or None,
            )
        ]

    def _to_result(self, entry: dict, relevance: float) -> RegulationSearchResult:
        status, note = decide_status(entry)
        return RegulationSearchResult(
            external_id=entry["external_id"],
            name=entry["name"],
            type=_LEVEL_TYPES.get(entry.get("level", ""), RegulationType.REGULATION),
            status=status,
            source=self.source_name,
            authority=authority_from_category(entry.get("category", "")),
            effective_date=_parse_date(entry.get("effective_date", "")),
            last_amended_date=_parse_date(entry.get("modified_date", "")),
            official_url=entry.get("url") or None,
            standard_number=None,  # 全國法規資料庫沒有標準編號
            note=note,
            relevance=round(relevance, 4),
            # 官方來源，且索引帶有 UpdateDate，可以確認是否為現行版本
            can_confirm_currency=True,
        )
