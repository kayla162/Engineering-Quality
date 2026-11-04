"""品質計畫審查（橘框對綠框）：承攬廠商品質計畫裡的品質管理標準表，有沒有漏掉本案施工規範的可檢查標準。

邏輯圖的「結果」：品管人員把資料整合成橘框，和綠框不符的話要改。這裡只做「規範有、計畫沒寫」——
規範某一列的關鍵值（CNS 560、±6mm、25D、48 小時…）在計畫那張表裡一次都沒出現，就列出來給人看。
寫了但寫錯的值，系統判斷不了（同一個值可能寫在別的表），不做。
"""

import docx

from app.specs.chapter_reader import SpecChapterRow
from app.specs.plan_review import plan_standard_tables, review_plan


def chapter(code: str, title: str, text: str) -> SpecChapterRow:
    return SpecChapterRow(code=code, title=title, version="5.0", first_page=1, last_page=1, pages=[text])


REBAR = chapter(
    "03210", "鋼筋",
    "2. 產品 2.1 材料 2.1.1 鋼筋 鋼筋須符合CNS 560之規定。 "
    "3. 施工 3.2 施工方法 3.2.1 鋼筋加工 搭接應相距25D以上。 "
    "3.4 許可差 3.4.1 梁、柱內鋼筋之橫向位置：[±6mm]。 "
    "3.2.2 鋼筋排紮及組立 鋼筋交叉點應以黑鐵絲結紮牢固，不得以銲接為之。 4. 計量與計價",
)
CONCRETE = chapter("03310", "結構用混凝土", "3. 施工 3.2 養護 3.2.1 澆置後至少養護7天，不得受震動。 4. 計量")
FORMWORK = chapter("03110", "場鑄結構混凝土用模板", "3. 施工 3.4 拆模 3.4.1 版底模板應於澆置14天後方可拆除。 4. 計量")


def plan(tmp_path, tables: list[tuple[str, list[list[str]]]]):
    document = docx.Document()
    for caption, rows in tables:
        document.add_paragraph(caption)
        table = document.add_table(rows=0, cols=len(rows[0]))
        for row in rows:
            for cell, value in zip(table.add_row().cells, row):
                cell.text = value
    path = tmp_path / "整體品質計畫.docx"
    document.save(path)
    return path


HEADER = ["施工流程", "管理項目", "管理標準", "檢查時機", "檢查方法"]


class TestReadingThePlan:
    def test_only_quality_standard_tables_are_read(self, tmp_path):
        path = plan(tmp_path, [
            ("表 四-11 地上層鋼筋工程品質管理標準表", [HEADER, ["材料", "鋼筋", "CNS 560", "進場時", "目視"]]),
            ("表 五-1 材料設備送審管制總表", [["項次", "材料名稱"], ["1", "鋼筋"]]),
        ])
        tables = plan_standard_tables(path)
        assert [t.title for t in tables] == ["地上層鋼筋工程品質管理標準表"]
        assert "CNS560" in tables[0].text


class TestReview:
    def test_spec_values_missing_from_the_plan_are_listed(self, tmp_path):
        path = plan(tmp_path, [
            ("表 四-11 地上層鋼筋工程品質管理標準表", [HEADER, ["材料", "鋼筋", "符合CNS 560", "進場時", "目視"]]),
        ])
        (table,) = review_plan(path, [REBAR, CONCRETE, FORMWORK]).tables
        assert (table.chapter_code, table.chapter_title) == ("03210", "鋼筋")
        missing = [row.standard for row in table.missing]
        assert any("25D" in s for s in missing)
        assert any("±6mm" in s for s in missing)
        assert not any("CNS 560" in s for s in missing)
        # 「不得以銲接為之」沒有可比對的值，不判斷
        assert not any("銲接" in s for s in missing)
        assert table.judged == 3

    def test_the_subject_picks_the_chapter_that_ends_with_it(self, tmp_path):
        """「混凝土工程」要對到「結構用混凝土」，不是標題也含混凝土的「場鑄結構混凝土用模板」。"""
        path = plan(tmp_path, [
            ("表 四-12 混凝土工程品質管理標準表", [HEADER, ["施工中", "澆置", "養護7天", "完成後", "目視"]]),
            ("表 四-9 模板組立工程品質管理標準表", [HEADER, ["施工中", "拆模", "14天後", "拆模前", "目視"]]),
        ])
        review = review_plan(path, [REBAR, CONCRETE, FORMWORK])
        assert [(t.title, t.chapter_code) for t in review.tables] == [
            ("混凝土工程品質管理標準表", "03310"),
            ("模板組立工程品質管理標準表", "03110"),
        ]
        assert all(t.missing == [] for t in review.tables)

    def test_a_table_without_a_spec_chapter_is_reported_not_guessed(self, tmp_path):
        path = plan(tmp_path, [("表 四-3 假設工程品質管理標準表", [HEADER, ["施工中", "告示牌", "≧2面", "不定期", "目視"]])])
        (table,) = review_plan(path, [REBAR, CONCRETE, FORMWORK]).tables
        assert table.chapter_code is None
        assert table.missing == []
