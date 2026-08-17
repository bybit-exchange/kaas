"""Convert rich document formats to Markdown using Microsoft MarkItDown.

Wraps MarkItDown to convert PDF, DOCX, PPTX, XLSX, HTML, EPUB, and RTF files
into Markdown text suitable for the extraction pipeline.
"""

from __future__ import annotations

from pathlib import Path

from markitdown import MarkItDown

# Extensions that require MarkItDown conversion. Kept in sync with the Go-side
# richExtensions map in internal/api/submit_files.go.
RICH_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".epub", ".rtf"}
)

_converter = MarkItDown()


def needs_conversion(file_path: str | Path) -> bool:
    """Return True if the file extension requires MarkItDown conversion."""
    ext = Path(file_path).suffix.lower()
    return ext in RICH_EXTENSIONS


def convert_to_markdown(file_path: Path) -> str:
    """Convert a rich document to Markdown text.

    Args:
        file_path: Absolute path to the document file.

    Returns:
        Markdown text content.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If conversion produces empty content.
        RuntimeError: If MarkItDown fails to convert.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"file not found: {file_path}")

    try:
        result = _converter.convert(str(file_path))
    except Exception as e:
        raise RuntimeError(
            f"MarkItDown conversion failed for {file_path.name}: {e}"
        ) from e

    content = (result.text_content or "").strip()
    if not content:
        raise ValueError(
            f"conversion produced empty content for {file_path.name}"
        )

    return content
