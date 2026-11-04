"""檢核表的「契約」欄：契約書裡提到工項（或它所屬分項）的地方。

秀山的契約書（工程會範本、Word 轉 PDF）條號是自動編號，PDF 文字層裡沒有「第一條」——
實測 2335 段只抽得到兩處「第五條附件」。所以出處只寫**頁碼與前面最近的小標題**
（每條開頭的「假設工程之組立及拆除：一、…」），不推算條號：數錯一條比不寫更糟。

這是「契約提到這裡」，不是「契約對這個工項有特別規定」——列出來讓人去看，不影響檢核結果。
"""

import re
from dataclasses import dataclass

from app.parsers.base import ParsedSection

#: 一條的開頭：「工程品質： 一、」「施工計畫與報表：」（換段）「…：(一)」
_HEADING = re.compile(r"(?:^|。|\s)([^\s：:，。；;、()（）「」]{2,20})[：:]\s*(?=一、|[（(]一[)）]|$)")
#: 長得像標題、其實不是：句子（「本契約包括下列文件：」）與附件表格的欄名（「工程名稱：」「審查日期：」）
_SENTENCE = re.compile(r"下列|如下|應|得|情形|之一|名稱|日期|文號|編號|簽名|戳章|備註|項目|結果|說明|人員")
_CJK = re.compile(r"[一-鿿]")
#: 分項名稱的字尾：「開關箱設備工程」->「開關箱」
_SECTION_TAIL = re.compile(r"(?:設備工程|設施工程|工程|設備|設施|作業)$")
#: 太泛、找到也沒有意義的詞。標單名稱第一段常是這種分類（「產品，乾粉滅火器」），主體在第二段
_GENERIC = {
    "其他", "雜項", "工程", "設備", "材料", "施工", "一般", "零星", "產品", "施工費", "安裝費",
    "工資", "工料", "費用", "處理", "工作", "設施", "裝修", "安裝", "運費", "運雜費",
}
#: 修飾語：「預拌混凝土」也要找「混凝土」、「普通模板」也要找「模板」
_MODIFIER = re.compile(r"^(?:普通|清水|一般|預拌|場鑄|新設|臨時|室內|室外|戶外|鋼製|鋁製)")
_BRACKET = re.compile(r"[()（）\[\]]")
MAX_MENTIONS = 3
EXCERPT = 80


@dataclass(frozen=True)
class Passage:
    page: int | None
    heading: str | None
    text: str


@dataclass(frozen=True)
class Mention:
    page: int | None
    heading: str | None
    excerpt: str


def contract_passages(sections: list[ParsedSection]) -> list[Passage]:
    """每一段，連同它所在的頁碼與前面最近的一條標題。"""
    passages = []
    heading = None
    for section in sections:
        text = section.content.strip()
        for match in _HEADING.finditer(text):
            title = match.group(1)
            # 兩個字的只在段首才算：段落中間的「期間：」「設施：」多半是斷行切出來的半截
            if not _SENTENCE.search(title) and (len(title) >= 3 or match.start() == 0):
                heading = title
                break
        passages.append(Passage(section.page, heading, text))
    return passages


def mentions(keyword: str, passages: list[Passage]) -> list[Mention]:
    """提到這個詞的前三處，依契約順序。"""
    found = []
    for passage in passages:
        position = passage.text.find(keyword)
        if position < 0:
            continue
        start = max(0, position - (EXCERPT - len(keyword)) // 2)
        excerpt = passage.text[start: start + EXCERPT]
        found.append(Mention(passage.page, passage.heading, excerpt))
        if len(found) == MAX_MENTIONS:
            break
    return found


def item_keywords(item_name: str, sections: list[str]) -> list[str]:
    """拿去契約裡找的詞：工項主體（逗號前；第一段是「產品」「施工費」這類分類時取下一段）、
    去掉修飾語的主體，再來是所屬分項的主體。

    「普通模板，…」->「普通模板」「模板」；「產品，乾粉滅火器」->「乾粉滅火器」；
    「KW-MP PANEL」只剩分項「開關箱」。
    """
    segments = [part.strip() for part in re.split(r"[，,]", item_name) if part.strip()]
    subject = next((part for part in segments if part not in _GENERIC), "")
    candidates = [subject, _MODIFIER.sub("", subject)]
    for name in sections:
        core = _SECTION_TAIL.sub("", name.strip())
        # 「衛生設備工程」只剩「衛生」會對到「職業安全衛生」；兩個字太短時留到「衛生設備」
        candidates.append(core if len(core) > 2 else re.sub(r"工程$", "", name.strip()))
    keywords = []
    for word in candidates:
        if (
            len(word) >= 2
            and _CJK.search(word)
            and not _BRACKET.search(word)
            and word not in _GENERIC
            and word not in keywords
        ):
            keywords.append(word)
    return keywords
