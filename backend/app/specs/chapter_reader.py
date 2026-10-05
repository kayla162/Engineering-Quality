"""施工規範書的章節切分。

真實規範書的形狀（本案 13.施工規範.pdf，2026-10-05 查證）：
    772 頁、86 章，每頁頁首是 `<組碼> <章碼>-<頁次> V<版本> <日期>`

        01725 01725-1 V3.0 2013/01/10     組碼與章碼相同
        05500 05503-1 V5.0 2020/08/19     組碼與章碼不同，章碼是 05503

    章名在頁首後面：`第01725 章V3.0` 的下一行是 `施工測量`（寫法不只一種，見 `_TITLE`）

兩個關鍵設計：

1. **不要求每一頁都符合頁首格式。** 實測 748/772 頁（97%）符合，剩下的是封面
   目錄與跨頁大表。沒有頁首的頁歸給前一頁的章節——它們是延續頁。把 regex 調到
   100% 比這條規則脆弱得多。

2. **切不出任何章節要報錯。** 安靜回空清單的結果，是一張全部「請確認依據」的
   檢核表，看起來像「這個案子沒有依據」，實際是「我們沒讀懂規範書」。
   和 `boq_reader` 找不到表頭要報錯是同一條原則。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.core.errors import UnprocessableDocumentError

#: 頁首：<組碼> <章碼>-<頁次> V<版本>。章碼是第二組，不是第一組。
_HEADER = re.compile(r"^(\d{5})\s+(\d{5})-(\d+)\s+V([\d.]+)")

#: 章名行：`第<章碼> 章` 後面接版本與章名。實測 86 章有三種寫法：
#:     第01725 章V3.0 ⏎ 施工測量      章名在下一行（74 章）
#:     第02220 章 ⏎ 工地拆除          章名行沒有版本（11 章）
#:     第16742 章 V 1.0 ⏎ 數據網路…   版本中間有空白（1 章）
#: 第一組抓章碼：內文的交叉參照也長得像（`第01330 章--資料送審`），
#: 要靠章碼是不是本章的，才分得出哪一行是章名。
_TITLE = re.compile(r"第\s*(\d{5})\s*章(?:\s*V\s*[\d.]+)?\s*(\S[^\n]*)")


class SpecFormatError(UnprocessableDocumentError):
    """施工規範書格式不符預期。"""


@dataclass(slots=True)
class SpecChapterRow:
    code: str
    title: str
    version: str
    first_page: int
    last_page: int
    pages: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """整章的內文，空白已正規化——「1.4 相關準則」可能跨行。"""
        return " ".join(" ".join(self.pages).split())


def read_spec_chapters(path: Path) -> list[SpecChapterRow]:
    """把施工規範書切成章節。"""
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise SpecFormatError(f"無法開啟施工規範書：{exc}") from exc

    rows: list[SpecChapterRow] = []
    try:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text()
            header = _HEADER.match(" ".join(text.split()[:4]))
            if header is None:
                # 延續頁：歸給前一章。還沒有任何一章時（封面、目錄）直接略過。
                if rows:
                    rows[-1].pages.append(text)
                    rows[-1].last_page = page_index
                continue

            code, version = header.group(2), header.group(4)
            if rows and rows[-1].code == code:
                rows[-1].pages.append(text)
                rows[-1].last_page = page_index
                continue

            # 章名要在保留換行的原文上找：_TITLE 靠行尾判斷章名在哪裡結束，
            # 空白正規化後整頁變成一行，章名會一路吃到頁尾。找不到本章的章名行
            # 就留空，不要拿交叉參照湊數。
            title = next(
                (match.group(2).strip() for match in _TITLE.finditer(text) if match.group(1) == code),
                "",
            )
            rows.append(
                SpecChapterRow(
                    code=code,
                    title=title,
                    version=version,
                    first_page=page_index,
                    last_page=page_index,
                    pages=[text],
                )
            )
    finally:
        document.close()

    if not rows:
        raise SpecFormatError(
            "施工規範書裡找不到任何章節頁首（預期格式：章碼 章碼-頁次 V版本）"
        )
    return rows
