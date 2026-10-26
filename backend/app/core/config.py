"""所有可調整的設定集中在這裡。

規則：程式碼其他地方不要直接讀 os.environ，一律透過 `settings`。
設定值來源：環境變數 > 專案根目錄的 .env > 這裡的預設值。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 專案根目錄（.../engineering-regulation-platform/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 應用程式 ---
    APP_NAME: str = "工程法規符合性檢查平台"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # --- 本機帳號登入 ---
    AUTH_SESSION_COOKIE: str = "eq_session"
    AUTH_SESSION_TTL_HOURS: int = 12
    AUTH_COOKIE_SECURE: bool = True
    AUTH_MAX_LOGIN_ATTEMPTS: int = 10
    AUTH_LOGIN_WINDOW_SECONDS: int = 300

    # --- 資料庫 ---
    # PostgreSQL:  postgresql+asyncpg://user:pass@host:5432/dbname
    # 本機/測試:    sqlite+aiosqlite:///./data/app.db
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/regplatform"
    DB_ECHO: bool = False

    # --- 檔案上傳 ---
    UPLOAD_DIR: Path = PROJECT_ROOT / "storage" / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: str = ".docx,.pdf,.txt,.xls,.xlsx"

    # --- 資料檔（種子資料、字典） ---
    DATA_DIR: Path = PROJECT_ROOT / "data"

    # --- 報告 ---
    # PDF 匯出用的中文字型（.ttf/.ttc）。留空則自動搜尋常見系統字型，見 reports/fonts.py
    PDF_FONT_PATH: str = ""

    # --- OCR（掃描版 PDF） ---
    # 可選取文字不足、但有圖片的頁才會送 OCR，見 parsers/ocr.py
    ENABLE_OCR: bool = True
    # Tesseract 語言代碼，用 + 連接
    OCR_LANGUAGES: str = "chi_tra+eng"
    OCR_DPI: int = 300
    # 語言資料目錄（含 chi_tra.traineddata）。留空則用 TESSDATA_PREFIX 或系統安裝的位置
    TESSDATA_PATH: str = ""

    # --- 比對引擎門檻 ---
    # >= AUTO：直接採用比對到的法規狀態，視為高信心
    # >= POSSIBLE 且 < AUTO：仍採用該法規狀態，但標記為「疑似」，且是 LLM fallback 的觸發區間
    # <  POSSIBLE：判定為 NOT_FOUND
    MATCH_AUTO_THRESHOLD: float = 0.90
    MATCH_POSSIBLE_THRESHOLD: float = 0.70

    # --- AI ---
    # 關掉之後系統仍可完整運作，只是抽取召回率與比對信心下降（見 architecture.md 1.5）
    ENABLE_LLM_FALLBACK: bool = True
    LLM_PROVIDER: str = "anthropic"          # anthropic | null
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5"
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_TOKENS: int = 4096

    # --- 外部法規來源 ---
    # 逗號分隔的 adapter 名稱，順序即查詢順序
    REGULATION_SOURCES: str = "mock"
    # 已查詢過的法規在幾天內視為新鮮，不重複打外部來源
    REGULATION_CACHE_TTL_DAYS: int = 7
    # 全國法規資料庫的本地索引（由 scripts/sync_taiwan_law.py 產生）
    TAIWAN_LAW_INDEX_PATH: Path = PROJECT_ROOT / "data" / "taiwan_law_index.json"
    # 公共工程施工綱要規範目錄（由 scripts/sync_pcces.py 產生）
    PCCES_INDEX_PATH: Path = PROJECT_ROOT / "data" / "pcces_index.json"

    # --- Migration 回填既有資料、部署初始化預設租戶用；請求授權必須使用 CurrentUser.tenant_id ---
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"

    # --- Log ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ---- 衍生屬性 ----
    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        return tuple(e.strip().lower() for e in self.ALLOWED_EXTENSIONS.split(",") if e.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def regulation_sources(self) -> list[str]:
        return [s.strip() for s in self.REGULATION_SOURCES.split(",") if s.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
