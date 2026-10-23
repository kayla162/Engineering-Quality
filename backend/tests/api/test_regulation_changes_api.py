"""法規異動監控。

用一個可以改內容的假來源扮演 mock：測試裡「官方公告廢止」就是改它回傳的狀態。
"""

from datetime import date

import pytest

from app.core.enums import AuditAction, RegulationStatus, ReviewStatus
from app.services import regulation_change_service
from app.sources.base import (
    RegulationDetail,
    RegulationSearchResult,
    RegulationSource,
    SourceReadiness,
)
from app.sources.mock_source import MockRegulationSource
from tests.factories import make_docx_bytes


class EditableSource(RegulationSource):
    """一開始和 mock 假資料一模一樣，之後可以改某部法規的欄位或讓它消失。"""

    source_name = "mock"

    def __init__(self):
        self.inner = MockRegulationSource()
        self.overrides: dict[str, dict] = {}
        self.removed: set[str] = set()
        self.ready = True
        self.failing = False

    def readiness(self) -> SourceReadiness:
        if self.ready:
            return SourceReadiness(source="mock", ready=True)
        return SourceReadiness(source="mock", ready=False, detail="假資料檔不見了")

    async def search(self, query: str) -> list[RegulationSearchResult]:
        if self.failing:
            from app.core.errors import SourceQueryError

            raise SourceQueryError("mock", "連線逾時", http_status="504")
        results = []
        for result in await self.inner.search(query):
            if result.name in self.removed:
                continue
            results.append(result.model_copy(update=self.overrides.get(result.name, {})))
        return results

    async def get_detail(self, regulation_id: str) -> RegulationDetail | None:
        return await self.inner.get_detail(regulation_id)

    async def get_version_history(self, regulation_id: str):
        return await self.inner.get_version_history(regulation_id)


@pytest.fixture
def source(monkeypatch):
    fake = EditableSource()
    monkeypatch.setattr(regulation_change_service, "get_sources", lambda: [fake])
    return fake


@pytest.fixture
async def analyzed(api_client) -> str:
    files = {"file": ("整體品質計畫.docx", make_docx_bytes(), "application/octet-stream")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()[
        "document_id"
    ]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    return document_id


async def check(api_client) -> dict:
    response = await api_client.post("/api/regulation-changes/check")
    assert response.status_code == 200, response.text
    return response.json()


async def open_changes(api_client) -> list[dict]:
    return (await api_client.get("/api/regulation-changes")).json()["items"]


class TestNoChanges:
    async def test_an_unchanged_source_produces_no_changes(self, api_client, source, analyzed):
        body = await check(api_client)

        assert body["checked"] > 0
        assert (body["changed"], body["new_changes"]) == (0, [])

    async def test_only_referenced_regulations_are_checked(self, api_client, source, analyzed):
        """假資料有 24 部，範例文件只引用到其中一部分。"""
        referenced = {
            r["regulation_id"]
            for r in (
                await api_client.get(
                    f"/api/documents/{analyzed}/references", params={"page_size": 500}
                )
            ).json()["items"]
            if r["regulation_id"]
        }

        body = await check(api_client)

        assert body["checked"] + len(body["skipped"]) == len(referenced)

    async def test_nothing_to_check_without_documents(self, api_client, source):
        body = await check(api_client)

        assert (body["checked"], body["skipped"]) == (0, [])


class TestDetectingChanges:
    async def test_a_repeal_is_detected(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}

        body = await check(api_client)

        assert body["changed"] == 1
        change = body["new_changes"][0]
        assert change["regulation_name"] == "政府採購法"
        assert change["changes"] == {
            "status": {"old": RegulationStatus.ACTIVE, "new": RegulationStatus.REPEALED}
        }

    async def test_the_master_record_is_updated(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}

        change = (await check(api_client))["new_changes"][0]
        detail = (await api_client.get(f"/api/regulations/{change['regulation_id']}")).json()

        assert change["current_status"] == detail["status"] == RegulationStatus.REPEALED

    async def test_references_keep_the_status_they_were_matched_with(
        self, api_client, source, analyzed
    ):
        """要不要重新分析由人決定——已覆核過的結論不能被安靜地改掉。"""
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}
        await check(api_client)

        references = (
            await api_client.get(f"/api/documents/{analyzed}/references", params={"page_size": 500})
        ).json()["items"]
        procurement = [r for r in references if r["normalized_name"] == "政府採購法"]

        assert procurement and all(r["status"] == RegulationStatus.ACTIVE for r in procurement)

    async def test_affected_documents_are_listed(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}

        change = (await check(api_client))["new_changes"][0]

        assert [d["document_id"] for d in change["affected_documents"]] == [analyzed]
        assert change["affected_documents"][0]["references"] == 2

    async def test_an_amendment_date_change_is_detected(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"last_amended_date": date(2030, 1, 1)}

        change = (await check(api_client))["new_changes"][0]

        assert change["changes"]["last_amended_date"]["new"] == "2030-01-01"

    async def test_a_second_run_does_not_repeat_the_same_change(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}
        await check(api_client)

        assert (await check(api_client))["changed"] == 0
        assert len(await open_changes(api_client)) == 1

    async def test_a_vanished_regulation_is_reported_not_repealed(
        self, api_client, source, analyzed
    ):
        """來源查不到不等於廢止（可能是更名），狀態不能自己改。"""
        source.removed.add("政府採購法")

        change = (await check(api_client))["new_changes"][0]

        assert change["changes"] == {"presence": {"old": "found", "new": "missing"}}
        assert change["current_status"] == RegulationStatus.ACTIVE

    async def test_a_vanished_regulation_is_reported_once(self, api_client, source, analyzed):
        source.removed.add("政府採購法")
        await check(api_client)

        assert (await check(api_client))["changed"] == 0


class TestSkipping:
    async def test_an_unready_source_is_skipped_with_the_reason(self, api_client, source, analyzed):
        """「沒有異動」和「沒查」要分得出來。"""
        source.ready = False

        body = await check(api_client)

        assert body["checked"] == 0
        assert body["skipped"] and all(r["reason"] == "假資料檔不見了" for r in body["skipped"])

    async def test_a_failing_query_is_skipped(self, api_client, source, analyzed):
        source.failing = True

        body = await check(api_client)

        assert body["checked"] == 0
        assert all("連線逾時" in r["reason"] for r in body["skipped"])


class TestAcknowledging:
    async def test_acknowledged_changes_leave_the_open_list(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}
        change = (await check(api_client))["new_changes"][0]

        response = await api_client.post(
            f"/api/regulation-changes/{change['change_id']}/acknowledge"
        )

        assert response.json()["acknowledged_by"] == "test-admin"
        assert await open_changes(api_client) == []
        everything = (
            await api_client.get("/api/regulation-changes", params={"include_acknowledged": True})
        ).json()
        assert everything["total"] == 1

    async def test_an_unknown_change_is_404(self, api_client):
        response = await api_client.post(
            "/api/regulation-changes/00000000-0000-0000-0000-000000000000/acknowledge"
        )

        assert response.status_code == 404

    async def test_check_and_acknowledge_are_audited(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}
        change = (await check(api_client))["new_changes"][0]
        await api_client.post(f"/api/regulation-changes/{change['change_id']}/acknowledge")

        actions = [
            item["action"]
            for item in (await api_client.get("/api/audit-logs")).json()["items"]
        ]
        assert AuditAction.REGULATION_CHANGES_CHECKED in actions
        assert AuditAction.REGULATION_CHANGE_ACKNOWLEDGED in actions

    async def test_the_dashboard_counts_open_changes(self, api_client, source, analyzed):
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}
        await check(api_client)

        assert (await api_client.get("/api/dashboard")).json()["open_regulation_changes"] == 1


class TestReviewIsUntouched:
    async def test_a_reviewed_reference_stays_reviewed(self, api_client, source, analyzed):
        references = (
            await api_client.get(f"/api/documents/{analyzed}/references", params={"page_size": 500})
        ).json()["items"]
        target = next(r for r in references if r["normalized_name"] == "政府採購法")
        await api_client.patch(
            f"/api/regulation-references/{target['reference_id']}/review",
            json={"review_status": ReviewStatus.CONFIRMED},
        )
        source.overrides["政府採購法"] = {"status": RegulationStatus.REPEALED}

        await check(api_client)

        detail = (await api_client.get(f"/api/regulation-references/{target['reference_id']}")).json()
        assert detail["review_status"] == ReviewStatus.CONFIRMED
