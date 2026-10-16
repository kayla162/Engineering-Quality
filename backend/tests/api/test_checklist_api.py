"""檢核表 API。

結果怎麼算在 test_checklist_service.py 測；這裡測 HTTP 這一層：路由有沒有接對
（POST 重建、GET 只讀）、回應的形狀、錯誤碼。

標單六個工項，加一份兩章的規範書。**三種結果的筆數刻意互不相同**（OK 2、
SPEC_NOT_INCLUDED 1、NEEDS_CONFIRMATION 3）：兩種結果的筆數一樣時，摘要裡那兩個欄位
對調也看不出來，整張表的標題數字（真實文件實測 248 / 188 / 592）會悄悄顛倒，而所有
測試照樣通過。三個 NEEDS_CONFIRMATION 各是真實標單上的一種原因：
    壹.一.1.1.1  計價代碼 01725…  規範書有這章、這章有相關準則      -> OK
    壹.一.1.1.2  計價代碼 01725…  同上                              -> OK
    壹.一.1.2.1  計價代碼 03110…  綱要規範有、本案規範書沒收        -> SPEC_NOT_INCLUDED
    壹.一.1.3.1  沒有計價代碼                                        -> NEEDS_CONFIRMATION
    壹.一.1.4.1  計價代碼 99999…  不在規範書、也不是綱要規範的章      -> NEEDS_CONFIRMATION
    壹.一.1.5.1  計價代碼 01523…  規範書有這章、但這章沒有相關準則    -> NEEDS_CONFIRMATION
"""

import json
import uuid

import pytest

from app.core.config import settings
from app.core.enums import ParseQuality
from app.repositories.documents import DocumentRepository
from tests.factories import BOQ_HEADER, make_boq_bytes, make_spec_pdf_bytes

BOQ = [
    BOQ_HEADER,
    ["壹.一.1.1.1", "施工測量，基地測量", "式", 1, 1, 1, "0172500004"],
    ["壹.一.1.1.2", "施工測量，放樣", "式", 1, 1, 1, "0172500005"],
    ["壹.一.1.2.1", "普通模板，普通模板含組立", "M2", 959, 1, 1, "0311010002"],
    ["壹.一.1.3.1", "天花板，長條鋁企口天花板", "M2", 120, 1, 1, ""],
    ["壹.一.1.4.1", "自訂工項，各機關自訂", "式", 1, 1, 1, "9999900001"],
    ["壹.一.1.5.1", "施工安全衛生，安全衛生管理", "式", 1, 1, 1, "0152300001"],
]

#: 本案規範書兩章：01725 宣告了相關準則；01523 在規範書裡，但沒有宣告相關準則
SPEC = [
    ("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 1.5 資料送審"),
    ("01523", "01523", "施工安全衛生及管理", "4.0", "1. 通則 3. 執行"),
]

ITEM_NOS = [row[0] for row in BOQ[1:]]

RESULTS = {
    "壹.一.1.1.1": "OK",
    "壹.一.1.1.2": "OK",
    "壹.一.1.2.1": "SPEC_NOT_INCLUDED",
    "壹.一.1.3.1": "NEEDS_CONFIRMATION",
    "壹.一.1.4.1": "NEEDS_CONFIRMATION",
    "壹.一.1.5.1": "NEEDS_CONFIRMATION",
}

#: 各列的 chapter_code：計價代碼前 5 碼，沒有計價代碼是 None。和 RESULTS 並排看：
#: 03110（SPEC_NOT_INCLUDED）與 99999（代碼不是任何一章）的列 `chapter` 是 null，
#: chapter_code 照樣有值；它不看規範書。
CHAPTER_CODES = {
    "壹.一.1.1.1": "01725",
    "壹.一.1.1.2": "01725",
    "壹.一.1.2.1": "03110",
    "壹.一.1.3.1": None,
    "壹.一.1.4.1": "99999",
    "壹.一.1.5.1": "01523",
}

#: 本檔測試用的迷你綱要規範目錄（PCCES）。刻意不讀 data/pcces_index.json：那是
#: scripts/sync_pcces.py 同步下來的檔案、被 .gitignore 擋掉，測試不該靠它在不在、
#: 裡面有什麼。ChecklistService 會用它判斷「本案規範未收錄」——03110 在這裡，
#: 所以 壹.一.1.2.1 對得到章節、規範書卻沒有；99999 不在這裡，所以 壹.一.1.4.1 說不上
#: 「漏收」。01523 也不在這裡，但本案規範書有它：先比規範書、再用目錄判斷漏收，所以
#: 壹.一.1.5.1 照樣對得到章節。做法同 test_checklist_service.py。
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

    boq_id = await upload(
        api_client, "標單.xlsx", make_boq_bytes(rows=BOQ), "application/vnd.ms-excel"
    )
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
        """三種結果的筆數互不相同（2 / 1 / 3），所以任何兩個欄位對調都會被抓到。

        只比總和抓不到算錯：全部算成 needs_confirmation 總和照樣對。筆數一樣的兩個欄位
        （例如各 1）對調也照樣通過——真實標單上就是把「248 筆 OK、188 筆未收錄」悄悄
        顛倒成「188 筆 OK、248 筆未收錄」，這張表的標題數字全是反的。"""
        body = (await api_client.post(url(project_id))).json()

        expected = {"ok": 2, "spec_not_included": 1, "needs_confirmation": 3}
        # 筆數不互異的話，這個測試就守不住欄位對調
        assert len(set(expected.values())) == len(expected)
        assert body["summary"] == expected
        assert sum(body["summary"].values()) == body["total"]

    async def test_each_result_comes_with_the_rows_it_describes(self, api_client, project_id):
        await api_client.post(url(project_id))

        rows = await items_by_no(api_client, project_id)

        assert {no: row["result"] for no, row in rows.items()} == RESULTS
        # 規範書有這章、也宣告了相關準則：章節與依據都帶出來
        for item_no in ("壹.一.1.1.1", "壹.一.1.1.2"):
            assert rows[item_no]["chapter"]["code"] == "01725"
            assert [b["reference"] for b in rows[item_no]["bases"]] == ["測量法"]
        # 規範書有這章、但這章沒有宣告相關準則：章節照樣帶出來，只是沒有依據
        assert rows["壹.一.1.5.1"]["chapter"] == {
            "code": "01523", "title": "施工安全衛生及管理", "version": "4.0"
        }
        assert rows["壹.一.1.5.1"]["bases"] == []
        # 本案規範書沒有這章、或根本沒有章碼：不能掛一個別章的章節或依據上去
        for item_no in ("壹.一.1.2.1", "壹.一.1.3.1", "壹.一.1.4.1"):
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

        for item_no in ("壹.一.1.1.1", "壹.一.1.1.2"):
            assert [b["reference"] for b in rows[item_no]["bases"]] == ["測量法"]

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
    async def test_a_matched_item_carries_its_chapter_and_basis(
        self, api_client, project_id, monkeypatch
    ):
        from app.services import checklist_service

        # 查證什麼都沒查到：不靠 data/taiwan_law_index.json 裡有沒有同名的法規，
        # 下面斷言 verification_status 是 null 才是這個測試要說的事
        async def nothing_found(names, source):
            return {}

        monkeypatch.setattr(checklist_service, "verify_names", nothing_found)
        await api_client.post(url(project_id))

        row = (await items_by_no(api_client, project_id))["壹.一.1.1.1"]

        assert row["result"] == "OK"
        # 版本不含「V」字首（頁首的 V3.0 在建索引時就去掉了）
        assert row["chapter"] == {"code": "01725", "title": "施工測量", "version": "3.0"}
        # 整筆比對，不只看 reference：依據只有這四個欄位。查證結果只有
        # verification_status 一個欄位，不能再多出一個 verified 之類的布林去暗示哪些查證
        # 過——null 是「沒查證」，布林的 false 會讀成「查過、不是」；出處只寫到章，因為
        # 相關準則不一定在 1.4，系統不宣稱自己不知道的小節號。
        assert row["bases"] == [
            {
                "basis_type": "law",
                "reference": "測量法",
                "detail": "第01725章 相關準則",
                "verification_status": None,
            }
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
            "work_item_id", "item_no", "name", "result", "chapter_code", "chapter", "bases"
        }

    async def test_a_spec_not_included_row_names_the_chapter_it_is_missing(
        self, api_client, project_id
    ):
        """SPEC_NOT_INCLUDED 的 `chapter` 是 null（本案規範書沒有這一章），所以檢核表自己得
        說出缺的是哪一章：docs/api.md 6.6 節叫前端依章分流那一批，章碼只能從這裡拿，
        不然得再去打另一支 API 接工項清單。"""
        await api_client.post(url(project_id))

        row = (await items_by_no(api_client, project_id))["壹.一.1.2.1"]

        assert row["result"] == "SPEC_NOT_INCLUDED"
        assert row["chapter"] is None
        # 計價代碼 0311010002 的前 5 碼
        assert row["chapter_code"] == "03110"

    async def test_chapter_code_is_the_cost_code_prefix_whatever_the_result(
        self, api_client, project_id
    ):
        """有計價代碼的列都有 chapter_code，不管結果是什麼、本案規範書有沒有這一章；沒有
        計價代碼的列是 null。它不是從 `chapter` 抄來的：抄的話，SPEC_NOT_INCLUDED 與
        「代碼不是任何一章」的列都會是 null。"""
        await api_client.post(url(project_id))

        rows = await items_by_no(api_client, project_id)

        assert {no: row["chapter_code"] for no, row in rows.items()} == CHAPTER_CODES
        # 對得到章節的列，兩個欄位講的是同一章
        matched = [row for row in rows.values() if row["chapter"] is not None]
        assert matched
        assert all(row["chapter_code"] == row["chapter"]["code"] for row in matched)

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
        assert response.json()["summary"] == {
            "ok": 0, "spec_not_included": 0, "needs_confirmation": len(ITEM_NOS)
        }

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
        assert body["summary"] == {
            "ok": 0, "spec_not_included": 0, "needs_confirmation": len(ITEM_NOS)
        }
        assert all(i["chapter"] is None and i["bases"] == [] for i in body["items"])
        # chapter_code 只看工項自己的計價代碼，沒有規範書也一樣有
        assert {i["item_no"]: i["chapter_code"] for i in body["items"]} == CHAPTER_CODES
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


class TestVerificationInResponse:
    async def test_the_status_reaches_the_client(self, api_client, project_id, monkeypatch):
        from app.core.enums import RegulationStatus
        from app.services import checklist_service

        # fixture 的 01725 章宣告的是「測量法」，用它才對得上實際產出的依據
        async def fake_verify(names, source):
            return {"測量法": RegulationStatus.ACTIVE}

        monkeypatch.setattr(checklist_service, "verify_names", fake_verify)

        body = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()
        statuses = {
            b["reference"]: b["verification_status"]
            for item in body["items"]
            for b in item["bases"]
        }

        assert statuses.get("測量法") == RegulationStatus.ACTIVE

    async def test_an_unverified_basis_is_null_not_not_found(self, api_client, project_id):
        """未查證是 null。顯示成「查無此法規」會讓人以為規範引用了不存在的東西。"""
        body = (await api_client.post(f"/api/projects/{project_id}/checklist")).json()
        values = {
            b["verification_status"]
            for item in body["items"]
            for b in item["bases"]
        }

        assert "NOT_FOUND" not in values

    async def test_a_basis_nobody_verified_is_null_in_both_post_and_get(
        self, api_client, project_id, monkeypatch
    ):
        """上一個測試靠真實索引的內容決定有沒有 None 可看，索引在不在都會過。這個不靠：
        查證什麼都沒查到，每一筆都必須是 null——欄位在、值是 null，而且 POST 回應和
        之後 GET 讀到的一樣（讀取不重查，狀態是從資料庫來的）。"""
        from app.services import checklist_service

        async def nothing_found(names, source):
            return {}

        monkeypatch.setattr(checklist_service, "verify_names", nothing_found)

        built = (await api_client.post(url(project_id))).json()
        read_back = (await api_client.get(url(project_id))).json()

        for body in (built, read_back):
            bases = [b for item in body["items"] for b in item["bases"]]
            # 先確認真的有依據可看：空集合會讓下面的比對空轉
            assert bases
            assert all("verification_status" in b for b in bases)
            assert {b["verification_status"] for b in bases} == {None}

    async def test_a_standard_stays_null_beside_a_verified_law(
        self, api_client, project_with_boq, monkeypatch
    ):
        """標準沒有資料來源，查證不會碰它：同一章裡的法規查到了，標準仍然是 null。

        這個 API 層的 fixture 原本沒有任何標準依據，「標準是 null」只在 service 層斷言；
        只把標準標成 NOT_FOUND（或把標準也送去查）的錯誤，API 層的測試全都看不出來。
        fake 對收到的每個名稱都回 ACTIVE：標準要是被送去查，會變成 ACTIVE 而不是 null。"""
        from app.core.enums import RegulationStatus
        from app.services import checklist_service

        async def verify_everything_it_is_asked(names, source):
            return {name: RegulationStatus.ACTIVE for name in names}

        monkeypatch.setattr(checklist_service, "verify_names", verify_everything_it_is_asked)
        await attach_spec(
            api_client,
            project_with_boq,
            [("01725", "01725", "施工測量", "3.0", "1.4 相關準則 (1) 測量法 (2) CNS 2473 鋼材 1.5 送審")],
        )

        built = (await api_client.post(url(project_with_boq))).json()
        read_back = (await api_client.get(url(project_with_boq))).json()

        for body in (built, read_back):
            statuses = {
                b["reference"]: b["verification_status"]
                for item in body["items"]
                for b in item["bases"]
            }
            assert statuses == {"測量法": RegulationStatus.ACTIVE, "CNS 2473": None}
