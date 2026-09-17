"""抽取器的共同輸出格式。

Rule / Dictionary / NER / LLM 四層抽取器都回傳同一種 Candidate，
由 pipeline 決定要不要往下一層送。這樣新增一層抽取器不會影響其他層。
"""

from dataclasses import dataclass, field

from app.core.enums import ExtractionMethod, RegulationType


@dataclass(slots=True)
class Candidate:
    """從一段文字裡抽出的一個法規引用候選。"""

    raw_text: str
    regulation_type: RegulationType
    method: ExtractionMethod
    confidence: float = 1.0
    article: str | None = None
    standard_number: str | None = None
    # 在原始段落中的字元位置，用來去除不同抽取器抽到的重複候選
    start: int = 0
    end: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)


# 同分時的優先順序：字典命中的名稱最精確，其次是規則，最後才是 LLM
_METHOD_PRIORITY = {
    ExtractionMethod.DICTIONARY: 0,
    ExtractionMethod.REGEX: 1,
    ExtractionMethod.NER: 2,
    ExtractionMethod.LLM_FALLBACK: 3,
}


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """去重：位置重疊或名稱相同的候選只留一筆。

    被淘汰的候選如果帶有條號或標準編號，會併到保留的那一筆，
    這樣「字典抽到精確名稱、規則抽到條號」的情況不會漏掉條號。
    """
    # 排序決定重疊時誰留下：**先看誰把名稱讀得比較完整，再看哪一層比較可信**。
    #
    # `-c.end` 排在 confidence 前面，因為法規名稱的**結尾**決定它是哪一部法規，
    # 開頭的雜訊才是可以剝掉的：
    #   「計畫依政府採購法」vs「政府採購法」        -> 結尾相同，字典那筆較精確，字典勝
    #   「建築技術規則建築構造編」vs「建築技術規則」 -> 前者結尾較晚，較完整的那筆勝
    #
    # 一般情況兩者結尾相同，所以實際決定權仍在 confidence 與來源優先序；
    # 只有「某一層把名稱讀短了」時 -c.end 才會發揮作用。
    #
    # 少了它的話：規則引擎抽到的獨立法規「建築技術規則建築構造編」（信心 0.9）
    # 會被字典命中的「建築技術規則」（信心 1.0）截短。字典對「這是法規」很有把握，
    # 但它有把握的是一個**被截短的錯名稱**——結果是高信心地對到錯誤的法規，
    # 比漏抽嚴重。信心講的是「像不像法規」，不是「名稱完不完整」。
    ordered = sorted(
        candidates,
        key=lambda c: (-c.end, -c.confidence, _METHOD_PRIORITY[c.method], len(c.raw_text), c.start),
    )
    kept: list[Candidate] = []
    for candidate in ordered:
        clash = next(
            (
                k
                for k in kept
                if (candidate.start < k.end and k.start < candidate.end)
                or candidate.raw_text == k.raw_text
            ),
            None,
        )
        if clash is None:
            kept.append(candidate)
        else:
            clash.article = clash.article or candidate.article
            clash.standard_number = clash.standard_number or candidate.standard_number
    return sorted(kept, key=lambda c: c.start)
