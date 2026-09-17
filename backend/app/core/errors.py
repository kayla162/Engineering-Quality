"""統一的錯誤型別與 FastAPI exception handler（對應 docs/api.md 第 6 節）。

所有 API 錯誤回應格式固定為：
    {"error": {"code": "...", "message": "...", "details": null}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """所有可預期的業務錯誤的基底類別。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class DocumentNotFoundError(NotFoundError):
    code = "DOCUMENT_NOT_FOUND"


class ReferenceNotFoundError(NotFoundError):
    code = "REFERENCE_NOT_FOUND"


class RegulationNotFoundError(NotFoundError):
    code = "REGULATION_NOT_FOUND"


class JobNotFoundError(NotFoundError):
    code = "JOB_NOT_FOUND"


class ProjectNotFoundError(NotFoundError):
    code = "PROJECT_NOT_FOUND"


class InvalidFileTypeError(AppError):
    code = "INVALID_FILE_TYPE"


class FileTooLargeError(AppError):
    code = "FILE_TOO_LARGE"


class DuplicateFileError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "DUPLICATE_FILE"


class UnprocessableDocumentError(AppError):
    """檔案毀損、加密或無法解析。"""

    status_code = 422
    code = "UNPROCESSABLE_DOCUMENT"


class SourceQueryError(Exception):
    """外部法規來源查詢失敗。

    這個例外不會直接變成 HTTP 錯誤，而是由 MatchingService 捕捉後
    把該筆 reference 標記為 UNKNOWN，讓整份文件的分析繼續完成。
    """

    def __init__(
        self,
        source: str,
        message: str,
        http_status: str | None = None,
        remedy: str | None = None,
    ):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.message = message
        self.http_status = http_status
        #: 使用者/維運可以自己做的下一步（例如「跑這個同步腳本」）。
        #: 只有在真的有動作可做時才填，否則前端會顯示一個沒有意義的指示。
        self.remedy = remedy


def _error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body("VALIDATION_ERROR", "請求格式錯誤", exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 完整堆疊只寫進 log，不外洩給前端
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("INTERNAL_ERROR", "系統發生未預期的錯誤"),
        )
