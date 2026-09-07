"""Tests for batch splitting: budget estimation, batch packing,
_merge_batch_split, and integration tests for _process_article split paths.

Follows the patterns from test_compile_paths.py: monkeypatched LLM seams,
real KBStore on tmp_path, and stderr capture for log tags.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai.commands import compile as cm
from kb_ai.core import extract as ex
from kb_ai.core.extract import ExtractionResult, _combine_extractions
from kb_ai.core.merge import (
    MAX_PROMPT_CHARS,
    _MERGE_FRAMING_CHARS,
    _SAFETY_MARGIN,
    _SUB_ARTICLE_BUDGET_THRESHOLD,
    _estimate_full_extraction_size,
    estimate_create_budget,
    estimate_merge_budget,
)
from kb_ai.storage.store import KBStore


# ── helpers ──────────────────────────────────────────────────────────

def _ext(summary: str = "short summary", topics: list | None = None) -> ExtractionResult:
    """Build a minimal ExtractionResult for testing."""
    return ExtractionResult(summary=summary, topics=topics or ["t"])


def _big_ext(n_chars: int = 5000) -> ExtractionResult:
    """An extraction whose estimated size is roughly n_chars."""
    return ExtractionResult(summary="x" * n_chars, topics=["t"])


# ── Budget estimation: estimate_create_budget ────────────────────────


class TestEstimateCreateBudget:

    def test_positive_budget(self):
        """Budget for create path with typical items is positive and < MAX_PROMPT_CHARS."""
        items = [("raw/a.md", _ext()), ("raw/b.md", _ext())]
        budget = estimate_create_budget("concept", "My Article", items)
        assert 200 < budget < MAX_PROMPT_CHARS

    def test_scales_with_rels(self):
        """Budget shrinks as more items (longer source_path) are added."""
        small = [("raw/a.md", _ext())]
        large = [("raw/" + f"file_{i}.md", _ext()) for i in range(50)]
        budget_small = estimate_create_budget("concept", "Title", small)
        budget_large = estimate_create_budget("concept", "Title", large)
        assert budget_large < budget_small

    def test_floor_at_200(self):
        """With huge topics/rels, budget floors at 200."""
        huge_topics = ["topic_" + str(i) * 100 for i in range(200)]
        ext = ExtractionResult(summary="s", topics=huge_topics)
        huge_rels = [("raw/" + "x" * 500 + f"/{i}.md", ext) for i in range(100)]
        budget = estimate_create_budget("concept", "T", huge_rels)
        assert budget == 200


# ── Budget estimation: estimate_merge_budget ─────────────────────────


class TestEstimateMergeBudget:

    def test_positive_budget(self):
        """Budget for merge path with short article is positive and < MAX_PROMPT_CHARS."""
        budget = estimate_merge_budget("Short article content.")
        assert 200 < budget < MAX_PROMPT_CHARS

    def test_shrinks_with_article(self):
        """Budget shrinks as article_content grows."""
        budget_small = estimate_merge_budget("small")
        budget_large = estimate_merge_budget("x" * 30000)
        assert budget_large < budget_small

    def test_floor_at_200(self):
        """Very large article floors the budget at 200."""
        budget = estimate_merge_budget("x" * (MAX_PROMPT_CHARS * 2))
        assert budget == 200


# ── Batch packing: _pack_merge_batch ─────────────────────────────────


class TestPackMergeBatch:

    def test_all_fit(self):
        """All items fit in one batch when budget is large."""
        items = [("raw/a.md", _ext()), ("raw/b.md", _ext())]
        batch, remaining = cm._pack_merge_batch(items, budget=100_000)
        assert len(batch) == 2
        assert remaining == []

    def test_splits(self):
        """Items exceeding budget are split into batch + remaining."""
        items = [
            ("raw/a.md", _big_ext(3000)),
            ("raw/b.md", _big_ext(3000)),
            ("raw/c.md", _big_ext(3000)),
        ]
        # Budget that fits ~2 items but not 3
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        budget = single_size * 2 + 10  # fits 2 but not 3
        batch, remaining = cm._pack_merge_batch(items, budget)
        assert len(batch) == 2
        assert len(remaining) == 1
        assert len(batch) + len(remaining) == len(items)

    def test_single_oversized(self):
        """One item exceeding budget is taken alone."""
        items = [("raw/a.md", _big_ext(50000))]
        batch, remaining = cm._pack_merge_batch(items, budget=100)
        assert len(batch) == 1
        assert remaining == []

    def test_empty(self):
        """Empty input returns ([], [])."""
        batch, remaining = cm._pack_merge_batch([], budget=10000)
        assert batch == []
        assert remaining == []

    def test_preserves_order(self):
        """Items appear in batch and remaining in original order."""
        items = [
            ("raw/a.md", _big_ext(3000)),
            ("raw/b.md", _big_ext(3000)),
            ("raw/c.md", _big_ext(3000)),
            ("raw/d.md", _big_ext(3000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        budget = single_size * 2 + 10
        batch, remaining = cm._pack_merge_batch(items, budget)
        batch_rels = [r for r, _ in batch]
        remaining_rels = [r for r, _ in remaining]
        assert batch_rels == ["raw/a.md", "raw/b.md"]
        assert remaining_rels == ["raw/c.md", "raw/d.md"]


# ── _merge_batch_split ───────────────────────────────────────────────


class TestMergeBatchSplit:

    def test_creates_then_merges(self, monkeypatch):
        """Batch 1 calls create, batches 2+ call merge; returns correct content and count."""
        calls: list[str] = []

        def fake_create(article_type, title, extraction, source_path, model="m"):
            calls.append(f"create:{source_path}")
            return f"created from {source_path}"

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            calls.append(f"merge:{source_path}")
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        # Use extractions large enough that a budget fitting exactly 1 item
        # still stays above _SUB_ARTICLE_BUDGET_THRESHOLD (no sub-article split).
        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
            ("raw/c.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        assert single_size > _SUB_ARTICLE_BUDGET_THRESHOLD, "test assumption"
        # Budget fits exactly 1 item per batch, but above sub-article threshold
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: single_size + 10)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: single_size + 10)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert n_batches == 3
        assert all_rels == ["raw/a.md", "raw/b.md", "raw/c.md"]
        assert calls[0].startswith("create:")
        assert all(c.startswith("merge:") for c in calls[1:])
        # New return type: list of (path, content) pairs
        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert "merged" in articles[0][1]

    def test_merge_only(self, monkeypatch):
        """With existing article_content, all batches call merge_into_article."""
        calls: list[str] = []

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            calls.append(f"merge:{source_path}")
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        assert single_size > _SUB_ARTICLE_BUDGET_THRESHOLD, "test assumption"
        # Budget fits exactly 1 item per batch, but above sub-article threshold
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: single_size + 10)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content="existing content")

        assert n_batches == 2
        assert all_rels == ["raw/a.md", "raw/b.md"]
        assert all(c.startswith("merge:") for c in calls)
        # New return type: list of (path, content) pairs
        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert "existing content" in articles[0][1]

    def test_error_mid_batch(self, monkeypatch):
        """Batch 2 raises RuntimeError; it propagates (not swallowed)."""

        def fake_create(article_type, title, extraction, source_path, model="m"):
            return "created"

        def failing_merge(article_path, article_content, extraction, source_path, model="m"):
            raise RuntimeError("batch 2 LLM failure")

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", failing_merge)

        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        assert single_size > _SUB_ARTICLE_BUDGET_THRESHOLD, "test assumption"
        # Budget fits 1 item per batch, above sub-article threshold
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: single_size + 10)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: single_size + 10)

        with pytest.raises(RuntimeError, match="batch 2 LLM failure"):
            cm._merge_batch_split(
                "wiki/concept/foo.md", items, "m",
                article_content=None, article_type="concept", title="Foo")

    def test_single_batch(self, monkeypatch):
        """All items fit in one batch; returns 1 batch, correct content."""
        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"created from {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)

        items = [("raw/a.md", _ext()), ("raw/b.md", _ext())]
        # Large budget: everything fits
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert n_batches == 1
        assert all_rels == ["raw/a.md", "raw/b.md"]
        # New return type: list of (path, content) pairs
        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert "created" in articles[0][1]


# ── Integration tests via compile_kb ─────────────────────────────────

# Fixtures and helpers following test_compile_paths.py patterns.

@pytest.fixture
def kb_multi(tmp_path) -> KBStore:
    """A KB store with multiple raw files for batch split testing."""
    store = KBStore(str(tmp_path))
    for i in range(6):
        store.write_raw(f"raw/doc_{i}.md", f"content of doc {i}")
    return store


@pytest.fixture
def kb_two(tmp_path) -> KBStore:
    """A KB store with two raw files."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "content of a")
    store.write_raw("raw/b.md", "content of b")
    return store


@pytest.fixture
def split_fakes(monkeypatch):
    """Replace LLM/index seams, making extractions large enough to trigger splits.

    The extraction size is controlled by the summary field length, and the budget
    helpers are monkeypatched to force splits when desired.
    """
    state: dict = {
        "extracted": [],
        "created": [],
        "merged": [],
        "classification": {"merge_into": [], "create_new": []},
        "fail_write": set(),
        "force_split": False,
    }

    def fake_extract(content, model="m"):
        state["extracted"].append(content)
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    def fake_classify(extraction, existing, model="m", categories=None):
        return json.loads(json.dumps(state["classification"]))

    def fake_create(article_type, title, extraction, source_path, model="m"):
        if title in state["fail_write"]:
            raise RuntimeError(f"write failed for {title}")
        state["created"].append((article_type, title, source_path))
        return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

    def fake_merge(article_path, article_content, extraction, source_path, model="m"):
        if article_path in state["fail_write"]:
            raise RuntimeError(f"merge failed for {article_path}")
        state["merged"].append((article_path, source_path))
        return article_content + f"\nmerged {source_path}\n"

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "dedup_create_new", lambda result, existing: result)
    monkeypatch.setattr(cm, "create_new_article", fake_create)
    monkeypatch.setattr(cm, "merge_into_article", fake_merge)
    monkeypatch.setattr(cm, "update_markdown_index", lambda store, min_articles, summary_max_chars: None)
    monkeypatch.setattr(cm, "update_timeline", lambda store, rels: None)
    monkeypatch.setattr(cm, "update_people_stubs", lambda store, cfg: None)

    return state


def _merges(*paths) -> dict:
    return {"merge_into": [{"path": p} for p in paths], "create_new": []}


def _log_of(store: KBStore) -> str:
    return (store.base_dir / ".compile.log").read_text()


@pytest.mark.xfail(reason="_process_article not yet updated for new _merge_batch_split return type (p3-feat-003)")
def test_process_article_merge_create_split(kb_two, split_fakes, monkeypatch):
    """When extractions exceed budget on the create path, the split tag
    [merge→create-split] appears in the compile log."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # Force split by making estimate_create_budget return a tiny budget
    # that is smaller than the combined extraction size but allows the
    # split code path to trigger (needs_split = total_size > budget and len > 1).
    original_estimate_create = cm.estimate_create_budget

    def tiny_create_budget(*args, **kwargs):
        # Return 1 char budget so total_size always exceeds it
        return 1

    monkeypatch.setattr(cm, "estimate_create_budget", tiny_create_budget)

    out = cm.compile_kb(str(kb_two.base_dir))

    log = _log_of(kb_two)
    assert "[merge\u2192create-split]" in log
    assert "batches" in log
    assert out["errors"] == []


@pytest.mark.xfail(reason="_process_article not yet updated for new _merge_batch_split return type (p3-feat-003)")
def test_process_article_merge_batch_split(kb_two, split_fakes, monkeypatch):
    """When extractions exceed budget on the merge-batch path, the split tag
    [merge-batch-split] appears in the compile log."""
    kb_two.write_article("wiki/concept/target.md", "---\ntitle: T\n---\nprior body\n")
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    def tiny_merge_budget(*args, **kwargs):
        return 1

    monkeypatch.setattr(cm, "estimate_merge_budget", tiny_merge_budget)

    out = cm.compile_kb(str(kb_two.base_dir))

    log = _log_of(kb_two)
    assert "[merge-batch-split]" in log
    assert "batches" in log
    assert out["errors"] == []


def test_process_article_under_threshold_unchanged(kb_two, split_fakes):
    """When extractions fit within budget, the original (non-split) path is taken."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_two.base_dir))

    log = _log_of(kb_two)
    assert "[merge\u2192create]" in log
    assert "[merge\u2192create-split]" not in log
    assert "[merge-batch-split]" not in log
    assert out["compiled"] == 2
    assert out["errors"] == []
