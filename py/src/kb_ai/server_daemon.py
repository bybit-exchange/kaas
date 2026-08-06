"""Long-running server daemon with stdin readline loop protocol.

Keeps OpenAI client and future resources loaded in memory, serving requests via
a JSON-line protocol on stdin/stdout. The Go/TS backend spawns this process once
and reuses it for the lifetime of the application.

Protocol:
  - Input (one JSON object per line on stdin):
    {"id": "1", "cmd": "ping"}
    {"id": "2", "cmd": "init", "payload": {"llm": {"api_key": "...", "base_url": "...", "model": "..."}}}
    {"id": "3", "cmd": "shutdown"}
  - Output (one JSON object per line on stdout):
    {"id": "1", "ok": true, "data": {"uptime_sec": 0.01}}
    {"id": "1", "ok": false, "error": {"code": "UNKNOWN_CMD", "message": "..."}}
  - Streaming output:
    {"id": "3", "stream": true, "event": {...}}
    {"id": "3", "stream": true, "event": {...}, "final": true}

Startup:
  1. Print "__READY__" to stderr
  2. Enter readline loop (dispatches to ThreadPoolExecutor)
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Thread-safe output layer
# ---------------------------------------------------------------------------

_stdout_lock = threading.Lock()


def _write_response(response: dict) -> None:
    """Write a JSON response line to stdout atomically (thread-safe)."""
    line = json.dumps(response, ensure_ascii=False)
    with _stdout_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _respond_ok(request_id: str, data: dict) -> None:
    """Write a success JSON response to stdout."""
    _write_response({"id": request_id, "ok": True, "data": data})


def _respond_error(request_id: str, code: str, message: str) -> None:
    """Write an error JSON response to stdout."""
    _write_response({"id": request_id, "ok": False, "error": {"code": code, "message": message}})


def _respond_stream_event(request_id: str, event: dict, final: bool = False) -> None:
    """Write a streaming event JSON response to stdout."""
    resp: dict = {"id": request_id, "stream": True, "event": event}
    if final:
        resp["final"] = True
    _write_response(resp)


# ---------------------------------------------------------------------------
# Streaming commands and cancel support
# ---------------------------------------------------------------------------

STREAMING_COMMANDS = {"chat", "pipeline-stream"}


class CancelledError(Exception):
    """Raised when a streaming command is cancelled via cancel_event."""
    pass


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_ping(request_id: str, start_time: float) -> None:
    """Handle the ping command — returns uptime."""
    uptime = time.time() - start_time
    _respond_ok(request_id, {"uptime_sec": round(uptime, 2)})


def _handle_init(request_id: str, payload: dict) -> None:
    """Handle the init command — initialize OpenAI client."""
    import kb_ai.llm._infra as infra
    from kb_ai.llm._infra import _client_lock

    inner = payload.get("payload", {})
    llm_cfg = inner.get("llm", {})
    api_key = llm_cfg.get("api_key", "")
    base_url = llm_cfg.get("base_url", "") or infra._DEFAULT_BASE_URL
    model = llm_cfg.get("model", "")

    from openai import OpenAI

    with _client_lock:
        infra._client = OpenAI(base_url=base_url, api_key=api_key, timeout=900.0, max_retries=0)

    if model:
        os.environ["LLM_MODEL"] = model

    summarize_model = llm_cfg.get("summarize_model", "")
    if summarize_model:
        os.environ["LLM_SUMMARIZE_MODEL"] = summarize_model

    _respond_ok(request_id, {"initialized": True})


def _handle_shutdown(request_id: str, executor: ThreadPoolExecutor) -> None:
    """Handle the shutdown command — respond ok then signal exit."""
    _respond_ok(request_id, {"shutdown": True})


def _handle_extract(request_id: str, payload: dict) -> None:
    """Handle the extract command — extract knowledge from content."""
    from kb_ai.core.extract import (
        _is_transcript,
        _parse_frontmatter,
        chunk_content,
        chunk_transcript,
        extract_knowledge_chunked,
        extract_knowledge_summarized,
        extraction_to_dict,
    )
    from kb_ai.llm import CostTracker, set_phase_context, set_request_tracker

    inner = payload.get("payload", {})
    content = inner.get("content", "")
    model = inner.get("model", "claude-sonnet-4-6")
    strategy = inner.get("strategy", "chunked")
    summarize_model = inner.get("summarize_model") or os.environ.get("LLM_SUMMARIZE_MODEL") or os.environ.get("LLM_MODEL", "")

    if not content:
        _respond_error(request_id, "EMPTY_CONTENT", "content must not be empty")
        return

    print(f"[daemon:extract] strategy={strategy} model={model} summarize_model={summarize_model}",
          file=sys.stderr, flush=True)

    set_phase_context("extract")
    req_tracker = CostTracker()
    set_request_tracker(req_tracker)
    try:
        if strategy == "summarize":
            meta, body = _parse_frontmatter(content)
            chunks = chunk_transcript(body, meta) if _is_transcript(meta) else chunk_content(content)
            print(f"[daemon:extract] routed=summarize chunks={len(chunks)}", file=sys.stderr, flush=True)
            result = extract_knowledge_summarized(chunks, meta, summarize_model, model)
        elif strategy == "auto":
            meta, body = _parse_frontmatter(content)
            chunks = chunk_transcript(body, meta) if _is_transcript(meta) else chunk_content(content)
            if len(chunks) >= 3:
                print(f"[daemon:extract] routed=summarize (auto, chunks={len(chunks)}>=3)", file=sys.stderr, flush=True)
                result = extract_knowledge_summarized(chunks, meta, summarize_model, model)
            else:
                print(f"[daemon:extract] routed=chunked (auto, chunks={len(chunks)}<3)", file=sys.stderr, flush=True)
                result = extract_knowledge_chunked(content, model=model)
        else:
            print(f"[daemon:extract] routed=chunked", file=sys.stderr, flush=True)
            result = extract_knowledge_chunked(content, model=model)
    finally:
        set_request_tracker(None)

    cost = req_tracker.summary_with_details()
    _respond_ok(request_id, {"extraction": extraction_to_dict(result), "cost": cost})


def _handle_pipeline(request_id: str, payload: dict) -> None:
    """Handle the pipeline command — run extraction pipeline."""
    from kb_ai.commands.pipeline import run_server_pipeline_with_input
    from kb_ai.llm import CostTracker, set_request_tracker

    inner = payload.get("payload", {})
    req_tracker = CostTracker()
    set_request_tracker(req_tracker)
    try:
        result = run_server_pipeline_with_input(inner)
    finally:
        set_request_tracker(None)
    cost = req_tracker.summary_with_details()
    _respond_ok(request_id, {"results": result, "cost": cost})


def _handle_rewrite(request_id: str, payload: dict) -> None:
    """Handle the rewrite command — rewrite a query for better retrieval."""
    from kb_ai.commands.rewrite import rewrite_query

    inner = payload.get("payload", {})
    query = inner.get("query", "")
    history = inner.get("history")
    model = inner.get("model", "claude-sonnet-4-6")

    if not query:
        _respond_error(request_id, "EMPTY_QUERY", "query must not be empty")
        return

    result = rewrite_query(query, history, model=model)
    _respond_ok(request_id, result)


def _handle_suggest(request_id: str, payload: dict) -> None:
    """Handle the suggest command — suggest follow-up questions."""
    from kb_ai.commands.suggest import suggest_questions

    inner = payload.get("payload", {})
    query = inner.get("query", "")
    answer = inner.get("answer", "")
    model = inner.get("model", "claude-haiku-4-5")

    if not query or not answer:
        _respond_error(request_id, "EMPTY_INPUT", "query and answer must not be empty")
        return

    result = suggest_questions(query, answer, model=model)
    _respond_ok(request_id, result)


def _handle_index(request_id: str, payload: dict) -> None:
    """Handle the index command — index documents into vector store."""
    from kb_ai.commands.pipeline import run_server_index_with_input

    inner = payload.get("payload", {})
    result = run_server_index_with_input(inner)
    _respond_ok(request_id, result)


def _handle_derive(request_id: str, payload: dict) -> None:
    """Handle the derive command -- build a topic-scoped knowledge base.

    No volume gate: this path is asynchronous, so there is nobody to prompt (spec
    H5). The HTTP layer's job row is the operator-facing control.
    """
    from kb_ai._errors import KBError
    from kb_ai.derive import derive_kb
    from kb_ai.llm import CostTracker, set_request_tracker

    inner = payload.get("payload", {})
    kb_dir = inner.get("kb_dir", "")
    topic = inner.get("topic", "")
    # An empty kb_dir resolves to the daemon's own working directory, and this is
    # the one handler that creates directories.
    if not kb_dir.strip():
        _respond_error(request_id, "EMPTY_KB_DIR", "kb_dir must not be empty")
        return
    if not topic.strip():
        _respond_error(request_id, "EMPTY_TOPIC", "topic must not be empty")
        return

    select_from = inner.get("select_from") or "articles"

    req_tracker = CostTracker()
    set_request_tracker(req_tracker)
    try:
        report = derive_kb(
            kb_dir, topic,
            slug=inner.get("slug") or None,
            force=bool(inner.get("force")),
            select_from=select_from,
            model=inner.get("model") or "claude-sonnet-4-6",
            approve=None,
        )
    except KBError as e:
        _respond_error(request_id, e.code, str(e))
        return
    finally:
        set_request_tracker(None)

    _respond_ok(request_id, {
        "derived_kb": report.derived_kb,
        "slug": report.slug,
        "topic": report.topic,
        "select_from": select_from,
        # Whichever unit the filter selected: selected_articles is empty by design
        # under select_from="documents", so reporting it would always say 0 there.
        "selected": len(report.selected_documents or report.selected_articles),
        "documents": len(report.documents),
        "bytes": sum(d.size_bytes for d in report.documents),
        "offtopic": len(report.offtopic_articles),
        "filter_batches": report.filter_batches,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
    })


def _handle_fetch_url(request_id: str, payload: dict) -> None:
    """Handle the fetch-url command — fetch and extract content from a URL."""
    from kb_ai.commands.fetch import fetch_url

    inner = payload.get("payload", {})
    url = inner.get("url", "")

    if not url:
        _respond_error(request_id, "EMPTY_URL", "url must not be empty")
        return

    try:
        result = fetch_url(url)
    except ValueError as e:
        _respond_error(request_id, "FETCH_FAILED", str(e))
        return

    _respond_ok(request_id, result)


# ---------------------------------------------------------------------------
# Cancel + streaming handlers
# ---------------------------------------------------------------------------

def _handle_cancel(payload: dict, request_id: str, cancel_registry: dict, cancel_lock: threading.Lock) -> None:
    """Handle the cancel command — set cancel_event for the target request."""
    target_id = payload.get("payload", {}).get("target_id", "")
    with cancel_lock:
        event = cancel_registry.get(target_id)
        if event:
            event.set()
    _respond_ok(request_id, {"cancelled": target_id})


def _dispatch_streaming(
    payload: dict,
    cmd: str,
    request_id: str,
    cancel_event: threading.Event,
    cancel_registry: dict,
    cancel_lock: threading.Lock,
) -> None:
    """Run a streaming command, handling cancel and errors."""
    try:
        if cmd == "chat":
            _handle_chat_stream(payload, request_id, cancel_event)
        elif cmd == "pipeline-stream":
            _handle_pipeline_stream(payload, request_id, cancel_event)
    except CancelledError:
        _respond_stream_event(request_id, {"type": "error", "code": "CANCELLED"}, final=True)
    except Exception as e:
        _respond_stream_event(request_id, {"type": "error", "code": "INTERNAL", "message": str(e)}, final=True)
    finally:
        with cancel_lock:
            cancel_registry.pop(request_id, None)


def _handle_chat_stream(payload: dict, request_id: str, cancel_event: threading.Event) -> None:
    """Handle the chat streaming command — calls run_server_chat_http with emit callback."""
    from kb_ai.commands.chat import run_server_chat_http

    inner = payload.get("payload", {})

    def emit(event: dict):
        if cancel_event.is_set():
            raise CancelledError()
        is_final = event.get("type") in ("done", "error")
        _respond_stream_event(request_id, event, final=is_final)

    run_server_chat_http(inner, emit)


def _handle_pipeline_stream(payload: dict, request_id: str, cancel_event: threading.Event) -> None:
    """Handle the pipeline-stream command — calls run_server_pipeline_with_input with streaming."""
    from kb_ai.commands.pipeline import run_server_pipeline_with_input
    from kb_ai.llm import CostTracker, PipelineCancelledError, set_request_tracker

    inner = payload.get("payload", {})
    req_tracker = CostTracker()
    set_request_tracker(req_tracker)

    def emit(event: dict):
        if cancel_event.is_set():
            raise CancelledError()
        is_final = event.get("type") in ("done", "error")
        _respond_stream_event(request_id, event, final=is_final)

    try:
        results = run_server_pipeline_with_input(inner, emit=emit, cancel_event=cancel_event)
        cost = req_tracker.summary_with_details()
        _respond_stream_event(request_id, {"type": "done", "results": results, "cost": cost}, final=True)
    except PipelineCancelledError:
        raise CancelledError()
    finally:
        set_request_tracker(None)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch(
    payload: dict,
    cmd: str,
    request_id: str,
    start_time: float,
    executor: ThreadPoolExecutor,
) -> bool:
    """Route a command to the appropriate handler.

    Returns True if the daemon should shut down after this command.
    """
    try:
        if cmd == "ping":
            _handle_ping(request_id, start_time)
        elif cmd == "init":
            _handle_init(request_id, payload)
        elif cmd == "shutdown":
            _handle_shutdown(request_id, executor)
            return True
        elif cmd == "extract":
            _handle_extract(request_id, payload)
        elif cmd == "pipeline":
            _handle_pipeline(request_id, payload)
        elif cmd == "rewrite":
            _handle_rewrite(request_id, payload)
        elif cmd == "suggest":
            _handle_suggest(request_id, payload)
        elif cmd == "index":
            _handle_index(request_id, payload)
        elif cmd == "derive":
            _handle_derive(request_id, payload)
        elif cmd == "fetch-url":
            _handle_fetch_url(request_id, payload)
        else:
            _respond_error(request_id, "UNKNOWN_CMD", f"unknown command: {cmd}")
    except Exception as e:
        _respond_error(request_id, "INTERNAL_ERROR", f"{type(e).__name__}: {e}")
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the kb-ai daemon command.

    Signals readiness, then processes JSON commands from stdin.
    Requests are dispatched to a ThreadPoolExecutor for concurrent processing.
    """
    # Signal readiness to the parent process
    print("__READY__", file=sys.stderr, flush=True)

    start_time = time.time()
    max_workers = int(os.environ.get("KAAS_DAEMON_MAX_WORKERS", "8"))
    executor = ThreadPoolExecutor(max_workers=max_workers)

    # Cancel registry: request_id -> threading.Event
    cancel_registry: dict[str, threading.Event] = {}
    cancel_lock = threading.Lock()

    # Main readline loop
    while True:
        line = sys.stdin.readline()
        if not line:
            # stdin closed — exit gracefully
            break

        line = line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as e:
            # No request_id available for malformed JSON — use empty string
            _respond_error("", "PARSE_ERROR", f"invalid JSON: {e}")
            continue

        cmd = payload.get("cmd")
        request_id = payload.get("id", "")

        if not cmd:
            _respond_error(request_id, "INVALID_CMD", "missing 'cmd' field")
            continue

        if not request_id:
            _respond_error(request_id, "INVALID_REQUEST", "missing 'id' field")
            continue

        # Shutdown is handled synchronously on the main thread
        if cmd == "shutdown":
            should_exit = _dispatch(payload, cmd, request_id, start_time, executor)
            if should_exit:
                break
            continue

        # Cancel is handled synchronously (fast, just sets an Event)
        if cmd == "cancel":
            _handle_cancel(payload, request_id, cancel_registry, cancel_lock)
            continue

        # Streaming commands get cancel support
        if cmd in STREAMING_COMMANDS:
            cancel_event = threading.Event()
            with cancel_lock:
                cancel_registry[request_id] = cancel_event
            executor.submit(_dispatch_streaming, payload, cmd, request_id, cancel_event, cancel_registry, cancel_lock)
            continue

        # All other commands are dispatched to the thread pool
        executor.submit(_dispatch, payload, cmd, request_id, start_time, executor)

    executor.shutdown(wait=True, cancel_futures=True)
