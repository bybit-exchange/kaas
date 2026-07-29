"""Tests for context propagation to workers via contextual_submit.

Verifies that ThreadContext (deadline_abs, cancel_event, phase, etc.) is
correctly propagated to worker threads when using contextual_submit().
This is the core correctness guarantee for the atomic context switch.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from kb_ai._context import (
    ThreadContext,
    _current_context,
    contextual_submit,
    get_context,
    set_context,
    set_pipeline_deadline,
)
from kb_ai._cost import CostTracker


@pytest.fixture
def fresh_context():
    """Provide a fresh ThreadContext and reset the contextvar after the test."""
    ctx = ThreadContext()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


class TestDeadlinePropagation:
    def test_deadline_visible_in_worker(self, fresh_context):
        """Worker thread sees deadline_abs set by parent."""
        get_context().deadline_abs = 12345.0

        def worker():
            return get_context().deadline_abs

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            assert future.result(timeout=5) == 12345.0

    def test_set_pipeline_deadline_visible_in_worker(self, fresh_context):
        """Worker sees deadline set via set_pipeline_deadline()."""
        before = time.monotonic()
        set_pipeline_deadline(60.0)

        def worker():
            return get_context().deadline_abs

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            result = future.result(timeout=5)
            assert result >= before + 59.0
            assert result <= before + 61.0


class TestCancelEventPropagation:
    def test_cancel_event_shared_with_worker(self, fresh_context):
        """Worker gets the same cancel_event object as parent."""
        ev = threading.Event()
        get_context().cancel_event = ev

        def worker():
            ctx = get_context()
            return ctx.cancel_event is ev

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            assert future.result(timeout=5) is True

    def test_parent_cancels_after_submit(self, fresh_context):
        """Parent sets cancel_event after submit -- worker sees it."""
        ev = threading.Event()
        get_context().cancel_event = ev
        barrier = threading.Barrier(2, timeout=5)

        def worker():
            barrier.wait()  # wait for parent to signal
            return get_context().cancel_event.is_set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            ev.set()
            barrier.wait()  # unblock worker
            assert future.result(timeout=5) is True


class TestPhasePropagation:
    def test_phase_visible_in_worker(self, fresh_context):
        """Worker sees phase set by parent."""
        get_context().phase = "classify"

        def worker():
            return get_context().phase

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            assert future.result(timeout=5) == "classify"


class TestRequestTrackerPropagation:
    def test_tracker_shared_writes(self, fresh_context):
        """Multiple workers writing to same request_tracker via shared context."""
        req_tracker = CostTracker()
        get_context().request_tracker = req_tracker

        def worker(idx):
            ctx = get_context()
            ctx.request_tracker.record("claude-sonnet-4-6", 100, 50)
            return idx

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [contextual_submit(pool, worker, i) for i in range(4)]
            for f in futures:
                f.result(timeout=5)

        # All 4 workers should have recorded to the same tracker
        assert req_tracker.calls == 4
        assert req_tracker.total_prompt_tokens == 400


class TestCallEmitPropagation:
    def test_emit_visible_in_worker(self, fresh_context):
        """Worker can call emit function set by parent."""
        events = []
        get_context().call_emit = events.append

        def worker():
            ctx = get_context()
            ctx.call_emit({"test": True})

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            future.result(timeout=5)

        assert events == [{"test": True}]


class TestFullPipelineContextPropagation:
    def test_all_fields_propagated(self, fresh_context):
        """All ThreadContext fields are visible in worker thread."""
        ev = threading.Event()
        tracker = CostTracker()
        emit_fn = lambda e: None

        parent_ctx = get_context()
        parent_ctx.deadline_abs = 99999.0
        parent_ctx.cancel_event = ev
        parent_ctx.call_timeout = 30.0
        parent_ctx.call_emit = emit_fn
        parent_ctx.phase = "write"
        parent_ctx.content_hash = "abc123"
        parent_ctx.request_tracker = tracker

        def worker():
            ctx = get_context()
            return {
                "deadline_abs": ctx.deadline_abs,
                "cancel_event_is_same": ctx.cancel_event is ev,
                "call_timeout": ctx.call_timeout,
                "call_emit_is_same": ctx.call_emit is emit_fn,
                "phase": ctx.phase,
                "content_hash": ctx.content_hash,
                "tracker_is_same": ctx.request_tracker is tracker,
            }

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            result = future.result(timeout=5)

        assert result["deadline_abs"] == 99999.0
        assert result["cancel_event_is_same"] is True
        assert result["call_timeout"] == 30.0
        assert result["call_emit_is_same"] is True
        assert result["phase"] == "write"
        assert result["content_hash"] == "abc123"
        assert result["tracker_is_same"] is True
