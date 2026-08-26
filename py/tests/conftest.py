"""Shared test fixtures for kb_ai tests."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kb_ai._cost import CostTracker
from kb_ai._context import ThreadContext, set_context, _current_context


@pytest.fixture(autouse=True)
def _no_write_timeout_override(monkeypatch):
    """Keep KB_AI_WRITE_TIMEOUT_S out of the suite's view.

    Tests across three files assert the write phase's default call timeout. The
    operator that override exists for -- someone running a slow local model -- will
    have it exported, and would otherwise get a red suite for a reason that has
    nothing to do with their change. A test that wants the override sets it in its
    own body, which runs after this.

    The warn-once cache is module-level state keyed on the value it warned about, so
    it is reset here too: otherwise the first test to warn would decide whether a
    later one sees its own warning, making the order matter.
    """
    from kb_ai.core.merge import _warn_unusable_write_timeout

    monkeypatch.delenv("KB_AI_WRITE_TIMEOUT_S", raising=False)
    _warn_unusable_write_timeout.cache_clear()


@pytest.fixture
def cost_tracker():
    """Fresh CostTracker with store_details=True for inspection."""
    return CostTracker(store_details=True)


@pytest.fixture
def fresh_context():
    """Provide a fresh ThreadContext and reset the contextvar after the test."""
    ctx = ThreadContext()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client that returns a fixed completion response."""
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=20, cache_creation_tokens=0),
        model_dump=lambda: {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cache_read_input_tokens": 20,
        },
    )
    choice = SimpleNamespace(
        message=SimpleNamespace(content="Hello world"),
        finish_reason="stop",
    )
    response = SimpleNamespace(choices=[choice], usage=usage)
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client
