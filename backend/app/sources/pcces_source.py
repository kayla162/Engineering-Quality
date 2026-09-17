"""公共工程施工綱要規範（行政院公共工程委員會）資料來源。

資料由 scripts/sync_pcces.py 從工程會技術雲同步成本地目錄（315 章），
這個 adapter 只負責「從目錄查詢 + 轉成統一格式」。

為什麼這個來源不做模糊比對（重要）：
    目錄裡存的是「工項／材料名」，不是文件名——「卜特蘭水泥」「鋼筋」「品質管理」。
    用專案自己的比對器實測，這些名稱對上帶編號的標準引用會拿到 0.90 以上並被自動採信：

        CNS 61 卜特蘭水泥        -> 03052 卜特蘭水泥   0.90
        CNS 560 鋼筋混凝土用鋼筋 -> 03210 鋼筋         0.90
        ISO 9001 品質管理系統    -> 01450 品質管理     0.90
        職業安全衛生法           -> 01574 職業安全衛生 0.92

    把一份 CNS 標準判成一個施工綱要規範章節，是「有信心的錯」，比誠實回答查不到
    傷害大得多。所以 search() 只在「引用真的指向施工綱要規範」時才回答：
    有章碼，或字面上就寫了綱要規範。其餘一律回空。

    比對引擎那邊還有第二道守門（引用帶標準編號時只採用標準型別的候選），
    兩層是刻意的：這裡的閘門是字串判斷，會有沒想到的寫法。

涵蓋範圍：
    ✓ 公共工程共通性工項施工綱要規範 315 章（含已刪除章節）
    ✗ 各機關自訂的施工規範、設計規範（例如「混凝土結構施工規範」是內政部的）
    ✗ 作業要點等行政規則
"""

import json
import logging
import re
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

logger = logging.getLogger(__name__)

#: 目錄缺檔或壞檔時唯一的補救動作
SYNC_COMMAND = "python scripts/sync_pcces.py"

#: 規範本體（不是任何一章）的識別碼與名稱
SPEC_ID = "PCCES"
SPEC_NAME = "公共工程施工綱要規範"

#: 官方目錄頁。工程會沒有提供逐章的固定網址，所以每一章都指向這裡。
CATALOGUE_URL = "https://pcic.pcc.gov.tw/pwc-web/service/tec0304"

#: 章碼是 5 位數字（CSI 分類），前後不能再接數字，避免把長編號切一段出來當章碼
_CHAPTER_CODE = re.compile(r"(?<!\d)(\d{5})(?!\d)")

#: 出現這些標準前綴就代表引用的是標準，不是施工綱要規範，直接退出
_STANDARD_TOKEN = re.compile(r"\b(?:CNS|ISO|ASTM|JIS)\b", re.IGNORECASE)

#: 字面上寫了這個，才算是在引用施工綱要規範
_SPEC_MARKER = "綱要規範"


class PccesSource(RegulationSource):
    source_name = "pcces"

    def __init__(self, index_path: Path | None = None):
        self._path = index_path or settings.PCCES_INDEX_PATH
        self._chapters: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._chapters is None:
            if not self._path.exists():
                raise SourceQueryError(
                    self.source_name,
                    f"找不到施工綱要規範目錄 {self._path}（尚未同步工程會資料）",
                    remedy=SYNC_COMMAND,
                )
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SourceQueryError(
                    self.source_name,
                    f"施工綱要規範目錄 {self._path} 格式錯誤：{exc}",
                    remedy=SYNC_COMMAND,
                ) from exc

            self._chapters = {c["code"]: c for c in payload.get("chapters", [])}
            logger.info("載入公共工程施工綱要規範目錄：%d 章", len(self._chapters))
        return self._chapters

    def readiness(self) -> SourceReadiness:
        return self._readiness_from(self._load)

    async def search(self, query: str) -> list[RegulationSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        chapters = self._load()

        # 1. 引用的是標準，不是綱要規範。連比都不要比。
        if _STANDARD_TOKEN.search(query):
            return []

        # 2. 有章碼就以章碼為準（比規範本體精確）。
        #    章碼不在目錄裡代表查無此章，不退而給規範本體——那等於假裝查到了。
        code = _CHAPTER_CODE.search(query)
        if code:
            chapter = chapters.get(code.group(1))
            return [self._to_result(chapter)] if chapter else []

        # 3. 沒有章碼，但字面上寫了綱要規範 -> 規範本體
        if _SPEC_MARKER in query:
            return [self._spec_result(len(chapters))]

        # 4. 其餘一律不回答（章名長得像材料名，模糊比對只會製造錯誤對應）
        return []

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        chapters = self._load()
        regulation_id = regulation_id.upper()

        if regulation_id == SPEC_ID:
            base = self._spec_result(len(chapters))
            return RegulationDetail(**base.model_dump(), versions=[])

        code = regulation_id.removeprefix(f"{SPEC_ID}-")
        chapter = chapters.get(code)
        if chapter is None:
            return None
        base = self._to_result(chapter)
        return RegulationDetail(**base.model_dump(), versions=self._versions(chapter))

    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]:
        detail = await self.get_detail(regulation_id)
        return detail.versions if detail else []

    # --- 內部 ---

    def _versions(self, chapter: dict) -> list[RegulationVersionInfo]:
        edition = str(chapter.get("edition") or "").strip()
        if not _is_edition_number(edition):
            return []
        return [RegulationVersionInfo(version=f"第 {edition} 版", source_url=CATALOGUE_URL)]

    def _spec_result(self, chapter_count: int) -> RegulationSearchResult:
        """規範本體。引用「公共工程施工綱要規範」時對到的就是這一筆，不是某一章。"""
        return RegulationSearchResult(
            external_id=SPEC_ID,
            name=SPEC_NAME,
            type=RegulationType.ENGINEERING_SPEC,
            status=RegulationStatus.ACTIVE,
            source=self.source_name,
            authority="行政院公共工程委員會",
            official_url=CATALOGUE_URL,
            note=f"共通性工項施工綱要規範，現行共 {chapter_count} 章；引用特定章節請註明章碼",
            relevance=1.0,
            can_confirm_currency=True,
        )

    def _to_result(self, chapter: dict) -> RegulationSearchResult:
        code = chapter["code"]
        edition = str(chapter.get("edition") or "").strip()
        repealed = not _is_edition_number(edition)

        return RegulationSearchResult(
            external_id=f"{SPEC_ID}-{code}",
            # 名稱照實際被引用的樣子存。只存章名的話，「第03310章」比「結構用混凝土」
            # 相似度太低，比對引擎會把這筆丟掉。
            name=f"{SPEC_NAME}第{code}章 {chapter['name']}",
            type=RegulationType.ENGINEERING_SPEC,
            status=RegulationStatus.REPEALED if repealed else RegulationStatus.ACTIVE,
            source=self.source_name,
            authority="行政院公共工程委員會",
            official_url=CATALOGUE_URL,
            # 章碼會被存成別名，讓之後用純章碼也查得到
            standard_number=code,
            note=f"官方標示：{edition}" if repealed else f"版次 {edition}",
            relevance=1.0,
            # 版次直接來自官方目錄，不像付費標準那樣只查得到「存在」
            can_confirm_currency=True,
        )


def _is_edition_number(edition: str) -> bool:
    """版次欄正常是 "8.0" 這種數字；不是數字時官方是在講狀態（例如「本章已刪除」）。"""
    return bool(edition) and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", edition))
