"""Offline tests for the streaming chat command (kb_ai.commands.chat).

`_run_chat_core` is the single code path behind the stdin bridge, the HTTP/SSE
server and the MCP `ask` tool, so the contract under test is what that core
owns: prompt-cache message shaping, history normalisation, cost estimation,
citation extraction, usage accounting and the API-error boundary. The LLM
stream is a fake that records the request it was given — nothing here touches
the network.
"""
from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from openai import APIError, APIStatusError, APITimeoutError

from kb_ai.commands import chat as ch
from kb_ai.storage.store import KBStore


# ── fake stream helpers ─────────────────────────────────────────────

def _delta(text: str | None):
    """A content chunk of the OpenAI streaming response (None = no content)."""
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
        usage=None,
    )


def _usage_chunk(prompt_tokens: int = 100, completion_tokens: int = 20,
                 details=None, raw: dict | None = None):
    """The trailing usage-only chunk (stream_options.include_usage)."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=details,
    )
    if raw is not None:
        usage.model_dump = lambda: raw
    return SimpleNamespace(choices=[], usage=usage)


def _cache_details(cached: int = 0, created: int = 0):
    return SimpleNamespace(cached_tokens=cached, cache_creation_tokens=created)


@pytest.fixture(autouse=True)
def fresh_cache_state():
    """The module keeps one process-wide adaptive cache toggle — isolate it."""
    ch._reset_cache_state()
    yield
    ch._reset_cache_state()


@pytest.fixture
def llm(monkeypatch):
    """Fake streaming client: replays `chunks`, records every create() call."""
    state = SimpleNamespace(chunks=[_delta("ok"), _usage_chunk()], calls=[])

    def create(**kwargs):
        state.calls.append(kwargs)
        return iter(state.chunks)

    monkeypatch.setattr(ch, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return state


def _failing_client(monkeypatch, exc: Exception):
    """Install a client whose create() raises `exc`."""
    def create(**kwargs):
        raise exc

    monkeypatch.setattr(ch, "get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))


def _system_text(call: dict) -> str:
    """Pull the system prompt text out of a recorded create() call."""
    content = call["messages"][0]["content"]
    return content[0]["text"] if isinstance(content, list) else content


# ── _build_system_message ───────────────────────────────────────────

def test_system_message_is_a_cached_content_block_when_caching_is_on():
    assert ch._build_system_message(True, "instructions") == {
        "role": "system",
        "content": [{"type": "text", "text": "instructions",
                     "cache_control": {"type": "ephemeral"}}],
    }


def test_system_message_is_a_plain_string_when_caching_is_off():
    assert ch._build_system_message(False, "instructions") == {
        "role": "system", "content": "instructions"}


# ── _add_cache_to_last_history ──────────────────────────────────────

def test_add_cache_to_last_history_returns_an_empty_history_untouched():
    empty: list[dict] = []
    assert ch._add_cache_to_last_history(empty) is empty


def test_add_cache_to_last_history_marks_only_the_final_message():
    history = [{"role": "user", "content": "first"},
               {"role": "assistant", "content": "second"}]

    out = ch._add_cache_to_last_history(history)

    assert out[0] == {"role": "user", "content": "first"}
    assert out[-1] == {"role": "assistant", "content": [
        {"type": "text", "text": "second", "cache_control": {"type": "ephemeral"}}]}


def test_add_cache_to_last_history_does_not_mutate_the_input():
    history = [{"role": "assistant", "content": "second"}]

    ch._add_cache_to_last_history(history)

    assert history == [{"role": "assistant", "content": "second"}]


def test_add_cache_to_last_history_skips_non_string_content():
    history = [{"role": "assistant", "content": [{"type": "text", "text": "blocks"}]}]

    assert ch._add_cache_to_last_history(history) == history


# ── _build_user_message ─────────────────────────────────────────────

def test_user_message_wraps_the_context_as_reference_material():
    assert ch._build_user_message("who?", "article body") == (
        "<reference_material>\narticle body\n</reference_material>\n\nwho?")


def test_user_message_is_the_bare_query_when_there_is_no_context():
    assert ch._build_user_message("who?", "") == "who?"


# ── cost reporting ──────────────────────────────────────────────────

def test_chat_prices_a_routed_model_name(llm):
    """A proxy-routed name must not silently report 0 in the done event.

    Chat used to carry its own exact/prefix-only pricing lookup, so every
    deployment behind a router (`us.claude-sonnet-4-6`) reported no cost at all.
    """
    events: list[dict] = []
    llm.chunks = [_delta("ok"), _usage_chunk(prompt_tokens=1_000_000, completion_tokens=0)]

    ch._run_chat_core({"query": "q", "model": "us.claude-sonnet-4-6"}, events.append)

    done = next(e for e in events if e["type"] == "done")
    assert done["cost_usd"] == pytest.approx(3.0)


def test_chat_reports_zero_for_a_model_with_no_known_pricing(llm):
    events: list[dict] = []
    llm.chunks = [_delta("ok"), _usage_chunk(prompt_tokens=1_000_000, completion_tokens=0)]

    ch._run_chat_core({"query": "q", "model": "some-other-llm"}, events.append)

    done = next(e for e in events if e["type"] == "done")
    assert done["cost_usd"] == 0.0


# ── _extract_citations ──────────────────────────────────────────────

def test_extract_citations_keeps_only_retrieved_paths_and_dedupes():
    answer = ("see [A](wiki/a.md) and [Ghost](wiki/ghost.md) "
              "and again [A again](wiki/a.md)")

    cited = ch._extract_citations(answer, {"wiki/a.md", "wiki/b.md"})

    assert cited == [{"title": "A", "path": "wiki/a.md"}]


def test_extract_citations_matches_the_leading_slash_form():
    """The chat prompt asks for `/wiki/...`; retrieved paths have no leading slash."""
    cited = ch._extract_citations("see [A](/wiki/a.md)", {"wiki/a.md"})

    assert cited == [{"title": "A", "path": "wiki/a.md"}]


def test_extract_citations_matches_relative_and_extensionless_forms():
    answer = "see [A](./wiki/a.md) and [B](wiki/b)"

    cited = ch._extract_citations(answer, {"wiki/a.md", "wiki/b.md"})

    assert cited == [{"title": "A", "path": "wiki/a.md"},
                     {"title": "B", "path": "wiki/b.md"}]


def test_extract_citations_ignores_an_anchor_fragment():
    cited = ch._extract_citations("see [A](/wiki/a.md#overview)", {"wiki/a.md"})

    assert cited == [{"title": "A", "path": "wiki/a.md"}]


def test_extract_citations_dedupes_across_path_spellings():
    answer = "see [A](/wiki/a.md) then [A again](wiki/a.md) then [A third](./wiki/a)"

    cited = ch._extract_citations(answer, {"wiki/a.md"})

    assert cited == [{"title": "A", "path": "wiki/a.md"}]


def test_extract_citations_ignores_external_links():
    answer = "see [Upstream](https://example.com/wiki/a.md)"

    assert ch._extract_citations(answer, {"wiki/a.md"}) == []


# ── context assembly ────────────────────────────────────────────────

def test_chat_without_context_sends_only_the_bare_query(llm):
    events: list[dict] = []

    ch._run_chat_core({"query": "hello"}, events.append)

    sent = llm.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert sent[-1]["content"] == "hello"
    assert events[-1]["retrieved_sources"] == []
    assert events[-1]["cited_sources"] == []


def test_chat_grounds_the_prompt_in_supplied_articles(llm):
    llm.chunks = [_delta("see [W](wiki/w.md) and [Ghost](wiki/ghost.md)"), _usage_chunk()]
    events: list[dict] = []

    ch._run_chat_core({
        "query": "how do workers run?",
        "articles": [{"title": "W", "path": "wiki/w.md", "content": "worker pool details"}],
    }, events.append)

    user = llm.calls[0]["messages"][-1]["content"]
    assert "<reference_material>" in user
    assert "### W (/wiki/w.md)\nworker pool details" in user
    done = events[-1]
    assert done["retrieved_sources"] == [{"title": "W", "path": "wiki/w.md"}]
    # Only citations that intersect the retrieved paths survive.
    assert done["cited_sources"] == [{"title": "W", "path": "wiki/w.md"}]


def test_chat_with_explicit_articles_emits_no_retrieval_status(llm):
    """Without kb_dir there is nothing to retrieve, so no status event."""
    events: list[dict] = []

    ch._run_chat_core({"query": "q", "articles": [
        {"title": "W", "path": "wiki/w.md", "content": "body"}]}, events.append)

    assert [e["type"] for e in events] == ["delta", "done"]


def test_chat_reads_explicit_paths_from_the_kb(tmp_path, llm):
    store = KBStore(str(tmp_path))
    store.write_article("wiki/w.md", "worker pool details")
    events: list[dict] = []

    ch._run_chat_core({"query": "how?", "kb_dir": str(tmp_path),
                       "paths": ["wiki/w.md"]}, events.append)

    status = next(e for e in events if e["type"] == "status")
    assert status["stage"] == "retrieved"
    assert [s["path"] for s in status["sources"]] == ["wiki/w.md"]
    # The page was really read off disk and grounded into the prompt.
    assert "worker pool details" in llm.calls[0]["messages"][-1]["content"]


# ── history normalisation ───────────────────────────────────────────

def test_chat_drops_non_turn_history_and_the_duplicated_current_query(llm):
    """Go sends the full transcript plus the query field, so the trailing user
    message would otherwise be sent twice."""
    ch._run_chat_core({
        "query": "next?",
        "messages": [
            {"role": "user", "content": "first question"},
            {"role": "system", "content": "not a turn"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "next?"},
        ],
    }, lambda e: None)

    sent = llm.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "first question"
    assert sent[-1]["content"] == "next?"


def test_chat_marks_the_last_history_turn_for_prompt_caching(llm):
    ch._run_chat_core({"query": "next?", "messages": [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]}, lambda e: None)

    sent = llm.calls[0]["messages"]
    assert sent[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent[2]["content"] == [{"type": "text", "text": "first answer",
                                  "cache_control": {"type": "ephemeral"}}]


def test_chat_sends_plain_messages_once_the_cache_auto_disables(llm):
    for _ in range(10):
        ch._update_cache_state(0, 0)      # ten consecutive misses
    assert ch._cache_state.is_enabled is False

    ch._run_chat_core({"query": "next?", "messages": [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]}, lambda e: None)

    sent = llm.calls[0]["messages"]
    assert isinstance(sent[0]["content"], str)
    assert sent[2]["content"] == "first answer"


# ── prompt selection ────────────────────────────────────────────────

def test_chat_uses_the_with_sources_prompt_by_default(llm):
    ch._run_chat_core({"query": "q"}, lambda e: None)

    assert "Cite sources as" in _system_text(llm.calls[0])


def test_chat_uses_the_no_sources_prompt_when_sources_are_disabled(llm):
    ch._run_chat_core({"query": "q", "include_sources": False}, lambda e: None)

    assert 'Do NOT include any "Sources:" section' in _system_text(llm.calls[0])


def test_chat_forwards_model_and_temperature_to_the_llm(llm):
    ch._run_chat_core({"query": "q", "model": "claude-haiku-4-5",
                       "temperature": 0.7}, lambda e: None)

    call = llm.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["temperature"] == 0.7
    assert call["stream"] is True
    assert call["stream_options"] == {"include_usage": True}


# ── empty request ───────────────────────────────────────────────────

def test_chat_with_nothing_to_answer_finishes_without_calling_the_llm(llm):
    events: list[dict] = []

    ch._run_chat_core({}, events.append)

    assert llm.calls == []
    assert len(events) == 1
    done = events[0]
    assert done["type"] == "done"
    assert done["tokens_prompt"] == 0
    assert done["tokens_completion"] == 0
    assert done["cost_usd"] == 0.0
    assert done["cited_sources"] == []
    assert done["retrieved_sources"] == []
    assert "prompt_id" in done


# ── streaming and usage accounting ──────────────────────────────────

def test_chat_streams_each_content_chunk_and_skips_empty_deltas(llm):
    llm.chunks = [_delta("Workers "), _delta(None), _delta("run."), _usage_chunk()]
    events: list[dict] = []

    ch._run_chat_core({"query": "q"}, events.append)

    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert "".join(e["content"] for e in events if e["type"] == "delta") == "Workers run."


def test_chat_reports_token_counts_and_cost_from_the_usage_chunk(llm):
    llm.chunks = [_delta("hi"), _usage_chunk(prompt_tokens=1_000_000,
                                             completion_tokens=1_000_000)]
    events: list[dict] = []

    ch._run_chat_core({"query": "q", "model": "claude-sonnet-4-6"}, events.append)

    done = events[-1]
    assert done["tokens_prompt"] == 1_000_000
    assert done["tokens_completion"] == 1_000_000
    assert done["cost_usd"] == pytest.approx(18.0)


def test_chat_reads_cached_tokens_from_prompt_tokens_details(llm):
    llm.chunks = [_delta("hi"), _usage_chunk(prompt_tokens=1_000_000, completion_tokens=0,
                                             details=_cache_details(cached=500_000))]
    events: list[dict] = []

    ch._run_chat_core({"query": "q", "model": "claude-sonnet-4-6"}, events.append)

    done = events[-1]
    assert done["cached_tokens"] == 500_000
    # Half the prompt billed at 10%: 500k*3 + 500k*0.3 per 1M = 1.65 USD.
    assert done["cost_usd"] == pytest.approx(1.65)


def test_chat_falls_back_to_the_anthropic_raw_usage_keys(llm):
    llm.chunks = [_delta("hi"), _usage_chunk(
        prompt_tokens=1000, completion_tokens=10, details=None,
        raw={"cache_read_input_tokens": 400, "cache_creation_input_tokens": 600})]
    events: list[dict] = []

    ch._run_chat_core({"query": "q"}, events.append)

    assert events[-1]["cached_tokens"] == 400


def test_chat_counts_a_cacheless_response_as_a_miss_and_a_cache_read_as_a_hit(llm):
    llm.chunks = [_delta("hi"), _usage_chunk(details=_cache_details())]
    ch._run_chat_core({"query": "q"}, lambda e: None)
    assert ch._cache_state.consecutive_misses == 1

    llm.chunks = [_delta("hi"), _usage_chunk(details=_cache_details(cached=64))]
    ch._run_chat_core({"query": "q"}, lambda e: None)
    assert ch._cache_state.consecutive_misses == 0


# ── API error boundary ──────────────────────────────────────────────

def test_chat_reraises_a_timeout_and_warns_with_the_timeout_kind(monkeypatch, capsys):
    request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    _failing_client(monkeypatch, APITimeoutError(request=request))

    with pytest.raises(APITimeoutError):
        ch._run_chat_core({"query": "q", "model": "claude-haiku-4-5"}, lambda e: None)

    err = capsys.readouterr().err
    assert "[LLM-WARN] timeout:" in err
    assert "model=claude-haiku-4-5 attempt=1" in err


def test_chat_reraises_an_http_error_and_warns_with_the_status_kind(monkeypatch, capsys):
    request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    response = httpx.Response(503, request=request)
    _failing_client(monkeypatch, APIStatusError("service unavailable",
                                               response=response, body=None))

    with pytest.raises(APIStatusError):
        ch._run_chat_core({"query": "q"}, lambda e: None)

    assert "[LLM-WARN] http_503: service unavailable" in capsys.readouterr().err


def test_chat_reraises_a_statusless_api_error_as_http_zero(monkeypatch, capsys):
    request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    _failing_client(monkeypatch, APIError("connection reset", request, body=None))

    with pytest.raises(APIError):
        ch._run_chat_core({"query": "q"}, lambda e: None)

    assert "[LLM-WARN] http_0: connection reset" in capsys.readouterr().err


def test_chat_emits_no_done_event_when_the_stream_never_starts(monkeypatch):
    """A failed create() must not produce a `done` event claiming success."""
    request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    _failing_client(monkeypatch, APITimeoutError(request=request))
    events: list[dict] = []

    with pytest.raises(APITimeoutError):
        ch._run_chat_core({"query": "q"}, events.append)

    assert events == []


# ── entry points ────────────────────────────────────────────────────

def test_run_server_chat_http_streams_through_the_emit_callback(llm):
    events: list[dict] = []

    ch.run_server_chat_http({"query": "q"}, events.append)

    assert [e["type"] for e in events] == ["delta", "done"]
    assert events[0]["content"] == "ok"


def test_chat_command_execute_runs_the_core(llm):
    events: list[dict] = []

    ch.ChatCommand().execute({"query": "q"}, events.append)

    assert [e["type"] for e in events] == ["delta", "done"]


def test_run_server_chat_reads_stdin_and_writes_json_line_events(llm, capsys):
    with patch("sys.stdin", StringIO(json.dumps({"query": "q"}))):
        ch.run_server_chat()

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()
             if line.strip()]
    assert [e["type"] for e in lines] == ["delta", "done"]
    assert lines[0]["content"] == "ok"


def test_run_server_chat_reports_a_failure_as_an_error_event(monkeypatch, capsys):
    """The bridge entry point must never raise — the daemon reads its stdout."""
    def boom():
        raise RuntimeError("client unavailable")

    monkeypatch.setattr(ch, "get_client", boom)

    with patch("sys.stdin", StringIO(json.dumps({"query": "q"}))):
        ch.run_server_chat()

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()
             if line.strip()]
    assert lines[-1] == {"type": "error", "message": "client unavailable",
                         "code": "INTERNAL_ERROR"}
