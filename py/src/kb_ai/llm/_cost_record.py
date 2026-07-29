"""Unified cost recording for LLM calls.

Consolidates the duplicated cost-recording logic (global tracker + request tracker
+ per-call event emission) into a single function.

Context is read via callable accessors injected by the caller (_completion.py),
which now read from get_context() (contextvars-based ThreadContext).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from kb_ai._cost import CostTracker
    from kb_ai.llm._infra import UsageInfo


def record_cost(
    *,
    model: str,
    usage: "UsageInfo",
    duration_s: float,
    attempts: int,
    global_tracker: "CostTracker",
    get_phase_context: Callable[[], str],
    get_content_hash_context: Callable[[], str],
    get_call_emit: Callable[[], Any],
    get_request_tracker: Callable[[], "CostTracker | None"],
) -> float:
    """Record cost to global tracker, request tracker, and emit per-call event.

    This is the single entry point for all cost recording after an LLM call.
    It handles:
      1. Recording to the global (process-level) tracker.
      2. Recording to the per-request tracker (if set in thread-local).
      3. Emitting a per-call event via call_emit (if set and phase is known).

    Args:
        model: Model identifier.
        usage: Parsed usage info from the response.
        duration_s: Call duration in seconds.
        attempts: Number of attempts used.
        global_tracker: The process-level CostTracker instance.
        get_phase_context: Callable to get current thread's phase.
        get_content_hash_context: Callable to get current thread's content hash.
        get_call_emit: Callable to get the current thread's emit function.
        get_request_tracker: Callable to get the per-request tracker.

    Returns:
        The computed cost in USD.
    """
    # Record to global tracker.
    call_cost = global_tracker.record(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
        duration_s=duration_s,
        attempts=attempts,
    )

    # Record to per-request tracker.
    req_tracker = get_request_tracker()
    if req_tracker is not None:
        req_tracker.record(
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cached_tokens=usage.cached_tokens,
            duration_s=duration_s,
            attempts=attempts,
        )

    # Emit per-call event if callback is set and phase is known.
    phase = get_phase_context()
    emit_fn = get_call_emit()
    if emit_fn is not None and phase != "unknown":
        try:
            event: dict[str, Any] = {
                "type": "llm_call",
                "phase": phase,
                "model": model,
                "duration_s": duration_s,
                "tokens_prompt": usage.prompt_tokens,
                "tokens_completion": usage.completion_tokens,
                "tokens_cached": usage.cached_tokens,
                "cost_usd": call_cost,
            }
            content_hash = get_content_hash_context()
            if content_hash:
                event["content_hash"] = content_hash
            emit_fn(event)
        except Exception:
            pass

    return call_cost
