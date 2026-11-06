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


def test_the_demo_version_has_no_blanks_and_marks_what_it_filled():
    for build in (quality_plan_docx, supervision_plan_docx):
        headings, body = text_of(build("秀山分隊興建工程", [REBAR, GROUNDING], MATERIALS, demo=True))
        assert "（待填" not in body
        assert "【示範】" in body and "（示範）" in body
        assert "（初稿・示範補正）" in body


class TestContractorProcedures:
    """組織與程序章節用承攬廠商自己的品質管理程序範本（data/contractor_procedures.json），標「【承攬廠商範本】」。"""

    def sections(self, build, demo=False):
        document = docx.Document(io.BytesIO(build("秀山分隊興建工程", [REBAR, GROUNDING], MATERIALS, demo=demo)))
        sections, current = {}, None
        for paragraph in document.paragraphs:
            if paragraph.style.name == "Heading 1":
                current = paragraph.text
                sections[current] = []
            elif current:
                sections[current].append(paragraph.text)
        return {heading: "\n".join(texts) for heading, texts in sections.items()}

    def test_the_three_tier_duties_fill_the_responsibility_chapter(self):
        text = self.sections(quality_plan_docx)["二、管理權責及分工"]
        assert "【承攬廠商範本】" in text
        assert "10.建立文件紀錄管理系統" in text and "三級品管（主辦機關）" in text
        # 範本沒涵蓋的部分仍留給使用者
        assert "（待填：本案協力廠商的權責分工）" in text

    def test_procedures_introduce_the_inspection_and_self_check_chapters(self):
        sections = self.sections(quality_plan_docx)
        assert "材料品質查驗紀錄表" in sections["六、材料及施工檢驗程序"]
        assert "檢驗停留點" in sections["八、自主檢查表"]
        assert "不合格品改善追蹤表" in sections["九、不合格品之管制"]
        assert "（待填" not in sections["九、不合格品之管制"]

    def test_the_supervision_plan_uses_the_supervisor_side(self):
        sections = self.sections(supervision_plan_docx)
        assert "二級品管" in sections["二、監造組織及權責分工"]
        assert "會同檢驗" in sections["四、材料設備抽驗程序及標準"]
        assert "加強查驗" in sections["五、施工抽查程序及標準"]

    def test_no_company_or_agency_names_are_copied(self):
        for build in (quality_plan_docx, supervision_plan_docx):
            text = "\n".join(self.sections(build).values())
            assert "營造工程有限公司" not in text and "建築師事務所" not in text and "工程處" not in text

    def test_demo_fills_only_what_the_template_leaves_blank(self):
        sections = self.sections(quality_plan_docx, demo=True)
        responsibility = sections["二、管理權責及分工"]
        assert "【承攬廠商範本】" in responsibility and "【示範】" in responsibility
        assert "（待填" not in responsibility
        # 範本已涵蓋的章不再疊示範文字
        assert "【示範】" not in sections["九、不合格品之管制"]
