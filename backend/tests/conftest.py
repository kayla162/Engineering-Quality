"""測試共用設定。

重點：環境變數必須在 import 任何 app 模組之前設定，因為 app.core.config.settings
是模組層級的單例。測試一律使用獨立的 SQLite 檔案，並關閉 AI。
"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="regplatform-tests-"))

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["ENABLE_LLM_FALLBACK"] = "false"
os.environ["LOG_JSON"] = "false"
# 用 INFO 而不是 WARNING：info 級的 log 也要被實際執行到，
# 才抓得到「extra 欄位名稱和 LogRecord 內建屬性衝突」這類只在寫 log 時才炸的錯誤
os.environ["LOG_LEVEL"] = "INFO"
os.environ["REGULATION_SOURCES"] = "mock"

from app.core.db import dispose_engine, get_engine, get_session_factory  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.document_service import DocumentService  # noqa: E402
from tests.factories import make_docx_bytes, seed_regulations  # noqa: E402


@pytest.fixture(scope="function")
async def db_session():
    """每個測試一個乾淨的資料庫。"""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with get_session_factory()() as session:
        await seed_regulations(session)
        yield session

    await dispose_engine()


@pytest.fixture
async def api_client(db_session):
    """走完整 ASGI 流程的 HTTP 測試 client（背景任務也會執行）。"""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def uploaded_document(db_session):
    """已上傳一份範例 DOCX 的文件。"""
    document = await DocumentService(db_session).upload("整體品質計畫.docx", make_docx_bytes())
    await db_session.commit()
    return document


@pytest.fixture
def sample_docx_bytes() -> bytes:
    return make_docx_bytes()
