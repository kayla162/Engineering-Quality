"""掃描版 PDF 的 OCR。

OCR 讀錯字是常態，所以這裡驗的不只是「讀得到」，還有兩件事：
讀出來的段落一定被標記成 OCR；OCR 不能用時，錯誤訊息要說出原因，不能安靜地跳過。

測試不依賴這台機器有沒有裝 Tesseract：除了最後一組，全部換上假的引擎。
"""

from dataclasses import dataclass, field

import pytest

from app.core.config import settings
from app.core.errors import UnprocessableDocumentError
from app.parsers import ocr, parse_document
from tests.factories import make_pdf_bytes, make_scanned_pdf_bytes

OCR_TEXT = "本工程依政府採購法第七十條辦理品質管理。" * 15


@dataclass
class FakeEngine:
    """每頁回傳固定的辨識結果；`fail` 為 True 時模擬辨識失敗。"""

    blocks: list[str] = field(default_factory=lambda: [OCR_TEXT])
    fail: bool = False
    calls: int = 0

    def page_blocks(self, page) -> list[str]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("tesseract crashed")
        return self.blocks


@pytest.fixture
def write(tmp_path):
    def _write(data: bytes):
        path = tmp_path / "文件.pdf"
        path.write_bytes(data)
        return path

    return _write


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(ocr, "load_engine", lambda: (fake, None))
    return fake


@pytest.fixture
def no_engine(monkeypatch):
    monkeypatch.setattr(ocr, "load_engine", lambda: (None, "OCR 已關閉（ENABLE_OCR=false）"))


class TestScannedPdf:
    def test_scanned_pages_are_read_by_ocr(self, write, engine):
        result = parse_document(write(make_scanned_pdf_bytes(pages=2)))

        assert [s.content for s in result.sections] == [OCR_TEXT, OCR_TEXT]
        assert [s.page for s in result.sections] == [1, 2]

    def test_ocr_sections_are_marked(self, write, engine):
        result = parse_document(write(make_scanned_pdf_bytes(pages=2)))

        assert all(s.is_ocr for s in result.sections)

    def test_a_scanned_document_is_flagged_with_an_ocr_note(self, write, engine):
        coverage = parse_document(write(make_scanned_pdf_bytes(pages=2))).coverage

        assert coverage.ocr_pages == 2
        assert coverage.is_degraded is True
        assert "OCR" in coverage.note

    def test_block_whitespace_is_collapsed(self, write, engine):
        engine.blocks = ["混凝土\n應符合CNS\n3090  規定。" + "。" * 200]

        result = parse_document(write(make_scanned_pdf_bytes(pages=1)))

        assert result.sections[0].content.startswith("混凝土 應符合CNS 3090 規定。")

    def test_without_ocr_the_error_says_why(self, write, no_engine):
        with pytest.raises(UnprocessableDocumentError, match="ENABLE_OCR=false"):
            parse_document(write(make_scanned_pdf_bytes(pages=1)))

    def test_when_ocr_reads_nothing_the_error_says_ocr_was_tried(self, write, engine):
        engine.blocks = []

        with pytest.raises(UnprocessableDocumentError, match="已嘗試 OCR"):
            parse_document(write(make_scanned_pdf_bytes(pages=1)))

    def test_a_failing_page_does_not_crash_the_document(self, write, engine, caplog):
        """單頁辨識失敗記 log、當作沒讀到；整份都失敗才報錯。"""
        engine.fail = True

        with pytest.raises(UnprocessableDocumentError, match="已嘗試 OCR"):
            parse_document(write(make_scanned_pdf_bytes(pages=2)))
        assert engine.calls == 2
        assert "OCR 辨識失敗" in caplog.text


class TestMixedPdf:
    def test_text_pages_are_not_sent_to_ocr(self, write, monkeypatch):
        """純文字 PDF 連語言資料都不該去找。"""

        def must_not_load():
            raise AssertionError("text PDF should not load OCR")

        monkeypatch.setattr(ocr, "load_engine", must_not_load)

        result = parse_document(write(make_pdf_bytes(text_pages=3)))

        assert not any(s.is_ocr for s in result.sections)

    def test_ocr_that_reads_less_than_the_text_layer_is_ignored(self, write, engine):
        """圖頁上的圖號是向量文字；OCR 讀回來的比它少，就保留原本的文字。"""
        engine.blocks = ["圖"]

        result = parse_document(write(make_pdf_bytes(text_pages=1, figure_pages=1)))

        figure_page = [s for s in result.sections if s.page == 2]
        assert [s.content for s in figure_page] == ["圖1"]
        assert not any(s.is_ocr for s in figure_page)
        assert result.coverage.ocr_pages == 0

    def test_the_engine_is_loaded_once_per_document(self, write, monkeypatch):
        fake = FakeEngine()
        loads = []

        def load():
            loads.append(1)
            return fake, None

        monkeypatch.setattr(ocr, "load_engine", load)

        parse_document(write(make_pdf_bytes(text_pages=1, figure_pages=3)))

        assert (len(loads), fake.calls) == (1, 3)

    def test_without_ocr_figure_pages_are_flagged_with_the_reason(self, write, no_engine):
        coverage = parse_document(write(make_pdf_bytes(text_pages=4, figure_pages=6))).coverage

        assert coverage.is_degraded is True
        assert "ENABLE_OCR=false" in coverage.note


class TestLoadEngine:
    @pytest.fixture(autouse=True)
    def enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_OCR", True)
        monkeypatch.setattr(settings, "OCR_LANGUAGES", "chi_tra+eng")

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_OCR", False)

        engine, reason = ocr.load_engine()

        assert engine is None and "ENABLE_OCR" in reason

    def test_a_missing_tessdata_folder(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "TESSDATA_PATH", str(tmp_path / "nowhere"))

        engine, reason = ocr.load_engine()

        assert engine is None and "TESSDATA_PATH" in reason

    def test_a_missing_language_is_named(self, monkeypatch, tmp_path):
        """裝了 Tesseract 但沒有繁中語言資料，是 Windows 安裝程式的預設狀況。"""
        (tmp_path / "eng.traineddata").write_bytes(b"")
        monkeypatch.setattr(settings, "TESSDATA_PATH", str(tmp_path))

        engine, reason = ocr.load_engine()

        assert engine is None and "缺少 chi_tra（" in reason

    def test_all_languages_present(self, monkeypatch, tmp_path):
        for lang in ("chi_tra", "eng"):
            (tmp_path / f"{lang}.traineddata").write_bytes(b"")
        monkeypatch.setattr(settings, "TESSDATA_PATH", str(tmp_path))

        engine, reason = ocr.load_engine()

        assert reason is None
        assert (engine.tessdata, engine.languages) == (tmp_path, "chi_tra+eng")


def _real_engine():
    """這台機器真的能跑繁中 OCR 時才回傳引擎。"""
    original = settings.ENABLE_OCR
    settings.ENABLE_OCR = True
    try:
        engine, _ = ocr.load_engine()
    finally:
        settings.ENABLE_OCR = original
    return engine


@pytest.mark.skipif(_real_engine() is None, reason="這台機器沒有 Tesseract 繁中語言資料")
class TestRealTesseract:
    """真的跑一次 Tesseract：假引擎驗不到 PyMuPDF 的呼叫方式是不是對的。"""

    def test_a_scanned_page_is_read(self, write, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_OCR", True)

        result = parse_document(write(make_scanned_pdf_bytes(pages=1)))

        text = "".join(s.content for s in result.sections).replace(" ", "")
        assert "政府採購法" in text
        assert all(s.is_ocr for s in result.sections)
