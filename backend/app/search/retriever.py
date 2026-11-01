"""示範用的段落檢索（Phase 2 RAG 的替身）：字元雙字組（bigram）TF-IDF + 餘弦相似度。

Phase 2 規劃的是 embedding + 向量資料庫（Qdrant），需要 embedding 服務與 API key。
在那之前，這裡用純 Python 做一個「找得到相關段落」的版本，讓檢索的使用流程先跑得起來：

- 中文沒有空白斷詞，用相鄰兩字當詞（「混凝」「凝土」「土澆」…），英數字串整段當一個詞。
- 每次查詢現算，不建索引、不存東西：示範規模（幾千段）夠快，也不會有索引過期的問題。
- **這是字面相似，不是語意相似。**「澆置」查得到「澆置」，查不到「灌漿」。畫面會標明。

和 development-plan.md 第 5 節的分工一致：檢索只負責「找得到相關內容」，
不負責「這是不是最新有效版本」——那仍然是法規比對（Layer 1）的工作。
換成真的 embedding 時，換掉 BigramIndex，`search()` 的介面不變。
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_CJK_RUN = re.compile(r"[一-鿿]+")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*")


def tokens(text: str) -> list[str]:
    """中文取相鄰兩字，英數字（CNS 3090 的 3090、QP-07-03）整段當一個詞。"""
    result: list[str] = []
    for run in _CJK_RUN.findall(text):
        result += [run[i : i + 2] for i in range(len(run) - 1)] if len(run) > 1 else [run]
    result += [word.upper() for word in _WORD.findall(text)]
    return result


@dataclass(frozen=True)
class Hit:
    index: int
    score: float
    #: 查詢裡哪些詞在這段出現了，前端可以拿來標示
    matched: list[str]


class BigramIndex:
    def __init__(self, texts: Sequence[str]):
        self._counts = [Counter(tokens(text)) for text in texts]
        document_frequency = Counter(term for counts in self._counts for term in counts)
        total = len(texts)
        self._idf = {term: math.log((1 + total) / (1 + df)) + 1 for term, df in document_frequency.items()}
        self._norms = [self._norm(counts) for counts in self._counts]

    def _weight(self, term: str, count: int) -> float:
        return (1 + math.log(count)) * self._idf.get(term, 0.0)

    def _norm(self, counts: Counter) -> float:
        return math.sqrt(sum(self._weight(t, c) ** 2 for t, c in counts.items())) or 1.0

    def search(self, query: str, k: int = 10, min_score: float = 0.05) -> list[Hit]:
        query_counts = Counter(tokens(query))
        query_weights = {t: self._weight(t, c) for t, c in query_counts.items() if t in self._idf}
        if not query_weights:
            return []
        query_norm = math.sqrt(sum(w * w for w in query_weights.values()))

        hits = []
        for index, counts in enumerate(self._counts):
            shared = [t for t in query_weights if t in counts]
            if not shared:
                continue
            dot = sum(query_weights[t] * self._weight(t, counts[t]) for t in shared)
            score = dot / (query_norm * self._norms[index])
            if score >= min_score:
                hits.append(Hit(index, round(score, 4), shared))
        hits.sort(key=lambda hit: (-hit.score, hit.index))
        return hits[:k]
