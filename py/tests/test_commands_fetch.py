"""Offline tests for URL fetching (kb_ai.commands.fetch).

trafilatura is monkeypatched throughout, so no network access happens.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from kb_ai.commands import fetch


@pytest.fixture
def stub_trafilatura(monkeypatch):
    """Patch trafilatura with configurable canned results."""
    state = {
        "downloaded": "<html>page</html>",
        "content": "# Title\n\nbody",
        "metadata": SimpleNamespace(title="Real Title", date="2026-01-15"),
        "extract_kwargs": {},
    }

    monkeypatch.setattr(fetch.trafilatura, "fetch_url", lambda url: state["downloaded"])

    def fake_extract(downloaded, **kwargs):
        state["extract_kwargs"] = kwargs
        return state["content"]

    monkeypatch.setattr(fetch.trafilatura, "extract", fake_extract)
    monkeypatch.setattr(fetch.trafilatura, "extract_metadata", lambda d: state["metadata"])
    return state


def test_fetch_url_returns_extracted_document(stub_trafilatura):
    out = fetch.fetch_url("https://example.com/post")

    assert out == {
        "title": "Real Title",
        "content": "# Title\n\nbody",
        "date": "2026-01-15",
        "url": "https://example.com/post",
    }


def test_fetch_url_requests_markdown_with_links_and_tables(stub_trafilatura):
    fetch.fetch_url("https://example.com/post")

    assert stub_trafilatura["extract_kwargs"] == {
        "output_format": "markdown",
        "include_links": True,
        "include_tables": True,
    }


def test_fetch_url_raises_when_download_fails(stub_trafilatura):
    stub_trafilatura["downloaded"] = None

    with pytest.raises(ValueError, match="failed to download"):
        fetch.fetch_url("https://example.com/gone")


@pytest.mark.parametrize("content", [None, ""])
def test_fetch_url_raises_when_extraction_is_empty(stub_trafilatura, content):
    stub_trafilatura["content"] = content

    with pytest.raises(ValueError, match="failed to extract content"):
        fetch.fetch_url("https://example.com/empty")


# ── title / date fallbacks ──────────────────────────────────────────

@pytest.mark.parametrize("metadata", [
    None,
    SimpleNamespace(title=None, date=None),
    SimpleNamespace(title="", date=""),
])
def test_fetch_url_falls_back_to_url_slug_and_today(stub_trafilatura, metadata):
    stub_trafilatura["metadata"] = metadata

    out = fetch.fetch_url("https://example.com/blog/my-post")

    assert out["title"] == "my-post"
    assert out["date"] == date.today().isoformat()


def test_fetch_url_strips_trailing_slash_for_title(stub_trafilatura):
    stub_trafilatura["metadata"] = None

    out = fetch.fetch_url("https://example.com/blog/my-post/")

    assert out["title"] == "my-post"


def test_fetch_url_title_falls_back_to_url_when_no_slug(stub_trafilatura):
    """A degenerate URL with no usable last segment must still yield a title."""
    stub_trafilatura["metadata"] = None

    out = fetch.fetch_url("///")

    assert out["title"] == "///"


def test_fetch_url_keeps_metadata_date_without_title(stub_trafilatura):
    stub_trafilatura["metadata"] = SimpleNamespace(title=None, date="2025-12-01")

    out = fetch.fetch_url("https://example.com/x/report")

    assert out["title"] == "report"
    assert out["date"] == "2025-12-01"
