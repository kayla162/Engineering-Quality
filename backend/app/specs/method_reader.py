"""工法欄（檢核表階段 4）：施工規範列出多種工法時要選，契約文件寫了哪一種。

spec 第 7 節拆成兩個判斷：

1. **要不要選**：施工規範同一章寫「得採用下列工法之一：(1) 鋼模 (2) 木模」這類句子，
   列出兩種以上，就是要選。
2. **選了哪一種**：契約文件（契約書、需求書等附件）的文字裡**恰好出現一種**選項 -> 填它。
   出現零種或兩種以上 -> 不猜，填「未指定」，交給人看圖（呼叫端附上相關圖號）。

不從圖面猜工法：圖面內容系統讀不懂，猜出來的是「有信心的錯」。

**用真實規範校正過（2026-11）**：秀山分隊的施工規範（772 頁）一次都沒有寫「得採用下列工法之一」，
舊版整本讀到 0 筆。它沿用工程會綱要規範的慣例，用方括號列出設計單位該挑的選項，所以另外認三種寫法：

- 「選擇下列控制方式之一：[單台…][群管理…]」——「下列…之一」接方括號清單
- 「開挖施工方式得採[人工開挖]或[機械開挖]」——講做法的句子裡用「或」連接的方括號
- 「鋼筋之續接，應依下列規定辦理。(1) 搭接 … (2) 銲接 … (3) 機械式續接」——每節一種做法

只讀「3. 施工」節（construction_part）。方括號裡是標準編號（[CNS 1364]）或數值（[20%]）的不算，
沒講做法的「[鋼質]或[鐵質]」也不算：那是依據、規格與材料，不是工法。秀山規範整本讀到的
選項只有鋼筋續接一組。
"""

import re
from dataclasses import dataclass

#: 引出選項清單的句型
_OPTIONS_INTRO = re.compile(r"(?:得|可|應)?(?:採用|選用|採)下列(?:工法|施工方法|方法)之一\s*[:：]?")
#: 選項編號：(1) （1） 1.
_OPTION_MARK = re.compile(r"[（(]\s*\d+\s*[)）]|(?<![\d.])\d+\.(?!\d)")
#: 選項清單最多讀到這裡：句號、下一個小節編號（「3.4」），或 200 字
_LIST_END = re.compile(r"。|\s\d+\.\d+\s")

_BRACKET = r"\[[^\[\]]{1,25}\]"
_BRACKET_TEXT = re.compile(r"\[([^\[\]]{1,25})\]")
#: 「選擇下列控制方式之一：[A][B]」
_ONE_OF_BRACKETS = re.compile(rf"下列[^。：:\[]{{0,8}}之一種?\s*[:：]?\s*(?P<list>(?:{_BRACKET}\s*){{2,}})")
#: 「可採用[A][B]或[C]」
_BRACKETS_OR = re.compile(rf"(?P<list>(?:{_BRACKET}\s*){{1,6}}或\s*{_BRACKET})")
#: 「[A]或[B]」前面要有這些字，才是在講做法
_METHOD_WORDS = re.compile(r"工法|施工方法|方式|做法|作法")
#: 方括號裡是標準編號或數值：依據與規格，不是做法
_NOT_A_METHOD = re.compile(r"CNS|ASTM|ISO|JIS|IEC|AWS|ACI|\d")
#: 「鋼筋之續接，應依下列規定辦理。(1) 搭接 … (2) 銲接 …」，讀到下一個小節（「3.2.4」）為止
_SECTIONS_INTRO = re.compile(r"(?:續接|接合|工法|施工方法)[^。]{0,6}應依下列規定辦理。?")
_SECTIONS_END = re.compile(r"\s\d+\.\d+\.\d+\s")
_SECTION_HEADING = re.compile(r"[（(]\s*\d+\s*[)）]\s*(?P<heading>[^\s(（]{2,12})")
_HEADING_TAIL = re.compile(r"(?:施工要求|規定|作業)$")
_CJK_GAP = re.compile(r"(?<=[一-鿿])\s+|\s+(?=[一-鿿])")
#: 綱要規範的節標題：「3. 施工」「4. 計量與計價」
_PART_CONSTRUCTION = re.compile(r"(?:^|\s)3\.\s*施\s*工(?:\s|$)")
_PART_MEASUREMENT = re.compile(r"(?:^|\s)4\.\s*計\s*量")


@dataclass(frozen=True)
class MethodChoice:
    options: list[str]
    #: 契約文件指定的工法；None = 未指定
    selected: str | None
    #: 指定的出處（文件名稱與前後文），或未指定的原因
    evidence: str | None


def method_options(chapter_text: str) -> list[str]:
    """這一章列出的工法選項。不到兩種就不算「要選」，回傳空清單。四種寫法依序找，先找到的算。"""
    text = construction_part(chapter_text or "")
    for reader in (_numbered_after_intro, _one_of_brackets, _sections, _brackets_or):
        options = list(dict.fromkeys(reader(text)))
        if len(options) >= 2:
            return options
    return []


def construction_part(chapter_text: str) -> str:
    """章裡「3. 施工」到「4. 計量與計價」之間；章沒有分節標題時回傳整章。

    工法是施工方法。「2. 產品」的方括號是材料、設備的選擇（[燈泡]或[LED]），不是工法——
    秀山規範 86 章裡有 72 章分節，原本讀到的 7 章選項有 6 章出自「2. 產品」。
    """
    start = _PART_CONSTRUCTION.search(chapter_text)
    if start is None:
        return chapter_text
    end = _PART_MEASUREMENT.search(chapter_text, start.end())
    return chapter_text[start.end(): end.start() if end else None]


def _numbered_after_intro(text: str) -> list[str]:
    intro = _OPTIONS_INTRO.search(text)
    if intro is None:
        return []
    rest = text[intro.end(): intro.end() + 200]
    end = _LIST_END.search(rest)
    block = rest[: end.start()] if end else rest
    parts = [p.strip(" ，,、；;") for p in _OPTION_MARK.split(block)]
    return [p for p in parts if 1 < len(p) <= 20]


def _bracket_options(block: str) -> list[str]:
    # PDF 斷行會在中文字之間留空白（「錨碇螺 栓」）；英文字之間的空白要留（「Shaded Pole Type」）
    options = [_CJK_GAP.sub("", o).strip() for o in _BRACKET_TEXT.findall(block)]
    return [] if any(_NOT_A_METHOD.search(o) for o in options) else [o for o in options if o]


def _one_of_brackets(text: str) -> list[str]:
    match = _ONE_OF_BRACKETS.search(text)
    return _bracket_options(match["list"]) if match else []


def _brackets_or(text: str) -> list[str]:
    """「[A]或[B]」只有在講做法的句子裡才算：「施工」節裡也有材料選擇（螺栓[鋼質]或[鐵質]）。"""
    for match in _BRACKETS_OR.finditer(text):
        sentence_start = max(text.rfind(mark, 0, match.start()) for mark in "。；;\n") + 1
        if not _METHOD_WORDS.search(text[sentence_start: match.start()]):
            continue
        if options := _bracket_options(match["list"]):
            return options
    return []


def _sections(text: str) -> list[str]:
    intro = _SECTIONS_INTRO.search(text)
    if intro is None:
        return []
    rest = text[intro.end(): intro.end() + 3000]
    end = _SECTIONS_END.search(rest)
    block = rest[: end.start()] if end else rest
    return [_HEADING_TAIL.sub("", m["heading"]) for m in _SECTION_HEADING.finditer(block)]


def choose_method(options: list[str], contract_texts: list[tuple[str, str]]) -> MethodChoice:
    """在契約文件裡找選了哪一種。contract_texts 是 [(文件名稱, 全文)]。"""
    found: dict[str, str] = {}
    for filename, text in contract_texts:
        for option in options:
            position = text.find(option)
            if position >= 0 and option not in found:
                snippet = text[max(0, position - 15): position + len(option) + 15].replace("\n", " ")
                found[option] = f"{filename}：「…{snippet}…」"
    if len(found) == 1:
        option, evidence = next(iter(found.items()))
        return MethodChoice(options, option, evidence)
    if len(found) > 1:
        return MethodChoice(options, None, f"契約文件同時提到 {'、'.join(found)}，無法判斷採用哪一種")
    return MethodChoice(options, None, "契約文件沒有提到採用哪一種工法")
