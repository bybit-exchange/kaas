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

from kb_ai._context import adopt_context, cancellable, contextual_submit, get_context
from kb_ai._errors import PipelineCancelledError
from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.extract import ExtractionResult
from kb_ai.core.merge import (
    EV_MERGE_ABANDONED,
    MergeEvent,
    build_source_blocks,
    create_new_article,
    format_merge_event,
    merge_into_article,
)

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
    propagated via contextual_submit from the parent thread, and adopted as a copy
    because two things here are per-worker: the phase label naming this article,
    and the call_timeout that create_new_article / merge_into_article set and
    restore around their own calls. Neither may run on the object every sibling
    worker shares.
    """
    adopt_context(get_context(), phase=f"write:{art_path}", content_hash="")

    t_art = time.time()
    all_sources = [(ref, ch, ext) for ch, ref, ext, _action, _det in ops]
    all_hashes = [ch for ch, _ref, _ext, _action, _det in ops]
    first_create = next((det for _ch, _ref, _ext, action, det in ops if action == "create"), None)

    full_path = store.base_dir / art_path
    action = "merge" if full_path.exists() else "create"

    try:
        with cancellable(cancel_event):
            # One block per source, ordered oldest to newest, for whichever branch
            # runs: both writers take the same payload, so building it once here
            # keeps the two routes' orderings from drifting apart.
            sources = build_source_blocks(store.read_raw, all_sources)
            if action == "merge":
                # Article exists -- merge all sources in one LLM call
                old_content = store.read_article(art_path)
                events: list[MergeEvent] = []
                new_content = merge_into_article(art_path, old_content, sources,
                                                 model=model, events=events)
                # SG1-SG3, worded as the CLI route words them (the prefix is this
                # phase's own): two write phases over one layout describing the same
                # finding two ways is the drift T14 and VF6 exist to stop.
                #
                # Before the write, not after it: reporting below it loses the
                # findings of the run most worth reporting to the exception. They
                # describe what the merge produced rather than what reached disk, so
                # a failed write prints SG2's delta beside the error it also files.
                for event in events:
                    print(f"[pipeline] {format_merge_event(event).strip()}",
                          file=sys.stderr, flush=True)
                store.write_article(art_path, new_content)
                # `merged` says the sources reached the article. SG1 abandoned the
                # write precisely so they did not, so an abandoned merge is its own
                # status rather than a merge that happened to change nothing -- a
                # client reading `merged` would file the document into an article
                # that never received it. The ops still count as completed: D9
                # accepts losing the merge over losing the article's history.
                key = "abandoned" if any(e.kind == EV_MERGE_ABANDONED for e in events) else "merged"
                with write_lock:
                    for ch in all_hashes:
                        _ensure_write_result(write_results, ch)
                        write_results[ch][key].append(art_path)
            else:
                # Article doesn't exist -- combine all sources and create in one LLM call
                full_path.parent.mkdir(parents=True, exist_ok=True)
                path_parts = art_path.split("/")
                article_type = path_parts[1] if len(path_parts) > 2 else "concept"
                title = Path(art_path).stem.replace("-", " ").title()
                if first_create:
                    article_type = first_create.type or article_type
                    title = first_create.title or title

                new_content = create_new_article(article_type, title, sources, model=model)
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
        write_results[ch] = {"created": [], "merged": [], "abandoned": [], "errors": []}


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
                                if wr["abandoned"]:
                                    result["abandoned"] = wr["abandoned"]
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
        # Present only when it happened, as the two lists beside it are (SG1).
        if wr["abandoned"]:
            result["abandoned"] = wr["abandoned"]
        item_results.append(result)
        if emit:
            emit(result)

    return item_results, len(article_ops)
