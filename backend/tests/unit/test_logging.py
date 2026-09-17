"""log_context 的單元測試。

背景：Python 的 logging 遇到與 LogRecord 內建屬性同名的 extra 欄位會丟 KeyError，
讓整個 request 掛掉。log_context 就是為了讓這件事不可能再發生。
"""

import logging

import pytest

from app.core.logging import log_context


def test_reserved_keys_are_prefixed():
    assert log_context(filename="a.docx") == {"ctx_filename": "a.docx"}


def test_normal_keys_are_untouched():
    assert log_context(document_id="x", page=3) == {"document_id": "x", "page": 3}


@pytest.mark.parametrize("key", ["filename", "module", "name", "message", "args", "levelname"])
def test_logging_never_raises_for_reserved_keys(key, caplog):
    logger = logging.getLogger("test.log_context")
    with caplog.at_level(logging.INFO):
        logger.info("測試訊息", extra=log_context(**{key: "value"}))
    assert caplog.records[0].getMessage() == "測試訊息"
