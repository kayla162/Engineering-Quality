"""企業內部文件清單：匯入、抽取、比對、異動監控。

用 scripts/generate_enterprise_template.py --demo 產生的假資料（虛構的示範營造）
與 data/samples/sample_quality_plan_enterprise.txt 走完整條路。
"""

import io

import pytest
from openpyxl import load_workbook

from app.core.config import settings
from app.core.enums import AuditAction, RegulationStatus, RegulationType
from app.sources import reset_sources

DEMO = settings.DATA_DIR / "samples" / "enterprise_documents_demo.xlsx"
SAMPLE = settings.DATA_DIR / "samples" / "sample_quality_plan_enterprise.txt"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def enterprise_enabled(monkeypatch):
    monkeypatch.setattr(settings, "REGULATION_SOURCES", "enterprise,mock")
    reset_sources()
    yield
    reset_sources()


async def import_list(api_client, data: bytes | None = None, filename="清單.xlsx"):
    return await api_client.post(
        "/api/enterprise-documents/import",
        files={"file": (filename, data if data is not None else DEMO.read_bytes(), XLSX)},
    )


def edited_demo(edit) -> bytes:
    """改一份假資料清單：edit 收到「文件清單」工作表。"""
    workbook = load_workbook(DEMO)
    edit(workbook["文件清單"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def row_of(sheet, doc_number: str) -> int:
    return next(r for r in range(2, sheet.max_row + 1) if sheet.cell(r, 1).value == doc_number)


async def analyze_sample(api_client) -> dict[str, dict]:
    files = {"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/plain")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()["document_id"]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    items = (
        await api_client.get(f"/api/documents/{document_id}/references", params={"page_size": 500})
    ).json()["items"]
    return {item["raw_text"]: item for item in items}


class TestImport:
    async def test_the_demo_list_imports(self, api_client):
        response = await import_list(api_client)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 12
        assert body["imported_by"] == "test-admin"

    async def test_status_labels_round_trip(self, api_client):
        body = (await import_list(api_client)).json()
        by_number = {item["doc_number"]: item for item in body["items"]}

        assert (by_number["QP-07-01"]["status"], by_number["QP-07-01"]["status_label"]) == (
            RegulationStatus.REPEALED,
            "作廢",
        )
        assert by_number["QP-07-01"]["replaced_by"] == "QP-07-06"
        assert by_number["QP-07-02"]["status"] == RegulationStatus.AMENDED

    async def test_import_replaces_the_whole_list(self, api_client):
        await import_list(api_client)

        def keep_two(sheet):
            sheet.delete_rows(4, sheet.max_row)

        body = (await import_list(api_client, edited_demo(keep_two))).json()

        assert body["total"] == 2

    async def test_a_bad_row_rejects_the_whole_file_and_says_where(self, api_client):
        await import_list(api_client)

        def break_rows(sheet):
            sheet.cell(row_of(sheet, "QP-07-03"), 7, "停用")
            # ws.cell(r, c, None) 不會清空儲存格，要直接設 .value
            sheet.cell(row_of(sheet, "QM-01"), 2).value = None

        response = await import_list(api_client, edited_demo(break_rows))

        assert response.status_code == 400
        details = response.json()["error"]["details"]
        assert {d["row"] for d in details} == {2, 6}
        assert any("停用" in d["message"] for d in details)
        # 舊清單原封不動
        assert (await api_client.get("/api/enterprise-documents")).json()["total"] == 12

    async def test_duplicate_numbers_are_rejected(self, api_client):
        def duplicate(sheet):
            sheet.cell(row_of(sheet, "QP-04-01"), 1, "QM-01")

        response = await import_list(api_client, edited_demo(duplicate))

        assert response.status_code == 400
        assert "QM-01".casefold() in str(response.json()["error"]["details"]).casefold()

    async def test_the_blank_template_is_rejected_as_empty(self, api_client):
        template = settings.DATA_DIR / "templates" / "企業內部文件清單範本.xlsx"

        response = await import_list(api_client, template.read_bytes())

        assert response.status_code == 400
        assert "空的" in response.json()["error"]["message"]

    async def test_only_xlsx_is_accepted(self, api_client):
        response = await import_list(api_client, b"a,b,c", filename="清單.csv")

        assert response.status_code == 400

    async def test_import_is_audited(self, api_client):
        await import_list(api_client)

        item = (await api_client.get("/api/audit-logs")).json()["items"][0]
        assert item["action"] == AuditAction.ENTERPRISE_DOCUMENTS_IMPORTED
        assert item["detail"]["total"] == 12

    async def test_the_template_can_be_downloaded(self, api_client):
        response = await api_client.get("/api/enterprise-documents/template")

        assert response.status_code == 200
        assert response.content.startswith(b"PK")


class TestMatching:
    @pytest.fixture
    async def references(self, api_client) -> dict[str, dict]:
        await import_list(api_client)
        return await analyze_sample(api_client)

    async def test_a_document_number_is_found(self, references):
        """規則引擎抓不到「QP-07-03」，只有字典認得。"""
        item = references["QP-07-03"]

        assert item["normalized_name"] == "混凝土澆置作業標準"
        assert item["status"] == RegulationStatus.ACTIVE
        assert item["regulation_type"] == RegulationType.INTERNAL

    async def test_a_name_without_a_legal_suffix_is_found(self, references):
        """「品質手冊」「程序書」不是法規字尾，沒有字典就抽不到。

        範例寫「本公司品質手冊」：較長的別名「公司品質手冊」優先命中。
        """
        assert references["公司品質手冊"]["normalized_name"] == "品質手冊"
        assert references["公司品質手冊"]["status"] == RegulationStatus.ACTIVE
        assert references["文件管制程序書"]["status"] == RegulationStatus.ACTIVE

    async def test_an_alias_is_normalized(self, references):
        item = references["自主檢查作業程序"]

        assert item["normalized_name"] == "自主檢查程序書"
        assert item["status"] == RegulationStatus.ACTIVE

    async def test_a_withdrawn_document_is_repealed(self, references):
        assert references["模板組立作業標準"]["status"] == RegulationStatus.REPEALED

    async def test_a_revised_document_is_amended(self, references):
        assert references["鋼筋綁紮作業標準"]["status"] == RegulationStatus.AMENDED

    async def test_official_regulations_still_match(self, references):
        assert references["政府採購法"]["status"] == RegulationStatus.ACTIVE

    async def test_the_source_is_enterprise(self, api_client, references):
        detail = (
            await api_client.get(
                f"/api/regulation-references/{references['QP-07-03']['reference_id']}"
            )
        ).json()

        assert detail["matched_regulation"]["source"] == "enterprise"
        assert detail["matched_regulation"]["authority"] == "工務部"


class TestWithoutAList:
    async def test_internal_documents_are_not_extracted(self, api_client):
        """沒匯入清單時，文件編號與「品質手冊」這類名稱根本抽不到。"""
        references = await analyze_sample(api_client)

        assert "QP-07-03" not in references
        assert "公司品質手冊" not in references

    async def test_the_source_reports_why_it_is_not_ready(self, api_client):
        body = (await api_client.get("/api/sources")).json()
        enterprise = next(s for s in body["sources"] if s["source"] == "enterprise")

        assert enterprise["ready"] is False
        assert "還沒有匯入" in enterprise["detail"]

    async def test_after_import_the_source_is_ready(self, api_client):
        await import_list(api_client)

        body = (await api_client.get("/api/sources")).json()

        assert body["status"] == "ok"


class TestTenantIsolation:
    async def test_another_tenants_list_is_not_used(self, api_client, db_session):
        """別家公司的內部文件，不能出現在這個租戶的抽取與比對裡。"""
        import uuid

        from app.models.tenant import Tenant
        from app.services.enterprise_document_service import (
            EnterpriseDocumentService,
            parse_workbook,
        )

        other = Tenant(id=uuid.uuid4(), name="別的公司")
        db_session.add(other)
        await EnterpriseDocumentService(db_session, other.id).replace_all(
            parse_workbook(DEMO.read_bytes()), "other-admin"
        )
        await db_session.commit()

        references = await analyze_sample(api_client)
        listed = (await api_client.get("/api/enterprise-documents")).json()

        assert "QP-07-03" not in references
        assert listed["total"] == 0


class TestChangeMonitoring:
    @pytest.fixture
    async def analyzed(self, api_client):
        await import_list(api_client)
        await analyze_sample(api_client)

    async def test_withdrawing_a_document_is_detected(self, api_client, analyzed):
        def withdraw(sheet):
            sheet.cell(row_of(sheet, "QP-07-03"), 7, "作廢")

        await import_list(api_client, edited_demo(withdraw))
        body = (await api_client.post("/api/regulation-changes/check")).json()

        change = next(c for c in body["new_changes"] if c["regulation_name"] == "混凝土澆置作業標準")
        assert change["changes"]["status"] == {
            "old": RegulationStatus.ACTIVE,
            "new": RegulationStatus.REPEALED,
        }

    async def test_removing_a_document_from_the_list_is_reported_missing(self, api_client, analyzed):
        def remove(sheet):
            sheet.delete_rows(row_of(sheet, "QM-01"))

        await import_list(api_client, edited_demo(remove))
        body = (await api_client.post("/api/regulation-changes/check")).json()

        change = next(c for c in body["new_changes"] if c["regulation_name"] == "品質手冊")
        assert change["changes"] == {"presence": {"old": "found", "new": "missing"}}

    async def test_an_unchanged_list_produces_no_changes(self, api_client, analyzed):
        body = (await api_client.post("/api/regulation-changes/check")).json()

        assert body["changed"] == 0
        assert body["skipped"] == []
