"""Tests for kb_ai.llm._completion module."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

import kb_ai.llm as llm_pkg
from kb_ai._errors import (
    DeadlineExceededError,
    EmptyCompletionError,
    LLMTimeoutError,
    OutputTruncatedError,
    PipelineCancelledError,
    PromptTooLargeError,
)
from kb_ai.llm._completion import (
    _CONTINUATION_MAX,
    _CONTINUATION_USER,
    _completion_inner,
    _dedup_overlap,
    completion,
    completion_json,
    estimate_max_tokens,
)


def _make_response(content="Hello world", finish_reason="stop", prompt_tokens=100,
                   completion_tokens=50, cached_tokens=20):
    """Build a mock OpenAI response."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=cached_tokens, cache_creation_tokens=0
        ),
        model_dump=lambda: {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_read_input_tokens": cached_tokens,
        },
    )
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _status_error(status_code: int, message: str = "boom") -> APIStatusError:
    """Build a real openai.APIStatusError carrying the given HTTP status."""
    request = httpx.Request("POST", "http://test:8080/v1/chat/completions")
    return APIStatusError(message, response=httpx.Response(status_code, request=request), body=None)


def _timeout_error() -> APITimeoutError:
    """Build a real openai.APITimeoutError for the same test endpoint."""
    return APITimeoutError(httpx.Request("POST", "http://test:8080/v1/chat/completions"))


@pytest.fixture
def mock_client():
    """Create a mock OpenAI client and patch get_client."""
    client = MagicMock()
    client.base_url = "http://test:8080/v1"
    client.chat.completions.create.return_value = _make_response()
    with patch.object(llm_pkg, "get_client", return_value=client):
        yield client


class TestCompletionInner:
    """Tests for _completion_inner."""

    def test_basic_call(self, mock_client):
        text, reason, tokens = _completion_inner("test-model", [{"role": "user", "content": "Hi"}])
        assert text == "Hello world"
        assert reason == "stop"
        assert tokens == 50
        mock_client.chat.completions.create.assert_called_once()

    def test_returns_raw_text_unstripped(self, mock_client):
        # The single terminal strip lives at completion()'s return boundary, so
        # continuation seams keep their whitespace; _completion_inner must not
        # strip. (3-tuple: the token count is only available where usage is
        # parsed — text-length estimates are wrong for reasoning models.)
        mock_client.chat.completions.create.return_value = _make_response(content="  padded  ")
        text, _, _ = _completion_inner("model", [{"role": "user", "content": "Hi"}])
        assert text == "  padded  "

    def test_prompt_too_large_raises(self, mock_client):
        big_content = "x" * (llm_pkg.MAX_PROMPT_CHARS + 1)
        with pytest.raises(PromptTooLargeError, match="prompt_too_large"):
            _completion_inner("model", [{"role": "user", "content": big_content}])

    def test_cancel_event_raises(self, mock_client):
        cancel = threading.Event()
        cancel.set()
        llm_pkg.set_cancel_event(cancel)
        try:
            with pytest.raises(PipelineCancelledError, match="cancelled"):
                _completion_inner("model", [{"role": "user", "content": "Hi"}])
        finally:
            llm_pkg.set_cancel_event(None)


class TestReasoningEffortPassthrough:
    """KB_AI_REASONING_EFFORT passthrough + the 400-strip-retry-disable degrade."""

    def test_env_knob_sent_in_request_kwargs(self, mock_client, monkeypatch):
        # The knob is process-wide by design: when set, every call carries it.
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        completion("model", [{"role": "user", "content": "Hi"}])
        assert mock_client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"

    def test_unset_knob_leaves_request_kwargs_byte_identical(self, mock_client):
        # Default is zero change: no param key at all unless configured
        # (conftest deletes ambient operator values).
        completion("model", [{"role": "user", "content": "Hi"}])
        assert "reasoning_effort" not in mock_client.chat.completions.create.call_args.kwargs

    def test_explicit_kwarg_wins_over_env(self, mock_client, monkeypatch):
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        _completion_inner("model", [{"role": "user", "content": "Hi"}],
                          reasoning_effort="minimal")
        sent = mock_client.chat.completions.create.call_args.kwargs
        assert sent["reasoning_effort"] == "minimal"

    def test_400_strips_retries_once_and_disables_for_process(
            self, mock_client, monkeypatch, capsys):
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        mock_client.chat.completions.create.side_effect = [
            _status_error(400, "Unknown parameter: 'reasoning_effort'"),
            _make_response(content="recovered", finish_reason="stop"),
        ]

        result = completion("model", [{"role": "user", "content": "Hi"}])

        assert result == "recovered"
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[0].kwargs["reasoning_effort"] == "low"
        assert "reasoning_effort" not in calls[1].kwargs
        err = capsys.readouterr().err
        assert "[LLM-WARN] reasoning_effort_unsupported:" in err
        # The degrade owns the alert; the generic http_400 kind must not fire too.
        assert "http_400:" not in err

        # Process-lifetime disable: with the knob still exported, the next call
        # omits the param without needing another 400 to teach it.
        mock_client.chat.completions.create.reset_mock()
        mock_client.chat.completions.create.side_effect = None
        completion("model", [{"role": "user", "content": "Hi"}])
        assert "reasoning_effort" not in mock_client.chat.completions.create.call_args.kwargs

    def test_400_unrelated_to_the_param_is_not_blamed_on_it(
            self, mock_client, monkeypatch, capsys):
        # A generic 400 while the param was sent is ambiguous: the probe (one
        # retry without the param) also 400s, so the error raises with the
        # knob intact -- no process-wide disable over someone else's 400.
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        mock_client.chat.completions.create.side_effect = _status_error(
            400, "model `nope` not found")

        with pytest.raises(APIStatusError):
            completion("model", [{"role": "user", "content": "Hi"}])

        calls = mock_client.chat.completions.create.call_args_list
        assert len(calls) == 2  # the initial 400 plus one probe without the param
        assert calls[0].kwargs["reasoning_effort"] == "low"
        assert "reasoning_effort" not in calls[1].kwargs
        err = capsys.readouterr().err
        assert "reasoning_effort_unsupported" not in err
        assert "http_400:" in err

        # The knob survives: the disable flag was not flipped by the blame.
        mock_client.chat.completions.create.reset_mock()
        mock_client.chat.completions.create.side_effect = None
        completion("model", [{"role": "user", "content": "Hi"}])
        assert mock_client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"

    def test_generic_400_probes_once_and_disables_only_on_success(
            self, mock_client, monkeypatch, capsys):
        # Some gateways refuse unknown fields without naming them. The probe
        # succeeds without the param, which pins the blame on it: alert +
        # process-wide disable, the same end state as the named-body refusal.
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        mock_client.chat.completions.create.side_effect = [
            _status_error(400, "invalid request"),
            _make_response(content="recovered", finish_reason="stop"),
        ]

        result = completion("model", [{"role": "user", "content": "Hi"}])

        assert result == "recovered"
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[0].kwargs["reasoning_effort"] == "low"
        assert "reasoning_effort" not in calls[1].kwargs
        err = capsys.readouterr().err
        assert "reasoning_effort_unsupported" in err
        assert "generic 400" in err

        mock_client.chat.completions.create.reset_mock()
        mock_client.chat.completions.create.side_effect = None
        completion("model", [{"role": "user", "content": "Hi"}])
        assert "reasoning_effort" not in mock_client.chat.completions.create.call_args.kwargs

    def test_probe_interrupted_by_timeout_keeps_the_knob(
            self, mock_client, monkeypatch, capsys):
        # The probe's own request timed out and the ladder retry succeeded:
        # that success is not evidence about the param (the param was already
        # stripped for the whole in-flight attempt sequence), so the knob
        # stays enabled for the process and no unsupported-alert fires. Only
        # a probe that succeeds outright disables it.
        monkeypatch.setenv("KB_AI_REASONING_EFFORT", "low")
        monkeypatch.setattr("kb_ai.llm._completion._TIMEOUT_BACKOFF_BASE", 0)
        mock_client.chat.completions.create.side_effect = [
            _status_error(400, "invalid request"),
            _timeout_error(),
            _make_response(content="recovered", finish_reason="stop"),
        ]

        result = completion("model", [{"role": "user", "content": "Hi"}])

        assert result == "recovered"
        assert "reasoning_effort_unsupported" not in capsys.readouterr().err
        calls = mock_client.chat.completions.create.call_args_list
        assert "reasoning_effort" in calls[0].kwargs      # the original 400
        assert "reasoning_effort" not in calls[1].kwargs  # the probe
        assert "reasoning_effort" not in calls[2].kwargs  # ladder retry (param already stripped)

        # The process state is what matters: the next call still carries it.
        mock_client.chat.completions.create.reset_mock()
        mock_client.chat.completions.create.side_effect = None
        completion("model", [{"role": "user", "content": "Hi"}])
        assert mock_client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"


class TestBatchDeadlineClamp:
    """The batch deadline clamps every per-request HTTP timeout to what
    remains, so a pipeline call cannot outrun its deadline by a full
    write-timeout ladder while the Go-side batch watchdog then kills it as
    wedged and its orphaned daemon request keeps running and writing."""

    def setup_method(self):
        llm_pkg.set_pipeline_deadline(None)
        llm_pkg.set_call_timeout(None)

    def teardown_method(self):
        llm_pkg.set_pipeline_deadline(None)
        llm_pkg.set_call_timeout(None)

    def test_no_deadline_sends_no_per_request_timeout(self, mock_client):
        _completion_inner("model", [{"role": "user", "content": "Hi"}])
        assert "timeout" not in mock_client.chat.completions.create.call_args.kwargs

    def test_deadline_clamps_to_the_remainder(self, mock_client):
        llm_pkg.set_pipeline_deadline(5)
        _completion_inner("model", [{"role": "user", "content": "Hi"}])
        got = mock_client.chat.completions.create.call_args.kwargs["timeout"]
        assert got == pytest.approx(5, abs=1)

    def test_deadline_never_tightens_below_the_call_timeout_override(self, mock_client):
        mock_client.with_options = MagicMock(return_value=mock_client)
        llm_pkg.set_call_timeout(2)
        llm_pkg.set_pipeline_deadline(500)
        _completion_inner("model", [{"role": "user", "content": "Hi"}])
        assert mock_client.with_options.call_args.kwargs["timeout"] == 2
        assert mock_client.chat.completions.create.call_args.kwargs["timeout"] == 2

    def test_deadline_clamps_a_longer_override(self, mock_client):
        mock_client.with_options = MagicMock(return_value=mock_client)
        llm_pkg.set_call_timeout(300)
        llm_pkg.set_pipeline_deadline(5)
        _completion_inner("model", [{"role": "user", "content": "Hi"}])
        assert mock_client.with_options.call_args.kwargs["timeout"] == 300
        got = mock_client.chat.completions.create.call_args.kwargs["timeout"]
        assert got == pytest.approx(5, abs=1)

    def test_retry_recomputes_the_timeout_from_the_shrunk_deadline(
            self, mock_client, monkeypatch):
        # The clamp is per attempt: a timeout retry after the deadline shrank
        # must carry the new remainder, not the first attempt's frozen value
        # (which could outrun the deadline by a whole write ladder, past the
        # caller's watchdog margin).
        monkeypatch.setattr("kb_ai.llm._completion._TIMEOUT_BACKOFF_BASE", 0)
        attempts: list[float | None] = []

        def flaky(**kwargs):
            attempts.append(kwargs.get("timeout"))
            if len(attempts) == 1:
                llm_pkg.set_pipeline_deadline_abs(time.monotonic() + 120)
                raise _timeout_error()
            return _make_response(content="recovered")

        mock_client.chat.completions.create.side_effect = flaky
        llm_pkg.set_pipeline_deadline(800)

        text, finish_reason, _ = _completion_inner("model", [{"role": "user", "content": "Hi"}])

        assert text == "recovered" and finish_reason == "stop"
        assert attempts[0] == pytest.approx(800, abs=5)
        assert attempts[1] == pytest.approx(120, abs=5)

    def test_passed_deadline_fails_before_the_call(self, mock_client):
        llm_pkg.set_pipeline_deadline_abs(time.monotonic() - 1)
        with pytest.raises(DeadlineExceededError, match="deadline_too_close"):
            _completion_inner("model", [{"role": "user", "content": "Hi"}])
        mock_client.chat.completions.create.assert_not_called()


class TestCompletion:
    """Tests for the completion wrapper."""

    def test_returns_text(self, mock_client):
        result = completion("test-model", [{"role": "user", "content": "Hi"}])
        assert result == "Hello world"

    def test_empty_body_retried_once_then_succeeds(self, mock_client, capsys):
        # Reasoning-style models can stop with finish=stop and content="" —
        # the whole answer stayed in the reasoning channel. One retry.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="", finish_reason="stop", completion_tokens=1266),
            _make_response(content="real answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}])
        assert result == "real answer"
        assert mock_client.chat.completions.create.call_count == 2
        assert "[empty-completion]" in capsys.readouterr().err

    def test_empty_body_twice_raises(self, mock_client):
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="", finish_reason="stop"),
            _make_response(content="", finish_reason="stop"),
        ]
        with pytest.raises(EmptyCompletionError):
            completion("model", [{"role": "user", "content": "Hi"}])

    def test_empty_body_then_truncated_falls_into_ladder(self, mock_client):
        # The retry may come back truncated; the normal restart ladder owns it.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="", finish_reason="stop"),
            _make_response(content="partial", finish_reason="length"),
            _make_response(content="full answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
        assert result == "full answer"

    def test_retries_on_truncation(self, mock_client):
        # First call truncated, second succeeds
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length"),
            _make_response(content="full answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
        assert result == "full answer"
        # Second call should have doubled max_tokens
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[0].kwargs["max_tokens"] == 4096
        assert calls[1].kwargs["max_tokens"] == 8192

    def test_raises_on_ceiling(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            finish_reason="length"
        )
        with pytest.raises(OutputTruncatedError, match="truncated at ceiling"):
            completion("model", [{"role": "user", "content": "Hi"}], max_tokens=64000)

    def test_strips_raw_text_at_return_boundary(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(content="  padded  ")
        assert completion("model", [{"role": "user", "content": "Hi"}]) == "padded"

    def test_variant_finish_reasons_enter_restart_ladder(self, mock_client):
        # BUG-2(a): gateways spell the length-cut differently; the old exact
        # "length" comparison let these bypass the ladder and return mangled
        # text to callers.
        for variant in ("max_tokens", "MAX_OUTPUT_TOKENS", "Length"):
            mock_client.chat.completions.create.side_effect = [
                _make_response(content="partial", finish_reason=variant),
                _make_response(content="full answer", finish_reason="stop"),
            ]
            result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
            assert result == "full answer"
            calls = mock_client.chat.completions.create.call_args_list
            assert calls[0].kwargs["max_tokens"] == 4096
            assert calls[1].kwargs["max_tokens"] == 8192
            mock_client.chat.completions.create.reset_mock()

    def test_non_truncation_reasons_return_immediately(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            content="full answer", finish_reason="tool_calls"
        )
        assert completion("model", [{"role": "user", "content": "Hi"}]) == "full answer"
        assert mock_client.chat.completions.create.call_count == 1

    def test_restart_alert_carries_discarded_tokens(self, mock_client, capsys):
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length",
                           completion_tokens=5000),
            _make_response(content="full answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
        assert result == "full answer"

        err = capsys.readouterr().err
        assert "[LLM-WARN] output_truncated_restart:" in err
        assert "discarded_tokens=5000" in err
        # The .bench/-regexed restart line is preserved byte-for-byte.
        assert "  [truncated] max_tokens=4096 hit, retrying with 8192\n" in err

    def test_restart_alert_discarded_falls_back_to_cap_without_usage(self, mock_client, capsys):
        # Usage parses to 0 completion tokens when absent; the alert then
        # estimates the discard as the cap that was hit.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length",
                           completion_tokens=0),
            _make_response(content="full answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
        assert result == "full answer"
        assert "discarded_tokens=4096" in capsys.readouterr().err

    def test_continue_on_length_keyword_accepted(self, mock_client):
        # The opt-in flag is inert without truncation: one call, stripped text.
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "Hello world"
        assert mock_client.chat.completions.create.call_count == 1


class TestContinuationMode:
    """continue_on_length=True: keep truncated partials instead of discarding."""

    def test_concatenates_partial_and_sends_raw_assistant_seam(self, mock_client):
        # The second call's messages carry the RAW partial as an assistant
        # message plus the verbatim continue instruction (seam contract), and
        # the grant matches the previous round's size (no doubling).
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="first part ", finish_reason="length"),
            _make_response(content="second part", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "first part second part"
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[1].kwargs["max_tokens"] == 4096
        assert calls[1].kwargs["messages"] == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "first part "},
            {"role": "user", "content": _CONTINUATION_USER},
        ]

    def test_accumulates_across_rounds(self, mock_client):
        # Round 3 sees the full accumulated assistant text, not just chunk 2.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="part one ", finish_reason="length"),
            _make_response(content="part two ", finish_reason="length"),
            _make_response(content="part three", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "part one part two part three"
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[2].kwargs["messages"][1] == {
            "role": "assistant", "content": "part one part two "
        }

    def test_seam_whitespace_and_indentation_survive_verbatim(self, mock_client):
        # A chunk beginning with indentation must neither fuse onto the
        # previous line nor lose its leading whitespace — only the single
        # terminal strip may touch whitespace.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="# Title\n\nBody line one\n", finish_reason="length"),
            _make_response(content="    - indented item\n  continued", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "# Title\n\nBody line one\n    - indented item\n  continued"

    def test_true_seam_overlap_is_deduped(self, mock_client):
        # The model repeats the tail of chunk 1; only the exact overlap goes.
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="The quick brown fox", finish_reason="length"),
            _make_response(content="brown fox jumps over the dog", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "The quick brown fox jumps over the dog"

    def test_alert_and_stderr_line(self, mock_client, capsys):
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length",
                           completion_tokens=4096),
            _make_response(content=" more", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}],
                            max_tokens=4096, continue_on_length=True)
        assert result == "partial more"
        err = capsys.readouterr().err
        assert "[LLM-WARN] output_truncated_continue:" in err
        assert "discarded_tokens=0" in err
        assert "kept_tokens=4096" in err
        # The .bench/-regexed continuing line is preserved byte-for-byte.
        assert "  [truncated] max_tokens=4096 hit, continuing with 4096\n" in err

    def test_grant_exhausted_at_ceiling_raises_immediately(self, mock_client):
        # First rung already at the ceiling: granted accounting leaves nothing
        # to grant, so the kept partial cannot be extended.
        mock_client.chat.completions.create.return_value = _make_response(
            content="chunk", finish_reason="length"
        )
        with pytest.raises(OutputTruncatedError, match="truncated at ceiling"):
            completion("model", [{"role": "user", "content": "Hi"}],
                       max_tokens=64000, continue_on_length=True)
        assert mock_client.chat.completions.create.call_count == 1

    def test_max_continuations_exhausted_raises(self, mock_client):
        # First call + _CONTINUATION_MAX truncated rounds: the 4th continuation
        # would be needed -> OutputTruncatedError.
        mock_client.chat.completions.create.return_value = _make_response(
            content="chunk", finish_reason="length"
        )
        with pytest.raises(OutputTruncatedError, match="continuations"):
            completion("model", [{"role": "user", "content": "Hi"}],
                       max_tokens=4096, continue_on_length=True)
        assert mock_client.chat.completions.create.call_count == 1 + _CONTINUATION_MAX

    def test_continuation_blocked_by_deadline(self, mock_client, fresh_context):
        mock_client.chat.completions.create.return_value = _make_response(
            content="partial", finish_reason="length"
        )
        fresh_context.deadline_abs = time.monotonic() + 5
        with pytest.raises(DeadlineExceededError, match="deadline_too_close to continue"):
            completion("model", [{"role": "user", "content": "Hi"}],
                       max_tokens=4096, continue_on_length=True)
        assert mock_client.chat.completions.create.call_count == 1


class TestEstimateMaxTokens:
    """estimate_max_tokens: ceil(chars*0.75)+headroom, clamped to [minimum, ceiling]."""

    def test_formula_with_default_headroom(self):
        assert estimate_max_tokens(10_000) == 23_884  # ceil(7500) + 16384

    def test_fractional_chars_round_up(self):
        assert estimate_max_tokens(101, minimum=0, ceiling=100_000, headroom=0) == 76
        assert estimate_max_tokens(100, minimum=0, ceiling=100_000, headroom=0) == 75

    def test_clamps_to_minimum(self):
        assert estimate_max_tokens(100, minimum=4096, headroom=0) == 4096

    def test_clamps_to_ceiling(self):
        assert estimate_max_tokens(1_000_000) == llm_pkg._MAX_TOKENS_CEILING

    def test_monotonic_across_sizes(self):
        sizes = [0, 1, 7, 100, 101, 4096, 10_000, 50_000, 100_000, 1_000_000]
        values = [estimate_max_tokens(n) for n in sizes]
        assert values == sorted(values)

    def test_custom_bounds(self):
        assert estimate_max_tokens(1_000, minimum=10, ceiling=200, headroom=10) == 200
        assert estimate_max_tokens(1_000, minimum=1_000, ceiling=100_000, headroom=0) == 1_000

    def test_reexported_from_kb_ai_llm(self):
        assert llm_pkg.estimate_max_tokens is estimate_max_tokens


class TestDedupOverlap:
    """_dedup_overlap: raw concatenation minus true seam repetition only."""

    def test_concatenates_disjoint_chunks_verbatim(self):
        assert _dedup_overlap("abc", "def") == "abcdef"

    def test_drops_exact_overlap_once(self):
        assert _dedup_overlap("hello wor", "world") == "hello world"

    def test_keeps_leading_whitespace_and_indentation(self):
        chunk = "\n    - indented item"
        assert _dedup_overlap("line one", chunk) == "line one" + chunk

    def test_overlap_scan_is_bounded(self):
        # The true overlap "def" is 3 chars; with the scan bound at 2 it is
        # beyond the scan and nothing is removed — the dedup never reaches
        # further back into `acc` than max_chars.
        assert _dedup_overlap("abcdef", "defxyz", max_chars=2) == "abcdefdefxyz"
        # An overlap the default bound (2048) can fully see is removed: a
        # model that re-emits a long block (a table, a list) must not have
        # the repeat silently persisted as duplicated text.
        assert _dedup_overlap("a" * 256, "a" * 256 + "b") == "a" * 256 + "b"
        assert _dedup_overlap("ab" * 1024, "ab" * 1024 + "tail") == "ab" * 1024 + "tail"

    def test_empty_sides(self):
        assert _dedup_overlap("", "x") == "x"
        assert _dedup_overlap("x", "") == "x"


class TestContinuationConstant:
    """_CONTINUATION_USER is sent verbatim by the continuation branch (seam
    contract text, not free-form)."""

    def test_instruction_text_is_stable(self):
        assert _CONTINUATION_USER.startswith(
            "Continue exactly where the previous message stopped."
        )


class TestCompletionJson:
    """Tests for completion_json."""

    def test_parses_json(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            content='{"key": "value"}'
        )
        result = completion_json("model", [{"role": "user", "content": "Hi"}])
        assert result == {"key": "value"}

    def test_strips_markdown_fences(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            content='```json\n{"key": "value"}\n```'
        )
        result = completion_json("model", [{"role": "user", "content": "Hi"}])
        assert result == {"key": "value"}

    def test_rejects_continue_on_length(self, mock_client):
        # JSON cannot be stitched mid-object; a caller asking for JSON
        # continuation has a design error worth surfacing (raises before any
        # call is issued).
        with pytest.raises(ValueError, match="continue_on_length"):
            completion_json("model", [{"role": "user", "content": "Hi"}],
                            continue_on_length=True)
        assert mock_client.chat.completions.create.call_count == 0
