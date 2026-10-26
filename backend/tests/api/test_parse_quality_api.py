"""解析品質要走到 API 上。

記在資料庫但不回給前端，等於沒記——使用者還是會拿到一份看起來乾淨的結果，
不知道這份文件有一半的內容壓在圖裡沒讀到。
"""

import pytest

from app.core.enums import JobStatus, ParseQuality
from app.parsers import ocr
from tests.factories import make_pdf_bytes, make_scanned_pdf_bytes


async def analyze(api_client, filename: str, data: bytes) -> dict:
    files = {"file": (filename, data, "application/pdf")}
    document_id = (await api_client.post("/api/documents/upload", files=files)).json()[
        "document_id"
    ]
    await api_client.post(f"/api/documents/{document_id}/analyze")
    return (await api_client.get(f"/api/documents/{document_id}")).json()


class TestParseQualityInResponse:
    async def test_a_figure_heavy_pdf_reports_degraded(self, api_client):
        body = await analyze(
            api_client, "設計規範.pdf", make_pdf_bytes(text_pages=4, figure_pages=6)
        )

        assert body["parse_quality"] == ParseQuality.DEGRADED

    async def test_the_note_reaches_the_client(self, api_client):
        body = await analyze(
            api_client, "設計規範.pdf", make_pdf_bytes(text_pages=4, figure_pages=6)
        )

        assert "以圖為主" in body["parse_quality_note"]

    async def test_a_text_pdf_reports_ok_without_a_note(self, api_client):
        body = await analyze(api_client, "契約書.pdf", make_pdf_bytes(text_pages=10))

        assert body["parse_quality"] == ParseQuality.OK
        assert body["parse_quality_note"] is None

    async def test_a_flagged_document_still_finishes_analysis(self, api_client):
        """標記不是失敗——分析要照常跑完，段落照常存。"""
        body = await analyze(
            api_client, "設計規範.pdf", make_pdf_bytes(text_pages=4, figure_pages=6)
        )

        assert body["latest_job"]["status"] == JobStatus.COMPLETED


class FakeEngine:
    def page_blocks(self, page) -> list[str]:
        return ["本工程依政府採購法第七十條辦理品質管理。" * 15]


class TestScannedPdfThroughTheApi:
    """掃描檔從上傳走到詳細面板：每一步都要看得出「這是 OCR 讀的」。"""

    @pytest.fixture(autouse=True)
    def fake_ocr(self, monkeypatch):
        monkeypatch.setattr(ocr, "load_engine", lambda: (FakeEngine(), None))

    async def test_analysis_finishes_and_the_note_mentions_ocr(self, api_client):
        body = await analyze(api_client, "掃描檔.pdf", make_scanned_pdf_bytes(pages=2))

        assert body["latest_job"]["status"] == JobStatus.COMPLETED
        assert body["parse_quality"] == ParseQuality.DEGRADED
        assert "OCR" in body["parse_quality_note"]

    async def test_the_reference_detail_says_the_text_came_from_ocr(self, api_client):
        body = await analyze(api_client, "掃描檔.pdf", make_scanned_pdf_bytes(pages=1))
        references = (
            await api_client.get(f"/api/documents/{body['document_id']}/references")
        ).json()["items"]
        procurement = next(r for r in references if r["normalized_name"] == "政府採購法")

        detail = (
            await api_client.get(f"/api/regulation-references/{procurement['reference_id']}")
        ).json()

        assert detail["section_is_ocr"] is True
        assert detail["page"] == 1

    async def test_text_pdfs_are_not_marked_as_ocr(self, api_client):
        body = await analyze(api_client, "契約書.pdf", make_pdf_bytes(text_pages=2))
        reference = (
            await api_client.get(f"/api/documents/{body['document_id']}/references")
        ).json()["items"][0]

        detail = (
            await api_client.get(f"/api/regulation-references/{reference['reference_id']}")
        ).json()

        assert detail["section_is_ocr"] is False
