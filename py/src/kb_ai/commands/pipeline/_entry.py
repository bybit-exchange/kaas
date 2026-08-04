"""Pipeline entry points -- bridge interface for Go backend.

This module provides:
- run_server_pipeline(): stdin-based bridge entry point
- run_server_pipeline_with_input(): core pipeline logic for bridge + HTTP
- run_server_index(): stdin-based bridge entry for index command
- run_server_index_with_input(): core index logic for bridge + HTTP
"""

from __future__ import annotations

import json
import sys

from kb_ai._context import get_context, set_pipeline_deadline
from kb_ai.commands.pipeline._orchestrator import PipelineContext, run_pipeline_orchestrated
from kb_ai.storage.index import SUMMARY_MAX_CHARS, update_markdown_index
from kb_ai.llm import tracker
from kb_ai.core.people import update_people_stubs
from kb_ai.storage.store import KBStore

_DEFAULT_WORKERS = 16


def run_server_pipeline_with_input(input_data: dict, emit=None, cancel_event=None) -> list[dict]:
    """Core pipeline logic that accepts a dict and returns results list.

    Used by both the stdin-based bridge (run_server_pipeline) and the HTTP server.
    When emit is provided, per-item results are streamed as each article completes.

    Sets up ThreadContext at entry point: deadline, cancel_event, emit.
    """
    # Set up context for this pipeline run
    ctx = get_context()
    if cancel_event:
        ctx.cancel_event = cancel_event

    deadline_seconds = input_data.get("deadline_seconds")
    if deadline_seconds and deadline_seconds > 0:
        set_pipeline_deadline(deadline_seconds)

    try:
        return _run_pipeline_inner(input_data, emit, cancel_event=cancel_event)
    finally:
        set_pipeline_deadline(None)
        ctx.cancel_event = None


def _run_pipeline_inner(input_data: dict, emit=None, cancel_event=None) -> list[dict]:
    kb_dir = input_data["kb_dir"]
    model = input_data.get("model", "claude-sonnet-4-6")
    classify_model = input_data.get("classify_model", "") or model
    categories = input_data.get("categories", ["concept", "project", "decision", "person"])
    workers = input_data.get("workers", _DEFAULT_WORKERS)
    items = input_data["items"]
    topic_index_min_articles = int(input_data.get("topic_index_min_articles") or 3)
    summary_max_chars = int(input_data.get("summary_max_chars") or SUMMARY_MAX_CHARS)
    people_cfg = input_data.get("people") or []

    store = KBStore(kb_dir)

    pipeline_ctx = PipelineContext(
        store=store,
        model=model,
        classify_model=classify_model,
        categories=list(categories),
        workers=workers,
        cancel_event=cancel_event,
        emit=emit,
    )

    item_results = run_pipeline_orchestrated(pipeline_ctx, items)

    # ── Phase 3: Update indices once ──
    update_markdown_index(store, min_articles=topic_index_min_articles,
                          summary_max_chars=summary_max_chars)
    update_people_stubs(store, people_cfg)

    return item_results


def run_server_pipeline():
    """Stdin-based bridge entry point. Delegates to run_server_pipeline_with_input."""
    from kb_ai.__main__ import respond

    input_data = json.loads(sys.stdin.read())
    item_results = run_server_pipeline_with_input(input_data)
    respond(True, data={
        "results": item_results,
        "cost": tracker.summary(),
    })


def run_server_index_with_input(input_data: dict) -> dict:
    """Core index logic that accepts a dict and returns result.

    Used by both the stdin-based bridge (run_server_index) and the HTTP server.
    """
    kb_dir = input_data["kb_dir"]
    topic_index_min_articles = int(input_data.get("topic_index_min_articles") or 3)
    summary_max_chars = int(input_data.get("summary_max_chars") or SUMMARY_MAX_CHARS)
    people_cfg = input_data.get("people") or []

    store = KBStore(kb_dir)

    update_markdown_index(store, min_articles=topic_index_min_articles,
                          summary_max_chars=summary_max_chars)
    update_people_stubs(store, people_cfg)

    article_count = sum(1 for _ in store.wiki_dir.rglob("*.md")) if store.wiki_dir.exists() else 0
    return {"indexed": article_count}


def run_server_index():
    """Stdin-based bridge entry point for index. Delegates to run_server_index_with_input."""
    from kb_ai.__main__ import respond

    input_data = json.loads(sys.stdin.read())
    result = run_server_index_with_input(input_data)
    respond(True, data=result)
