"""語意搜尋的語料：法規條文與施工綱要規範章節（app/search/corpus.py）。

這是公開資料，不分租戶。由 `scripts/build_search_index.py` 整份重建，不在 API 裡改。

向量直接存在 PostgreSQL（pgvector），不另外架向量資料庫：
- 語料只有幾千筆，pgvector 的 HNSW 索引綽綽有餘；
- 條文、章節和其他業務資料在同一個資料庫，備份、權限、交易都只有一套；
- 搜尋結果要和法規主檔 join（現行／廢止），同一個資料庫一個查詢就做完。
SQLite（開發與測試）沒有向量型別，同一欄位存成 JSON 陣列，在記憶體算相似度。
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base, created_at_column, uuid_pk

#: 向量維度，跟著預設模型 BAAI/bge-m3。換成不同維度的模型要寫 migration 改欄位
EMBEDDING_DIMENSION = 1024

EmbeddingColumn = JSON().with_variant(Vector(EMBEDDING_DIMENSION), "postgresql")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: 「建築法 第 34 條」「PCCES 03310」，評估集的正確答案也用這個
    ref: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    #: law_article | spec_chapter
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    locator: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 沒有啟用 embedding 時建索引，這欄是空的，搜尋只用關鍵字與字詞相似度
    embedding: Mapped[Any] = mapped_column(EmbeddingColumn, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    indexed_at: Mapped[datetime] = created_at_column()
