"""Offline tests for the MCP server's transport wiring and CLI parsing.

Complements tests/test_server_mcp.py (which covers the `ask` collector and the
bearer gate) by driving `run_server_mcp` / `_run_http`. Both transports are
stubbed — FastMCP's own `run` is monkeypatched and a fake `uvicorn` module is
injected — so nothing binds a port or reads stdio.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

import kb_ai.server_mcp as mcp_server


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def transport(monkeypatch):
    """Stub every way the module can start a server.

    Returns a control/record surface: `runs` logs FastMCP transports started,
    `uvicorn_calls` logs fake-uvicorn invocations, `http_calls` logs _run_http
    arguments (only when `patch_run_http` is asked for). mcp.settings host/port
    are restored afterwards because _run_http mutates the shared instance.
    """
    settings = mcp_server.mcp.settings
    saved = (settings.host, settings.port)
    rec = SimpleNamespace(runs=[], uvicorn_calls=[], http_calls=[], app=object())

    monkeypatch.setattr(mcp_server.mcp, "run",
                        lambda transport=None: rec.runs.append(transport))
    monkeypatch.setattr(mcp_server.mcp, "streamable_http_app", lambda: rec.app)

    def fake_uvicorn_run(app, host=None, port=None, log_level=None):
        rec.uvicorn_calls.append({"app": app, "host": host, "port": port,
                                  "log_level": log_level})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_uvicorn_run))
    # KAAS_KB_DIR / KAAS_MCP_TOKEN are written directly by the module under
    # test; setenv here registers them for restoration on teardown.
    monkeypatch.setenv("KAAS_KB_DIR", "./sentinel-kb")
    monkeypatch.delenv("KAAS_MCP_TOKEN", raising=False)
    yield rec
    settings.host, settings.port = saved


# ── kb_dir override ─────────────────────────────────────────────────

def test_kb_dir_override_beats_the_env_var(monkeypatch):
    monkeypatch.setenv("KAAS_KB_DIR", "/from/env")
    assert mcp_server._kb_dir("/from/flag") == "/from/flag"


def test_kb_dir_ignores_an_empty_override(monkeypatch):
    monkeypatch.setenv("KAAS_KB_DIR", "/from/env")
    assert mcp_server._kb_dir("") == "/from/env"


# ── _run_http ───────────────────────────────────────────────────────

def test_run_http_without_a_token_uses_fastmcp_runner(transport):
    mcp_server._run_http("0.0.0.0", 9001, "")

    assert transport.runs == ["streamable-http"]
    assert transport.uvicorn_calls == [], "no bearer gate, so no uvicorn wrapper"
    assert mcp_server.mcp.settings.host == "0.0.0.0"
    assert mcp_server.mcp.settings.port == 9001


def test_run_http_with_a_token_serves_the_gated_app(transport):
    mcp_server._run_http("127.0.0.1", 9002, "s3cret")

    assert transport.runs == [], "FastMCP's own runner would bypass the gate"
    assert len(transport.uvicorn_calls) == 1
    call = transport.uvicorn_calls[0]
    assert isinstance(call["app"], mcp_server._BearerGate)
    assert call["app"].app is transport.app
    assert call["app"].token == "s3cret"
    assert (call["host"], call["port"]) == ("127.0.0.1", 9002)
    assert call["log_level"] == mcp_server.mcp.settings.log_level.lower()


# ── run_server_mcp argument handling ────────────────────────────────

def test_run_server_mcp_defaults_to_stdio(transport):
    mcp_server.run_server_mcp([])

    assert transport.runs == ["stdio"]
    assert transport.uvicorn_calls == []


def test_run_server_mcp_stdio_flag(transport):
    mcp_server.run_server_mcp(["--stdio"])

    assert transport.runs == ["stdio"]


def test_run_server_mcp_http_uses_host_and_port_defaults(transport, monkeypatch):
    monkeypatch.setattr(mcp_server, "_run_http",
                        lambda host, port, token: transport.http_calls.append(
                            (host, port, token)))

    mcp_server.run_server_mcp(["--http"])

    assert transport.http_calls == [("127.0.0.1", 8082, "")]


def test_run_server_mcp_http_honours_host_port_and_token(transport, monkeypatch):
    monkeypatch.setattr(mcp_server, "_run_http",
                        lambda host, port, token: transport.http_calls.append(
                            (host, port, token)))
    monkeypatch.setenv("KAAS_MCP_TOKEN", "from-env")

    mcp_server.run_server_mcp(["--http", "--host", "0.0.0.0", "--port", "9999"])

    assert transport.http_calls == [("0.0.0.0", 9999, "from-env")]


def test_run_server_mcp_kb_dir_flag_sets_the_env_var(transport):
    mcp_server.run_server_mcp(["--stdio", "--kb-dir", "/srv/other-kb"])

    assert os.environ["KAAS_KB_DIR"] == "/srv/other-kb"
    assert mcp_server._kb_dir() == "/srv/other-kb"
    assert transport.runs == ["stdio"]


def test_run_server_mcp_leaves_kb_dir_env_alone_without_the_flag(transport):
    mcp_server.run_server_mcp(["--stdio"])

    assert mcp_server._kb_dir() == "./sentinel-kb"


def test_run_server_mcp_rejects_both_transports(transport):
    with pytest.raises(SystemExit):
        mcp_server.run_server_mcp(["--stdio", "--http"])

    assert transport.runs == []


def test_run_server_mcp_rejects_a_non_numeric_port(transport):
    with pytest.raises(SystemExit):
        mcp_server.run_server_mcp(["--http", "--port", "not-a-port"])

    assert transport.runs == []
