"""Tests for context propagation to workers via contextual_submit.

Verifies that ThreadContext (deadline_abs, cancel_event, phase, etc.) is
correctly propagated to worker threads when using contextual_submit().
This is the core correctness guarantee for the atomic context switch.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields

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
        """Every ThreadContext field is visible in the worker thread.

        The values are keyed by field name and checked against the dataclass, so a
        field added to ThreadContext without a value here fails this test instead
        of leaving it quietly claiming more coverage than it has -- which is what
        happened when alert_sink was added.
        """
        values = {
            "deadline_abs": 99999.0,
            "cancel_event": threading.Event(),
            "call_timeout": 30.0,
            "call_emit": lambda e: None,
            "phase": "write",
            "content_hash": "abc123",
            "request_tracker": CostTracker(),
            "alert_sink": lambda msg: None,
        }
        assert set(values) == {f.name for f in fields(ThreadContext)}, (
            "a ThreadContext field has no value here, so this test is no longer "
            "checking every field"
        )

        parent_ctx = get_context()
        for name, value in values.items():
            setattr(parent_ctx, name, value)

        def worker():
            ctx = get_context()
            return {name: getattr(ctx, name) for name in values}

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = contextual_submit(pool, worker)
            result = future.result(timeout=5)

        for name, value in values.items():
            # Identity, not equality: contextual_submit hands over the parent's own
            # object, and every mutable field here is useful only if it is that one.
            assert result[name] is value, f"{name} was not propagated to the worker"
