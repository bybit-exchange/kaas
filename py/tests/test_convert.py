"""Tests for kb_ai.convert module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kb_ai.convert import RICH_EXTENSIONS, convert_to_markdown, needs_conversion


class TestNeedsConversion:
    """Tests for needs_conversion()."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/tmp/doc.pdf", True),
            ("/tmp/doc.docx", True),
            ("/tmp/doc.pptx", True),
            ("/tmp/doc.xlsx", True),
            ("/tmp/doc.html", True),
            ("/tmp/doc.htm", True),
            ("/tmp/doc.epub", True),
            ("/tmp/doc.rtf", True),
            ("/tmp/doc.md", False),
            ("/tmp/doc.txt", False),
            ("/tmp/doc.csv", False),
            ("/tmp/doc.json", False),
            ("/tmp/doc.xml", False),
            ("/tmp/doc.zip", False),
        ],
    )
    def test_extension_detection(self, path: str, expected: bool):
        assert needs_conversion(path) is expected

    def test_accepts_path_object(self):
        assert needs_conversion(Path("/tmp/report.pdf")) is True

    def test_case_insensitive(self):
        # Path.suffix preserves case; needs_conversion lowercases it
        assert needs_conversion("/tmp/DOC.PDF") is True
        assert needs_conversion("/tmp/doc.Docx") is True


class TestRichExtensions:
    """Tests for the RICH_EXTENSIONS constant."""

    def test_contains_expected_extensions(self):
        expected = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".epub", ".rtf"}
        assert RICH_EXTENSIONS == expected

    def test_is_frozenset(self):
        assert isinstance(RICH_EXTENSIONS, frozenset)


class TestConvertToMarkdown:
    """Tests for convert_to_markdown()."""

    def test_file_not_found(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.pdf"
        with pytest.raises(FileNotFoundError, match="file not found"):
            convert_to_markdown(missing)

    @patch("kb_ai.convert._converter")
    def test_empty_output_raises_value_error(self, mock_conv: MagicMock, tmp_path: Path):
        # Create a dummy file so the existence check passes
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        mock_result = MagicMock()
        mock_result.text_content = ""
        mock_conv.convert.return_value = mock_result

        with pytest.raises(ValueError, match="empty content"):
            convert_to_markdown(f)

    @patch("kb_ai.convert._converter")
    def test_whitespace_only_raises_value_error(self, mock_conv: MagicMock, tmp_path: Path):
        f = tmp_path / "whitespace.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        mock_result = MagicMock()
        mock_result.text_content = "   \n\n  "
        mock_conv.convert.return_value = mock_result

        with pytest.raises(ValueError, match="empty content"):
            convert_to_markdown(f)

    @patch("kb_ai.convert._converter")
    def test_none_text_content_raises_value_error(self, mock_conv: MagicMock, tmp_path: Path):
        f = tmp_path / "none.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        mock_result = MagicMock()
        mock_result.text_content = None
        mock_conv.convert.return_value = mock_result

        with pytest.raises(ValueError, match="empty content"):
            convert_to_markdown(f)

    @patch("kb_ai.convert._converter")
    def test_conversion_exception_raises_runtime_error(self, mock_conv: MagicMock, tmp_path: Path):
        f = tmp_path / "corrupt.pdf"
        f.write_bytes(b"not a real pdf")

        mock_conv.convert.side_effect = Exception("parse error")

        with pytest.raises(RuntimeError, match="MarkItDown conversion failed"):
            convert_to_markdown(f)

    @patch("kb_ai.convert._converter")
    def test_successful_conversion(self, mock_conv: MagicMock, tmp_path: Path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 content")

        mock_result = MagicMock()
        mock_result.text_content = "# Report\n\nThis is the content."
        mock_conv.convert.return_value = mock_result

        result = convert_to_markdown(f)
        assert result == "# Report\n\nThis is the content."
        mock_conv.convert.assert_called_once_with(str(f))

    @patch("kb_ai.convert._converter")
    def test_strips_surrounding_whitespace(self, mock_conv: MagicMock, tmp_path: Path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"PK\x03\x04 docx")

        mock_result = MagicMock()
        mock_result.text_content = "\n\n  # Title\n\nBody  \n\n"
        mock_conv.convert.return_value = mock_result

        result = convert_to_markdown(f)
        assert result == "# Title\n\nBody"
