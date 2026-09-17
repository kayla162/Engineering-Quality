"""計分邏輯本身的測試。

golden set 的數字要拿來擋 regression，所以算錯比沒有更糟——
會給人「已經很準了」的錯覺。這裡把計分規則本身釘住。
"""

import pytest

from app.core.enums import ExtractionMethod, RegulationType
from app.extractors.base import Candidate
from tests.golden.scoring import (
    ExpectedRef,
    GoldenCase,
    aggregate,
    load_cases,
    parse_expected,
    score_case,
)


def found(name: str, article: str | None = None) -> Candidate:
    return Candidate(
        raw_text=name,
        regulation_type=RegulationType.LAW,
        method=ExtractionMethod.REGEX,
        article=article,
    )


def case(*expected: ExpectedRef) -> GoldenCase:
    return GoldenCase(case_id="t", text="（測試用）", expected=list(expected))


class TestParseExpected:
    def test_name_only(self):
        assert parse_expected("政府採購法\n") == [ExpectedRef("政府採購法", None)]

    def test_name_with_article(self):
        assert parse_expected("政府採購法\t第70條\n") == [ExpectedRef("政府採購法", "第70條")]

    def test_blank_lines_and_comments_are_ignored(self):
        content = "# 這是註解\n\n政府採購法\n\n  \n職業安全衛生法\n"

        assert [e.name for e in parse_expected(content)] == ["政府採購法", "職業安全衛生法"]

    def test_spaces_instead_of_tab(self):
        """從 Word 貼過來很容易變成空白，不要因為這個就判人家標錯。"""
        assert parse_expected("政府採購法    第70條") == [ExpectedRef("政府採購法", "第70條")]


class TestLoadCases:
    def test_pairs_txt_with_expected(self, tmp_path):
        (tmp_path / "a.txt").write_text("依政府採購法辦理", encoding="utf-8")
        (tmp_path / "a.expected").write_text("政府採購法", encoding="utf-8")

        cases = load_cases(tmp_path)

        assert len(cases) == 1
        assert cases[0].case_id == "a"
        assert cases[0].text == "依政府採購法辦理"
        assert cases[0].expected == [ExpectedRef("政府採購法", None)]

    def test_text_without_annotation_is_an_error(self, tmp_path):
        """沒標註的文字檔安靜跳過，等於讓人以為標註做完了。"""
        (tmp_path / "a.txt").write_text("依政府採購法辦理", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="a.expected"):
            load_cases(tmp_path)

    def test_empty_directory(self, tmp_path):
        assert load_cases(tmp_path) == []


class TestScoreCase:
    def test_everything_found(self):
        score = score_case(
            case(ExpectedRef("政府採購法"), ExpectedRef("職業安全衛生法")),
            [found("政府採購法"), found("職業安全衛生法")],
        )

        assert score.recall == 1.0
        assert score.precision == 1.0
        assert score.missing == [] and score.spurious == []

    def test_missing_lowers_recall_only(self):
        score = score_case(
            case(ExpectedRef("政府採購法"), ExpectedRef("職業安全衛生法")),
            [found("政府採購法")],
        )

        assert score.recall == 0.5
        assert score.precision == 1.0
        assert score.missing == ["職業安全衛生法"]

    def test_spurious_lowers_precision_only(self):
        score = score_case(case(ExpectedRef("政府採購法")), [found("政府採購法"), found("施工方法")])

        assert score.recall == 1.0
        assert score.precision == 0.5
        assert score.spurious == ["施工方法"]

    def test_names_are_compared_after_normalisation(self):
        """比對用的是正式流程同一套 clean_text，全形/括號/條號差異不算錯。"""
        score = score_case(case(ExpectedRef("CNS 560")), [found("ＣＮＳ５６０")])

        assert score.recall == 1.0

    def test_duplicate_citations_count_once(self):
        """同一部法規在一段文字裡出現兩次，不該讓分數變好或變壞。"""
        score = score_case(case(ExpectedRef("政府採購法")), [found("政府採購法"), found("政府採購法")])

        assert score.precision == 1.0
        assert score.recall == 1.0

    def test_nothing_expected_and_nothing_found_is_perfect(self):
        """全是干擾字的段落——什麼都不該抽到，抽到就是亂抽。"""
        score = score_case(case(), [])

        assert score.precision == 1.0 and score.recall == 1.0


class TestArticles:
    def test_wrong_article_is_reported_separately(self):
        """條號錯是另一種失敗，混進 P/R 會看不出到底是哪種問題。"""
        score = score_case(case(ExpectedRef("政府採購法", "第70條")), [found("政府採購法", "第10條")])

        assert score.precision == 1.0 and score.recall == 1.0
        assert score.article_mismatches == [("政府採購法", "第70條", "第10條")]

    def test_matching_article_is_not_reported(self):
        score = score_case(case(ExpectedRef("政府採購法", "第70條")), [found("政府採購法", "第70條")])

        assert score.article_mismatches == []

    def test_unannotated_article_is_not_checked(self):
        """標註沒寫條號 = 不在乎，讓標註成本低一點。"""
        score = score_case(case(ExpectedRef("政府採購法")), [found("政府採購法", "第70條")])

        assert score.article_mismatches == []


class TestAggregate:
    def test_micro_average_over_all_cases(self):
        """用總數平均，不是各案例平均——否則只有一筆引用的案例權重會被放大。"""
        a = score_case(case(ExpectedRef("甲法"), ExpectedRef("乙法")), [found("甲法")])
        b = score_case(case(ExpectedRef("丙法")), [found("丙法")])

        totals = aggregate([a, b])

        assert totals.expected_count == 3
        assert totals.matched_count == 2
        assert totals.recall == pytest.approx(2 / 3)

    def test_no_cases_is_zero_not_a_crash(self):
        totals = aggregate([])

        assert totals.expected_count == 0
        assert totals.recall == 0.0
