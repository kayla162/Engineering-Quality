"""用本案自己的用詞校正 OCR 讀出的圖名錯字。

掃描契約圖的圖名常有一個字讀錯：「梁配筋圖」讀成「又配筋圖」、「平面圖」讀成「在面圖」、「插座」讀成「插主」。
比對工項時要圖名主體的開頭兩個字出現在工項名稱裡（drawing_reader.is_related），錯一個字就整張對不到，
工項被標成「標單有、契約圖沒有」。

校正的依據是**本案標單**的工項與分項名稱（加上幾個圖面常用字），不是通用字典：
圖名裡四、五個字的一段不在詞彙裡、又和詞彙裡**恰好一個**詞只差一個字時，換成那個詞。
三個字的一段不改：證據太弱，秀山實測會把「辦公桌」「會議椅」改成「辦公室」「會議室」。
保守的地方：

- 被換掉的字要是詞彙裡完全沒出現過的（OCR 讀出來的錯字，「讚」「蕩」「芝」）；詞彙裡出現過的字不換——
  「安全監視」不會因為詞彙有「安全監控」就被改掉（「視」出現在「影視」）。
- 數字（一二三…）與方位（東西南北）不換，也不換成它們。
- 只校正 OCR 讀的圖名（DrawingSheet.is_ocr），而且**只用在比對**，存下來、顯示的圖名不改。

秀山實測（fast 模型）：三冊改了 13 個圖名（「影視對讚」->「影視對講」、「插座芝置」->「插座配置」）。
"""

import re
from collections import Counter

_CJK_RUN = re.compile(r"[一-鿿]+")
#: 換掉或換成這些字會改掉意思，不碰
_PROTECTED = set("一二三四五六七八九十東西南北上下前後左右")
#: 窗口長度：三個字以下只差一字的詞太多，六個字以上很少整段出現在標單
WINDOW_LENGTHS = (5, 4)
#: 被換掉的字在詞彙裡出現超過這個次數，就當成真的字、不換（出現過一次的真字很常見：「影視」的「視」）
MAX_SUSPECT_COUNT = 0
#: 圖面常用字：標單不一定寫，但圖名一定會出現
DRAWING_WORDS = (
    "平面圖", "立面圖", "剖面圖", "配置圖", "詳圖", "大樣圖", "系統圖", "昇位圖", "配筋圖", "標準圖",
    "結構平面圖", "配置平面圖", "一般說明", "索引表", "負載表", "單線圖",
)


class Vocabulary:
    def __init__(self, words: set[str], char_counts: Counter):
        self.words = words
        self.char_counts = char_counts
        #: 「把第 i 個字遮起來」-> 詞，用來找只差一個字的詞
        self._masked: dict[str, set[str]] = {}
        for word in words:
            for i in range(len(word)):
                self._masked.setdefault(f"{len(word)}:{word[:i]}?{word[i + 1:]}", set()).add(word)

    def one_off(self, window: str) -> list[tuple[str, int]]:
        """詞彙裡和 window 只差一個字的詞與差在哪個位置。"""
        found = []
        for i in range(len(window)):
            for word in self._masked.get(f"{len(window)}:{window[:i]}?{window[i + 1:]}", ()):
                if word != window:
                    found.append((word, i))
        return found


def vocabulary(names: list[str]) -> Vocabulary:
    """標單的工項、分項名稱（加上圖面常用字）裡所有四、五個字的連續中文，以及每個字出現的次數。"""
    texts = [*names, *DRAWING_WORDS]
    words: set[str] = set()
    chars: Counter = Counter()
    for text in texts:
        for run in _CJK_RUN.findall(text):
            chars.update(run)
            for length in WINDOW_LENGTHS:
                words.update(run[i:i + length] for i in range(len(run) - length + 1))
    return Vocabulary(words, chars)


def correct_title(title: str, vocab: Vocabulary) -> str:
    """換掉圖名裡讀錯的字；沒有把握就原樣回傳。"""
    chars = list(title)
    for length in WINDOW_LENGTHS:
        for start in range(len(chars) - length + 1):
            window = "".join(chars[start:start + length])
            if not _CJK_RUN.fullmatch(window) or window in vocab.words:
                continue
            candidates = {
                (word, i) for word, i in vocab.one_off(window)
                if _replaceable(window[i], word[i], vocab)
            }
            # 只差一個字的詞只能有一個（同一個詞不會在兩個位置都只差一個字）
            if len(candidates) != 1:
                continue
            ((word, i),) = candidates
            chars[start + i] = word[i]
    return "".join(chars)


def _replaceable(wrong: str, right: str, vocab: Vocabulary) -> bool:
    return (
        wrong not in _PROTECTED
        and right not in _PROTECTED
        and vocab.char_counts[wrong] <= MAX_SUSPECT_COUNT
    )
