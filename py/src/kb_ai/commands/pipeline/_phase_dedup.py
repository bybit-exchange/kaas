"""Dedup phase -- cross-group deduplication of classification results.

String-based title-overlap dedup (no embeddings). After parallel classify,
different groups may have independently created articles with similar titles.
This phase deduplicates them against each other.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from kb_ai._types import ClassificationResult
from kb_ai.core.classify import dedup_create_new
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import ArticleMeta

if TYPE_CHECKING:
    import threading


def run_dedup_phase(
    classified_items: list[tuple[str, str, ExtractionResult, ClassificationResult]],
    base_existing: list[ArticleMeta],
    cancel_event: "threading.Event | None" = None,
) -> tuple[list[tuple[str, str, ExtractionResult, ClassificationResult]], int]:
    """Execute the dedup phase: cross-group string-based title dedup.

    Args:
        classified_items: list of (content_hash, source_ref, extraction, classification)
        base_existing: existing articles in the KB before this pipeline run
        cancel_event: optional threading.Event for cancellation

    Returns:
        Tuple of (deduplicated classified_items, dedup count)
    """
    if cancel_event and cancel_event.is_set():
        return classified_items, 0

    if len(classified_items) <= 1:
        return classified_items, 0

    # Collect all new articles across all items
    all_new_articles: list[ArticleMeta] = []
    for _ch, _ref, _ext, classification in classified_items:
        for create in classification.create_new:
            all_new_articles.append(ArticleMeta(
                title=create.title, path=create.path, summary="",
            ))

    if not all_new_articles:
        return classified_items, 0

    deduped_count = 0
    for i, (content_hash, source_ref, extraction, classification) in enumerate(classified_items):
        own_paths = {c.path for c in classification.create_new}
        cross_existing = list(base_existing) + [
            a for a in all_new_articles if a.path not in own_paths
        ]
        before = len(classification.create_new)
        classification = dedup_create_new(classification, cross_existing)
        after = len(classification.create_new)
        deduped_count += before - after
        classified_items[i] = (content_hash, source_ref, extraction, classification)

    if deduped_count > 0:
        print(
            f"[pipeline] cross-group dedup: {deduped_count} articles merged",
            file=sys.stderr,
            flush=True,
        )

    return classified_items, deduped_count
