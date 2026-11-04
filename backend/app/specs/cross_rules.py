"""法規雙重規範提醒：同一個構件同時受兩部以上規定約束、要一起滿足的情形。

邏輯圖：「法規可 google『建築人』參考，需注意有無雙重規範（如頂樓 RC 欄杆要 1.1m，超過 1.5m 會被納入樓高）」。
系統讀不懂條文之間的牽動，所以用一份目錄（data/cross_rules.json）：每條有觸發詞，本案標單工項或契約圖圖名
出現觸發詞就提醒，並引出是哪幾項觸發的。

目錄是**示範**：只有使用者給的那一條有出處，其餘條號與數值未查證，每筆 provenance 寫明。這是提醒，
不是檢核結果——不影響任何工項的判定。
"""

import json
from dataclasses import dataclass, field
from functools import cache

from app.core.config import settings

MAX_EVIDENCE = 3


@dataclass(frozen=True)
class CrossRuleReminder:
    rule_id: str
    title: str
    regulations: list[str]
    note: str
    provenance: str
    #: 觸發的前幾項（「標單：壹.一.1.4.20 …」）
    evidence: list[str] = field(default_factory=list)
    #: 觸發的總項數
    matches: int = 0


@cache
def _rules_from(path: str) -> tuple:
    with open(path, encoding="utf-8") as file:
        return tuple(json.load(file)["rules"])


def load_cross_rules() -> list[dict]:
    return list(_rules_from(str(settings.DATA_DIR / "cross_rules.json")))


def remind(texts: list[tuple[str, str]]) -> list[CrossRuleReminder]:
    """texts 是（來源, 內容），例如（「標單」,「壹.一.1.4.20 露台.屋頂沿女兒牆…」）。依目錄順序回傳被觸發的提醒。"""
    reminders = []
    for rule in load_cross_rules():
        hits = [f"{source}：{text}" for source, text in texts if any(word in text for word in rule["triggers"])]
        if hits:
            reminders.append(
                CrossRuleReminder(
                    rule_id=rule["id"],
                    title=rule["title"],
                    regulations=list(rule["regulations"]),
                    note=rule["note"],
                    provenance=rule["provenance"],
                    evidence=hits[:MAX_EVIDENCE],
                    matches=len(hits),
                )
            )
    return reminders
