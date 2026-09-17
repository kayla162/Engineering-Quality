"""文件解析與上傳驗證的單元測試。"""

import pytest

from app.core.enums import ContentType
from app.core.errors import InvalidFileTypeError, UnprocessableDocumentError
from app.core.security import file_hash, sanitize_filename, validate_upload
from app.parsers import parse_document
from tests.factories import make_docx_bytes, make_txt_bytes


class TestParsers:
    def test_docx_keeps_headings_paragraphs_and_table_cells(self, tmp_path):
        path = tmp_path / "sample.docx"
        path.write_bytes(make_docx_bytes())

        sections = parse_document(path)
        types = {section.content_type for section in sections}
        assert ContentType.HEADING in types
        assert ContentType.PARAGRAPH in types
        assert ContentType.CELL in types
        # order_index 必須連續，前端才能還原文件順序
        assert [s.order_index for s in sections] == list(range(len(sections)))

    def test_txt_splits_by_line(self, tmp_path):
        path = tmp_path / "sample.txt"
        path.write_bytes(make_txt_bytes())
        sections = parse_document(path)
        assert len(sections) == 5
        assert all(section.content_type == ContentType.PARAGRAPH for section in sections)

    def test_txt_handles_big5(self, tmp_path):
        path = tmp_path / "big5.txt"
        path.write_bytes("依政府採購法辦理".encode("cp950"))
        assert parse_document(path)[0].content == "依政府採購法辦理"

    def test_broken_docx_raises_readable_error(self, tmp_path):
        path = tmp_path / "broken.docx"
        path.write_bytes(b"PK\x03\x04 not really a docx")
        with pytest.raises(UnprocessableDocumentError):
            parse_document(path)

    def test_unknown_extension_is_rejected(self, tmp_path):
        path = tmp_path / "file.rtf"
        path.write_bytes(b"x")
        with pytest.raises(InvalidFileTypeError):
            parse_document(path)


class TestUploadValidation:
    def test_accepts_docx(self):
        assert validate_upload("計畫.docx", make_docx_bytes()) == ".docx"

    def test_rejects_unlisted_extension(self):
        with pytest.raises(InvalidFileTypeError):
            validate_upload("virus.exe", b"MZ...")

    def test_rejects_faked_extension(self):
        """副檔名說是 docx，內容卻不是 zip。"""
        with pytest.raises(InvalidFileTypeError):
            validate_upload("fake.docx", b"this is plain text")

    def test_rejects_empty_file(self):
        with pytest.raises(InvalidFileTypeError):
            validate_upload("empty.txt", b"")

    def test_hash_is_stable_and_content_based(self):
        assert file_hash(b"abc") == file_hash(b"abc")
        assert file_hash(b"abc") != file_hash(b"abd")

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("../../etc/passwd", "passwd"),
            ("整體品質計畫.docx", "整體品質計畫.docx"),
            ("a<b>c.txt", "a_b_c.txt"),
        ],
    )
    def test_sanitize_filename(self, raw, expected):
        assert sanitize_filename(raw) == expected
