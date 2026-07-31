"""Tests for kb_ai.llm._cost_record.record_cost.

Covers the three sinks record_cost writes to: the process-level tracker, the
per-request tracker, and the per-call SSE event emitted through call_emit.
"""

from __future__ import annotations

import pytest

from kb_ai._cost import CostTracker, estimate_cost
from kb_ai.llm._cost_record import record_cost
from kb_ai.llm._infra import UsageInfo

USAGE = UsageInfo(
    prompt_tokens=1000, completion_tokens=200, cached_tokens=400, cache_created_tokens=0
)


def _record(*, usage=USAGE, model="claude-sonnet-4-6", duration_s=1.5, attempts=1,
            global_tracker=None, phase="extract", content_hash="hash-1",
            call_emit=None, request_tracker=None) -> tuple[float, CostTracker]:
    """Call record_cost with simple stub accessors. Returns (cost, global_tracker)."""
    global_tracker = global_tracker if global_tracker is not None else CostTracker(
        store_details=True
    )
    cost = record_cost(
        model=model,
        usage=usage,
        duration_s=duration_s,
        attempts=attempts,
        global_tracker=global_tracker,
        get_phase_context=lambda: phase,
        get_content_hash_context=lambda: content_hash,
        get_call_emit=lambda: call_emit,
        get_request_tracker=lambda: request_tracker,
    )
    return cost, global_tracker


class TestGlobalTracker:
    """Recording into the process-level tracker."""

    def test_records_tokens_and_cost(self):
        cost, tracker = _record()

        assert cost == pytest.approx(
            estimate_cost("claude-sonnet-4-6", 1000, 200, 400)
        )
        assert cost > 0
        assert tracker.calls == 1
        assert tracker.total_prompt_tokens == 1000
        assert tracker.total_completion_tokens == 200
        assert tracker.total_cached_tokens == 400
        assert tracker.total_cost == pytest.approx(cost)

    def test_attempts_are_forwarded_to_call_details(self):
        _, tracker = _record(attempts=3)

        assert tracker.details[0]["attempts"] == 3
        assert tracker.details[0]["duration_s"] == 1.5

    def test_unknown_model_costs_zero_but_still_counts(self):
        cost, tracker = _record(model="some-local-llm")

        assert cost == 0.0
        assert tracker.calls == 1
        assert tracker.total_prompt_tokens == 1000


class TestRequestTracker:
    """Recording into the per-request tracker (when one is set)."""

    def test_records_to_both_trackers(self):
        request_tracker = CostTracker(store_details=True)

        cost, global_tracker = _record(request_tracker=request_tracker)

        assert request_tracker.calls == 1
        assert request_tracker.total_prompt_tokens == 1000
        assert request_tracker.total_completion_tokens == 200
        assert request_tracker.total_cached_tokens == 400
        assert request_tracker.total_cost == pytest.approx(cost)
        # The global tracker is not skipped when a request tracker exists.
        assert global_tracker.calls == 1

    def test_no_request_tracker_leaves_global_only(self):
        _, global_tracker = _record(request_tracker=None)

        assert global_tracker.calls == 1


class TestCallEmit:
    """The per-call llm_call event."""

    def test_emits_full_event(self):
        events: list[dict] = []

        cost, _ = _record(call_emit=events.append, duration_s=2.25)

        assert events == [{
            "type": "llm_call",
            "phase": "extract",
            "model": "claude-sonnet-4-6",
            "duration_s": 2.25,
            "tokens_prompt": 1000,
            "tokens_completion": 200,
            "tokens_cached": 400,
            "cost_usd": cost,
            "content_hash": "hash-1",
        }]

    def test_omits_content_hash_when_empty(self):
        events: list[dict] = []

        _record(call_emit=events.append, content_hash="")

        assert "content_hash" not in events[0]
        assert events[0]["phase"] == "extract"

    def test_no_emit_when_phase_unknown(self):
        events: list[dict] = []

        cost, tracker = _record(call_emit=events.append, phase="unknown")

        assert events == []
        # Cost accounting still happens without a known phase.
        assert cost > 0
        assert tracker.calls == 1

    def test_no_emit_when_callback_missing(self):
        _, tracker = _record(call_emit=None)

        assert tracker.calls == 1

    def test_emit_failure_is_swallowed(self):
        def _explode(event):
            raise RuntimeError("stream closed")

        cost, tracker = _record(call_emit=_explode)

        # A dead SSE stream must not fail the LLM call or lose the cost record.
        assert cost > 0
        assert tracker.calls == 1

    def test_content_hash_accessor_failure_is_swallowed(self):
        events: list[dict] = []

        def _boom() -> str:
            raise RuntimeError("no context")

        cost = record_cost(
            model="claude-haiku-4-5",
            usage=USAGE,
            duration_s=1.0,
            attempts=1,
            global_tracker=CostTracker(store_details=True),
            get_phase_context=lambda: "classify",
            get_content_hash_context=_boom,
            get_call_emit=lambda: events.append,
            get_request_tracker=lambda: None,
        )

        assert cost > 0
        assert events == []
