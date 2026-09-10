"""Tests for derive/_filter.py -- topic selection, batching, failure modes."""
from __future__ import annotations

import pytest

from kb_ai._errors import DeriveError
from kb_ai.derive import _filter
from kb_ai.derive._types import MODE_PRECISION, MODE_RECALL
from kb_ai.storage.store import ArticleMeta


def _catalog(n: int, *, summary: str = "s") -> list[ArticleMeta]:
    return [ArticleMeta(title=f"T{i}", path=f"wiki/a{i}.md", summary=summary)
            for i in range(n)]


def test_empty_catalog_makes_no_llm_call(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("completion_json must not be called")

    monkeypatch.setattr(_filter, "completion_json", boom)
    result = _filter.select_by_topic([], "pricing", MODE_RECALL, model="m")
    assert result == _filter.SelectionResult(paths=[], batches=0, dropped_invented=0, skipped=[])


def test_returns_every_selected_path_with_no_cap(monkeypatch):
    catalog = _catalog(30)
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": [a.path for a in catalog]})
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == [a.path for a in catalog]
    assert result.batches == 1


def test_drops_invented_paths_and_counts_them(monkeypatch):
    catalog = _catalog(2)
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {
        "paths": ["wiki/a0.md", "wiki/invented.md", 42, "wiki/a1.md"],
    })
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == ["wiki/a0.md", "wiki/a1.md"]
    assert result.dropped_invented == 2


def test_dedupes_preserving_first_seen_order(monkeypatch):
    catalog = _catalog(2)
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": ["wiki/a1.md", "wiki/a0.md", "wiki/a1.md"]})
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == ["wiki/a1.md", "wiki/a0.md"]
    assert result.dropped_invented == 0


def test_keys_column_reaches_the_prompt(monkeypatch):
    catalog = [ArticleMeta(title="Limits", path="wiki/limits.md", summary="Ceilings.",
                           keys="max_zip_entries")]
    seen: list[str] = []

    def capture(**kwargs):
        seen.append(kwargs["messages"][0]["content"])
        return {"paths": []}

    monkeypatch.setattr(_filter, "completion_json", capture)
    _filter.select_by_topic(catalog, "zip limits", MODE_RECALL, model="m")
    assert "max_zip_entries" in seen[0]


def test_llm_error_raises_derive_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(_filter, "completion_json", boom)
    with pytest.raises(DeriveError, match="topic filter failed"):
        _filter.select_by_topic(_catalog(1), "pricing", MODE_RECALL, model="m")


@pytest.mark.parametrize("payload", [{"paths": "wiki/a0.md"}, {}, [], None])
def test_malformed_response_raises_derive_error(monkeypatch, payload):
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: payload)
    with pytest.raises(DeriveError):
        _filter.select_by_topic(_catalog(1), "pricing", MODE_RECALL, model="m")


def test_batches_when_the_listing_exceeds_the_budget(monkeypatch):
    # 40 articles with 3K-char summaries: ~120K chars of listing against an 80K
    # prompt budget, so the pack must split.
    catalog = _catalog(40, summary="x" * 3000)
    calls: list[str] = []

    def capture(**kwargs):
        content = kwargs["messages"][0]["content"]
        calls.append(content)
        # Select only the articles this batch actually listed.
        return {"paths": [a.path for a in catalog if f"- {a.path} " in content]}

    monkeypatch.setattr(_filter, "completion_json", capture)
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m",
                                     filter_rounds=1)

    assert result.batches > 1
    assert result.batches == len(calls)
    assert sorted(result.paths) == sorted(a.path for a in catalog)  # union, not a ranking
    from kb_ai.llm import MAX_PROMPT_CHARS
    assert all(len(c) <= MAX_PROMPT_CHARS for c in calls)


def test_single_and_multi_batch_return_the_same_shape(monkeypatch):
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {"paths": []})
    one = _filter.select_by_topic(_catalog(2), "t", MODE_RECALL, model="m")
    many = _filter.select_by_topic(_catalog(40, summary="x" * 3000), "t", MODE_RECALL, model="m")
    assert type(one) is type(many)
    assert one.batches == 1 and many.batches > 1


def test_a_line_over_a_whole_batch_is_skipped_not_fatal(monkeypatch):
    huge = ArticleMeta(title="Huge", path="wiki/huge.md", summary="x" * 200_000)
    catalog = [huge, ArticleMeta(title="Ok", path="wiki/ok.md", summary="s")]
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {"paths": ["wiki/ok.md"]})

    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m")
    assert result.paths == ["wiki/ok.md"]
    assert [(s.ref, s.reason) for s in result.skipped] == [("wiki/huge.md", "line_over_budget")]


def test_a_topic_too_long_to_leave_a_budget_fails_naming_the_topic(monkeypatch):
    """A topic that fills the prompt budget must blame the topic, not the catalog.

    Before the fix the budget went non-positive, every catalog line was dropped as
    line_over_budget, and the run failed as NO_DOCUMENTS -- "none of the 0 matching
    articles resolved", which sends the operator hunting through their catalog for
    a topic-length problem.
    """
    from kb_ai._errors import TopicTooLargeError
    from kb_ai.llm import MAX_PROMPT_CHARS

    def boom(**kwargs):
        raise AssertionError("completion_json must not be called")

    monkeypatch.setattr(_filter, "completion_json", boom)
    with pytest.raises(TopicTooLargeError, match="topic"):
        _filter.select_by_topic(_catalog(3), "x" * MAX_PROMPT_CHARS, MODE_RECALL,
                                model="m")


def test_the_two_modes_give_different_inclusion_instructions():
    recall = _filter.build_prompt("pricing", MODE_RECALL, "- wiki/a.md — A: s")
    precision = _filter.build_prompt("pricing", MODE_PRECISION, "- wiki/a.md — A: s")
    assert recall != precision
    assert "peripherally" in recall
    assert "substantially" in precision
    assert "pricing" in recall and "pricing" in precision


def test_unknown_mode_is_a_programmer_error():
    with pytest.raises(ValueError):
        _filter.build_prompt("t", "sideways", "")


# ---------------------------------------------------------------------------
# Multi-round voting tests
# ---------------------------------------------------------------------------


def _make_round_stub(round_results: list[dict], filter_rounds: int):
    """Return a completion_json stub that cycles through round_results.

    Each call increments an internal counter; the result is chosen by
    ``(call_count - 1) % filter_rounds`` so that multi-batch scenarios
    replay the same round sequence for every batch.
    """
    call_count = [0]

    def stub(**kwargs):
        call_count[0] += 1
        round_idx = (call_count[0] - 1) % filter_rounds
        value = round_results[round_idx]
        if isinstance(value, Exception):
            raise value
        return value

    return stub


def test_voting_retains_paths_meeting_threshold(monkeypatch):
    """3 rounds — A(3/3)→kept, B(2/3)→kept, C(1/3)→excluded."""
    catalog = _catalog(3)  # wiki/a0.md, wiki/a1.md, wiki/a2.md
    a, b, c = [x.path for x in catalog]
    round_results = [
        {"paths": [a, b, c]},  # round 1: all three
        {"paths": [a, b]},     # round 2: A and B
        {"paths": [a]},        # round 3: only A
    ]
    monkeypatch.setattr(
        _filter, "completion_json",
        _make_round_stub(round_results, filter_rounds=3),
    )
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL,
                                     model="m", filter_rounds=3)
    # threshold = ceil(3*2/3) = 2 → A(3) ✓, B(2) ✓, C(1) ✗
    assert a in result.paths
    assert b in result.paths
    assert c not in result.paths
    assert len(result.paths) == 2


def test_voting_single_round_is_backward_compatible(monkeypatch):
    """filter_rounds=1 produces the same result as pre-voting code."""
    catalog = _catalog(3)
    selected = [catalog[0].path, catalog[2].path]
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": selected})
    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                     filter_rounds=1)
    assert result.paths == selected
    assert result.batches == 1
    assert result.dropped_invented == 0


def test_voting_all_rounds_agree(monkeypatch):
    """All 3 rounds return the same paths → all retained."""
    catalog = _catalog(4)
    all_paths = [a.path for a in catalog]
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": all_paths})
    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                     filter_rounds=3)
    assert sorted(result.paths) == sorted(all_paths)


def test_voting_no_path_meets_threshold(monkeypatch):
    """Each round returns a different non-overlapping path → empty result."""
    catalog = _catalog(3)
    a, b, c = [x.path for x in catalog]
    round_results = [
        {"paths": [a]},  # round 1: only A
        {"paths": [b]},  # round 2: only B
        {"paths": [c]},  # round 3: only C
    ]
    monkeypatch.setattr(
        _filter, "completion_json",
        _make_round_stub(round_results, filter_rounds=3),
    )
    # threshold = ceil(3*2/3) = 2 → each path has 1 vote, none meets threshold
    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                     filter_rounds=3)
    assert result.paths == []


def test_voting_dropped_invented_counts_unique_paths(monkeypatch):
    """An invented path appearing in 2 rounds counts as 1 in dropped_invented."""
    catalog = _catalog(2)
    a = catalog[0].path
    round_results = [
        {"paths": [a, "wiki/fake.md"]},     # round 1: A + invented
        {"paths": [a, "wiki/fake.md"]},     # round 2: same invented path
        {"paths": [a]},                     # round 3: no invented
    ]
    monkeypatch.setattr(
        _filter, "completion_json",
        _make_round_stub(round_results, filter_rounds=3),
    )
    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                     filter_rounds=3)
    # "wiki/fake.md" appears in 2 rounds but is deduplicated → counts as 1
    assert result.dropped_invented == 1
    assert a in result.paths


def test_voting_error_in_any_round_raises(monkeypatch):
    """Round 2 fails → DeriveError."""
    catalog = _catalog(2)
    a = catalog[0].path
    round_results = [
        {"paths": [a]},                      # round 1: OK
        RuntimeError("gateway down"),         # round 2: fails
        {"paths": [a]},                      # round 3: never reached
    ]
    monkeypatch.setattr(
        _filter, "completion_json",
        _make_round_stub(round_results, filter_rounds=3),
    )
    with pytest.raises(DeriveError, match="topic filter failed"):
        _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                filter_rounds=3)


@pytest.mark.parametrize("rounds", [0, -1])
def test_invalid_filter_rounds_raises(rounds):
    """filter_rounds < 1 raises ValueError."""
    with pytest.raises(ValueError, match="filter_rounds"):
        _filter.select_by_topic(_catalog(1), "t", MODE_RECALL, model="m",
                                filter_rounds=rounds)


def test_voting_with_multiple_batches(monkeypatch):
    """Voting works correctly across multiple batches."""
    # Large summaries force multiple batches.
    catalog = _catalog(40, summary="x" * 3000)
    all_paths = {a.path for a in catalog}
    filter_rounds = 3

    # Round 1: return all batch paths.  Round 2: return all.  Round 3: return
    # only the first half of each batch's paths.  threshold=2, so even paths
    # with 2/3 votes are retained → all paths should survive.
    call_count = [0]

    def stub(**kwargs):
        call_count[0] += 1
        round_idx = (call_count[0] - 1) % filter_rounds
        content = kwargs["messages"][0]["content"]
        batch_paths = [a.path for a in catalog if f"- {a.path} " in content]
        if round_idx < 2:
            return {"paths": batch_paths}
        # Round 3: only first half of batch
        return {"paths": batch_paths[: len(batch_paths) // 2]}

    monkeypatch.setattr(_filter, "completion_json", stub)
    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m",
                                     filter_rounds=filter_rounds)

    assert result.batches > 1
    # Every path gets at least 2/3 votes (threshold=2), so all are retained.
    assert sorted(result.paths) == sorted(all_paths)
