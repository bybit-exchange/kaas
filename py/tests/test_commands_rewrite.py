"""Offline tests for server-side query rewriting (kb_ai.commands.rewrite).

Covers the no-history short circuit, history formatting, the cost estimator's
prefix-matching fallback, and request-tracker hygiene. The LLM call is
monkeypatched.
"""
from __future__ import annotations

import pytest

from kb_ai.commands import rewrite
from kb_ai.llm import get_request_tracker


def _fake_completion(reply: str, *, prompt_tokens: int = 0, completion_tokens: int = 0,
                     capture: dict | None = None):
    def fake(*, model, messages, **kwargs):
        if capture is not None:
            capture["model"] = model
            capture["messages"] = messages
            capture.update(kwargs)
        if prompt_tokens or completion_tokens:
            get_request_tracker().record(model, prompt_tokens, completion_tokens)
        return reply

    return fake


# ── no-history short circuit ────────────────────────────────────────

@pytest.mark.parametrize("history", [None, []])
def test_rewrite_without_history_skips_llm(monkeypatch, history):
    def boom(**kwargs):
        raise AssertionError("completion() must not be called without history")

    monkeypatch.setattr(rewrite, "completion", boom)

    out = rewrite.rewrite_query("what about pricing?", history)

    assert out == {
        "rewritten_query": "what about pricing?",
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "cost_usd": 0.0,
    }


# ── rewriting with history ──────────────────────────────────────────

def test_rewrite_with_history_calls_llm(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(rewrite, "completion", _fake_completion(
        "What is the pricing of KaaS?", prompt_tokens=200, completion_tokens=20,
        capture=capture))

    history = [
        {"role": "user", "content": "What is KaaS?"},
        {"role": "assistant", "content": "A knowledge platform."},
    ]
    out = rewrite.rewrite_query("what about pricing?", history, model="claude-sonnet-4-6")

    assert out["rewritten_query"] == "What is the pricing of KaaS?"
    assert out["tokens_prompt"] == 200
    assert out["tokens_completion"] == 20
    assert out["cost_usd"] > 0

    # The prompt must carry both the history and the latest question.
    user_content = capture["messages"][1]["content"]
    assert "user: What is KaaS?" in user_content
    assert "assistant: A knowledge platform." in user_content
    assert "what about pricing?" in user_content
    # Rewriting must be deterministic.
    assert capture["temperature"] == 0


def test_rewrite_cost_matches_pricing_table(monkeypatch):
    monkeypatch.setattr(rewrite, "completion", _fake_completion(
        "rewritten", prompt_tokens=1_000_000, completion_tokens=0))

    out = rewrite.rewrite_query("q", [{"role": "user", "content": "c"}],
                                model="claude-sonnet-4-6")

    # 1M prompt tokens at 3 USD/M input, no cached tokens.
    assert out["cost_usd"] == pytest.approx(3.0)


def test_rewrite_restores_previous_request_tracker(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(rewrite, "completion", boom)
    before = get_request_tracker()

    with pytest.raises(RuntimeError):
        rewrite.rewrite_query("q", [{"role": "user", "content": "c"}])

    assert get_request_tracker() is before


# ── _format_history ─────────────────────────────────────────────────

def test_format_history_joins_role_and_content():
    out = rewrite._format_history([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ])
    assert out == "user: hi\nassistant: hello"


def test_format_history_tolerates_missing_keys():
    out = rewrite._format_history([{}, {"role": "user"}, {"content": "orphan"}])
    assert out == "unknown: \nuser: \nunknown: orphan"


def test_format_history_empty():
    assert rewrite._format_history([]) == ""


# ── _estimate_cost ──────────────────────────────────────────────────

def test_estimate_cost_exact_model():
    # 1M input at 3 USD/M + 1M output at 15 USD/M.
    cost = rewrite._estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_estimate_cost_discounts_cached_tokens():
    """Cached prompt tokens bill at 10% of the input rate."""
    full = rewrite._estimate_cost("claude-haiku-4-5", 1_000_000, 0)
    cached = rewrite._estimate_cost("claude-haiku-4-5", 1_000_000, 0,
                                    cached_tokens=1_000_000)
    assert full == pytest.approx(1.0)
    assert cached == pytest.approx(0.1)


def test_estimate_cost_falls_back_to_prefix_match():
    """An unlisted point release must still price via its family prefix rather
    than silently costing nothing."""
    cost = rewrite._estimate_cost("claude-sonnet-4-9", 1_000_000, 0)
    assert cost > 0


def test_estimate_cost_unknown_model_is_zero():
    assert rewrite._estimate_cost("some-other-vendor-model", 1_000_000, 1_000_000) == 0.0


def test_estimate_cost_zero_tokens():
    assert rewrite._estimate_cost("claude-sonnet-4-6", 0, 0) == 0.0
