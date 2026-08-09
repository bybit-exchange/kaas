"""End-to-end tests for derive.derive_kb with a stub filter and stub compile (I2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._cost import CostTracker
from kb_ai._errors import (
    DeriveError, NestedDeriveError, NoCatalogError, NoDocumentsError, SlugExistsError,
)
from kb_ai.derive import derive_kb
from kb_ai.derive._types import MODE_PRECISION, MODE_RECALL, SelectionResult, Skipped
from kb_ai.llm import set_request_tracker


def _fixture_kb(tmp_path: Path) -> Path:
    """A compiled-looking source KB: two articles with sources:, one without."""
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "wiki").mkdir(parents=True)
    (kb / "index").mkdir(parents=True)

    (kb / "raw" / "pricing-notes.md").write_text("Fee schedule and tiers.")
    (kb / "raw" / "infra-notes.md").write_text("Cluster topology.")

    (kb / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\nsources:\n  - raw/pricing-notes.md\n---\n\n# Pricing\n")
    (kb / "wiki" / "fees.md").write_text(
        "---\ntitle: Fees\nsources:\n  - raw/pricing-notes.md\n---\n\n# Fees\n")
    (kb / "wiki" / "orphan.md").write_text(
        "---\ntitle: Orphan\n---\n\n# Orphan\n")
    (kb / "wiki" / "infra.md").write_text(
        "---\ntitle: Infra\nsources:\n  - raw/infra-notes.md\n---\n\n# Infra\n")

    (kb / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Fees](wiki/fees.md) — What we charge.\n"
        "- [Infra](wiki/infra.md) — Cluster topology.\n"
        "- [Orphan](wiki/orphan.md) — No sources.\n"
        "- [Pricing](wiki/pricing.md) — Fee schedule.\n"
    )
    return kb


def _select(first: list[str], second: list[str] | None = None):
    """Stub selector: RECALL returns `first`, PRECISION returns `second`."""
    seen: list[str] = []

    def select(catalog, topic, mode):
        seen.append(mode)
        wanted = first if mode == MODE_RECALL else (second if second is not None else [])
        present = {a.path for a in catalog}
        return SelectionResult(paths=[p for p in wanted if p in present],
                               batches=1, dropped_invented=1, skipped=[])

    return select, seen


def _fake_compile(derived_dir: str, **kwargs) -> dict:
    """Stand in for compile_kb: write one article and a catalog naming it."""
    base = Path(derived_dir)
    (base / "wiki").mkdir(parents=True, exist_ok=True)
    (base / "index").mkdir(parents=True, exist_ok=True)
    (base / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\ntags: [fees]\n---\n\n# Pricing\n\nProse.\n")
    (base / "wiki" / "stray.md").write_text(
        "---\ntitle: Stray\ntags: [misc]\n---\n\n# Stray\n\nProse.\n")
    (base / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Pricing](wiki/pricing.md) — Fees.\n"
        "- [Stray](wiki/stray.md) — Unrelated.\n"
    )
    return {"compiled": 2, "errors": [], "cost": {"total_cost_usd": 1.25}}


def test_happy_path_layout_and_report(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md", "wiki/fees.md", "wiki/orphan.md"],
                            ["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing and fees", model="m", prune=True,
                       select=select, compile_fn=_fake_compile)

    derived = kb / "derived" / "pricing-and-fees"
    assert report.derived_kb == str(derived)
    assert report.slug == "pricing-and-fees"
    assert modes == [MODE_RECALL, MODE_PRECISION]

    # Only the document behind the selected articles was copied.
    assert (derived / "raw" / "pricing-notes.md").read_text() == "Fee schedule and tiers."
    assert not (derived / "raw" / "infra-notes.md").exists()

    assert report.selected_articles == ["wiki/pricing.md", "wiki/fees.md", "wiki/orphan.md"]
    assert [(s.ref, s.reason) for s in report.skipped_articles] == [
        ("wiki/orphan.md", "no_sources_key")]
    assert [d.rel_path for d in report.documents] == ["raw/pricing-notes.md"]
    assert report.dropped_invented_paths == 1
    assert report.filter_batches == 1
    assert report.compiled is True
    # compile_kb's own "cost" key is stripped: it is a process-wide tracker
    # summary, not this run's spend. report.cost is the authoritative figure.
    assert report.compile == {"compiled": 2, "errors": []}
    assert report.offtopic_articles == ["wiki/stray.md"]
    assert (derived / "_offtopic" / "stray.md").exists()


def test_the_precision_pass_is_off_by_default(tmp_path: Path):
    """RECALL is the only pass that runs unless pruning is asked for.

    Two measured runs put the move ratio at 0.83 and 0.00 -- too strict, then
    selecting nothing at all -- so the pass ships off and stays available as an
    instrument rather than shaping the default output.
    """
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing", model="m",
                       select=select, compile_fn=_fake_compile)

    assert modes == [MODE_RECALL]
    assert report.offtopic_articles == []
    assert not (kb / "derived" / "pricing" / "_offtopic").exists()
    # The article the pass would have moved is still in the derived wiki.
    assert (kb / "derived" / "pricing" / "wiki" / "stray.md").exists()


def test_prune_opts_into_the_precision_pass(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing", model="m", prune=True,
                       select=select, compile_fn=_fake_compile)

    assert modes == [MODE_RECALL, MODE_PRECISION]
    assert report.offtopic_articles == ["wiki/stray.md"]
    assert (kb / "derived" / "pricing" / "_offtopic" / "stray.md").exists()


def test_the_derived_compile_inherits_the_source_categories(tmp_path: Path):
    """A derived KB is a KB: it must not re-partition under a different taxonomy.

    The source's set is frozen in its kaas.json. Letting the derived compile fall
    back to DEFAULT_CATEGORIES would file articles under categories the operator
    excluded, which is the silent re-partition freezing exists to prevent.
    """
    from kb_ai.storage.store import KBStore

    kb = _fixture_kb(tmp_path)
    KBStore(str(kb)).save_config({"categories": ["concept", "decision"]})
    select, _ = _select(["wiki/pricing.md"])
    seen: dict = {}

    def capturing_compile(derived_dir: str, **kwargs) -> dict:
        seen.update(kwargs)
        return _fake_compile(derived_dir, **kwargs)

    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=capturing_compile)

    assert seen["categories"] == ["concept", "decision"]


def test_a_source_without_a_frozen_set_leaves_the_categories_unset(tmp_path: Path):
    """A KB predating the frozen-config feature keeps the compile's own default."""
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"])
    seen: dict = {}

    def capturing_compile(derived_dir: str, **kwargs) -> dict:
        seen.update(kwargs)
        return _fake_compile(derived_dir, **kwargs)

    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=capturing_compile)

    assert seen["categories"] is None


def test_manifest_contents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md", "wiki/orphan.md"], ["wiki/pricing.md"])

    derive_kb(str(kb), "pricing", model="gpt-test", slug="p", prune=True,
              select=select, compile_fn=_fake_compile)

    manifest = json.loads((kb / "derived" / "p" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["source_kb"] == str(kb.resolve())
    assert manifest["topic"] == "pricing"
    assert manifest["slug"] == "p"
    assert manifest["filter_model"] == "gpt-test"
    assert manifest["created_at"]
    assert manifest["selected_articles"] == [
        {"path": "wiki/pricing.md", "title": "Pricing", "sources": ["raw/pricing-notes.md"]},
        {"path": "wiki/orphan.md", "title": "Orphan", "sources": []},
    ]
    assert manifest["skipped_articles"] == [
        {"path": "wiki/orphan.md", "reason": "no_sources_key"}]
    assert len(manifest["documents"]) == 1
    assert set(manifest["documents"][0]) == {"rel_path", "checksum", "size_bytes"}
    assert manifest["documents"][0]["checksum"] and len(manifest["documents"][0]["checksum"]) == 16
    assert manifest["dropped_invented_paths"] == 1
    assert manifest["offtopic_articles"] == ["wiki/stray.md"]
    assert manifest["compile"]["compiled"] == 2
    assert "cost" in manifest


def test_manifest_is_written_before_compiling(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    seen: dict = {}

    def dying_compile(derived_dir: str, **kwargs):
        seen["manifest"] = json.loads(
            (Path(derived_dir) / "manifest.json").read_text())
        raise RuntimeError("compile died")

    with pytest.raises(RuntimeError, match="compile died"):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=dying_compile)

    assert seen["manifest"]["slug"] == "pricing"
    assert seen["manifest"]["documents"]


def test_a_failed_copy_leaves_a_manifest_a_force_retry_accepts(tmp_path: Path,
                                                               monkeypatch):
    """A derive that dies while copying documents must stay recoverable.

    The manifest is written as soon as create() succeeds, so the half-built
    directory identifies itself as derive's own and check_slug_available lets the
    --force retry the CLI advises replace it. Before the fix the retry hit
    "refusing to replace a directory this command did not create" and the only
    way out was a manual rm -rf.
    """
    import kb_ai.derive as derive_mod

    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    real_copy = derive_mod.copy_documents

    def failing_copy(*a, **kw):
        raise OSError("ENOSPC")

    monkeypatch.setattr(derive_mod, "copy_documents", failing_copy)
    with pytest.raises(OSError, match="ENOSPC"):
        derive_kb(str(kb), "pricing", model="m", select=select,
                  compile_fn=_fake_compile)

    derived = kb / "derived" / "pricing"
    manifest = json.loads((derived / "manifest.json").read_text())
    assert manifest["slug"] == "pricing"
    assert manifest["compiled"] is False
    assert manifest["documents"] == []  # nothing was copied, so nothing is claimed

    monkeypatch.setattr(derive_mod, "copy_documents", real_copy)
    report = derive_kb(str(kb), "pricing", model="m", force=True, select=select,
                       compile_fn=_fake_compile)
    assert report.compiled is True
    assert (derived / "raw" / "pricing-notes.md").exists()


def test_declining_the_gate_leaves_raw_and_manifest_uncompiled(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    def compile_fn(*a, **kw):
        raise AssertionError("compile must not run when the gate declines")

    report = derive_kb(str(kb), "pricing", model="m", select=select,
                       compile_fn=compile_fn, approve=lambda r: False)

    derived = kb / "derived" / "pricing"
    assert report.compiled is False
    assert report.compile is None
    assert (derived / "raw" / "pricing-notes.md").exists()
    assert (derived / "manifest.json").exists()
    assert modes == [MODE_RECALL]  # the second pass never ran


def test_the_gate_sees_the_resolved_documents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    seen: dict = {}

    def approve(report):
        seen["docs"] = [(d.rel_path, d.size_bytes) for d in report.documents]
        return True

    derive_kb(str(kb), "pricing", model="m", select=select,
              compile_fn=_fake_compile, approve=approve)

    assert seen["docs"] == [("raw/pricing-notes.md", len("Fee schedule and tiers.".encode()))]


def test_no_catalog(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(NoCatalogError):
        derive_kb(str(bare), "pricing", model="m",
                  select=lambda *a: SelectionResult([], 0, 0, []),
                  compile_fn=_fake_compile)


def test_no_documents_creates_no_derived_dir(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/orphan.md"])
    with pytest.raises(NoDocumentsError):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)
    assert not (kb / "derived").exists()


def test_slug_exists_is_raised_before_any_llm_call(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    (kb / "derived" / "pricing").mkdir(parents=True)

    def select(*args):
        raise AssertionError("the filter must not run when the slug is taken")

    with pytest.raises(SlugExistsError):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)


def test_force_replaces_a_previous_run(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)
    stale = kb / "derived" / "pricing" / "stale.txt"
    stale.write_text("old")

    derive_kb(str(kb), "pricing", model="m", force=True,
              select=select, compile_fn=_fake_compile)
    assert not stale.exists()


def test_nested_derive_is_refused(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)

    with pytest.raises(NestedDeriveError):
        derive_kb(str(kb / "derived" / "pricing"), "fees", model="m",
                  select=select, compile_fn=_fake_compile)


def test_extractions_travel_with_their_documents(tmp_path: Path):
    """A derived KB gets the same four layers as its parent (spec F1, F4)."""
    kb = _fixture_kb(tmp_path)
    from kb_ai.core.extract import ExtractionResult
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore, _compute_checksum
    checksum = _compute_checksum("Fee schedule and tiers.")
    exl.persist(KBStore(str(kb)), "raw/pricing-notes.md",
                ExtractionResult(summary="extracted pricing"),
                source_checksum=checksum, extract_model="m")

    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    report = derive_kb(str(kb), "pricing", model="m", select=select,
                       compile_fn=_fake_compile)

    copied = kb / "derived" / "pricing" / "extraction" / "pricing-notes.md"
    assert "summary: extracted pricing" in copied.read_text()
    assert report.warnings == []


def test_a_mismatched_extraction_is_reported_as_a_warning(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    from kb_ai.core.extract import ExtractionResult
    from kb_ai.storage import extraction as exl
    from kb_ai.storage.store import KBStore
    exl.persist(KBStore(str(kb)), "raw/pricing-notes.md",
                ExtractionResult(summary="describes different text"),
                source_checksum="0" * 16, extract_model="m")

    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    report = derive_kb(str(kb), "pricing", model="m", select=select,
                       compile_fn=_fake_compile)

    assert not (kb / "derived" / "pricing" / "extraction").exists()
    assert len(report.warnings) == 1
    assert "does not match the document" in report.warnings[0]


def test_cost_covers_both_passes_and_exceeds_compile_snapshot(tmp_path: Path):
    """report.cost must include PRECISION spend that compile's cost snapshot cannot hold (F6)."""
    kb = _fixture_kb(tmp_path)
    req_tracker = CostTracker(store_details=False)
    snapshot: dict = {}

    # Stub selector records one LLM call per pass (RECALL + PRECISION = 2 calls).
    def select_with_cost(catalog, topic, mode):
        req_tracker.record("claude-haiku-4-5", prompt_tokens=100, completion_tokens=10)
        wanted = ["wiki/pricing.md"]
        present = {a.path for a in catalog}
        return SelectionResult(paths=[p for p in wanted if p in present],
                               batches=1, dropped_invented=0, skipped=[])

    # Stub compile records one LLM call and returns a cost snapshot of that call only.
    # This snapshot predates the PRECISION pass, so it does not include its cost.
    def compile_with_cost(derived_dir: str, **kwargs) -> dict:
        compile_cost = req_tracker.record("claude-haiku-4-5",
                                          prompt_tokens=200, completion_tokens=20)
        base = Path(derived_dir)
        (base / "wiki").mkdir(parents=True, exist_ok=True)
        (base / "index").mkdir(parents=True, exist_ok=True)
        (base / "wiki" / "pricing.md").write_text(
            "---\ntitle: Pricing\n---\n\n# Pricing\n\nProse.\n")
        (base / "index" / "master-index.md").write_text(
            "# Knowledge Base Index\n\n"
            "- [Pricing](wiki/pricing.md) — Fees.\n"
        )
        snapshot["cost"] = {"total_cost_usd": round(compile_cost, 6)}
        return {"compiled": 1, "errors": [], "cost": snapshot["cost"]}

    set_request_tracker(req_tracker)
    try:
        report = derive_kb(str(kb), "pricing", model="m", prune=True,
                           select=select_with_cost, compile_fn=compile_with_cost)
    finally:
        set_request_tracker(None)

    # 3 recorded calls: RECALL + compile + PRECISION (the last one is AFTER compile's snapshot).
    assert report.cost["calls"] == 3
    # The whole-run total must exceed compile's own cost snapshot (which lacks PRECISION).
    assert report.cost["total_cost_usd"] > snapshot["cost"]["total_cost_usd"]
    # Shape differs too: tracker.summary() carries token counts that compile's dict does not.
    assert report.cost != snapshot["cost"]


def test_the_reported_compile_blob_carries_no_cost(tmp_path: Path):
    """compile_kb's "cost" is a process-wide tracker summary, so derive drops it.

    In the CLI it silently includes the RECALL pass; in the long-lived daemon it is
    the daemon's lifetime spend, and this feature publishes the blob over HTTP and
    into the manifest. report.cost is the authoritative per-request figure.
    """
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing", model="m", select=select,
                       compile_fn=_fake_compile)

    assert "cost" not in report.compile
    assert report.compile["compiled"] == 2
    assert report.cost is not None

    manifest = json.loads((kb / "derived" / "pricing" / "manifest.json").read_text())
    assert "cost" not in manifest["compile"]
    assert manifest["cost"] is not None


def test_a_declined_gate_still_reports_the_recall_pass_cost(tmp_path: Path):
    """The RECALL pass is already paid for when the gate is offered (F6, E3).

    Reporting cost: null there hides real spend -- N LLM calls on a large catalog
    -- in both the CLI payload and the on-disk manifest.
    """
    kb = _fixture_kb(tmp_path)
    req_tracker = CostTracker(store_details=False)

    def select_with_cost(catalog, topic, mode):
        req_tracker.record("claude-haiku-4-5", prompt_tokens=100, completion_tokens=10)
        present = {a.path for a in catalog}
        return SelectionResult(paths=[p for p in ["wiki/pricing.md"] if p in present],
                               batches=1, dropped_invented=0, skipped=[])

    def compile_fn(*a, **kw):
        raise AssertionError("compile must not run when the gate declines")

    set_request_tracker(req_tracker)
    try:
        report = derive_kb(str(kb), "pricing", model="m", select=select_with_cost,
                           compile_fn=compile_fn, approve=lambda r: False)
    finally:
        set_request_tracker(None)

    assert report.compiled is False
    assert report.cost == req_tracker.summary()
    assert report.cost["calls"] == 1
    assert report.cost["total_cost_usd"] > 0

    manifest = json.loads((kb / "derived" / "pricing" / "manifest.json").read_text())
    assert manifest["cost"]["total_cost_usd"] == report.cost["total_cost_usd"]


def test_per_request_tracker_takes_precedence_over_global(tmp_path: Path, monkeypatch):
    """derive_kb reports the per-request tracker when one is set, not the global one."""
    import kb_ai.derive as _derive_mod

    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    # Replace the module-level 'tracker' reference in derive/__init__ with a fresh
    # local instance so the test does not mutate the process-wide global tracker.
    fake_global = CostTracker(store_details=False)
    monkeypatch.setattr(_derive_mod, "tracker", fake_global)
    # Give the fake global some spend so the two trackers are distinguishable.
    fake_global.record("claude-haiku-4-5", prompt_tokens=500, completion_tokens=50)

    # Per-request tracker has a different, specific amount of spend.
    req_tracker = CostTracker(store_details=False)
    req_tracker.record("claude-haiku-4-5", prompt_tokens=77, completion_tokens=7)

    set_request_tracker(req_tracker)
    try:
        report = derive_kb(str(kb), "pricing", model="m",
                           select=select, compile_fn=_fake_compile)
    finally:
        set_request_tracker(None)

    # report.cost must equal the per-request tracker's summary, not the global's.
    assert report.cost == req_tracker.summary()
    assert report.cost != fake_global.summary()


# ── select_from="documents" ──────────────────────────────────────────

def _uncompiled_kb(tmp_path: Path) -> Path:
    """A KB that was fetched into but never compiled: raw only, no wiki, no catalog."""
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "raw" / "pricing-notes.md").write_text(
        "---\ntitle: Pricing Notes\ndate: 2026-06-03\nsource: lark\n---\n\nFee schedule and tiers.")
    (kb / "raw" / "infra-notes.md").write_text(
        "---\ntitle: Infra Notes\n---\n\nCluster topology.")
    return kb


def test_documents_mode_selects_documents_directly(tmp_path: Path):
    """The selected path IS the document, so no sources: hop is involved."""
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["raw/pricing-notes.md"])

    report = derive_kb(str(kb), "pricing", model="m", select_from="documents",
                       select=select, compile_fn=_fake_compile)

    assert report.selected_documents == ["raw/pricing-notes.md"]
    assert report.selected_articles == []
    assert [d.rel_path for d in report.documents] == ["raw/pricing-notes.md"]
    assert modes == [MODE_RECALL]


def test_documents_mode_works_on_an_uncompiled_kb(tmp_path: Path):
    """The whole point: an article catalog does not exist yet, and requiring one
    would mean every KB must be compiled before it can contribute to a topic."""
    kb = _uncompiled_kb(tmp_path)
    select, _ = _select(["raw/pricing-notes.md"])

    report = derive_kb(str(kb), "pricing", model="m", select_from="documents",
                       select=select, compile_fn=_fake_compile)

    assert [d.rel_path for d in report.documents] == ["raw/pricing-notes.md"]


def test_documents_mode_does_not_write_to_the_source_kb(tmp_path: Path):
    """A source KB may belong to someone else and be read-only; the in-memory
    catalog must be used rather than materialising an index inside it."""
    kb = _uncompiled_kb(tmp_path)
    select, _ = _select(["raw/pricing-notes.md"])

    derive_kb(str(kb), "pricing", model="m", select_from="documents",
              select=select, compile_fn=_fake_compile)

    assert not (kb / "index" / "document-index.md").exists()


def test_documents_mode_sees_the_document_catalog(tmp_path: Path):
    """The selector must receive document lines -- title, date, source and the
    summary -- not article lines."""
    kb = _uncompiled_kb(tmp_path)
    seen: list = []

    def select(catalog, topic, mode):
        seen.append(list(catalog))
        return SelectionResult(paths=[catalog[0].path], batches=1,
                               dropped_invented=0, skipped=[])

    derive_kb(str(kb), "pricing", model="m", select_from="documents",
              select=select, compile_fn=_fake_compile)

    paths = {a.path for a in seen[0]}
    assert paths == {"raw/infra-notes.md", "raw/pricing-notes.md"}
    pricing = next(a for a in seen[0] if a.path == "raw/pricing-notes.md")
    assert "2026-06-03" in pricing.summary
    assert "lark" in pricing.summary
    assert "Fee schedule" in pricing.summary


def test_documents_mode_prefers_a_written_document_index(tmp_path: Path):
    """When the index exists it is read rather than recomputed -- that is what
    makes a selection free on an already-compiled KB."""
    kb = _uncompiled_kb(tmp_path)
    (kb / "index").mkdir(exist_ok=True)
    (kb / "index" / "document-index.md").write_text(
        "# Document Index\n\n- [Only One](raw/pricing-notes.md) — Hand-written line.\n")
    seen: list = []

    def select(catalog, topic, mode):
        seen.append(list(catalog))
        return SelectionResult(paths=["raw/pricing-notes.md"], batches=1,
                               dropped_invented=0, skipped=[])

    derive_kb(str(kb), "pricing", model="m", select_from="documents",
              select=select, compile_fn=_fake_compile)

    assert [a.path for a in seen[0]] == ["raw/pricing-notes.md"]
    assert seen[0][0].summary == "Hand-written line."


def test_documents_mode_records_the_mode_in_the_manifest(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["raw/pricing-notes.md"])

    report = derive_kb(str(kb), "pricing", model="m", select_from="documents",
                       select=select, compile_fn=_fake_compile)

    manifest = json.loads((Path(report.derived_kb) / "manifest.json").read_text())
    assert manifest["select_from"] == "documents"
    assert manifest["selected_documents"] == ["raw/pricing-notes.md"]


def test_articles_mode_stays_the_default(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing", model="m",
                       select=select, compile_fn=_fake_compile)

    manifest = json.loads((Path(report.derived_kb) / "manifest.json").read_text())
    assert manifest["select_from"] == "articles"
    assert report.selected_articles == ["wiki/pricing.md"]
    assert report.selected_documents == []


def test_documents_mode_with_an_empty_raw_dir(tmp_path: Path):
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    select, _ = _select([])

    with pytest.raises(NoDocumentsError):
        derive_kb(str(kb), "pricing", model="m", select_from="documents",
                  select=select, compile_fn=_fake_compile)


def test_unknown_select_from_is_rejected(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select([])

    with pytest.raises(DeriveError, match="select_from"):
        derive_kb(str(kb), "pricing", model="m", select_from="everything",
                  select=select, compile_fn=_fake_compile)


def test_documents_mode_records_dropped_lines_as_documents(tmp_path: Path):
    """A catalog line too long for a whole batch is dropped by pack_batches. In
    documents mode that ref is a document path, so recording it under
    skipped_articles would file a document under the wrong kind of path."""
    kb = _uncompiled_kb(tmp_path)

    def select(catalog, topic, mode):
        return SelectionResult(
            paths=["raw/pricing-notes.md"], batches=1, dropped_invented=0,
            skipped=[Skipped(ref="raw/infra-notes.md", reason="line_over_budget")])

    report = derive_kb(str(kb), "pricing", model="m", select_from="documents",
                       select=select, compile_fn=_fake_compile)

    assert report.skipped_articles == []
    assert ("raw/infra-notes.md", "line_over_budget") in [
        (s.ref, s.reason) for s in report.skipped_documents]


def test_the_derived_compile_inherits_the_configured_extract_strategy(tmp_path: Path):
    """Same shape as extract_model: without it the derived compile runs on
    compile_kb's own default, so every extraction the copy inherited from a
    summarize deployment reads as stale and is re-extracted at full price -- and
    re-recorded as chunked, which the next parent compile then finds stale too."""
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"])
    seen: dict = {}

    def capturing_compile(derived_dir: str, **kwargs) -> dict:
        seen.update(kwargs)
        return _fake_compile(derived_dir, **kwargs)

    derive_kb(str(kb), "pricing", model="m", select=select,
              extract_strategy="summarize", summarize_model="sm",
              compile_fn=capturing_compile)

    assert seen["extract_strategy"] == "summarize"
    assert seen["summarize_model"] == "sm"


def test_the_derived_compile_defaults_to_chunked(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"])
    seen: dict = {}

    def capturing_compile(derived_dir: str, **kwargs) -> dict:
        seen.update(kwargs)
        return _fake_compile(derived_dir, **kwargs)

    derive_kb(str(kb), "pricing", model="m", select=select,
              compile_fn=capturing_compile)

    assert seen["extract_strategy"] == "chunked"
