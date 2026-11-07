"""混合檢索：精確比對（條號、章碼、標準編號）＋ 語意向量。

為什麼不只用向量：
- 「營造安全衛生設施標準第 19 條」「03310 章」「CNS 14253」這種查詢，使用者要的是**那一條**。
  向量模型對數字不敏感，第 19 條和第 91 條在向量空間裡幾乎一樣近。
  評估集裡這類題目，純向量 Recall@5 只有 0.64，加上精確比對是 1.00。
- 「開挖深度超過一點五公尺要做擋土」這種查詢，條文寫的是「露天開挖」「擋土支撐」，
  字面重疊少，只有向量找得到。

為什麼沒有把「字詞相似度」也放進來合併：第一版是 精確比對 ＋ RRF(字詞相似度, 向量)，
評估結果混合（0.76）反而輸給純向量（0.80）——字詞那一路在口語題目上很弱，
等權合併會把向量找到的正解往下拉（口語題 0.80 → 0.57）。拿掉之後是 0.89。
字詞相似度現在只在語意模型沒有啟用時當備援（見 docs/semantic-search.md）。

合併用 Reciprocal Rank Fusion：score = Σ 1 / (k + rank)，只看名次、不看分數，
不必校正不同方法的分數尺度。k=60 是原論文的值，沒有拿評估集調過。
精確比對命中的條文一律排在最前面，彼此之間再依其他路的名次排。

查詢流程與資料庫無關：PostgreSQL 由 pgvector 算向量那一路，SQLite 與評估腳本用
`InMemoryIndex` 在記憶體算，兩邊都交給同一個 `fuse()`。
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from app.search.corpus import Chunk, article_ref, chapter_ref
from app.search.retriever import BigramIndex

RRF_K = 60
#: 每一路取前幾名進融合
CANDIDATES = 50

MODES = ("lexical", "vector", "hybrid")
#: 評估用：第一版的設計，精確比對 ＋ RRF(字詞相似度, 向量)。不開放給 API
HYBRID_WITH_LEXICAL = "hybrid-lexical"

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100}
_NUM = r"(?:\d+|[零〇一二兩三四五六七八九十百]+)"
_ARTICLE = re.compile(rf"第\s*({_NUM})\s*(?:-\s*({_NUM})\s*條|條\s*之\s*({_NUM})|條)")
_CHAPTER_CODE = re.compile(r"(?<!\d)(\d{5})(?!\d)")
#: 標準編號：CNS 14253、ISO 45001、ASTM C39。只比對條文裡真的寫出這個編號的
_STANDARD = re.compile(r"(?<![A-Za-z])(CNS|ISO|ASTM|JIS|EN)\s*-?\s*([A-Z]?\d{2,6})", re.IGNORECASE)


def standard_keys(text: str) -> list[str]:
    return [f"{body.upper()} {number.upper()}" for body, number in _STANDARD.findall(text)]


def cn_to_int(text: str) -> int:
    """「三十四」→ 34、「一百零二」→ 102；阿拉伯數字直接轉。"""
    if text.isdigit():
        return int(text)
    total, digit = 0, 0
    for char in text:
        if char in _CN_DIGITS:
            digit = _CN_DIGITS[char]
        else:
            total += (digit or 1) * _CN_UNITS[char]
            digit = 0
    return total + digit


class RefMatcher:
    """從查詢裡找出明確指名的條文、章節或標準：「建築法第 34 條」「採購法第二十二條」「03310」「CNS 14253」。"""

    def __init__(self, chunks: Sequence[Chunk], aliases: Mapping[str, str] | None = None):
        self._refs = {chunk.ref for chunk in chunks}
        names = {chunk.source for chunk in chunks if chunk.kind == "law_article"}
        self._names = {name: name for name in names} | dict(aliases or {})
        # 長的先比：「營造業法施行細則」不能被「營造業法」搶走
        self._ordered_names = sorted(self._names, key=len, reverse=True)
        self._by_number: dict[str, list[str]] = {}
        self._by_standard: dict[str, list[str]] = {}
        for chunk in chunks:
            if chunk.kind == "law_article":
                self._by_number.setdefault(chunk.locator, []).append(chunk.ref)
            for key in dict.fromkeys(standard_keys(chunk.text)):
                self._by_standard.setdefault(key, []).append(chunk.ref)

    def law_in(self, query: str) -> str | None:
        return next((self._names[name] for name in self._ordered_names if name in query), None)

    def match(self, query: str) -> list[str]:
        found: list[str] = []
        law = self.law_in(query)
        for main, dash, zhi in _ARTICLE.findall(query):
            sub = dash or zhi
            number = str(cn_to_int(main)) + (f"-{cn_to_int(sub)}" if sub else "")
            if law:
                candidates = [article_ref(law, number)]
            else:
                # 只寫條號沒寫法規：每一部法規的這一條都算，順序交給其他兩路決定
                candidates = self._by_number.get(f"第 {number} 條", [])
            found += [ref for ref in candidates if ref in self._refs]
        found += [chapter_ref(code) for code in _CHAPTER_CODE.findall(query) if chapter_ref(code) in self._refs]
        for key in standard_keys(query):
            found += self._by_standard.get(key, [])
        return list(dict.fromkeys(found))


@dataclass(frozen=True)
class Ranked:
    ref: str
    score: float
    #: 這筆在各路的名次（1 起算），沒進前幾名就不出現。畫面用來說明「為什麼排在這裡」
    ranks: dict[str, int] = field(default_factory=dict)


def fuse(rankings: Mapping[str, Sequence[str]], exact: Sequence[str] = (), limit: int = 10) -> list[Ranked]:
    """RRF 合併各路排名；`exact` 裡的條文不論分數一律排最前面（之間仍依 RRF 分數排）。"""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for channel, refs in rankings.items():
        for position, ref in enumerate(refs[:CANDIDATES], start=1):
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (RRF_K + position)
            ranks.setdefault(ref, {})[channel] = position
    exact_set = set(exact)
    for position, ref in enumerate(exact, start=1):
        scores.setdefault(ref, 0.0)
        ranks.setdefault(ref, {})["exact"] = position
    ordered = sorted(scores, key=lambda ref: (ref not in exact_set, -scores[ref], ref))
    return [Ranked(ref, round(scores[ref], 5), ranks[ref]) for ref in ordered[:limit]]


class InMemoryIndex:
    """把整個語料放在記憶體：評估腳本與 SQLite 用。PostgreSQL 的向量那一路改由 pgvector 算。"""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        embeddings: np.ndarray | None = None,
        aliases: Mapping[str, str] | None = None,
    ):
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("embedding 筆數和語料筆數不同")
        self.chunks = list(chunks)
        self.refs = [chunk.ref for chunk in self.chunks]
        self.embeddings = embeddings
        self.matcher = RefMatcher(self.chunks, aliases)
        self._lexical = BigramIndex([chunk.text for chunk in self.chunks])

    def lexical(self, query: str, k: int = CANDIDATES) -> list[str]:
        return [self.refs[hit.index] for hit in self._lexical.search(query, k=k, min_score=0.0)]

    def vector(self, query_vector: np.ndarray, k: int = CANDIDATES) -> list[str]:
        if self.embeddings is None:
            return []
        similarities = self.embeddings @ query_vector
        top = np.argsort(-similarities, kind="stable")[:k]
        return [self.refs[i] for i in top]

    def search(
        self, query: str, mode: str = "hybrid", query_vector: np.ndarray | None = None, limit: int = 10
    ) -> list[Ranked]:
        if mode not in (*MODES, HYBRID_WITH_LEXICAL):
            raise ValueError(f"不支援的搜尋方式：{mode}")
        if mode == "lexical":
            return fuse({"lexical": self.lexical(query)}, limit=limit)
        if query_vector is None:
            raise ValueError(f"{mode} 需要查詢向量")
        if mode == "vector":
            return fuse({"vector": self.vector(query_vector)}, limit=limit)
        rankings = {"vector": self.vector(query_vector)}
        if mode == HYBRID_WITH_LEXICAL:
            rankings["lexical"] = self.lexical(query)
        return fuse(rankings, exact=self.matcher.match(query), limit=limit)
