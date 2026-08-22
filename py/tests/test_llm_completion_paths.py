"""Tests for the uncovered branches of kb_ai.llm._completion and kb_ai.llm.__init__.

Covers: per-call timeout override, response_format passthrough, error
classification / retry-exhaustion paths, adaptive-cache bookkeeping, the
truncation-vs-deadline guard, completion_json's json_repair fallback, and the
backward-compat context wrappers re-exported from kb_ai.llm.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import json_repair
import pytest
from openai import APIStatusError, APITimeoutError

import kb_ai.llm as llm_pkg
import kb_ai.llm._completion as completion_mod
from kb_ai._errors import DeadlineExceededError, LLMTimeoutError, PipelineCancelledError
from kb_ai.llm._completion import _cache_state, _completion_inner, completion, completion_json


def _make_response(content="Hello world", finish_reason="stop", prompt_tokens=100,
                   completion_tokens=50, cached_tokens=0, cache_created_tokens=0,
                   usage_present=True):
    """Build a fake OpenAI non-streaming response."""
    usage = None
    if usage_present:
        usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=cached_tokens, cache_creation_tokens=cache_created_tokens
            ),
            model_dump=lambda: {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_read_input_tokens": cached_tokens,
                "cache_creation_input_tokens": cache_created_tokens,
            },
        )
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _status_error(status_code: int, message: str = "boom",
                  headers: dict | None = None) -> APIStatusError:
    """Build a real openai.APIStatusError carrying the given HTTP status."""
    request = httpx.Request("POST", "http://test:8080/v1/chat/completions")
    return APIStatusError(
        message,
        response=httpx.Response(status_code, request=request, headers=headers),
        body=None,
    )


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(httpx.Request("POST", "http://test:8080/v1/chat/completions"))


MSGS = [{"role": "user", "content": "Hi"}]


@pytest.fixture
def mock_client():
    """Fake OpenAI client wired into kb_ai.llm.get_client."""
    client = MagicMock()
    client.base_url = "http://test:8080/v1"
    client.chat.completions.create.return_value = _make_response()
    with patch.object(llm_pkg, "get_client", return_value=client):
        yield client


@pytest.fixture
def cache_state():
    """Reset the module-level adaptive cache singleton before and after the test."""
    _cache_state.reset()
    yield _cache_state
    _cache_state.reset()


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff sleeps instead of actually sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


class TestClientOptions:
    """Per-call client configuration (timeout override, response_format)."""

    def test_call_timeout_override_routes_through_with_options(self, mock_client, fresh_context):
        override_client = MagicMock()
        override_client.base_url = "http://test:8080/v1"
        override_client.chat.completions.create.return_value = _make_response(
            content="from override client"
        )
        mock_client.with_options.return_value = override_client
        fresh_context.call_timeout = 42.5

        text, _ = _completion_inner("model", MSGS)

        assert text == "from override client"
        assert mock_client.with_options.call_args.kwargs == {"timeout": 42.5}
        assert mock_client.chat.completions.create.call_count == 0

    def test_no_call_timeout_uses_shared_client(self, mock_client, fresh_context):
        assert fresh_context.call_timeout is None

        text, _ = _completion_inner("model", MSGS)

        assert text == "Hello world"
        assert mock_client.with_options.call_count == 0

    def test_response_format_forwarded_when_given(self, mock_client):
        _completion_inner("model", MSGS, response_format={"type": "json_object"})

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_response_format_omitted_when_none(self, mock_client):
        _completion_inner("model", MSGS)

        assert "response_format" not in mock_client.chat.completions.create.call_args.kwargs


class TestErrorClassification:
    """Error classification / retry-exhaustion paths in _completion_inner."""

    def test_non_retryable_status_error_is_reraised(self, mock_client, capsys):
        original = _status_error(400, "bad request")
        mock_client.chat.completions.create.side_effect = original

        with pytest.raises(APIStatusError) as excinfo:
            _completion_inner("model", MSGS)

        assert excinfo.value is original
        # A 4xx must not be retried.
        assert mock_client.chat.completions.create.call_count == 1
        assert "http_400" in capsys.readouterr().err

    def test_gateway_error_is_reraised_when_retries_exhausted(
        self, mock_client, monkeypatch, capsys
    ):
        monkeypatch.setattr(completion_mod, "_TIMEOUT_RETRIES", 0)
        original = _status_error(503, "service unavailable")
        mock_client.chat.completions.create.side_effect = original

        with pytest.raises(APIStatusError) as excinfo:
            _completion_inner("model", MSGS)

        assert excinfo.value is original
        assert "gateway_503" in capsys.readouterr().err

    def test_rate_limit_is_reraised_when_retries_exhausted(
        self, mock_client, monkeypatch, capsys
    ):
        monkeypatch.setattr(completion_mod, "_TIMEOUT_RETRIES", 0)
        original = _status_error(429, "rate limit exceeded")
        mock_client.chat.completions.create.side_effect = original

        with pytest.raises(APIStatusError) as excinfo:
            _completion_inner("model", MSGS)

        assert excinfo.value is original
        assert "rate_limited_429" in capsys.readouterr().err

    def test_timeout_raises_llm_timeout_error_when_retries_exhausted(
        self, mock_client, monkeypatch, capsys
    ):
        monkeypatch.setattr(completion_mod, "_TIMEOUT_RETRIES", 0)
        mock_client.chat.completions.create.side_effect = _timeout_error()

        with pytest.raises(LLMTimeoutError) as excinfo:
            _completion_inner("model", MSGS)

        message = str(excinfo.value)
        assert "api_timeout_error" in message
        assert "attempts=1" in message
        assert "base_url=http://test:8080/v1" in message
        assert "api_timeout_error" in capsys.readouterr().err

    def test_retries_after_timeout_then_succeeds(self, mock_client, no_sleep, fresh_context):
        mock_client.chat.completions.create.side_effect = [
            _timeout_error(),
            _make_response(content="recovered"),
        ]

        text, reason = _completion_inner("model", MSGS)

        assert text == "recovered"
        assert reason == "stop"
        assert mock_client.chat.completions.create.call_count == 2
        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]


class TestRetryBackoff:
    """Exponential backoff, retry logging, and the deadline_too_close guard."""

    def test_backoff_doubles_across_retries(self, mock_client, no_sleep, fresh_context, capsys):
        base = completion_mod._TIMEOUT_BACKOFF_BASE
        mock_client.chat.completions.create.side_effect = [
            _timeout_error(),
            _timeout_error(),
            _make_response(content="third time lucky"),
        ]

        text, _ = _completion_inner("model", MSGS)

        assert text == "third time lucky"
        assert mock_client.chat.completions.create.call_count == 3
        # _TIMEOUT_BACKOFF_BASE * 2**attempt for attempt = 0, 1.
        assert no_sleep == [base, base * 2]
        err = capsys.readouterr().err
        assert "[timeout] op=unknown model=model attempt=1/3" in err
        assert f"retrying in {base}s..." in err
        assert f"retrying in {base * 2}s..." in err

    def test_gateway_error_retries_with_gateway_label(
        self, mock_client, no_sleep, fresh_context, capsys
    ):
        mock_client.chat.completions.create.side_effect = [
            _status_error(502, "bad gateway"),
            _make_response(content="gateway recovered"),
        ]

        text, _ = _completion_inner("model", MSGS)

        assert text == "gateway recovered"
        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]
        err = capsys.readouterr().err
        assert "[gateway_502]" in err
        assert f"retrying in {completion_mod._TIMEOUT_BACKOFF_BASE}s..." in err

    def test_rate_limit_is_retried_then_succeeds(
        self, mock_client, no_sleep, fresh_context, capsys
    ):
        """429 says "slow down", not "this request is malformed". Leaving it out of
        the retryable set fails a whole document on a condition that clears in
        seconds -- and the more concurrency a run uses, the more it happens."""
        mock_client.chat.completions.create.side_effect = [
            _status_error(429, "rate limit exceeded"),
            _make_response(content="limit cleared"),
        ]

        text, _ = _completion_inner("model", MSGS)

        assert text == "limit cleared"
        assert mock_client.chat.completions.create.call_count == 2
        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]
        assert "[rate_limited_429]" in capsys.readouterr().err

    def test_rate_limit_waits_the_retry_after_the_server_asked_for(
        self, mock_client, no_sleep, fresh_context
    ):
        mock_client.chat.completions.create.side_effect = [
            _status_error(429, "slow down", headers={"retry-after": "45"}),
            _make_response(content="ok"),
        ]

        _completion_inner("model", MSGS)

        assert no_sleep == [45.0]

    def test_rate_limit_keeps_the_backoff_when_retry_after_is_shorter(
        self, mock_client, no_sleep, fresh_context
    ):
        mock_client.chat.completions.create.side_effect = [
            _status_error(429, "slow down", headers={"retry-after": "1"}),
            _make_response(content="ok"),
        ]

        _completion_inner("model", MSGS)

        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]

    def test_rate_limit_caps_an_outsized_retry_after(
        self, mock_client, no_sleep, fresh_context
    ):
        """An unbounded header value would park a worker for as long as the server
        asked, which one bad value turns into a stalled run."""
        mock_client.chat.completions.create.side_effect = [
            _status_error(429, "slow down", headers={"retry-after": "99999"}),
            _make_response(content="ok"),
        ]

        _completion_inner("model", MSGS)

        assert no_sleep == [completion_mod._RETRY_AFTER_CAP_S]

    def test_rate_limit_falls_back_to_backoff_on_an_unreadable_retry_after(
        self, mock_client, no_sleep, fresh_context
    ):
        mock_client.chat.completions.create.side_effect = [
            _status_error(429, "slow down", headers={"retry-after": "in a while"}),
            _make_response(content="ok"),
        ]

        _completion_inner("model", MSGS)

        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]

    def test_deadline_too_close_blocks_timeout_retry(
        self, mock_client, no_sleep, fresh_context, capsys
    ):
        mock_client.chat.completions.create.side_effect = _timeout_error()
        fresh_context.phase = "fetch"
        # wait (10s) + the 60s safety margin overruns a 30s-away deadline.
        fresh_context.deadline_abs = time.monotonic() + 30

        with pytest.raises(DeadlineExceededError) as excinfo:
            _completion_inner("model", MSGS)

        message = str(excinfo.value)
        assert "deadline_too_close" in message
        assert "op=fetch" in message
        assert "model=model" in message
        assert "attempts=1" in message
        assert "base_url=http://test:8080/v1" in message
        # Bail out immediately: no backoff sleep, no second request.
        assert no_sleep == []
        assert mock_client.chat.completions.create.call_count == 1
        assert "[timeout] op=fetch model=model attempt=1/3" in capsys.readouterr().err

    def test_deadline_too_close_blocks_gateway_retry(
        self, mock_client, no_sleep, fresh_context, capsys
    ):
        mock_client.chat.completions.create.side_effect = _status_error(504, "gateway timeout")
        fresh_context.deadline_abs = time.monotonic() + 30

        with pytest.raises(DeadlineExceededError, match="deadline_too_close"):
            _completion_inner("model", MSGS)

        assert no_sleep == []
        assert "[gateway_504] " in capsys.readouterr().err

    def test_ample_deadline_still_allows_retry(self, mock_client, no_sleep, fresh_context):
        mock_client.chat.completions.create.side_effect = [
            _timeout_error(),
            _make_response(content="retried in time"),
        ]
        fresh_context.deadline_abs = time.monotonic() + 600

        text, _ = _completion_inner("model", MSGS)

        assert text == "retried in time"
        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]

    def test_context_accessors_survive_a_retry(self, mock_client, no_sleep, fresh_context):
        """record_cost's lambdas close over ctx -- it must still be the ThreadContext."""
        events: list[dict] = []
        request_tracker = llm_pkg.CostTracker(store_details=True)
        fresh_context.phase = "classify"
        fresh_context.content_hash = "deadbeef"
        fresh_context.call_emit = events.append
        fresh_context.request_tracker = request_tracker

        mock_client.chat.completions.create.side_effect = [
            _timeout_error(),
            _make_response(content="recovered", prompt_tokens=1000, completion_tokens=200),
        ]

        text, _ = _completion_inner("claude-sonnet-4-6", MSGS)

        assert text == "recovered"
        # The per-request tracker and the emitted event both come from closures over ctx.
        assert request_tracker.calls == 1
        assert request_tracker.total_prompt_tokens == 1000
        assert request_tracker.details[0]["attempts"] == 2
        assert len(events) == 1
        assert events[0]["phase"] == "classify"
        assert events[0]["content_hash"] == "deadbeef"
        assert events[0]["model"] == "claude-sonnet-4-6"
        assert events[0]["tokens_completion"] == 200
        assert events[0]["cost_usd"] > 0

    def test_cancel_event_checked_between_retries(self, mock_client, no_sleep, fresh_context):
        cancel = threading.Event()

        def _fail_then_cancel(**kwargs):
            cancel.set()
            raise _timeout_error()

        mock_client.chat.completions.create.side_effect = _fail_then_cancel
        fresh_context.cancel_event = cancel

        with pytest.raises(PipelineCancelledError, match="cancelled"):
            _completion_inner("model", MSGS)

        # First attempt runs, backoff happens, then the loop notices the cancel.
        assert mock_client.chat.completions.create.call_count == 1
        assert no_sleep == [completion_mod._TIMEOUT_BACKOFF_BASE]


class TestAdaptiveCacheBookkeeping:
    """_completion_inner feeds cache hit/miss results back into _cache_state."""

    def test_cache_miss_is_recorded_and_prompt_is_marked(self, mock_client, cache_state):
        mock_client.chat.completions.create.return_value = _make_response(
            cached_tokens=0, cache_created_tokens=0
        )
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Hi"}]

        _completion_inner("model", messages, cache=True)

        assert cache_state.consecutive_misses == 1
        sent = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert sent[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert sent[1] == {"role": "user", "content": "Hi"}

    def test_cache_hit_resets_miss_counter(self, mock_client, cache_state):
        mock_client.chat.completions.create.return_value = _make_response(
            cached_tokens=0, cache_created_tokens=0
        )
        _completion_inner("model", MSGS, cache=True)
        assert cache_state.consecutive_misses == 1

        mock_client.chat.completions.create.return_value = _make_response(cached_tokens=64)
        _completion_inner("model", MSGS, cache=True)

        assert cache_state.consecutive_misses == 0

    def test_cache_disabled_by_caller_is_not_recorded(self, mock_client, cache_state):
        mock_client.chat.completions.create.return_value = _make_response(
            cached_tokens=0, cache_created_tokens=0
        )

        _completion_inner("model", MSGS, cache=False)

        assert cache_state.consecutive_misses == 0
        # Untouched messages are forwarded verbatim when caching is off.
        assert mock_client.chat.completions.create.call_args.kwargs["messages"] is MSGS

    def test_missing_usage_skips_cost_recording(self, mock_client, fresh_context):
        mock_client.chat.completions.create.return_value = _make_response(usage_present=False)
        tracker = llm_pkg.CostTracker(store_details=True)
        fresh_context.request_tracker = tracker

        text, _ = _completion_inner("model", MSGS)

        assert text == "Hello world"
        assert tracker.calls == 0


class TestTruncationDeadline:
    """completion() must not start a doubled-max_tokens retry near the deadline."""

    def test_truncation_retry_blocked_by_deadline(self, mock_client, fresh_context):
        mock_client.chat.completions.create.return_value = _make_response(
            content="partial", finish_reason="length"
        )
        fresh_context.deadline_abs = time.monotonic() + 5

        with pytest.raises(DeadlineExceededError, match="deadline_too_close to retry"):
            completion("model", MSGS, max_tokens=4096)

        assert mock_client.chat.completions.create.call_count == 1

    def test_truncation_retry_allowed_with_ample_deadline(self, mock_client, fresh_context):
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length"),
            _make_response(content="complete", finish_reason="stop"),
        ]
        fresh_context.deadline_abs = time.monotonic() + 600

        assert completion("model", MSGS, max_tokens=4096) == "complete"


class TestCompletionJsonRepair:
    """completion_json falls back to json_repair for malformed model output."""

    def test_repairs_malformed_json(self, mock_client, capsys):
        mock_client.chat.completions.create.return_value = _make_response(
            content='{"key": "value", "n": 1,}'
        )

        result = completion_json("model", MSGS)

        assert result == {"key": "value", "n": 1}
        assert "[json-repair]" in capsys.readouterr().err

    def test_raises_original_error_when_repair_yields_non_dict(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(content="[1, 2")

        with pytest.raises(json.JSONDecodeError):
            completion_json("model", MSGS)

    def test_raises_original_error_when_repair_itself_fails(self, mock_client, monkeypatch):
        def _explode(*args, **kwargs):
            raise RuntimeError("repair unavailable")

        monkeypatch.setattr(json_repair, "repair_json", _explode)
        mock_client.chat.completions.create.return_value = _make_response(content="{oops")

        # The original JSONDecodeError must win -- never the repair library's error.
        with pytest.raises(json.JSONDecodeError):
            completion_json("model", MSGS)

    def test_forwards_kwargs_to_completion(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(content='{"a": 1}')

        assert completion_json("model", MSGS, temperature=0.7, max_tokens=256) == {"a": 1}

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 256


class TestPackageContextWrappers:
    """Backward-compat context accessors re-exported from kb_ai.llm."""

    def test_pipeline_deadline_roundtrip(self, fresh_context):
        llm_pkg.set_pipeline_deadline_abs(1234.5)

        assert llm_pkg._get_pipeline_deadline() == 1234.5
        assert fresh_context.deadline_abs == 1234.5

    def test_cancel_event_roundtrip(self, fresh_context):
        event = threading.Event()
        llm_pkg.set_cancel_event(event)

        assert llm_pkg._get_cancel_event() is event

        llm_pkg.set_cancel_event(None)
        assert llm_pkg._get_cancel_event() is None

    def test_call_timeout_roundtrip(self, fresh_context):
        llm_pkg.set_call_timeout(30.0)

        assert llm_pkg.get_call_timeout() == 30.0
        assert fresh_context.call_timeout == 30.0

        llm_pkg.set_call_timeout(None)
        assert llm_pkg.get_call_timeout() is None

    def test_call_emit_roundtrip(self, fresh_context):
        events: list[dict] = []

        def _emit(event):
            events.append(event)

        llm_pkg.set_call_emit(_emit)

        assert llm_pkg.get_call_emit() is _emit
        llm_pkg.get_call_emit()({"type": "probe"})
        assert events == [{"type": "probe"}]

        llm_pkg.set_call_emit(None)
        assert llm_pkg.get_call_emit() is None

    def test_phase_context_roundtrip(self, fresh_context):
        assert llm_pkg.get_phase_context() == "unknown"

        llm_pkg.set_phase_context("extract")
        assert llm_pkg.get_phase_context() == "extract"

    def test_error_event_tags_current_phase(self, fresh_context):
        llm_pkg.set_phase_context("classify")

        assert llm_pkg.error_event("boom") == {
            "type": "error", "message": "boom", "phase": "classify"
        }

    def test_error_event_falls_back_to_unknown_phase(self, fresh_context):
        assert llm_pkg.error_event("boom")["phase"] == "unknown"

    def test_content_hash_context_roundtrip(self, fresh_context):
        assert llm_pkg.get_content_hash_context() == ""

        llm_pkg.set_content_hash_context("abc123")
        assert llm_pkg.get_content_hash_context() == "abc123"
        assert fresh_context.content_hash == "abc123"

    def test_request_tracker_roundtrip(self, fresh_context):
        tracker = llm_pkg.CostTracker(store_details=True)
        llm_pkg.set_request_tracker(tracker)

        assert llm_pkg.get_request_tracker() is tracker

        llm_pkg.set_request_tracker(None)
        assert llm_pkg.get_request_tracker() is None


class TestCacheProxyAttributes:
    """kb_ai.llm._cache_consecutive_misses / _cache_disabled proxy into _cache_state."""

    def test_reads_proxy_state_from_cache_state(self, cache_state):
        cache_state.record_result(0, 0)

        assert llm_pkg._cache_consecutive_misses == cache_state.consecutive_misses == 1
        assert llm_pkg._cache_disabled is False

    def test_writes_proxy_state_into_cache_state(self, cache_state):
        llm_pkg._cache_consecutive_misses = 7
        assert cache_state.consecutive_misses == 7

        llm_pkg._cache_disabled = True
        assert cache_state.is_disabled is True
        assert cache_state.should_use_cache(True) is False

        llm_pkg._cache_disabled = False
        assert cache_state.is_enabled is True

    def test_unknown_attribute_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="has no attribute '_nope'"):
            llm_pkg._nope

    def test_ordinary_attribute_assignment_still_works(self):
        llm_pkg._probe_attr = "kept"
        try:
            assert llm_pkg._probe_attr == "kept"
        finally:
            del llm_pkg._probe_attr
