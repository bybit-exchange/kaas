"""Unified thread context module using contextvars.

Provides a single ThreadContext dataclass that bundles all per-request state
needed for LLM calls, replacing scattered threading.local() variables.

Context propagation to child threads is done via contextual_submit(), which
captures the parent's ThreadContext and sets it in the child before execution.

Context-setting helpers with non-trivial logic (cancellable, set_pipeline_deadline)
live here. Simple field assignments should be done inline via get_context().field = value.
"""

from __future__ import annotations

import contextvars
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from kb_ai._cost import CostTracker


@dataclass
class ThreadContext:
    """All context needed for LLM calls, bundled in one object.

    Field Sharing Semantics: When propagated to child threads via contextual_submit(),
    all fields are shared by reference. This is INTENTIONAL for mutable fields:
    - cancel_event: parent can signal cancellation to children
    - request_tracker: children record cost to the same tracker (uses internal lock)
    """

    deadline_abs: float = 0.0
    cancel_event: threading.Event | None = None
    call_timeout: float | None = None
    call_emit: Callable | None = None
    phase: str = "unknown"
    content_hash: str = ""
    request_tracker: "CostTracker | None" = None


_current_context: contextvars.ContextVar[ThreadContext] = contextvars.ContextVar(
    "kb_ai_context"
)


def get_context() -> ThreadContext:
    """Get current thread's context (lazily created)."""
    try:
        return _current_context.get()
    except LookupError:
        ctx = ThreadContext()
        _current_context.set(ctx)
        return ctx


def set_context(ctx: ThreadContext) -> None:
    """Explicitly set the context for the current execution context."""
    _current_context.set(ctx)


def set_pipeline_deadline(seconds_from_now: float | None):
    """Set pipeline deadline as seconds from now. None clears the deadline."""
    get_context().deadline_abs = (time.monotonic() + seconds_from_now) if seconds_from_now else 0.0


def set_pipeline_deadline_abs(absolute: float):
    """Set absolute monotonic deadline (for propagation to worker threads)."""
    get_context().deadline_abs = absolute


@contextmanager
def cancellable(cancel_event: threading.Event | None):
    """Context manager: sets thread-local cancel event, clears on exit."""
    ctx = get_context()
    ctx.cancel_event = cancel_event
    try:
        yield
    finally:
        ctx.cancel_event = None


def contextual_submit(executor: ThreadPoolExecutor, fn: Callable, *args, **kwargs) -> Future:
    """Submit fn to executor with the CURRENT thread's context propagated.

    MUST be called from the parent thread. Captures parent's ThreadContext and
    sets it in the child thread before executing fn.
    """
    ctx = get_context()  # Captured in PARENT thread

    def _wrapped():
        set_context(ctx)  # Applied in CHILD thread
        return fn(*args, **kwargs)

    return executor.submit(_wrapped)
