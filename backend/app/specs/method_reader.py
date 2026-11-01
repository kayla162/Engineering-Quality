"""工法欄（檢核表階段 4）：施工規範列出多種工法時要選，契約文件寫了哪一種。

spec 第 7 節拆成兩個判斷：

1. **要不要選**：施工規範同一章寫「得採用下列工法之一：(1) 鋼模 (2) 木模」這類句子，
   列出兩種以上，就是要選。
2. **選了哪一種**：契約文件（契約書、需求書等附件）的文字裡**恰好出現一種**選項 -> 填它。
   出現零種或兩種以上 -> 不猜，填「未指定」，交給人看圖（呼叫端附上相關圖號）。

不從圖面猜工法：圖面內容系統讀不懂，猜出來的是「有信心的錯」。

**以示範資料驗證。** 真實規範書的寫法可能不同（「得採下列方式」「承包商可選擇」），
拿到真實文件要回來補 _OPTIONS_INTRO 的寫法。
"""

import re
from dataclasses import dataclass

#: 引出選項清單的句型
_OPTIONS_INTRO = re.compile(r"(?:得|可|應)?(?:採用|選用|採)下列(?:工法|施工方法|方法)之一\s*[:：]?")
#: 選項編號：(1) （1） 1.
_OPTION_MARK = re.compile(r"[（(]\s*\d+\s*[)）]|(?<![\d.])\d+\.(?!\d)")
#: 選項清單最多讀到這裡：句號、下一個小節編號（「3.4」），或 200 字
_LIST_END = re.compile(r"。|\s\d+\.\d+\s")


@dataclass(frozen=True)
class MethodChoice:
    options: list[str]
    #: 契約文件指定的工法；None = 未指定
    selected: str | None
    #: 指定的出處（文件名稱與前後文），或未指定的原因
    evidence: str | None


def method_options(chapter_text: str) -> list[str]:
    """這一章列出的工法選項。不到兩種就不算「要選」，回傳空清單。"""
    intro = _OPTIONS_INTRO.search(chapter_text or "")
    if intro is None:
        return []
    rest = chapter_text[intro.end(): intro.end() + 200]
    end = _LIST_END.search(rest)
    block = rest[: end.start()] if end else rest
    parts = [p.strip(" ，,、；;") for p in _OPTION_MARK.split(block)]
    options = [p for p in parts if 1 < len(p) <= 20]
    return list(dict.fromkeys(options)) if len(options) >= 2 else []


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
