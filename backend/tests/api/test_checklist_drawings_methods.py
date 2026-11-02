"""檢核表階段 2（契約圖工項比對）與階段 4（工法欄＋圖號），以示範專案驗證。

示範文件在 data/samples/project_demo/（scripts/generate_project_demo.py 產生，全部是假資料）。
"""

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
