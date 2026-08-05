"""Dedup phase -- cross-group deduplication of classification results.

String-based title-overlap dedup (no embeddings). After parallel classify,
different groups may have independently created articles with similar titles.
This phase elects one of them to be created and turns the rest into merges into
the winner.
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

    # First writer wins. Walk the items in order and dedup each one against the
    # creations accepted so far, so exactly one item keeps the create and the
    # rest point at it. Deduping every item against every other item instead
    # makes collisions cancel out: two items merge into each other, neither
    # keeps its create, and the write phase -- which creates any merge target
    # that does not exist yet -- writes both paths after all.
    #
    # An item's own creations join the pool only once the whole item is done, so
    # a classification that deliberately split one document into two articles
    # keeps both.
    accepted: list[ArticleMeta] = list(base_existing)
    accepted_paths = {a.path for a in accepted}
    deduped_count = 0

    for i, (content_hash, source_ref, extraction, classification) in enumerate(classified_items):
        before = len(classification.create_new)
        classification = dedup_create_new(classification, accepted)
        deduped_count += before - len(classification.create_new)

        for create in classification.create_new:
            if create.path in accepted_paths:
                continue
            accepted.append(ArticleMeta(title=create.title, path=create.path, summary=""))
            accepted_paths.add(create.path)

        classified_items[i] = (content_hash, source_ref, extraction, classification)

    if deduped_count > 0:
        noun = "article" if deduped_count == 1 else "articles"
        print(
            f"[pipeline] cross-group dedup: {deduped_count} {noun} merged",
            file=sys.stderr,
            flush=True,
        )

    return classified_items, deduped_count
