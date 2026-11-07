"""ORM 欄位型別的全域檢查。

SQLite 不分辨含不含時區，所以 datetime 欄位少寫 ``DateTime(timezone=True)`` 時，
單元測試照樣會過，要到 PostgreSQL（asyncpg）寫入含時區的 ``utcnow()`` 才會爆
``can't subtract offset-naive and offset-aware datetimes``。這裡直接檢查 metadata。
"""

from sqlalchemy import DateTime

import app.models  # noqa: F401 — 註冊所有表
from app.models.base import Base


def _datetime_columns():
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, DateTime):
                yield f"{table.name}.{column.name}", column.type


def test_there_are_datetime_columns_to_check():
    assert len(list(_datetime_columns())) > 10


def test_all_datetime_columns_are_timezone_aware():
    naive = [name for name, col_type in _datetime_columns() if not col_type.timezone]
    assert naive == [], (
        "以下 datetime 欄位沒有 timezone=True（請用 app.models.base 的 "
        f"created_at_column / updated_at_column / nullable_timestamp）：{naive}"
    )
