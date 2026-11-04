"""秀山分隊興建工程的完整檢核表：真實標單、施工規範、契約書，加上示範契約圖（假資料）。

真實文件在 工程文書/（不進版控），沒有時整個檔案略過；PCCES 目錄（data/pcces_index.json）
也是同步產生的，沒有時同樣略過。數字是 2026-11 實測的結果，變了代表比對行為變了——
先確認是改善還是退步，再更新這裡。

第 1、3 階段（工項、依據）與契約欄全部是真實資料，鎖住摘要數字。第 2 階段（契約圖）一般測試用
示範圖，只鎖「讀得到、間接工程費不被判成契約圖沒有」；真實的三冊掃描契約圖要 OCR 約 12 分鐘，
設 XIUSHAN_OCR=1 才跑（test_the_real_scanned_drawings）。
"""

import os

import pytest

from app.core.config import settings
from app.core.enums import CheckResult
from app.sources import reset_sources

DOCS = settings.DATA_DIR.parent / "工程文書"
BOQ, SPEC, CONTRACT = DOCS / "2.契約書.xls", DOCS / "13.施工規範.pdf", DOCS / "1.契約書.pdf"
DRAWINGS = settings.DATA_DIR / "samples" / "xiushan_contract_drawings_demo.pdf"
PCCES = settings.DATA_DIR / "pcces_index.json"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in (BOQ, SPEC, CONTRACT, PCCES)),
    reason="沒有 工程文書/ 的真實文件或 data/pcces_index.json（都不進版控）",
)


@pytest.fixture(autouse=True)
def real_sources(monkeypatch):
    monkeypatch.setattr(settings, "PCCES_INDEX_PATH", PCCES)
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "taiwan_law,pcces,admin_rules,mock")
    monkeypatch.setattr(settings, "ENABLE_OCR", False)
    reset_sources()
    yield
    reset_sources()


async def build(api_client, with_drawings: bool) -> dict:
    roles = {BOQ: "boq", SPEC: "specification", CONTRACT: "contract"}
    if with_drawings:
        roles[DRAWINGS] = "drawing"
    project_id = (await api_client.post("/api/projects", json={"name": "秀山分隊興建工程"})).json()["project_id"]
    for path, role in roles.items():
        files = {"file": (path.name, path.read_bytes(), "application/octet-stream")}
        response = await api_client.post("/api/documents/upload", files=files)
        assert response.status_code == 201, response.text
        await api_client.post(
            f"/api/projects/{project_id}/documents",
            json={"document_id": response.json()["document_id"], "role": role},
        )
    await api_client.post(f"/api/projects/{project_id}/work-items")
    response = await api_client.post(f"/api/projects/{project_id}/checklist")
    assert response.status_code == 201, response.text
    body = response.json()
    body["by_no"] = {item["item_no"]: item for item in body["items"]}
    return body


async def test_work_items_and_bases_from_the_real_documents(api_client):
    body = await build(api_client, with_drawings=False)

    assert body["total"] == 1028
    assert body["has_drawings"] is False
    assert body["spec_warning"] is None
    assert body["summary"] == {
        "ok": SUMMARY_OK,
        "spec_not_included": SUMMARY_SPEC_NOT_INCLUDED,
        "needs_confirmation": SUMMARY_NEEDS_CONFIRMATION,
        "boq_not_in_drawings": 0,
        "method_undecided": SUMMARY_METHOD_UNDECIDED,
    }


async def test_only_rebar_items_have_a_method_column(api_client):
    body = await build(api_client, with_drawings=False)

    with_method = [item for item in body["items"] if item["method"]]
    assert {item["chapter_code"] for item in with_method} == {"03210"}
    assert {tuple(item["method"]["options"]) for item in with_method} == {("搭接", "銲接", "機械式續接")}
    # 契約書沒有指定續接方式
    assert all(item["method"]["selected"] is None for item in with_method)


async def test_the_demo_drawings_are_read_and_indirect_costs_are_not_flagged(api_client):
    body = await build(api_client, with_drawings=True)

    assert body["has_drawings"] is True
    assert body["drawing_warning"] is None
    indirect = [item for item in body["items"] if not item["item_no"].startswith("壹.一.")]
    assert len(indirect) == 35
    assert not any(CheckResult.BOQ_NOT_IN_DRAWINGS in item["issues"] for item in indirect)


#: 2026-11 實測（秀山真實標單 1028 項 × 真實施工規範 86 章）
SUMMARY_OK = 239
SUMMARY_SPEC_NOT_INCLUDED = 188
SUMMARY_NEEDS_CONFIRMATION = 592
SUMMARY_METHOD_UNDECIDED = 9


async def test_the_contract_column_points_at_real_contract_pages(api_client):
    body = await build(api_client, with_drawings=False)

    rebar = next(item for item in body["items"] if item["chapter_code"] == "03210")
    refs = rebar["contract_refs"]
    assert refs and all(ref["keyword"] == "鋼筋" and ref["page"] for ref in refs)
    covered = sum(bool(item["contract_refs"]) for item in body["items"])
    print(f"\n契約欄：{covered}/{body['total']} 個工項找得到契約提及處")
    assert covered >= CONTRACT_COVERED
    # 不影響檢核結果
    assert body["summary"]["ok"] == SUMMARY_OK


#: 2026-11 實測：契約書提到的工項數（工項主體或所屬分項）
CONTRACT_COVERED = 54


REAL_DRAWINGS = [DOCS / f"{name}(用印含簽名).pdf" for name in ("建築圖", "結構圖", "水電圖")]


@pytest.mark.skipif(
    os.environ.get("XIUSHAN_OCR") != "1" or not all(p.exists() for p in REAL_DRAWINGS),
    reason="秀山真實契約圖是掃描檔，OCR 三冊約 12 分鐘；要跑請設 XIUSHAN_OCR=1",
)
async def test_the_real_scanned_drawings(api_client, monkeypatch):
    """三冊用印掃描的真實契約圖：OCR 讀標題欄、依分項比對。數字是 2026-11 實測。"""
    monkeypatch.setattr(settings, "ENABLE_OCR", True)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 400)
    roles = {BOQ: "boq", SPEC: "specification", CONTRACT: "contract", **{p: "drawing" for p in REAL_DRAWINGS}}
    project_id = (await api_client.post("/api/projects", json={"name": "秀山分隊興建工程"})).json()["project_id"]
    for path, role in roles.items():
        files = {"file": (path.name, path.read_bytes(), "application/octet-stream")}
        document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
        await api_client.post(
            f"/api/projects/{project_id}/documents", json={"document_id": document_id, "role": role}
        )
    await api_client.post(f"/api/projects/{project_id}/work-items")
    body = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()

    assert body["has_drawings"] is True
    assert body["drawing_warning"] is None
    assert body["summary"]["boq_not_in_drawings"] <= REAL_BOQ_NOT_IN_DRAWINGS
    titles = [d["title"] for item in body["items"] for d in item["drawings"]]
    assert titles and all(d["is_ocr"] for item in body["items"] for d in item["drawings"])


#: 2026-11 實測（三冊真實掃描圖、分項比對）。示範圖逐項比對時是 750
REAL_BOQ_NOT_IN_DRAWINGS = 595
