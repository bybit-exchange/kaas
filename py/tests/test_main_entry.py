"""Offline tests for the CLI entry point (kb_ai.__main__).

test_main_registry.py already covers the registry contents and the argv guards;
what is left here is the lazy loaders that need argv wiring (`distill`,
`daemon`), the dispatch/error boundary of main(), and the `__main__` guard that
makes `python -m kb_ai` work.
"""
from __future__ import annotations

import json
import runpy
import sys

import pytest

from kb_ai.__main__ import COMMANDS, main, respond


# ── legacy respond helper ───────────────────────────────────────────

def test_respond_omits_absent_data_and_error(capsys):
    respond(True)

    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_respond_writes_data_and_error_and_keeps_non_ascii(capsys):
    respond(False, data={"title": "世界"}, error={"code": "BAD"})

    out = capsys.readouterr().out
    assert json.loads(out) == {"ok": False, "data": {"title": "世界"},
                               "error": {"code": "BAD"}}
    assert "世界" in out


# ── lazy loaders needing argv wiring ────────────────────────────────

def test_distill_loader_forwards_the_argv_tail(monkeypatch):
    """`kb-ai distill a b --kb x` must reach run_distill as argv[2:]."""
    import kb_ai.distill as distill

    seen: list[list[str]] = []
    monkeypatch.setattr(distill, "run_distill", lambda argv: seen.append(argv))
    monkeypatch.setattr(sys, "argv", ["kb-ai", "distill", "notes.md", "--kb", "/tmp/kb"])

    COMMANDS["distill"]()()

    assert seen == [["notes.md", "--kb", "/tmp/kb"]]


def test_daemon_loader_resolves_to_the_daemon_main():
    from kb_ai.server_daemon import main as daemon_main

    assert COMMANDS["daemon"]() is daemon_main


# ── main() dispatch ─────────────────────────────────────────────────

def test_main_resolves_the_loader_and_runs_the_command(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setitem(COMMANDS, "chat", lambda: lambda: calls.append("ran"))
    monkeypatch.setattr(sys, "argv", ["kb-ai", "chat"])

    main()

    assert calls == ["ran"]
    # A successful command owns its own stdout; main() adds nothing.
    assert capsys.readouterr().out == ""


def test_main_turns_a_command_failure_into_an_error_response(monkeypatch, capsys):
    def boom():
        raise RuntimeError("chat exploded")

    monkeypatch.setitem(COMMANDS, "chat", lambda: boom)
    monkeypatch.setattr(sys, "argv", ["kb-ai", "chat"])

    main()   # must not raise: the Go bridge needs a JSON line, not a traceback

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "ok": False,
        "error": {"code": "INTERNAL_ERROR", "message": "chat exploded"},
    }
    assert "RuntimeError: chat exploded" in captured.err


def test_main_turns_a_loader_import_failure_into_an_error_response(monkeypatch, capsys):
    def bad_loader():
        raise ImportError("no module named trafilatura")

    monkeypatch.setitem(COMMANDS, "fetch-url", bad_loader)
    monkeypatch.setattr(sys, "argv", ["kb-ai", "fetch-url"])

    main()

    resp = json.loads(capsys.readouterr().out)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INTERNAL_ERROR"
    assert "trafilatura" in resp["error"]["message"]


# ── python -m kb_ai ─────────────────────────────────────────────────

@pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
def test_module_runs_main_through_the_script_guard(monkeypatch, capsys):
    """`python -m kb_ai` must reach main() rather than just importing it.

    runpy re-executes the module body; the RuntimeWarning about it already being
    in sys.modules is expected and harmless here.
    """
    monkeypatch.setattr(sys, "argv", ["kb-ai"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("kb_ai.__main__", run_name="__main__")

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "NO_COMMAND"
