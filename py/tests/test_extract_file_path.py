"""Tests for file_path support in the extract command.

Verifies that:
- file_path triggers MarkItDown conversion
- Converted .md file is written atomically alongside the binary
- Path traversal is rejected
- Missing file returns FILE_NOT_FOUND
- Conversion failure returns CONVERSION_FAILED
- Write failure returns WRITE_FAILED
- content='' with file_path='' returns EMPTY_CONTENT (backward-compatible)
- Existing content-based flow still works unchanged
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kb_ai import server_daemon as sd
from kb_ai.core.extract import ExtractionResult


# ── helpers ─────────────────────────────────────────────────────────

def responses(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def one_response(capsys) -> dict:
    got = responses(capsys)
    assert len(got) == 1, f"expected exactly 1 response, got {got}"
    return got[0]


def request(cmd: str, request_id: str = "1", **payload) -> dict:
    return {"id": request_id, "cmd": cmd, "payload": payload}


def extract_request(kb_dir, **kwargs):
    kwargs.setdefault("source", "raw/a.pdf")
    return request("extract", kb_dir=kb_dir, **kwargs)


@pytest.fixture
def kb(tmp_path):
    """A KB directory with a sample PDF file."""
    return str(tmp_path)


@pytest.fixture
def pdf_file(tmp_path):
    """A fake PDF file inside the KB directory."""
    f = tmp_path / "raw" / "doc.pdf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"%PDF-1.4 fake content")
    return f


@pytest.fixture
def stub_extract(monkeypatch):
    """Patch kb_ai.core.extract so extraction can succeed without LLM calls."""
    import kb_ai.core.extract as ex

    state = {"chunks": ["c1"], "transcript": False, "routed": None}

    monkeypatch.setattr(ex, "_parse_frontmatter", lambda content: ({"meta": True}, "body"))
    monkeypatch.setattr(ex, "_is_transcript", lambda meta: state["transcript"])
    monkeypatch.setattr(ex, "chunk_content", lambda content: state["chunks"])
    monkeypatch.setattr(ex, "chunk_transcript", lambda body, meta: state["chunks"])

    def chunked(content, model):
        state["routed"] = "chunked"
        state["content"] = content
        return ExtractionResult(summary="chunked-result")

    def summarized(chunks, meta, summarize_model, model):
        state["routed"] = "summarize"
        return ExtractionResult(summary="summarized-result")

    monkeypatch.setattr(ex, "extract_knowledge_chunked", chunked)
    monkeypatch.setattr(ex, "extract_knowledge_summarized", summarized)
    return state


# ── backward compatibility ──────────────────────────────────────────

def test_empty_content_and_empty_file_path_returns_empty_content(capsys):
    """content='' with file_path='' returns EMPTY_CONTENT (backward-compatible)."""
    sd._handle_extract("1", request("extract", content="", file_path="",
                                    kb_dir="/tmp/kb", source="raw/a.md"))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "EMPTY_CONTENT"


def test_content_without_file_path_still_works(capsys, kb, stub_extract):
    """Existing content-based flow works unchanged."""
    sd._handle_extract("1", extract_request(kb, content="some text"))
    resp = one_response(capsys)
    assert resp["ok"] is True
    assert resp["data"]["extraction"]["summary"] == "chunked-result"
    assert stub_extract["routed"] == "chunked"


# ── path traversal ──────────────────────────────────────────────────

def test_path_traversal_rejected(capsys, tmp_path):
    """file_path not under kb_dir returns INVALID_PATH error."""
    kb_dir = str(tmp_path / "kb")
    os.makedirs(kb_dir, exist_ok=True)
    # file_path outside kb_dir
    outside = str(tmp_path / "outside" / "evil.pdf")

    sd._handle_extract("1", extract_request(kb_dir, file_path=outside,
                                            content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_PATH"


def test_path_traversal_via_dotdot_rejected(capsys, tmp_path):
    """Symlink-like traversal via .. is rejected."""
    kb_dir = str(tmp_path / "kb")
    os.makedirs(kb_dir, exist_ok=True)
    # Path that resolves outside kb_dir
    traversal_path = os.path.join(kb_dir, "..", "secret.pdf")

    sd._handle_extract("1", extract_request(kb_dir, file_path=traversal_path,
                                            content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_PATH"


# ── missing file ────────────────────────────────────────────────────

def test_missing_file_returns_file_not_found(capsys, tmp_path):
    """file_path pointing to non-existent file returns FILE_NOT_FOUND."""
    kb_dir = str(tmp_path)
    missing = str(tmp_path / "raw" / "missing.pdf")

    sd._handle_extract("1", extract_request(kb_dir, file_path=missing,
                                            content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "FILE_NOT_FOUND"


# ── conversion failure ──────────────────────────────────────────────

def test_conversion_failure_returns_error(capsys, kb, pdf_file):
    """Conversion failure returns CONVERSION_FAILED error."""
    with patch("kb_ai.convert.convert_to_markdown",
               side_effect=RuntimeError("MarkItDown failed")):
        sd._handle_extract("1", extract_request(kb, file_path=str(pdf_file),
                                                content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CONVERSION_FAILED"
    assert "MarkItDown failed" in resp["error"]["message"]


def test_conversion_empty_returns_error(capsys, kb, pdf_file):
    """ValueError from convert (empty content) returns CONVERSION_FAILED."""
    with patch("kb_ai.convert.convert_to_markdown",
               side_effect=ValueError("conversion produced empty content")):
        sd._handle_extract("1", extract_request(kb, file_path=str(pdf_file),
                                                content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CONVERSION_FAILED"


# ── write failure ───────────────────────────────────────────────────

def test_write_failure_returns_error(capsys, kb, pdf_file, stub_extract):
    """Write failure returns WRITE_FAILED error."""
    with patch("kb_ai.convert.convert_to_markdown", return_value="# Hello"):
        with patch("tempfile.mkstemp", side_effect=OSError("disk full")):
            sd._handle_extract("1", extract_request(
                kb, file_path=str(pdf_file), content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "WRITE_FAILED"


def test_write_failure_on_replace_returns_error(capsys, kb, pdf_file, stub_extract):
    """Write failure during os.replace returns WRITE_FAILED."""
    with patch("kb_ai.convert.convert_to_markdown", return_value="# Hello"):
        with patch("os.replace", side_effect=OSError("permission denied")):
            sd._handle_extract("1", extract_request(
                kb, file_path=str(pdf_file), content=""))
    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "WRITE_FAILED"


# ── successful conversion ───────────────────────────────────────────

def test_file_path_triggers_conversion_and_extraction(capsys, kb, pdf_file, stub_extract):
    """file_path triggers MarkItDown conversion and proceeds with extraction."""
    with patch("kb_ai.convert.convert_to_markdown", return_value="# Converted\n\nContent"):
        sd._handle_extract("1", extract_request(
            kb, file_path=str(pdf_file), content="",
            source="raw/doc.pdf"))
    resp = one_response(capsys)
    assert resp["ok"] is True
    assert resp["data"]["extraction"]["summary"] == "chunked-result"
    assert stub_extract["content"] == "# Converted\n\nContent"


def test_file_path_writes_md_file_atomically(capsys, kb, pdf_file, stub_extract):
    """Converted .md file is written alongside the binary."""
    with patch("kb_ai.convert.convert_to_markdown", return_value="# Doc"):
        sd._handle_extract("1", extract_request(
            kb, file_path=str(pdf_file), content="",
            source="raw/doc.pdf"))
    resp = one_response(capsys)
    assert resp["ok"] is True

    md_path = pdf_file.with_suffix(".md")
    assert md_path.exists()
    assert md_path.read_text() == "# Doc"


def test_file_path_normalises_newlines(capsys, kb, pdf_file, stub_extract):
    """CRLF in converted text is normalised to LF."""
    with patch("kb_ai.convert.convert_to_markdown",
               return_value="Line1\r\nLine2\r\nLine3"):
        sd._handle_extract("1", extract_request(
            kb, file_path=str(pdf_file), content="",
            source="raw/doc.pdf"))
    resp = one_response(capsys)
    assert resp["ok"] is True

    md_path = pdf_file.with_suffix(".md")
    assert md_path.read_text() == "Line1\nLine2\nLine3"
    # Extraction also receives normalised content
    assert stub_extract["content"] == "Line1\nLine2\nLine3"


def test_file_path_with_content_prefers_file_path(capsys, kb, pdf_file, stub_extract):
    """When both file_path and content are set, file_path conversion overrides content."""
    with patch("kb_ai.convert.convert_to_markdown", return_value="# From file"):
        sd._handle_extract("1", extract_request(
            kb, file_path=str(pdf_file), content="old content",
            source="raw/doc.pdf"))
    resp = one_response(capsys)
    assert resp["ok"] is True
    # The converted content should be used, not the original
    assert stub_extract["content"] == "# From file"
