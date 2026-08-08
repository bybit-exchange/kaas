"""Shared infrastructure for the llm package: constants, alerting, usage parsing, client.

Merged from _shared.py + _usage.py + _client.py.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import NamedTuple

from openai import OpenAI

from kb_ai._context import get_context

# ---------------------------------------------------------------------------
# Constants (from _shared.py)
# ---------------------------------------------------------------------------

_TIMEOUT_RETRIES = 2
_TIMEOUT_BACKOFF_BASE = 10  # seconds
_MAX_TOKENS_CEILING = 64000  # Bedrock Haiku 4.5 limit

# Client-wide HTTP timeout, and the ceiling every per-call override sits under.
# Deliberately generous because it has to cover the slowest call any phase makes;
# a phase that knows its own calls are smaller overrides it via set_call_timeout.
DEFAULT_CLIENT_TIMEOUT_S = 900.0

# 80K chars (not tokens): precise token counting is expensive for mixed zh/en content
# (1 CJK char ~ 2-3 tokens). 80K chars is safe for a 200K token context window.
# Injected by Go bridge via KB_AI_MAX_PROMPT_CHARS env var.
MAX_PROMPT_CHARS = int(os.environ.get("KB_AI_MAX_PROMPT_CHARS", "80000"))

_ALERT_CALLER = "kb_ai/llm.py:_completion_inner"


# ---------------------------------------------------------------------------
# Alert / utility functions (from _shared.py)
# ---------------------------------------------------------------------------

def emit_alert(message: str, model: str, attempt: int, kind: str,
               *, content_hash: str = "", caller: str = "") -> None:
    """Log an LLM-failure warning to stderr, and to the context's sink if set.

    The sink is how a warning reaches the log of the job it belongs to. Over the
    HTTP API the process stderr is a stream nobody debugging a slow compile reads;
    the KB's own .compile.log is, and it used to just stop advancing for the
    duration of a stall with nothing written to explain it.
    """
    extra = ""
    if content_hash:
        extra += f" content_hash={content_hash}"
    if caller:
        extra += f" caller={caller}"
    line = f"[LLM-WARN] {kind}: {message} (model={model} attempt={attempt}{extra})"
    print(line, file=sys.stderr, flush=True)

    sink = get_context().alert_sink
    if sink is None:
        return
    try:
        sink(line)
    except Exception as e:  # noqa: BLE001 -- alerting must not raise
        # The call this warns about is still retryable. A closed log file or a
        # torn-down job must not convert that into a failure.
        print(f"[LLM-WARN] alert_sink failed: {e}", file=sys.stderr, flush=True)


def count_prompt_chars(messages: list[dict]) -> int:
    """Count total characters in message contents."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    t = part.get("text")
                    if isinstance(t, str):
                        total += len(t)
    return total


# ---------------------------------------------------------------------------
# Usage parsing (from _usage.py)
# ---------------------------------------------------------------------------

class UsageInfo(NamedTuple):
    """Parsed usage information from an LLM response."""

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cache_created_tokens: int


_EMPTY = UsageInfo(prompt_tokens=0, completion_tokens=0, cached_tokens=0, cache_created_tokens=0)


def parse_usage(response) -> UsageInfo:
    """Extract usage info from a non-streaming LLM response.

    Handles both formats:
      - OpenAI: usage.prompt_tokens_details.cached_tokens
      - Anthropic passthrough (LiteLLM): usage.cache_read_input_tokens
    """
    usage = response.usage
    if not usage:
        return _EMPTY

    return _extract_usage_fields(usage)


def _extract_usage_fields(usage) -> UsageInfo:
    """Shared extraction logic for usage objects."""
    raw = usage.model_dump() if hasattr(usage, "model_dump") else {}
    cached = 0
    cache_created = 0

    # Try OpenAI format first
    det = getattr(usage, "prompt_tokens_details", None)
    if det:
        cached = getattr(det, "cached_tokens", 0) or 0
        cache_created = getattr(det, "cache_creation_tokens", 0) or 0
    # Try Anthropic passthrough fields (LiteLLM includes these)
    if not cached:
        cached = raw.get("cache_read_input_tokens", 0) or 0
    if not cache_created:
        cache_created = raw.get("cache_creation_input_tokens", 0) or 0

    prompt_tok = usage.prompt_tokens or 0
    completion_tok = usage.completion_tokens or 0

    return UsageInfo(
        prompt_tokens=prompt_tok,
        completion_tokens=completion_tok,
        cached_tokens=cached,
        cache_created_tokens=cache_created,
    )


# ---------------------------------------------------------------------------
# Client singleton (from _client.py)
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

_client: OpenAI | None = None
_client_lock = threading.Lock()


def get_client() -> OpenAI:
    """Get or create the shared OpenAI client instance.

    The client is configured with:
      - base_url from LLM_BASE_URL or OPENAI_BASE_URL env var (default: OpenAI).
      - api_key from LLM_API_KEY or OPENAI_API_KEY env var.
      - timeout=DEFAULT_CLIENT_TIMEOUT_S to accommodate long LLM calls.
      - max_retries=0: retry logic is handled by _completion.py, not the SDK.

    Returns:
        The shared OpenAI client instance.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                base_url = (os.environ.get("LLM_BASE_URL")
                            or os.environ.get("OPENAI_BASE_URL")
                            or _DEFAULT_BASE_URL)
                api_key = (os.environ.get("LLM_API_KEY")
                           or os.environ.get("OPENAI_API_KEY", ""))
                # max_retries=0: kb_ai outer layer (_completion_inner) already has
                # timeout/backoff retry logic; SDK default max_retries=2 would silently
                # retry internally, stacking 900s timeouts.
                _client = OpenAI(base_url=base_url, api_key=api_key,
                                 timeout=DEFAULT_CLIENT_TIMEOUT_S, max_retries=0)
    return _client


def reset_client() -> None:
    """Reset the client singleton (for testing)."""
    global _client
    with _client_lock:
        _client = None
