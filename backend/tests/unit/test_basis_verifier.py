"""法規查證：只採完全同名。

為什麼不用模糊比對（實測 2026-10-15，全國法規索引）：
    低電壓金屬閉鎖型配電箱檢驗法 -> 商品檢驗法、民法、醫事檢驗師法
    屋內線路裝置規則            -> 中央空氣調節系統電表及線路裝置規則、兵籍規則
一個 CNS 配電箱檢驗方法的最佳候選是民法。接上去就是「有信心的錯」。

查不到同名的名稱不出現在結果裡，呼叫端據此標成「未查證」——
不是「查無此法規」。屋內線路裝置規則與建築技術規則都是真法規，
只是不以那個名稱登錄在索引裡。
"""

from app.core.enums import RegulationStatus
from app.services.basis_verifier import verify_names


class FakeSource:
    """只認完全同名的假來源；模糊候選故意給錯的，證明我們沒有用它。

    候選有兩種：
      - 無關的雜訊（「民法」）：擋得住「隨便採第一筆」。
      - 查詢名稱的近似名稱（上位、下位、帶版本後綴）：擋得住「比較寬鬆的比對」。
        只有前者的話，子字串、前綴、去掉版本後綴這類寬鬆比對全都會通過測試，
        而它們在真實索引上正是會採到錯誤法規的那幾種。
    近似候選的狀態刻意設成 REPEALED：萬一被採用，狀態也和真答案不同，一眼看得出來。
    """

    def __init__(self, known: dict[str, str], near_misses: dict[str, list[str]] | None = None):
        self.known = known
        self.near_misses = near_misses or {}
        self.queries: list[str] = []

    async def search(self, query: str):
        self.queries.append(query)
        from app.sources.base import RegulationSearchResult

        from app.core.enums import RegulationType

        results = []
        # 近似候選排在同名之前：真實索引的排序不保證同名一定在最前面，
        # 「採第一筆」與「採第一筆名稱相近的」都不能蒙混過關。
        for near_name in self.near_misses.get(query, []):
            results.append(
                RegulationSearchResult(
                    source="fake",
                    external_id=f"fake-near-{near_name}",
                    name=near_name,
                    type=RegulationType.LAW,
                    status=RegulationStatus.REPEALED,
                )
            )
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

    async def test_a_longer_name_that_contains_the_query_is_not_adopted(self):
        """上位名稱：「建築技術規則」在索引裡只有拆開的四編，沒有同名的。

        採用「建築技術規則建築構造編」是把整部規則標成其中一編的狀態。
        """
        source = FakeSource({}, {"建築技術規則": ["建築技術規則建築構造編"]})

        result = await verify_names({"建築技術規則"}, source)

        assert result == {}

    async def test_a_shorter_name_contained_in_the_query_is_not_adopted(self):
        """下位名稱：查「交通部會計檢查辦法」不能採用名稱較短的「檢查辦法」。

        反方向的子字串同樣是「有信心的錯」，只擋上位名稱不夠。
        """
        source = FakeSource({}, {"交通部會計檢查辦法": ["檢查辦法"]})

        result = await verify_names({"交通部會計檢查辦法"}, source)

        assert result == {}

    async def test_a_version_suffixed_name_is_not_adopted(self):
        """索引把舊版本登錄成「名稱（日期  訂定）」，那是另一筆，不是同名。

        採用它會把現行規則標成舊版（甚至已廢止版）的狀態。
        """
        suffixed = "中央空氣調節系統電表及線路裝置規則（91.07.17  訂定）"
        source = FakeSource({}, {"中央空氣調節系統電表及線路裝置規則": [suffixed]})

        result = await verify_names({"中央空氣調節系統電表及線路裝置規則"}, source)

        assert result == {}

    async def test_the_exact_name_wins_over_near_misses_listed_before_it(self):
        """近似候選排在前面時，仍然要找到同名那一筆，並用它的狀態。"""
        source = FakeSource(
            {"勞動基準法": RegulationStatus.ACTIVE},
            {"勞動基準法": ["勞動基準法施行細則", "勞動基準"]},
        )

        result = await verify_names({"勞動基準法"}, source)

        assert result == {"勞動基準法": RegulationStatus.ACTIVE}

    async def test_each_distinct_name_is_queried_once(self):
        """792 筆依據只有 96 個相異名稱，不要查 792 次。"""
        source = FakeSource({"勞動基準法": RegulationStatus.ACTIVE})

        await verify_names({"勞動基準法", "勞動檢查法"}, source)

        assert source.queries == ["勞動基準法", "勞動檢查法"]

    async def test_names_are_queried_in_a_fixed_order(self):
        """set 沒有順序，查詢順序必須由 verify_names 自己固定。

        用較多個名稱：只有兩個時，沒排序的 set 迭代有一半機率剛好是排好的。
        七個名稱碰巧排好的機率是 1/5040。
        """
        source = FakeSource({})
        names = {
            "職業安全衛生法",
            "勞動基準法",
            "勞動檢查法",
            "噪音管制法",
            "水污染防治法",
            "空氣污染防制法",
            "廢棄物清理法",
        }

        await verify_names(names, source)

        assert source.queries == sorted(names)

    async def test_a_source_failure_does_not_break_the_build(self):
        """來源掛掉時整張檢核表還是要產得出來，只是沒有查證狀態。"""

        class BrokenSource:
            async def search(self, query: str):
                from app.core.errors import SourceQueryError

                raise SourceQueryError("fake", "來源壞了")

        assert await verify_names({"勞動基準法"}, BrokenSource()) == {}
