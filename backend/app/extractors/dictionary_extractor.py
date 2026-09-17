"""字典式抽取：直接比對已知的法規名稱與別名。

補規則引擎抓不到的簡稱（例如「品管要點」不符合任何命名慣例字尾）。
字典來源是 data/alias_dictionary.json，新增別名不需要改程式碼。
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.enums import ExtractionMethod, RegulationType
from app.extractors.base import Candidate


@dataclass(frozen=True, slots=True)
class AliasEntry:
    """一個可以在文字中被搜尋的詞，以及它對應的官方全名。"""

    term: str          # 文件裡可能出現的字串（別名或全名本身）
    canonical: str     # 官方全名
    type: RegulationType


@lru_cache
def load_alias_entries(path: Path | None = None) -> tuple[AliasEntry, ...]:
    """讀取別名字典。結果會被快取，重新載入請呼叫 load_alias_entries.cache_clear()。"""
    path = path or (settings.DATA_DIR / "alias_dictionary.json")
    if not path.exists():
        return ()

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries: list[AliasEntry] = []
    for item in raw.get("entries", []):
        canonical = item["canonical"]
        reg_type = RegulationType(item.get("type", RegulationType.OTHER))
        for term in [canonical, *item.get("aliases", [])]:
            entries.append(AliasEntry(term=term, canonical=canonical, type=reg_type))

    # 長詞優先，避免「採購法」先命中而蓋掉「政府採購法」
    return tuple(sorted(entries, key=lambda e: -len(e.term)))


class DictionaryExtractor:
    method = ExtractionMethod.DICTIONARY

    def __init__(self, entries: tuple[AliasEntry, ...] | None = None):
        self._entries = entries if entries is not None else load_alias_entries()

    def extract(self, text: str) -> list[Candidate]:
        results: list[Candidate] = []
        taken: list[tuple[int, int]] = []

        for entry in self._entries:
            for match in re.finditer(re.escape(entry.term), text, re.IGNORECASE):
                span = (match.start(), match.end())
                if any(span[0] < end and start < span[1] for start, end in taken):
                    continue  # 已被更長的詞覆蓋
                taken.append(span)
                is_alias = entry.term != entry.canonical
                results.append(
                    Candidate(
                        raw_text=match.group(0),
                        regulation_type=entry.type,
                        method=self.method,
                        confidence=1.0,
                        start=span[0],
                        end=span[1],
                        notes=[
                            f"字典命中別名「{entry.term}」對應「{entry.canonical}」"
                            if is_alias
                            else "字典命中法規全名"
                        ],
                    )
                )
        return results
