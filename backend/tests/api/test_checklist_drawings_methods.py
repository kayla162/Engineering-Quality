"""檢核表階段 2（契約圖工項比對）與階段 4（工法欄＋圖號），以示範專案驗證。

示範文件在 data/samples/project_demo/（scripts/generate_project_demo.py 產生，全部是假資料）。
"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.core.enums import CheckResult
from app.specs.drawing_reader import is_related
from app.specs.method_reader import choose_method, method_options

DEMO = settings.DATA_DIR / "samples" / "project_demo"
MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


async def demo_project(api_client, roles: dict[str, str]) -> str:
    project_id = (await api_client.post("/api/projects", json={"name": "示範工程"})).json()["project_id"]
    for filename, role in roles.items():
        path = DEMO / filename
        files = {"file": (path.name, path.read_bytes(), MIME[path.suffix])}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}
        )
    await api_client.post(f"/api/projects/{project_id}/work-items")
    return project_id


ALL_ROLES = {
    "標單_示範.xlsx": "boq",
    "施工規範_示範.pdf": "specification",
    "契約圖_示範.pdf": "drawing",
    "需求書_示範.txt": "other",
}


@pytest.fixture
async def checklist(api_client) -> dict:
    project_id = await demo_project(api_client, ALL_ROLES)
    response = await api_client.post(f"/api/projects/{project_id}/checklist")
    assert response.status_code == 201, response.text
    body = response.json()
    body["by_no"] = {item["item_no"]: item for item in body["items"]}
    body["project_id"] = project_id
    return body


class TestReaders:
    def test_method_options_are_read_from_the_spec_sentence(self):
        text = "3.2 承包商得採用下列工法之一：(1) 鋼模 (2) 木模 (3) 系統模板。3.3 拆模"

        assert method_options(text) == ["鋼模", "木模", "系統模板"]

    def test_a_single_method_is_not_a_choice(self):
        assert method_options("3.2 模板應依設計圖組立。") == []

    def test_exactly_one_option_in_the_contract_is_selected(self):
        choice = choose_method(["鋼模", "木模"], [("需求書.txt", "外牆模板採鋼模。")])

        assert (choice.selected, "需求書.txt" in choice.evidence) == ("鋼模", True)

    def test_two_options_in_the_contract_are_not_guessed(self):
        choice = choose_method(["鋼模", "木模"], [("需求書.txt", "牆採鋼模，板採木模。")])

        assert choice.selected is None
        assert "無法判斷" in choice.evidence

    @pytest.mark.parametrize(
        "item,title,related",
        [
            ("普通模板，普通模板含組立", "模板組立詳圖", True),
            ("鋼筋，SD420W 含加工及組立", "鋼筋續接詳圖", True),
            # 共用「組立」兩字，但主要名詞不同
            ("鋼筋，SD420W 含加工及組立", "模板組立詳圖", False),
            ("預拌混凝土，210kgf/cm2", "結構平面圖", False),
        ],
    )
    def test_drawing_titles_match_conservatively(self, item, title, related):
        assert is_related(item, title) is related


class TestDemoProject:
    async def test_a_drawn_item_with_a_specified_method_is_ok(self, checklist):
        row = checklist["by_no"]["壹.一.1.2.1"]

        assert row["result"] == CheckResult.OK
        assert [d["sheet_no"] for d in row["drawings"]] == ["S-02"]
        assert row["method"]["selected"] == "系統模板"
        assert "需求書_示範.txt" in row["method"]["evidence"]

    async def test_an_unspecified_method_asks_for_review_with_the_drawing(self, checklist):
        row = checklist["by_no"]["壹.一.1.2.2"]

        assert row["result"] == CheckResult.METHOD_UNDECIDED
        assert row["method"]["options"] == ["搭接", "續接器", "銲接"]
        assert row["method"]["selected"] is None
        assert [d["sheet_no"] for d in row["drawings"]] == ["S-03"]

    async def test_an_item_with_no_drawing_is_flagged(self, checklist):
        row = checklist["by_no"]["壹.一.1.2.3"]

        assert row["result"] == CheckResult.BOQ_NOT_IN_DRAWINGS
        assert row["drawings"] == []

    async def test_general_requirements_are_not_expected_on_drawings(self, checklist):
        """施工測量、安全衛生（01 類）本來就不畫在圖上，不該標成契約圖沒有。"""
        for item_no in ("壹.一.1.1.1", "壹.一.1.1.2"):
            assert CheckResult.BOQ_NOT_IN_DRAWINGS not in checklist["by_no"][item_no]["issues"]

    async def test_a_drawing_with_no_item_is_listed_at_project_level(self, checklist):
        assert checklist["has_drawings"] is True
        assert [d["sheet_no"] for d in checklist["drawings_without_items"]] == ["A-08", "S-01"]

    async def test_issues_are_listed_in_priority_order(self, checklist):
        """原 spec 第 6 節：工項來源不一致 > 工法未定 > 依據不全。"""
        priority = [
            CheckResult.BOQ_NOT_IN_DRAWINGS,
            CheckResult.METHOD_UNDECIDED,
            CheckResult.SPEC_NOT_INCLUDED,
            CheckResult.NEEDS_CONFIRMATION,
        ]
        for row in checklist["items"]:
            assert row["issues"] == sorted(row["issues"], key=priority.index)
            assert row["result"] == (row["issues"][0] if row["issues"] else CheckResult.OK)

    async def test_the_summary_adds_up(self, checklist):
        summary = checklist["summary"]

        assert sum(summary.values()) == checklist["total"]
        assert summary["boq_not_in_drawings"] == 1
        assert summary["method_undecided"] == 1

    async def test_get_returns_what_post_built(self, api_client, checklist):
        stored = (await api_client.get(f"/api/projects/{checklist['project_id']}/checklist")).json()

        for item in stored["items"]:
            built = checklist["by_no"][item["item_no"]]
            assert (item["result"], item["drawings"], item["method"]) == (
                built["result"],
                built["drawings"],
                built["method"],
            )
        assert stored["drawings_without_items"] == checklist["drawings_without_items"]


class TestWithoutDrawings:
    async def test_no_drawing_means_no_stage_two_judgement(self, api_client):
        roles = {k: v for k, v in ALL_ROLES.items() if v != "drawing"}
        project_id = await demo_project(api_client, roles)

        body = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()

        assert body["has_drawings"] is False
        assert body["summary"]["boq_not_in_drawings"] == 0
        # 工法欄不需要契約圖：鋼筋仍是未指定
        by_no = {item["item_no"]: item for item in body["items"]}
        assert by_no["壹.一.1.2.2"]["result"] == CheckResult.METHOD_UNDECIDED
        assert by_no["壹.一.1.2.2"]["drawings"] == []


def scanned_pdf() -> bytes:
    """只有一張點陣圖的 PDF：掃描的契約圖，標題欄讀不到。"""
    import pymupdf

    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 140), False)
    image.clear_with(200)
    doc = pymupdf.open()
    doc.new_page(width=1191, height=842).insert_image(pymupdf.Rect(0, 0, 1191, 842), pixmap=image)
    return doc.tobytes()


class TestUnreadableDrawings:
    """掃描的契約圖讀到零張圖時，不能把每個工項都判成「標單有，契約圖沒有」。"""

    async def test_no_sheets_read_means_no_stage_two_judgement_and_a_warning(self, api_client):
        roles = {k: v for k, v in ALL_ROLES.items() if v != "drawing"}
        project_id = await demo_project(api_client, roles)
        files = {"file": ("掃描契約圖.pdf", scanned_pdf(), "application/pdf")}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": "drawing"}
        )

        built = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()
        read_back = (await api_client.get(f"/api/projects/{project_id}/checklist")).json()

        for body in (built, read_back):
            assert body["has_drawings"] is False
            assert body["summary"]["boq_not_in_drawings"] == 0
            assert "讀不到" in body["drawing_warning"]

    async def test_readable_drawings_have_no_warning(self, checklist):
        assert checklist["drawing_warning"] is None


def boq_with_indirect_costs() -> bytes:
    """真實標單的結構：「壹.一 直接工程費」之外還有環保、職安、品管、保險、利潤、稅捐。"""
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "契約詳細表"
    for row in [
        ["示範市政府（假資料）", "", "", "", "", "", ""],
        ["詳細價目表[契約]", "", "", "", "", "", ""],
        ["項 次", "項  目  及  說  明", "單 位", "數 量", "單 價", "複 價", "編碼(備註)"],
        ["壹", "發包工程費", "", "", "", "", ""],
        ["壹.一", "直接工程費", "", "", "", "", ""],
        ["壹.一.1.1", "預拌混凝土，210kgf/cm2", "M3", 420, 2600, 1092000, "0331000004"],
        ["壹.二", "環保清潔費(壹.一*0.2%)", "式", 1, 2184, 2184, ""],
        ["壹.三", "職業安全衛生管理及設施費", "", "", "", "", ""],
        ["壹.三.1", "職業安全衛生管理費(含行政管理費)", "式", 1, 50000, 50000, ""],
        ["壹.七", "稅捐((壹.一 ~ 壹.六)*5%)", "式", 1, 60000, 60000, ""],
    ]:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class TestIndirectCosts:
    """間接工程費（環保、職安、稅捐…）本來就不畫在圖上，只有直接工程費的工項要比對契約圖。"""

    async def test_only_direct_cost_items_are_expected_on_drawings(self, api_client):
        project_id = (await api_client.post("/api/projects", json={"name": "示範工程"})).json()["project_id"]
        uploads = {
            ("標單.xlsx", boq_with_indirect_costs(), MIME[".xlsx"]): "boq",
            ("契約圖_示範.pdf", (DEMO / "契約圖_示範.pdf").read_bytes(), MIME[".pdf"]): "drawing",
        }
        for (name, content, mime), role in uploads.items():
            document_id = (
                await api_client.post("/api/documents/upload", files={"file": (name, content, mime)})
            ).json()["document_id"]
            await api_client.post(
                f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}
            )
        await api_client.post(f"/api/projects/{project_id}/work-items")

        body = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()
        flagged = {
            item["item_no"] for item in body["items"] if CheckResult.BOQ_NOT_IN_DRAWINGS in item["issues"]
        }

        assert flagged == {"壹.一.1.1"}


def boq_with_sections() -> bytes:
    """真實標單的層次：直接工程費 > 水電工程 > 開關箱設備工程（分項）> 計價工項。"""
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "契約詳細表"
    for row in [
        ["示範市政府（假資料）", "", "", "", "", "", ""],
        ["詳細價目表[契約]", "", "", "", "", "", ""],
        ["項 次", "項  目  及  說  明", "單 位", "數 量", "單 價", "複 價", "編碼(備註)"],
        ["壹", "發包工程費", "", "", "", "", ""],
        ["壹.一", "直接工程費", "", "", "", "", ""],
        ["壹.一.2", "水電工程", "", "", "", "", ""],
        ["壹.一.2.1", "開關箱設備工程", "", "", "", "", ""],
        ["壹.一.2.1.1", "KW-MP PANEL", "面", 1, 50000, 50000, ""],
        ["壹.一.2.1.2", "L2 PANEL", "面", 1, 30000, 30000, ""],
        ["壹.一.2.2", "給水設備工程", "", "", "", "", ""],
        ["壹.一.2.2.1", "PVC管 1吋", "M", 30, 100, 3000, ""],
    ]:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def drawing_pdf(sheets: list[tuple[str, str]]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for sheet_no, title in sheets:
        page = doc.new_page(width=842, height=595)
        page.insert_text((600, 540), f"圖號：{sheet_no}", fontname="china-t", fontsize=9)
        page.insert_text((600, 555), f"圖名：{title}", fontname="china-t", fontsize=9)
    return doc.tobytes()


async def project_with(api_client, uploads: list[tuple[str, bytes, str]]) -> dict:
    project_id = (await api_client.post("/api/projects", json={"name": "示範工程"})).json()["project_id"]
    for name, content, role in uploads:
        mime = MIME[Path(name).suffix]
        document_id = (
            await api_client.post("/api/documents/upload", files={"file": (name, content, mime)})
        ).json()["document_id"]
        await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}
        )
    await api_client.post(f"/api/projects/{project_id}/work-items")
    built = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()
    read_back = (await api_client.get(f"/api/projects/{project_id}/checklist")).json()
    for body in (built, read_back):
        body["by_no"] = {item["item_no"]: item for item in body["items"]}
    assert built["summary"] == read_back["summary"]
    return read_back


class TestSectionLevelDrawings:
    """真實標單的計價工項（「KW-MP PANEL」）對不到圖名；契約圖對應的是分項（「開關箱設備工程」）。"""

    async def test_an_item_is_covered_by_a_sheet_of_its_section(self, api_client):
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("水電圖.pdf", drawing_pdf([("E3-01", "開關箱單線圖")]), "drawing"),
        ])

        for item_no in ("壹.一.2.1.1", "壹.一.2.1.2"):
            item = body["by_no"][item_no]
            assert [d["sheet_no"] for d in item["drawings"]] == ["E3-01"]
            assert CheckResult.BOQ_NOT_IN_DRAWINGS not in item["issues"]
        # 給水設備沒有任何圖
        assert CheckResult.BOQ_NOT_IN_DRAWINGS in body["by_no"]["壹.一.2.2.1"]["issues"]
        assert body["drawings_without_items"] == []

    async def test_the_discipline_level_is_too_broad_to_count(self, api_client):
        """「水電工程」這一層太粗：「水電配置圖」不代表開關箱有畫。"""
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("水電圖.pdf", drawing_pdf([("E0-01", "水電配置圖")]), "drawing"),
        ])

        assert CheckResult.BOQ_NOT_IN_DRAWINGS in body["by_no"]["壹.一.2.1.1"]["issues"]


class TestSeveralDrawingSets:
    """契約圖常分成建築、結構、水電好幾冊，每一冊都要讀。"""

    async def test_sheets_from_every_drawing_document_count(self, api_client):
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("水電圖-電氣.pdf", drawing_pdf([("E3-01", "開關箱單線圖")]), "drawing"),
            ("水電圖-給水.pdf", drawing_pdf([("P1-01", "給水設備系統圖")]), "drawing"),
        ])

        assert body["summary"]["boq_not_in_drawings"] == 0
        assert [d["sheet_no"] for d in body["by_no"]["壹.一.2.2.1"]["drawings"]] == ["P1-01"]

    async def test_an_unreadable_set_is_named_and_the_others_still_count(self, api_client):
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("水電圖-電氣.pdf", drawing_pdf([("E3-01", "開關箱單線圖")]), "drawing"),
            ("結構圖-掃描.pdf", scanned_pdf(), "drawing"),
        ])

        assert body["has_drawings"] is True
        assert "結構圖-掃描.pdf" in body["drawing_warning"]
        assert CheckResult.BOQ_NOT_IN_DRAWINGS not in body["by_no"]["壹.一.2.1.1"]["issues"]


CONTRACT = (
    "本契約文件及效力： 一、 本契約包括下列文件：\n"
    "假設工程之組立及拆除： 一、 模板支撐等假設工程之組立及拆除，施工前應妥為設計。\n"
    "工程品質： 一、 開關箱應於送電前會同監造單位檢查。\n"
)


class TestContractColumn:
    """預期表每個工項都有「契約」欄：契約書提到它（或它所屬分項）的地方，附頁碼與前面最近的標題。"""

    async def test_contract_mentions_are_listed_per_item(self, api_client):
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("契約書.txt", CONTRACT.encode(), "contract"),
        ])

        refs = body["by_no"]["壹.一.2.1.1"]["contract_refs"]
        assert [(r["heading"], r["keyword"]) for r in refs] == [("工程品質", "開關箱")]
        assert "開關箱應於送電前" in refs[0]["excerpt"]
        assert body["by_no"]["壹.一.2.2.1"]["contract_refs"] == []

    async def test_contract_mentions_do_not_change_the_result(self, api_client):
        without = await project_with(api_client, [("標單.xlsx", boq_with_sections(), "boq")])
        project_id = (await api_client.get("/api/projects")).json()["items"][0]["project_id"]
        files = {"file": ("契約書.txt", CONTRACT.encode(), "text/plain")}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": "contract"}
        )
        with_contract = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()

        assert any(item["contract_refs"] for item in with_contract["items"])
        assert with_contract["summary"] == without["summary"]


class TestQualityStandardDraft:
    """橘框表單的第一種：品質管理標準表初稿，從本案施工規範的一章擷取。"""

    async def test_a_chapter_draft_and_its_excel(self, api_client, checklist):
        project_id = checklist["project_id"]

        draft = (await api_client.get(f"/api/projects/{project_id}/quality-standards/03210")).json()
        assert draft["title"] == "鋼筋工程品質管理標準表（初稿）"
        assert "初稿" in draft["notice"]
        assert draft["columns"][0] == "施工流程"

        response = await api_client.get(f"/api/projects/{project_id}/quality-standards/03210/export")
        assert response.status_code == 200
        from io import BytesIO

        from openpyxl import load_workbook

        sheet = load_workbook(BytesIO(response.content)).active
        texts = [str(c.value) for row in sheet.iter_rows(max_row=4) for c in row if c.value]
        assert "鋼筋工程品質管理標準表（初稿）" in texts
        assert any("初稿" in t and "品管人員" in t for t in texts)
        assert "管理標準" in texts

    async def test_the_self_inspection_and_supervision_drafts(self, api_client, checklist):
        """同一章的自主檢查表（承攬廠商）與抽查標準表（監造）初稿，都從品質管理標準表初稿衍生。"""
        from io import BytesIO

        from openpyxl import load_workbook

        base = f"/api/projects/{checklist['project_id']}/quality-standards/03210"
        own = await api_client.get(f"{base}/self-inspection/export")
        supervision = await api_client.get(f"{base}/supervision/export")

        assert own.status_code == supervision.status_code == 200
        own_texts = [str(c.value) for r in load_workbook(BytesIO(own.content)).active.iter_rows() for c in r if c.value]
        assert "鋼筋工程施工自主檢查表（初稿）" in own_texts
        assert load_workbook(BytesIO(supervision.content)).sheetnames == ["施工抽查標準表", "材料抽驗標準表"]

    async def test_the_method_statement_draft_is_a_word_file(self, api_client, checklist):
        """施工要領初稿：施工方法取自規範第3節，使用材料取自標單裡屬於這一章的工項。"""
        from io import BytesIO

        import docx

        response = await api_client.get(
            f"/api/projects/{checklist['project_id']}/quality-standards/03210/method-statement/export"
        )
        assert response.status_code == 200
        paragraphs = docx.Document(BytesIO(response.content)).paragraphs
        text = " ".join(p.text for p in paragraphs)
        assert "鋼筋工程施工要領（初稿）" in text
        assert "鋼筋，SD420W 含加工及組立" in text  # 示範標單裡計價代碼 03210 的工項

    async def test_function_tests_are_only_for_equipment_chapters(self, api_client, checklist):
        response = await api_client.get(
            f"/api/projects/{checklist['project_id']}/quality-standards/03210/function-test/export"
        )
        assert response.status_code == 400
        assert "不是機電設備章" in response.json()["error"]["message"]

    async def test_an_unknown_chapter_is_404(self, api_client, checklist):
        response = await api_client.get(f"/api/projects/{checklist['project_id']}/quality-standards/99999")
        assert response.status_code == 404


class TestQualityPlanReview:
    """品質計畫審查（橘框對綠框）：掛成「品質計畫」的 docx，和本案施工規範比對。"""

    async def test_the_review_lists_what_the_plan_left_out(self, api_client, checklist):
        import io

        import docx
        from openpyxl import load_workbook

        document = docx.Document()
        document.add_paragraph("表 四-11 鋼筋工程品質管理標準表")
        table = document.add_table(rows=2, cols=3)
        for cell, value in zip(table.rows[0].cells, ["管理項目", "管理標準", "檢查方法"]):
            cell.text = value
        for cell, value in zip(table.rows[1].cells, ["鋼筋", "符合 CNS 560", "目視"]):
            cell.text = value
        buffer = io.BytesIO()
        document.save(buffer)
        files = {"file": ("整體品質計畫.docx", buffer.getvalue(),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        project_id = checklist["project_id"]
        attached = await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": "quality_plan"}
        )
        assert attached.status_code < 300, attached.text

        response = await api_client.get(f"/api/projects/{project_id}/quality-plan-review/export")

        assert response.status_code == 200
        book = load_workbook(io.BytesIO(response.content))
        assert book.sheetnames == ["審查摘要", "計畫沒寫到的規範標準"]
        summary = [[c.value for c in row] for row in book["審查摘要"].iter_rows(min_row=4)]
        assert summary[0][:2] == ["鋼筋工程品質管理標準表", "第03210章 鋼筋"]

    async def test_without_a_quality_plan_it_says_what_to_attach(self, api_client, checklist):
        response = await api_client.get(f"/api/projects/{checklist['project_id']}/quality-plan-review/export")
        assert response.status_code == 400
        assert "品質計畫" in response.json()["error"]["message"]


class TestCrossRuleReminders:
    """法規雙重規範提醒：標單或契約圖觸發示範目錄裡的規則。"""

    async def test_boq_items_and_drawings_trigger_reminders(self, api_client):
        body = await project_with(api_client, [
            ("標單.xlsx", boq_with_sections(), "boq"),
            ("建築圖.pdf", drawing_pdf([("A2-04", "屋頂女兒牆詳圖"), ("A5-01", "電梯平面圖")]), "drawing"),
        ])
        project_id = (await api_client.get("/api/projects")).json()["items"][0]["project_id"]
        reminders = (await api_client.get(f"/api/projects/{project_id}/cross-rule-reminders")).json()

        assert body["total"] == 3
        by_title = {r["title"]: r for r in reminders}
        assert by_title["屋頂欄杆、女兒牆的高度"]["evidence"] == ["契約圖：A2-04 屋頂女兒牆詳圖"]
        assert "使用者提供" in by_title["屋頂欄杆、女兒牆的高度"]["provenance"]
        assert "電梯同時是無障礙昇降機" in by_title


class TestPlanDrafts:
    """整體品質計畫與監造計畫初稿：標單用到的每一章規範，各章橘框表單組成一份 Word。"""

    async def test_both_plans_download_as_word(self, api_client, checklist):
        from io import BytesIO

        import docx

        for kind, heading in (("quality-plan", "五、品質管理標準"), ("supervision-plan", "五、施工抽查程序及標準")):
            response = await api_client.get(f"/api/projects/{checklist['project_id']}/plans/{kind}/export")
            assert response.status_code == 200, response.text
            headings = [p.text for p in docx.Document(BytesIO(response.content)).paragraphs if p.style.name.startswith("Heading")]
            assert heading in headings
            # 示範標單用到 03110、03210、03310 等章，每章都有
            assert any("鋼筋" in h for h in headings)

    async def test_an_unknown_plan_is_404(self, api_client, checklist):
        response = await api_client.get(f"/api/projects/{checklist['project_id']}/plans/other/export")
        assert response.status_code == 404
