"""完整示範專案（data/samples/full_demo/，scripts/generate_full_demo.py 產生，全部是假資料）：
一個專案走過檢核表、契約欄、法規雙重規範提醒、功能運轉、品質計畫審查與計畫初稿。

水電圖是掃描版面（整頁圖片），要 OCR 才讀得到；測試環境預設關 OCR，所以分成兩組。
"""

import io

import pytest

from app.core.config import settings
from app.core.enums import CheckResult

DEMO = settings.DATA_DIR / "samples" / "full_demo"
ROLES = {
    "標單_完整示範.xlsx": "boq",
    "施工規範_完整示範.pdf": "specification",
    "契約書_完整示範.docx": "contract",
    "需求書_完整示範.txt": "other",
    "建築結構圖_完整示範.pdf": "drawing",
    "水電圖_完整示範.pdf": "drawing",
    "整體品質計畫_完整示範.docx": "quality_plan",
}
MIME = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


async def build_demo(api_client) -> dict:
    project_id = (await api_client.post("/api/projects", json={"name": "完整示範"})).json()["project_id"]
    for filename, role in ROLES.items():
        path = DEMO / filename
        files = {"file": (path.name, path.read_bytes(), MIME[path.suffix])}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        attached = await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}
        )
        assert attached.status_code < 300, attached.text
    await api_client.post(f"/api/projects/{project_id}/work-items")
    response = await api_client.post(f"/api/projects/{project_id}/checklist")
    assert response.status_code == 201, response.text
    body = response.json()
    body["by_no"] = {item["item_no"]: item for item in body["items"]}
    body["project_id"] = project_id
    return body


@pytest.fixture
async def demo(api_client) -> dict:
    return await build_demo(api_client)


class TestChecklist:
    async def test_every_priced_item_is_a_work_item(self, demo):
        assert demo["total"] == 16

    async def test_methods_drawings_and_missing_drawings(self, demo):
        formwork, rebar, concrete = (demo["by_no"][f"壹.一.1.2.{i}"] for i in (1, 2, 3))
        assert formwork["method"]["selected"] == "系統模板"
        assert [d["sheet_no"] for d in formwork["drawings"]] == ["S-02"]
        assert rebar["result"] == CheckResult.METHOD_UNDECIDED
        assert concrete["result"] == CheckResult.BOQ_NOT_IN_DRAWINGS

    async def test_finishing_items_find_their_detail_drawings(self, demo):
        expected = {
            "壹.一.1.3.1": "A3-01", "壹.一.1.3.2": "A5-01", "壹.一.1.3.3": "A6-01", "壹.一.1.3.4": "A7-01",
            "壹.一.1.3.5": "A4-01",
        }
        for item_no, sheet_no in expected.items():
            assert sheet_no in [d["sheet_no"] for d in demo["by_no"][item_no]["drawings"]], item_no

    async def test_a_drawing_without_items_is_listed(self, demo):
        assert "A8-01" in [d["sheet_no"] for d in demo["drawings_without_items"]]

    async def test_indirect_costs_are_not_judged_against_drawings(self, demo):
        assert CheckResult.BOQ_NOT_IN_DRAWINGS not in demo["by_no"]["壹.二.1"]["issues"]

    async def test_the_word_contract_is_cited_by_article(self, demo):
        refs = demo["by_no"]["壹.一.1.2.2"]["contract_refs"]
        assert any(ref["heading"].startswith("第11條 履約品管") for ref in refs)


class TestReminders:
    async def test_all_six_cross_rules_fire(self, api_client, demo):
        reminders = (await api_client.get(f"/api/projects/{demo['project_id']}/cross-rule-reminders")).json()
        assert len(reminders) == 6


class TestDrafts:
    async def test_lift_test_rows_come_from_the_spec(self, api_client, demo):
        from openpyxl import load_workbook

        response = await api_client.get(
            f"/api/projects/{demo['project_id']}/quality-standards/14210/function-test/export"
        )
        assert response.status_code == 200
        rows = [[c.value for c in row] for row in load_workbook(io.BytesIO(response.content)).worksheets[0].iter_rows(min_row=4)]
        assert [row[1] for row in rows] == ["著樓試驗", "安全裝置試驗", "載重試驗"]

    async def test_a_chapter_without_tests_uses_the_generic_template(self, api_client, demo):
        from openpyxl import load_workbook

        response = await api_client.get(
            f"/api/projects/{demo['project_id']}/quality-standards/16411/function-test/export"
        )
        rows = [[c.value for c in row] for row in load_workbook(io.BytesIO(response.content)).worksheets[0].iter_rows(min_row=4)]
        assert rows and all(str(row[-1]).startswith("通用範本") for row in rows)

    async def test_the_plan_review_finds_the_planted_gaps(self, api_client, demo):
        from openpyxl import load_workbook

        response = await api_client.get(f"/api/projects/{demo['project_id']}/quality-plan-review/export")
        assert response.status_code == 200
        book = load_workbook(io.BytesIO(response.content))
        missing = " ".join(str(c.value) for row in book["計畫沒寫到的規範標準"].iter_rows() for c in row)
        assert "40D" in missing and "CNS 1232" in missing
        summary = [[c.value for c in row] for row in book["審查摘要"].iter_rows(min_row=4)]
        assert ["假設工程品質管理標準表", "本案規範沒有對應的章"] in [row[:2] for row in summary]

    async def test_both_plans_download(self, api_client, demo):
        for kind in ("quality-plan", "supervision-plan"):
            response = await api_client.get(f"/api/projects/{demo['project_id']}/plans/{kind}/export")
            assert response.status_code == 200, kind


def _ocr_available() -> bool:
    from app.parsers import ocr

    original = settings.ENABLE_OCR
    settings.ENABLE_OCR = True
    try:
        return ocr.load_engine()[0] is not None
    finally:
        settings.ENABLE_OCR = original


@pytest.mark.skipif(not _ocr_available(), reason="這台機器沒有 Tesseract 繁中語言資料")
async def test_the_scanned_mep_set_is_read_by_ocr_and_switchboards_find_the_single_line_diagram(
    api_client, monkeypatch
):
    monkeypatch.setattr(settings, "ENABLE_OCR", True)
    demo = await build_demo(api_client)
    assert demo["drawing_warning"] is None
    # 開關箱（KW-MP PANEL）畫在電氣單線圖上。圖名兩行，只有 fast 模型時（CI）第一行「電氣單線圖」
    # 可能讀不到、只剩「負載表(1)」——兩個都算開關箱的圖，所以照樣對得到
    panel = demo["by_no"]["壹.一.2.1.1"]
    assert [d["sheet_no"] for d in panel["drawings"]] == ["E-01"]
    assert any(word in panel["drawings"][0]["title"] for word in ("單線圖", "負載表"))
    assert all(d["is_ocr"] for d in panel["drawings"])
    # 圖號 OCR 讀不到的寫「第N頁」，圖名照樣對得到
    lift = demo["by_no"]["壹.一.2.4.1"]
    assert [d["title"] for d in lift["drawings"]] == ["昇降機平面詳圖"]


async def test_the_project_lists_its_documents_and_roles(api_client, demo):
    response = await api_client.get(f"/api/projects/{demo['project_id']}/documents")
    assert response.status_code == 200
    assert [(d["filename"], d["role"]) for d in response.json()] == list(ROLES.items())
