"""Offline tests for the bridge entrypoints of the one-shot commands.

These are the functions the Go daemon dispatches to: they read a JSON request
from stdin and write exactly one JSON response to stdout. The underlying work is
monkeypatched — what is under test here is the stdin/stdout contract.
"""
from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from kb_ai.commands import fetch, rewrite


def _run_with_stdin(fn, payload: dict, capsys) -> dict:
    """Invoke a bridge entrypoint with payload on stdin, return the response."""
    with patch("sys.stdin", StringIO(json.dumps(payload))):
        fn()
    out = capsys.readouterr().out.strip()
    assert out, "entrypoint wrote no response to stdout"
    return json.loads(out)


# ── run_fetch_url ───────────────────────────────────────────────────

def test_run_fetch_url_responds_ok(monkeypatch, capsys):
    doc = {"title": "T", "content": "body", "date": "2026-01-01",
           "url": "https://example.com/a"}
    monkeypatch.setattr(fetch, "fetch_url", lambda url: doc)

    resp = _run_with_stdin(fetch.run_fetch_url, {"url": "https://example.com/a"}, capsys)

    assert resp == {"ok": True, "data": doc}


def test_run_fetch_url_passes_url_through(monkeypatch, capsys):
    seen = {}

    def fake(url):
        seen["url"] = url
        return {"title": "t", "content": "c", "date": "d", "url": url}

    monkeypatch.setattr(fetch, "fetch_url", fake)

    _run_with_stdin(fetch.run_fetch_url, {"url": "https://example.com/x"}, capsys)

    assert seen["url"] == "https://example.com/x"


def test_run_fetch_url_propagates_extraction_failure(monkeypatch, capsys):
    """run_fetch_url has no error boundary of its own — the daemon's dispatcher
    owns that — so the ValueError must surface rather than be swallowed."""
    def boom(url):
        raise ValueError("failed to download: " + url)

    monkeypatch.setattr(fetch, "fetch_url", boom)

    with patch("sys.stdin", StringIO(json.dumps({"url": "https://example.com/gone"}))):
        with pytest.raises(ValueError, match="failed to download"):
            fetch.run_fetch_url()


def test_run_fetch_url_requires_url_key(capsys):
    with patch("sys.stdin", StringIO(json.dumps({}))):
        with pytest.raises(KeyError):
            fetch.run_fetch_url()


# ── run_server_rewrite ──────────────────────────────────────────────

def test_run_server_rewrite_responds_ok(monkeypatch, capsys):
    result = {"rewritten_query": "expanded", "tokens_prompt": 10,
              "tokens_completion": 2, "cost_usd": 0.0001}
    monkeypatch.setattr(rewrite, "rewrite_query", lambda q, h, model: result)

    resp = _run_with_stdin(rewrite.run_server_rewrite, {
        "query": "what about it?",
        "history": [{"role": "user", "content": "kaas?"}],
        "model": "claude-sonnet-4-6",
    }, capsys)

    assert resp == {"ok": True, "data": result}


def test_run_server_rewrite_forwards_query_history_and_model(monkeypatch, capsys):
    seen = {}

    def fake(query, history, model):
        seen.update(query=query, history=history, model=model)
        return {"rewritten_query": query}

    monkeypatch.setattr(rewrite, "rewrite_query", fake)

    history = [{"role": "user", "content": "prior"}]
    _run_with_stdin(rewrite.run_server_rewrite, {
        "query": "q", "history": history, "model": "custom-model",
    }, capsys)

    assert seen == {"query": "q", "history": history, "model": "custom-model"}


def test_run_server_rewrite_defaults_model_and_history(monkeypatch, capsys):
    seen = {}

    def fake(query, history, model):
        seen.update(history=history, model=model)
        return {"rewritten_query": query}

    monkeypatch.setattr(rewrite, "rewrite_query", fake)

    _run_with_stdin(rewrite.run_server_rewrite, {"query": "q"}, capsys)

    assert seen["history"] is None
    assert seen["model"] == "claude-sonnet-4-6"


@pytest.mark.parametrize("payload", [{}, {"query": ""}])
def test_run_server_rewrite_rejects_empty_query(monkeypatch, capsys, payload):
    def boom(*args, **kwargs):
        raise AssertionError("rewrite_query must not run for an empty query")

    monkeypatch.setattr(rewrite, "rewrite_query", boom)

    resp = _run_with_stdin(rewrite.run_server_rewrite, payload, capsys)

    assert resp["ok"] is False
    assert resp["error"]["code"] == "EMPTY_QUERY"
