"""Shared LLM client using OpenAI SDK via LiteLLM proxy, with cost tracking.

This package provides completion helpers with automatic retry, cost tracking,
and adaptive prompt caching.

All public symbols are re-exported here for backward compatibility.

Context state (deadline, cancel_event, phase, emit, etc.) is stored in
kb_ai._context.ThreadContext via contextvars. The wrapper functions below
delegate to get_context() for backward compatibility.
"""

import time
from contextlib import contextmanager
import sys

# --- Errors (from kb_ai._errors) ---
from kb_ai._errors import (  # noqa: F401
    DeadlineExceededError,
    LLMTimeoutError,
    OutputTruncatedError,
    PipelineCancelledError,
    PromptTooLargeError,
)

# --- Cost tracking (from kb_ai._cost) ---
from kb_ai._cost import PRICING, CostTracker, estimate_cost  # noqa: F401

# --- Infrastructure (client + shared constants + usage parsing) ---
from ._infra import (  # noqa: F401
    MAX_PROMPT_CHARS,
    UsageInfo,
    _ALERT_CALLER,
    _DEFAULT_BASE_URL,
    _MAX_TOKENS_CEILING,
    _TIMEOUT_BACKOFF_BASE,
    _TIMEOUT_RETRIES,
    count_prompt_chars,
    emit_alert,
    get_client,
    parse_usage,
    reset_client,
)

# --- Cache ---
from ._cache import AdaptiveCacheState, enable_prompt_caching  # noqa: F401

# --- Completion (non-streaming) ---
from ._completion import completion, completion_json  # noqa: F401
# Private — NOT re-exported; accessed internally by submodules.
from ._completion import _cache_state, _cache_lock  # noqa: F401

# --- Context (re-exported for backward compat) ---
from kb_ai._context import (  # noqa: F401
    cancellable,
    get_context,
    set_pipeline_deadline,
    set_pipeline_deadline_abs,
)

# --- Global tracker (summary only, no per-call details) ---
tracker = CostTracker(store_details=False)

# Backward-compat alias
_emit_alert = emit_alert
_count_prompt_chars = count_prompt_chars
_enable_prompt_caching = enable_prompt_caching

# ---------------------------------------------------------------------------
# Backward-compat wrapper functions — delegate to get_context().
# These used to use threading.local(); now they write/read contextvars.
# ---------------------------------------------------------------------------

from kb_ai._context import get_context as _get_context  # noqa: E402


def _get_pipeline_deadline() -> float:
    return _get_context().deadline_abs


def set_cancel_event(event):
    _get_context().cancel_event = event


def _get_cancel_event():
    return _get_context().cancel_event


def set_call_timeout(seconds: float | None):
    """Override per-call HTTP timeout for the current thread.

    None = use client default (900s). Callers with stricter SLAs (e.g. extract
    bounds output to <=16K max_tokens) can set a smaller value to surface stalls
    via APITimeoutError + retry instead of waiting out the full default.
    """
    _get_context().call_timeout = seconds


def get_call_timeout() -> float | None:
    return _get_context().call_timeout


def set_call_emit(fn):
    """Set a per-call emit function for the current context. Pass None to disable."""
    _get_context().call_emit = fn


def get_call_emit():
    """Get the per-call emit function for the current context."""
    return _get_context().call_emit


def set_phase_context(phase: str):
    """Set the current phase name for this context (used in per-call emit)."""
    _get_context().phase = phase


def get_phase_context() -> str:
    return _get_context().phase


def error_event(message: str) -> dict:
    """Build an SSE 'error' event tagged with the current pipeline phase.

    Why: the Go-side stream consumer reads event.phase to populate
    llm_call_logs.operation when a pipeline run fails — without it, every
    fatal pipeline error lands as 'pipeline_unknown' and alerts lose context.
    """
    return {"type": "error", "message": message, "phase": get_phase_context()}


def set_content_hash_context(content_hash: str):
    """Set the current content_hash for this context (used in per-call emit)."""
    _get_context().content_hash = content_hash


def get_content_hash_context() -> str:
    return _get_context().content_hash


def set_request_tracker(t: "CostTracker | None"):
    """Set a per-request tracker for the current context. Worker threads must propagate."""
    _get_context().request_tracker = t


def get_request_tracker() -> "CostTracker | None":
    return _get_context().request_tracker


# ---------------------------------------------------------------------------
# Adaptive cache backward-compat attributes
# ---------------------------------------------------------------------------
_CACHE_MISS_THRESHOLD = _cache_state._miss_threshold


def __getattr__(name: str):
    """Module-level __getattr__ for backward-compat proxy attributes.

    Tests access _cache_consecutive_misses and _cache_disabled directly on the
    kb_ai.llm module. These now live inside _cache_state.
    """
    if name == "_cache_consecutive_misses":
        return _cache_state._consecutive_misses
    if name == "_cache_disabled":
        return _cache_state._disabled
    raise AttributeError(f"module 'kb_ai.llm' has no attribute {name!r}")


# Wire up __setattr__ on the module for proxy attributes.
_this_module = sys.modules[__name__]
_original_module_class = type(_this_module)


class _LLMModule(_original_module_class):
    """Module subclass to support __setattr__ for backward-compat proxy attributes."""

    def __setattr__(self, name, value):
        if name == "_cache_consecutive_misses":
            _cache_state._consecutive_misses = value
            return
        if name == "_cache_disabled":
            _cache_state._disabled = value
            return
        super().__setattr__(name, value)


_this_module.__class__ = _LLMModule
