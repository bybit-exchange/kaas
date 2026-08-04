"""End-to-end tests for derive.derive_kb with a stub filter and stub compile (I2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import (
    NestedDeriveError, NoCatalogError, NoDocumentsError, SlugExistsError,
)
from kb_ai.derive import derive_kb
from kb_ai.derive._types import MODE_PRECISION, MODE_RECALL, SelectionResult


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

    report = derive_kb(str(kb), "pricing and fees", model="m",
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
    assert report.compile == {"compiled": 2, "errors": [], "cost": {"total_cost_usd": 1.25}}
    assert report.offtopic_articles == ["wiki/stray.md"]
    assert (derived / "_offtopic" / "stray.md").exists()


def test_manifest_contents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md", "wiki/orphan.md"], ["wiki/pricing.md"])

    derive_kb(str(kb), "pricing", model="gpt-test", slug="p",
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


def test_extract_cache_entries_travel_with_their_documents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    from kb_ai.storage.store import _compute_checksum
    checksum = _compute_checksum("Fee schedule and tiers.")
    (kb / ".extract-cache").mkdir()
    (kb / ".extract-cache" / f"{checksum}.json").write_text('{"summary": "cached"}')

    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)

    copied = kb / "derived" / "pricing" / ".extract-cache" / f"{checksum}.json"
    assert copied.read_text() == '{"summary": "cached"}'
