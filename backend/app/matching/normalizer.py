"""正規化引擎：把文件裡的寫法轉成可以拿去比對的標準寫法。

兩個步驟：
1. 文字清理（全形轉半形、去掉書名號、去掉條號、統一標準編號寫法）
2. 別名查表（「採購法」-> 「政府採購法」）

別名資料來自 data/alias_dictionary.json，補別名不需要改程式碼。
"""

import re
import unicodedata
from dataclasses import dataclass

from app.extractors.dictionary_extractor import load_alias_entries

# 名稱前後常見的雜訊
_BRACKETS = str.maketrans({c: "" for c in "《》〈〉「」『』【】()（）"})
_ARTICLE_SUFFIX = re.compile(r"第\s*[0-9０-９一二三四五六七八九十百千]+\s*(?:條|項|款|目).*$")
_STANDARD_PREFIX = re.compile(
    r"^(CNS|ISO|IEC|ASTM|JIS|EN|ANSI|BS|DIN|AASHTO|ACI|AWS|API|UL|NFPA)[\s\-]*",
    re.IGNORECASE,
)


@dataclass(slots=True)
class NormalizationResult:
    normalized_name: str
    reasons: list[str]
    #: 是否命中別名字典（命中代表這是高可信度的對應）
    matched_alias: bool = False


def clean_text(text: str) -> str:
    """純文字清理，不查字典。抽取器與比對引擎共用同一套規則。"""
    # 全形英數轉半形（CNS５６０ -> CNS560）
    cleaned = unicodedata.normalize("NFKC", text).strip()
    cleaned = cleaned.translate(_BRACKETS)
    cleaned = _ARTICLE_SUFFIX.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 標準編號統一成「機構 編號」的寫法：CNS560 / CNS-560 -> CNS 560
    match = _STANDARD_PREFIX.match(cleaned)
    if match:
        rest = cleaned[match.end():].strip()
        cleaned = f"{match.group(1).upper()} {rest}".strip()
    return cleaned


class NormalizationEngine:
    def __init__(self, alias_entries=None):
        entries = alias_entries if alias_entries is not None else load_alias_entries()
        # 清理過的別名 -> 官方全名
        self._alias_map: dict[str, str] = {
            clean_text(entry.term).casefold(): entry.canonical for entry in entries
        }

    def normalize(self, raw_text: str) -> NormalizationResult:
        cleaned = clean_text(raw_text)
        reasons: list[str] = []

        canonical = self._alias_map.get(cleaned.casefold())
        if canonical and canonical != cleaned:
            reasons.append(f"別名字典：「{cleaned}」對應「{canonical}」")
            return NormalizationResult(canonical, reasons, matched_alias=True)
        if canonical:
            reasons.append("名稱與字典中的官方全名一致")
            return NormalizationResult(canonical, reasons, matched_alias=True)

        if cleaned != raw_text.strip():
            reasons.append("已正規化文字格式")
        return NormalizationResult(cleaned, reasons)
