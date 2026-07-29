"""Shared test fixtures for kb_ai tests."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kb_ai._cost import CostTracker
from kb_ai._context import ThreadContext, set_context, _current_context


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
