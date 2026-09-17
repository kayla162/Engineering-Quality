"""規則式抽取：正規表示式 + 關鍵字尾。

這是抽取的第一層，也是主力。設計原則是「寧可漏抽，不要亂抽」：
規則抽到的候選 extraction_confidence 給高分，模糊的部分交給後面的層與人工覆核。

要調整抽取行為，改這個檔案上方的幾張表就好，不需要動下面的邏輯：
  _SUFFIX_TYPES      ：中文法規名稱的字尾 -> 法規類型
  _EXACT_BLOCKLIST   ：整個字串就是泛稱，不是法規名稱（「施工規範」）
  _SUFFIX_BLOCKLIST  ：以這些字結尾的是日常用語（「施工方法」）
  _INTERNAL_CUT      ：句子裡的連接詞，用來切掉名稱前面多抓到的部分
  _STANDARD_ORGS     ：標準編號的發行機構代號
"""

import re

from app.core.enums import ExtractionMethod, RegulationType
from app.extractors.base import Candidate

# 中文法規名稱的字尾 -> 法規類型。順序重要：長的字尾要排在短的前面。
_SUFFIX_TYPES: dict[str, RegulationType] = {
    "條例": RegulationType.LAW,
    "施行細則": RegulationType.REGULATION,
    "細則": RegulationType.REGULATION,
    "辦法": RegulationType.REGULATION,
    "規則": RegulationType.REGULATION,
    "準則": RegulationType.REGULATION,
    "規範": RegulationType.ENGINEERING_SPEC,
    "標準": RegulationType.STANDARD,
    "要點": RegulationType.ANNOUNCEMENT,
    "綱要": RegulationType.ANNOUNCEMENT,
    "須知": RegulationType.CONTRACT_SPEC,
    "法": RegulationType.LAW,
}

# 「法」結尾的日常用語。它們既可能整個字就是（「無法」），也可能結在一段句子後面
# （「無法取得者應設法補正」）——所以「完全相等」與「結尾」兩張表都要收。
# 只放進其中一張的話，句子片段就會被當成法規名稱抽出來。
_EVERYDAY_LAW_WORDS: tuple[str, ...] = (
    "無法", "依法", "合法", "違法", "立法", "司法", "執法", "守法", "設法", "取法",
    "本法", "該法", "此法",
)

# 完全等於這些字的不是法規名稱，而是泛稱（「本節說明施工規範」不是在引用某部規範）
_EXACT_BLOCKLIST: frozenset[str] = frozenset(
    {
        # 單獨出現的字尾
        "標準", "規範", "規則", "準則", "要點", "須知", "辦法", "細則", "條例", "綱要",
        *_EVERYDAY_LAW_WORDS,
        # 沒有冠上主體的泛稱
        "施工規範", "技術規範", "設計規範", "檢驗規範", "相關規範",
        "作業要點", "施工要點", "管理辦法", "施行細則", "作業規定", "施工標準",
        # 「符合國家標準 CNS 4750 規定」——該抽的是編號，不是「國家標準」四個字。
        # 只擋完全相等，「中華民國國家標準」這種冠了主體的不受影響。
        "國家標準", "國際標準",
    }
)

# 以這些字結尾的是日常用語，不是法規名稱（「施工方法」「材料檢驗標準」）
_SUFFIX_BLOCKLIST: tuple[str, ...] = (
    "方法", "作法", "做法", "說法", "想法", "看法", "用法", "手法", "工法", "章法",
    "演算法", "算法", "語法", "文法", "療法",
    "檢驗標準", "驗收標準", "品質標準", "施工標準",
    # 從「相關技術法規」「五大管線相關法令等」切出來的半截詞。
    # 不能改用「法後面不接規/令」的前瞻——「政府採購法規定」會一起被擋掉。
    "相關法", "技術法",
    *_EVERYDAY_LAW_WORDS,
)

# 句子裡的連接詞。正規表示式常會從連接詞前面就開始比對
# （例如「本計畫依政府採購法」），這裡取「最後一個連接詞之後」的部分作為名稱。
_INTERNAL_CUT = re.compile(
    r"^.*(?P<conn>依據|依照|依循|依|應|得|須|需|按照|按|參照|參考|遵照|遵守|符合|適用|"
    # 疑問詞跟連接詞在這裡的作用一樣：它前面那段一定是句子，不是名稱
    # （「施工計畫內容是否規範」）。沒有任何法規名稱含這些詞。
    r"是否|如何|有無|能否|"
    r"辦理|訂定|援引|及|與|或|暨|等|之|為|由|並|另|如)"
)

# 名稱字尾在中間、後面接一小段補充的情況：「建築物耐震設計規範及解說」。
# 型別要看補充前面那段（規範），不是最後兩個字。
_TRAILING_TAIL = re.compile(rf"(?:及|與|暨)[{'一-鿿'}]{{1,4}}$")

# 名稱前面剩下的零星贅字。多字詞排在單字前面，才不會只剝掉一個字。
_LEADING_NOISE = re.compile(
    r"^(?:本節|本章|本項|本款|本表|本圖|前項|次項|附錄|"
    r"相關|有關|上開|前開|前述|各項|所有|說明|敘明|載明|規定|"
    r"本|該|其|係|以|請)+"
)

# 法規名稱不會以連接詞開頭。「依據規範」是表格標題，不是法規名稱。
_STARTS_WITH_CONNECTIVE = re.compile(
    r"^(?:依據|依照|依循|依|應|得|須|需|按照|按|參照|參考|遵照|遵守|符合|適用|"
    r"及|與|或|暨|等|之|為|由|並|另)"
)

# 中文法規名稱：一段中文（可含數字/英文）+ 認得的字尾 + 可選的「編」+ 可接條號
_CJK = r"一-鿿"

# 法規的「編」層級，例如「建築技術規則建築構造編」。官方資料庫把各編當成**獨立法規**
# （見 data/alias_dictionary.json 的註解），所以它是名稱的一部分，不是條號。
#
# 沒有這一段的話，名稱比對是非貪婪的，會停在第一個認得的字尾（「建築技術規則」），
# 把「建築構造編」丟掉——結果是高信心地對到錯誤的法規，比漏抽嚴重。
#
# 只吃緊接在字尾後面、8 個字以內、且真的以「編」結尾的一段；
# 「依政府採購法編列預算」這種「編」當動詞的情況吃不進去。
_SUBDIVISION = rf"(?:[{_CJK}]{{1,8}}編)?"

_NAME_PATTERN = re.compile(
    rf"(?P<name>[{_CJK}A-Za-z0-9（）()]{{2,40}}?(?:{'|'.join(_SUFFIX_TYPES)}){_SUBDIVISION})"
    # 名稱與條號之間可能隔著結束引號：「營造安全衛生設施標準」第59條。
    # 引號不在名稱的字元集裡，所以名稱會停在引號前面，條號如果要求緊接就會掉。
    rf"[」』》〉\s]*"
    rf"(?:第\s*(?P<article>[0-9０-９一二三四五六七八九十百千]+(?:\s*之\s*[0-9一二三四五六七八九十]+)?)\s*條"
    rf"(?:\s*第\s*[0-9一二三四五六七八九十]+\s*[項款目])?)?"
)

# 書名號/引號包起來的名稱，是最可靠的訊號
_QUOTED_PATTERN = re.compile(r"[《〈「『]\s*(?P<name>[^》〉」』]{2,40})\s*[》〉」』]")

# 標準編號的發行機構
_STANDARD_ORGS = (
    "CNS", "ISO", "IEC", "ASTM", "JIS", "EN", "ANSI", "BS", "DIN",
    "AASHTO", "ACI", "AWS", "API", "UL", "NFPA",
)
# 左邊界用「前面不是英數字」而不是 \b：Python 把中文也當成 word character，
# 所以「依據CNS3090」的「據」與「C」之間**沒有** \b，整個編號會抓不到。
# 真實文件常常不留空格，合成的範例文件才每次都寫「符合 CNS 3090 之規定」。
# 換成 lookbehind 之後仍然擋得住「ACNS3090」這種英數字緊鄰的情況。
_STANDARD_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9])(?P<org>{'|'.join(_STANDARD_ORGS)})"
    r"[\s\-‑–]*"
    r"(?P<number>[A-Z]{0,4}[\s\-]?\d{1,6}(?:[\-–/][A-Za-z0-9]{1,8})*)"
    r"(?:\s*[:：]\s*(?P<year>(?:19|20)\d{2}))?",
    re.IGNORECASE,
)


def _classify(name: str) -> RegulationType | None:
    for suffix, reg_type in _SUFFIX_TYPES.items():
        if name.endswith(suffix):
            return reg_type
    # 「建築技術規則建築構造編」的字尾是「編」，型別要看它的母法（建築技術規則）。
    # 不用正則從右邊剝——`[中文]{1,8}編$` 會從名稱中間開始比對，把母法一起砍掉
    # （建築技術規則建築構造編 -> 建築）。直接往回找母法的字尾比較穩，
    # 而且 _SUFFIX_TYPES 是長字尾排在前面，先找到的就是最精確的那個。
    # 同理，「建築物耐震設計規範及解說」的字尾是「說」，型別要看「規範」。
    # 只在「編」或「及/與/暨＋很短的補充」這兩種明確形狀才往回找；放寬成無條件往回找
    # 會讓整句話（「產品品質符合國家標準…並經檢驗合格」含「標準」二字）也被收下來。
    if name.endswith("編") or _TRAILING_TAIL.search(name):
        for suffix, reg_type in _SUFFIX_TYPES.items():
            if suffix in name:
                return reg_type
    return None


def _clean_name(name: str) -> str:
    """剝掉名稱前面的連接詞，只留下真正的法規名稱。回傳空字串代表「這不是名稱」。

    「本計畫依政府採購法」 -> 「政府採購法」
    「混凝土施工依混凝土結構施工規範」 -> 「混凝土結構施工規範」
    「確保工程的施工成果能符合設計及規範」 -> ""（整句話，不是名稱）
    """
    cut = _INTERNAL_CUT.match(name)
    if cut:
        if len(name) - cut.end() >= 3:
            name = name[cut.end():]
        # 切掉之後留不下一個像樣的名稱。這時有兩種可能，差別在連接詞**前面**那段：
        #   「建築物耐震設計規範」及「解說」    前段以「規範」結尾，是名稱 -> 整串保留
        #   「確保工程的施工成果能符合設計」及「規範」  前段不是名稱 -> 整句丟掉
        # 舊版一律退回保留整串，於是任何剛好以法規字尾結尾的句子片段都會變成一筆引用
        # （真實文件一次就撞出七筆）。
        elif _classify(name[: cut.start("conn")]) is None:
            return ""
    for _ in range(3):
        cleaned = _LEADING_NOISE.sub("", name)
        if cleaned == name:
            break
        name = cleaned
    return name.strip()


def _is_valid_name(name: str) -> bool:
    if len(name) < 3 or name in _EXACT_BLOCKLIST:
        return False
    if _STARTS_WITH_CONNECTIVE.match(name):
        return False
    if not _brackets_balanced(name):
        return False
    return not name.endswith(_SUFFIX_BLOCKLIST)


def _brackets_balanced(name: str) -> bool:
    """括號沒有成對，代表名稱是從半路被切出來的。

    「工程契約(含規範及圖說)」的字尾「規範」在括號裡面，非貪婪比對會切出
    「工程契約(含規範」——一個開了沒關的括號就是這種切法的指紋。
    """
    return name.count("(") == name.count(")") and name.count("（") == name.count("）")


def _normalize_standard_number(org: str, number: str, year: str | None) -> str:
    core = re.sub(r"\s+", " ", number.strip().upper().replace("‑", "-").replace("–", "-"))
    base = f"{org.upper()} {core}"
    return f"{base}:{year}" if year else base


class RuleEngine:
    """對一段文字跑規則式抽取，回傳候選清單。不碰資料庫、不呼叫外部服務。"""

    method = ExtractionMethod.REGEX

    def extract(self, text: str) -> list[Candidate]:
        return self._quoted(text) + self._standards(text) + self._chinese_names(text)

    # --- 各條規則 ---

    def _quoted(self, text: str) -> list[Candidate]:
        results = []
        for match in _QUOTED_PATTERN.finditer(text):
            name = _clean_name(match.group("name"))
            # 引號是「名稱在哪裡」的訊號，不是「這是法規」的證明。真實文件會把一整句
            # 話包在引號裡（「產品品質符合國家標準 CNS 4750規定並經檢驗合格」），
            # 原本沒有驗證就當成 OTHER 收下來，除了製造垃圾，它的 span 還涵蓋整段引文，
            # 會連帶把裡面真正的標準編號擠掉。所以這裡跟 _chinese_names 用同一套驗證：
            # 認不出法規字尾就不收。
            reg_type = _classify(name)
            if reg_type is None or not _is_valid_name(name):
                continue
            results.append(
                Candidate(
                    raw_text=name,
                    regulation_type=reg_type,
                    method=self.method,
                    confidence=1.0,
                    start=match.start(),
                    end=match.end(),
                    notes=["以書名號/引號標示"],
                )
            )
        return results

    def _standards(self, text: str) -> list[Candidate]:
        results = []
        for match in _STANDARD_PATTERN.finditer(text):
            number = _normalize_standard_number(
                match.group("org"), match.group("number"), match.group("year")
            )
            results.append(
                Candidate(
                    raw_text=match.group(0).strip(),
                    regulation_type=RegulationType.STANDARD,
                    method=self.method,
                    confidence=1.0,
                    standard_number=number,
                    start=match.start(),
                    end=match.end(),
                    notes=[f"標準編號格式：{number}"],
                )
            )
        return results

    def _chinese_names(self, text: str) -> list[Candidate]:
        results = []
        for match in _NAME_PATTERN.finditer(text):
            raw_name = match.group("name")
            name = _clean_name(raw_name)
            if not _is_valid_name(name):
                continue
            reg_type = _classify(name)
            if reg_type is None:
                continue
            article = match.group("article")
            # 名稱前面被剝掉的字數，用來把 start 對齊到真正的名稱開頭
            offset = len(raw_name) - len(name)
            results.append(
                Candidate(
                    raw_text=name,
                    regulation_type=reg_type,
                    method=self.method,
                    # 有寫條號的引用通常是明確引用，信心給滿分
                    confidence=1.0 if article else 0.9,
                    article=f"第{article.replace(' ', '')}條" if article else None,
                    start=match.start("name") + offset,
                    end=match.end(),
                    notes=["名稱字尾符合法規命名慣例"],
                )
            )
        return results
