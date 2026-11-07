"""比較幾種檢索方式找法規條文與規範章節的命中率：字詞相似度、純向量、混合。

    python scripts/eval_search.py                       # 預設 BAAI/bge-m3，開發集＋保留測試集
    python scripts/eval_search.py --models BAAI/bge-m3 sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    python scripts/eval_search.py --write docs/search-eval-results.md --misses

評估集分兩份，每題列出所有可接受的正確答案（條文或章節的 ref）：
- data/search_eval/queries.json（開發集）：設計時看過結果，用來決定架構
- data/search_eval/queries_test.json（保留測試集）：架構定案後才寫、只跑一次，
  數字才不是「拿考題練習」

語料由 data/search_corpus.json 決定（app/search/corpus.py）。需要 requirements-semantic.txt。
模型已下載過的話，設 HF_HUB_OFFLINE=1 可以避免每次連線檢查更新。

指標（每題算完再平均）：
- Recall@5：正確答案有幾成出現在前 5 名
- Hit@1：第 1 名是不是正確答案
- MRR@10：第一個正確答案名次的倒數（前 10 名沒有就是 0）

文件向量會快取在 data/generated/embeddings/（依模型與語料內容的雜湊命名），第二次跑只要幾十秒。
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from app.search.corpus import build_corpus, load_corpus_config  # noqa: E402
from app.search.hybrid import HYBRID_WITH_LEXICAL, InMemoryIndex  # noqa: E402

DATA = ROOT / "data"
CACHE = DATA / "generated" / "embeddings"
QUERY_SETS = {
    "dev": DATA / "search_eval" / "queries.json",
    "test": DATA / "search_eval" / "queries_test.json",
}
SET_LABELS = {"dev": "開發集", "test": "保留測試集"}

#: hybrid-lexical 是第一版設計，留著對照為什麼拿掉字詞相似度
METHODS = ("lexical", "vector", HYBRID_WITH_LEXICAL, "hybrid")
METHOD_LABELS = {
    "lexical": "字詞相似度（原本的搜尋）",
    "vector": "純向量",
    HYBRID_WITH_LEXICAL: "精確比對＋RRF(字詞, 向量)（第一版）",
    "hybrid": "**精確比對＋向量（採用）**",
}
TYPE_LABELS = {"exact": "指名條號／章碼／標準", "keyword": "關鍵字", "semantic": "口語描述"}
METRICS = ("recall@5", "hit@1", "mrr@10")


def load_queries(path: Path, refs: set[str]) -> list[dict]:
    queries = json.loads(path.read_text(encoding="utf-8"))["queries"]
    problems = [f"{q['id']}: {ref}" for q in queries for ref in q["relevant"] if ref not in refs]
    if problems:
        raise SystemExit(f"{path.name} 的正確答案不在語料裡：\n  " + "\n  ".join(problems))
    return queries


def score(ranking: list[str], relevant: set[str]) -> dict[str, float]:
    first = next((i for i, ref in enumerate(ranking[:10], start=1) if ref in relevant), None)
    return {
        "recall@5": len(relevant & set(ranking[:5])) / len(relevant),
        "hit@1": float(bool(ranking) and ranking[0] in relevant),
        "mrr@10": 1 / first if first else 0.0,
    }


def evaluate(model_name: str, chunks, config, query_sets: dict[str, list[dict]]) -> dict:
    from app.search.embeddings import LocalEmbedder, cached_document_vectors

    print(f"模型 {model_name}", file=sys.stderr)
    embedder = LocalEmbedder(model_name)
    index = InMemoryIndex(chunks, cached_document_vectors(embedder, chunks, CACHE), config.get("aliases"))

    everything = [q for queries in query_sets.values() for q in queries]
    started = time.perf_counter()
    vectors = {q["id"]: embedder.embed_query(q["query"]) for q in everything}
    per_query_ms = (time.perf_counter() - started) * 1000 / len(everything)

    sets = {}
    for name, queries in query_sets.items():
        rows = []
        for q in queries:
            row = {"id": q["id"], "type": q["type"], "query": q["query"], "relevant": q["relevant"], "methods": {}}
            for method in METHODS:
                ranking = [r.ref for r in index.search(q["query"], mode=method, query_vector=vectors[q["id"]])]
                row["methods"][method] = {"top5": ranking[:5], **score(ranking, set(q["relevant"]))}
            rows.append(row)
        sets[name] = rows
    return {"model": model_name, "dimension": embedder.dimension, "query_embed_ms": round(per_query_ms, 1), "sets": sets}


def mean(rows, method: str, metric: str, query_type: str | None = None) -> float:
    values = [r["methods"][method][metric] for r in rows if query_type in (None, r["type"])]
    return sum(values) / len(values) if values else 0.0


def table(result: dict, rows: list[dict], types: list[str]) -> list[str]:
    lines = [
        f"### {result['model']}（{result['dimension']} 維，查詢向量化平均 {result['query_embed_ms']} ms）",
        "",
        "| 方法 | Recall@5 | Hit@1 | MRR@10 | " + " | ".join(f"R@5 {TYPE_LABELS[t]}" for t in types) + " |",
        "|---|---:|---:|---:|" + "---:|" * len(types),
    ]
    for method in METHODS:
        values = [mean(rows, method, m) for m in METRICS] + [mean(rows, method, "recall@5", t) for t in types]
        lines.append(f"| {METHOD_LABELS[method]} | " + " | ".join(f"{v:.2f}" for v in values) + " |")
    return lines + [""]


def report(results: list[dict], chunks, query_sets: dict[str, list[dict]]) -> str:
    lines = [
        f"語料 {len(chunks)} 筆（條文 {sum(c.kind == 'law_article' for c in chunks)}、"
        f"規範章節 {sum(c.kind == 'spec_chapter' for c in chunks)}）。",
        "",
    ]
    for name, queries in query_sets.items():
        counts = Counter(q["type"] for q in queries)
        types = [t for t in TYPE_LABELS if counts[t]]
        lines += [
            f"## {SET_LABELS[name]}：{len(queries)} 題（" + "、".join(f"{TYPE_LABELS[t]} {counts[t]}" for t in types) + "）",
            "",
        ]
        for result in results:
            lines += table(result, result["sets"][name], types)
    return "\n".join(lines)


def misses(result: dict, name: str, method: str = "hybrid") -> str:
    lines = [f"{SET_LABELS[name]}：混合搜尋 Recall@5 未滿分的題目（{result['model']}）", ""]
    for row in result["sets"][name]:
        m = row["methods"][method]
        if m["recall@5"] < 1:
            lines.append(f"- {row['id']}「{row['query']}」正解 {row['relevant']}；前 5 名 {m['top5']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=["BAAI/bge-m3"])
    parser.add_argument("--sets", nargs="+", choices=list(QUERY_SETS), default=list(QUERY_SETS))
    parser.add_argument("--write", type=Path, help="把結果表格寫進這個 Markdown 檔")
    parser.add_argument("--json", type=Path, default=DATA / "search_eval" / "results.json", help="逐題結果")
    parser.add_argument("--misses", action="store_true", help="列出混合搜尋沒找齊的題目")
    args = parser.parse_args()

    config = load_corpus_config(DATA / "search_corpus.json")
    chunks = build_corpus(DATA)
    refs = {c.ref for c in chunks}
    query_sets = {name: load_queries(QUERY_SETS[name], refs) for name in args.sets}
    ids = [q["id"] for queries in query_sets.values() for q in queries]
    if len(ids) != len(set(ids)):
        raise SystemExit("評估集的題號重複")

    results = [evaluate(model, chunks, config, query_sets) for model in args.models]
    text = report(results, chunks, query_sets)
    if args.misses:
        text += "\n## 混合搜尋沒找齊的題目\n\n" + "\n".join(
            misses(result, name) for result in results for name in query_sets
        )
    print(text)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write:
        args.write.write_text(f"<!-- 由 scripts/eval_search.py 產生，不要手改 -->\n\n{text}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
