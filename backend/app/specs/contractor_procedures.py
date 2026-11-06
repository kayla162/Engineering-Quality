"""承攬廠商品質管理程序範本（data/contractor_procedures.json）。

整體品質計畫、監造計畫初稿裡系統產生不了的組織與程序章節，先用同一營造廠在另案服務建議書寫的品質管理
程序（三級品管權責、材料設備檢驗步驟、檢驗停留點、不合格品管制…）補上，每段標「【承攬廠商範本】」。
範本沒涵蓋的部分（still_blank）仍留「（待填）」，示範補正模式才用示範文字補。
"""

import json
from dataclasses import dataclass
from functools import cache

from app.core.config import settings


@dataclass(frozen=True)
class ProcedureSection:
    paragraphs: list[str]
    #: 範本沒涵蓋、仍要使用者填的部分；None 代表這一章範本已經涵蓋
    still_blank: str | None = None


@cache
def _data() -> dict:
    with open(settings.DATA_DIR / "contractor_procedures.json", encoding="utf-8") as file:
        return json.load(file)


def provenance() -> str:
    return f"{_data()['mark']}：{_data()['provenance']}。"


def sections(kind: str) -> dict[str, ProcedureSection]:
    """kind：quality（整體品質計畫）或 supervision（監造計畫）。段落已加上「【承攬廠商範本】」。"""
    data = _data()
    return {
        heading: ProcedureSection(
            paragraphs=[f"{data['mark']}{text}" for text in section["paragraphs"]],
            still_blank=section.get("still_blank"),
        )
        for heading, section in data[f"{kind}_plan"].items()
    }
