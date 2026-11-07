"""建立法規條文與規範章節的搜尋索引（knowledge_chunks 表）。整份取代。

    python scripts/build_search_index.py              # 依 EMBEDDING_PROVIDER 決定要不要算向量
    python scripts/build_search_index.py --no-vectors # 只建字詞索引（不需要 torch）

前置：scripts/sync_taiwan_law.py、scripts/sync_pcces.py 已下載資料；
要算向量的話 EMBEDDING_PROVIDER=local 並安裝 requirements-semantic.txt。
收錄範圍見 data/search_corpus.json。
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.search.corpus import build_corpus  # noqa: E402
from app.search.embeddings import cached_document_vectors, get_embedder  # noqa: E402
from app.services.knowledge_search_service import KnowledgeSearchService  # noqa: E402


async def main(with_vectors: bool) -> None:
    chunks = build_corpus(settings.DATA_DIR, settings.PCCES_INDEX_PATH)
    embedder = get_embedder() if with_vectors else None
    vectors = None
    if embedder is not None:
        started = time.perf_counter()
        print(f"{embedder.name} 向量化 {len(chunks)} 筆…")
        # 和 scripts/eval_search.py 共用快取：評估跑過就不必再算一次
        vectors = cached_document_vectors(embedder, chunks, settings.DATA_DIR / "generated" / "embeddings")
        print(f"  完成，{time.perf_counter() - started:.0f} 秒")
    elif with_vectors:
        print("EMBEDDING_PROVIDER=none：只建字詞索引，搜尋不會用到語意向量")

    async with get_session_factory()() as session:
        count = await KnowledgeSearchService(session, embedder).rebuild(chunks, vectors)
    await dispose_engine()
    print(f"已寫入 {count} 筆（{'含' if vectors is not None else '不含'}向量）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-vectors", action="store_true")
    asyncio.run(main(not parser.parse_args().no_vectors))
