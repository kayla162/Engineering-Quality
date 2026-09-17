"""FastAPI 應用程式進入點。

本機啟動：
    uvicorn app.main:app --reload --app-dir backend
API 文件：
    http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import log_context, setup_logging
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "%s v%s 啟動",
        settings.APP_NAME,
        settings.APP_VERSION,
        extra=log_context(
            llm_enabled=settings.ENABLE_LLM_FALLBACK,
            sources=settings.regulation_sources,
        ),
    )
    yield
    await dispose_engine()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="工程法規／規範智慧檢索與符合性檢查平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
# 讓 /docs 明確標示所有錯誤都是 docs/api.md 第 6 節的統一格式
app.include_router(
    api_router,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
