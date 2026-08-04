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
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")

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
