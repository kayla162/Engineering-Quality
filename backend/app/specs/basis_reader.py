"""章節裡「1.4 相關準則」區塊的定位。

為什麼只取這一段而不是整章：整章內文裡會順帶提到別的規範（施工方法描述、
相關章節交叉引用），抽起來是雜訊。「1.4 相關準則」是規範書自己宣告的依據清單。

實測本案規範書 86 章裡 75 章有此宣告，共 1237 筆依據記錄。
標準沒有資料來源可查證，只引述——這個判斷在 service 層依 `RegulationType` 做，不在這裡。
"""

import re

#: 1.d 相關準則（d 可能是 1-9，不限於 1.4）... 直到下一個 1.d 小節、2. 產品、或文本結尾為止。
#: 使用 (?<!\S) 確保小節號在字邊界（不在數字或文字中間）。可能有多個相關準則區塊。
_BLOCK = re.compile(
    r"(?<!\S)1\.\d+\s*相關準則(.*?)(?=(?<!\S)1\.\d+\s|(?<!\S)2\.\s*產品|$)", re.S
)


def basis_block(chapter_text: str) -> str | None:
    """切出章節裡宣告依據的那一段。沒有這一段就回 None。

    可能有多個相關準則區塊（同一個小節號重複或不同小節號），
    此函數整合所有區塊。
    """
    blocks = []
    for match in _BLOCK.finditer(chapter_text):
        block = match.group(1).strip()
        if block:
            blocks.append(block)

    if not blocks:
        return None

    return " ".join(blocks)
