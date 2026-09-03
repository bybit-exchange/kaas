"""Tests for kb_ai.commands.pipeline._orchestrator."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from kb_ai._context import ThreadContext, _current_context, get_context, set_context
from kb_ai._cost import CostTracker
from kb_ai.commands.pipeline._orchestrator import (
    PipelineContext,
    _active_tracker,
    _build_cost_summary,
    run_pipeline_orchestrated,
)
from kb_ai.llm import tracker


@pytest.fixture
def fresh_context():
    """Provide a fresh ThreadContext and reset the contextvar after the test."""
    ctx = ThreadContext()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


class TestActiveTracker:
    def test_returns_global_when_no_request_tracker(self, fresh_context):
        assert _active_tracker() is tracker

    def test_returns_request_tracker_when_set(self, fresh_context):
        req_tracker = CostTracker()
        get_context().request_tracker = req_tracker
        assert _active_tracker() is req_tracker


class TestBuildCostSummary:
    def test_basic(self):
        delta = {"prompt": 100, "completion": 50, "cached": 20}
        result = _build_cost_summary(delta)
        assert result == {"prompt": 100, "completion": 50, "cached": 20}


class TestPipelineContext:
    def test_defaults(self):
        store = MagicMock()
        ctx = PipelineContext(store=store)
        assert ctx.model == "claude-sonnet-4-6"
        assert ctx.classify_model == ""
        assert ctx.workers == 16
        assert ctx.cancel_event is None
        assert ctx.emit is None

    def test_custom(self):
        store = MagicMock()
        ev = threading.Event()
        emit_fn = lambda e: None
        ctx = PipelineContext(
            store=store,
            model="claude-haiku-4-5",
            classify_model="claude-haiku-4-5",
            categories=["concept"],
            workers=4,
            cancel_event=ev,
            emit=emit_fn,
        )
        assert ctx.model == "claude-haiku-4-5"
        assert ctx.cancel_event is ev
        assert ctx.emit is emit_fn


class TestPhaseLlmObservability:
    """Per-call LLM lines derived from the phase tracker deltas (G1 data source)."""

    @patch("kb_ai.commands.pipeline._orchestrator.run_write_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_dedup_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_classify_phase")
    def test_write_llm_line_and_event_scalars(
        self, mock_classify, mock_dedup, mock_write, fresh_context, capsys
    ):
        req_tracker = CostTracker()
        get_context().request_tracker = req_tracker

        def record_write_calls(*args, **kwargs):
            req_tracker.record("claude-sonnet-4-6", 200, 80, duration_s=2.5)
            req_tracker.record("claude-sonnet-4-6", 300, 90, duration_s=3.5)
            return ([], 0)

        mock_classify.return_value = ([], [])
        mock_dedup.return_value = ([], 0)
        mock_write.side_effect = record_write_calls

        store = MagicMock()
        store.existing_articles.return_value = []
        events = []
        ctx = PipelineContext(store=store, emit=events.append)

        run_pipeline_orchestrated(ctx, [])

        err = capsys.readouterr().err
        assert (
            "[pipeline] write llm: 2 calls, 6.0s llm time, 170 completion tokens" in err
        )
        write_events = [
            e for e in events if e.get("type") == "phase" and e["phase"] == "write"
        ]
        assert len(write_events) == 1
        assert write_events[0]["llm_calls"] == 2
        assert write_events[0]["llm_duration_s"] == 6.0

    @patch("kb_ai.commands.pipeline._orchestrator.run_write_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_dedup_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_classify_phase")
    def test_classify_llm_line(self, mock_classify, mock_dedup, mock_write, fresh_context, capsys):
        req_tracker = CostTracker()
        get_context().request_tracker = req_tracker

        def record_classify_call(*args, **kwargs):
            req_tracker.record("claude-sonnet-4-6", 100, 50, duration_s=1.5)
            return ([], [])

        mock_classify.side_effect = record_classify_call
        mock_dedup.return_value = ([], 0)
        mock_write.return_value = ([], 0)

        store = MagicMock()
        store.existing_articles.return_value = []
        ctx = PipelineContext(store=store)

        run_pipeline_orchestrated(ctx, [])

        err = capsys.readouterr().err
        assert (
            "[pipeline] classify llm: 1 calls, 1.5s llm time, 50 completion tokens" in err
        )


class TestRunPipelineOrchestrated:
    @patch("kb_ai.commands.pipeline._orchestrator.run_write_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_dedup_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_classify_phase")
    def test_empty_items(self, mock_classify, mock_dedup, mock_write, fresh_context):
        mock_classify.return_value = ([], [])
        mock_dedup.return_value = ([], 0)
        mock_write.return_value = ([], 0)

        store = MagicMock()
        store.existing_articles.return_value = []
        ctx = PipelineContext(store=store)

        results = run_pipeline_orchestrated(ctx, [])
        assert results == []
        mock_classify.assert_called_once()
        mock_dedup.assert_called_once()
        mock_write.assert_called_once()

    @patch("kb_ai.commands.pipeline._orchestrator.run_write_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_dedup_phase")
    @patch("kb_ai.commands.pipeline._orchestrator.run_classify_phase")
    def test_emit_receives_phase_events(self, mock_classify, mock_dedup, mock_write, fresh_context):
        mock_classify.return_value = ([], [])
        mock_dedup.return_value = ([], 0)
        mock_write.return_value = ([], 0)

        store = MagicMock()
        store.existing_articles.return_value = []
        events = []
        ctx = PipelineContext(store=store, emit=events.append)

        run_pipeline_orchestrated(ctx, [])

        phase_events = [e for e in events if e.get("type") == "phase"]
        phases = [e["phase"] for e in phase_events]
        assert "classify" in phases
        assert "dedup" in phases
        assert "write" in phases
