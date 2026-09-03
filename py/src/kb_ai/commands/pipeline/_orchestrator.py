"""Pipeline orchestrator -- chains classify -> dedup -> write phases.

This module provides the PipelineContext dataclass (shared pipeline state)
and run_pipeline_orchestrated() which connects the phase modules into a
single pipeline execution.
"""

from __future__ import annotations

import sys
import time
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from kb_ai._context import get_context
from kb_ai.commands.pipeline._phase_classify import run_classify_phase
from kb_ai.core.classify import DEFAULT_CATEGORIES
from kb_ai.commands.pipeline._phase_dedup import run_dedup_phase
from kb_ai.commands.pipeline._phase_write import run_write_phase
from kb_ai.llm import tracker

if TYPE_CHECKING:
    from kb_ai.storage.store import KBStore


def _active_tracker():
    """Return per-request CostTracker if set (HTTP mode), else module-level global (CLI mode).

    Phase-level snapshot/delta must use the per-request tracker to avoid cross-
    contamination from concurrent /pipeline or /extract requests. CLI mode
    (run_server_pipeline) doesn't set a per-request tracker -- global is fine
    there since only one request runs per process.
    """
    return get_context().request_tracker or tracker


def _build_cost_summary(delta: dict) -> dict:
    """Build a cost summary dict from a tracker delta."""
    return {
        "prompt": delta["prompt"],
        "completion": delta["completion"],
        "cached": delta["cached"],
    }


@dataclass
class PipelineContext:
    """Shared state for a single pipeline execution."""

    store: "KBStore"
    model: str = "claude-sonnet-4-6"
    classify_model: str = ""
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    workers: int = 16
    cancel_event: threading.Event | None = None
    emit: Callable[[dict], None] | None = None


def run_pipeline_orchestrated(
    ctx: PipelineContext,
    items: list[dict],
) -> list[dict]:
    """Execute the full pipeline: classify -> dedup -> write.

    Args:
        ctx: PipelineContext with shared configuration
        items: list of extraction dicts to process

    Returns:
        list of per-item result dicts
    """
    pipeline_ctx = get_context()
    if ctx.emit:
        pipeline_ctx.call_emit = ctx.emit
        pipeline_ctx.phase = "classify"

    classify_model = ctx.classify_model or ctx.model

    try:
        return _run_phases(ctx, items, classify_model)
    finally:
        pipeline_ctx.call_emit = None


def _run_phases(
    ctx: PipelineContext,
    items: list[dict],
    classify_model: str,
) -> list[dict]:
    """Run classify, dedup, and write phases sequentially."""
    item_results: list[dict] = []

    # -- Phase 1: Classify --
    t0 = time.time()
    snap_classify = _active_tracker().snapshot()

    classified_items, classify_errors = run_classify_phase(
        items=items,
        store=ctx.store,
        classify_model=classify_model,
        categories=ctx.categories,
        cancel_event=ctx.cancel_event,
    )

    # Emit classify errors
    for err in classify_errors:
        item_results.append(err)
        if ctx.emit:
            ctx.emit(err)

    classify_duration = time.time() - t0
    classify_delta = _active_tracker().delta(snap_classify)
    c_calls = len(classify_delta.get("call_details", []))
    c_llm = sum(d.get("duration_s", 0.0) for d in classify_delta["call_details"])
    print(
        f"[pipeline] classify llm: {c_calls} calls, {c_llm:.1f}s llm time, "
        f"{classify_delta['completion']} completion tokens",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[pipeline] classify done: {len(classified_items)} items in {classify_duration:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    if ctx.emit:
        ctx.emit({
            "type": "phase",
            "phase": "classify",
            "duration_s": round(classify_duration, 2),
            "items": len(classified_items),
            "model": classify_model,
            "cost": _build_cost_summary(classify_delta),
        })

    # -- Phase 1.5: Dedup --
    get_context().phase = "dedup"
    t_dedup = time.time()
    snap_dedup = _active_tracker().snapshot()

    classified_items, deduped_count = run_dedup_phase(
        classified_items=classified_items,
        base_existing=ctx.store.existing_articles(),
        cancel_event=ctx.cancel_event,
    )

    dedup_duration = time.time() - t_dedup
    if ctx.emit:
        dedup_delta = _active_tracker().delta(snap_dedup)
        ctx.emit({
            "type": "phase",
            "phase": "dedup",
            "duration_s": round(dedup_duration, 2),
            "deduped": deduped_count,
            "cost": _build_cost_summary(dedup_delta),
        })

    # -- Phase 2: Write --
    get_context().phase = "write"
    t_write = time.time()
    snap_write = _active_tracker().snapshot()

    write_item_results, articles_written = run_write_phase(
        classified_items=classified_items,
        store=ctx.store,
        model=ctx.model,
        workers=ctx.workers,
        cancel_event=ctx.cancel_event,
        emit=ctx.emit,
    )

    item_results.extend(write_item_results)

    write_duration = time.time() - t_write
    write_delta = _active_tracker().delta(snap_write)
    w_calls = len(write_delta.get("call_details", []))
    w_llm = sum(d.get("duration_s", 0.0) for d in write_delta["call_details"])
    print(
        f"[pipeline] write llm: {w_calls} calls, {w_llm:.1f}s llm time, "
        f"{write_delta['completion']} completion tokens",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[pipeline] write done: {articles_written} articles in {write_duration:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    if ctx.emit:
        ctx.emit({
            "type": "phase",
            "phase": "write",
            "duration_s": round(write_duration, 2),
            "articles": articles_written,
            "llm_calls": w_calls,
            "llm_duration_s": round(w_llm, 1),
            "cost": _build_cost_summary(write_delta),
        })

    return item_results
