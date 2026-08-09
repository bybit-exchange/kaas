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
        infra._client = OpenAI(base_url=base_url, api_key=api_key,
                               timeout=infra.DEFAULT_CLIENT_TIMEOUT_S, max_retries=0)

    if model:
        os.environ["LLM_MODEL"] = model

    summarize_model = llm_cfg.get("summarize_model", "")
    if summarize_model:
        os.environ["LLM_SUMMARIZE_MODEL"] = summarize_model

    # The extraction strategy is a per-deployment contract, not a per-request
    # choice: the derive handler compiles a copied extraction layer and has to
    # compare against the same value the copies were produced under.
    extract_strategy = llm_cfg.get("extract_strategy", "")
    if extract_strategy:
        os.environ["LLM_EXTRACT_STRATEGY"] = extract_strategy

    _respond_ok(request_id, {"initialized": True})


def _handle_shutdown(request_id: str, executor: ThreadPoolExecutor) -> None:
    """Handle the shutdown command — respond ok then signal exit."""
    _respond_ok(request_id, {"shutdown": True})


def _normalise_newlines(content: str) -> str:
    """Make the daemon see the text the CLI would have seen.

    The CLI hashes and chunks path.read_text() output, which is universal-newline
    translated; the Go worker sends the file bytes with CRLF intact. Without this
    the two routes diverge twice over for any CRLF document: the daemon's
    source_checksum differs from the CLI's, so the extraction is reported
    permanently stale and derive permanently skips copying it, and the model is
    prompted with different bytes. Normalising once on receipt fixes both;
    normalising inside _compute_checksum would fix only the first.
    """
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _handle_extract(request_id: str, payload: dict) -> None:
    """Handle the extract command — extract knowledge and persist it.

    The engine writes the extraction file rather than the Go side: one markdown
    serializer, so the two ingestion routes agree by construction instead of by
    two implementations reproducing PyYAML's escaping decisions.
    """
    from kb_ai.core.extract import (
        extraction_to_dict,
        plan_extraction,
        run_planned_extraction,
    )
    from kb_ai.llm import CostTracker, set_phase_context, set_request_tracker
    from kb_ai.prompts import PromptError
    from kb_ai.storage import extraction as extraction_layer
    from kb_ai.storage.store import KBStore, _compute_checksum

    inner = payload.get("payload", {})
    content = _normalise_newlines(inner.get("content", ""))
    kb_dir = inner.get("kb_dir", "")
    source = inner.get("source", "")
    model = inner.get("model") or "claude-sonnet-4-6"
    strategy = inner.get("strategy", "chunked")
    summarize_model = inner.get("summarize_model") or os.environ.get("LLM_SUMMARIZE_MODEL") or os.environ.get("LLM_MODEL", "")

    if not content:
        _respond_error(request_id, "EMPTY_CONTENT", "content must not be empty")
        return
    if not kb_dir.strip():
        _respond_error(request_id, "EMPTY_KB_DIR", "kb_dir must not be empty")
        return
    if not source.strip():
        _respond_error(request_id, "EMPTY_SOURCE", "source must not be empty")
        return

    store = KBStore(kb_dir)
    checksum = _compute_checksum(content)
    try:
        prompt_version = extraction_layer.current_prompt_version()
    except PromptError as e:
        _respond_error(request_id, "PROMPT_UNAVAILABLE",
                       f"cannot compute prompt_version: {e}")
        return

    print(f"[daemon:extract] strategy={strategy} model={model} summarize_model={summarize_model}",
          file=sys.stderr, flush=True)

    # Route first, so the recorded strategy is the one that ran rather than the
    # one requested -- "auto" would make the field useless. Chunking costs no LLM
    # call, so resolving it up front also lets the freshness check below compare
    # the strategy the request would actually produce.
    #
    # Through the shared router, not a second copy of it: the CLI's gate compares
    # against the same function, so the two routes cannot disagree about what a
    # given configuration produces.
    try:
        plan = plan_extraction(content, strategy)
    except ValueError as e:
        _respond_error(request_id, "INVALID_STRATEGY", str(e))
        return
    resolved = plan.strategy
    print(f"[daemon:extract] routed={resolved} (requested={strategy}, "
          f"chunks={len(plan.chunks) if plan.chunks else 'n/a'})",
          file=sys.stderr, flush=True)

    # Read before calling the model: a pipeline failure with an attempt left
    # replays the whole task, so without this every retry pays for extraction a
    # second time. This is not re-extracting -- it is declining to.
    stored, _reason = extraction_layer.load(store, source)
    if stored is not None and not extraction_layer.staleness(
            stored.provenance, source_checksum=checksum, extract_model=model,
            extract_strategy=resolved, prompt_version=prompt_version,
            summarize_model=summarize_model):
        print(f"[daemon:extract] reusing {store.extraction_rel_path(source)}",
              file=sys.stderr, flush=True)
        _respond_ok(request_id, {
            "extraction": extraction_to_dict(stored.extraction),
            "cost": CostTracker().summary_with_details(),
            "reused": True,
        })
        return

    set_phase_context("extract")
    req_tracker = CostTracker()
    set_request_tracker(req_tracker)
    try:
        result = run_planned_extraction(plan, content, extract_model=model,
                                        summarize_model=summarize_model)
    finally:
        set_request_tracker(None)

    # A write failure fails the task: there is no "extracted but not persisted"
    # state, because the pipeline reads the extraction back off disk. Not retried
    # -- the atomic write already covers a torn file, and ENOSPC / EACCES / EROFS
    # do not clear in milliseconds.
    try:
        extraction_layer.persist(
            store, source, result,
            source_checksum=checksum,
            extract_model=model,
            extract_strategy=resolved,
            summarize_model=summarize_model,
        )
    except (OSError, ValueError, PermissionError) as e:
        _respond_error(request_id, "EXTRACTION_NOT_PERSISTED",
                       f"persist extraction for {source!r}: {e}")
        return

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
            # The deployment's strategy, put in the environment by the init
            # command. The derived compile must compare against the value the
            # copied extractions were produced under, or it re-extracts every one
            # of them and records a strategy the parent then finds stale in turn.
            extract_strategy=(inner.get("extract_strategy")
                              or os.environ.get("LLM_EXTRACT_STRATEGY")
                              or "chunked"),
            summarize_model=(inner.get("summarize_model")
                             or os.environ.get("LLM_SUMMARIZE_MODEL")
                             or os.environ.get("LLM_MODEL", "")),
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
