"""檢核表 API。

結果怎麼算在 test_checklist_service.py 測；這裡測 HTTP 這一層：路由有沒有接對
（POST 重建、GET 只讀）、回應的形狀、錯誤碼。

用 tests/factories.py 預設的標單（三個工項）加一份只有 01725 一章的規範書，三種結果各一個：
    壹.一.1.1.1  計價代碼 01725…  規範書有這章、這章有相關準則  -> OK
    壹.一.1.2.1  計價代碼 03110…  綱要規範有、本案規範書沒收    -> SPEC_NOT_INCLUDED
    壹.一.1.3.1  沒有計價代碼                                    -> NEEDS_CONFIRMATION
"""

import json
import uuid

import pytest

from app.core.config import settings
from app.core.enums import ParseQuality
from app.repositories.documents import DocumentRepository
from tests.factories import make_boq_bytes, make_spec_pdf_bytes

SPEC = [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審")]

ITEM_NOS = ["壹.一.1.1.1", "壹.一.1.2.1", "壹.一.1.3.1"]

#: 本檔測試用的迷你綱要規範目錄（PCCES）。刻意不讀 data/pcces_index.json：那是
#: scripts/sync_pcces.py 同步下來的檔案、被 .gitignore 擋掉，測試不該靠它在不在、
#: 裡面有什麼。ChecklistService 會用它判斷「本案規範未收錄」——03110 在這裡，
#: 所以 壹.一.1.2.1 對得到章節、規範書卻沒有。做法同 test_checklist_service.py。
PCCES_CHAPTERS = [
    {"code": "01725", "name": "施工測量", "edition": "3.0"},
    {"code": "03110", "name": "場鑄結構混凝土用模板", "edition": "6.0"},
]


@pytest.fixture(autouse=True)
def pcces_catalog(tmp_path, monkeypatch):
    path = tmp_path / "pcces_index.json"
    path.write_text(
        json.dumps({"source": "pcces", "count": len(PCCES_CHAPTERS), "chapters": PCCES_CHAPTERS}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "PCCES_INDEX_PATH", path)


async def upload(api_client, filename: str, data: bytes, mime: str) -> str:
    response = await api_client.post(
        "/api/documents/upload", files={"file": (filename, data, mime)}
    )
    return response.json()["document_id"]


async def attach(api_client, project_id: str, document_id: str, role: str) -> None:
    await api_client.post(
        f"/api/projects/{project_id}/documents",
        json={"document_id": document_id, "role": role},
    )


@pytest.fixture
async def project_with_boq(api_client):
    """建好專案、掛好標單、建好工項清單，還沒有規範書——使用者最先碰到的狀態。"""
    response = await api_client.post("/api/projects", json={"name": "秀山分隊興建工程"})
    project_id = response.json()["project_id"]

    boq_id = await upload(api_client, "標單.xlsx", make_boq_bytes(), "application/vnd.ms-excel")
    await attach(api_client, project_id, boq_id, "boq")
    await api_client.post(f"/api/projects/{project_id}/work-items")
    return project_id


async def attach_spec(api_client, project_id: str, chapters=SPEC, trailing_pages: int = 0) -> str:
    spec_id = await upload(
        api_client,
        "施工規範.pdf",
        make_spec_pdf_bytes(chapters, trailing_pages=trailing_pages),
        "application/pdf",
    )
    await attach(api_client, project_id, spec_id, "specification")
    return spec_id


@pytest.fixture
async def project_id(api_client, project_with_boq):
    await attach_spec(api_client, project_with_boq)
    return project_with_boq


def url(project_id: str) -> str:
    return f"/api/projects/{project_id}/checklist"


async def items_by_no(api_client, project_id: str) -> dict[str, dict]:
    items = (await api_client.get(url(project_id))).json()["items"]
    return {item["item_no"]: item for item in items}


class TestBuildChecklist:
    async def test_checklist_is_built(self, api_client, project_id):
        response = await api_client.post(url(project_id))

        assert response.status_code == 201
        assert [i["item_no"] for i in response.json()["items"]] == ITEM_NOS
        assert response.json()["total"] == len(ITEM_NOS)

    async def test_the_summary_counts_each_result(self, api_client, project_id):
        """只比總和抓不到算錯：全部算成 needs_confirmation 總和照樣對。"""
        body = (await api_client.post(url(project_id))).json()

        assert body["summary"] == {"ok": 1, "spec_not_included": 1, "needs_confirmation": 1}
        assert sum(body["summary"].values()) == body["total"]

    async def test_each_result_comes_with_the_rows_it_describes(self, api_client, project_id):
        await api_client.post(url(project_id))

        rows = await items_by_no(api_client, project_id)

        assert {no: row["result"] for no, row in rows.items()} == {
            "壹.一.1.1.1": "OK",
            "壹.一.1.2.1": "SPEC_NOT_INCLUDED",
            "壹.一.1.3.1": "NEEDS_CONFIRMATION",
        }
        # 本案規範書沒有這章、或根本沒有章碼：不能掛一個別章的章節或依據上去
        for item_no in ("壹.一.1.2.1", "壹.一.1.3.1"):
            assert rows[item_no]["chapter"] is None
            assert rows[item_no]["bases"] == []

    async def test_the_response_is_the_checklist_that_get_returns(self, api_client, project_id):
        """POST 回應的和之後 GET 讀到的要是同一張表——前端建完就直接用回應畫面。"""
        built = (await api_client.post(url(project_id))).json()

        read_back = (await api_client.get(url(project_id))).json()

        # 先確認真的有一張表：兩個都是 404 的錯誤本文時，「相等」也成立
        assert built["total"] == len(ITEM_NOS)
        assert read_back == built

    async def test_rebuilding_replaces_instead_of_accumulating(self, api_client, project_id):
        await api_client.post(url(project_id))
        await api_client.post(url(project_id))

        rows = await items_by_no(api_client, project_id)

        assert [b["reference"] for b in rows["壹.一.1.1.1"]["bases"]] == ["測量法"]

    async def test_the_rows_use_the_work_item_ids_of_the_work_item_list(
        self, api_client, project_id
    ):
        """前端要把檢核表和工項清單接起來，靠的就是 work_item_id。"""
        await api_client.post(url(project_id))

        checklist = await items_by_no(api_client, project_id)
        work_items = (await api_client.get(f"/api/projects/{project_id}/work-items")).json()

        assert {no: row["work_item_id"] for no, row in checklist.items()} == {
            item["item_no"]: item["work_item_id"] for item in work_items["items"]
        }
        assert {no: row["name"] for no, row in checklist.items()} == {
            item["item_no"]: item["name"] for item in work_items["items"]
        }


class TestGetChecklist:
    async def test_a_matched_item_carries_its_chapter_and_basis(self, api_client, project_id):
        await api_client.post(url(project_id))

        row = (await items_by_no(api_client, project_id))["壹.一.1.1.1"]

        assert row["result"] == "OK"
        # 版本不含「V」字首（頁首的 V3.0 在建索引時就去掉了）
        assert row["chapter"] == {"code": "01725", "title": "施工測量", "version": "3.0"}
        # 整筆比對，不只看 reference：依據只有這三個欄位。沒有任何一筆依據在本階段被
        # 查證過，所以不能多出一個 verified 之類的欄位去暗示哪些查證過；出處只寫到章，
        # 因為相關準則不一定在 1.4，系統不宣稱自己不知道的小節號。
        assert row["bases"] == [
            {"basis_type": "law", "reference": "測量法", "detail": "第01725章 相關準則"}
        ]

    async def test_a_law_and_a_standard_are_told_apart_by_basis_type(
        self, api_client, project_with_boq
    ):
        """basis_type 是前端分辨「法規」與「標準」的唯一依據。"""
        await attach_spec(
            api_client,
            project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 (2) CNS 2473 鋼材 1.5 送審")],
        )
        await api_client.post(url(project_with_boq))

        row = (await items_by_no(api_client, project_with_boq))["壹.一.1.1.1"]

        assert {b["reference"]: b["basis_type"] for b in row["bases"]} == {
            "測量法": "law",
            "CNS 2473": "standard",
        }

    async def test_the_fields_are_exactly_the_documented_ones(self, api_client, project_id):
        """docs/api.md 6.6 節寫的就是這些欄位。多一個、少一個都要同步改文件。"""
        await api_client.post(url(project_id))

        body = (await api_client.get(url(project_id))).json()

        assert set(body) == {"total", "summary", "contract_note", "spec_warning", "items"}
        assert set(body["items"][0]) == {
            "work_item_id", "item_no", "name", "result", "chapter", "bases"
        }

    async def test_the_contract_note_travels_with_the_checklist(self, api_client, project_id):
        """契約依據是專案層級的、不逐工項列（階段 3 spec 3.1 節）。這句話要跟著檢核表
        走，否則沒有人知道契約欄去哪了。POST 與 GET 都要有。"""
        built = (await api_client.post(url(project_id))).json()
        read_back = (await api_client.get(url(project_id))).json()

        for body in (built, read_back):
            assert "標價清單" in body["contract_note"]
            assert "專案層級" in body["contract_note"]

    async def test_get_does_not_build(self, api_client, project_id):
        """GET 只讀已經建好的。規範書掛了、工項也有，但從沒 POST 過：依據與章節索引
        都還是空的。若 GET 偷偷重建，這裡會看到 OK。"""
        response = await api_client.get(url(project_id))

        assert response.status_code == 200
        rows = {i["item_no"]: i for i in response.json()["items"]}
        assert {r["result"] for r in rows.values()} == {"NEEDS_CONFIRMATION"}
        assert all(r["chapter"] is None and r["bases"] == [] for r in rows.values())

    @pytest.mark.parametrize("method, status_code", [("post", 201), ("get", 200)])
    async def test_a_project_without_a_spec_still_gets_a_checklist(
        self, api_client, project_with_boq, method, status_code
    ):
        """沒掛規範書不會報錯：工項都在，只是依據欄空白。刻意和沒掛標單是 400 不對稱——
        沒有標單表是空的，沒有規範書表還在。"""
        response = await getattr(api_client, method)(url(project_with_boq))

        assert response.status_code == status_code
        body = response.json()
        assert [i["item_no"] for i in body["items"]] == ITEM_NOS
        assert body["summary"] == {"ok": 0, "spec_not_included": 0, "needs_confirmation": 3}
        assert all(i["chapter"] is None and i["bases"] == [] for i in body["items"])
        assert body["spec_warning"] is None


class TestSpecWarning:
    async def test_a_clean_spec_has_no_warning(self, api_client, project_id):
        body = (await api_client.post(url(project_id))).json()

        assert body["spec_warning"] is None

    async def test_a_degraded_spec_warns_on_both_endpoints(
        self, api_client, db_session, project_with_boq
    ):
        """規範書若大量是圖，依據可能殘缺。警告只在 POST 的回應裡就等於大部分時候
        看不到——使用者多半是用 GET 看檢核表。"""
        spec_id = await attach_spec(api_client, project_with_boq)
        document = await DocumentRepository(db_session).get(uuid.UUID(spec_id))
        document.parse_quality = ParseQuality.DEGRADED
        document.parse_quality_note = "105 頁裡有 57 頁以圖為主，圖內的文字未被讀取"
        await db_session.commit()

        built = (await api_client.post(url(project_with_boq))).json()
        read_back = (await api_client.get(url(project_with_boq))).json()

        for body in (built, read_back):
            assert "以圖為主" in body["spec_warning"]


class TestErrors:
    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_unknown_project_is_404(self, api_client, method):
        response = await getattr(api_client, method)(
            "/api/projects/00000000-0000-0000-0000-000000000000/checklist"
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    async def test_a_spec_with_no_readable_chapters_is_rejected(
        self, api_client, project_with_boq
    ):
        """讀不懂規範書要報錯，不是產出一張全部「請確認依據」的表——那看起來像
        「這個案子沒有依據」，實際是「我們沒讀懂規範書」。"""
        await attach_spec(api_client, project_with_boq, chapters=[], trailing_pages=1)

        response = await api_client.post(url(project_with_boq))

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNPROCESSABLE_DOCUMENT"
        assert "章節" in response.json()["error"]["message"]
