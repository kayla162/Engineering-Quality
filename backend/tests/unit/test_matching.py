"""正規化與比對引擎的單元測試。"""

import pytest

from app.core.config import settings
from app.core.enums import RegulationStatus
from app.matching.matching_engine import MatchCandidate, MatchingEngine
from app.matching.normalizer import NormalizationEngine, clean_text


class TestNormalizer:
    @pytest.fixture
    def engine(self) -> NormalizationEngine:
        return NormalizationEngine()

    def test_alias_maps_to_official_name(self, engine):
        result = engine.normalize("採購法")
        assert result.normalized_name == "政府採購法"
        assert result.matched_alias is True
        assert result.reasons

    def test_official_name_passes_through(self, engine):
        assert engine.normalize("政府採購法").normalized_name == "政府採購法"

    def test_unknown_name_is_only_cleaned(self, engine):
        result = engine.normalize("《營建剩餘土石方處理辦法》")
        assert result.normalized_name == "營建剩餘土石方處理辦法"
        assert result.matched_alias is False

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("ＣＮＳ ３０９０", "CNS 3090"),   # 全形轉半形
            ("CNS-560", "CNS 560"),           # 統一標準編號寫法
            ("CNS560", "CNS 560"),
            ("政府採購法第70條", "政府採購法"),  # 去掉條號
            ("「政府採購法」", "政府採購法"),     # 去掉引號
        ],
    )
    def test_clean_text(self, raw, expected):
        assert clean_text(raw) == expected


def candidate(
    name, status=RegulationStatus.ACTIVE, aliases=None, currency=True, key=None,
    reg_type="law", standard_number=None,
):
    return MatchCandidate(
        key=key or name,
        name=name,
        normalized_name=name,
        type=reg_type,
        status=status,
        aliases=aliases or [],
        standard_number=standard_number,
        can_confirm_currency=currency,
    )


class TestMatchingEngine:
    @pytest.fixture
    def engine(self) -> MatchingEngine:
        return MatchingEngine(llm_provider=None)  # 規則引擎單獨就要能運作

    async def test_exact_name_is_full_confidence(self, engine):
        decision = await engine.match("政府採購法", [candidate("政府採購法")])
        assert decision.confidence == 1.0
        assert decision.status is RegulationStatus.ACTIVE
        assert decision.is_tentative is False

    async def test_alias_match(self, engine):
        decision = await engine.match("採購法", [candidate("政府採購法", aliases=["採購法"])])
        assert decision.confidence >= 0.95
        assert decision.status is RegulationStatus.ACTIVE

    async def test_reordered_name_is_tentative_but_matched(self, engine):
        """「混凝土結構施工規範」對上「結構混凝土施工規範」：仍採用其狀態，但標記為疑似。"""
        decision = await engine.match(
            "混凝土結構施工規範",
            [candidate("結構混凝土施工規範", status=RegulationStatus.AMENDED)],
        )
        assert settings.MATCH_POSSIBLE_THRESHOLD <= decision.confidence < settings.MATCH_AUTO_THRESHOLD
        assert decision.status is RegulationStatus.AMENDED
        assert decision.is_tentative is True

    async def test_low_similarity_is_not_found(self, engine):
        decision = await engine.match("營建剩餘土石方處理辦法", [candidate("政府採購法")])
        assert decision.status is RegulationStatus.NOT_FOUND
        assert decision.candidate is None

    async def test_no_candidates_is_not_found(self, engine):
        decision = await engine.match("完全不存在的法規", [])
        assert decision.status is RegulationStatus.NOT_FOUND
        assert decision.confidence == 0.0

    async def test_repealed_status_is_preserved(self, engine):
        decision = await engine.match(
            "勞工安全衛生法", [candidate("勞工安全衛生法", status=RegulationStatus.REPEALED)]
        )
        assert decision.status is RegulationStatus.REPEALED

    async def test_unconfirmable_currency_downgrades_to_possible_match(self, engine):
        """付費標準即使名稱完全命中，也只能是 POSSIBLE_MATCH。"""
        decision = await engine.match(
            "CNS 3090", [candidate("CNS 3090", currency=False)]
        )
        assert decision.confidence == 1.0
        assert decision.status is RegulationStatus.POSSIBLE_MATCH
        assert any("人工查證" in reason for reason in decision.reasons)

    async def test_reasons_are_human_readable(self, engine):
        decision = await engine.match("政府採購法", [candidate("政府採購法")])
        assert decision.reasons
        assert all(isinstance(reason, str) and reason for reason in decision.reasons)


class TestTentativeMatchNeverClaimsActive:
    """信心不足時不得宣告「現行有效」。

    背景：接上真實法規資料庫後發現，「勞工安全衛生法」（已更名的舊法）會以 71%
    模糊比對到「職業安全衛生法」，並被標成「現行有效（疑似）」。使用者看到會以為
    引用沒問題，但實際上引用的是已經不存在的法規名稱。
    這是 docs/database.md 第 4 節明確要避免的「看似肯定但可能誤導」。
    """

    @pytest.fixture
    def engine(self) -> MatchingEngine:
        return MatchingEngine(llm_provider=None)

    async def test_tentative_active_is_downgraded(self, engine):
        decision = await engine.match(
            "勞工安全衛生法", [candidate("職業安全衛生法", status=RegulationStatus.ACTIVE)]
        )
        assert settings.MATCH_POSSIBLE_THRESHOLD <= decision.confidence < settings.MATCH_AUTO_THRESHOLD
        assert decision.status is RegulationStatus.POSSIBLE_MATCH
        assert any("人工確認" in reason for reason in decision.reasons)
        # 仍要保留比對到哪一部法規，人工覆核時才看得到線索
        assert decision.candidate is not None
        assert decision.candidate.name == "職業安全衛生法"

    async def test_confident_active_is_kept(self, engine):
        decision = await engine.match("政府採購法", [candidate("政府採購法")])
        assert decision.confidence >= settings.MATCH_AUTO_THRESHOLD
        assert decision.status is RegulationStatus.ACTIVE

    async def test_alias_match_still_claims_active(self, engine):
        """別名是我們自己確認過的對應關係，不算「不確定」。"""
        decision = await engine.match("採購法", [candidate("政府採購法", aliases=["採購法"])])
        assert decision.status is RegulationStatus.ACTIVE

    @pytest.mark.parametrize(
        "status", [RegulationStatus.AMENDED, RegulationStatus.REPEALED]
    )
    async def test_needs_attention_statuses_survive_tentative_match(self, engine, status):
        """AMENDED / REPEALED 本來就是「要注意」，降級沒有意義，要原樣呈現。"""
        decision = await engine.match(
            "混凝土結構施工規範", [candidate("結構混凝土施工規範", status=status)]
        )
        assert decision.is_tentative is True
        assert decision.status is status


class TestStandardNumberTypeGuard:
    """引用帶標準編號時，不可以對到非標準型別的候選。

    背景：施工綱要規範的章節名稱是「工項/材料名」而不是文件名——「卜特蘭水泥」、
    「鋼筋」、「品質管理」。用專案自己的比對器實測，這些章節對上帶編號的標準引用
    會拿到 0.90 以上的分數：

        CNS 61 卜特蘭水泥        -> 03052 卜特蘭水泥   0.90  自動採信
        CNS 560 鋼筋混凝土用鋼筋 -> 03210 鋼筋         0.90  自動採信
        ISO 9001 品質管理系統    -> 01450 品質管理     0.90  自動採信

    這種「有信心的錯」比查不到傷害大得多。文件裡真的出現標準編號時，
    比對對象就一定是標準，其他型別一律不採用。
    """

    @pytest.fixture
    def engine(self) -> MatchingEngine:
        return MatchingEngine(llm_provider=None)

    async def test_similar_engineering_spec_is_not_matched(self, engine):
        """實測到的真實碰撞：CNS 61 vs 施工綱要規範第03052章。"""
        decision = await engine.match(
            "CNS 61 卜特蘭水泥",
            [candidate("卜特蘭水泥", reg_type="engineering_spec")],
            standard_number="CNS 61",
        )

        assert decision.status is RegulationStatus.NOT_FOUND
        assert decision.candidate is None

    async def test_similar_law_is_not_matched(self, engine):
        decision = await engine.match(
            "ISO 9001 品質管理系統－要求",
            [candidate("品質管理系統－要求", reg_type="engineering_spec")],
            standard_number="ISO 9001",
        )

        assert decision.status is RegulationStatus.NOT_FOUND

    async def test_reason_explains_why_nothing_matched(self, engine):
        """使用者要看得出來是「型別不合」而不是「名稱不像」。"""
        decision = await engine.match(
            "CNS 61 卜特蘭水泥",
            [candidate("卜特蘭水泥", reg_type="engineering_spec")],
            standard_number="CNS 61",
        )

        assert any("CNS 61" in reason for reason in decision.reasons)
        assert any("標準" in reason for reason in decision.reasons)

    async def test_standard_candidate_still_matches(self, engine):
        """守門只擋型別不合的，正牌標準照樣比對得到。"""
        decision = await engine.match(
            "CNS 61 卜特蘭水泥",
            [candidate("CNS 61 卜特蘭水泥", reg_type="standard", standard_number="CNS 61")],
            standard_number="CNS 61",
        )

        assert decision.candidate is not None
        assert decision.confidence >= settings.MATCH_AUTO_THRESHOLD

    async def test_standard_candidate_wins_over_lookalike(self, engine):
        """兩者同時存在時，要挑到標準那一筆，不是名稱更短的章節。"""
        decision = await engine.match(
            "CNS 61 卜特蘭水泥",
            [
                candidate("卜特蘭水泥", reg_type="engineering_spec", key="章節"),
                candidate("CNS 61 卜特蘭水泥", reg_type="standard", standard_number="CNS 61", key="標準"),
            ],
            standard_number="CNS 61",
        )

        assert decision.candidate.key == "標準"

    async def test_reference_without_standard_number_is_untouched(self, engine):
        """沒有標準編號的引用不受守門影響——不要為了修一個問題弄壞另一個。"""
        decision = await engine.match(
            "政府採購法施行細則",
            [candidate("政府採購法", reg_type="law")],
        )

        assert decision.candidate is not None
