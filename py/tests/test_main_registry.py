"""Tests for __main__.py command registry and error handling.

Verifies that:
- The command registry contains all expected commands
- Unknown commands produce proper error output
- The MCP special case is handled
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from kb_ai.__main__ import COMMANDS, main


# ── Command registry tests ────────────────────────────────────────────


EXPECTED_COMMANDS = ["compile", "fetch-url", "chat", "rewrite"]


@pytest.mark.parametrize("cmd", EXPECTED_COMMANDS)
def test_registry_contains_expected_command(cmd):
    """Each expected command is present in the COMMANDS registry."""
    assert cmd in COMMANDS


def test_registry_lazy_loaders_are_callable():
    """Each registry entry is a callable that returns a function."""
    for name, loader in COMMANDS.items():
        assert callable(loader), f"COMMANDS[{name!r}] is not callable"


def test_registry_compile_resolves():
    """The 'compile' command loader resolves to a callable function."""
    fn = COMMANDS["compile"]()
    assert callable(fn)


def test_registry_check_resolves():
    """The read-only F3/F5 entry point is reachable as `kb-ai check`."""
    assert "check" in COMMANDS
    assert callable(COMMANDS["check"]())


def test_registry_fetch_url_resolves():
    """The 'fetch-url' command loader resolves to a callable function."""
    fn = COMMANDS["fetch-url"]()
    assert callable(fn)


def test_registry_chat_resolves():
    """The 'chat' command loader resolves to a callable function."""
    fn = COMMANDS["chat"]()
    assert callable(fn)


def test_registry_rewrite_resolves():
    """The 'rewrite' command loader resolves to a callable function."""
    fn = COMMANDS["rewrite"]()
    assert callable(fn)


# ── Unknown command error handling ────────────────────────────────────


def test_unknown_command_produces_error_response(capsys):
    """An unknown command outputs a JSON error with code UNKNOWN_COMMAND."""
    with patch.object(sys, "argv", ["kb-ai", "nonexistent-cmd"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        # main() calls sys.exit(0) after respond_error
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["ok"] is False
    assert output["error"]["code"] == "UNKNOWN_COMMAND"
    assert "nonexistent-cmd" in output["error"]["message"]


def test_no_command_produces_error_response(capsys):
    """No command argument outputs a JSON error with code NO_COMMAND."""
    with patch.object(sys, "argv", ["kb-ai"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["ok"] is False
    assert output["error"]["code"] == "NO_COMMAND"


# ── MCP special case ─────────────────────────────────────────────────


def test_mcp_command_not_in_lazy_registry():
    """MCP is handled as a special case in main(), not via the COMMANDS registry."""
    # MCP is NOT in COMMANDS because it owns stdin/stdout
    assert "mcp" not in COMMANDS


def test_mcp_command_recognized(monkeypatch):
    """The 'mcp' command is recognized and dispatched (not treated as unknown)."""
    # We just verify it doesn't produce UNKNOWN_COMMAND error.
    # We mock run_server_mcp to avoid actually starting the MCP server.
    called = []

    def fake_mcp(args):
        called.append(args)

    monkeypatch.setattr(sys, "argv", ["kb-ai", "mcp"])

    with patch("kb_ai.server_mcp.run_server_mcp", side_effect=fake_mcp):
        main()

    assert called == [[]]


def test_derive_command_is_registered():
    from kb_ai.__main__ import COMMANDS

    assert "derive" in COMMANDS
    assert callable(COMMANDS["derive"]())
