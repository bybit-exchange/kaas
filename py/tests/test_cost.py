"""Tests for kb_ai._cost module."""
from __future__ import annotations

import threading

import pytest

from kb_ai._cost import (
    PRICING,
    CostTracker,
    estimate_cost,
    resolve_pricing,
)


# ── resolve_pricing ────────────────────────────────────────────────────

class TestResolvePricing:
    def test_exact_match(self):
        p = resolve_pricing("claude-sonnet-4-6")
        assert p == {"input": 3.0, "output": 15.0}

    def test_prefix_match(self):
        # "claude-sonnet-4" is a prefix of "claude-sonnet-4-6" minus the last segment
        p = resolve_pricing("claude-sonnet-4-20250514")
        assert p is not None
        assert p["input"] == 3.0

    def test_substring_fallback_opus(self):
        p = resolve_pricing("ai.kaas.chat.bedrock.global.opus-4-6")
        assert p == PRICING["claude-opus-4-6"]

    def test_substring_fallback_sonnet(self):
        p = resolve_pricing("ai.kaas.chat.bedrock.global.sonnet-4-6")
        assert p == PRICING["claude-sonnet-4-6"]

    def test_substring_fallback_haiku(self):
        p = resolve_pricing("ai.kaas.chat.bedrock.global.haiku-4-5")
        assert p == PRICING["claude-haiku-4-5"]

    def test_unknown_model_returns_none(self):
        assert resolve_pricing("gpt-4o") is None

    def test_case_insensitive_substring(self):
        p = resolve_pricing("AI.KAAS.SONNET.ROUTER")
        assert p == PRICING["claude-sonnet-4-6"]


# ── estimate_cost ──────────────────────────────────────────────────────

class TestEstimateCost:
    def test_basic_cost_no_cache(self):
        # claude-sonnet-4-6: input=3.0, output=15.0 per 1M tokens
        cost = estimate_cost("claude-sonnet-4-6", 1000, 500, 0)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_cost_with_cache(self):
        # 1000 prompt, 500 completion, 200 cached
        # non_cached = 800, cached = 200
        # cost = (800 * 3.0 + 200 * 3.0 * 0.1 + 500 * 15.0) / 1M
        cost = estimate_cost("claude-sonnet-4-6", 1000, 500, 200)
        expected = (800 * 3.0 + 200 * 3.0 * 0.1 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_cost_all_cached(self):
        cost = estimate_cost("claude-sonnet-4-6", 1000, 500, 1000)
        expected = (0 * 3.0 + 1000 * 3.0 * 0.1 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_unknown_model_returns_zero(self):
        cost = estimate_cost("gpt-4o", 1000, 500, 0)
        assert cost == 0.0

    def test_opus_pricing(self):
        cost = estimate_cost("claude-opus-4-6", 1000, 500, 0)
        expected = (1000 * 5.0 + 500 * 25.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_haiku_pricing(self):
        cost = estimate_cost("claude-haiku-4-5", 1000, 500, 0)
        expected = (1000 * 1.0 + 500 * 5.0) / 1_000_000
        assert cost == pytest.approx(expected)


# ── CostTracker ────────────────────────────────────────────────────────

class TestCostTracker:
    def test_record_accumulates(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 100, 50)
        cost_tracker.record("claude-sonnet-4-6", 200, 100)
        assert cost_tracker.calls == 2
        assert cost_tracker.total_prompt_tokens == 300
        assert cost_tracker.total_completion_tokens == 150
        assert cost_tracker.total_cost > 0

    def test_record_with_explicit_cost(self, cost_tracker: CostTracker):
        returned = cost_tracker.record("claude-sonnet-4-6", 100, 50, cost=0.42)
        assert returned == 0.42
        assert cost_tracker.total_cost == 0.42

    def test_record_stores_details(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 100, 50, cached_tokens=10, duration_s=1.5)
        assert len(cost_tracker.details) == 1
        d = cost_tracker.details[0]
        assert d["model"] == "claude-sonnet-4-6"
        assert d["prompt_tokens"] == 100
        assert d["completion_tokens"] == 50
        assert d["cached_tokens"] == 10
        assert d["duration_s"] == 1.5
        assert "attempts" not in d  # only stored when > 1

    def test_record_stores_attempts_when_gt_1(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 100, 50, attempts=3)
        assert cost_tracker.details[0]["attempts"] == 3

    def test_no_details_when_disabled(self):
        t = CostTracker(store_details=False)
        t.record("claude-sonnet-4-6", 100, 50)
        assert t.details == []
        assert t.calls == 1

    def test_snapshot_and_delta(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 100, 50)
        snap = cost_tracker.snapshot()
        cost_tracker.record("claude-sonnet-4-6", 200, 100)
        d = cost_tracker.delta(snap)
        assert d["calls"] == 1
        assert d["prompt"] == 200
        assert d["completion"] == 100
        assert d["cost"] > 0
        assert d["elapsed"] >= 0
        assert len(d["call_details"]) == 1

    def test_summary(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 1000, 500, cached_tokens=200)
        s = cost_tracker.summary()
        assert s["calls"] == 1
        assert s["total_prompt_tokens"] == 1000
        assert s["total_completion_tokens"] == 500
        assert s["total_cached_tokens"] == 200
        assert s["total_cost_usd"] > 0

    def test_summary_with_details(self, cost_tracker: CostTracker):
        cost_tracker.record("claude-sonnet-4-6", 100, 50)
        s = cost_tracker.summary_with_details()
        assert s["calls"] == 1
        assert len(s["call_details"]) == 1

    def test_thread_safety(self):
        """Multiple threads recording concurrently should not lose data."""
        t = CostTracker(store_details=False)
        n_threads = 10
        n_per_thread = 100

        def worker():
            for _ in range(n_per_thread):
                t.record("claude-sonnet-4-6", 10, 5)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert t.calls == n_threads * n_per_thread
        assert t.total_prompt_tokens == n_threads * n_per_thread * 10

    def test_print_summary(self, cost_tracker: CostTracker, capsys):
        import sys
        cost_tracker.record("claude-sonnet-4-6", 1000, 500, cached_tokens=200)
        cost_tracker.print_summary(file=sys.stdout)
        captured = capsys.readouterr()
        assert "[LLM Cost]" in captured.out
        assert "200 cached" in captured.out
