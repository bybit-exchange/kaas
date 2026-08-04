"""A derived KB must be invisible to its source KB's compile and index (C6, D4)."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import derive_kb
from kb_ai.derive._types import MODE_RECALL, SelectionResult
from kb_ai.storage.index import update_markdown_index
from kb_ai.storage.store import KBStore


def _source_kb(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "wiki").mkdir(parents=True)
    (kb / "index").mkdir(parents=True)
    (kb / "raw" / "notes.md").write_text("Fee schedule.")
    (kb / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\ntags: [fees]\nsources:\n  - raw/notes.md\n---\n\n# Pricing\n\nProse.\n")
    update_markdown_index(KBStore(str(kb)))
    return kb


def _select(catalog, topic, mode):
    if mode == MODE_RECALL:
        return SelectionResult(paths=[a.path for a in catalog], batches=1,
                               dropped_invented=0, skipped=[])
    return SelectionResult(paths=["wiki/derived-only.md"], batches=1,
                           dropped_invented=0, skipped=[])


def _fake_compile(derived_dir: str, **kwargs) -> dict:
    base = Path(derived_dir)
    (base / "wiki").mkdir(parents=True, exist_ok=True)
    (base / "index").mkdir(parents=True, exist_ok=True)
    (base / "wiki" / "derived-only.md").write_text(
        "---\ntitle: Derived Only\ntags: [fees]\n---\n\n# Derived Only\n\nProse.\n")
    (base / "wiki" / "moved-aside.md").write_text(
        "---\ntitle: Moved Aside\ntags: [misc]\n---\n\n# Moved Aside\n\nProse.\n")
    update_markdown_index(KBStore(str(base)))
    return {"compiled": 2}


def test_source_compile_and_index_do_not_see_the_derived_kb(tmp_path: Path):
    kb = _source_kb(tmp_path)
    report = derive_kb(str(kb), "pricing", model="m", slug="pricing",
                       select=_select, compile_fn=_fake_compile)
    assert report.offtopic_articles == ["wiki/moved-aside.md"]

    store = KBStore(str(kb))

    # The source's raw scan must not pick up the copied documents.
    rel_paths = [rf.rel_path for rf in store.list_raw_files()]
    assert rel_paths == ["raw/notes.md"]

    # The source's index rebuild must not list derived or _offtopic articles.
    update_markdown_index(store)
    catalog = (kb / "index" / "master-index.md").read_text()
    assert "wiki/pricing.md" in catalog
    assert "derived" not in catalog
    assert "derived-only" not in catalog
    assert "moved-aside" not in catalog

    # The source catalog parses back to exactly its own article.
    assert [a.path for a in store.existing_articles()] == ["wiki/pricing.md"]


def test_offtopic_is_outside_the_derived_kbs_own_index(tmp_path: Path):
    kb = _source_kb(tmp_path)
    derive_kb(str(kb), "pricing", model="m", slug="pricing",
              select=_select, compile_fn=_fake_compile)

    derived = kb / "derived" / "pricing"
    derived_catalog = (derived / "index" / "master-index.md").read_text()
    assert "wiki/derived-only.md" in derived_catalog
    assert "moved-aside" not in derived_catalog
    assert (derived / "_offtopic" / "moved-aside.md").exists()
