"""驗證模型回答裡的引用：引的條文有沒有給它、引文是不是真的在那一條裡。

不靠模型自我檢查，用字串比對：
- `ref` 必須是這次送給模型的條文之一（防止引用一條根本沒給它、甚至不存在的條文）；
- `quote` 經過正規化（NFKC、去空白）後，必須是那一條原文的子字串（防止改寫、拼湊、張冠李戴）；
- 太短的引文（少於 MIN_QUOTE_CHARS 字）不算，否則「應」「雇主」這種字串到處都對得上。

通過驗證只代表「引文確實出自那一條」，不代表回答的推論正確——那是評估裡 LLM 裁判與人工抽查的工作
（scripts/eval_qa.py）。
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.ai.base import Citation, Passage

MIN_QUOTE_CHARS = 6

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """全形半形統一（NFKC）、去掉所有空白。條文的換行與模型的空格都不影響比對。"""
    return _SPACES.sub("", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class CheckedCitation:
    ref: str
    quote: str
    verified: bool
    #: 沒通過的原因，給畫面與評估看
    problem: str | None = None


def check_citations(citations: Sequence[Citation], passages: Sequence[Passage]) -> list[CheckedCitation]:
    texts = {p.ref: normalize(p.text) for p in passages}
    checked = []
    for citation in citations:
        quote = normalize(citation.quote)
        if citation.ref not in texts:
            problem = "引用的條文不在這次提供的範圍內"
        elif len(quote) < MIN_QUOTE_CHARS:
            problem = f"引文太短（少於 {MIN_QUOTE_CHARS} 字），無法確認出處"
        elif quote not in texts[citation.ref]:
            problem = "引文不在該條原文裡（可能改寫、拼湊或引錯條）"
        else:
            problem = None
        checked.append(CheckedCitation(citation.ref, citation.quote, problem is None, problem))
    return checked
