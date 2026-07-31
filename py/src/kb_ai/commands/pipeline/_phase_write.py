"""Write phase -- parallel article writing using contextual_submit.

This module handles:
- Grouping classified items by target article path
- Path validation (wiki/ prefix, no escape)
- Parallel article creation/merge via ThreadPoolExecutor + contextual_submit
- Error recovery: failed writes don't crash the pipeline
- cancel_event propagation for graceful shutdown
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from openai import APIError as LLMAPIError

from kb_ai._context import cancellable, contextual_submit, get_context
from kb_ai._errors import PipelineCancelledError
from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.commands.compile import _combine_extractions
from kb_ai.core.extract import ExtractionResult
from kb_ai.core.merge import create_new_article, merge_into_article

if TYPE_CHECKING:
    from kb_ai.storage.store import KBStore


def _process_article(
    art_path: str,
    ops: list[tuple[str, str, ExtractionResult, str, CreateTarget | MergeTarget]],
    store: "KBStore",
    model: str,
    cancel_event: threading.Event | None,
    write_results: dict[str, dict],
    write_lock: threading.Lock,
) -> None:
    """Process a single article: create or merge all operations.

    Context (deadline, cancel_event, etc.) is obtained from get_context(),
    propagated via contextual_submit from the parent thread.
    """
    ctx = get_context()
    ctx.phase = "write"
    ctx.content_hash = ""

    t_art = time.time()
    all_sources = [(ref, ext) for _ch, ref, ext, _action, _det in ops]
    all_hashes = [ch for ch, _ref, _ext, _action, _det in ops]
    first_create = next((det for _ch, _ref, _ext, action, det in ops if action == "create"), None)

    full_path = store.base_dir / art_path
    action = "merge" if full_path.exists() else "create"

    try:
        with cancellable(cancel_event):
            if action == "merge":
                # Article exists -- merge all sources in one LLM call
                combined, merge_refs = _combine_extractions(all_sources)
                old_content = store.read_article(art_path)
                new_content = merge_into_article(art_path, old_content, combined, ", ".join(merge_refs), model=model)
                store.write_article(art_path, new_content)
                with write_lock:
                    for ch in all_hashes:
                        _ensure_write_result(write_results, ch)
                        write_results[ch]["merged"].append(art_path)
            else:
                # Article doesn't exist -- combine all sources and create in one LLM call
                full_path.parent.mkdir(parents=True, exist_ok=True)
                path_parts = art_path.split("/")
                article_type = path_parts[1] if len(path_parts) > 2 else "concept"
                title = Path(art_path).stem.replace("-", " ").title()
                if first_create:
                    article_type = first_create.type or article_type
                    title = first_create.title or title

                combined, merge_refs = _combine_extractions(all_sources)
                new_content = create_new_article(article_type, title, combined, ", ".join(merge_refs), model=model)
                store.write_article(art_path, new_content)
                with write_lock:
                    for ch in all_hashes:
                        _ensure_write_result(write_results, ch)
                        write_results[ch]["created"].append(art_path)
    except PipelineCancelledError:
        err_msg = "pipeline cancelled: client disconnected"
        with write_lock:
            for ch in all_hashes:
                _ensure_write_result(write_results, ch)
                write_results[ch]["errors"].append({"path": art_path, "error": err_msg})
    except Exception as e:
        prefix = "LLM Error" if isinstance(e, LLMAPIError) else "Error"
        err_msg = f"{prefix} (Write/{action}: {art_path}): {e}"
        with write_lock:
            for ch in all_hashes:
                _ensure_write_result(write_results, ch)
                write_results[ch]["errors"].append({"path": art_path, "error": err_msg})

    art_duration = time.time() - t_art
    print(
        f"[pipeline] write {action}: {art_path} ({len(ops)} ops, {art_duration:.1f}s)",
        file=sys.stderr,
        flush=True,
    )


def _ensure_write_result(write_results: dict[str, dict], ch: str) -> None:
    """Ensure a write_results entry exists for the given content_hash."""
    if ch not in write_results:
        write_results[ch] = {"created": [], "merged": [], "errors": []}


def run_write_phase(
    classified_items: list[tuple[str, str, ExtractionResult, ClassificationResult]],
    store: "KBStore",
    model: str = "claude-sonnet-4-6",
    workers: int = 16,
    cancel_event: threading.Event | None = None,
    emit: Callable[[dict], None] | None = None,
) -> tuple[list[dict], int]:
    """Execute the write phase: group by article, then parallel write.

    Args:
        classified_items: list of (content_hash, source_ref, extraction, classification)
        store: KBStore instance for reading/writing articles
        model: LLM model name for article generation
        workers: max number of parallel write workers
        cancel_event: optional threading.Event for cancellation
        emit: optional callback for streaming per-item results

    Returns:
        Tuple of (item_results list, articles_written count)
    """
    # Article paths come from LLM output, so containment must be checked against
    # the wiki subtree itself -- a path like "wiki/../raw/a.md" passes the wiki/
    # prefix check and still resolves inside kb_dir.
    wiki_root = (store.base_dir / "wiki").resolve()

    # Group by target article path, validate paths
    article_ops: dict[str, list[tuple[str, str, ExtractionResult, str, CreateTarget | MergeTarget]]] = {}
    item_results: list[dict] = []
    item_has_ops: dict[str, bool] = {}

    for content_hash, source_ref, extraction, classification in classified_items:
        has_ops = False
        for entry in classification.create_new:
            art_path = entry.path
            if not art_path.startswith("wiki/"):
                item_results.append({
                    "content_hash": content_hash,
                    "status": "error",
                    "error": f"invalid path: must start with wiki/ (got {art_path})",
                    "phase": "write",
                })
                continue
            full_resolved = (store.base_dir / art_path).resolve()
            if not str(full_resolved).startswith(str(wiki_root) + os.sep):
                item_results.append({
                    "content_hash": content_hash,
                    "status": "error",
                    "error": f"path escapes wiki/: {art_path}",
                    "phase": "write",
                })
                continue
            article_ops.setdefault(art_path, []).append((content_hash, source_ref, extraction, "create", entry))
            has_ops = True

        for entry in classification.merge_into:
            art_path = entry.path
            if not art_path.startswith("wiki/"):
                item_results.append({
                    "content_hash": content_hash,
                    "status": "error",
                    "error": f"invalid path: must start with wiki/ (got {art_path})",
                    "phase": "write",
                })
                continue
            full_resolved = (store.base_dir / art_path).resolve()
            if not str(full_resolved).startswith(str(wiki_root) + os.sep):
                item_results.append({
                    "content_hash": content_hash,
                    "status": "error",
                    "error": f"path escapes wiki/: {art_path}",
                    "phase": "write",
                })
                continue
            article_ops.setdefault(art_path, []).append((content_hash, source_ref, extraction, "merge", entry))
            has_ops = True

        if has_ops:
            item_has_ops[content_hash] = True
        elif content_hash not in {r["content_hash"] for r in item_results}:
            # No ops and no errors - item classified but resulted in nothing
            result = {
                "content_hash": content_hash,
                "status": "ok",
                "created": [],
                "merged": [],
            }
            item_results.append(result)
            if emit:
                emit(result)

    # Write phase
    write_results: dict[str, dict] = {}
    write_lock = threading.Lock()
    emitted_hashes: set[str] = set()

    if article_ops:
        write_workers = min(len(article_ops), workers)
        with ThreadPoolExecutor(max_workers=write_workers) as pool:
            futures = {
                contextual_submit(
                    pool,
                    _process_article,
                    path,
                    ops,
                    store,
                    model,
                    cancel_event,
                    write_results,
                    write_lock,
                ): path
                for path, ops in article_ops.items()
            }

            for future in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    completed_writes = sum(1 for f in futures if f.done())
                    total_writes = len(futures)
                    print(
                        f"[pipeline] cancel detected in write: "
                        f"completed={completed_writes}/{total_writes} articles",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                try:
                    future.result()
                except Exception as e:
                    path = futures[future]
                    with write_lock:
                        for op in article_ops.get(path, []):
                            ch = op[0]
                            _ensure_write_result(write_results, ch)
                            write_results[ch]["errors"].append({"path": path, "error": str(e)})

                # Emit per-item progress for completed content_hashes after each article
                path = futures[future]
                with write_lock:
                    for op in article_ops.get(path, []):
                        ch = op[0]
                        if ch in write_results and ch not in emitted_hashes:
                            # Check if all articles for this content_hash are done
                            all_article_paths = [p for p, ops_list in article_ops.items()
                                                 for o in ops_list if o[0] == ch]
                            done_paths = {futures[f] for f in futures if f.done()}
                            if all(p in done_paths for p in all_article_paths):
                                emitted_hashes.add(ch)
                                wr = write_results[ch]
                                result = {"content_hash": ch}
                                if wr["errors"]:
                                    result["status"] = "error"
                                    result["error"] = "; ".join(e["error"] for e in wr["errors"])
                                else:
                                    result["status"] = "ok"
                                if wr["created"]:
                                    result["created"] = wr["created"]
                                if wr["merged"]:
                                    result["merged"] = wr["merged"]
                                item_results.append(result)
                                if emit:
                                    emit(result)

            # Cancel pending write futures if cancelled
            if cancel_event and cancel_event.is_set():
                for f in futures:
                    f.cancel()

    # Build final per-item results for any remaining (not yet emitted)
    for ch, wr in write_results.items():
        if ch in emitted_hashes:
            continue
        result = {"content_hash": ch}
        if wr["errors"]:
            result["status"] = "error"
            result["error"] = "; ".join(e["error"] for e in wr["errors"])
        else:
            result["status"] = "ok"
        if wr["created"]:
            result["created"] = wr["created"]
        if wr["merged"]:
            result["merged"] = wr["merged"]
        item_results.append(result)
        if emit:
            emit(result)

    return item_results, len(article_ops)
