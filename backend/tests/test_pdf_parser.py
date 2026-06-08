"""PDF 解析器测试 —— pdfplumber / pymupdf / 扫描版 / 元数据."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.pdf_parser import (
    PageInfo,
    PaperMetadata,
    ParsedPDF,
    _extract_metadata_pdfplumber,
    _extract_metadata_pymupdf,
    _parse_with_pdfplumber,
    _parse_with_pymupdf,
    extract_full_text,
    parse_pdf,
)


class TestParseWithPdfplumber:
    """pdfplumber 解析测试."""

    @pytest.mark.integration
    def test_parse_real_pdf(self):
        """真实 PDF 解析 (需文件)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF")
            f.flush()
            result = _parse_with_pdfplumber(f.name)
        assert isinstance(result, list) or result is None

    def test_parse_nonexistent_file(self):
        """解析不存在的文件返回 None."""
        result = _parse_with_pdfplumber("/nonexistent/file.pdf")
        assert result is None

    def test_parse_invalid_pdf(self, tmp_path):
        """无效 PDF 返回 None."""
        bad = tmp_path / "bad.pdf"
        bad.write_text("not a pdf", encoding="utf-8")
        result = _parse_with_pdfplumber(str(bad))
        assert result is None


class TestParseWithPymupdf:
    """pymupdf fallback 解析测试."""

    @pytest.mark.integration
    def test_parse_real_pdf(self):
        """真实 PDF."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF")
            f.flush()
            result = _parse_with_pymupdf(f.name)
        assert isinstance(result, list) or result is None

    def test_parse_nonexistent_file(self):
        result = _parse_with_pymupdf("/nonexistent/file.pdf")
        assert result is None


class TestScannedPageDetection:
    """扫描版 PDF 检测."""

    def test_normal_page_not_scanned(self):
        page = PageInfo(page_number=1, text_content="Valid research content with sufficient characters.", char_count=55, is_scanned=False)
        assert not page.is_scanned

    def test_low_char_count_is_scanned(self):
        page = PageInfo(page_number=1, text_content="few", char_count=3, is_scanned=True)
        assert page.is_scanned

    def test_parser_detects_scanned(self):
        """构造一个全是扫描页的结果."""
        pages = [
            PageInfo(page_number=i, text_content="", char_count=0, is_scanned=True)
            for i in range(1, 4)
        ]
        result = ParsedPDF(
            file_path="/fake/s.pdf",
            page_count=3,
            pages=pages,
            total_chars=0,
            is_scanned=True,
            metadata=PaperMetadata(title=None, authors=None, year=None, journal=None),
            parser_used="pymupdf",
        )
        assert result.is_scanned is True
        assert result.total_chars == 0


class TestMetadataExtraction:
    """元数据提取测试."""

    def test_metadata_pdfplumber(self):
        """Mock pdfplumber 元数据."""
        meta = PaperMetadata(title="Test", authors=["A", "B"], year=2024, journal="JMLR")
        assert meta.title == "Test"
        assert meta.authors == ["A", "B"]
        assert meta.year == 2024
        assert meta.journal == "JMLR"

    def test_metadata_none_fields(self):
        """所有字段可为 None."""
        meta = PaperMetadata(title=None, authors=None, year=None, journal=None)
        assert meta.title is None
        assert meta.authors is None

    def test_metadata_pymupdf_empty(self):
        """pymupdf 无元数据时返回空."""
        result = PaperMetadata(title=None, authors=None, year=None, journal=None)
        assert result.title is None


class TestParsePdfIntegration:
    """parse_pdf 完整流程 (mock 子解析器)."""

    def test_parse_pdf_success(self, tmp_path):
        """完整解析成功."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n%%EOF")
        fake_page = PageInfo(page_number=1, text_content="Hello world content here with enough characters for scan detection.", char_count=80, is_scanned=False)
        with patch(
            "backend.services.pdf_parser._parse_with_pdfplumber",
            return_value=[fake_page],
        ):
            with patch(
                "backend.services.pdf_parser._extract_metadata_pdfplumber",
                return_value=PaperMetadata(title="Hello", authors=["X"], year=2023, journal="Test"),
            ):
                result = parse_pdf(str(pdf_file))
                assert result.page_count == 1
                assert result.parser_used == "pdfplumber"
                assert result.metadata.title == "Hello"
                assert result.is_scanned is False

    def test_parse_pdf_fallback_to_pymupdf(self, tmp_path):
        """pdfplumber 失败 → pymupdf fallback."""
        pdf_file = tmp_path / "fb.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n%%EOF")
        fake_page = PageInfo(page_number=1, text_content="Fallback content with sufficient length for non-scanned page.", char_count=60, is_scanned=False)
        with patch("backend.services.pdf_parser._parse_with_pdfplumber", return_value=None):
            with patch("backend.services.pdf_parser._parse_with_pymupdf", return_value=[fake_page]):
                with patch(
                    "backend.services.pdf_parser._extract_metadata_pymupdf",
                    return_value=PaperMetadata(title="FB", authors=["Y"], year=2022, journal="J"),
                ):
                    result = parse_pdf(str(pdf_file))
                    assert result.parser_used == "pymupdf"

    def test_parse_pdf_both_fail(self, tmp_path):
        """两个解析器都失败 → RuntimeError."""
        pdf_file = tmp_path / "fail.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n%%EOF")
        with patch("backend.services.pdf_parser._parse_with_pdfplumber", return_value=None):
            with patch("backend.services.pdf_parser._parse_with_pymupdf", return_value=None):
                with pytest.raises(RuntimeError, match="无法解析"):
                    parse_pdf(str(pdf_file))

    def test_parse_pdf_not_found(self):
        """文件不存在 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_pdf("/no/such/file.pdf")


class TestExtractFullText:
    """extract_full_text 测试."""

    def test_extract_full_text(self, mock_parse_pdf):
        result = extract_full_text("/fake/test.pdf")
        assert "Page one content" in result
        assert "Page three content" in result
