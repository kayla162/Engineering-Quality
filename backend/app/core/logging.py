"""Log 設定：預設輸出單行 JSON，方便日後直接接 ELK / Loki。"""

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 呼叫端用 logger.info("...", extra={"document_id": ...}) 帶進來的欄位
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def log_context(**fields) -> dict:
    """組出可以安全放進 logger 的 extra=。

    Python 的 logging 遇到與 LogRecord 內建屬性同名的欄位（filename、module、name...）
    會直接丟 KeyError，讓整個 request 掛掉。這裡自動把衝突的欄位加上前綴。

        logger.info("上傳完成", extra=log_context(filename=name))  # -> ctx_filename
    """
    return {(f"ctx_{key}" if key in _RESERVED else key): value for key, value in fields.items()}


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if settings.LOG_JSON
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    # 這兩個套件預設太吵
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
