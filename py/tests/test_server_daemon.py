"""Offline tests for the long-running daemon protocol (kb_ai.server_daemon).

This is the process the Go bridge spawns once and reuses, so the contract under
test is the JSON-line protocol: one response object per request, correct ids,
error codes for bad input, and cancel/streaming bookkeeping. Every handler's
real work is monkeypatched — the handlers import their dependencies lazily, so
patching the source module is what takes effect.
"""
from __future__ import annotations

import json
import threading
import time
from io import StringIO
from unittest.mock import patch

import pytest

from kb_ai import server_daemon as sd
from kb_ai.core.extract import ExtractionResult


# ── helpers ─────────────────────────────────────────────────────────

def responses(capsys) -> list[dict]:
    """Parse every JSON line the daemon wrote to stdout."""
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def one_response(capsys) -> dict:
    """Parse the single response the daemon wrote, failing if there is not exactly one."""
    got = responses(capsys)
    assert len(got) == 1, f"expected exactly 1 response, got {got}"
    return got[0]


def request(cmd: str, request_id: str = "1", **payload) -> dict:
    """Build a daemon request envelope."""
    return {"id": request_id, "cmd": cmd, "payload": payload}


# ── output layer ────────────────────────────────────────────────────

def test_respond_ok_shape(capsys):
    sd._respond_ok("42", {"value": 1})
    assert one_response(capsys) == {"id": "42", "ok": True, "data": {"value": 1}}


def test_respond_error_shape(capsys):
    sd._respond_error("42", "BAD", "went wrong")
    assert one_response(capsys) == {
        "id": "42",
        "ok": False,
        "error": {"code": "BAD", "message": "went wrong"},
    }


def test_respond_stream_event_non_final(capsys):
    sd._respond_stream_event("7", {"type": "delta"})
    resp = one_response(capsys)
    assert resp == {"id": "7", "stream": True, "event": {"type": "delta"}}
    assert "final" not in resp


def test_respond_stream_event_final(capsys):
    sd._respond_stream_event("7", {"type": "done"}, final=True)
    assert one_response(capsys)["final"] is True


def test_write_response_preserves_non_ascii(capsys):
    sd._respond_ok("1", {"title": "世界"})
    # ensure_ascii=False keeps CJK readable on the wire rather than escaping it.
    assert "世界" in capsys.readouterr().out


def test_write_response_emits_one_line_per_response(capsys):
    sd._respond_ok("1", {"a": 1})
    sd._respond_ok("2", {"b": 2})
    assert len(responses(capsys)) == 2


def test_write_response_is_thread_safe(capsys):
    """Concurrent writers must not interleave partial lines."""
    def writer(n: int):
        for i in range(20):
            sd._respond_ok(f"{n}-{i}", {"n": n})

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every line must be complete, parseable JSON.
    assert len(responses(capsys)) == 80


# ── ping ────────────────────────────────────────────────────────────

def test_handle_ping_reports_uptime(capsys):
    sd._handle_ping("1", time.time() - 5)

    resp = one_response(capsys)
    assert resp["ok"] is True
    assert resp["data"]["uptime_sec"] == pytest.approx(5, abs=1)


# ── init ────────────────────────────────────────────────────────────

def test_handle_init_builds_client_and_sets_models(capsys, monkeypatch):
    import kb_ai.llm._infra as infra
    import openai

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(infra, "_client", None, raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_SUMMARIZE_MODEL", raising=False)

    sd._handle_init("1", request("init", llm={
        "api_key": "sk-test",
        "base_url": "http://llm.local/v1",
        "model": "claude-sonnet-4-6",
        "summarize_model": "claude-haiku-4-5",
    }))

    assert one_response(capsys)["data"] == {"initialized": True}
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "http://llm.local/v1"
    # Retries are the Go side's job; the daemon must not silently retry.
    assert captured["max_retries"] == 0
    assert isinstance(infra._client, FakeOpenAI)

    import os
    assert os.environ["LLM_MODEL"] == "claude-sonnet-4-6"
    assert os.environ["LLM_SUMMARIZE_MODEL"] == "claude-haiku-4-5"


def test_handle_init_falls_back_to_default_base_url(capsys, monkeypatch):
    import kb_ai.llm._infra as infra
    import openai

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(infra, "_client", None, raising=False)

    sd._handle_init("1", request("init", llm={"api_key": "k", "base_url": ""}))

    assert captured["base_url"] == infra._DEFAULT_BASE_URL


def test_handle_init_leaves_model_env_alone_when_absent(capsys, monkeypatch):
    import kb_ai.llm._infra as infra
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(infra, "_client", None, raising=False)
    monkeypatch.setenv("LLM_MODEL", "preset-model")

    sd._handle_init("1", request("init", llm={"api_key": "k"}))

    import os
    assert os.environ["LLM_MODEL"] == "preset-model"


def test_handle_init_tolerates_missing_llm_block(capsys, monkeypatch):
    import kb_ai.llm._infra as infra
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(infra, "_client", None, raising=False)

    sd._handle_init("1", {"id": "1", "cmd": "init"})

    assert one_response(capsys)["ok"] is True


# ── extract ─────────────────────────────────────────────────────────

@pytest.fixture
def kb(tmp_path):
    """A KB directory for the extraction the handler now persists."""
    return str(tmp_path)


def extract_request(kb_dir, **kwargs):
    """An extract payload with the fields the worker always sends."""
    kwargs.setdefault("source", "raw/a.md")
    return request("extract", kb_dir=kb_dir, **kwargs)


@pytest.fixture
def stub_extract(monkeypatch):
    """Patch kb_ai.core.extract so routing can be observed without LLM calls."""
    import kb_ai.core.extract as ex

    state = {"chunks": ["c1"], "transcript": False, "routed": None}

    monkeypatch.setattr(ex, "_parse_frontmatter", lambda content: ({"meta": True}, "body"))
    monkeypatch.setattr(ex, "_is_transcript", lambda meta: state["transcript"])
    monkeypatch.setattr(ex, "chunk_content", lambda content: state["chunks"])
    monkeypatch.setattr(ex, "chunk_transcript", lambda body, meta: state["chunks"])

    def chunked(content, model):
        state["routed"] = "chunked"
        state["model"] = model
        state["content"] = content
        return ExtractionResult(summary="chunked-result")

    def summarized(chunks, meta, summarize_model, model):
        state["routed"] = "summarize"
        state["summarize_model"] = summarize_model
        state["model"] = model
        return ExtractionResult(summary="summarized-result")

    monkeypatch.setattr(ex, "extract_knowledge_chunked", chunked)
    monkeypatch.setattr(ex, "extract_knowledge_summarized", summarized)
    return state


def test_handle_extract_rejects_empty_content(capsys):
    sd._handle_extract("1", request("extract", content=""))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "EMPTY_CONTENT"


@pytest.mark.parametrize("missing, code", [
    ("kb_dir", "EMPTY_KB_DIR"),
    ("source", "EMPTY_SOURCE"),
])
def test_handle_extract_requires_the_fields_it_persists_with(capsys, missing, code):
    payload = {"kb_dir": "/kb", "source": "raw/a.md", "content": "text"}
    payload[missing] = ""
    sd._handle_extract("1", {"payload": payload})

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == code


def test_handle_extract_refuses_an_unknown_strategy(capsys, stub_extract, kb):
    """It used to fall back to chunked for anything it did not recognise, so a
    typo in a deployment's configuration extracted every document under a strategy
    nobody chose and the recorded provenance agreed with itself."""
    sd._handle_extract("1", extract_request(kb, content="text",
                                            strategy="Chunked"))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INVALID_STRATEGY"
    assert "unknown extract strategy" in resp["error"]["message"]


def test_handle_extract_defaults_to_chunked(capsys, stub_extract, kb):
    sd._handle_extract("1", extract_request(kb, content="some text"))

    resp = one_response(capsys)
    assert resp["ok"] is True
    assert resp["data"]["extraction"]["summary"] == "chunked-result"
    assert "cost" in resp["data"]
    assert stub_extract["routed"] == "chunked"


def test_handle_extract_summarize_strategy(capsys, stub_extract, kb):
    sd._handle_extract("1", extract_request(kb, content="text", strategy="summarize",
                                            summarize_model="sum-model",
                                            model="main-model"))

    assert one_response(capsys)["data"]["extraction"]["summary"] == "summarized-result"
    assert stub_extract["routed"] == "summarize"
    assert stub_extract["summarize_model"] == "sum-model"
    assert stub_extract["model"] == "main-model"


def test_handle_extract_auto_routes_to_summarize_for_many_chunks(capsys, stub_extract, kb):
    stub_extract["chunks"] = ["a", "b", "c"]

    sd._handle_extract("1", extract_request(kb, content="text", strategy="auto"))

    assert stub_extract["routed"] == "summarize"


def test_handle_extract_auto_routes_to_chunked_for_few_chunks(capsys, stub_extract, kb):
    stub_extract["chunks"] = ["a", "b"]

    sd._handle_extract("1", extract_request(kb, content="text", strategy="auto"))

    assert stub_extract["routed"] == "chunked"


def test_handle_extract_auto_uses_transcript_chunker(capsys, stub_extract, kb):
    """A transcript must be chunked by turns, not by raw content."""
    import kb_ai.core.extract as ex

    called = {}
    stub_extract["transcript"] = True

    def transcript_chunker(body, meta):
        called["transcript"] = True
        return ["a", "b", "c"]

    def content_chunker(content):
        pytest.fail("a transcript must not go through the content chunker")

    with patch.object(ex, "chunk_transcript", transcript_chunker):
        with patch.object(ex, "chunk_content", content_chunker):
            sd._handle_extract("1", extract_request(kb, content="text", strategy="auto"))

    assert called["transcript"] is True
    assert stub_extract["routed"] == "summarize"


def test_handle_extract_clears_request_tracker(capsys, stub_extract, kb):
    from kb_ai.llm import get_request_tracker

    sd._handle_extract("1", extract_request(kb, content="text"))

    assert get_request_tracker() is None


def test_handle_extract_clears_request_tracker_on_failure(capsys, monkeypatch, kb):
    import kb_ai.core.extract as ex
    from kb_ai.llm import get_request_tracker

    def boom(content, model):
        raise RuntimeError("llm down")

    monkeypatch.setattr(ex, "extract_knowledge_chunked", boom)

    with pytest.raises(RuntimeError):
        sd._handle_extract("1", extract_request(kb, content="text"))

    assert get_request_tracker() is None


# ── pipeline / index ────────────────────────────────────────────────

def test_handle_pipeline_returns_results_and_cost(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input",
                        lambda inner: [{"path": "a.md"}])

    sd._handle_pipeline("1", request("pipeline", kb_dir="/kb"))

    data = one_response(capsys)["data"]
    assert data["results"] == [{"path": "a.md"}]
    assert "cost" in data


def test_handle_pipeline_forwards_payload(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline
    seen = {}

    def fake(inner):
        seen.update(inner)
        return []

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", fake)

    sd._handle_pipeline("1", request("pipeline", kb_dir="/kb", workers=4))

    assert seen == {"kb_dir": "/kb", "workers": 4}


def test_handle_pipeline_clears_request_tracker_on_failure(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline
    from kb_ai.llm import get_request_tracker

    def boom(inner):
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", boom)

    with pytest.raises(RuntimeError):
        sd._handle_pipeline("1", request("pipeline"))

    assert get_request_tracker() is None


def test_handle_index_returns_result(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline

    monkeypatch.setattr(pipeline, "run_server_index_with_input", lambda inner: {"files": 3})

    sd._handle_index("1", request("index", kb_dir="/kb"))

    assert one_response(capsys)["data"] == {"files": 3}


# ── rewrite / suggest ───────────────────────────────────────────────

def test_handle_rewrite_returns_result(capsys, monkeypatch):
    import kb_ai.commands.rewrite as rw

    monkeypatch.setattr(rw, "rewrite_query",
                        lambda q, h, model: {"rewritten_query": f"{q}!", "model": model})

    sd._handle_rewrite("1", request("rewrite", query="q", history=[{"role": "user"}]))

    assert one_response(capsys)["data"]["rewritten_query"] == "q!"


def test_handle_rewrite_rejects_empty_query(capsys):
    sd._handle_rewrite("1", request("rewrite", query=""))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "EMPTY_QUERY"


def test_handle_suggest_returns_result(capsys, monkeypatch):
    import kb_ai.commands.suggest as sg

    monkeypatch.setattr(sg, "suggest_questions",
                        lambda q, a, model: {"suggestions": ["x"]})

    sd._handle_suggest("1", request("suggest", query="q", answer="a"))

    assert one_response(capsys)["data"]["suggestions"] == ["x"]


@pytest.mark.parametrize("payload", [
    {"query": "", "answer": "a"},
    {"query": "q", "answer": ""},
    {},
])
def test_handle_suggest_rejects_empty_input(capsys, payload):
    sd._handle_suggest("1", request("suggest", **payload))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "EMPTY_INPUT"


# ── fetch-url ───────────────────────────────────────────────────────

def test_handle_fetch_url_returns_document(capsys, monkeypatch):
    import kb_ai.commands.fetch as f

    monkeypatch.setattr(f, "fetch_url", lambda url: {"title": "T", "url": url})

    sd._handle_fetch_url("1", request("fetch-url", url="http://example.com"))

    assert one_response(capsys)["data"]["title"] == "T"


def test_handle_fetch_url_rejects_empty_url(capsys):
    sd._handle_fetch_url("1", request("fetch-url", url=""))

    resp = one_response(capsys)
    assert resp["error"]["code"] == "EMPTY_URL"


def test_handle_fetch_url_maps_value_error_to_fetch_failed(capsys, monkeypatch):
    import kb_ai.commands.fetch as f

    def boom(url):
        raise ValueError("failed to download: " + url)

    monkeypatch.setattr(f, "fetch_url", boom)

    sd._handle_fetch_url("1", request("fetch-url", url="http://example.com/gone"))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "FETCH_FAILED"
    assert "failed to download" in resp["error"]["message"]


# ── cancel ──────────────────────────────────────────────────────────

def test_handle_cancel_sets_the_target_event(capsys):
    event = threading.Event()
    registry = {"stream-1": event}
    lock = threading.Lock()

    sd._handle_cancel(request("cancel", target_id="stream-1"), "9", registry, lock)

    assert event.is_set()
    assert one_response(capsys)["data"] == {"cancelled": "stream-1"}


def test_handle_cancel_unknown_target_is_not_an_error(capsys):
    registry: dict[str, threading.Event] = {}

    sd._handle_cancel(request("cancel", target_id="ghost"), "9", registry, threading.Lock())

    assert one_response(capsys)["ok"] is True


def test_handle_cancel_leaves_other_streams_running(capsys):
    target, other = threading.Event(), threading.Event()
    registry = {"a": target, "b": other}

    sd._handle_cancel(request("cancel", target_id="a"), "9", registry, threading.Lock())

    assert target.is_set()
    assert not other.is_set()


# ── streaming dispatch ──────────────────────────────────────────────

def test_dispatch_streaming_chat_success(capsys, monkeypatch):
    import kb_ai.commands.chat as chat

    def fake(inner, emit):
        emit({"type": "delta", "content": "hi"})
        emit({"type": "done"})

    monkeypatch.setattr(chat, "run_server_chat_http", fake)
    registry = {"1": threading.Event()}
    lock = threading.Lock()

    sd._dispatch_streaming(request("chat", query="q"), "chat", "1",
                           registry["1"], registry, lock)

    events = responses(capsys)
    assert [e["event"]["type"] for e in events] == ["delta", "done"]
    assert events[-1]["final"] is True
    # The registry entry must be released so ids can be reused.
    assert registry == {}


def test_dispatch_streaming_marks_error_events_final(capsys, monkeypatch):
    import kb_ai.commands.chat as chat

    monkeypatch.setattr(chat, "run_server_chat_http",
                        lambda inner, emit: emit({"type": "error", "message": "bad"}))

    sd._dispatch_streaming(request("chat"), "chat", "1", threading.Event(), {}, threading.Lock())

    assert one_response(capsys)["final"] is True


def test_dispatch_streaming_cancelled_emits_cancelled_event(capsys, monkeypatch):
    import kb_ai.commands.chat as chat

    cancel_event = threading.Event()
    cancel_event.set()

    def fake(inner, emit):
        emit({"type": "delta"})   # emit sees the set event and raises

    monkeypatch.setattr(chat, "run_server_chat_http", fake)
    registry = {"1": cancel_event}

    sd._dispatch_streaming(request("chat"), "chat", "1", cancel_event,
                           registry, threading.Lock())

    resp = one_response(capsys)
    assert resp["event"] == {"type": "error", "code": "CANCELLED"}
    assert resp["final"] is True
    assert registry == {}


def test_dispatch_streaming_internal_error_emits_final_event(capsys, monkeypatch):
    import kb_ai.commands.chat as chat

    def boom(inner, emit):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(chat, "run_server_chat_http", boom)
    registry = {"1": threading.Event()}

    sd._dispatch_streaming(request("chat"), "chat", "1", threading.Event(),
                           registry, threading.Lock())

    resp = one_response(capsys)
    assert resp["event"]["code"] == "INTERNAL"
    assert "engine exploded" in resp["event"]["message"]
    assert resp["final"] is True
    assert registry == {}


def test_dispatch_streaming_unknown_command_emits_nothing(capsys):
    """Only the two registered streaming commands produce events; anything else
    falls through and is cleaned up."""
    registry = {"1": threading.Event()}

    sd._dispatch_streaming(request("nope"), "nope", "1", threading.Event(),
                           registry, threading.Lock())

    assert responses(capsys) == []
    assert registry == {}


def test_handle_pipeline_stream_emits_done_with_cost(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline

    def fake(inner, emit=None, cancel_event=None):
        emit({"type": "article", "path": "a.md"})
        return [{"path": "a.md"}]

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", fake)

    sd._handle_pipeline_stream(request("pipeline-stream", kb_dir="/kb"), "1", threading.Event())

    events = responses(capsys)
    assert events[0]["event"]["type"] == "article"
    assert events[-1]["event"]["type"] == "done"
    assert events[-1]["event"]["results"] == [{"path": "a.md"}]
    assert "cost" in events[-1]["event"]
    assert events[-1]["final"] is True


def test_handle_pipeline_stream_translates_pipeline_cancellation(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline
    from kb_ai.llm import PipelineCancelledError

    def boom(inner, emit=None, cancel_event=None):
        raise PipelineCancelledError("stopped")

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", boom)

    with pytest.raises(sd.CancelledError):
        sd._handle_pipeline_stream(request("pipeline-stream"), "1", threading.Event())


def test_handle_pipeline_stream_clears_request_tracker(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline
    from kb_ai.llm import get_request_tracker

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input",
                        lambda inner, emit=None, cancel_event=None: [])

    sd._handle_pipeline_stream(request("pipeline-stream"), "1", threading.Event())

    assert get_request_tracker() is None


def test_chat_stream_emit_raises_once_cancelled(capsys, monkeypatch):
    """The cancel event must stop the stream at the next emit, not merely be
    recorded for later."""
    import kb_ai.commands.chat as chat

    cancel_event = threading.Event()
    emitted = []

    def fake(inner, emit):
        emit({"type": "delta", "content": "1"})
        emitted.append("first")
        cancel_event.set()
        with pytest.raises(sd.CancelledError):
            emit({"type": "delta", "content": "2"})
        emitted.append("second-blocked")

    monkeypatch.setattr(chat, "run_server_chat_http", fake)

    sd._handle_chat_stream(request("chat"), "1", cancel_event)

    assert emitted == ["first", "second-blocked"]


# ── _dispatch routing ───────────────────────────────────────────────

def test_dispatch_unknown_command(capsys):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        should_exit = sd._dispatch(request("bogus"), "bogus", "1", time.time(), ex)

    assert should_exit is False
    resp = one_response(capsys)
    assert resp["error"]["code"] == "UNKNOWN_CMD"
    assert "bogus" in resp["error"]["message"]


def test_dispatch_shutdown_signals_exit(capsys):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        should_exit = sd._dispatch(request("shutdown"), "shutdown", "1", time.time(), ex)

    assert should_exit is True
    assert one_response(capsys)["data"] == {"shutdown": True}


def test_dispatch_ping(capsys):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        sd._dispatch(request("ping"), "ping", "1", time.time(), ex)

    assert "uptime_sec" in one_response(capsys)["data"]


def test_dispatch_converts_handler_exception_to_internal_error(capsys, monkeypatch):
    """A handler blowing up must still produce exactly one response, or the Go
    side would wait forever on that id."""
    from concurrent.futures import ThreadPoolExecutor

    def boom(request_id, payload):
        raise KeyError("missing thing")

    monkeypatch.setattr(sd, "_handle_rewrite", boom)

    with ThreadPoolExecutor(max_workers=1) as ex:
        sd._dispatch(request("rewrite"), "rewrite", "1", time.time(), ex)

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "INTERNAL_ERROR"
    assert "KeyError" in resp["error"]["message"]


@pytest.mark.parametrize("cmd,handler", [
    ("init", "_handle_init"),
    ("extract", "_handle_extract"),
    ("pipeline", "_handle_pipeline"),
    ("rewrite", "_handle_rewrite"),
    ("suggest", "_handle_suggest"),
    ("index", "_handle_index"),
    ("fetch-url", "_handle_fetch_url"),
])
def test_dispatch_routes_to_the_right_handler(monkeypatch, cmd, handler):
    from concurrent.futures import ThreadPoolExecutor

    called = {}
    monkeypatch.setattr(sd, handler,
                        lambda request_id, payload: called.setdefault("hit", handler))

    with ThreadPoolExecutor(max_workers=1) as ex:
        sd._dispatch(request(cmd), cmd, "1", time.time(), ex)

    assert called["hit"] == handler


def test_streaming_commands_registry():
    assert sd.STREAMING_COMMANDS == {"chat", "pipeline-stream"}


# ── main loop ───────────────────────────────────────────────────────

def run_main(lines: list[str], capsys) -> list[dict]:
    """Drive main() with the given stdin lines and collect its responses."""
    with patch("sys.stdin", StringIO("".join(line + "\n" for line in lines))):
        sd.main()
    return responses(capsys)


def test_main_prints_ready_marker():
    with patch("sys.stdin", StringIO("")):
        with patch("sys.stderr", StringIO()) as err:
            sd.main()
    assert "__READY__" in err.getvalue()


def test_main_exits_on_closed_stdin(capsys):
    assert run_main([], capsys) == []


def test_main_handles_ping(capsys):
    got = run_main([json.dumps({"id": "1", "cmd": "ping"})], capsys)

    assert len(got) == 1
    assert got[0]["id"] == "1"
    assert got[0]["ok"] is True


def test_main_reports_parse_error_with_empty_id(capsys):
    got = run_main(["{not json"], capsys)

    assert got[0]["id"] == ""
    assert got[0]["error"]["code"] == "PARSE_ERROR"


def test_main_skips_blank_lines(capsys):
    got = run_main(["", "   ", json.dumps({"id": "1", "cmd": "ping"})], capsys)

    assert len(got) == 1


def test_main_rejects_missing_cmd(capsys):
    got = run_main([json.dumps({"id": "1"})], capsys)

    assert got[0]["error"]["code"] == "INVALID_CMD"


def test_main_rejects_missing_id(capsys):
    got = run_main([json.dumps({"cmd": "ping"})], capsys)

    assert got[0]["error"]["code"] == "INVALID_REQUEST"


def test_main_stops_reading_after_shutdown(capsys):
    got = run_main([
        json.dumps({"id": "1", "cmd": "shutdown"}),
        json.dumps({"id": "2", "cmd": "ping"}),
    ], capsys)

    assert len(got) == 1
    assert got[0]["data"] == {"shutdown": True}


def test_main_dispatches_cancel_synchronously(capsys):
    got = run_main([
        json.dumps({"id": "9", "cmd": "cancel", "payload": {"target_id": "ghost"}}),
    ], capsys)

    assert got[0]["data"] == {"cancelled": "ghost"}


def test_main_runs_streaming_command_with_cancel_support(capsys, monkeypatch):
    import kb_ai.commands.chat as chat

    monkeypatch.setattr(chat, "run_server_chat_http",
                        lambda inner, emit: emit({"type": "done"}))

    got = run_main([json.dumps({"id": "s1", "cmd": "chat", "payload": {"query": "q"}})], capsys)

    assert got[-1]["id"] == "s1"
    assert got[-1]["final"] is True


def test_main_processes_several_commands(capsys):
    got = run_main([
        json.dumps({"id": "1", "cmd": "ping"}),
        json.dumps({"id": "2", "cmd": "ping"}),
        json.dumps({"id": "3", "cmd": "bogus"}),
    ], capsys)

    assert {r["id"] for r in got} == {"1", "2", "3"}


def test_main_honours_worker_env(capsys, monkeypatch):
    monkeypatch.setenv("KAAS_DAEMON_MAX_WORKERS", "2")

    captured = {}
    real_pool = sd.ThreadPoolExecutor

    def spy(max_workers):
        captured["max_workers"] = max_workers
        return real_pool(max_workers=max_workers)

    monkeypatch.setattr(sd, "ThreadPoolExecutor", spy)

    run_main([], capsys)

    assert captured["max_workers"] == 2


# ── derive ──────────────────────────────────────────────────────────

def test_derive_command_dispatches_to_derive_kb(monkeypatch):
    from kb_ai import server_daemon

    seen: dict = {}
    responses: list[dict] = []

    class _Report:
        derived_kb = "/kb/derived/pricing"
        slug = "pricing"
        topic = "pricing"
        selected_articles = ["wiki/a.md"]
        selected_documents: list = []
        skipped_articles: list = []
        skipped_documents: list = []
        documents: list = []
        dropped_invented_paths = 0
        filter_batches = 1
        offtopic_articles: list = []
        compiled = True
        compile = {"compiled": 1}
        cost = {"total_cost_usd": 0.25}
        warnings: list = []

    def fake_derive_kb(source_kb, topic, **kw):
        seen.update({"source_kb": source_kb, "topic": topic, **kw})
        return _Report()

    monkeypatch.setattr("kb_ai.derive.derive_kb", fake_derive_kb)
    monkeypatch.setattr(server_daemon, "_respond_ok",
                        lambda rid, data: responses.append(data))

    server_daemon._handle_derive("req-1", {"payload": {
        "kb_dir": "/kb", "topic": "pricing", "slug": "pricing", "force": True, "model": "m",
    }})

    assert seen["source_kb"] == "/kb"
    assert seen["topic"] == "pricing"
    assert seen["slug"] == "pricing"
    assert seen["force"] is True
    assert seen["model"] == "m"
    assert seen["approve"] is None  # H5: no volume gate on the async path
    assert responses[0]["slug"] == "pricing"
    assert responses[0]["compiled"] is True
    assert responses[0]["cost"] == {"total_cost_usd": 0.25}


def test_derive_command_reports_a_domain_error_code(monkeypatch):
    from kb_ai import server_daemon
    from kb_ai._errors import SlugExistsError

    errors_seen: list = []

    def boom(*a, **kw):
        raise SlugExistsError("already exists")

    monkeypatch.setattr("kb_ai.derive.derive_kb", boom)
    monkeypatch.setattr(server_daemon, "_respond_error",
                        lambda rid, code, msg: errors_seen.append((code, msg)))

    server_daemon._handle_derive("req-1", {"payload": {"kb_dir": "/kb", "topic": "t"}})
    assert errors_seen[0][0] == "SLUG_EXISTS"


def test_derive_requires_a_topic(monkeypatch):
    from kb_ai import server_daemon

    errors_seen: list = []
    monkeypatch.setattr(server_daemon, "_respond_error",
                        lambda rid, code, msg: errors_seen.append((code, msg)))

    server_daemon._handle_derive("req-1", {"payload": {"kb_dir": "/kb"}})
    assert errors_seen[0][0] == "EMPTY_TOPIC"


def test_derive_requires_a_kb_dir(monkeypatch):
    """An empty kb_dir would become Path("").resolve() -- the daemon's own CWD.

    This is the one handler that creates directories, so the missing input is
    guarded like every sibling handler's (EMPTY_CONTENT, EMPTY_QUERY, EMPTY_URL).
    """
    from kb_ai import server_daemon

    errors_seen: list = []
    monkeypatch.setattr(server_daemon, "_respond_error",
                        lambda rid, code, msg: errors_seen.append((code, msg)))
    monkeypatch.setattr("kb_ai.derive.derive_kb",
                        lambda *a, **kw: pytest.fail("derive must not run"))

    server_daemon._handle_derive("req-1", {"payload": {"topic": "pricing"}})
    assert errors_seen[0][0] == "EMPTY_KB_DIR"


def test_derive_isolates_cost_to_request_tracker(monkeypatch):
    """Per-request tracker must isolate cost from global tracker accumulation.

    Matches the class of defect fixed in commit a9bd607: a long-lived daemon
    accumulates LLM spend in the global tracker across all requests.  Each
    handler must create a fresh per-request CostTracker and set it before
    calling into the engine so the engine's own cost snapshot reads from the
    per-request tracker, not the global one.
    """
    from kb_ai import server_daemon
    from kb_ai._cost import CostTracker
    from kb_ai.llm import get_request_tracker
    import kb_ai.llm as llm_mod
    import kb_ai.derive as derive_mod

    responses: list[dict] = []

    # Pre-seed the global tracker with prior spend that must not leak into
    # this request's reported cost.
    prior = CostTracker()
    prior.record("claude-sonnet-4-6", 1_000_000, 500, cost=5.0)
    monkeypatch.setattr(llm_mod, "tracker", prior)
    monkeypatch.setattr(derive_mod, "tracker", prior)

    def fake_derive_kb(source_kb, topic, **kw):
        # If the handler set the per-request tracker, use it; otherwise fall
        # back to the global tracker (replicating derive_kb's own logic).
        req = get_request_tracker()
        effective = req if req is not None else prior
        effective.record("claude-sonnet-4-6", 500, 50, cost=0.01)
        effective.record("claude-sonnet-4-6", 300, 30, cost=0.01)
        cost = effective.summary()

        class _Report:
            derived_kb = "/kb/derived/t"
            slug = "t"
            selected_articles: list = []
            selected_documents: list = []
            skipped_articles: list = []
            skipped_documents: list = []
            documents: list = []
            dropped_invented_paths = 0
            filter_batches = 2
            offtopic_articles: list = []
            compiled = False
            compile: dict = {}
            warnings: list = []

        r = _Report()
        r.topic = topic
        r.cost = cost
        return r

    monkeypatch.setattr("kb_ai.derive.derive_kb", fake_derive_kb)
    monkeypatch.setattr(server_daemon, "_respond_ok",
                        lambda rid, data: responses.append(data))

    server_daemon._handle_derive("req-1", {"payload": {"kb_dir": "/kb", "topic": "t"}})

    assert responses, "handler produced no response"
    reported = responses[0]["cost"]["total_cost_usd"]
    # Only the two 0.01 calls from this request (0.02 total), not the 5.0
    # seeded in the global tracker from prior requests.
    assert reported == pytest.approx(0.02), (
        f"cost isolation failed: reported {reported} USD; "
        "expected 0.02 (5.0 from prior global spend must not appear)"
    )


def test_derive_command_passes_select_from(monkeypatch):
    """Without this the async path can only ever filter over articles, so a KB
    that was never compiled is unreachable through the daemon."""
    from kb_ai import server_daemon

    seen: dict = {}
    responses: list = []

    class _Report:
        derived_kb = "/kb/derived/pricing"
        slug = "pricing"
        topic = "pricing"
        selected_articles: list = []
        selected_documents = ["raw/a.md", "raw/b.md"]
        skipped_articles: list = []
        skipped_documents: list = []
        documents: list = []
        dropped_invented_paths = 0
        filter_batches = 1
        offtopic_articles: list = []
        compiled = True
        compile = {"compiled": 1}
        cost: dict = {}
        warnings: list = []

    monkeypatch.setattr("kb_ai.derive.derive_kb",
                        lambda source_kb, topic, **kw: (seen.update(kw), _Report())[1])
    monkeypatch.setattr(server_daemon, "_respond_ok",
                        lambda rid, data: responses.append(data))

    server_daemon._handle_derive("req-1", {"payload": {
        "kb_dir": "/kb", "topic": "pricing", "select_from": "documents",
    }})

    assert seen["select_from"] == "documents"
    assert responses[0]["select_from"] == "documents"
    # selected_articles is empty by design in this mode; reporting it would say 0.
    assert responses[0]["selected"] == 2


# ── extract: persistence, parity and reuse (spec C2-C9, H3, H6) ─────

def test_handle_extract_persists_the_extraction(capsys, stub_extract, kb):
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore, _compute_checksum

    sd._handle_extract("1", extract_request(kb, content="some text", model="M"))

    store = KBStore(kb)
    stored, reason = exl.load(store, "raw/a.md")
    assert reason == ""
    assert stored.extraction.summary == "chunked-result"
    assert stored.provenance.source == "raw/a.md"
    assert stored.provenance.source_checksum == _compute_checksum("some text")
    assert stored.provenance.extract_model == "M"
    assert stored.provenance.extract_strategy == "chunked"


def test_handle_extract_records_the_strategy_that_ran_not_auto(capsys, stub_extract, kb):
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore

    stub_extract["chunks"] = ["a", "b", "c"]
    sd._handle_extract("1", extract_request(kb, content="text", strategy="auto",
                                            summarize_model="S"))

    stored, _ = exl.load(KBStore(kb), "raw/a.md")
    assert stored.provenance.extract_strategy == "summarize"
    assert stored.provenance.summarize_model == "S"


def test_handle_extract_reuses_a_fresh_extraction_without_calling_the_model(
        capsys, stub_extract, kb):
    sd._handle_extract("1", extract_request(kb, content="text", model="M"))
    capsys.readouterr()
    stub_extract["routed"] = None

    sd._handle_extract("2", extract_request(kb, content="text", model="M"))

    resp = one_response(capsys)
    assert resp["data"]["reused"] is True
    assert resp["data"]["extraction"]["summary"] == "chunked-result"
    assert stub_extract["routed"] is None, "a retry must not pay for extraction again"


def test_handle_extract_re_extracts_when_the_model_changed(capsys, stub_extract, kb):
    sd._handle_extract("1", extract_request(kb, content="text", model="M"))
    capsys.readouterr()
    stub_extract["routed"] = None

    sd._handle_extract("2", extract_request(kb, content="text", model="OTHER"))

    assert stub_extract["routed"] == "chunked"


def test_handle_extract_fails_the_task_when_the_write_fails(capsys, stub_extract, kb,
                                                            monkeypatch):
    from kb_ai.storage import extraction as exl

    def boom(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(exl, "persist", boom)

    sd._handle_extract("1", extract_request(kb, content="text"))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "EXTRACTION_NOT_PERSISTED"
    assert "No space left" in resp["error"]["message"]


def test_handle_extract_reports_unreadable_prompts(capsys, stub_extract, kb,
                                                   monkeypatch):
    from kb_ai.prompts import NoActivePromptError
    from kb_ai.storage import extraction as exl

    def boom():
        raise NoActivePromptError("prompt file not found: extract.md")

    monkeypatch.setattr(exl, "extract_prompt_version", boom)

    sd._handle_extract("1", extract_request(kb, content="text"))

    resp = one_response(capsys)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "PROMPT_UNAVAILABLE"
    assert stub_extract["routed"] is None


def test_handle_extract_normalises_crlf_before_hashing(capsys, stub_extract, kb,
                                                      tmp_path):
    """H6: the daemon's source_checksum equals the CLI's for a CRLF document."""
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore, _compute_checksum

    raw = tmp_path / "crlf.md"
    raw.write_bytes(b"line one\r\nline two\rline three\n")

    sd._handle_extract("1", extract_request(kb, content=raw.read_bytes().decode()))

    stored, _ = exl.load(KBStore(kb), "raw/a.md")
    assert stored.provenance.source_checksum == _compute_checksum(raw.read_text())


def test_handle_extract_prompts_the_model_with_the_same_bytes_as_the_cli(
        capsys, stub_extract, kb, tmp_path):
    """H6's second half: a green checksum test would still hide this."""
    raw = tmp_path / "crlf.md"
    raw.write_bytes(b"line one\r\nline two\rline three\n")

    sd._handle_extract("1", extract_request(kb, content=raw.read_bytes().decode()))

    assert stub_extract["content"] == raw.read_text()


def test_both_routes_write_a_byte_identical_extraction_file(capsys, kb, tmp_path,
                                                            monkeypatch):
    """H3 / C2: one serializer, exercised through both ingestion routes.

    Runs in one process on purpose -- prompt_version is memoized per process, so
    two processes would be measuring cache timing rather than the serializer.
    """
    import kb_ai.core.extract as ex
    from kb_ai.commands import compile as cm
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore

    monkeypatch.setattr(exl, "_now_iso", lambda: "2026-08-07T11:22:33+00:00")
    result = ExtractionResult(summary="同一份摘要", concepts=[{"title": "t"}],
                             topics=["b", "a"])
    # One patch for both routes: they dispatch through the same router, which
    # resolves this in core.extract's namespace. Two were needed when each route
    # called the extractor itself -- the same duplication that let their recorded
    # strategies diverge.
    monkeypatch.setattr(ex, "extract_knowledge_chunked",
                        lambda content, model=None: result)
    monkeypatch.setattr(cm, "classify_article",
                        lambda *a, **kw: {"merge_into": [], "create_new": []})
    monkeypatch.setattr(cm, "dedup_create_new", lambda result_, existing: result_)

    # CLI route.
    cli = KBStore(str(tmp_path / "cli"))
    cli.write_raw("raw/a.md", "content")
    cm.compile_kb(str(cli.base_dir), extract_model="M", extract_only=True)

    # Worker route, same document.
    worker = KBStore(kb)
    worker.write_raw("raw/a.md", "content")
    sd._handle_extract("1", extract_request(kb, content="content", model="M"))

    assert (worker.extraction_path("raw/a.md").read_text()
            == cli.extraction_path("raw/a.md").read_text())
