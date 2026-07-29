"""Offline unit tests for the MCP server's `ask` tool collector.

The `ask` tool wraps the existing chat core (`run_server_chat_http`) which
emits delta/done events to a callback. These tests monkeypatch that core with
a fake emitter so the collector logic — accumulating deltas into an answer,
extracting sources/cost from `done`, appending a Sources footer, error
mapping — is exercised offline without an LLM or network.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

import kb_ai.server_mcp as mcp_server


def _fake_core(events):
    """Build a fake run_server_chat_http that replays `events` to emit_fn."""
    def fake(input_data, emit_fn):
        fake.seen_input = input_data
        for ev in events:
            emit_fn(ev)
    return fake


# ── Collector: deltas → answer, done → sources/cost ──────────────────

def test_ask_collects_deltas_into_answer(monkeypatch):
    events = [
        {"type": "status", "stage": "retrieved", "sources": []},
        {"type": "delta", "content": "Hello "},
        {"type": "delta", "content": "world"},
        {"type": "done", "cited_sources": [], "cost_usd": 0.0},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    out = mcp_server.ask("q")
    assert out["answer"].startswith("Hello world")


def test_ask_extracts_cited_sources_and_cost(monkeypatch):
    events = [
        {"type": "delta", "content": "See "},
        {"type": "delta", "content": "[Doc](wiki/concept/x.md)."},
        {"type": "done",
         "cited_sources": [{"title": "Doc", "path": "wiki/concept/x.md"}],
         "retrieved_sources": [{"title": "Doc", "path": "wiki/concept/x.md"},
                               {"title": "Other", "path": "wiki/concept/y.md"}],
         "cost_usd": 0.0123},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    out = mcp_server.ask("q")
    assert out["sources"] == [{"title": "Doc", "path": "wiki/concept/x.md"}]
    assert out["cost_usd"] == 0.0123


def test_ask_appends_sources_footer(monkeypatch):
    events = [
        {"type": "delta", "content": "Answer body."},
        {"type": "done",
         "cited_sources": [{"title": "Doc", "path": "wiki/concept/x.md"}],
         "cost_usd": 0.0},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    out = mcp_server.ask("q")
    assert "Answer body." in out["answer"]
    assert "Sources:" in out["answer"]
    assert "[Doc](wiki/concept/x.md)" in out["answer"]


# ── Fallbacks and edge cases ─────────────────────────────────────────

def test_ask_falls_back_to_retrieved_sources(monkeypatch):
    """No cited_sources but retrieved_sources present → use retrieved."""
    events = [
        {"type": "delta", "content": "Answer."},
        {"type": "done",
         "cited_sources": [],
         "retrieved_sources": [{"title": "R", "path": "wiki/concept/r.md"}],
         "cost_usd": 0.0},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    out = mcp_server.ask("q")
    assert out["sources"] == [{"title": "R", "path": "wiki/concept/r.md"}]


def test_ask_empty_sources_no_footer(monkeypatch):
    events = [
        {"type": "delta", "content": "Answer with no sources."},
        {"type": "done", "cited_sources": [], "retrieved_sources": [], "cost_usd": 0.0},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    out = mcp_server.ask("q")
    assert out["sources"] == []
    assert "Sources:" not in out["answer"]
    assert out["answer"] == "Answer with no sources."


def test_ask_raises_on_error_event(monkeypatch):
    events = [
        {"type": "delta", "content": "partial"},
        {"type": "error", "error": "LLM exploded"},
    ]
    monkeypatch.setattr(mcp_server, "run_server_chat_http", _fake_core(events))
    with pytest.raises(RuntimeError, match="LLM exploded"):
        mcp_server.ask("q")


def test_ask_propagates_core_exception(monkeypatch):
    """Real chat core raises on API failure rather than emitting `error`."""
    def boom(input_data, emit_fn):
        raise RuntimeError("api 500")
    monkeypatch.setattr(mcp_server, "run_server_chat_http", boom)
    with pytest.raises(RuntimeError, match="api 500"):
        mcp_server.ask("q")


# ── Input passthrough ────────────────────────────────────────────────

def test_ask_passes_paths_and_model_through(monkeypatch):
    fake = _fake_core([{"type": "done", "cited_sources": [], "cost_usd": 0.0}])
    monkeypatch.setattr(mcp_server, "run_server_chat_http", fake)
    mcp_server.ask("my query", paths=["wiki/a.md", "wiki/b.md"], model="claude-opus-4-8")
    inp = fake.seen_input
    assert inp["query"] == "my query"
    assert inp["paths"] == ["wiki/a.md", "wiki/b.md"]
    assert inp["model"] == "claude-opus-4-8"
    assert inp["include_sources"] is True


def test_ask_omits_optional_fields_when_absent(monkeypatch):
    fake = _fake_core([{"type": "done", "cited_sources": [], "cost_usd": 0.0}])
    monkeypatch.setattr(mcp_server, "run_server_chat_http", fake)
    mcp_server.ask("just a query")
    inp = fake.seen_input
    assert "paths" not in inp
    assert "model" not in inp
    assert inp["query"] == "just a query"


# ── kb_dir resolution ────────────────────────────────────────────────

def test_kb_dir_defaults_to_data(monkeypatch):
    monkeypatch.delenv("KAAS_KB_DIR", raising=False)
    assert mcp_server._kb_dir() == "./data"


def test_kb_dir_reads_env(monkeypatch):
    monkeypatch.setenv("KAAS_KB_DIR", "/srv/knowledge")
    assert mcp_server._kb_dir() == "/srv/knowledge"


def test_ask_uses_kb_dir(monkeypatch):
    monkeypatch.setenv("KAAS_KB_DIR", "/srv/kb")
    fake = _fake_core([{"type": "done", "cited_sources": [], "cost_usd": 0.0}])
    monkeypatch.setattr(mcp_server, "run_server_chat_http", fake)
    mcp_server.ask("q")
    assert fake.seen_input["kb_dir"] == "/srv/kb"


# ── Bearer token check (pure predicate) ──────────────────────────────

def test_bearer_ok_when_no_token_configured():
    assert mcp_server._bearer_ok(None, "") is True
    assert mcp_server._bearer_ok("anything", "") is True


def test_bearer_requires_matching_token():
    assert mcp_server._bearer_ok("Bearer secret", "secret") is True
    assert mcp_server._bearer_ok("Bearer wrong", "secret") is False
    assert mcp_server._bearer_ok(None, "secret") is False
    assert mcp_server._bearer_ok("secret", "secret") is False  # missing "Bearer " prefix


# ── Bearer gate (pure-ASGI middleware) ───────────────────────────────
#
# Driven directly at the ASGI layer (no TestClient/httpx) so the test proves
# the gate is pure-ASGI: it must stream the inner app's chunked body through
# untouched (the reason for not using BaseHTTPMiddleware, which buffers
# streaming bodies), and short-circuit unauthorized requests with a 401.

async def _inner_stream(scope, receive, send):
    """Minimal streaming ASGI app emitting two body chunks (SSE stand-in)."""
    assert scope["type"] == "http"
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/event-stream")]})
    await send({"type": "http.response.body", "body": b"chunk1 ", "more_body": True})
    await send({"type": "http.response.body", "body": b"chunk2", "more_body": False})


def _drive(token, auth_header):
    """Send one HTTP request through _BearerGate(inner) and collect the
    response status + concatenated body."""
    gate = mcp_server._BearerGate(_inner_stream, token)
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode("latin-1")))
    scope = {"type": "http", "method": "GET", "path": "/mcp", "headers": headers}
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(gate(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def test_gate_passes_streaming_response_with_valid_token():
    status, body = _drive("secret", "Bearer secret")
    assert status == 200
    assert body == b"chunk1 chunk2"  # both chunks streamed through untouched


def test_gate_rejects_bad_token():
    status, _ = _drive("secret", "Bearer wrong")
    assert status == 401


def test_gate_rejects_missing_token():
    status, _ = _drive("secret", None)
    assert status == 401


def test_gate_disabled_when_no_token():
    status, body = _drive("", None)  # empty token = auth off
    assert status == 200
    assert body == b"chunk1 chunk2"


# ── __main__ command dispatch ────────────────────────────────────────

def test_main_dispatches_mcp_command(monkeypatch):
    """`kb-ai mcp --stdio` routes to run_server_mcp with the post-command args."""
    seen = {}

    def fake_run(argv=None):
        seen["argv"] = argv

    monkeypatch.setattr("kb_ai.server_mcp.run_server_mcp", fake_run)
    monkeypatch.setattr(sys, "argv", ["kb-ai", "mcp", "--stdio"])
    from kb_ai.__main__ import main
    main()
    assert seen["argv"] == ["--stdio"]


def test_main_mcp_does_not_emit_json_respond(monkeypatch, capsys):
    """The mcp branch must keep stdout clean (no {"ok":...} wrapper) so it
    doesn't corrupt the MCP stdio protocol stream."""
    monkeypatch.setattr("kb_ai.server_mcp.run_server_mcp", lambda argv=None: None)
    monkeypatch.setattr(sys, "argv", ["kb-ai", "mcp"])
    from kb_ai.__main__ import main
    main()
    out = capsys.readouterr().out
    assert '"ok"' not in out
    assert out == ""


# ── Tool registration (offline, no subprocess) ───────────────────────

def test_ask_tool_registered_with_schema():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {t.name: t for t in tools}
    assert "ask" in by_name
    ask_tool = by_name["ask"]
    props = ask_tool.inputSchema.get("properties", {})
    assert set(props) == {"query", "paths", "model"}
    assert ask_tool.inputSchema.get("required") == ["query"]


# ── stdio end-to-end smoke (spawns a subprocess) ─────────────────────

@pytest.mark.slow
def test_stdio_initialize_and_list_tools():
    """Spawn `kb-ai mcp` over stdio and drive the real MCP handshake.

    Exercises the transport + entry-point wiring (initialize → tools/list)
    without calling the tool, so no LLM/network is needed.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def drive():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "kb_ai", "mcp"],
            env={**os.environ, "KAAS_KB_DIR": "./data"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

    result = asyncio.run(drive())
    names = {t.name for t in result.tools}
    assert "ask" in names
