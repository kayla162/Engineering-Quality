"""章節裡「1.4 相關準則」區塊的定位。

為什麼只取這一段而不是整章：整章內文裡會順帶提到別的規範（施工方法描述、
相關章節交叉引用），抽起來是雜訊。「1.4 相關準則」是規範書自己宣告的依據清單。

實測本案規範書 86 章裡 74 章有這一段；抽出 1220 筆，其中 739 筆是標準
（CNS/ASTM/AWS）、481 筆是法規。標準沒有資料來源可查證，只引述——
這個判斷在 service 層依 `RegulationType` 做，不在這裡。
"""

import re

#: 1.4 相關準則 ... 直到 1.5 或 2. 產品 為止
_BLOCK = re.compile(r"1\.4\s*相關準則(.*?)(?=1\.5\s|2\.\s*產品|$)", re.S)


def basis_block(chapter_text: str) -> str | None:
    """切出章節裡宣告依據的那一段。沒有這一段就回 None。"""
    match = _BLOCK.search(chapter_text)
    if match is None:
        return None
    block = match.group(1).strip()
    return block or None
