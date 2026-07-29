"""Tests for kb_ai.llm._completion module."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import kb_ai.llm as llm_pkg
from kb_ai._errors import (
    DeadlineExceededError,
    LLMTimeoutError,
    OutputTruncatedError,
    PipelineCancelledError,
    PromptTooLargeError,
)
from kb_ai.llm._completion import _completion_inner, completion, completion_json


def _make_response(content="Hello world", finish_reason="stop", prompt_tokens=100,
                   completion_tokens=50, cached_tokens=20):
    """Build a mock OpenAI response."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=cached_tokens, cache_creation_tokens=0
        ),
        model_dump=lambda: {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_read_input_tokens": cached_tokens,
        },
    )
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.fixture
def mock_client():
    """Create a mock OpenAI client and patch get_client."""
    client = MagicMock()
    client.base_url = "http://test:8080/v1"
    client.chat.completions.create.return_value = _make_response()
    with patch.object(llm_pkg, "get_client", return_value=client):
        yield client


class TestCompletionInner:
    """Tests for _completion_inner."""

    def test_basic_call(self, mock_client):
        text, reason = _completion_inner("test-model", [{"role": "user", "content": "Hi"}])
        assert text == "Hello world"
        assert reason == "stop"
        mock_client.chat.completions.create.assert_called_once()

    def test_prompt_too_large_raises(self, mock_client):
        big_content = "x" * (llm_pkg.MAX_PROMPT_CHARS + 1)
        with pytest.raises(PromptTooLargeError, match="prompt_too_large"):
            _completion_inner("model", [{"role": "user", "content": big_content}])

    def test_cancel_event_raises(self, mock_client):
        cancel = threading.Event()
        cancel.set()
        llm_pkg.set_cancel_event(cancel)
        try:
            with pytest.raises(PipelineCancelledError, match="cancelled"):
                _completion_inner("model", [{"role": "user", "content": "Hi"}])
        finally:
            llm_pkg.set_cancel_event(None)


class TestCompletion:
    """Tests for the completion wrapper."""

    def test_returns_text(self, mock_client):
        result = completion("test-model", [{"role": "user", "content": "Hi"}])
        assert result == "Hello world"

    def test_retries_on_truncation(self, mock_client):
        # First call truncated, second succeeds
        mock_client.chat.completions.create.side_effect = [
            _make_response(content="partial", finish_reason="length"),
            _make_response(content="full answer", finish_reason="stop"),
        ]
        result = completion("model", [{"role": "user", "content": "Hi"}], max_tokens=4096)
        assert result == "full answer"
        # Second call should have doubled max_tokens
        calls = mock_client.chat.completions.create.call_args_list
        assert calls[0].kwargs["max_tokens"] == 4096
        assert calls[1].kwargs["max_tokens"] == 8192

    def test_raises_on_ceiling(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            finish_reason="length"
        )
        with pytest.raises(OutputTruncatedError, match="truncated at ceiling"):
            completion("model", [{"role": "user", "content": "Hi"}], max_tokens=64000)


class TestCompletionJson:
    """Tests for completion_json."""

    def test_parses_json(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            content='{"key": "value"}'
        )
        result = completion_json("model", [{"role": "user", "content": "Hi"}])
        assert result == {"key": "value"}

    def test_strips_markdown_fences(self, mock_client):
        mock_client.chat.completions.create.return_value = _make_response(
            content='```json\n{"key": "value"}\n```'
        )
        result = completion_json("model", [{"role": "user", "content": "Hi"}])
        assert result == {"key": "value"}
