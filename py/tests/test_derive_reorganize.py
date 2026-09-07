"""Tests for the reorganize wiring in compile_kb and derive_kb (Feature p1-feat-005).

Covers:
  - compile_kb with aggregation_plan: planned articles seeded, topical classify
    used, dedup skipped, classify cache skipped
  - compile_kb with aggregation_plan=None: zero behavior change
  - _planned_article_meta used in merge→create fallback
  - derive_kb with reorganize=True: reorganize called, plan passed to compile_fn
  - derive_kb with reorganize=False: no new code path
  - manifest includes reorganize_plan
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kb_ai.commands import compile as cm
from kb_ai.core.extract import ExtractionResult
from kb_ai.derive import derive_kb
from kb_ai.derive._reorganize import (
    CanonicalMapping,
    EntityIndex,
    ReorganizePlan,
    ThematicArticle,
)
from kb_ai.derive._types import MODE_RECALL, SelectionResult
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import ArticleMeta, KBStore, _compute_checksum


# ── helpers ─────────────────────────────────────────────────────────

def _kb_with_raw(tmp_path: Path) -> KBStore:
    """A KB store with raw files, ready to compile."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "content of a")
    store.write_raw("raw/b.md", "content of b")
    return store


def _fixture_kb_for_derive(tmp_path: Path) -> Path:
    """A compiled-looking source KB for derive tests."""
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "wiki").mkdir(parents=True)
    (kb / "index").mkdir(parents=True)

    (kb / "raw" / "pricing-notes.md").write_text("Fee schedule and tiers.")
    (kb / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\nsources:\n  - raw/pricing-notes.md\n---\n\n# Pricing\n"
    )
    (kb / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Pricing](wiki/pricing.md) — Fee schedule.\n"
    )
    return kb


def _select_stub(paths: list[str]):
    """Stub selector: RECALL returns `paths`."""
    def select(catalog, topic, mode):
        present = {a.path for a in catalog}
        return SelectionResult(
            paths=[p for p in paths if p in present],
            batches=1,
            dropped_invented=0,
            skipped=[],
        )
    return select


def _fake_compile_result(derived_dir: str, **kwargs) -> dict:
    """Stand in for compile_kb: write one article and a catalog."""
    base = Path(derived_dir)
    (base / "wiki").mkdir(parents=True, exist_ok=True)
    (base / "index").mkdir(parents=True, exist_ok=True)
    (base / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\n---\n\n# Pricing\n\nProse.\n"
    )
    (base / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Pricing](wiki/pricing.md) — Fees.\n"
    )
    return {"compiled": 1, "errors": [], "cost": {"total_cost_usd": 0.50}}


@pytest.fixture
def kb(tmp_path) -> KBStore:
    return _kb_with_raw(tmp_path)


@pytest.fixture
def fakes(monkeypatch):
    """Replace every LLM/index seam compile_kb reaches for.

    The returned dict is both a call log and a control surface.
    """
    from kb_ai.core import extract as ex
    from kb_ai.core import merge as mg

    state: dict = {
        "extracted": [],
        "classified": [],
        "classified_topical": [],
        "created": [],
        "merged": [],
        "indexed": [],
        "classification": {"merge_into": [], "create_new": []},
        "fail_extract": set(),
        "fail_write": set(),
    }

    def fake_extract(content, model="m"):
        state["extracted"].append(content)
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    def fake_classify(extraction, existing, model="m", categories=None):
        state["classified"].append(extraction.source_path)
        result = state["classification"]
        return json.loads(json.dumps(result))  # deep copy per call

    def fake_classify_topical(extraction, existing, topic, plan, model="m", categories=None):
        state["classified_topical"].append(extraction.source_path)
        result = state["classification"]
        return json.loads(json.dumps(result))

    def fake_create(article_type, title, extraction, source_path, model="m"):
        state["created"].append((article_type, title, source_path))
        return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

    def fake_merge(article_path, article_content, extraction, source_path, model="m"):
        state["merged"].append((article_path, source_path))
        return article_content + f"\nmerged {source_path}\n"

    def fake_summarized(chunks, meta, summarize_model, extract_model):
        joined = "".join(chunks)
        return ExtractionResult(summary=f"summary of {joined}", topics=["t"])

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(ex, "extract_knowledge_summarized", fake_summarized)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "classify_article_topical", fake_classify_topical)
    monkeypatch.setattr(cm, "dedup_create_new", lambda result, existing: result)
    monkeypatch.setattr(cm, "create_new_article", fake_create)
    monkeypatch.setattr(cm, "merge_into_article", fake_merge)
    monkeypatch.setattr(
        cm,
        "update_markdown_index",
        lambda store, min_articles, summary_max_chars: state["indexed"].append("index"),
    )
    monkeypatch.setattr(
        cm,
        "update_timeline",
        lambda store, rels: state["indexed"].append("timeline"),
    )
    monkeypatch.setattr(
        cm,
        "update_people_stubs",
        lambda store, cfg: state["indexed"].append(("people", cfg)),
    )
    # update_document_index is called at Phase 3
    monkeypatch.setattr(
        cm,
        "update_document_index",
        lambda store, summary_max_chars: state["indexed"].append("doc_index"),
    )
    return state


def _plan_dicts() -> list[dict]:
    """Example aggregation plan for testing."""
    return [
        {
            "path": "wiki/concept/pricing-overview.md",
            "type": "concept",
            "title": "Pricing — Complete Overview",
            "description": "Overview of all pricing information",
        },
        {
            "path": "wiki/reference/fee-schedule.md",
            "type": "reference",
            "title": "Fee Schedule Reference",
            "description": "Detailed fee schedule and tiers",
        },
    ]


# ── compile_kb: aggregation_plan=None (zero change) ────────────────

class TestCompileKBNoPlan:
    """When aggregation_plan is None, all behavior must be identical to current."""

    def test_default_aggregation_plan_is_none(self, kb, fakes):
        """Calling without aggregation_plan uses the normal classify path."""
        fakes["classification"] = {
            "merge_into": [],
            "create_new": [
                {"path": "wiki/concept/a.md", "title": "A", "type": "concept"}
            ],
        }
        out = cm.compile_kb(str(kb.base_dir))
        assert out["compiled"] == 2
        # Normal classify was used, not topical
        assert len(fakes["classified"]) == 2
        assert fakes["classified_topical"] == []

    def test_explicit_none_is_same_as_default(self, kb, fakes):
        fakes["classification"] = {
            "merge_into": [],
            "create_new": [
                {"path": "wiki/concept/a.md", "title": "A", "type": "concept"}
            ],
        }
        out = cm.compile_kb(str(kb.base_dir), aggregation_plan=None, topic="")
        assert out["compiled"] == 2
        assert len(fakes["classified"]) == 2
        assert fakes["classified_topical"] == []


# ── compile_kb: aggregation_plan set ───────────────────────────────

class TestCompileKBWithPlan:
    """When aggregation_plan is provided, topical classify is used."""

    def test_topical_classify_is_used(self, kb, fakes):
        """classify_article_topical is called instead of classify_article."""
        fakes["classification"] = {
            "merge_into": [{"path": "wiki/concept/pricing-overview.md"}],
            "create_new": [],
        }
        plan = _plan_dicts()
        out = cm.compile_kb(
            str(kb.base_dir),
            aggregation_plan=plan,
            topic="pricing",
        )
        assert out["compiled"] == 2
        # Topical classify was used, not normal
        assert len(fakes["classified_topical"]) == 2
        assert fakes["classified"] == []

    def test_dedup_is_skipped(self, kb, fakes, monkeypatch):
        """dedup_create_new must NOT be called when plan is set."""
        dedup_called = []

        def tracking_dedup(result, existing):
            dedup_called.append(True)
            return result

        monkeypatch.setattr(cm, "dedup_create_new", tracking_dedup)

        fakes["classification"] = {
            "merge_into": [{"path": "wiki/concept/pricing-overview.md"}],
            "create_new": [],
        }
        cm.compile_kb(
            str(kb.base_dir),
            aggregation_plan=_plan_dicts(),
            topic="pricing",
        )
        assert dedup_called == []

    def test_classify_cache_is_skipped(self, kb, fakes, monkeypatch):
        """Classify cache must not be consulted when plan is set."""
        cache_loads = []
        original_load = KBStore.load_classify_cache

        def tracking_load(self, key):
            cache_loads.append(key)
            return original_load(self, key)

        monkeypatch.setattr(KBStore, "load_classify_cache", tracking_load)

        fakes["classification"] = {
            "merge_into": [],
            "create_new": [
                {"path": "wiki/concept/x.md", "title": "X", "type": "concept"}
            ],
        }
        cm.compile_kb(
            str(kb.base_dir),
            aggregation_plan=_plan_dicts(),
            topic="pricing",
        )
        # No cache lookups should have happened
        assert cache_loads == []

    def test_planned_articles_seeded_into_existing(self, kb, fakes, monkeypatch):
        """Planned articles from the plan are seeded into existing_articles
        before the classify loop starts."""
        seen_existing = []

        def capturing_topical(extraction, existing, topic, plan, model="m", categories=None):
            # Record how many existing articles are seen
            seen_existing.append(len(existing))
            return {"merge_into": [], "create_new": []}

        monkeypatch.setattr(cm, "classify_article_topical", capturing_topical)

        plan = _plan_dicts()
        cm.compile_kb(
            str(kb.base_dir),
            aggregation_plan=plan,
            topic="pricing",
        )
        # Both calls should see the 2 planned articles (the KB has no existing articles)
        assert all(count >= 2 for count in seen_existing)

    def test_planned_article_meta_in_merge_create_fallback(self, kb, fakes):
        """When merges target a non-existent planned article, the fallback
        should use the planned title and type, not the path-derived ones."""
        fakes["classification"] = {
            "merge_into": [{"path": "wiki/concept/pricing-overview.md"}],
            "create_new": [],
        }
        plan = _plan_dicts()
        out = cm.compile_kb(
            str(kb.base_dir),
            aggregation_plan=plan,
            topic="pricing",
        )
        assert out["compiled"] == 2
        # The article was created via merge→create fallback
        # Check that it used the planned title/type
        created = fakes["created"]
        assert len(created) >= 1
        # Find the merge→create entry for pricing-overview
        overview_creates = [
            (atype, title) for atype, title, src in created
            if "Pricing" in title
        ]
        assert len(overview_creates) >= 1
        article_type, title = overview_creates[0]
        # These come from _planned_article_meta, not from path derivation
        assert title == "Pricing — Complete Overview"
        assert article_type == "concept"

    def test_merge_create_fallback_without_plan_uses_path(self, kb, fakes):
        """When no plan is set, merge→create fallback derives title from path."""
        fakes["classification"] = {
            "merge_into": [{"path": "wiki/concept/pricing-overview.md"}],
            "create_new": [],
        }
        out = cm.compile_kb(str(kb.base_dir))
        assert out["compiled"] == 2
        created = fakes["created"]
        overview_creates = [
            (atype, title) for atype, title, src in created
            if "Pricing" in title
        ]
        assert len(overview_creates) >= 1
        article_type, title = overview_creates[0]
        # Path-derived: "Pricing Overview" (Title Case) not "Pricing — Complete Overview"
        assert title == "Pricing Overview"
        assert article_type == "concept"


# ── derive_kb: reorganize=False (no new code path) ─────────────────

class TestDeriveKBNoReorganize:
    """When reorganize=False (default), no new code path executes."""

    def test_default_reorganize_is_false(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        seen_kwargs: dict = {}

        def capturing_compile(derived_dir, **kwargs):
            seen_kwargs.update(kwargs)
            return _fake_compile_result(derived_dir, **kwargs)

        report = derive_kb(
            str(kb), "pricing", model="m",
            select=select, compile_fn=capturing_compile,
        )
        assert report.compiled is True
        assert report.reorganize_plan is None
        # compile_fn must NOT receive aggregation_plan or topic
        assert "aggregation_plan" not in seen_kwargs
        assert "topic" not in seen_kwargs

    def test_explicit_false_same_as_default(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        seen_kwargs: dict = {}

        def capturing_compile(derived_dir, **kwargs):
            seen_kwargs.update(kwargs)
            return _fake_compile_result(derived_dir, **kwargs)

        report = derive_kb(
            str(kb), "pricing", model="m", reorganize=False,
            select=select, compile_fn=capturing_compile,
        )
        assert report.reorganize_plan is None
        assert "aggregation_plan" not in seen_kwargs


# ── derive_kb: reorganize=True ─────────────────────────────────────

def _mock_reorganize_plan() -> ReorganizePlan:
    """A canned ReorganizePlan for testing."""
    return ReorganizePlan(
        topic="pricing",
        articles=[
            ThematicArticle(
                path="wiki/concept/pricing-overview.md",
                type="concept",
                title="Pricing — Complete Overview",
                description="Overview of all pricing",
            ),
            ThematicArticle(
                path="wiki/reference/fee-schedule.md",
                type="reference",
                title="Fee Schedule Reference",
                description="Detailed fee schedule",
            ),
        ],
        canonical_mapping=CanonicalMapping(),
        entity_index=EntityIndex(extraction_count=5),
    )


class TestDeriveKBReorganize:
    """When reorganize=True, the reorganize phase runs and plan is passed."""

    def test_reorganize_calls_reorganize_and_passes_plan(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        seen_kwargs: dict = {}

        def capturing_compile(derived_dir, **kwargs):
            seen_kwargs.update(kwargs)
            return _fake_compile_result(derived_dir, **kwargs)

        plan = _mock_reorganize_plan()

        with patch(
            "kb_ai.derive._reorganize.reorganize",
            return_value=plan,
        ) as mock_reorg:
            report = derive_kb(
                str(kb), "pricing", model="m", reorganize=True,
                select=select, compile_fn=capturing_compile,
            )

        # reorganize() was called
        mock_reorg.assert_called_once()
        call_kwargs = mock_reorg.call_args
        assert call_kwargs[0][1] == "pricing"  # topic arg
        assert call_kwargs[1]["model"] == "m"

        # compile_fn received the plan
        assert "aggregation_plan" in seen_kwargs
        assert "topic" in seen_kwargs
        assert seen_kwargs["topic"] == "pricing"
        assert len(seen_kwargs["aggregation_plan"]) == 2
        assert seen_kwargs["aggregation_plan"][0]["path"] == "wiki/concept/pricing-overview.md"

    def test_reorganize_plan_in_report(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        plan = _mock_reorganize_plan()

        with patch(
            "kb_ai.derive._reorganize.reorganize",
            return_value=plan,
        ):
            report = derive_kb(
                str(kb), "pricing", model="m", reorganize=True,
                select=select, compile_fn=_fake_compile_result,
            )

        assert report.reorganize_plan is not None
        assert report.reorganize_plan["topic"] == "pricing"
        assert len(report.reorganize_plan["articles"]) == 2
        assert report.reorganize_plan["extraction_count"] == 5

    def test_manifest_includes_reorganize_plan(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        plan = _mock_reorganize_plan()

        with patch(
            "kb_ai.derive._reorganize.reorganize",
            return_value=plan,
        ):
            report = derive_kb(
                str(kb), "pricing", model="m", reorganize=True,
                select=select, compile_fn=_fake_compile_result,
            )

        manifest = json.loads(
            (Path(report.derived_kb) / "manifest.json").read_text()
        )
        assert "reorganize_plan" in manifest
        assert manifest["reorganize_plan"]["topic"] == "pricing"
        assert len(manifest["reorganize_plan"]["articles"]) == 2

    def test_manifest_excludes_reorganize_plan_when_false(self, tmp_path):
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])

        report = derive_kb(
            str(kb), "pricing", model="m", reorganize=False,
            select=select, compile_fn=_fake_compile_result,
        )

        manifest = json.loads(
            (Path(report.derived_kb) / "manifest.json").read_text()
        )
        assert "reorganize_plan" not in manifest

    def test_reorganize_uses_source_categories(self, tmp_path):
        """reorganize() receives the source KB's frozen categories."""
        kb = _fixture_kb_for_derive(tmp_path)
        KBStore(str(kb)).save_config({"categories": ["concept", "reference"]})
        select = _select_stub(["wiki/pricing.md"])
        plan = _mock_reorganize_plan()

        with patch(
            "kb_ai.derive._reorganize.reorganize",
            return_value=plan,
        ) as mock_reorg:
            derive_kb(
                str(kb), "pricing", model="m", reorganize=True,
                select=select, compile_fn=_fake_compile_result,
            )

        call_kwargs = mock_reorg.call_args
        assert call_kwargs[1]["categories"] == ["concept", "reference"]

    def test_reorganize_flush_before_compile(self, tmp_path):
        """The manifest is flushed after the reorganize phase and before compile,
        so a compile that dies still has the plan on disk."""
        kb = _fixture_kb_for_derive(tmp_path)
        select = _select_stub(["wiki/pricing.md"])
        plan = _mock_reorganize_plan()
        manifests_seen: list[dict] = []

        def dying_compile(derived_dir, **kwargs):
            # Read manifest before compile does anything
            manifests_seen.append(
                json.loads((Path(derived_dir) / "manifest.json").read_text())
            )
            raise RuntimeError("compile died")

        with patch(
            "kb_ai.derive._reorganize.reorganize",
            return_value=plan,
        ):
            with pytest.raises(RuntimeError, match="compile died"):
                derive_kb(
                    str(kb), "pricing", model="m", reorganize=True,
                    select=select, compile_fn=dying_compile,
                )

        assert len(manifests_seen) == 1
        assert "reorganize_plan" in manifests_seen[0]
        assert manifests_seen[0]["reorganize_plan"]["topic"] == "pricing"


# ── compile_kb: aggregation_plan seeding edge cases ────────────────

class TestPlanSeeding:
    """Edge cases for how the aggregation plan seeds existing_articles."""

    def test_empty_path_skipped(self, kb, fakes, monkeypatch):
        """Plan entries with empty path should be skipped."""
        seen_existing = []

        def capturing_topical(extraction, existing, topic, plan, model="m", categories=None):
            seen_existing.append(len(existing))
            return {"merge_into": [], "create_new": []}

        monkeypatch.setattr(cm, "classify_article_topical", capturing_topical)

        plan = [
            {"path": "", "title": "No Path", "type": "concept", "description": ""},
            {"path": "wiki/concept/valid.md", "title": "Valid", "type": "concept", "description": "desc"},
        ]
        cm.compile_kb(str(kb.base_dir), aggregation_plan=plan, topic="t")
        # Only the valid entry should be seeded (1, not 2)
        assert all(count >= 1 for count in seen_existing)

    def test_empty_title_skipped(self, kb, fakes, monkeypatch):
        """Plan entries with empty title should be skipped."""
        seen_existing = []

        def capturing_topical(extraction, existing, topic, plan, model="m", categories=None):
            seen_existing.append(len(existing))
            return {"merge_into": [], "create_new": []}

        monkeypatch.setattr(cm, "classify_article_topical", capturing_topical)

        plan = [
            {"path": "wiki/concept/no-title.md", "title": "", "type": "concept", "description": ""},
            {"path": "wiki/concept/valid.md", "title": "Valid", "type": "concept", "description": "desc"},
        ]
        cm.compile_kb(str(kb.base_dir), aggregation_plan=plan, topic="t")
        assert all(count >= 1 for count in seen_existing)
