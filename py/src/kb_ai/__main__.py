import signal
import sys
import traceback

from kb_ai._protocol import respond_error, respond_ok

signal.signal(signal.SIGPIPE, signal.SIG_DFL)


# Legacy helper kept for backward-compat (some modules import `respond` from here).
def respond(ok: bool, data=None, error=None):
    """Write JSON response to stdout per bridge protocol."""
    import json
    resp = {"ok": ok}
    if data is not None:
        resp["data"] = data
    if error is not None:
        resp["error"] = error
    print(json.dumps(resp, ensure_ascii=False))


def _lazy_commands() -> dict:
    """Build command registry with lazy imports to avoid loading all modules at startup."""

    def compile_cmd():
        from kb_ai.commands.compile import run_compile
        return run_compile

    def fetch_url():
        from kb_ai.commands.fetch import run_fetch_url
        return run_fetch_url

    def chat():
        from kb_ai.commands.chat import run_server_chat
        return run_server_chat

    def rewrite():
        from kb_ai.commands.rewrite import run_server_rewrite
        return run_server_rewrite

    def distill():
        from kb_ai.distill import run_distill
        return lambda: run_distill(sys.argv[2:])

    def daemon():
        from kb_ai.server_daemon import main as daemon_main
        return daemon_main

    return {
        "compile": compile_cmd,
        "fetch-url": fetch_url,
        "chat": chat,
        "rewrite": rewrite,
        "distill": distill,
        "daemon": daemon,
    }


COMMANDS = _lazy_commands()


def main():
    if len(sys.argv) < 2:
        respond_error("NO_COMMAND", "usage: kb-ai <command>")
        sys.exit(0)

    command = sys.argv[1]

    # The MCP server owns stdin/stdout for the protocol stream (stdio transport),
    # so it must run OUTSIDE the respond() JSON wrapper below: a {"ok":...} line
    # on stdout would corrupt the stream. Exceptions propagate to stderr/exit code.
    if command == "mcp":
        from kb_ai.server_mcp import run_server_mcp
        run_server_mcp(sys.argv[2:])
        return

    if command not in COMMANDS:
        respond_error("UNKNOWN_COMMAND", f"unknown command: {command}")
        sys.exit(0)

    try:
        run_fn = COMMANDS[command]()
        run_fn()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        respond_error("INTERNAL_ERROR", str(e))


if __name__ == "__main__":
    main()
