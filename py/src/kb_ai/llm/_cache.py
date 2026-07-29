"""Adaptive prompt cache state machine.

Manages the auto-disable logic for Anthropic prompt caching. The cache is
disabled after a configurable number of consecutive misses (neither cache
read nor cache write occurred), and re-enabled on any hit.

Thread-safe: all state mutations are guarded by a lock.
"""

from __future__ import annotations

import sys
import threading


class AdaptiveCacheState:
    """Thread-safe adaptive cache state machine.

    States:
      - ENABLED: cache is active, system messages get cache_control.
      - DISABLED: cache has been auto-disabled after consecutive misses.

    Transitions:
      - ENABLED -> DISABLED: after `miss_threshold` consecutive misses.
      - DISABLED -> ENABLED: on explicit reset() call.
      - Any -> ENABLED: on record_result() with a hit (cache read or write).

    A "miss" is a call where BOTH cached_tokens == 0 AND cache_created_tokens == 0.
    A cache write (cache_created_tokens > 0) counts as a hit because it means
    the prefix was successfully cached for future reads.
    """

    def __init__(self, miss_threshold: int = 10, label: str = "LLM"):
        self._miss_threshold = miss_threshold
        self._label = label
        self._consecutive_misses = 0
        self._disabled = False
        self._lock = threading.Lock()

    @property
    def is_disabled(self) -> bool:
        """Whether caching is currently disabled."""
        with self._lock:
            return self._disabled

    @property
    def is_enabled(self) -> bool:
        """Whether caching is currently enabled."""
        return not self.is_disabled

    @property
    def consecutive_misses(self) -> int:
        """Current consecutive miss count."""
        with self._lock:
            return self._consecutive_misses

    @property
    def miss_threshold(self) -> int:
        """Number of consecutive misses that triggers auto-disable."""
        return self._miss_threshold

    def should_use_cache(self, caller_wants_cache: bool) -> bool:
        """Determine whether to actually use caching for a call.

        Args:
            caller_wants_cache: Whether the caller requested caching.

        Returns:
            True if caching should be used (caller wants it AND it's not disabled).
        """
        if not caller_wants_cache:
            return False
        with self._lock:
            return not self._disabled

    def record_result(self, cached_tokens: int, cache_created_tokens: int) -> None:
        """Record a cache result and update state machine.

        Call this after every LLM call where caching was active.

        Args:
            cached_tokens: Number of tokens served from cache.
            cache_created_tokens: Number of tokens written to cache.
        """
        with self._lock:
            if cached_tokens > 0 or cache_created_tokens > 0:
                # Hit (read or write) -> reset miss counter
                self._consecutive_misses = 0
            else:
                # Miss -> increment and possibly disable
                self._consecutive_misses += 1
                if self._consecutive_misses >= self._miss_threshold:
                    self._disabled = True
                    print(
                        f"[{self._label}] prompt cache auto-disabled after "
                        f"{self._miss_threshold} consecutive misses",
                        file=sys.stderr,
                    )

    def reset(self) -> None:
        """Reset state machine: re-enable cache and clear miss counter."""
        with self._lock:
            self._consecutive_misses = 0
            self._disabled = False


def enable_prompt_caching(messages: list[dict]) -> list[dict]:
    """Add cache_control to system messages for Anthropic prompt caching.

    Transforms system messages with string content into the structured content
    format with cache_control markers. Non-system messages are passed through
    unchanged.

    Args:
        messages: List of chat messages.

    Returns:
        New list with system messages transformed for prompt caching.
    """
    result = []
    for msg in messages:
        if msg["role"] == "system" and isinstance(msg.get("content"), str):
            result.append({
                "role": "system",
                "content": [{
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"},
                }],
            })
        else:
            result.append(msg)
    return result
