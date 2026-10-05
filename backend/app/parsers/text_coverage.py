"""PDF 文字覆蓋率：判斷「解析成功，但內容幾乎被圖吃掉」。

`PdfParser` 原本的守門只擋「整份文件一個字都沒有」。設計圖說會輕鬆通過那一關——
它有圖號、標題欄、比例尺，但真正有資訊的尺寸標註與構件名稱壓在點陣圖裡，抽不出來。
於是抽取器拿到一份近乎空白的輸入，產出一個乾淨的「這份文件沒有東西」。

那是「有信心的錯」，比誠實的解析失敗傷害大。這個模組不擋文件——它只負責把
「這份有多少內容沒讀到」量出來，讓人看得到。
"""

from dataclasses import dataclass

#: 一頁的可選取文字少於這個字數，就當它沒有承載內文。
MIN_PAGE_CHARS = 200

#: 「以圖為主」的頁佔比達到這個比例就標記為解析品質不佳。
#:
#: 校準自 4 份真實工程文件（2026-10-05，用本模組的量法實測）：
#:     13.施工規範              0/772    0%  ─┐ 乾淨
#:     1.契約書                 1/130  0.8%  ─┘
#:                                              ← 中間沒有樣本，門檻放哪裡都行
#:     11.施工管理要點            2/9     22%  ─┐ 有內容遺失
#:     10.建築物無障礙設施設計規範  57/105   54%  ─┘
#:
#: 門檻一度放在 25%，結果放過了 11.施工管理要點：它第 7 頁是七張道路修復圖例、
#: 第 9 頁是兩張工程告示牌規格表（法定必載欄位、尺寸、通報專線 0800-009-609），
#: 整頁抽出來只有標題 86 個字。那正是品質計畫合規檢核最需要的內容。
#:
#: 放 10%：對乾淨文件有 12 倍餘裕，對問題文件有 2.2 倍。漏報與誤報的代價不對稱——
#: 這一層不擋文件也不中斷分析，誤報只是多一行警告，漏報卻讓人拿著空結果當沒問題。
#: 樣本只有 4 份，拿到更多真實文件（特別是契約圖）要回來重新校準。
FIGURE_PAGE_RATIO = 0.10


@dataclass(frozen=True, slots=True)
class TextCoverage:
    """一份 PDF 有多少頁的內容是抽不出來的。"""

    pages: int
    figure_pages: int

    @property
    def is_degraded(self) -> bool:
        return self.pages > 0 and self.figure_pages / self.pages >= FIGURE_PAGE_RATIO

    @property
    def note(self) -> str:
        return (
            f"{self.pages} 頁裡有 {self.figure_pages} 頁以圖為主，"
            f"圖內的文字（尺寸標註、構件名稱等）未被讀取"
        )


def measure_pages(pages: list[tuple[int, bool]]) -> TextCoverage:
    """從「每頁的（文字長度, 有沒有圖）」算出覆蓋率。

    拆成這一層是為了讓 `PdfParser` 能在它既有的那一輪頁面迴圈裡順手餵資料，
    不必為了量測把檔案重開一次——`13.施工規範.pdf` 有 772 頁。
    """
    return TextCoverage(
        pages=len(pages),
        figure_pages=sum(1 for length, has_image in pages if length < MIN_PAGE_CHARS and has_image),
    )

