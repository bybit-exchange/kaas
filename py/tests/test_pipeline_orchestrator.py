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
