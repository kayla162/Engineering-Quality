"""整體品質計畫與監造計畫初稿：把各章的橘框表單初稿組成一份計畫（需求說明第 4 點：「離完整的整體品質計畫、
監造計畫不遠了，差在部分內容需要使用者提供」）。章節照秀山整體品質計畫的目錄；系統產生不了的章寫「（待填）」。
"""

import io

import docx

from app.specs.chapter_reader import SpecChapterRow
from app.specs.plan_assembly import quality_plan_docx, supervision_plan_docx

REBAR = SpecChapterRow(
    code="03210", title="鋼筋", version="5.0", first_page=1, last_page=1,
    pages=["2. 產品 2.1 材料 2.1.1 鋼筋 鋼筋須符合CNS 560之規定。 "
           "3. 施工 3.2 施工方法 3.2.1 鋼筋加工 所有鋼筋應在常溫下彎曲，不得加熱。 "
           "3.4 許可差 3.4.1 梁、柱內鋼筋之橫向位置：[±6mm]。 4. 計量與計價"],
)
GROUNDING = SpecChapterRow(
    code="16061", title="接地", version="5.0", first_page=1, last_page=1,
    pages=["3. 施工 3.5 現場測試 3.5.1 接地電阻值應小於10Ω。 4. 計量與計價"],
)
MATERIALS = {"03210": ["鋼筋，SD420W，高拉力鋼筋"], "16061": ["接地銅棒"]}


def text_of(content: bytes) -> tuple[list[str], str]:
    document = docx.Document(io.BytesIO(content))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    body = "\n".join(p.text for p in document.paragraphs)
    body += "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
    return headings, body


class TestQualityPlan:
    def content(self):
        return text_of(quality_plan_docx("秀山分隊興建工程", [REBAR, GROUNDING], MATERIALS))

    def test_chapters_follow_the_quality_plan(self):
        headings, _ = self.content()
        main = [h for h in headings if h[:2] in ("一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")]
        assert main == [
            "一、計畫範圍", "二、管理權責及分工", "三、品管組織及工作職掌", "四、施工要領", "五、品質管理標準",
            "六、材料及施工檢驗程序", "七、設備功能運轉檢測程序及標準", "八、自主檢查表", "九、不合格品之管制",
            "十、矯正與預防措施、內部品質稽核及文件紀錄管理",
        ]

    def test_generated_chapters_carry_each_spec_chapter(self):
        headings, body = self.content()
        assert "鋼筋工程施工要領（初稿）" in headings
        assert "鋼筋工程品質管理標準表（初稿）" in headings
        assert "梁、柱內鋼筋之橫向位置：±6mm。" in body
        assert "鋼筋，SD420W，高拉力鋼筋" in body
        # 設備功能運轉只有機電章
        assert "接地功能運轉檢測標準表（初稿）" in headings
        assert "鋼筋功能運轉檢測標準表（初稿）" not in headings

    def test_what_the_system_cannot_write_is_left_for_the_user(self):
        _, body = self.content()
        assert body.count("（待填") >= 4
        assert "秀山分隊興建工程" in body
        assert "初稿" in body


class TestSupervisionPlan:
    def test_chapters_follow_the_supervision_plan(self):
        headings, body = text_of(supervision_plan_docx("秀山分隊興建工程", [REBAR, GROUNDING], MATERIALS))
        for expected in ("材料設備抽驗程序及標準", "施工抽查程序及標準", "設備功能運轉測試抽驗程序及標準"):
            assert any(expected in h for h in headings), expected
        assert "鋼筋工程施工抽查標準表（初稿）" in headings
        assert "抽查標準（定量／定性）" in body
        assert "接地功能運轉測試抽驗標準表（初稿）" in headings
