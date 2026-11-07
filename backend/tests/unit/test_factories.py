"""測試資料產生器本身的保證。

回歸：docx / xlsx 是 zip，帶存檔當下的時間。同一個產生器相隔跨過時間邊界呼叫兩次，
會產出不同的位元組，「重複上傳回 409」的測試因此時好時壞（本機 4 次失敗 3 次）。
"""

import hashlib
import time
from pathlib import Path

from app.parsers import parse_document
from tests.factories import make_docx_bytes, make_xlsx_bytes


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_same_content_gives_the_same_bytes_across_time():
    """zip 的時間精度是 2 秒，openpyxl 的修改時間是 1 秒：等 2.1 秒一定跨過邊界。"""
    docx, xlsx = make_docx_bytes(), make_xlsx_bytes()
    time.sleep(2.1)

    assert digest(make_docx_bytes()) == digest(docx)
    assert digest(make_xlsx_bytes()) == digest(xlsx)


def test_fixed_timestamps_still_parse(tmp_path: Path):
    """改寫 zip 之後檔案仍是合法的 Word / Excel，解析器讀得出內容。"""
    docx = tmp_path / "文件.docx"
    docx.write_bytes(make_docx_bytes())
    xlsx = tmp_path / "標單.xlsx"
    xlsx.write_bytes(make_xlsx_bytes())

    assert parse_document(docx).sections
    assert parse_document(xlsx).sections
