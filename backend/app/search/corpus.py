"""語意搜尋的語料：法規條文（全國法規資料庫）與施工綱要規範章節（工程會）。

一筆 `Chunk` 就是搜尋的最小單位：一條條文，或一個規範章節。
`ref` 是穩定的識別字，評估集的正確答案、資料庫的唯一鍵都用它：

- 條文：``建築法 第 34 條``、``營造安全衛生設施標準 第 1-1 條``
- 章節：``PCCES 03310``

條文全文來自 `scripts/sync_taiwan_law.py` 下載的 `data/taiwan_law_cache/*.json.zip`；
章節來自 `scripts/sync_pcces.py` 產生的 `pcces_index.json`（只有章名，沒有內文）。
收哪些法規由 `data/search_corpus.json` 決定，不是把一萬多部法規全倒進來——
和 development-plan.md 第 5 節一致：只收「確定需要語意搜尋」的內容。
"""

import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

LAW_DATASETS = ("ChLaw", "ChOrder")

_SPACES = re.compile(r"\s+")
_ARTICLE_NO = re.compile(r"第\s*(\d+(?:-\d+)?)\s*條")
#: 已刪除或移到別處的條文只剩「（刪除）」「〈移至建築構造編〉」，收進來只會變成搜尋結果裡的雜訊
_PLACEHOLDER = re.compile(r"^[（(〈](?:刪除|移至[^）)〉]*)[）)〉]。?$")


@dataclass(frozen=True)
class Chunk:
    ref: str
    #: law_article | spec_chapter
    kind: str
    #: 法規名稱，或「施工綱要規範」
    source: str
    #: 條號（「第 34 條」）或章碼（「03310」）
    locator: str
    #: 條文所在的章節標題，或規範章名
    heading: str
    content: str

    @property
    def text(self) -> str:
        """檢索用的全文：字詞索引與 embedding 都用這段，兩種方法看到的東西一樣。"""
        head = f"{self.source} {self.locator}"
        if self.heading:
            head += f"（{self.heading}）"
        return f"{head}\n{self.content}" if self.content else head


def article_ref(law_name: str, number: str) -> str:
    return f"{law_name} 第 {number} 條"


def chapter_ref(code: str) -> str:
    return f"PCCES {code}"


def load_corpus_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache
def default_aliases() -> dict[str, str]:
    """`data/search_corpus.json` 裡的法規簡稱（「採購法」→「政府採購法」）。"""
    from app.core.config import settings

    path = settings.DATA_DIR / "search_corpus.json"
    return load_corpus_config(path).get("aliases", {}) if path.exists() else {}


def law_articles(cache_dir: Path, law_names: Iterable[str]) -> list[Chunk]:
    """從全國法規資料庫的下載檔取出指定法規的每一條條文。找不到的法規名稱會報錯，不默默略過。"""
    wanted = list(law_names)
    found: dict[str, list[Chunk]] = {}
    for dataset in LAW_DATASETS:
        archive = cache_dir / f"{dataset}.json.zip"
        if not archive.exists():
            continue
        with zipfile.ZipFile(archive) as zf:
            data = json.loads(zf.read(f"{dataset}.json").decode("utf-8-sig"))
        for law in data["Laws"]:
            name = law["LawName"]
            if name in wanted and name not in found:
                found[name] = list(_articles_of(name, law["LawArticles"]))

    missing = [name for name in wanted if name not in found]
    if missing:
        raise ValueError(f"法規資料裡找不到：{'、'.join(missing)}（先執行 scripts/sync_taiwan_law.py）")
    return [chunk for name in wanted for chunk in found[name]]


def _articles_of(law_name: str, articles: list[dict]) -> Iterable[Chunk]:
    heading = ""
    for article in articles:
        content = _SPACES.sub(" ", article["ArticleContent"]).strip()
        if article["ArticleType"] == "C":
            # 章節標題「第 一 章 總則」：中文數字之間的空白拿掉
            heading = re.sub(r"(?<=[^\sA-Za-z0-9])\s+(?=[^\sA-Za-z0-9])", "", content)
            continue
        match = _ARTICLE_NO.search(article["ArticleNo"])
        if not match or not content or _PLACEHOLDER.match(content):
            continue
        number = match.group(1)
        yield Chunk(
            ref=article_ref(law_name, number),
            kind="law_article",
            source=law_name,
            locator=f"第 {number} 條",
            heading=heading,
            content=content,
        )


def spec_chapters(pcces_index: Path) -> list[Chunk]:
    data = json.loads(pcces_index.read_text(encoding="utf-8"))
    return [
        Chunk(
            ref=chapter_ref(chapter["code"]),
            kind="spec_chapter",
            source="施工綱要規範",
            locator=chapter["code"],
            heading=chapter["name"],
            content="",
        )
        for chapter in data["chapters"]
    ]


def build_corpus(data_dir: Path, pcces_index: Path | None = None) -> list[Chunk]:
    """`data_dir` 底下要有 search_corpus.json 與 taiwan_law_cache/；章節目錄預設也在這裡。"""
    config = load_corpus_config(data_dir / "search_corpus.json")
    chunks = law_articles(data_dir / "taiwan_law_cache", config["laws"])
    if config.get("pcces_chapters", True):
        chunks += spec_chapters(pcces_index or data_dir / "pcces_index.json")
    duplicates = [ref for ref, n in Counter(chunk.ref for chunk in chunks).items() if n > 1]
    if duplicates:
        raise ValueError(f"語料裡有重複的識別字：{sorted(duplicates)[:5]}")
    return chunks
