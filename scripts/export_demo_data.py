"""匯出靜態展示版（VITE_DEMO=1）用的題目與回答：frontend/public/demo-data.json。

    python scripts/export_demo_data.py

回答來自 scripts/eval_qa.py 的評估結果（data/qa_eval/results.json，Claude Opus 5.5 的真實輸出、混合搜尋），
搜尋結果用和上線同一套 InMemoryIndex（bge-m3）現算。展示版不呼叫任何 API。
只收「裁判判定正確且主張都有依據」的回答，以及正確拒答的陷阱題。
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.search.corpus import build_corpus, load_corpus_config  # noqa: E402
from app.search.embeddings import LocalEmbedder, cached_document_vectors  # noqa: E402
from app.search.hybrid import InMemoryIndex  # noqa: E402
from app.services.knowledge_search_service import METHOD_NOTES, SNIPPET_LENGTH  # noqa: E402

#: (題號, 分組)。分組決定畫面上的按鈕區塊
QUESTIONS = [
    ("s02", "一般問題"), ("s03", "一般問題"), ("s07", "一般問題"), ("s11", "一般問題"), ("s14", "一般問題"),
    ("s19", "一般問題"), ("s05", "一般問題"), ("t18", "一般問題"), ("t22", "一般問題"),
    ("u03", "超出法規範圍（陷阱題）"), ("u01", "超出法規範圍（陷阱題）"),
    ("u05", "超出法規範圍（陷阱題）"), ("u11", "超出法規範圍（陷阱題）"),
]
SECTION_NOTE = "示範版只收錄法規條文；上傳文件的段落搜尋請在完整版使用。"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "data", help="含 search_corpus.json、法規快取與 qa_eval/results.json")
    parser.add_argument("--out", type=Path, default=ROOT / "frontend" / "public" / "demo-data.json")
    args = parser.parse_args()

    rows = json.loads((args.data / "qa_eval" / "results.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows if r["retriever"] == "hybrid"}
    chunks = build_corpus(args.data)
    by_ref = {c.ref: c for c in chunks}
    config = load_corpus_config(args.data / "search_corpus.json")
    embedder = LocalEmbedder("BAAI/bge-m3")
    index = InMemoryIndex(chunks, cached_document_vectors(embedder, chunks, args.data / "generated" / "embeddings"),
                          config.get("aliases"))

    items = []
    for qid, group in QUESTIONS:
        row = by_id[qid]
        if row["kind"] == "answerable":
            assert row["status"] == "answered" and row["judge"]["correctness"] == "correct" and row["judge"]["faithful"], qid
        else:
            assert row["status"] == "insufficient", qid
        ranked = index.search(row["query"], mode="hybrid", query_vector=embedder.embed_query(row["query"]), limit=10)
        hits = []
        for r in ranked:
            chunk = by_ref[r.ref]
            snippet = chunk.content[:SNIPPET_LENGTH] + ("…" if len(chunk.content) > SNIPPET_LENGTH else "")
            hits.append({"ref": r.ref, "kind": chunk.kind, "source": chunk.source, "locator": chunk.locator,
                         "heading": chunk.heading, "snippet": snippet, "score": r.score, "ranks": r.ranks})
        items.append({
            "id": qid,
            "group": group,
            "question": row["query"],
            "knowledge": {"query": row["query"], "mode": "hybrid", "vector_enabled": True,
                          "method_note": METHOD_NOTES["hybrid"], "hits": hits},
            "answer": {
                "question": row["query"], "status": row["status"], "answer": row["answer"],
                "citations": row["citations"], "retrieved": row["retrieved"],
                "model": row["model"], "prompt_version": "qa_v1",
            },
        })

    payload = {
        "note": "示範版：回答是評估時 Claude Opus 5.5 的真實輸出（混合搜尋），引用都已逐字比對原文；網頁不呼叫任何 API。",
        "section_note": SECTION_NOTE,
        "items": items,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} 題 → {args.out}（{args.out.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
