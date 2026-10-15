"""法規查證：只採完全同名。

為什麼不用模糊比對（實測 2026-10-15，全國法規索引）：
    低電壓金屬閉鎖型配電箱檢驗法 -> 商品檢驗法、民法、醫事檢驗師法
    屋內線路裝置規則            -> 中央空氣調節系統電表及線路裝置規則、兵籍規則
一個 CNS 配電箱檢驗方法的最佳候選是民法。接上去就是「有信心的錯」。

查不到同名的名稱不出現在結果裡，呼叫端據此標成「未查證」——
不是「查無此法規」。屋內線路裝置規則與建築技術規則都是真法規，
只是不以那個名稱登錄在索引裡。
"""

import pytest

from app.core.enums import RegulationStatus
from app.services.basis_verifier import verify_names


class FakeSource:
    """只認完全同名的假來源；模糊候選故意給錯的，證明我們沒有用它。"""

    def __init__(self, known: dict[str, str]):
        self.known = known
        self.queries: list[str] = []

    async def search(self, query: str):
        self.queries.append(query)
        from app.sources.base import RegulationSearchResult

        from app.core.enums import RegulationType

        results = []
        if query in self.known:
            results.append(
                RegulationSearchResult(
                    source="fake",
                    external_id=f"fake-{query}",
                    name=query,
                    type=RegulationType.LAW,
                    status=self.known[query],
                )
            )
        # 模糊候選：名稱不同，絕對不該被採用
        results.append(
            RegulationSearchResult(
                source="fake",
                external_id="fake-noise",
                name="民法",
                type=RegulationType.LAW,
                status=RegulationStatus.ACTIVE,
            )
        )
        return results


class TestVerifyNames:
    async def test_an_exact_name_gets_its_status(self):
        source = FakeSource({"職業安全衛生法": RegulationStatus.ACTIVE})

        result = await verify_names({"職業安全衛生法"}, source)

        assert result == {"職業安全衛生法": RegulationStatus.ACTIVE}

    async def test_a_name_with_only_fuzzy_candidates_is_absent(self):
        """查不到同名就不出現在 dict 裡——呼叫端才能標成「未查證」。"""
        source = FakeSource({})

        result = await verify_names({"低電壓金屬閉鎖型配電箱檢驗法"}, source)

        assert result == {}

    async def test_the_fuzzy_candidate_is_never_adopted(self):
        """假來源每次都回一個「民法」。它絕對不能被當成答案。"""
        source = FakeSource({})

        result = await verify_names({"瓷磚安裝法"}, source)

        assert "民法" not in result.values()
        assert result == {}

    async def test_each_distinct_name_is_queried_once(self):
        """792 筆依據只有 96 個相異名稱，不要查 792 次。"""
        source = FakeSource({"勞動基準法": RegulationStatus.ACTIVE})

        await verify_names({"勞動基準法", "勞動檢查法"}, source)

        assert sorted(source.queries) == ["勞動基準法", "勞動檢查法"]

    async def test_a_source_failure_does_not_break_the_build(self):
        """來源掛掉時整張檢核表還是要產得出來，只是沒有查證狀態。"""

        class BrokenSource:
            async def search(self, query: str):
                from app.core.errors import SourceQueryError

                raise SourceQueryError("fake", "來源壞了")

        assert await verify_names({"勞動基準法"}, BrokenSource()) == {}
