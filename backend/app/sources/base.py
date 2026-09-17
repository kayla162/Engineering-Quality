"""RegulationSource 介面與統一回傳格式。

呼叫端（MatchingService）完全不知道資料是從哪個來源來的，也不需要知道。
新增一個真實資料來源時，只要實作這個介面並在 sources/__init__.py 註冊。

每個 adapter 要自己處理該來源特有的錯誤（timeout / 4xx / 5xx / 壞掉的 JSON），
對外一律轉成 SourceQueryError。單一來源失敗不會讓整份文件的分析失敗。
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date

from pydantic import BaseModel, Field

from app.core.enums import SourceAvailability
from app.core.errors import SourceQueryError


class RegulationVersionInfo(BaseModel):
    version: str
    effective_date: date | None = None
    amended_date: date | None = None
    content_hash: str | None = None
    source_url: str | None = None


class RegulationSearchResult(BaseModel):
    """所有來源的搜尋結果都會被轉成這個格式。"""

    external_id: str = Field(description="該來源自己的識別碼")
    name: str
    type: str
    status: str
    source: str = Field(description="adapter 名稱，例如 mock")
    authority: str | None = None
    effective_date: date | None = None
    last_amended_date: date | None = None
    official_url: str | None = None
    standard_number: str | None = None
    note: str | None = None
    #: 來源自己給的相關度（0~1），僅供參考，最終比對分數由 MatchingEngine 決定
    relevance: float = 1.0
    #: 這個來源有沒有能力確認「目前是否為最新有效版本」。
    #: 付費標準（CNS/ISO/ASTM/JIS）通常查得到存在、查不到最新版號，因此為 false，
    #: 比對結果會被降級成 POSSIBLE_MATCH，明確要求人工查證。
    can_confirm_currency: bool = True


class RegulationDetail(RegulationSearchResult):
    versions: list[RegulationVersionInfo] = Field(default_factory=list)


class SourceReadiness(BaseModel):
    """這個來源現在能不能查，以及不能查的話該怎麼辦。

    存在的理由：官方索引是由同步腳本產生的本地檔案，「有沒有跑過同步」是部署方的
    責任。沒跑就會每一筆引用都變成 UNKNOWN，使用者卻不知道原因。這個型別讓系統
    在分析之前就能把原因與下一步講清楚。
    """

    source: str
    ready: bool
    #: 未就緒的原因（給人看的完整句子，含檔案路徑）。就緒時為 None。
    detail: str | None = None
    #: 讓它就緒要做什麼，例如要跑的命令。沒有可執行的動作時為 None。
    remedy: str | None = None


class SourcesReadiness(BaseModel):
    """所有已啟用來源的就緒總覽。"""

    status: SourceAvailability
    sources: list[SourceReadiness]


class RegulationSource(ABC):
    source_name: str = "base"

    def readiness(self) -> SourceReadiness:
        """預設：沒有前置條件，隨時可查。

        需要本地檔案（索引、種子資料）的來源要覆寫，
        通常直接回傳 `self._readiness_from(self._load)` 即可。
        """
        return SourceReadiness(source=self.source_name, ready=True)

    def _readiness_from(self, load: Callable[[], object]) -> SourceReadiness:
        """把「載入前置資料」的失敗轉成未就緒狀態。

        刻意不讓例外往外跑：就緒檢查是給前端輪詢用的，
        它自己壞掉變成 500 反而讓使用者更看不出發生什麼事。
        """
        try:
            load()
        except SourceQueryError as exc:
            return SourceReadiness(
                source=self.source_name,
                ready=False,
                detail=exc.message,
                remedy=exc.remedy,
            )
        return SourceReadiness(source=self.source_name, ready=True)

    @abstractmethod
    async def search(self, query: str) -> list[RegulationSearchResult]: ...

    @abstractmethod
    async def get_detail(self, regulation_id: str) -> RegulationDetail | None: ...

    @abstractmethod
    async def get_version_history(self, regulation_id: str) -> list[RegulationVersionInfo]: ...
