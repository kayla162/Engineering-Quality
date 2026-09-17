"""golden set 的載入與計分。

用途：回答「我改了抽取規則之後，到底有沒有變準」。沒有這個，調 rule_engine 的
黑名單、補別名字典都只是憑感覺。

刻意只量抽取層（文字 -> 候選），不量整條 file -> references：
  - 要調的是抽取，解析器的問題是另一回事，混在一起會看不出是誰的錯
  - 只跑抽取的話幾毫秒就有結果，可以邊補標註邊看數字
  - 測試環境關閉 AI，所以只有規則與字典兩層被量到，數字是確定性的
    （LLM fallback 只在前兩層都沒收穫時才啟動）

標註格式見 data/golden_set/README.md。
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.extractors.base import Candidate
from app.matching.normalizer import clean_text


@dataclass(frozen=True)
class ExpectedRef:
    """標註裡的一筆「應該要抽到的引用」。article 為 None 代表不在乎條號。"""

    name: str
    article: str | None = None


@dataclass
class GoldenCase:
    case_id: str
    text: str
    expected: list[ExpectedRef]


@dataclass
class CaseScore:
    case_id: str
    matched: list[str] = field(default_factory=list)
    #: 該抽沒抽到 -> 拉低 recall
    missing: list[str] = field(default_factory=list)
    #: 抽到不該抽的 -> 拉低 precision
    spurious: list[str] = field(default_factory=list)
    #: (名稱, 標註的條號, 實際抽到的條號)。不計入 P/R，是另一種失敗模式。
    article_mismatches: list[tuple[str, str | None, str | None]] = field(default_factory=list)

    @property
    def expected_count(self) -> int:
        return len(self.matched) + len(self.missing)

    @property
    def found_count(self) -> int:
        return len(self.matched) + len(self.spurious)

    @property
    def recall(self) -> float:
        return _ratio(len(self.matched), self.expected_count)

    @property
    def precision(self) -> float:
        return _ratio(len(self.matched), self.found_count)


@dataclass
class Totals:
    expected_count: int
    found_count: int
    matched_count: int
    case_count: int

    # 這裡的空集合是 0.0，不是 1.0：完全沒有標註時報「準確度 100%」
    # 會讓人以為量過了。單一案例的「什麼都不該抽、也真的沒抽到」才是滿分。
    @property
    def recall(self) -> float:
        return _ratio(self.matched_count, self.expected_count, empty=0.0)

    @property
    def precision(self) -> float:
        return _ratio(self.matched_count, self.found_count, empty=0.0)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _ratio(hit: int, total: int, empty: float = 1.0) -> float:
    """沒有樣本時要回什麼由呼叫端決定——單一案例是滿分，整體統計是零分。"""
    return hit / total if total else empty


def _key(name: str) -> str:
    """比對用的鍵。走正式流程同一套 clean_text，全形／括號／條號差異不算錯。"""
    return clean_text(name).casefold()


def parse_expected(content: str) -> list[ExpectedRef]:
    """一行一筆：`名稱` 或 `名稱<TAB 或空白>條號`。# 開頭是註解。"""
    refs: list[ExpectedRef] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 從 Word 貼過來很容易把 TAB 變成空白，兩種都接受
        name, _, article = line.partition("\t")
        if not article:
            name, _, article = line.partition("  ")
        refs.append(ExpectedRef(name.strip(), article.strip() or None))
    return refs


def load_cases(directory: Path) -> list[GoldenCase]:
    """讀取一個目錄下所有 `<id>.txt` + `<id>.expected` 配對。

    有 .txt 沒 .expected 直接報錯：安靜跳過等於讓人以為標註做完了，
    而分數會因為樣本變少而失真。
    """
    cases: list[GoldenCase] = []
    for text_path in sorted(directory.glob("*.txt")):
        annotation = text_path.with_suffix(".expected")
        if not annotation.exists():
            raise FileNotFoundError(
                f"{text_path.name} 沒有對應的標註檔 {annotation.name}——"
                "請補上（一行一筆引用），或把文字檔移走"
            )
        cases.append(
            GoldenCase(
                case_id=text_path.stem,
                text=text_path.read_text(encoding="utf-8"),
                expected=parse_expected(annotation.read_text(encoding="utf-8")),
            )
        )
    return cases


def score_case(case: GoldenCase, candidates: list[Candidate]) -> CaseScore:
    """比對「標註說該有什麼」與「抽取器實際抽到什麼」。

    兩邊都以名稱去重：同一部法規在一段文字裡出現兩次是常態，
    不該讓分數變好或變壞。
    """
    expected = {_key(ref.name): ref for ref in case.expected}
    actual = {_key(c.raw_text): c for c in candidates}

    score = CaseScore(case_id=case.case_id)
    for key, ref in expected.items():
        candidate = actual.get(key)
        if candidate is None:
            score.missing.append(ref.name)
            continue
        score.matched.append(ref.name)
        # 標註沒寫條號 = 不在乎，讓標註成本低一點
        if ref.article is not None and ref.article != candidate.article:
            score.article_mismatches.append((ref.name, ref.article, candidate.article))

    score.spurious = [c.raw_text for key, c in actual.items() if key not in expected]
    return score


def aggregate(scores: list[CaseScore]) -> Totals:
    """用總數做 micro average，不是各案例分數再平均——
    否則只有一筆引用的案例會被放大成跟整份文件一樣重。"""
    return Totals(
        expected_count=sum(s.expected_count for s in scores),
        found_count=sum(s.found_count for s in scores),
        matched_count=sum(len(s.matched) for s in scores),
        case_count=len(scores),
    )


def format_report(scores: list[CaseScore]) -> str:
    """印出可以直接照著行動的報告：哪一案、漏了什麼、亂抽了什麼。"""
    totals = aggregate(scores)
    lines = [
        "",
        "=" * 78,
        f"抽取準確度：{totals.case_count} 個案例、{totals.expected_count} 筆標註引用",
        "=" * 78,
        f"{'案例':<26}{'漏抽':>6}{'亂抽':>6}{'條號錯':>8}{'recall':>9}{'precision':>11}",
        "-" * 78,
    ]
    for s in sorted(scores, key=lambda s: (s.recall, s.precision)):
        lines.append(
            f"{s.case_id:<26}{len(s.missing):>6}{len(s.spurious):>6}"
            f"{len(s.article_mismatches):>8}{s.recall:>9.0%}{s.precision:>11.0%}"
        )
    lines += [
        "-" * 78,
        f"{'總計':<26}{totals.expected_count - totals.matched_count:>6}"
        f"{totals.found_count - totals.matched_count:>6}{'':>8}"
        f"{totals.recall:>9.0%}{totals.precision:>11.0%}",
        f"{'':<26}{'':>6}{'':>6}{'':>8}{'F1':>9}{totals.f1:>11.0%}",
        "",
    ]

    for s in scores:
        if not (s.missing or s.spurious or s.article_mismatches):
            continue
        lines.append(f"[{s.case_id}]")
        for name in s.missing:
            lines.append(f"  漏抽    {name}")
        for name in s.spurious:
            lines.append(f"  亂抽    {name}    <- 補 rule_engine.py 的黑名單")
        for name, want, got in s.article_mismatches:
            lines.append(f"  條號錯  {name}：標註 {want}，抽到 {got}")
        lines.append("")
    return "\n".join(lines)
