"""Tests for kb_ai.llm._cache module."""

from __future__ import annotations

from kb_ai.llm._cache import AdaptiveCacheState, enable_prompt_caching


class TestAdaptiveCacheState:
    """Tests for the AdaptiveCacheState class."""

    def test_initial_state_is_enabled(self):
        state = AdaptiveCacheState(miss_threshold=5)
        assert state.is_enabled
        assert not state.is_disabled
        assert state.consecutive_misses == 0
        assert state.miss_threshold == 5

    def test_should_use_cache_when_enabled(self):
        state = AdaptiveCacheState()
        assert state.should_use_cache(True) is True
        assert state.should_use_cache(False) is False

    def test_should_use_cache_when_disabled(self):
        state = AdaptiveCacheState(miss_threshold=1)
        state.record_result(0, 0)  # triggers disable
        assert state.should_use_cache(True) is False
        assert state.should_use_cache(False) is False

    def test_disables_after_threshold_misses(self):
        state = AdaptiveCacheState(miss_threshold=3)
        state.record_result(0, 0)
        assert state.is_enabled
        state.record_result(0, 0)
        assert state.is_enabled
        state.record_result(0, 0)
        assert state.is_disabled
        assert state.consecutive_misses == 3

    def test_hit_resets_miss_counter(self):
        state = AdaptiveCacheState(miss_threshold=3)
        state.record_result(0, 0)
        state.record_result(0, 0)
        # cache read resets
        state.record_result(10, 0)
        assert state.consecutive_misses == 0
        assert state.is_enabled

    def test_cache_write_counts_as_hit(self):
        state = AdaptiveCacheState(miss_threshold=3)
        state.record_result(0, 0)
        state.record_result(0, 0)
        # cache write (creation) resets
        state.record_result(0, 100)
        assert state.consecutive_misses == 0
        assert state.is_enabled

    def test_reset_re_enables(self):
        state = AdaptiveCacheState(miss_threshold=1)
        state.record_result(0, 0)
        assert state.is_disabled
        state.reset()
        assert state.is_enabled
        assert state.consecutive_misses == 0

    def test_independent_instances(self):
        """AC3: Two separate instances track state independently."""
        s1 = AdaptiveCacheState(miss_threshold=2)
        s2 = AdaptiveCacheState(miss_threshold=2)

        s1.record_result(0, 0)
        s1.record_result(0, 0)

        assert s1.is_disabled
        assert s2.is_enabled
        assert s2.consecutive_misses == 0

    def test_different_thresholds(self):
        s1 = AdaptiveCacheState(miss_threshold=1)
        s2 = AdaptiveCacheState(miss_threshold=100)

        s1.record_result(0, 0)
        assert s1.is_disabled

        for _ in range(50):
            s2.record_result(0, 0)
        assert s2.is_enabled


class TestEnablePromptCaching:
    """Tests for the enable_prompt_caching function."""

    def test_transforms_system_messages(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = enable_prompt_caching(messages)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == [{
            "type": "text",
            "text": "You are helpful.",
            "cache_control": {"type": "ephemeral"},
        }]
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_preserves_non_system_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = enable_prompt_caching(messages)
        assert result == messages

    def test_preserves_already_structured_system(self):
        structured = [{"type": "text", "text": "Already structured"}]
        messages = [{"role": "system", "content": structured}]
        result = enable_prompt_caching(messages)
        # list content is not a str, so it's passed through
        assert result[0]["content"] is structured
