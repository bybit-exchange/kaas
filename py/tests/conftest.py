"""Shared test fixtures for kb_ai tests."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kb_ai._cost import CostTracker
from kb_ai._context import ThreadContext, set_context, _current_context


@pytest.fixture(autouse=True)
def _no_phase_timeout_overrides(monkeypatch):
    """Keep the per-phase timeout overrides out of the suite's view.

    Tests across four files assert the extract and write phases' default call
    timeouts. The operator those overrides exist for -- someone running a slow local
    model -- will have them exported, and would otherwise get a red suite for a
    reason that has nothing to do with their change. A test that wants an override
    sets it in its own body, which runs after this. KB_AI_REASONING_EFFORT joins
    them for the same reason: an exported knob would silently add a kwarg to
    every mocked request in the suite. The two section-merge knobs join as
    well: an exported mode or concurrency bound would decide dispatch routing
    and semaphore sizing for every merge test.

    The warn-once caches are module-level state keyed on the value they warned about,
    so they are reset here too: otherwise the first test to warn would decide whether
    a later one sees its own warning, making the order matter. The reasoning-effort
    disable flag is the same kind of state: the first test whose mock answers 400
    would otherwise decide for every later test whether the param is ever sent.
    """
    from kb_ai.core.extract import _warn_unusable_extract_timeout
    from kb_ai.core.merge import _warn_unusable_write_timeout
    from kb_ai.llm import _completion as completion_module

    monkeypatch.delenv("KB_AI_WRITE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("KB_AI_EXTRACT_TIMEOUT_S", raising=False)
    monkeypatch.delenv("KB_AI_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("KB_MERGE_SECTION_MODE", raising=False)
    monkeypatch.delenv("KB_MERGE_SECTION_MAX_CONCURRENT", raising=False)
    _warn_unusable_write_timeout.cache_clear()
    _warn_unusable_extract_timeout.cache_clear()
    monkeypatch.setattr(completion_module, "_reasoning_effort_disabled", False)


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
