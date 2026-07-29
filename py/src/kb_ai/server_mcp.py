"""MCP server for the KaaS wiki — exposes a single `ask` tool.

Lets any Model Context Protocol client (Claude Code / Codex / openclaw) query
the compiled KaaS wiki as a knowledge source. `ask` reuses the existing chat
core (`run_server_chat_http`): it runs LLM-iterative retrieval over the
compiled markdown, then an LLM answer with inline `[Title](path)` citations.

The chat core is streaming (delta/done events); MCP `tools/call` is
request/response, so `ask` collects the stream into a complete answer before
returning. Two transports:
  - stdio (default): the client spawns `kb-ai mcp`; fully in-process.
  - streamable-http: `kb-ai mcp --http` (DEPRECATED — the Go backend now
    serves MCP natively at /mcp when [ai.mcp] enabled=true; this standalone
    HTTP mode will be removed in v2.0).

`run_server_chat_http` is imported at module level (not inside `ask`) so tests
can monkeypatch `kb_ai.server_mcp.run_server_chat_http` with a fake emitter.
"""
from __future__ import annotations

import argparse
import hmac
import os
import sys

from mcp.server.fastmcp import FastMCP

from kb_ai.commands.chat import run_server_chat_http

mcp = FastMCP("kaas")


def _kb_dir(override: str | None = None) -> str:
    """Resolve the knowledge-base root.

    Order: explicit override (--kb-dir) > KAAS_KB_DIR env > ./data. An MCP
    client spawns the stdio server from an arbitrary cwd, so the KB root is
    given explicitly rather than assumed relative to the process.
    """
    if override:
        return override
    return os.environ.get("KAAS_KB_DIR", "./data")


def _with_sources_footer(answer: str, sources: list[dict]) -> str:
    """Append a `Sources:` markdown list when sources are present.

    Clients that don't parse the structured `sources` output still see the
    citations inline at the end of the answer text.
    """
    if not sources:
        return answer
    lines = "\n".join(f"- [{s.get('title', '')}]({s.get('path', '')})" for s in sources)
    return f"{answer}\n\nSources:\n{lines}"


@mcp.tool()
def ask(query: str, paths: list[str] | None = None, model: str | None = None) -> dict:
    """Ask the compiled KaaS wiki a question; returns a cited answer.

    Args:
        query: Natural-language question.
        paths: Optional wiki article paths to ground the answer in (skips
            master-index navigation and reads those pages in full).
        model: Optional chat model override.

    Returns a dict: {answer (markdown, inline citations + Sources footer),
    sources [{title, path}], cost_usd}.
    """
    answer_parts: list[str] = []
    done: dict = {}

    def emit(ev: dict) -> None:
        kind = ev.get("type")
        if kind == "delta":
            answer_parts.append(ev.get("content", ""))
        elif kind == "done":
            done.update(ev)
        elif kind == "error":
            raise RuntimeError(ev.get("error") or "chat failed")
        # "status" and any unknown event types are ignored.

    input_data: dict = {"query": query, "kb_dir": _kb_dir(), "include_sources": True}
    if paths:
        input_data["paths"] = paths
    if model:
        input_data["model"] = model

    run_server_chat_http(input_data, emit)

    answer = "".join(answer_parts)
    sources = done.get("cited_sources") or done.get("retrieved_sources") or []
    return {
        "answer": _with_sources_footer(answer, sources),
        "sources": sources,
        "cost_usd": done.get("cost_usd", 0.0),
    }


def _bearer_ok(auth_header: str | None, expected_token: str) -> bool:
    """Validate an Authorization header against the configured bearer token.

    When no token is configured (empty), all requests pass (local/intranet
    assumption). Otherwise the header must be exactly `Bearer <token>`.
    """
    if not expected_token:
        return True
    if not auth_header:
        return False
    # Constant-time compare to avoid leaking the token via response timing.
    return hmac.compare_digest(auth_header, f"Bearer {expected_token}")


class _BearerGate:
    """Pure-ASGI middleware enforcing a bearer token on HTTP requests.

    Deliberately ASGI-level (not Starlette's BaseHTTPMiddleware): the MCP
    streamable-http transport returns long-lived SSE streams, and
    BaseHTTPMiddleware buffers/relays streaming bodies through a memory stream
    which can stall or truncate them. This gate inspects the request headers,
    short-circuits unauthorized HTTP requests with a 401, and otherwise hands
    the raw scope/receive/send to the wrapped app — so streamed responses pass
    through untouched. Non-HTTP scopes (lifespan) are always delegated.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            raw = headers.get(b"authorization")
            auth = raw.decode("latin-1") if raw else None
            if not _bearer_ok(auth, self.token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def _run_http(host: str, port: int, token: str) -> None:
    """Run the streamable-http transport, optionally behind a bearer gate.

    With no token, delegates to FastMCP's own runner. With a token, wraps the
    ASGI app in the pure-ASGI _BearerGate and serves it via uvicorn.
    """
    mcp.settings.host = host
    mcp.settings.port = port
    if not token:
        mcp.run(transport="streamable-http")
        return

    import uvicorn

    app = _BearerGate(mcp.streamable_http_app(), token)
    uvicorn.run(app, host=host, port=port, log_level=mcp.settings.log_level.lower())


def run_server_mcp(argv: list[str] | None = None) -> None:
    """Entry point for `kb-ai mcp`.

    --stdio (default): in-process stdio transport.
    --http --host --port: streamable-http transport (published via Go /mcp).
    --kb-dir: override KAAS_KB_DIR for this process.
    Bearer auth (HTTP only) is enabled when KAAS_MCP_TOKEN is set.
    """
    parser = argparse.ArgumentParser(prog="kb-ai mcp")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="stdio transport (default)")
    transport.add_argument("--http", action="store_true", help="streamable-http transport")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--kb-dir", default=None, help="override KAAS_KB_DIR")
    args = parser.parse_args(argv)

    if args.kb_dir:
        os.environ["KAAS_KB_DIR"] = args.kb_dir

    if args.http:
        _run_http(args.host, args.port, os.environ.get("KAAS_MCP_TOKEN", ""))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    run_server_mcp(sys.argv[1:])
