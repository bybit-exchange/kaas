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

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.commands import compile as cm
from kb_ai.commands.pipeline import _phase_write as pw
from kb_ai.core import extract as ex
from kb_ai.core import merge as mg
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


# ── VA8: the supersede action, on both routes ───────────────────────
#
# VF6 above compares what reaches the writer. A2 gives the writer an action that
# edits the article in place, so the thing worth comparing is now the article the
# two routes write: the same claim, the same anchor and the same payload have to
# produce the same bytes whichever phase ran. Both routes go through one
# merge_into_article, so what could still diverge is what they hand it -- the
# blocks (VF6) and the article they read -- and a trail landing twice, or on a
# different day, is what that divergence would look like.

CLAIM = "Progress: 0%"
# Past _LARGE_ARTICLE_THRESHOLD, so both routes take the diff path -- the one that
# carries `supersede` -- rather than one of them rewriting the whole article.
SUPERSEDE_ARTICLE = (f"---\ntitle: Target\n---\n\n## Status\n{CLAIM}\n\n"
                     + "padding prose for the large-article threshold. " * 800)

PATCHES = {"patches": [{"action": "supersede", "anchor": CLAIM,
                        "replacement": "Progress: 50%",
                        # The newest dated block in this payload (2021-06-01).
                        "by": "raw/a.md",
                        "was": "the earlier figure was 0%"}]}


def _superseding_kb(root) -> KBStore:
    store = _kb(root)
    store.write_article(ARTICLE, SUPERSEDE_ARTICLE)
    return store


def _cli_supersede(root, monkeypatch) -> str:
    """compile_kb merging both documents into the existing article."""
    store = _superseding_kb(root)

    monkeypatch.setattr(ex, "extract_knowledge_chunked",
                        lambda content, model="m": _extraction_of(content))
    monkeypatch.setattr(cm, "classify_article",
                        lambda extraction, existing, model="m", categories=None:
                        json.loads(json.dumps({"merge_into": [{"path": ARTICLE}],
                                               "create_new": []})))
    monkeypatch.setattr(cm, "dedup_create_new", lambda result, existing: result)
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: PATCHES)
    monkeypatch.setattr(cm, "update_markdown_index",
                        lambda store, min_articles, summary_max_chars: None)
    monkeypatch.setattr(cm, "update_timeline", lambda store, rels: None)
    monkeypatch.setattr(cm, "update_people_stubs", lambda store, cfg: None)

    out = cm.compile_kb(str(store.base_dir))

    assert out["errors"] == []
    return (store.base_dir / ARTICLE).read_text()


def _worker_supersede(root, monkeypatch) -> str:
    """run_write_phase over the same documents and the same article."""
    store = _superseding_kb(root)
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: PATCHES)

    items = []
    for rel, content in DOCS.items():
        extraction = _extraction_of(content)
        extraction.source_path = rel
        items.append((_compute_checksum(content), rel, extraction,
                      ClassificationResult(create_new=[],
                                           merge_into=[MergeTarget(path=ARTICLE)])))

    item_results, written = pw.run_write_phase(items, store, workers=2)

    assert written == 1
    assert all(r["status"] == "ok" for r in item_results), item_results
    return (store.base_dir / ARTICLE).read_text()


def test_both_routes_write_the_same_article_for_one_supersede(tmp_path, monkeypatch):
    """VA8. Compared as bytes: the anchor replaced once, one trail, the same date."""
    cli = _cli_supersede(tmp_path / "cli-sup", monkeypatch)
    worker = _worker_supersede(tmp_path / "worker-sup", monkeypatch)

    assert cli == worker
    assert "Progress: 50%" in cli and CLAIM not in cli
    assert cli.count("[Superseded 2021-06-01 by raw/a.md: the earlier figure was 0%]") == 1
