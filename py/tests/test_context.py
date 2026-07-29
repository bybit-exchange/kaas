"""Tests for kb_ai._context module."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from kb_ai._context import (
    ThreadContext,
    _current_context,
    cancellable,
    contextual_submit,
    get_context,
    set_context,
    set_pipeline_deadline,
    set_pipeline_deadline_abs,
)
from kb_ai._cost import CostTracker


# ── ThreadContext dataclass ────────────────────────────────────────────

class TestThreadContext:
    def test_defaults(self):
        ctx = ThreadContext()
        assert ctx.deadline_abs == 0.0
        assert ctx.cancel_event is None
        assert ctx.call_timeout is None
        assert ctx.call_emit is None
        assert ctx.phase == "unknown"
        assert ctx.content_hash == ""
        assert ctx.request_tracker is None

    def test_custom_fields(self):
        ev = threading.Event()
        tracker = CostTracker()
        emit_fn = lambda e: None
        ctx = ThreadContext(
            deadline_abs=100.0,
            cancel_event=ev,
            call_timeout=30.0,
            call_emit=emit_fn,
            phase="classify",
            content_hash="abc123",
            request_tracker=tracker,
        )
        assert ctx.deadline_abs == 100.0
        assert ctx.cancel_event is ev
        assert ctx.call_timeout == 30.0
        assert ctx.call_emit is emit_fn
        assert ctx.phase == "classify"
        assert ctx.content_hash == "abc123"
        assert ctx.request_tracker is tracker


# ── get_context / set_context ──────────────────────────────────────────

class TestGetSetContext:
    def test_get_context_creates_default(self, fresh_context):
        # fresh_context fixture sets a fresh context; get_context returns it
        ctx = get_context()
        assert isinstance(ctx, ThreadContext)

    def test_get_context_returns_same_instance(self, fresh_context):
        ctx1 = get_context()
        ctx2 = get_context()
        assert ctx1 is ctx2

    def test_set_context_replaces(self, fresh_context):
        new_ctx = ThreadContext(phase="extract")
        set_context(new_ctx)
        assert get_context().phase == "extract"
        assert get_context() is new_ctx


# ── set_pipeline_deadline ──────────────────────────────────────────────

class TestSetPipelineDeadline:
    def test_sets_deadline_relative(self, fresh_context):
        before = time.monotonic()
        set_pipeline_deadline(60.0)
        ctx = get_context()
        assert ctx.deadline_abs >= before + 59.0
        assert ctx.deadline_abs <= before + 61.0

    def test_none_clears_deadline(self, fresh_context):
        set_pipeline_deadline(60.0)
        set_pipeline_deadline(None)
        assert get_context().deadline_abs == 0.0

    def test_set_absolute(self, fresh_context):
        set_pipeline_deadline_abs(12345.0)
        assert get_context().deadline_abs == 12345.0


# ── cancellable ────────────────────────────────────────────────────────

class TestCancellable:
    def test_sets_and_clears_cancel_event(self, fresh_context):
        ev = threading.Event()
        assert get_context().cancel_event is None
        with cancellable(ev):
            assert get_context().cancel_event is ev
        assert get_context().cancel_event is None

    def test_clears_on_exception(self, fresh_context):
        ev = threading.Event()
        with pytest.raises(ValueError):
            with cancellable(ev):
                raise ValueError("boom")
        assert get_context().cancel_event is None

    def test_none_is_valid(self, fresh_context):
        with cancellable(None):
            assert get_context().cancel_event is None


# ── contextual_submit ──────────────────────────────────────────────────

class TestContextualSubmit:
    def test_propagates_context_to_worker(self, fresh_context):
        """Worker thread sees the same ThreadContext as parent."""
        parent_ctx = get_context()
        parent_ctx.phase = "test_phase"
        parent_ctx.deadline_abs = 999.0
        parent_ctx.content_hash = "hash123"

        results = {}

        def worker():
            ctx = get_context()
            results["phase"] = ctx.phase
            results["deadline_abs"] = ctx.deadline_abs
            results["content_hash"] = ctx.content_hash
            results["is_same"] = ctx is parent_ctx

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = contextual_submit(executor, worker)
            future.result(timeout=5)

        assert results["phase"] == "test_phase"
        assert results["deadline_abs"] == 999.0
        assert results["content_hash"] == "hash123"
        assert results["is_same"] is True

    def test_cancel_event_shared(self, fresh_context):
        """Cancel event is shared: parent can signal child."""
        ev = threading.Event()
        get_context().cancel_event = ev

        def worker():
            ctx = get_context()
            return ctx.cancel_event is ev

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = contextual_submit(executor, worker)
            assert future.result(timeout=5) is True

    def test_request_tracker_shared(self, fresh_context):
        """Request tracker is shared: child records to same tracker."""
        tracker = CostTracker()
        get_context().request_tracker = tracker

        def worker():
            ctx = get_context()
            ctx.request_tracker.record("claude-sonnet-4-6", 100, 50)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = contextual_submit(executor, worker)
            future.result(timeout=5)

        assert tracker.calls == 1
        assert tracker.total_prompt_tokens == 100

    def test_worker_function_args_passed(self, fresh_context):
        """Arguments to fn are correctly forwarded."""
        def add(a, b):
            return a + b

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = contextual_submit(executor, add, 3, 7)
            assert future.result(timeout=5) == 10

    def test_worker_function_kwargs_passed(self, fresh_context):
        """Keyword arguments to fn are correctly forwarded."""
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = contextual_submit(executor, greet, "world", greeting="hi")
            assert future.result(timeout=5) == "hi world"

    def test_multiple_workers_see_same_context(self, fresh_context):
        """Multiple concurrent workers all see the parent context."""
        parent_ctx = get_context()
        parent_ctx.phase = "parallel_phase"

        results = []
        lock = threading.Lock()

        def worker(idx):
            ctx = get_context()
            with lock:
                results.append((idx, ctx.phase, ctx is parent_ctx))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [contextual_submit(executor, worker, i) for i in range(4)]
            for f in futures:
                f.result(timeout=5)

        assert len(results) == 4
        for idx, phase, is_same in results:
            assert phase == "parallel_phase"
            assert is_same is True
