"""Classify phase -- topic-clustered parallel classification.

This module handles:
- Clustering items by topic overlap (Union-Find with max_group_size cap)
- Parallel group classification via ThreadPoolExecutor + contextual_submit
- Serial within-group classification maintaining existing accumulation
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from openai import APIError as LLMAPIError

from kb_ai._context import cancellable, contextual_submit, get_context
from kb_ai._types import ClassificationResult
from kb_ai.core.classify import (
    DEFAULT_CATEGORIES,
    classify_article,
    classify_cache_key,
    dedup_create_new,
    hash_existing_articles,
)
from kb_ai.core.extract import ExtractionResult, parse_extraction_result
from kb_ai.storage.store import ArticleMeta

if TYPE_CHECKING:
    from kb_ai.storage.store import KBStore

_MAX_CLASSIFY_GROUPS = 8


def _cluster_by_topic_overlap(
    items: list[dict],
    string_threshold: float = 0.3,
    max_group_size: int = 8,
) -> list[list[int]]:
    """Cluster items by topic/concept string overlap.

    Two items are unioned when their topic/concept sets overlap by
    >= string_threshold (intersection / smaller set). Groups are capped at
    max_group_size to prevent transitive closure from merging the entire batch
    into one serial chain.
    """
    n = len(items)
    if n <= 1:
        return [list(range(n))]

    topic_sets: list[set] = []
    for item in items:
        ext = item["extraction"]
        topics = [t for t in (ext.get("topics") or []) if isinstance(t, str)]
        concepts = [
            c["title"] if isinstance(c, dict) else c
            for c in (ext.get("concepts") or [])
            if (isinstance(c, dict) and c.get("title")) or isinstance(c, str)
        ]
        topic_sets.append(set(t.lower() for t in topics + concepts))

    parent = list(range(n))
    size = [1] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b) -> bool:
        pa, pb = find(a), find(b)
        if pa == pb:
            return True
        if size[pa] + size[pb] > max_group_size:
            return False
        if size[pa] < size[pb]:
            pa, pb = pb, pa
        parent[pb] = pa
        size[pa] += size[pb]
        return True

    # Order pairs by overlap strength descending so the strongest links form first.
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if topic_sets[i] and topic_sets[j]:
                overlap = len(topic_sets[i] & topic_sets[j])
                smaller = min(len(topic_sets[i]), len(topic_sets[j]))
                if smaller > 0 and overlap / smaller >= string_threshold:
                    pairs.append((overlap / smaller, i, j))

    pairs.sort(reverse=True)
    for _, i, j in pairs:
        union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    return list(groups.values())


def _classify_group(
    group_items: list[dict],
    existing: list,
    classify_model: str,
    categories: list[str],
    store: "KBStore",
    art_hash: str,
    cat_hash: str,
) -> list[tuple]:
    """Classify a group of items serially, maintaining existing accumulation within group.

    Context (deadline, cancel_event, emit, etc.) is obtained from get_context(),
    which is propagated via contextual_submit from the parent thread.
    """
    ctx = get_context()
    ctx.phase = "classify"

    results = []
    for item in group_items:
        extraction_dict = item["extraction"]
        content_hash = item.get("content_hash", "")
        source_ref = item.get("source_ref", "unknown")
        ctx.content_hash = content_hash

        try:
            extraction = parse_extraction_result(extraction_dict)
            extraction.source_path = source_ref

            classification: ClassificationResult | None = None
            cache_key_used = ""
            if content_hash:
                cache_key_used = classify_cache_key(content_hash, art_hash, cat_hash)
                cached_dict = store.load_classify_cache(cache_key_used)
                if cached_dict is not None:
                    classification = ClassificationResult.from_dict(cached_dict)

            if classification is None:
                classification = classify_article(
                    extraction, existing, model=classify_model, categories=categories)
                if content_hash and cache_key_used:
                    store.save_classify_cache(cache_key_used, classification.to_dict())

            classification = dedup_create_new(classification, existing)

            for create in classification.create_new:
                existing.append(ArticleMeta(
                    title=create.title, path=create.path, summary="",
                ))

            results.append(("ok", content_hash, source_ref, extraction, classification))

        except Exception as e:
            prefix = "LLM Error" if isinstance(e, LLMAPIError) else "Error"
            err_msg = f"{prefix} (Classify): {e}"
            results.append(("error", content_hash, source_ref, None, err_msg))

    return results


def run_classify_phase(
    items: list[dict],
    store: "KBStore",
    classify_model: str = "claude-sonnet-4-6",
    categories: list[str] | None = None,
    cancel_event=None,
) -> tuple[list[tuple[str, str, ExtractionResult, ClassificationResult]], list[dict]]:
    """Execute the classify phase: topic-clustered parallel classification.

    Returns:
    - classified_items: list of (content_hash, source_ref, extraction, classification)
    - errors: list of error dicts with content_hash, status, error, phase
    """
    if categories is None:
        categories = list(DEFAULT_CATEGORIES)

    base_existing = store.existing_articles()
    cat_hash = hashlib.sha256(
        json.dumps(categories, sort_keys=True).encode()
    ).hexdigest()[:8]
    art_hash = hash_existing_articles(base_existing)

    groups = _cluster_by_topic_overlap(items)
    max_group = max(len(g) for g in groups) if groups else 0
    print(
        f"[pipeline] clustered {len(items)} items into {len(groups)} groups "
        f"(max group size: {max_group})",
        file=sys.stderr,
        flush=True,
    )

    classified_items: list[tuple[str, str, ExtractionResult, ClassificationResult]] = []
    errors: list[dict] = []

    if len(groups) == 1:
        # Single group -- run serially in-place (no thread overhead)
        with cancellable(cancel_event):
            results = _classify_group(
                items, list(base_existing), classify_model, categories, store, art_hash, cat_hash,
            )
        for status, content_hash, source_ref, extraction, data in results:
            if status == "ok":
                classified_items.append((content_hash, source_ref, extraction, data))
            else:
                errors.append({
                    "content_hash": content_hash,
                    "status": "error",
                    "error": data,
                    "phase": "classify",
                })
    else:
        # Multiple groups -- run in parallel using contextual_submit
        num_workers = min(len(groups), _MAX_CLASSIFY_GROUPS)
        all_group_results: list[tuple[list[int], list[tuple]]] = []

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {}
            for group_indices in groups:
                group_items = [items[i] for i in group_indices]

                def _classify_with_cancel(g_items=group_items, g_existing=list(base_existing)):
                    with cancellable(cancel_event):
                        return _classify_group(
                            g_items, g_existing, classify_model, categories,
                            store, art_hash, cat_hash,
                        )

                future = contextual_submit(pool, _classify_with_cancel)
                futures[future] = group_indices

            for future in as_completed(futures):
                group_indices = futures[future]
                if cancel_event and cancel_event.is_set():
                    completed_groups = len(all_group_results)
                    total_groups = len(groups)
                    print(
                        f"[pipeline] cancel detected in classify: "
                        f"completed={completed_groups}/{total_groups} groups",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                try:
                    results = future.result()
                    all_group_results.append((group_indices, results))
                except Exception as e:
                    for idx in group_indices:
                        item = items[idx]
                        errors.append({
                            "content_hash": item.get("content_hash", ""),
                            "status": "error",
                            "error": str(e),
                            "phase": "classify",
                        })

            # Cancel pending futures if cancelled
            if cancel_event and cancel_event.is_set():
                for f in futures:
                    f.cancel()

        for _indices, results in all_group_results:
            for status, content_hash, source_ref, extraction, data in results:
                if status == "ok":
                    classified_items.append((content_hash, source_ref, extraction, data))
                else:
                    errors.append({
                        "content_hash": content_hash,
                        "status": "error",
                        "error": data,
                        "phase": "classify",
                    })

    return classified_items, errors
