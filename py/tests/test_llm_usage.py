"""Tests for kb_ai.llm._usage module."""

from __future__ import annotations

from types import SimpleNamespace

from kb_ai.llm._infra import UsageInfo, parse_usage, _EMPTY


class TestUsageInfo:
    """Tests for the UsageInfo namedtuple."""

    def test_fields(self):
        info = UsageInfo(prompt_tokens=100, completion_tokens=50,
                         cached_tokens=20, cache_created_tokens=5)
        assert info.prompt_tokens == 100
        assert info.completion_tokens == 50
        assert info.cached_tokens == 20
        assert info.cache_created_tokens == 5

    def test_empty_constant(self):
        assert _EMPTY.prompt_tokens == 0
        assert _EMPTY.completion_tokens == 0
        assert _EMPTY.cached_tokens == 0
        assert _EMPTY.cache_created_tokens == 0


class TestParseUsage:
    """Tests for the parse_usage function."""

    def test_none_usage_returns_empty(self):
        response = SimpleNamespace(usage=None)
        result = parse_usage(response)
        assert result == _EMPTY

    def test_openai_format(self):
        usage = SimpleNamespace(
            prompt_tokens=200,
            completion_tokens=80,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=50,
                cache_creation_tokens=10,
            ),
            model_dump=lambda: {},
        )
        response = SimpleNamespace(usage=usage)
        result = parse_usage(response)
        assert result.prompt_tokens == 200
        assert result.completion_tokens == 80
        assert result.cached_tokens == 50
        assert result.cache_created_tokens == 10

    def test_anthropic_passthrough_format(self):
        usage = SimpleNamespace(
            prompt_tokens=300,
            completion_tokens=100,
            prompt_tokens_details=None,
            model_dump=lambda: {
                "cache_read_input_tokens": 75,
                "cache_creation_input_tokens": 25,
            },
        )
        response = SimpleNamespace(usage=usage)
        result = parse_usage(response)
        assert result.prompt_tokens == 300
        assert result.completion_tokens == 100
        assert result.cached_tokens == 75
        assert result.cache_created_tokens == 25

    def test_mixed_format_prefers_openai(self):
        """OpenAI format takes precedence when both are present."""
        usage = SimpleNamespace(
            prompt_tokens=400,
            completion_tokens=150,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=60,
                cache_creation_tokens=30,
            ),
            model_dump=lambda: {
                "cache_read_input_tokens": 99,  # should be ignored (openai cached_tokens > 0)
                "cache_creation_input_tokens": 99,  # should be ignored (openai cache_creation > 0)
            },
        )
        response = SimpleNamespace(usage=usage)
        result = parse_usage(response)
        assert result.cached_tokens == 60
        assert result.cache_created_tokens == 30  # OpenAI value takes precedence
