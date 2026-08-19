"""Both write routes build the same per-source blocks (supersession spec VF6).

The CLI's `compile_kb` and the daemon's `run_write_phase` are two independent
write phases over one KB layout, and the extraction layer already paid for that
duplication once: the CLI's freshness gate asserted a strategy the daemon never
recorded, so every UI-ingested document was silently re-extracted and downgraded
by the next CLI compile. T14 pinned the two routes against each other in one
process to close it; this is the same test one layer over, on the payload the
writers receive.

Mirrors T14's shape deliberately: both routes in one process, over byte-identical
KBs, comparing what reached the writer rather than what each route logged.
"""
from __future__ import annotations

from datetime import date

import json

from kb_ai._types import ClassificationResult, CreateTarget
from kb_ai.commands import compile as cm
from kb_ai.commands.pipeline import _phase_write as pw
from kb_ai.core import extract as ex
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import KBStore, _compute_checksum

ARTICLE = "wiki/concept/target.md"

# Dated against path order on purpose: raw/a.md is the newer document, so any
# route that renders in scan order rather than in date order fails here.
DOCS = {
    "raw/a.md": "---\ntitle: A\ndate: 2021-06-01\n---\nnewer body\n",
    "raw/b.md": "---\ntitle: B\ndate: 2020-01-01\n---\nolder body\n",
}


def _kb(root) -> KBStore:
    store = KBStore(str(root))
    for rel, content in DOCS.items():
        store.write_raw(rel, content)
    return store


def _extraction_of(content: str) -> ExtractionResult:
    """What the CLI route's faked extractor produces for a raw document."""
    return ExtractionResult(summary=f"summary of {content}", topics=["t"])


def _cli_blocks(root, monkeypatch) -> list:
    """Drive compile_kb to the merge->create path and capture its blocks."""
    store = _kb(root)
    captured: list = []

    def fake_extract(content, model="m"):
        return _extraction_of(content)

    def fake_classify(extraction, existing, model="m", categories=None):
        return json.loads(json.dumps(
            {"merge_into": [{"path": ARTICLE}], "create_new": []}))

    def recording_create(article_type, title, sources, model="m"):
        captured.extend(sources)
        return f"---\ntitle: {title}\n---\nbody\n"

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "dedup_create_new", lambda result, existing: result)
    monkeypatch.setattr(cm, "create_new_article", recording_create)
    monkeypatch.setattr(cm, "update_markdown_index",
                        lambda store, min_articles, summary_max_chars: None)
    monkeypatch.setattr(cm, "update_timeline", lambda store, rels: None)
    monkeypatch.setattr(cm, "update_people_stubs", lambda store, cfg: None)

    out = cm.compile_kb(str(store.base_dir))

    assert out["errors"] == []
    return captured


def _worker_blocks(root, monkeypatch) -> list:
    """Drive run_write_phase over the same documents and capture its blocks."""
    store = _kb(root)
    captured: list = []

    def recording_create(article_type, title, sources, model="m"):
        captured.extend(sources)
        return f"---\ntitle: {title}\n---\nbody\n"

    monkeypatch.setattr(pw, "create_new_article", recording_create)

    items = []
    for rel, content in DOCS.items():
        extraction = _extraction_of(content)
        # Set by _phase_classify on the real route, and by compile_kb on the
        # other one, so the two payloads are only comparable with it set here.
        extraction.source_path = rel
        items.append((
            # The same checksum the CLI route carries, so WP7's duplicate
            # collapsing is measured on equal terms rather than on a test-local
            # stand-in that could never collide.
            _compute_checksum(content),
            rel, extraction,
            ClassificationResult(
                create_new=[CreateTarget(path=ARTICLE, type="concept", title="Target")],
                merge_into=[]),
        ))

    item_results, written = pw.run_write_phase(items, store, workers=2)

    assert written == 1
    assert all(r["status"] == "ok" for r in item_results), item_results
    return captured


def test_both_write_routes_build_identical_source_blocks(tmp_path, monkeypatch):
    """Same documents, same blocks: source, date and extraction, in one order.

    Compared whole rather than field by field -- a route that carried the dates
    but flattened the extractions, or ordered them differently, is exactly the
    kind of divergence this exists to catch."""
    cli = _cli_blocks(tmp_path / "cli", monkeypatch)
    worker = _worker_blocks(tmp_path / "worker", monkeypatch)

    assert cli == worker
    assert [b.source_path for b in cli] == ["raw/b.md", "raw/a.md"]
    assert [b.date for b in cli] == [date(2020, 1, 1), date(2021, 6, 1)]


def test_both_routes_read_the_date_from_the_documents_own_frontmatter(tmp_path, monkeypatch):
    """Not from the ingest clock and not from mtime: the two KBs are written in
    this test's own wall-clock order, which is the opposite of their dates."""
    cli = _cli_blocks(tmp_path / "cli", monkeypatch)

    assert [b.date for b in cli] == [date(2020, 1, 1), date(2021, 6, 1)]
