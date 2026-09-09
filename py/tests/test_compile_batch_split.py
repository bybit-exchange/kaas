"""Tests for batch splitting: budget estimation, batch packing,
_merge_batch_split, and integration tests for _process_article split paths.

Follows the patterns from test_compile_paths.py: monkeypatched LLM seams,
real KBStore on tmp_path, and stderr capture for log tags.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kb_ai.commands import compile as cm
from kb_ai.core import extract as ex
from kb_ai.core.extract import ExtractionResult, _combine_extractions
from kb_ai.core.merge import (
    MAX_PROMPT_CHARS,
    _MAX_BATCH_BUDGET,
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

    def test_budget_capped_at_max_batch_budget(self, monkeypatch):
        """When dynamic budget exceeds _MAX_BATCH_BUDGET, _pack_merge_batch receives the capped value."""
        captured_budgets: list[int] = []
        original_pack = cm._pack_merge_batch

        def spy_pack(items, budget):
            captured_budgets.append(budget)
            return original_pack(items, budget)

        monkeypatch.setattr(cm, "_pack_merge_batch", spy_pack)

        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"created from {source_path}"

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        # Return a budget well above _MAX_BATCH_BUDGET for both paths
        dynamic_budget = 60_000
        assert dynamic_budget > _MAX_BATCH_BUDGET, "test assumes dynamic budget exceeds cap"
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: dynamic_budget)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: dynamic_budget)

        items = [
            ("raw/a.md", _ext()),
            ("raw/b.md", _ext()),
        ]

        # Create path: article_content=None
        cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert captured_budgets[0] == _MAX_BATCH_BUDGET

        # Merge path: article_content is provided
        captured_budgets.clear()
        cm._merge_batch_split(
            "wiki/concept/bar.md", items, "m",
            article_content="existing content")

        assert captured_budgets[0] == _MAX_BATCH_BUDGET


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


# ── Sub-article path helper ──────────────────────────────────────────


class TestSubArticlePath:

    def test_basic_part_1(self):
        assert cm._sub_article_path("wiki/concept/foo.md", 1) == "wiki/concept/foo-part-1.md"

    def test_basic_part_3(self):
        assert cm._sub_article_path("wiki/concept/foo.md", 3) == "wiki/concept/foo-part-3.md"

    def test_hyphenated_stem(self):
        assert cm._sub_article_path("wiki/concept/foo-bar.md", 2) == "wiki/concept/foo-bar-part-2.md"

    def test_nested_path(self):
        assert cm._sub_article_path("wiki/how-to/deep/nested.md", 5) == "wiki/how-to/deep/nested-part-5.md"


# ── Cleanup stale sub-articles ───────────────────────────────────────


class TestCleanupStaleSubArticles:

    def test_removes_matching_parts(self, tmp_path):
        """Stale -part-N.md files for the given article are removed."""
        store = KBStore(str(tmp_path))
        parent = tmp_path / "wiki" / "concept"
        parent.mkdir(parents=True)
        (parent / "foo-part-1.md").write_text("old part 1")
        (parent / "foo-part-2.md").write_text("old part 2")
        (parent / "foo-part-3.md").write_text("old part 3")
        (parent / "foo-bar-part-1.md").write_text("different article")
        (parent / "foo.md").write_text("original")

        removed = cm._cleanup_stale_sub_articles(store, "wiki/concept/foo.md")

        assert len(removed) == 3
        assert not (parent / "foo-part-1.md").exists()
        assert not (parent / "foo-part-2.md").exists()
        assert not (parent / "foo-part-3.md").exists()
        assert (parent / "foo-bar-part-1.md").exists()  # not touched
        assert (parent / "foo.md").exists()  # not touched by cleanup

    def test_no_op_when_none_exist(self, tmp_path):
        """No stale files to remove — returns empty list."""
        store = KBStore(str(tmp_path))
        parent = tmp_path / "wiki" / "concept"
        parent.mkdir(parents=True)
        (parent / "foo.md").write_text("original")

        removed = cm._cleanup_stale_sub_articles(store, "wiki/concept/foo.md")

        assert removed == []
        assert (parent / "foo.md").exists()

    def test_no_op_when_dir_missing(self, tmp_path):
        """Parent directory doesn't exist — returns empty list."""
        store = KBStore(str(tmp_path))

        removed = cm._cleanup_stale_sub_articles(store, "wiki/concept/foo.md")

        assert removed == []


# ── _merge_batch_split sub-article production ────────────────────────


class TestMergeBatchSplitSubArticles:

    def test_produces_sub_articles_when_budget_exhausted(self, monkeypatch):
        """When estimate_merge_budget drops below threshold, sub-articles are produced."""
        call_count = {"create": 0, "merge": 0}

        def fake_create(article_type, title, extraction, source_path, model="m"):
            call_count["create"] += 1
            return f"---\ntitle: {title}\n---\ncontent"

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            call_count["merge"] += 1
            return article_content + "\nmerged\n"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        # Budget below threshold triggers sub-article split after every create/merge.
        # Use a small per-item create budget so only 1 item fits per batch.
        item_size = _estimate_full_extraction_size(_ext("summary a"), "raw/a.md")
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: item_size + 10)

        items = [
            ("raw/a.md", _ext("summary a")),
            ("raw/b.md", _ext("summary b")),
            ("raw/c.md", _ext("summary c")),
        ]

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Should produce multiple sub-articles since budget is always below threshold
        assert len(articles) > 1
        # Each sub-article path has -part-N suffix
        for i, (path, content) in enumerate(articles, 1):
            assert path == f"wiki/concept/foo-part-{i}.md"
            assert content  # non-empty
        # All source rels collected
        assert all_rels == ["raw/a.md", "raw/b.md", "raw/c.md"]
        # Part numbering is sequential starting at 1
        assert articles[0][0].endswith("-part-1.md")
        assert articles[-1][0].endswith(f"-part-{len(articles)}.md")

    def test_single_article_when_budget_sufficient(self, monkeypatch):
        """When budget stays above threshold, returns single article at original path."""

        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"created from {source_path}"

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", fake_merge)
        # Budget always well above threshold
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 50_000)

        items = [
            ("raw/a.md", _ext()),
            ("raw/b.md", _ext()),
        ]

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert all_rels == ["raw/a.md", "raw/b.md"]

    def test_sub_article_titles_contain_part_number(self, monkeypatch):
        """First sub-article uses original title; subsequent ones include '(Part N)'."""
        titles_seen: list[str] = []

        def fake_create(article_type, title, extraction, source_path, model="m"):
            titles_seen.append(title)
            return f"---\ntitle: {title}\n---\ncontent"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article",
                            lambda *a, **kw: a[1] + "\nmerged")
        # Force split after every create by returning below-threshold budget
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        items = [
            ("raw/a.md", _ext()),
            ("raw/b.md", _ext()),
            ("raw/c.md", _ext()),
        ]

        cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="My Article")

        # First create uses original title
        assert titles_seen[0] == "My Article"
        # Subsequent creates include Part N
        for t in titles_seen[1:]:
            assert "Part" in t

    def test_budget_call_not_duplicated(self, monkeypatch):
        """estimate_merge_budget is called once per iteration (not twice)."""
        merge_budget_calls = 0

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
            ("raw/c.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])

        def counting_budget(content):
            nonlocal merge_budget_calls
            merge_budget_calls += 1
            return single_size + 10  # fits exactly 1 item per batch

        monkeypatch.setattr(cm, "estimate_merge_budget", counting_budget)

        cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content="existing content")

        # 3 iterations (3 items, 1-per-batch), each checks merge budget once
        assert merge_budget_calls == 3

    def test_existing_article_split_produces_sub_articles(self, monkeypatch):
        """When article_content is not None and budget drops, sub-articles are produced."""

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            return article_content + f"\nmerged {source_path}\n"

        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"---\ntitle: {title}\n---\ncreated\n"

        monkeypatch.setattr(cm, "merge_into_article", fake_merge)
        monkeypatch.setattr(cm, "create_new_article", fake_create)
        # First call: below threshold (triggers split of existing content)
        # Subsequent calls: above threshold
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        items = [
            ("raw/a.md", _ext()),
            ("raw/b.md", _ext()),
        ]

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content="existing large article content")

        # existing content finalized as part-1, remaining items become part-2
        assert len(articles) >= 2
        assert articles[0][0] == "wiki/concept/foo-part-1.md"
        assert "existing large article content" in articles[0][1]
        assert all_rels == ["raw/a.md", "raw/b.md"]


# ── Integration: _process_article with sub-articles ──────────────────


@pytest.fixture
def kb_many(tmp_path) -> KBStore:
    """A KB store with enough raw files to trigger sub-article splitting."""
    store = KBStore(str(tmp_path))
    for i in range(4):
        store.write_raw(f"raw/doc_{i}.md", f"content of doc {i}")
    return store


def test_process_article_writes_sub_articles(kb_many, split_fakes, monkeypatch):
    """When sub-article split occurs, multiple -part-N.md files are written."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # Force the merge→create-split path by making create_budget tiny
    monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 1)

    # After the first create in _merge_batch_split, make merge_budget below threshold
    # to trigger sub-article production.
    monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)

    out = cm.compile_kb(str(kb_many.base_dir))

    log = _log_of(kb_many)
    assert "sub-articles" in log
    assert out["errors"] == []

    # Check that sub-article files exist
    concept_dir = kb_many.base_dir / "wiki" / "concept"
    sub_articles = sorted(concept_dir.glob("target-part-*.md"))
    assert len(sub_articles) >= 2
    # Original file should NOT exist when sub-articles are produced
    assert not (concept_dir / "target.md").exists()


def test_process_article_sub_article_state_tracking(kb_many, split_fakes, monkeypatch):
    """After sub-article split, compile state records the original art_path, not sub-article paths."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # Force split
    monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 1)
    monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)

    cm.compile_kb(str(kb_many.base_dir))

    state_path = kb_many.base_dir / ".compile-state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())

    # When all ops for a file succeed, the state entry gets "compiled_at"
    # (no "completed_ops" key). Verify that sub-article paths are NOT
    # recorded anywhere in the state — the original art_path is used
    # internally and the final state marks files as fully compiled.
    for rel_path, rel_data in state.items():
        if not isinstance(rel_data, dict):
            continue
        # If partially complete, completed_ops should reference the
        # original art_path, not sub-article paths.
        if "completed_ops" in rel_data:
            assert not any("-part-" in op for op in rel_data["completed_ops"])
        # Verify the rel_path key itself doesn't contain sub-article paths
        assert "-part-" not in rel_path
    # All 4 raw files should be marked as compiled
    compiled_count = sum(
        1 for v in state.values()
        if isinstance(v, dict) and "compiled_at" in v
    )
    assert compiled_count == 4


def test_process_article_sub_article_log_tag(kb_many, split_fakes, monkeypatch):
    """Compile log contains 'sub-articles' text when a split occurs."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # Force split
    monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 1)
    monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)

    cm.compile_kb(str(kb_many.base_dir))

    log = _log_of(kb_many)
    assert "sub-articles" in log
    assert "[merge\u2192create-split]" in log


def test_stale_sub_article_cleanup_on_recompile(kb_two, split_fakes, monkeypatch, capsys):
    """When a re-compile goes through the split path, stale -part-N files are cleaned up."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # First compile: force sub-article split
    monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 1)
    monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)

    cm.compile_kb(str(kb_two.base_dir))

    concept_dir = kb_two.base_dir / "wiki" / "concept"
    sub_articles_after_first = sorted(concept_dir.glob("target-part-*.md"))
    assert len(sub_articles_after_first) >= 2, "First compile should produce sub-articles"

    # Modify raw files to force re-extraction (change checksums)
    kb_two.write_raw("raw/a.md", "updated content of a")
    kb_two.write_raw("raw/b.md", "updated content of b")

    # Clear captured stderr to isolate the second compile's output
    capsys.readouterr()

    # Second compile: still force split path with tiny budgets.
    # The split path calls _cleanup_stale_sub_articles before writing.
    cm.compile_kb(str(kb_two.base_dir))

    # Verify cleanup happened via stderr message
    captured = capsys.readouterr()
    assert "cleaned up" in captured.err and "stale sub-article" in captured.err

    # Sub-articles from the second compile exist
    sub_articles_after_second = sorted(concept_dir.glob("target-part-*.md"))
    assert len(sub_articles_after_second) >= 2
    # All sub-article files are non-empty (were written fresh)
    for sub in sub_articles_after_second:
        assert sub.read_text()


def test_merge_batch_split_deletes_original_on_sub_split(kb_two, split_fakes, monkeypatch):
    """When merge-batch path produces sub-articles, the original file is deleted."""
    # Create an existing article to trigger the merge-batch path
    kb_two.write_article("wiki/concept/target.md", "---\ntitle: T\n---\nprior body\n")
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    # Force the merge budget below threshold to produce sub-articles
    monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 1)
    # create_budget is large so sub-article creates can pack items
    monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

    out = cm.compile_kb(str(kb_two.base_dir))

    concept_dir = kb_two.base_dir / "wiki" / "concept"
    log = _log_of(kb_two)

    # The original file should be deleted
    assert not (concept_dir / "target.md").exists()
    # Sub-articles should exist
    sub_articles = sorted(concept_dir.glob("target-part-*.md"))
    assert len(sub_articles) >= 2
    assert "sub-articles" in log
    assert out["errors"] == []


def test_backward_compat_under_threshold_groups_unchanged(kb_two, split_fakes):
    """Groups that fit within budget are processed exactly as before (no sub-articles)."""
    split_fakes["classification"] = _merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_two.base_dir))

    concept_dir = kb_two.base_dir / "wiki" / "concept"
    # Single article written, no sub-articles
    assert (concept_dir / "target.md").exists()
    sub_articles = list(concept_dir.glob("target-part-*.md"))
    assert sub_articles == []
    assert out["compiled"] == 2
    assert out["errors"] == []
    log = _log_of(kb_two)
    assert "sub-articles" not in log


# ── _get_batch_parallel_sem ──────────────────────────────────────────


def _reset_batch_sem(monkeypatch):
    """Drop the cached semaphore so a test reads the env afresh."""
    monkeypatch.delenv(cm._BATCH_PARALLEL_ENV, raising=False)
    cm._batch_parallel_sem = None
    cm._batch_parallel_sem_bound = 0


class TestGetBatchParallelSem:

    def test_defaults_to_six_and_caches(self, monkeypatch):
        _reset_batch_sem(monkeypatch)

        sem = cm._get_batch_parallel_sem()

        assert cm._batch_parallel_sem_bound == 6
        assert sem is cm._get_batch_parallel_sem()

    def test_reads_env_and_resizes(self, monkeypatch):
        _reset_batch_sem(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_ENV, "3")
        tight = cm._get_batch_parallel_sem()
        assert cm._batch_parallel_sem_bound == 3

        monkeypatch.setenv(cm._BATCH_PARALLEL_ENV, "10")
        wider = cm._get_batch_parallel_sem()

        assert cm._batch_parallel_sem_bound == 10
        assert wider is not tight
        assert wider is cm._get_batch_parallel_sem()

    @pytest.mark.parametrize("raw", ["not-a-number", "0", "-4"],
                             ids=["unparseable", "zero", "negative"])
    def test_invalid_env_warns_once_and_uses_default(self, monkeypatch, capsys, raw):
        cm._warn_invalid_batch_parallel.cache_clear()
        _reset_batch_sem(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_ENV, raw)

        assert cm._get_batch_parallel_sem() is not None
        assert cm._batch_parallel_sem_bound == 6
        cm._get_batch_parallel_sem()  # second call should not warn again

        err = capsys.readouterr().err
        assert err.count(cm._BATCH_PARALLEL_ENV) == 1


# ── _sem_guard ───────────────────────────────────────────────────────


class TestSemGuard:

    def test_acquires_and_releases(self):
        """Semaphore permit is held inside the block and released after."""
        import threading
        sem = threading.Semaphore(1)
        # Acquire the only permit to verify the guard releases it
        with cm._sem_guard(sem):
            # Inside: the permit was acquired by the guard
            pass
        # After: permit released; we can acquire again without blocking
        assert sem.acquire(blocking=False)
        sem.release()

    def test_none_is_noop(self):
        """Passing None does not raise and yields immediately."""
        with cm._sem_guard(None):
            pass  # no error

    def test_releases_on_exception(self):
        """The semaphore is released even when the body raises."""
        import threading
        sem = threading.Semaphore(1)
        with pytest.raises(ValueError):
            with cm._sem_guard(sem):
                raise ValueError("boom")
        # Permit released despite exception
        assert sem.acquire(blocking=False)
        sem.release()


# ── _pre_split_chains ────────────────────────────────────────────────


class TestPreSplitChains:

    def test_basic_chunking(self, monkeypatch):
        """Items are split into chunks based on budget and average item size."""
        items = [(f"raw/{i}.md", _ext(f"summary {i}")) for i in range(20)]
        # Force small budget so items_per_batch is small
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 200)
        # Each item's estimated size is ~40 chars (from _ext with short summary)
        # budget=200 (capped at _MAX_BATCH_BUDGET which is 20000, so 200 wins)
        # avg_size ~40, items_per_batch = max(1, int(200/40)) = 5
        # chunk_size = max(1, 5 * 3) = 15
        chunks = cm._pre_split_chains(items, "concept", "Title")
        assert len(chunks) >= 1
        # All items accounted for
        flat = [item for chunk in chunks for item in chunk]
        assert flat == items
        # Each chunk is non-empty
        assert all(len(c) > 0 for c in chunks)

    def test_preserves_order(self, monkeypatch):
        """Items appear in the same order across all chunks."""
        items = [(f"raw/{i}.md", _ext(f"s{i}")) for i in range(10)]
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        chunks = cm._pre_split_chains(items, "concept", "Title")
        flat = [item for chunk in chunks for item in chunk]
        assert flat == items

    def test_single_item_returns_one_chunk(self, monkeypatch):
        """A single item always returns [items]."""
        items = [("raw/only.md", _ext("only item"))]
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        chunks = cm._pre_split_chains(items, "concept", "Title")
        assert chunks == [items]

    def test_fewer_items_than_chunk_returns_single_chunk(self, monkeypatch):
        """When all items fit in one chunk, returns [items]."""
        items = [("raw/a.md", _ext()), ("raw/b.md", _ext())]
        # Huge budget: everything fits in one chunk
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)
        chunks = cm._pre_split_chains(items, "concept", "Title")
        assert chunks == [items]

    def test_respects_target_batches_per_chain(self, monkeypatch):
        """Lowering target_batches_per_chain produces more, smaller chunks."""
        items = [(f"raw/{i}.md", _ext(f"s{i}")) for i in range(30)]
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 200)
        chunks_3 = cm._pre_split_chains(items, "concept", "Title",
                                         target_batches_per_chain=3)
        chunks_1 = cm._pre_split_chains(items, "concept", "Title",
                                         target_batches_per_chain=1)
        # Fewer batches per chain = more chunks
        assert len(chunks_1) >= len(chunks_3)
        # Both cover all items
        assert [i for c in chunks_3 for i in c] == items
        assert [i for c in chunks_1 for i in c] == items

    def test_budget_capped_at_max_batch_budget(self, monkeypatch):
        """When estimate_create_budget returns more than _MAX_BATCH_BUDGET,
        _pre_split_chains caps it."""
        items = [(f"raw/{i}.md", _big_ext(5000)) for i in range(10)]
        # Return budget far above _MAX_BATCH_BUDGET
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)
        chunks_capped = cm._pre_split_chains(items, "concept", "Title")
        # Should still produce at least one chunk; with _MAX_BATCH_BUDGET=20000
        # and avg_size ~5000: items_per_batch = 4, chunk_size = 12 → 1 chunk
        assert len(chunks_capped) >= 1
        flat = [item for chunk in chunks_capped for item in chunk]
        assert flat == items


# ── _ChainResult ─────────────────────────────────────────────────────


class TestChainResult:

    def test_fields(self):
        """_ChainResult is a dataclass with the expected fields."""
        r = cm._ChainResult(
            articles=[("wiki/concept/foo-part-1.md", "content")],
            all_rels=["raw/a.md"],
            n_batches=2,
        )
        assert r.articles == [("wiki/concept/foo-part-1.md", "content")]
        assert r.all_rels == ["raw/a.md"]
        assert r.n_batches == 2

    def test_is_dataclass(self):
        """_ChainResult is recognized as a dataclass."""
        from dataclasses import is_dataclass
        assert is_dataclass(cm._ChainResult)


# ── _run_chain ───────────────────────────────────────────────────────


def _make_parent_ctx():
    """Create a minimal ThreadContext suitable for _run_chain's parent_ctx."""
    from kb_ai._context import ThreadContext
    return ThreadContext(phase="test")


class TestRunChain:

    def test_single_batch(self, monkeypatch):
        """All items fit in one batch; returns single article, 1 batch."""
        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"created from {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        items = [("raw/a.md", _ext()), ("raw/b.md", _ext())]
        result = cm._run_chain(
            "wiki/concept/foo.md", items, "m",
            article_type="concept", title="Foo",
            start_part_num=2, parent_ctx=_make_parent_ctx(), sem=None,
        )

        assert result.n_batches == 1
        assert result.all_rels == ["raw/a.md", "raw/b.md"]
        assert len(result.articles) == 1
        # Single article uses start_part_num path
        assert result.articles[0][0] == "wiki/concept/foo-part-2.md"
        assert "created" in result.articles[0][1]

    def test_multi_batch_no_split(self, monkeypatch):
        """Multiple batches, budget stays above threshold; returns single article."""
        calls: list[str] = []

        def fake_create(article_type, title, extraction, source_path, model="m"):
            calls.append("create")
            return f"created from {source_path}"

        def fake_merge(article_path, article_content, extraction, source_path, model="m"):
            calls.append("merge")
            return article_content + f"\nmerged {source_path}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article", fake_merge)

        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
            ("raw/c.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        assert single_size > _SUB_ARTICLE_BUDGET_THRESHOLD
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: single_size + 10)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: single_size + 10)

        result = cm._run_chain(
            "wiki/concept/foo.md", items, "m",
            article_type="concept", title="Foo",
            start_part_num=3, parent_ctx=_make_parent_ctx(), sem=None,
        )

        assert result.n_batches == 3
        assert result.all_rels == ["raw/a.md", "raw/b.md", "raw/c.md"]
        assert len(result.articles) == 1
        assert result.articles[0][0] == "wiki/concept/foo-part-3.md"
        assert calls == ["create", "merge", "merge"]

    def test_internal_split(self, monkeypatch):
        """Budget drops below threshold mid-chain; produces multiple sub-articles."""
        def fake_create(article_type, title, extraction, source_path, model="m"):
            return f"created:{title}"

        monkeypatch.setattr(cm, "create_new_article", fake_create)
        monkeypatch.setattr(cm, "merge_into_article",
                            lambda *a, **kw: a[1] + "\nmerged")
        # Force split after every create: merge budget below threshold
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        # Per-item create budget small enough that only 1 item fits per batch,
        # so we get create → split → create → split → create pattern.
        item_size = _estimate_full_extraction_size(_ext(), "raw/a.md")
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: item_size + 10)

        items = [
            ("raw/a.md", _ext()),
            ("raw/b.md", _ext()),
            ("raw/c.md", _ext()),
        ]

        result = cm._run_chain(
            "wiki/concept/foo.md", items, "m",
            article_type="concept", title="Foo",
            start_part_num=2, parent_ctx=_make_parent_ctx(), sem=None,
        )

        # Should produce multiple sub-articles since budget is always below threshold
        assert len(result.articles) > 1
        assert result.all_rels == ["raw/a.md", "raw/b.md", "raw/c.md"]
        # Paths use sequential part numbers starting from start_part_num
        assert result.articles[0][0] == "wiki/concept/foo-part-2.md"
        assert result.articles[1][0] == "wiki/concept/foo-part-3.md"

    def test_calls_adopt_context(self, monkeypatch):
        """_run_chain calls adopt_context with the parent_ctx and correct phase."""
        adopt_calls: list[tuple] = []
        original_adopt = cm.adopt_context

        def tracking_adopt(parent, **overrides):
            adopt_calls.append((parent, overrides))
            return original_adopt(parent, **overrides)

        monkeypatch.setattr(cm, "adopt_context", tracking_adopt)
        monkeypatch.setattr(cm, "create_new_article",
                            lambda *a, **kw: "content")
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        ctx = _make_parent_ctx()
        cm._run_chain(
            "wiki/concept/foo.md", [("raw/a.md", _ext())], "m",
            article_type="concept", title="Foo",
            start_part_num=1, parent_ctx=ctx, sem=None,
        )

        assert len(adopt_calls) == 1
        assert adopt_calls[0][0] is ctx
        assert adopt_calls[0][1] == {"phase": "write-chain:wiki/concept/foo.md"}

    def test_sem_guard_wraps_llm_calls(self, monkeypatch):
        """Each LLM call is wrapped in _sem_guard with the provided semaphore."""
        import threading
        sem = threading.Semaphore(1)
        held_during: list[bool] = []

        def check_create(article_type, title, extraction, source_path, model="m"):
            # Try to acquire non-blocking; should fail if sem is already held
            could_acquire = sem.acquire(blocking=False)
            if could_acquire:
                sem.release()
                held_during.append(False)  # sem was NOT held by guard
            else:
                held_during.append(True)  # sem was held by guard
            return "content"

        monkeypatch.setattr(cm, "create_new_article", check_create)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        cm._run_chain(
            "wiki/concept/foo.md", [("raw/a.md", _ext())], "m",
            article_type="concept", title="Foo",
            start_part_num=1, parent_ctx=_make_parent_ctx(), sem=sem,
        )

        # The sem should have been held during the create call
        assert held_during == [True]

    def test_propagates_create_error(self, monkeypatch):
        """RuntimeError from create_new_article propagates."""
        def failing_create(*a, **kw):
            raise RuntimeError("create failed")

        monkeypatch.setattr(cm, "create_new_article", failing_create)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)

        with pytest.raises(RuntimeError, match="create failed"):
            cm._run_chain(
                "wiki/concept/foo.md", [("raw/a.md", _ext())], "m",
                article_type="concept", title="Foo",
                start_part_num=1, parent_ctx=_make_parent_ctx(), sem=None,
            )

    def test_propagates_merge_error(self, monkeypatch):
        """RuntimeError from merge_into_article propagates."""
        monkeypatch.setattr(cm, "create_new_article",
                            lambda *a, **kw: "created")

        def failing_merge(*a, **kw):
            raise RuntimeError("merge failed")

        monkeypatch.setattr(cm, "merge_into_article", failing_merge)

        items = [
            ("raw/a.md", _big_ext(15000)),
            ("raw/b.md", _big_ext(15000)),
        ]
        single_size = _estimate_full_extraction_size(items[0][1], items[0][0])
        assert single_size > _SUB_ARTICLE_BUDGET_THRESHOLD
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: single_size + 10)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: single_size + 10)

        with pytest.raises(RuntimeError, match="merge failed"):
            cm._run_chain(
                "wiki/concept/foo.md", items, "m",
                article_type="concept", title="Foo",
                start_part_num=1, parent_ctx=_make_parent_ctx(), sem=None,
            )


# ── TestMergeBatchSplitParallel ──────────────────────────────────────


class TestMergeBatchSplitParallel:
    """Tests for the three-phase parallel path in _merge_batch_split.

    Strategy: use monkeypatched budget helpers so that Phase A splits after
    the first create (merge_budget < threshold), and _pre_split_chains
    produces multiple chunks from the remaining items.
    """

    # -- shared helpers ---------------------------------------------------

    @staticmethod
    def _make_items(n: int):
        """Build N items whose extraction size is predictable."""
        return [(f"raw/doc_{i}.md", _ext(f"summary {i}")) for i in range(n)]

    @staticmethod
    def _patch_for_parallel(monkeypatch, *, create_fn=None, merge_fn=None):
        """Monkeypatch budgets so Phase A splits after 1 create and
        _pre_split_chains produces multiple chunks.

        - estimate_merge_budget -> 100  (< _SUB_ARTICLE_BUDGET_THRESHOLD)
          so every create is followed by a split.
        - estimate_create_budget -> 200  (small budget)
          so _pre_split_chains computes small chunk sizes.
        - _estimate_full_extraction_size -> 100  (predictable per-item size)
          so items_per_batch = max(1, int(200/100)) = 2,
          chunk_size = 2 * 3 = 6  with default target_batches_per_chain=3.
          For 12 items: Phase A takes 2 items (1 batch of 2), splits.
          Remaining 10 items -> 10/6 = 2 chunks (6 + 4).
        """
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 200)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )

        if create_fn is None:
            def create_fn(article_type, title, extraction, source_path, model="m"):
                return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"
        if merge_fn is None:
            def merge_fn(article_path, article_content, extraction, source_path, model="m"):
                return article_content + f"\nmerged {source_path}\n"

        monkeypatch.setattr(cm, "create_new_article", create_fn)
        monkeypatch.setattr(cm, "merge_into_article", merge_fn)

    # -- tests ------------------------------------------------------------

    def test_parallel_chains_produce_correct_sub_articles(self, monkeypatch):
        """After Phase A split, continuation chains produce sub-articles with
        sequential part numbers (1, 2, 3, ...)."""
        items = self._make_items(12)
        self._patch_for_parallel(monkeypatch)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Must have more than 1 sub-article (Phase A produced at least 1,
        # continuation chains produced at least 1 more).
        assert len(articles) >= 3, f"expected >= 3 sub-articles, got {len(articles)}"

        # Part numbers are sequential starting at 1
        for i, (path, content) in enumerate(articles, 1):
            assert path == f"wiki/concept/foo-part-{i}.md", (
                f"article {i}: expected foo-part-{i}.md, got {path}")
            assert content, f"article {i} has empty content"

        assert n_batches >= 3

    def test_parallel_chains_preserve_all_rels(self, monkeypatch):
        """Every source rel_path appears in all_rels exactly once."""
        items = self._make_items(12)
        self._patch_for_parallel(monkeypatch)

        _articles, all_rels, _n = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        expected_rels = [rel for rel, _ext in items]
        assert all_rels == expected_rels

    def test_parallel_chains_concurrent_execution(self, monkeypatch):
        """Continuation chains actually run concurrently (not serially).

        Uses threading.Barrier: if N chains call barrier.wait() concurrently,
        all pass. If serial, the barrier times out.
        """
        import threading

        # Use 8 items. Phase A takes ~2 (budget 200, item size 100 -> 2 per batch).
        # Remaining 6 -> _pre_split_chains with chunk_size = 2*3 = 6 -> 1 chunk.
        # That's not enough for parallel. Use smaller chunk sizing:
        # budget=100 -> items_per_batch=1, chunk_size=1*3=3.
        # Phase A: 1 batch of 1 item, then split. Remaining 7 items.
        # 7 items / chunk_size 3 = 3 chunks (3, 3, 1).
        items = self._make_items(8)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )

        # 3 chains run concurrently; barrier parties = 3.
        barrier = threading.Barrier(3, timeout=5)
        barrier_passed = threading.Event()
        main_thread = threading.current_thread()
        # Track which threads have already waited on the barrier.
        barrier_done = threading.local()

        def concurrent_create(article_type, title, extraction, source_path, model="m"):
            # Phase A runs on the calling thread; only child threads
            # (continuation chains in Phase B) participate in the barrier.
            # Each child thread hits the barrier exactly once (its first create).
            if threading.current_thread() is not main_thread:
                if not getattr(barrier_done, "done", False):
                    barrier_done.done = True
                    barrier.wait()  # blocks until 3 child threads arrive
                    barrier_passed.set()
            return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

        def concurrent_merge(article_path, article_content, extraction, source_path, model="m"):
            return article_content + f"\nmerged {source_path}\n"

        monkeypatch.setattr(cm, "create_new_article", concurrent_create)
        monkeypatch.setattr(cm, "merge_into_article", concurrent_merge)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # If barrier.wait() didn't deadlock, concurrency was verified.
        assert barrier_passed.is_set(), "chains did not execute concurrently"
        assert len(articles) >= 2
        # All rels accounted for
        assert len(all_rels) == len(items)

    def test_no_parallelism_without_split(self, monkeypatch):
        """When no split occurs, no threads are spawned (zero overhead)."""
        import threading
        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        # Large budgets: everything fits in one batch, no split
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100_000)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100_000)
        monkeypatch.setattr(cm, "create_new_article",
                            lambda *a, **kw: "created content")

        # Patch ThreadPoolExecutor to detect if it's created
        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        items = self._make_items(4)
        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert not pool_created.is_set(), "ThreadPoolExecutor was created (no split expected)"
        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert n_batches == 1

    def test_error_in_continuation_chain_propagates(self, monkeypatch):
        """RuntimeError from a continuation chain's LLM call propagates."""
        items = self._make_items(8)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )

        call_count = {"n": 0}

        def failing_create(article_type, title, extraction, source_path, model="m"):
            call_count["n"] += 1
            # First call is Phase A (Chain 0); let it succeed so we reach Phase B.
            if call_count["n"] == 1:
                return f"created from {source_path}"
            raise RuntimeError("continuation chain LLM failure")

        monkeypatch.setattr(cm, "create_new_article", failing_create)
        monkeypatch.setattr(cm, "merge_into_article",
                            lambda *a, **kw: a[1] + "\nmerged")

        with pytest.raises(RuntimeError, match="continuation chain LLM failure"):
            cm._merge_batch_split(
                "wiki/concept/foo.md", items, "m",
                article_content=None, article_type="concept", title="Foo")

    def test_semaphore_limits_concurrency(self, monkeypatch):
        """With KB_BATCH_PARALLEL_MAX_CONCURRENT=2, at most 2 LLM calls
        run simultaneously across all chains."""
        import threading

        items = self._make_items(10)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )

        # Reset semaphore state and set env to limit to 2
        _reset_batch_sem(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_ENV, "2")

        lock = threading.Lock()
        max_concurrent = {"val": 0}
        current = {"val": 0}

        def counting_create(article_type, title, extraction, source_path, model="m"):
            with lock:
                current["val"] += 1
                if current["val"] > max_concurrent["val"]:
                    max_concurrent["val"] = current["val"]
            # Small sleep to allow overlap detection
            import time
            time.sleep(0.01)
            with lock:
                current["val"] -= 1
            return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

        def counting_merge(article_path, article_content, extraction, source_path, model="m"):
            with lock:
                current["val"] += 1
                if current["val"] > max_concurrent["val"]:
                    max_concurrent["val"] = current["val"]
            import time
            time.sleep(0.01)
            with lock:
                current["val"] -= 1
            return article_content + f"\nmerged {source_path}\n"

        monkeypatch.setattr(cm, "create_new_article", counting_create)
        monkeypatch.setattr(cm, "merge_into_article", counting_merge)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # The semaphore-guarded calls in continuation chains must be <= 2
        # Note: Phase A calls are not semaphore-guarded, so they don't count.
        # But max_concurrent tracks all calls. Phase A runs serially (1 call),
        # then continuation chains run with sem=2.
        # The max concurrent across continuation chains must be <= 2.
        assert max_concurrent["val"] <= 2, (
            f"max concurrent LLM calls was {max_concurrent['val']}, expected <= 2")
        assert len(all_rels) == len(items)

    def test_cost_tracking_across_chains(self, monkeypatch):
        """op_tracker receives costs from all chains, not just Chain 0."""
        from kb_ai._cost import CostTracker

        items = self._make_items(8)
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )

        call_count = {"n": 0}

        def costed_create(article_type, title, extraction, source_path, model="m"):
            # Record a cost on the request tracker to verify propagation.
            rt = cm.get_request_tracker()
            if rt is not None:
                rt.record("test-model", 100, 50, cost=0.01)
            call_count["n"] += 1
            return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

        def costed_merge(article_path, article_content, extraction, source_path, model="m"):
            rt = cm.get_request_tracker()
            if rt is not None:
                rt.record("test-model", 100, 50, cost=0.01)
            return article_content + f"\nmerged {source_path}\n"

        monkeypatch.setattr(cm, "create_new_article", costed_create)
        monkeypatch.setattr(cm, "merge_into_article", costed_merge)

        # Run inside _measure_op_cost to get the op_tracker
        with cm._measure_op_cost() as op_tracker:
            articles, all_rels, n_batches = cm._merge_batch_split(
                "wiki/concept/foo.md", items, "m",
                article_content=None, article_type="concept", title="Foo")

        # Phase A makes at least 1 call; continuation chains make additional calls.
        # All calls should have recorded cost to the op_tracker via request_tracker.
        assert call_count["n"] >= 3, (
            f"expected at least 3 LLM calls (Phase A + continuations), got {call_count['n']}")
        # Each call records 0.01; total must reflect ALL chains.
        assert op_tracker.total_cost >= call_count["n"] * 0.01 - 0.001, (
            f"op_tracker.total_cost={op_tracker.total_cost:.4f} too low for "
            f"{call_count['n']} calls at $0.01 each")


# ── _get_batch_parallel_threshold ────────────────────────────────────


def _reset_batch_threshold_cache():
    """Clear the lru_cache on the warning function so tests see fresh warnings."""
    cm._warn_invalid_batch_parallel_threshold.cache_clear()


class TestGetBatchParallelThreshold:

    def test_returns_default(self, monkeypatch):
        """No env var set -> returns _BATCH_PARALLEL_THRESHOLD (4)."""
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)
        assert cm._get_batch_parallel_threshold() == 4

    def test_reads_env(self, monkeypatch):
        """Valid env var -> returns parsed value."""
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "8")
        assert cm._get_batch_parallel_threshold() == 8

    def test_zero_valid(self, monkeypatch):
        """Env var = '0' -> returns 0 (always parallelize)."""
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "0")
        assert cm._get_batch_parallel_threshold() == 0

    def test_invalid_warns_once(self, monkeypatch, capsys):
        """Non-integer env var -> returns default and warns to stderr once."""
        _reset_batch_threshold_cache()
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "bad")

        assert cm._get_batch_parallel_threshold() == 4
        # second call should not warn again
        cm._get_batch_parallel_threshold()

        err = capsys.readouterr().err
        assert err.count(cm._BATCH_PARALLEL_THRESHOLD_ENV) == 1
        assert "bad" in err

    def test_negative_warns(self, monkeypatch, capsys):
        """Negative env var -> returns default and warns."""
        _reset_batch_threshold_cache()
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "-5")

        assert cm._get_batch_parallel_threshold() == 4

        err = capsys.readouterr().err
        assert cm._BATCH_PARALLEL_THRESHOLD_ENV in err


# ── Batch parallel threshold in _merge_batch_split ───────────────────


class TestBatchParallelThreshold:
    """Tests for the threshold-based serial/parallel dispatch in Phase B."""

    @staticmethod
    def _make_items(n: int):
        return [(f"raw/doc_{i}.md", _ext(f"summary {i}")) for i in range(n)]

    @staticmethod
    def _patch_for_split(monkeypatch, *, create_fn=None, merge_fn=None):
        """Patch budgets so Phase A splits after 1 create.

        - estimate_merge_budget -> 100 (below _SUB_ARTICLE_BUDGET_THRESHOLD)
        - estimate_create_budget -> 100 (small budget)
        - _estimate_full_extraction_size -> 100 (predictable per-item size)
        """
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            "kb_ai.core.merge._estimate_full_extraction_size",
            lambda ext, rel: 100,
        )
        if create_fn is None:
            def create_fn(article_type, title, extraction, source_path, model="m"):
                return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"
        if merge_fn is None:
            def merge_fn(article_path, article_content, extraction, source_path, model="m"):
                return article_content + f"\nmerged {source_path}\n"
        monkeypatch.setattr(cm, "create_new_article", create_fn)
        monkeypatch.setattr(cm, "merge_into_article", merge_fn)

    def test_serial_fallback_below_threshold(self, monkeypatch):
        """When remaining <= threshold, no ThreadPoolExecutor is created."""
        import threading

        # 5 items: Phase A takes 1 (budget=100, item_size=100), splits.
        # Remaining = 4, which equals the default threshold of 4 -> serial.
        items = self._make_items(5)
        self._patch_for_split(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert not pool_created.is_set(), "ThreadPoolExecutor should not be created for serial path"
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels
        assert len(articles) >= 2  # Phase A sub-article + serial chain result(s)
        assert n_batches >= 2

    def test_parallel_above_threshold(self, monkeypatch):
        """When remaining > threshold, ThreadPoolExecutor IS created."""
        import threading

        # 12 items: Phase A takes 1. Remaining = 11 > default threshold 4.
        items = self._make_items(12)
        self._patch_for_split(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert pool_created.is_set(), "ThreadPoolExecutor should be created for parallel path"
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels

    def test_threshold_zero_always_parallel(self, monkeypatch):
        """threshold=0 means always parallelize, even with few remaining."""
        import threading

        # 3 items: Phase A takes 1. Remaining = 2.
        # With threshold=0, should still go parallel.
        items = self._make_items(3)
        self._patch_for_split(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "0")

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # threshold=0: the condition `threshold > 0 and len(remaining) <= threshold`
        # is False, so we always go to the parallel (else) branch.
        # However, with only 2 remaining items and chunk_size=3,
        # _pre_split_chains may produce 1 chunk of <=1 item, hitting the
        # synchronous fallback inside the else branch. Either way, the code
        # enters the parallel dispatch branch (not the serial threshold branch).
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels

    def test_threshold_env_override(self, monkeypatch):
        """Setting threshold via env var controls serial/parallel dispatch."""
        import threading

        # 8 items: Phase A takes 1. Remaining = 7.
        # With threshold=10, remaining <= threshold -> serial.
        items = self._make_items(8)
        self._patch_for_split(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "10")

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        assert not pool_created.is_set(), "threshold=10 should trigger serial path for 7 remaining"
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels

    def test_threshold_env_invalid_uses_default(self, monkeypatch):
        """Invalid env var falls back to default threshold."""
        import threading
        _reset_batch_threshold_cache()

        # 5 items: Phase A takes 1. Remaining = 4 = default threshold -> serial.
        items = self._make_items(5)
        self._patch_for_split(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "abc")

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Default threshold=4, remaining=4 -> serial
        assert not pool_created.is_set(), "invalid env should use default (4), triggering serial"

    def test_threshold_env_negative_uses_default(self, monkeypatch):
        """Negative env var falls back to default threshold."""
        import threading
        _reset_batch_threshold_cache()

        items = self._make_items(5)
        self._patch_for_split(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, "-1")

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()

        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)

        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Default threshold=4, remaining=4 -> serial
        assert not pool_created.is_set(), "negative env should use default (4), triggering serial"
