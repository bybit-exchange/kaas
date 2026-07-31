"""Offline tests for follow-up question suggestion (kb_ai.commands.suggest).

The LLM call is monkeypatched, so these run without network. The fake records
token usage into the ambient request tracker, mirroring what completion() does,
which is what lets the token-accounting assertions be meaningful.
"""
from __future__ import annotations

import pytest

from kb_ai.commands import suggest
from kb_ai.llm import get_request_tracker


def _fake_completion(reply: str, *, prompt_tokens: int = 0, completion_tokens: int = 0,
                     capture: dict | None = None):
    """Build a stand-in for completion() that returns reply verbatim."""

    def fake(*, model, messages, **kwargs):
        if capture is not None:
            capture["model"] = model
            capture["messages"] = messages
            capture.update(kwargs)
        if prompt_tokens or completion_tokens:
            tracker = get_request_tracker()
            tracker.record(model, prompt_tokens, completion_tokens)
        return reply

    return fake


def test_suggest_parses_json_array(monkeypatch):
    monkeypatch.setattr(suggest, "completion",
                        _fake_completion('["Why?", "How?", "When?"]'))

    out = suggest.suggest_questions("original question", "the answer")

    assert out["suggestions"] == ["Why?", "How?", "When?"]


def test_suggest_strips_markdown_code_fence(monkeypatch):
    reply = '```json\n["A", "B"]\n```'
    monkeypatch.setattr(suggest, "completion", _fake_completion(reply))

    out = suggest.suggest_questions("q", "a")

    assert out["suggestions"] == ["A", "B"]


def test_suggest_caps_at_three(monkeypatch):
    monkeypatch.setattr(suggest, "completion",
                        _fake_completion('["1", "2", "3", "4", "5"]'))

    out = suggest.suggest_questions("q", "a")

    assert out["suggestions"] == ["1", "2", "3"]


def test_suggest_drops_non_string_entries(monkeypatch):
    monkeypatch.setattr(suggest, "completion",
                        _fake_completion('["keep", 42, null, {"a": 1}, "also keep"]'))

    out = suggest.suggest_questions("q", "a")

    assert out["suggestions"] == ["keep", "also keep"]


@pytest.mark.parametrize("reply", [
    "not json at all",
    "",
    '{"suggestions": ["a"]}',   # an object, not the expected array
    "[unclosed",
])
def test_suggest_degrades_to_empty_on_unusable_reply(monkeypatch, reply):
    monkeypatch.setattr(suggest, "completion", _fake_completion(reply))

    out = suggest.suggest_questions("q", "a")

    assert out["suggestions"] == []


def test_suggest_reports_token_usage(monkeypatch):
    monkeypatch.setattr(suggest, "completion",
                        _fake_completion('["a"]', prompt_tokens=120, completion_tokens=30))

    out = suggest.suggest_questions("q", "a")

    assert out["tokens_prompt"] == 120
    assert out["tokens_completion"] == 30


def test_suggest_truncates_long_answers(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(suggest, "completion", _fake_completion('["a"]', capture=capture))

    long_answer = "x" * 5000
    suggest.suggest_questions("q", long_answer)

    user_content = capture["messages"][1]["content"]
    # The 2000-char cap must apply, and nothing beyond it may leak through.
    assert "x" * 2000 in user_content
    assert "x" * 2001 not in user_content


def test_suggest_passes_short_answer_through(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(suggest, "completion", _fake_completion('["a"]', capture=capture))

    suggest.suggest_questions("my question", "short answer")

    user_content = capture["messages"][1]["content"]
    assert "my question" in user_content
    assert "short answer" in user_content


def test_suggest_sends_system_prompt_and_model(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(suggest, "completion", _fake_completion('["a"]', capture=capture))

    suggest.suggest_questions("q", "a", model="claude-haiku-4-5")

    assert capture["model"] == "claude-haiku-4-5"
    assert capture["messages"][0]["role"] == "system"
    assert capture["messages"][0]["content"]        # registry prompt is non-empty
    assert capture["temperature"] == 0.7
    assert capture["max_tokens"] == 256


def test_suggest_restores_previous_request_tracker(monkeypatch):
    """The per-request tracker must be swapped back even on failure, or a
    concurrent request would keep accumulating into the wrong tracker."""
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(suggest, "completion", boom)
    before = get_request_tracker()

    with pytest.raises(RuntimeError):
        suggest.suggest_questions("q", "a")

    assert get_request_tracker() is before
