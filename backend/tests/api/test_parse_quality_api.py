"""解析品質要走到 API 上。

記在資料庫但不回給前端，等於沒記——使用者還是會拿到一份看起來乾淨的結果，
不知道這份文件有一半的內容壓在圖裡沒讀到。
"""

import pytest

from app.core.enums import JobStatus, ParseQuality
from tests.factories import make_pdf_bytes


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
