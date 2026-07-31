"""Offline tests for the pipeline dedup phase (kb_ai.commands.pipeline._phase_dedup).

Dedup is pure string work (no LLM), so these tests drive it directly. What
matters: the cancellation short-circuit, the cheap bail-outs that must not touch
the items, and the real cross-group merge -- two classify groups that
independently invented the same article must end up with one of them turned into
a merge.
"""
from __future__ import annotations

import threading

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.commands.pipeline._phase_dedup import run_dedup_phase
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import ArticleMeta


# ── helpers ─────────────────────────────────────────────────────────

def item(content_hash: str, *, creates=(), merges=()):
    """Build one classified_items entry: (hash, source_ref, extraction, classification)."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path=p, type="concept", title=t) for p, t in creates],
        merge_into=[MergeTarget(path=p) for p in merges],
    )
    return (
        content_hash,
        f"raw/{content_hash}.md",
        ExtractionResult(summary=f"sum {content_hash}"),
        classification,
    )


def created_titles(entry) -> list[str]:
    return [c.title for c in entry[3].create_new]


def merged_paths(entry) -> list[str]:
    return [m.path for m in entry[3].merge_into]


# ── cancellation ────────────────────────────────────────────────────

def test_dedup_leaves_items_untouched_when_cancelled():
    """A set cancel event must skip the work, not silently half-dedup."""
    cancel = threading.Event()
    cancel.set()
    items = [
        item("h1", creates=[("wiki/concept/foo-bar.md", "Foo Bar")]),
        item("h2", creates=[("wiki/concept/foo-bar-2.md", "Foo Bar")]),
    ]

    result, count = run_dedup_phase(items, [], cancel_event=cancel)

    assert count == 0
    assert [created_titles(e) for e in result] == [["Foo Bar"], ["Foo Bar"]]
    assert [merged_paths(e) for e in result] == [[], []]


def test_dedup_runs_when_the_cancel_event_is_unset():
    cancel = threading.Event()
    items = [
        item("h1", creates=[("wiki/concept/foo-bar.md", "Foo Bar")]),
        item("h2", creates=[("wiki/concept/foo-bar-2.md", "Foo Bar")]),
    ]

    _result, count = run_dedup_phase(items, [], cancel_event=cancel)

    assert count == 2


# ── cheap bail-outs ─────────────────────────────────────────────────

def test_dedup_skips_an_empty_item_list():
    result, count = run_dedup_phase([], [])
    assert result == []
    assert count == 0


def test_dedup_skips_a_single_item():
    """One item has nothing to collide with, even against itself."""
    items = [item("h1", creates=[
        ("wiki/concept/foo.md", "Foo Bar"),
        ("wiki/concept/foo-2.md", "Foo Bar"),
    ])]

    result, count = run_dedup_phase(items, [])

    assert count == 0
    assert created_titles(result[0]) == ["Foo Bar", "Foo Bar"]


def test_dedup_skips_when_no_item_created_anything():
    """Merge-only results have no new titles to cross-check."""
    items = [
        item("h1", merges=["wiki/concept/a.md"]),
        item("h2", merges=["wiki/concept/b.md"]),
    ]

    result, count = run_dedup_phase(items, [ArticleMeta(title="A", path="wiki/concept/a.md")])

    assert count == 0
    assert [merged_paths(e) for e in result] == [["wiki/concept/a.md"], ["wiki/concept/b.md"]]


# ── cross-group merging ─────────────────────────────────────────────

def test_dedup_merges_a_title_two_groups_invented_independently():
    items = [
        item("h1", creates=[("wiki/concept/vector-search.md", "Vector Search")]),
        item("h2", creates=[("wiki/concept/vector-search-basics.md", "Vector Search")]),
    ]

    result, count = run_dedup_phase(items, [])

    assert count == 2
    # Each item drops its own create and points at the other item's path.
    assert created_titles(result[0]) == []
    assert merged_paths(result[0]) == ["wiki/concept/vector-search-basics.md"]
    assert created_titles(result[1]) == []
    assert merged_paths(result[1]) == ["wiki/concept/vector-search.md"]
    assert "dedup: title overlap" in result[0][3].merge_into[0].reason


def test_dedup_keeps_unrelated_titles():
    items = [
        item("h1", creates=[("wiki/concept/kubernetes.md", "Kubernetes")]),
        item("h2", creates=[("wiki/concept/postgres.md", "Postgres")]),
    ]

    result, count = run_dedup_phase(items, [])

    assert count == 0
    assert created_titles(result[0]) == ["Kubernetes"]
    assert created_titles(result[1]) == ["Postgres"]


def test_dedup_does_not_collide_an_item_with_its_own_creates():
    """own_paths must be excluded, or every item would merge into itself."""
    items = [
        item("h1", creates=[
            ("wiki/concept/foo.md", "Foo Bar"),
            ("wiki/concept/foo-2.md", "Foo Bar"),
        ]),
        item("h2", creates=[("wiki/concept/unrelated.md", "Unrelated")]),
    ]

    result, count = run_dedup_phase(items, [])

    assert count == 0
    assert created_titles(result[0]) == ["Foo Bar", "Foo Bar"]


def test_dedup_merges_against_a_preexisting_article():
    base = [ArticleMeta(title="Vector Search", path="wiki/concept/existing.md")]
    items = [
        item("h1", creates=[("wiki/concept/vector-search.md", "Vector Search")]),
        item("h2", creates=[("wiki/concept/unrelated.md", "Unrelated")]),
    ]

    result, count = run_dedup_phase(items, base)

    assert count == 1
    assert created_titles(result[0]) == []
    assert merged_paths(result[0]) == ["wiki/concept/existing.md"]
    assert created_titles(result[1]) == ["Unrelated"]


def test_dedup_reports_the_merge_count_on_stderr(capsys):
    items = [
        item("h1", creates=[("wiki/concept/vector-search.md", "Vector Search")]),
        item("h2", creates=[("wiki/concept/vector-search-2.md", "Vector Search")]),
    ]

    run_dedup_phase(items, [])

    assert "cross-group dedup: 2 articles merged" in capsys.readouterr().err


def test_dedup_stays_quiet_when_nothing_merged(capsys):
    items = [
        item("h1", creates=[("wiki/concept/kubernetes.md", "Kubernetes")]),
        item("h2", creates=[("wiki/concept/postgres.md", "Postgres")]),
    ]

    run_dedup_phase(items, [])

    assert "cross-group dedup" not in capsys.readouterr().err


def test_dedup_preserves_the_hash_ref_and_extraction_of_each_item():
    """Rewriting classifications must not shuffle the tuple's other fields."""
    items = [
        item("h1", creates=[("wiki/concept/vector-search.md", "Vector Search")]),
        item("h2", creates=[("wiki/concept/vector-search-2.md", "Vector Search")]),
    ]

    result, _count = run_dedup_phase(items, [])

    assert [e[0] for e in result] == ["h1", "h2"]
    assert [e[1] for e in result] == ["raw/h1.md", "raw/h2.md"]
    assert [e[2].summary for e in result] == ["sum h1", "sum h2"]
