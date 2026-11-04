"""檢核表的「契約」欄：契約書裡提到工項的地方。

秀山的契約書是 Word 轉 PDF，條號（第一條…）是自動編號，文字層裡沒有。所以出處寫頁碼與前面
最近的小標題（「假設工程之組立及拆除：」），不推算條號。
"""

from app.parsers.base import ParsedSection
from app.specs.contract_reader import contract_passages, item_keywords, mentions


def section(text: str, page: int) -> ParsedSection:
    return ParsedSection(content=text, order_index=0, page=page)


SECTIONS = [
    section("本契約文件及效力： 一、 本契約包括下列文件：", 1),
    section("(一) 招標文件及其變更或補充。", 1),
    section("假設工程之組立及拆除： 一、 鷹架、施工架及模板支撐等假設工程之組立及拆除，施工前應妥為設計。", 17),
    section("二、 模板拆除應依施工規範辦理。", 17),
    section("工程品質： 一、 混凝土澆置前應會同監造單位檢查。", 21),
    # 標題後面直接換段，或接「(一)」
    section("施工計畫與報表：", 22),
    section("(一) 乙方應於開工前提出施工計畫。", 22),
    section("乙方應出具切結書；其內容應包括下列情形：", 23),
    section("(一) 電梯安裝應依核定之施工計畫辦理。", 23),
]


class TestPassages:
    def test_each_passage_knows_its_page_and_nearest_title(self):
        passages = contract_passages(SECTIONS)
        by_text = {p.text[:6]: p for p in passages}
        assert by_text["二、 模板拆"].page == 17
        assert by_text["二、 模板拆"].heading == "假設工程之組立及拆除"
        assert by_text["(一) 招標"].heading == "本契約文件及效力"

    def test_a_title_can_stand_alone_but_a_sentence_is_not_a_title(self):
        passages = contract_passages(SECTIONS)
        heading_of = {p.text: p.heading for p in passages}
        assert heading_of["(一) 乙方應於開工前提出施工計畫。"] == "施工計畫與報表"
        # 「…包括下列情形：」是句子，不換標題
        assert heading_of["(一) 電梯安裝應依核定之施工計畫辦理。"] == "施工計畫與報表"

    def test_form_field_labels_are_not_titles(self):
        passages = contract_passages(SECTIONS + [section("工程名稱：", 104), section("審查日期：", 104)])
        assert passages[-1].heading == "施工計畫與報表"


class TestMentions:
    def test_a_keyword_finds_page_heading_and_excerpt(self):
        found = mentions("模板", contract_passages(SECTIONS))
        assert [(m.page, m.heading) for m in found] == [(17, "假設工程之組立及拆除"), (17, "假設工程之組立及拆除")]
        assert "模板支撐" in found[0].excerpt
        assert len(found[0].excerpt) <= 80

    def test_at_most_three_mentions(self):
        many = [section(f"第{i}段提到混凝土。", i) for i in range(1, 10)]
        assert len(mentions("混凝土", contract_passages(many))) == 3

    def test_nothing_found_is_an_empty_list(self):
        assert mentions("空調", contract_passages(SECTIONS)) == []


class TestItemKeywords:
    def test_the_subject_before_the_first_comma_then_the_sections(self):
        assert item_keywords("普通模板，普通模板含組立(8成新)", ["結構體工程"]) == ["普通模板", "模板", "結構體"]

    def test_section_suffixes_are_removed(self):
        assert item_keywords("KW-MP PANEL", ["開關箱設備工程", "水電工程"]) == ["開關箱", "水電"]

    def test_too_short_or_generic_words_are_dropped(self):
        assert item_keywords("其他，雜項", ["雜項工程"]) == []


class TestRealBoqNames:
    """秀山標單的名稱：「產品，乾粉滅火器…」「施工費，…」——第一段是分類，不是主體。"""

    def test_a_generic_first_segment_is_skipped(self):
        assert item_keywords("產品，乾粉滅火器，10型，ABC", []) == ["乾粉滅火器"]
        assert item_keywords("施工費，外牆清洗", []) == ["外牆清洗"]

    def test_modifiers_are_stripped_instead_of_taking_the_last_two_characters(self):
        assert item_keywords("預拌混凝土，210kgf/cm2", []) == ["預拌混凝土", "混凝土"]
        assert item_keywords("臨時設施，施工用臨時水電", []) == ["臨時設施"]

    def test_fragments_with_brackets_are_not_keywords(self):
        assert item_keywords("安裝(含配管及試車)", []) == []


def test_a_two_character_section_core_keeps_its_noun():
    """「衛生設備工程」只剩「衛生」會對到「職業安全衛生」；留「衛生設備」。"""
    assert item_keywords("KW-MP PANEL", ["衛生設備工程"]) == ["衛生設備"]
