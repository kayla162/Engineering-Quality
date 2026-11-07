"""把文字轉成向量。

預設用本機跑的開源模型（sentence-transformers），不呼叫外部 API：
法規條文是公開資料，但使用者上傳的工程文件不一定能送出去，而且評估要能重現。
Anthropic 沒有提供 embedding API，這裡和 `app/ai` 的 LLM 供應商是兩件事。

`EMBEDDING_PROVIDER=none`（預設）時完全不載入模型，搜尋退回只用關鍵字與字詞相似度，
測試與 CI 不需要安裝 torch。要啟用語意搜尋：

    pip install -r requirements-semantic.txt
    EMBEDDING_PROVIDER=local EMBEDDING_MODEL=BAAI/bge-m3
"""

import hashlib
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.config import settings


class Embedder(Protocol):
    name: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class LocalEmbedder:
    """sentence-transformers 模型。輸出都做 L2 正規化，內積就是餘弦相似度。"""

    def __init__(self, model_name: str, max_seq_length: int = 512, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer  # 選用套件，用到才載入

        self.name = model_name
        self._model = SentenceTransformer(model_name)
        self._model.max_seq_length = max_seq_length
        self._batch_size = batch_size
        dimension = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dimension = int(dimension())
        # e5 系列要在查詢與文件前加前綴，其他模型不用
        self._query_prefix, self._doc_prefix = ("query: ", "passage: ") if "e5" in model_name.lower() else ("", "")

    def embed_documents(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray:
        return self._model.encode(
            [self._doc_prefix + t for t in texts],
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
        ).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._model.encode(
            self._query_prefix + text, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype(np.float32)


def corpus_hash(chunks) -> str:
    """語料內容的指紋：條文改了、收錄範圍改了，快取的向量就不能再用。"""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.ref.encode())
        digest.update(chunk.text.encode())
    return digest.hexdigest()[:12]


def cached_document_vectors(embedder: Embedder, chunks, cache_dir: Path) -> np.ndarray:
    """文件向量依「模型＋語料指紋」快取成 .npy。bge-m3 在 CPU 上算幾千筆要十幾分鐘，評估與建索引共用。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{embedder.name.replace('/', '__')}-{corpus_hash(chunks)}.npy"
    if path.exists():
        return np.load(path)
    vectors = embedder.embed_documents([chunk.text for chunk in chunks], show_progress=True)
    np.save(path, vectors)
    return vectors


@lru_cache
def get_embedder() -> Embedder | None:
    """依設定取得 embedder；沒有啟用就回傳 None（呼叫端要能退回關鍵字搜尋）。"""
    if settings.EMBEDDING_PROVIDER == "none":
        return None
    if settings.EMBEDDING_PROVIDER == "local":
        return LocalEmbedder(settings.EMBEDDING_MODEL)
    raise ValueError(f"不支援的 EMBEDDING_PROVIDER：{settings.EMBEDDING_PROVIDER}")
