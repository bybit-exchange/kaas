"""LLM topic filter over a catalog listing (spec A1-A8).

Two passes use this module with opposite inclusion instructions (spec O4):
RECALL over the source catalog, where a miss loses documents permanently, and
PRECISION over the derived catalog, where every article already came from
topical documents so a permissive prompt would select everything.

There is no top-K cap, which is what makes batching cheap: the batches only need
unioning, never a global ranking.
"""
from __future__ import annotations

import math
import os
import sys

from kb_ai._errors import DeriveError, TopicTooLargeError
from kb_ai.derive._types import (
    MODE_PRECISION,
    MODE_RECALL,
    SelectionResult,
    Skipped,
)
from kb_ai.llm import MAX_PROMPT_CHARS, completion_json
from kb_ai.storage.store import ArticleMeta, render_catalog_line

_FILTER_DEBUG = os.environ.get("KAAS_FILTER_DEBUG") == "1"

# Headroom over the measured skeleton, mirroring core/merge.py's _SAFETY_MARGIN
# habit: the skeleton is measured, not guessed, and this absorbs the difference
# between characters and whatever the gateway counts.
_SAFETY_MARGIN = 2_000

_INSTRUCTION = {
    MODE_RECALL: (
        "Include an article if it could contribute to understanding the topic, "
        "even peripherally. Missing a relevant article permanently loses the "
        "documents behind it, so prefer including a borderline article."
    ),
    MODE_PRECISION: (
        "Include an article only if it is substantially about the topic. A "
        "peripheral mention does not qualify. Every article listed here was "
        "already judged related to the topic once, so judging by that standard "
        "again would select everything and decide nothing."
    ),
}


def build_prompt(topic: str, mode: str, listing: str) -> str:
    """Render the filter prompt. listing="" gives the skeleton, for budgeting."""
    try:
        instruction = _INSTRUCTION[mode]
    except KeyError:
        raise ValueError(f"unknown filter mode: {mode!r}") from None
    return (
        "You are selecting which knowledge-base articles belong to a topic. "
        "Below is the article catalog (path — title: summary). An article that "
        "documents a table of settings, fields or endpoints also lists their "
        "names after `| keys:`, so a topic naming one specific named value "
        "belongs to the article whose keys contain it.\n\n"
        f"{listing}\n\n"
        f"Topic: {topic}\n\n"
        f"{instruction}\n\n"
        "Return JSON {\"paths\": [...]} listing every matching article path, "
        "verbatim from the catalog. There is no limit on how many you may "
        "return. Return an empty list if none match."
    )


def pack_batches(catalog: list[ArticleMeta],
                 budget: int) -> tuple[list[list[ArticleMeta]], list[Skipped]]:
    """Greedily pack catalog entries into batches whose listing fits budget (A6).

    A single line longer than a whole batch is dropped as line_over_budget rather
    than making the run unschedulable (A8).
    """
    batches: list[list[ArticleMeta]] = []
    skipped: list[Skipped] = []
    current: list[ArticleMeta] = []
    size = 0

    for article in catalog:
        cost = len(render_catalog_line(article)) + 1  # + the joining newline
        if cost > budget:
            skipped.append(Skipped(ref=article.path, reason="line_over_budget"))
            continue
        if current and size + cost > budget:
            batches.append(current)
            current, size = [], 0
        current.append(article)
        size += cost

    if current:
        batches.append(current)
    return batches, skipped


def select_by_topic(catalog: list[ArticleMeta], topic: str, mode: str,
                    *, model: str,
                    filter_rounds: int = 3) -> SelectionResult:
    """Every catalog path the model judged part of the topic (A1-A8).

    Uncapped, filtered to catalog membership, de-duplicated preserving first-seen
    order. An empty catalog returns early without an LLM call (A2). Any LLM or
    response-shape failure raises DeriveError (A3): unlike retrieval, this cannot
    degrade to [] -- an empty selection would silently build an empty KB.
    """
    if filter_rounds < 1:
        raise ValueError(
            f"filter_rounds must be \u2265 1, got {filter_rounds}"
        )

    if not catalog:
        return SelectionResult(paths=[], batches=0, dropped_invented=0, skipped=[])

    # supermajority: at least ⌈2N/3⌉ rounds must select a path
    threshold = math.ceil(filter_rounds * 2 / 3)

    valid = {a.path for a in catalog}
    budget = MAX_PROMPT_CHARS - len(build_prompt(topic, mode, "")) - _SAFETY_MARGIN
    if budget <= 0:
        # Every catalog line would be dropped as line_over_budget and the run
        # would fail as NO_DOCUMENTS, blaming the catalog for a topic-length
        # problem. A8 drops individual oversized lines; it does not cover a topic
        # that leaves no room for any line at all.
        raise TopicTooLargeError(
            f"the {len(topic)}-character topic leaves no room for catalog lines "
            f"within the {MAX_PROMPT_CHARS}-character prompt budget; shorten the "
            "topic"
        )
    batches, skipped = pack_batches(catalog, budget)

    if filter_rounds > 1:
        print(
            f"[filter] voting: {filter_rounds} rounds, "
            f"threshold \u2265{threshold}/{filter_rounds}",
            file=sys.stderr,
        )

    paths: list[str] = []
    seen: set[str] = set()
    dropped = 0

    for i, batch in enumerate(batches):
        listing = "\n".join(render_catalog_line(a) for a in batch)
        prompt = build_prompt(topic, mode, listing)
        batch_valid = {a.path for a in batch}
        vote_counts: dict[str, int] = {}
        invented: set[str] = set()

        for _round in range(filter_rounds):
            try:
                result = completion_json(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e:  # noqa: BLE001 -- re-raised as typed domain error
                raise DeriveError(f"topic filter failed: {e}") from e

            raw = result.get("paths") if isinstance(result, dict) else None
            if not isinstance(raw, list):
                raise DeriveError(
                    "topic filter returned no paths list; refusing to treat "
                    "that as 'nothing matches'"
                )
            for p in raw:
                if not isinstance(p, str) or p not in valid:
                    invented.add(repr(p))
                    continue
                if p in batch_valid:
                    vote_counts[p] = vote_counts.get(p, 0) + 1

        dropped += len(invented)

        survivors: list[str] = []
        for p, v in vote_counts.items():
            if _FILTER_DEBUG:
                mark = "\u2713" if v >= threshold else "\u2717"
                print(
                    f"[filter]   {p}: {v}/{filter_rounds} votes {mark}",
                    file=sys.stderr,
                )
            if v >= threshold and p not in seen:
                seen.add(p)
                survivors.append(p)
                paths.append(p)

        if filter_rounds > 1:
            candidates = len(batch_valid)
            print(
                f"[filter] batch {i + 1}/{len(batches)}: "
                f"{len(survivors)} of {candidates} paths passed voting "
                f"({filter_rounds} rounds)",
                file=sys.stderr,
            )

    return SelectionResult(paths=paths, batches=len(batches),
                           dropped_invented=dropped, skipped=skipped)
