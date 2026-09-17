"""抽取層的單元測試：規則引擎、字典、去重。"""

import pytest

from app.core.enums import ExtractionMethod, RegulationType
from app.extractors.base import Candidate, dedupe
from app.extractors import ExtractionPipeline
from app.extractors.dictionary_extractor import DictionaryExtractor
from app.extractors.rule_engine import RuleEngine


@pytest.fixture
def rule() -> RuleEngine:
    return RuleEngine()


@pytest.fixture
def dictionary() -> DictionaryExtractor:
    return DictionaryExtractor()


class TestRuleEngine:
    @pytest.mark.parametrize(
        "text, expected_name, expected_article",
        [
            ("依政府採購法第70條辦理", "政府採購法", "第70條"),
            ("本計畫依政府採購法規定辦理", "政府採購法", None),
            ("依營建剩餘土石方處理辦法辦理", "營建剩餘土石方處理辦法", None),
            ("混凝土施工依混凝土結構施工規範辦理", "混凝土結構施工規範", None),
            ("依水土保持技術規範第15條之1辦理", "水土保持技術規範", "第15條"),
        ],
    )
    def test_extracts_chinese_names(self, rule, text, expected_name, expected_article):
        names = {c.raw_text: c for c in rule.extract(text)}
        assert expected_name in names
        assert names[expected_name].article == expected_article

    @pytest.mark.parametrize(
        "text",
        [
            "施工方法應另行提報",       # 「方法」不是法規
            "無法於期限內完成",         # 「無法」不是法規
            "三、材料檢驗標準",         # 泛稱
            "本節說明施工規範之適用",   # 沒有冠上主體的泛稱
            "依據規範",                 # 表格標題，以連接詞開頭
        ],
    )
    def test_rejects_common_phrases(self, rule, text):
        assert [c.raw_text for c in rule.extract(text)] == []

    @pytest.mark.parametrize(
        "text, number",
        [
            ("應符合 CNS 3090 之規定", "CNS 3090"),
            ("依 CNS560 辦理", "CNS 560"),
            ("試驗依 ASTM C39/C39M 辦理", "ASTM C39/C39M"),
            ("取得 ISO 9001:2015 驗證", "ISO 9001:2015"),
        ],
    )
    def test_extracts_standard_numbers(self, rule, text, number):
        candidates = rule.extract(text)
        assert any(c.standard_number == number for c in candidates)
        assert all(c.regulation_type == RegulationType.STANDARD for c in candidates)

    def test_quoted_name_is_high_confidence(self, rule):
        candidates = rule.extract("參照《公共工程施工品質管理作業要點》辦理")
        assert candidates[0].raw_text == "公共工程施工品質管理作業要點"
        assert candidates[0].confidence == 1.0


class TestDictionaryExtractor:
    def test_matches_alias(self, dictionary):
        candidates = dictionary.extract("依採購法規定辦理")
        assert [c.raw_text for c in candidates] == ["採購法"]
        assert candidates[0].method == ExtractionMethod.DICTIONARY

    def test_prefers_longest_term(self, dictionary):
        """「政府採購法」出現時不應該只抓到「採購法」。"""
        candidates = dictionary.extract("依政府採購法規定辦理")
        assert [c.raw_text for c in candidates] == ["政府採購法"]

    def test_matches_short_alias_regex_would_miss(self, dictionary):
        assert [c.raw_text for c in dictionary.extract("依品管要點辦理")] == ["品管要點"]


class TestDedupe:
    def _candidate(self, text, method, start, article=None):
        return Candidate(
            raw_text=text,
            regulation_type=RegulationType.LAW,
            method=method,
            start=start,
            end=start + len(text),
            article=article,
        )

    def test_dictionary_wins_over_regex_on_overlap(self):
        regex = self._candidate("計畫依政府採購法", ExtractionMethod.REGEX, 0, article="第70條")
        dic = self._candidate("政府採購法", ExtractionMethod.DICTIONARY, 3)
        kept = dedupe([regex, dic])
        assert [c.raw_text for c in kept] == ["政府採購法"]

    def test_article_is_carried_over_from_discarded_candidate(self):
        regex = self._candidate("計畫依政府採購法", ExtractionMethod.REGEX, 0, article="第70條")
        dic = self._candidate("政府採購法", ExtractionMethod.DICTIONARY, 3)
        assert dedupe([regex, dic])[0].article == "第70條"

    def test_keeps_separate_occurrences(self):
        first = self._candidate("政府採購法", ExtractionMethod.DICTIONARY, 0)
        second = self._candidate("職業安全衛生法", ExtractionMethod.DICTIONARY, 20)
        assert len(dedupe([first, second])) == 2

    def test_dictionary_hit_may_not_truncate_a_longer_name(self):
        """字典命中的若只是更長法規名稱的開頭，不可以取代較長的那一個。

        「建築技術規則建築構造編」在官方資料庫是獨立法規，被截成「建築技術規則」
        會高信心地對到錯誤的法規——比漏抽嚴重。

        區別在結尾：字典命中「開始得比較晚」是在剝掉前面的雜訊（好事，見上一個測試），
        「結束得比較早」則是把一部更精確的法規截短（壞事）。
        """
        regex = self._candidate("建築技術規則建築構造編", ExtractionMethod.REGEX, 3)
        dic = self._candidate("建築技術規則", ExtractionMethod.DICTIONARY, 3)

        assert [c.raw_text for c in dedupe([regex, dic])] == ["建築技術規則建築構造編"]


class TestSentenceFragmentsEndingInLawWords:
    """句子片段剛好以「法」結尾時不可以被當成法規名稱。

    由 golden set 抓到的真實案例：「無法取得者應設法補正」被抽成一筆法規引用。
    根因是「設法」這類日常用語只登記在 _EXACT_BLOCKLIST（完全相等才擋），
    沒有登記成結尾，所以任何以它結尾的句子片段都會通過驗證。
    """

    @pytest.mark.parametrize(
        "text",
        [
            "材料檢驗標準由品管人員依作業要點辦理，無法取得者應設法補正。",
            "文件如有缺漏，承包商應設法補齊。",
            "本工程之施工品質應依法辦理。",
        ],
    )
    def test_fragment_is_not_extracted(self, rule, text):
        assert [c.raw_text for c in rule.extract(text)] == []


class TestSubdividedRegulationNames:
    """「建築技術規則建築構造編」不可以被截成「建築技術規則」。

    官方資料庫裡各編是獨立法規（見 data/alias_dictionary.json 的註解），
    截短之後會對到錯誤的法規，而且信心 100%——比漏抽嚴重。

    根因是 _NAME_PATTERN 的名稱部分是非貪婪比對，遇到第一個認得的字尾就停，
    看不到後面還有「…編」。
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("結構設計依建築技術規則建築構造編辦理。", "建築技術規則建築構造編"),
            ("依建築技術規則建築設計施工編之規定。", "建築技術規則建築設計施工編"),
            ("依建築技術規則總則編辦理。", "建築技術規則總則編"),
        ],
    )
    def test_subdivision_is_kept(self, rule, text, expected):
        assert expected in [c.raw_text for c in rule.extract(text)]

    def test_subdivided_name_is_still_classified(self, rule):
        """名稱結尾變成「編」之後，型別分類要照樣認得出是法規命令。"""
        candidates = {c.raw_text: c for c in rule.extract("依建築技術規則建築構造編辦理。")}

        assert candidates["建築技術規則建築構造編"].regulation_type == RegulationType.REGULATION

    async def test_the_original_failing_sentence(self):
        """golden set 裡的原句，走完整管線：兩部法規都要完整抽到。

        用管線而不是單獨的規則引擎，因為兩個名稱各由不同的層負責：
        「建築技術規則建築構造編」來自規則引擎，
        「建築物耐震設計規範及解說」的「及解說」是別名字典補上的。
        """
        pipeline = ExtractionPipeline(llm_provider=None)

        candidates, _ = await pipeline.extract(
            "結構設計依建築技術規則建築構造編與建築物耐震設計規範及解說辦理。"
        )
        names = [c.raw_text for c in candidates]

        assert "建築技術規則建築構造編" in names
        assert "建築物耐震設計規範及解說" in names

    @pytest.mark.parametrize(
        "text, expected",
        [
            # 「編」在後面當動詞，不是法規的一部分
            ("依政府採購法編列預算。", "政府採購法"),
            ("依營造業法編製施工計畫。", "營造業法"),
        ],
    )
    def test_verb_after_suffix_is_not_swallowed(self, rule, text, expected):
        assert expected in [c.raw_text for c in rule.extract(text)]


class TestStandardNumberAfterChinese:
    """中文緊接標準編號時不可以漏抽。

    真實文件寫「做坍度試驗依據CNS3090第7項規定辦理」——中間沒有空格。
    _STANDARD_PATTERN 開頭是 \b，但 Python 把中文也當成 word character，
    所以「據」和「C」之間沒有邊界，整個編號抓不到。
    合成的範例文件每次都寫「符合 CNS 3090 之規定」有空格，所以從來沒暴露。
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("做坍度試驗依據CNS3090第7項規定辦理", "CNS 3090"),
            ("產品品質符合國家標準CNS4750規定", "CNS 4750"),
            ("鋼筋應符合CNS560之規定", "CNS 560"),
            ("試驗依ASTMC39辦理", "ASTM C39"),
            # 原本就會過的寫法，回歸保護
            ("預拌混凝土應符合 CNS 3090 之規定", "CNS 3090"),
        ],
    )
    def test_standard_number_is_found(self, rule, text, expected):
        assert expected in [c.standard_number for c in rule.extract(text)]

    def test_letters_before_the_org_are_still_rejected(self, rule):
        """放寬邊界不能放寬到把 ACNS 當成 CNS。"""
        assert [c.standard_number for c in rule.extract("型號ACNS3090之零件")] == []


class TestArticleAfterClosingQuote:
    """名稱被引號包起來時，後面的條號不可以掉。

    真實文件寫「營造安全衛生設施標準」第59條第1款——結束引號卡在名稱與條號之間，
    而條號的正則要求緊接在名稱後面。
    """

    @pytest.mark.parametrize(
        "text",
        [
            "依「營造安全衛生設施標準」第59條第1款規定",
            "依《營造安全衛生設施標準》第59條規定",
            "依營造安全衛生設施標準第59條規定",  # 沒引號，回歸保護
        ],
    )
    def test_article_is_captured(self, rule, text):
        articles = [c.article for c in rule.extract(text) if c.raw_text == "營造安全衛生設施標準"]

        assert "第59條" in articles

    async def test_article_survives_the_pipeline(self):
        """去重之後也要留著——引號候選沒有條號，會把有條號的那筆擠掉。"""
        pipeline = ExtractionPipeline(llm_provider=None)

        candidates, _ = await pipeline.extract("依「營造安全衛生設施標準」第59條第1款規定")

        assert [c.article for c in candidates if c.raw_text == "營造安全衛生設施標準"] == ["第59條"]


class TestQuotedContentMustLookLikeARegulation:
    """引號是「名稱在哪裡」的訊號，不是「這是法規」的證明。

    真實文件把一整句話包在引號裡：
        「產品品質符合國家標準 CNS 4750規定並經檢驗合格」
    _quoted 沒有做 _chinese_names 那套驗證，任何引號內容都會變成一筆引用，
    而且它的 span 涵蓋整段引文，會連帶把裡面真正的 CNS 4750 擠掉。
    """

    @pytest.mark.parametrize(
        "text, rejected",
        [
            ("即「產品品質符合國家標準 CNS 4750規定並經檢驗合格」", "經檢驗合格"),
            ("或「正字標記之同等品」", "正字標記之同等品"),
            ("及「正字標記」等", "正字標記"),
        ],
    )
    def test_quoted_non_regulation_is_rejected(self, rule, text, rejected):
        assert rejected not in [c.raw_text for c in rule.extract(text)]

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("依「營造安全衛生設施標準」辦理", "營造安全衛生設施標準"),
            ("依《政府採購法》辦理", "政府採購法"),
            ("參照《建築技術規則建築構造編》", "建築技術規則建築構造編"),
        ],
    )
    def test_quoted_regulation_name_still_works(self, rule, text, expected):
        assert expected in [c.raw_text for c in rule.extract(text)]

    async def test_standard_inside_a_quoted_sentence_survives(self):
        """這是漏抽 CNS 4750 的真正原因：被引號候選的 span 吃掉。"""
        pipeline = ExtractionPipeline(llm_provider=None)

        candidates, _ = await pipeline.extract(
            "即「產品品質符合國家標準 CNS 4750規定並經檢驗合格」"
        )

        assert "CNS 4750" in [c.standard_number for c in candidates]


class TestGenericStandardTerms:
    """「國家標準」是泛稱，真正被引用的是它後面的編號。

    真實文件：「產品品質符合國家標準 CNS 4750規定」——該抽的是 CNS 4750，
    不是「國家標準」。這和既有的「施工規範」「相關規範」是同一類：
    沒有冠上主體的泛稱不是法規名稱。
    """

    @pytest.mark.parametrize(
        "text, rejected",
        [
            ("產品品質符合國家標準 CNS 4750規定", "國家標準"),
            ("應符合國家標準之規定", "國家標準"),
        ],
    )
    def test_generic_term_is_not_extracted(self, rule, text, rejected):
        assert rejected not in [c.raw_text for c in rule.extract(text)]

    def test_the_real_citation_beside_it_survives(self, rule):
        assert "CNS 4750" in [c.standard_number for c in rule.extract("符合國家標準 CNS 4750規定")]

    def test_named_standard_is_not_blocked(self, rule):
        """只擋完全等於「國家標準」四個字的情況，冠了主體的不受影響。"""
        assert "中華民國國家標準" in [
            c.raw_text for c in rule.extract("依中華民國國家標準辦理")
        ]


class TestSentenceFragmentsWithInternalConnectives:
    """句子片段剛好以法規字尾結尾時不可以被當成名稱。

    由真實文件的 golden set 抓到（sample-05/06），一次七筆：
        確保工程的施工成果能符合設計及規範
        使工程之機電設備功能符合規範
        如何符合品質要求及執行依據標準
        監造單位應按規範

    根因：_INTERNAL_CUT **有**找到連接詞，但切完只剩兩個字，被「至少留三個字」
    的守衛擋掉，於是整段句子原封不動保留下來。

    那個守衛不能拿掉——它正是用來保護「建築物耐震設計規範及解說」的（切在「及」
    只會剩「解說」）。兩者的差別在**連接詞前面那段像不像名稱**：
        建築物耐震設計規範 及 解說   -> 前段以「規範」結尾，是名稱，整串保留
        確保工程的施工成果能符合設計 及 規範 -> 前段不是名稱，整串丟掉
    """

    @pytest.mark.parametrize(
        "text",
        [
            "為確保工程的施工成果能符合設計及規範。",
            "使工程之機電設備功能符合規範與設計要求。",
            "施工計畫內容是否規範如何符合品質要求及執行依據標準。",
            "監造單位應按規範規定查驗工程品質。",
            "擬訂設備功能、運轉測試之抽驗程序及標準。",
        ],
    )
    def test_fragment_is_rejected(self, rule, text):
        assert [c.raw_text for c in rule.extract(text)] == []

    @pytest.mark.parametrize(
        "text, expected",
        [
            # 連接詞在名稱裡面，前段本身就是名稱 -> 整串保留。
            # 用書名號的寫法，因為 _NAME_PATTERN 是非貪婪的，停在「規範」就不再往後吃；
            # 會產生「…及解說」這種完整名稱的是 _quoted 那條路。
            ("結構設計依《建築物耐震設計規範及解說》辦理。", "建築物耐震設計規範及解說"),
            # 沒有連接詞的一般情況，回歸保護
            ("本計畫依政府採購法規定辦理", "政府採購法"),
            ("依營建剩餘土石方處理辦法辦理", "營建剩餘土石方處理辦法"),
        ],
    )
    def test_real_names_survive(self, rule, text, expected):
        assert expected in [c.raw_text for c in rule.extract(text)]


class TestTruncatedGenericTerms:
    """切割錯誤產生的半截詞。

    同樣來自真實文件：
        工程契約(含規範   從「工程契約(含規範及圖說)」切出來，括號沒有閉合
        五大管線相關法    從「五大管線相關法令等」切出來
        技術法           從「相關技術法規」切出來
    """

    @pytest.mark.parametrize(
        "text, rejected",
        [
            ("本品質計畫依據工程契約(含規範及圖說)、技師法", "工程契約(含規範"),
            ("建築法、五大管線相關法令等。", "五大管線相關法"),
            ("依據工程契約、設計圖說、規範、相關技術法規及參考品質計畫", "技術法"),
        ],
    )
    def test_fragment_is_rejected(self, rule, text, rejected):
        assert rejected not in [c.raw_text for c in rule.extract(text)]

    @pytest.mark.parametrize(
        "text, expected",
        [
            # 同一句裡真正的法規還是要抽到
            ("本品質計畫依據工程契約(含規範及圖說)、技師法", "技師法"),
            ("建築法、五大管線相關法令等。", "建築法"),
            # 「法規定」不可以被誤擋——這是最常見的寫法
            ("本計畫依政府採購法規定辦理", "政府採購法"),
            ("依建築技術規則規定辦理", "建築技術規則"),
        ],
    )
    def test_real_names_survive(self, rule, text, expected):
        assert expected in [c.raw_text for c in rule.extract(text)]
