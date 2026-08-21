"""Offline tests for the compile orchestrator (kb_ai.commands.compile).

compile_kb is one long function coordinating extract → classify → write →
index over a real KBStore on a temp dir. Every LLM seam is monkeypatched, so
these tests exercise the orchestration itself: incremental state, the extract
and classify caches, article grouping, partial-failure bookkeeping via
completed_ops, and the wiki/ path guard.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from kb_ai.commands import compile as cm
from kb_ai.storage.index import SUMMARY_MAX_CHARS
from kb_ai.core import extract as ex
from kb_ai.core import merge as mg
from kb_ai.core.extract import ExtractionResult
from kb_ai.llm import get_request_tracker
from kb_ai.prompts import NoActivePromptError
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore, _compute_checksum


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def kb(tmp_path) -> KBStore:
    """A KB store with a couple of raw files ready to compile."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "content of a")
    store.write_raw("raw/b.md", "content of b")
    return store


@pytest.fixture
def fakes(monkeypatch):
    """Replace every LLM/index seam compile_kb reaches for.

    The returned dict is both a call log and a control surface: set
    `classification` to steer what classify_article returns, or set
    `fail_extract` / `fail_write` to make a stage raise.
    """
    state: dict = {
        "extracted": [],
        "classified": [],
        "created": [],
        "merged": [],
        "indexed": [],
        "classification": {"merge_into": [], "create_new": []},
        "summarized": [],
        "fail_extract": set(),
        "fail_write": set(),
        # A2 step 4: what the merge reports for a given article (SG1-SG3), and the
        # sink each merge call was handed -- a route that forgets to pass one
        # reports nothing at all, which no assertion on the findings would catch.
        "findings": {},
        "sinks": [],
    }

    def fake_extract(content, model="m"):
        if content in state["fail_extract"]:
            raise RuntimeError(f"extract failed for {content}")
        state["extracted"].append(content)
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    def fake_classify(extraction, existing, model="m", categories=None):
        state["classified"].append(extraction.source_path)
        result = state["classification"]
        return json.loads(json.dumps(result))   # deep copy per call

    def fake_create(article_type, title, sources, model="m"):
        source_path = ", ".join(b.source_path for b in sources)
        if title in state["fail_write"]:
            raise RuntimeError(f"write failed for {title}")
        state["created"].append((article_type, title, source_path))
        return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"

    def fake_merge(article_path, article_content, sources, model="m", events=None):
        source_path = ", ".join(b.source_path for b in sources)
        if article_path in state["fail_write"]:
            raise RuntimeError(f"merge failed for {article_path}")
        state["merged"].append((article_path, source_path))
        state["sinks"].append(events)
        findings = state["findings"].get(article_path, [])
        if events is not None:
            events.extend(findings)
        # A merge that abandoned returns what it was handed (SG1), so the fake has
        # to as well -- a report that named an abandonment beside a changed article
        # would be testing something the real merge cannot produce.
        if any(f.kind == mg.EV_TRAIL_LOST for f in findings):
            return article_content
        return article_content + f"\nmerged {source_path}\n"

    def fake_summarized(chunks, meta, summarize_model, extract_model):
        joined = "".join(chunks)
        state["summarized"].append((joined, summarize_model, extract_model))
        return ExtractionResult(summary=f"summary of {joined}", topics=["t"])

    # Patched on core.extract rather than on cm: both ingestion routes dispatch
    # through run_planned_extraction, which resolves these in its own namespace.
    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(ex, "extract_knowledge_summarized", fake_summarized)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "dedup_create_new", lambda result, existing: result)
    monkeypatch.setattr(cm, "create_new_article", fake_create)
    monkeypatch.setattr(cm, "merge_into_article", fake_merge)
    monkeypatch.setattr(cm, "update_markdown_index",
                        lambda store, min_articles, summary_max_chars: state["indexed"].append("index"))
    monkeypatch.setattr(cm, "update_timeline",
                        lambda store, rels: state["indexed"].append("timeline"))
    monkeypatch.setattr(cm, "update_people_stubs",
                        lambda store, cfg: state["indexed"].append(("people", cfg)))
    return state


def creates(*paths) -> dict:
    return {
        "merge_into": [],
        "create_new": [{"path": p, "title": Path(p).stem, "type": "concept"} for p in paths],
    }


def merges(*paths) -> dict:
    return {"merge_into": [{"path": p} for p in paths], "create_new": []}


# ── nothing to do ───────────────────────────────────────────────────

def test_compile_with_no_raw_files(tmp_path, fakes):
    out = cm.compile_kb(str(tmp_path))

    assert out == {"compiled": 0, "extracted": 0, "message": "nothing to compile"}
    assert fakes["extracted"] == []


def test_compile_skips_unchanged_files(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    first = cm.compile_kb(str(kb.base_dir))
    assert first["compiled"] == 2

    # Second run: checksums match and everything completed, so nothing reruns.
    second = cm.compile_kb(str(kb.base_dir))
    assert second == {"compiled": 0, "extracted": 0, "message": "nothing to compile"}


def test_compile_does_not_preload_every_documents_content(kb, fakes, monkeypatch):
    """G2: both gates need only rel_path and checksum, which the streaming scan
    yields without holding any document's text. Preloading cost ~62 KB of
    retained memory per document, which is noise at 108 and not at 10,000."""
    def boom(self):
        raise AssertionError("compile_kb must not preload raw content")

    monkeypatch.setattr(KBStore, "list_raw_files", boom)
    fakes["classification"] = creates("wiki/concept/a.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 2
    assert out["extracted"] == 2


def test_only_the_documents_the_extraction_gate_selects_are_read(kb, fakes,
                                                                monkeypatch):
    """A fresh document's bytes are never needed: its extraction is on disk and
    the gate compares the checksum the streaming scan already computed."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.write_raw("raw/b.md", "content of b, revised")
    reads: list[str] = []
    original = KBStore.read_raw

    def counting_read_raw(self, rel_path):
        reads.append(rel_path)
        return original(self, rel_path)

    monkeypatch.setattr(KBStore, "read_raw", counting_read_raw)

    cm.compile_kb(str(kb.base_dir), extract_only=True)

    assert reads == ["raw/b.md"]


def test_compile_reprocesses_a_changed_file(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.write_raw("raw/a.md", "completely new content of a")
    fakes["extracted"].clear()

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 1
    assert fakes["extracted"] == ["completely new content of a"]


# ── happy path ──────────────────────────────────────────────────────

def test_compile_creates_articles(kb, fakes):
    fakes["classification"] = creates("wiki/concept/topic.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 2
    assert out["errors"] == []
    assert out["total_raw"] == 2
    assert (kb.base_dir / "wiki/concept/topic.md").exists()


def test_compile_reports_timing_and_cost(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert set(out["timing"]["phases"]) == {"extract", "classify", "write", "index"}
    assert "total_seconds" in out["timing"]
    assert "total_cost_usd" in out["cost"]


def test_write_phase_attributes_cost_to_the_article_that_spent_it(kb, fakes, monkeypatch):
    """Per-article cost lines must exclude what sibling workers spent.

    The write phase runs one worker per article group. Deltas of the process-wide
    tracker taken inside a worker also capture the other workers' spend in the
    same window, so the printed per-article costs summed to far more than the
    phase actually cost — inflated by roughly the worker count.
    """
    workers = 4
    for name in ("c", "d"):
        kb.write_raw(f"raw/{name}.md", f"content of {name}")
    holding = threading.Barrier(workers, timeout=30)
    recorded = threading.Barrier(workers, timeout=30)

    def classify_per_source(extraction, existing, model="m", categories=None):
        stem = Path(extraction.source_path).stem
        return {"merge_into": [],
                "create_new": [{"path": f"wiki/concept/{stem}.md",
                                "title": stem, "type": "concept"}]}

    def create_costing_three_dollars(article_type, title, sources, model="m"):
        source_path = ", ".join(b.source_path for b in sources)
        # Hold every worker inside its own measurement window, so a global delta
        # cannot help but see all four charges.
        holding.wait()
        for sink in (cm.tracker, get_request_tracker()):
            if sink is not None:
                sink.record("claude-sonnet-4-6", 1_000_000, 0)  # 3.00 USD
        recorded.wait()
        return f"---\ntitle: {title}\n---\nbody\n"

    monkeypatch.setattr(cm, "classify_article", classify_per_source)
    monkeypatch.setattr(cm, "create_new_article", create_costing_three_dollars)

    cm.compile_kb(str(kb.base_dir), workers=workers)

    log = (kb.base_dir / ".compile.log").read_text()
    per_article = [float(c) for c in re.findall(r"\[create\].*— \$([0-9.]+)", log)]
    phase_total = float(re.search(r"Phase 2b done: \$([0-9.]+)", log).group(1))

    assert per_article == [pytest.approx(3.0)] * workers
    assert sum(per_article) == pytest.approx(phase_total)


def test_compile_runs_the_index_phase(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    people = [{"canonical": "Grace Hopper", "aliases": ["Grace"]}]

    cm.compile_kb(str(kb.base_dir), people_cfg=people)

    assert "index" in fakes["indexed"]
    assert "timeline" in fakes["indexed"]
    assert ("people", people) in fakes["indexed"]


def test_compile_writes_a_log_file(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    log = (kb.base_dir / ".compile.log").read_text()
    assert "Starting compile: 2 to extract, 2 to compose" in log
    assert "Phase 1" in log
    assert "Compile done" in log


def test_compile_passes_models_through(kb, fakes, monkeypatch):
    seen = {}

    def fake_extract(content, model="m"):
        seen["extract_model"] = model
        return ExtractionResult(summary="s")

    def fake_classify(extraction, existing, model="m", categories=None):
        seen["compile_model"] = model
        seen["categories"] = categories
        return creates("wiki/concept/a.md")

    def fake_create(article_type, title, sources, model="m"):
        source_path = ", ".join(b.source_path for b in sources)
        seen["write_model"] = model
        return "article"

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "create_new_article", fake_create)

    cm.compile_kb(str(kb.base_dir), extract_model="E", compile_model="C",
                  write_model="W", categories=["cat"])

    assert seen["extract_model"] == "E"
    assert seen["compile_model"] == "C"
    assert seen["write_model"] == "W"
    assert seen["categories"] == ["cat"]


# ── caches ──────────────────────────────────────────────────────────

def test_compile_reuses_a_fresh_extraction(kb, fakes):
    """The extraction gate is independent of the compile state (spec G1).

    Dropping the state file puts both documents back into the write gate, and the
    extraction gate still sees two fresh extractions on disk.
    """
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.save_compile_state({})
    fakes["extracted"].clear()

    cm.compile_kb(str(kb.base_dir))

    assert fakes["extracted"] == [], "extraction/ should have served both files"


def test_compile_uses_the_classify_cache(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.save_compile_state({})
    fakes["classified"].clear()

    cm.compile_kb(str(kb.base_dir))

    assert fakes["classified"] == [], "classify cache should have served both files"


def test_compile_logs_that_nothing_needed_extracting(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))
    kb.save_compile_state({})

    cm.compile_kb(str(kb.base_dir))

    log = (kb.base_dir / ".compile.log").read_text()
    assert "every extraction is present and fresh" in log
    assert "hit classify cache" in log


# ── failures ────────────────────────────────────────────────────────

def test_compile_records_extract_errors_and_continues(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    fakes["fail_extract"] = {"content of a"}

    out = cm.compile_kb(str(kb.base_dir))

    assert len(out["errors"]) == 1
    assert out["errors"][0]["file"] == "raw/a.md"
    # The healthy file still compiled.
    assert out["compiled"] == 1


def test_compile_aborts_when_every_extraction_fails(kb, fakes):
    fakes["fail_extract"] = {"content of a", "content of b"}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 0
    assert len(out["errors"]) == 2
    assert "timing" not in out, "aborted compile returns the short-form result"
    log = (kb.base_dir / ".compile.log").read_text()
    assert "No usable extraction for any document to compose" in log


def test_compile_records_classify_errors(kb, fakes, monkeypatch):
    def boom(extraction, existing, model="m", categories=None):
        raise RuntimeError("classify down")

    monkeypatch.setattr(cm, "classify_article", boom)

    out = cm.compile_kb(str(kb.base_dir))

    assert len(out["errors"]) == 2
    assert all("classify down" in e["error"] for e in out["errors"])


def test_compile_records_write_errors_with_article(kb, fakes):
    fakes["classification"] = creates("wiki/concept/topic.md")
    fakes["fail_write"] = {"topic"}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["errors"]
    assert all(e["article"] == "wiki/concept/topic.md" for e in out["errors"])
    assert out["compiled"] == 0


# ── path guard ──────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_path", [
    "notwiki/a.md",
    "../escape.md",
    "/absolute/a.md",
    "raw/a.md",
])
def test_compile_skips_paths_outside_wiki(kb, fakes, bad_path):
    """The classifier is LLM output, so a path outside wiki/ must be refused
    rather than written anywhere on disk."""
    fakes["classification"] = {
        "merge_into": [],
        "create_new": [{"path": bad_path, "title": "T", "type": "concept"}],
    }

    out = cm.compile_kb(str(kb.base_dir))

    assert fakes["created"] == []
    log = (kb.base_dir / ".compile.log").read_text()
    assert "bad path (not under wiki/)" in log
    # A file whose only op was refused still counts as processed, not errored.
    assert out["errors"] == []


def test_compile_skips_bad_merge_paths(kb, fakes):
    fakes["classification"] = merges("notwiki/a.md")

    cm.compile_kb(str(kb.base_dir))

    assert fakes["merged"] == []
    assert "bad path (not under wiki/)" in (kb.base_dir / ".compile.log").read_text()


# ── merge routing ───────────────────────────────────────────────────

def test_compile_merge_into_missing_article_creates_it(kb, fakes):
    """A merge target that does not exist yet is created from the combined
    extractions rather than failing."""
    fakes["classification"] = merges("wiki/concept/target.md")

    cm.compile_kb(str(kb.base_dir))

    assert fakes["created"], "expected a merge→create"
    assert fakes["merged"] == []
    assert (kb.base_dir / "wiki/concept/target.md").exists()
    log = (kb.base_dir / ".compile.log").read_text()
    assert "[merge→create]" in log


def test_compile_single_merge_into_existing_article(kb, fakes):
    kb.write_article("wiki/concept/target.md", "---\ntitle: T\n---\nexisting\n")
    fakes["classification"] = merges("wiki/concept/target.md")

    cm.compile_kb(str(kb.base_dir))

    # Both raw files target the same article, so this is the batch path.
    assert fakes["merged"]
    log = (kb.base_dir / ".compile.log").read_text()
    assert "[merge-batch]" in log


def test_compile_batches_merges_into_one_call(kb, fakes):
    kb.write_article("wiki/concept/target.md", "existing")
    fakes["classification"] = merges("wiki/concept/target.md")

    cm.compile_kb(str(kb.base_dir))

    # One merge call covering both sources, not one per source.
    assert len(fakes["merged"]) == 1
    article_path, source = fakes["merged"][0]
    assert article_path == "wiki/concept/target.md"
    assert "raw/a.md" in source and "raw/b.md" in source


def test_compile_create_over_existing_file_merges_instead(kb, fakes):
    """A create whose target already exists must merge, not clobber."""
    kb.write_article("wiki/concept/topic.md", "---\ntitle: T\n---\nprior content\n")
    fakes["classification"] = creates("wiki/concept/topic.md")

    cm.compile_kb(str(kb.base_dir))

    assert fakes["merged"], "expected a merge rather than a fresh create"
    assert "prior content" in (kb.base_dir / "wiki/concept/topic.md").read_text()


def test_compile_derives_type_and_title_for_merge_create(kb, fakes):
    fakes["classification"] = merges("wiki/project/my-cool-thing.md")

    cm.compile_kb(str(kb.base_dir))

    article_type, title, _source = fakes["created"][0]
    assert article_type == "project"
    assert title == "My Cool Thing"


# ── the merge findings report (A2 step 4) ───────────────────────────
#
# SG1's abandonments, SG2's shrink deltas and SG3's refusals reach the compile
# report through a sink the write phase passes into every merge op. SG4 is what
# makes the shape safe to be this rich: the findings are built after the last
# write op and never re-enter a prompt, so nothing here can change what a later
# merge is told.
#
# The reports were stderr-only until this step, which meant a refused supersede
# was invisible to anything counting -- and FA5 needs the count to tell a clean
# Staleness column from a writer whose actions the code kept throwing away.

def _finding(kind: str, article: str, reason: str = "reason", detail: str = "") -> mg.MergeEvent:
    return mg.MergeEvent(kind=kind, article=article, reason=reason, detail=detail)


def test_compile_reports_a_refused_supersede(kb, fakes):
    """SG3 through the compile report: the article, the reason, the anchor."""
    kb.write_article("wiki/concept/target.md", "existing")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["findings"] = {"wiki/concept/target.md": [
        _finding(mg.EV_SUPERSEDE_REFUSED, "wiki/concept/target.md",
                 "anchor not found", "Progress: 0%")]}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["merge_findings"] == [{"kind": "supersede-refused",
                                     "article": "wiki/concept/target.md",
                                     "reason": "anchor not found",
                                     "detail": "Progress: 0%"}]
    log = (kb.base_dir / ".compile.log").read_text()
    assert "[supersede-refused] wiki/concept/target.md: anchor not found: Progress: 0%" in log


def test_compile_reports_a_shrunken_article(kb, fakes):
    """SG2: named with its delta, beside the other findings rather than in a report
    of its own -- one section is what makes a count of findings readable."""
    kb.write_article("wiki/concept/target.md", "existing")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["findings"] = {"wiki/concept/target.md": [
        _finding(mg.EV_ARTICLE_SHRANK, "wiki/concept/target.md",
                 "shrank 120 bytes (1000 → 880)")]}

    out = cm.compile_kb(str(kb.base_dir))

    assert [f["kind"] for f in out["merge_findings"]] == ["shrank"]
    assert "shrank 120 bytes" in (kb.base_dir / ".compile.log").read_text()


def test_compile_names_an_abandoned_merge_as_its_own_status(kb, fakes):
    """The status D9's price needs: `merged` would say the sources landed in the
    article, and SG1 abandoned the write precisely so they would not."""
    kb.write_article("wiki/concept/target.md", "existing\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["findings"] = {"wiki/concept/target.md": [
        _finding(mg.EV_TRAIL_LOST, "wiki/concept/target.md",
                 "pre-existing trail missing from the rewrite", "[Superseded ...]")]}

    out = cm.compile_kb(str(kb.base_dir))
    log = (kb.base_dir / ".compile.log").read_text()

    assert "[merge-abandoned] wiki/concept/target.md" in log
    assert "[merge-batch]" not in log
    assert [f["kind"] for f in out["merge_findings"]] == ["abandoned"]
    # The article kept every byte it had, which is the guarantee itself.
    assert (kb.base_dir / "wiki/concept/target.md").read_text() == "existing\n"


def test_an_abandoned_merge_still_marks_its_sources_compiled(kb, fakes):
    """The accounting D9 chose: the merge is lost, not retried. A deterministic
    trail failure would otherwise re-spend on every compile forever, and the
    report is what tells an operator to act instead."""
    kb.write_article("wiki/concept/target.md", "existing\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["findings"] = {"wiki/concept/target.md": [
        _finding(mg.EV_TRAIL_LOST, "wiki/concept/target.md", "reason", "block")]}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 2
    state = kb.load_compile_state()
    assert "compiled_at" in state["raw/a.md"]


def test_a_clean_compile_reports_no_findings(kb, fakes):
    """The column has to be readable as clean rather than as absent (FA5), so the
    key is always there and the section is not."""
    kb.write_article("wiki/concept/target.md", "existing")
    fakes["classification"] = merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["merge_findings"] == []
    assert "Merge findings" not in (kb.base_dir / ".compile.log").read_text()


def test_the_findings_report_is_ordered_independently_of_the_workers(kb, fakes):
    """Two articles finish in whatever order the pool returns them, and a report
    that printed in completion order would diff differently run to run over an
    unchanged KB. Sorted by article, then by kind."""
    kb.write_article("wiki/concept/aaa.md", "existing")
    kb.write_article("wiki/concept/zzz.md", "existing")
    fakes["classification"] = merges("wiki/concept/zzz.md", "wiki/concept/aaa.md")
    fakes["findings"] = {
        "wiki/concept/zzz.md": [_finding(mg.EV_ARTICLE_SHRANK, "wiki/concept/zzz.md")],
        "wiki/concept/aaa.md": [_finding(mg.EV_SUPERSEDE_REFUSED, "wiki/concept/aaa.md")],
    }

    out = cm.compile_kb(str(kb.base_dir))

    assert [f["article"] for f in out["merge_findings"]] == [
        "wiki/concept/aaa.md", "wiki/concept/zzz.md"]


def test_every_merge_route_is_handed_a_sink(kb, fakes):
    """Three call sites reach merge_into_article -- a create over an existing file,
    a single merge and a batch -- and a route that forgets the sink reports nothing
    for exactly the articles it wrote. Asserted on the sinks the fake was handed,
    because a missing one is invisible in the findings."""
    kb.write_article("wiki/concept/target.md", "existing")
    fakes["classification"] = merges("wiki/concept/target.md")

    cm.compile_kb(str(kb.base_dir))

    assert fakes["sinks"], "no merge ran"
    assert all(sink is not None for sink in fakes["sinks"])


def test_a_create_over_an_existing_file_is_handed_a_sink(kb, fakes):
    """The third route, which merges rather than creating (compile.py's create
    branch) and is the one easiest to miss."""
    kb.write_article("wiki/concept/topic.md", "prior content\n")
    fakes["classification"] = creates("wiki/concept/topic.md")

    cm.compile_kb(str(kb.base_dir))

    assert fakes["sinks"] and all(sink is not None for sink in fakes["sinks"])


# ── incremental completed_ops ───────────────────────────────────────

def test_compile_records_completed_ops_on_partial_failure(kb, fakes):
    """When one of a file's two articles fails, the successful one is recorded
    so a rerun does not redo it."""
    fakes["classification"] = creates("wiki/concept/good.md", "wiki/concept/bad.md")
    fakes["fail_write"] = {"bad"}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 0
    state = kb.load_compile_state()
    assert state["raw/a.md"]["completed_ops"] == ["wiki/concept/good.md"]
    assert "compiled_at" not in state["raw/a.md"]


def test_compile_rerun_skips_completed_ops(kb, fakes):
    fakes["classification"] = creates("wiki/concept/good.md", "wiki/concept/bad.md")
    fakes["fail_write"] = {"bad"}
    cm.compile_kb(str(kb.base_dir))

    # Let the previously failing article succeed on the rerun.
    fakes["fail_write"] = set()
    fakes["created"].clear()
    fakes["merged"].clear()

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 2
    written = {title for _t, title, _s in fakes["created"]}
    assert "good" not in written, "already-completed op should not be redone"
    log = (kb.base_dir / ".compile.log").read_text()
    assert "ops skipped" in log


def test_compile_marks_files_with_no_ops_as_compiled(kb, fakes):
    """A file the classifier says needs nothing still gets marked done, or it
    would be reprocessed on every run."""
    fakes["classification"] = {"merge_into": [], "create_new": []}

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 2
    state = kb.load_compile_state()
    assert "compiled_at" in state["raw/a.md"]


# ── worker configuration ────────────────────────────────────────────

def test_compile_honours_the_workers_argument(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir), workers=1)

    assert "workers=1" in (kb.base_dir / ".compile.log").read_text()


def test_compile_reads_workers_from_env(kb, fakes, monkeypatch):
    monkeypatch.setenv("KB_WORKERS", "1")
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    assert "workers=1" in (kb.base_dir / ".compile.log").read_text()


def test_compile_caps_workers_at_file_count(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir), workers=99)

    # Two raw files, so at most two workers.
    assert "workers=2" in (kb.base_dir / ".compile.log").read_text()


# ── run_compile entrypoint ──────────────────────────────────────────

def test_run_compile_reads_stdin_and_responds(kb, fakes, capsys, monkeypatch):
    from io import StringIO
    from unittest.mock import patch

    fakes["classification"] = creates("wiki/concept/a.md")
    payload = {
        "data_dir": str(kb.base_dir),
        "extract_model": "E",
        "compile_model": "C",
        "write_model": "W",
        "topic_index_min_articles": "5",
        "people": [{"canonical": "L", "aliases": ["l"]}],
        "workers": 1,
    }

    with patch("sys.stdin", StringIO(json.dumps(payload))):
        cm.run_compile()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    resp = json.loads(lines[-1])
    assert resp["ok"] is True
    assert resp["data"]["compiled"] == 2


def test_run_compile_defaults_optional_fields(kb, fakes, capsys):
    from io import StringIO
    from unittest.mock import patch

    fakes["classification"] = creates("wiki/concept/a.md")

    with patch("sys.stdin", StringIO(json.dumps({"data_dir": str(kb.base_dir)}))):
        cm.run_compile()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert json.loads(lines[-1])["ok"] is True
    # people_cfg defaults to an empty list rather than None.
    assert ("people", []) in fakes["indexed"]


def test_run_compile_coerces_topic_index_min_articles(kb, fakes, capsys, monkeypatch):
    from io import StringIO
    from unittest.mock import patch

    seen = {}
    monkeypatch.setattr(cm, "update_markdown_index",
                        lambda store, min_articles, summary_max_chars: seen.update(
                            min_articles=min_articles, summary_max_chars=summary_max_chars))
    fakes["classification"] = creates("wiki/concept/a.md")

    payload = {"data_dir": str(kb.base_dir), "topic_index_min_articles": None}
    with patch("sys.stdin", StringIO(json.dumps(payload))):
        cm.run_compile()

    assert seen["min_articles"] == 3


def _run_compile_seeing_summary_budget(kb, fakes, monkeypatch, raw):
    """Run run_compile with the given summary_max_chars payload value."""
    from io import StringIO
    from unittest.mock import patch

    seen = {}
    monkeypatch.setattr(cm, "update_markdown_index",
                        lambda store, min_articles, summary_max_chars: seen.update(
                            summary_max_chars=summary_max_chars))
    fakes["classification"] = creates("wiki/concept/a.md")

    with patch("sys.stdin", StringIO(json.dumps(
            {"data_dir": str(kb.base_dir), "summary_max_chars": raw}))):
        cm.run_compile()
    return seen["summary_max_chars"]


def test_run_compile_forwards_the_summary_budget(kb, fakes, capsys, monkeypatch):
    assert _run_compile_seeing_summary_budget(kb, fakes, monkeypatch, "240") == 240


@pytest.mark.parametrize("raw", [None, 0])
def test_run_compile_defaults_the_summary_budget(kb, fakes, capsys, monkeypatch, raw):
    assert _run_compile_seeing_summary_budget(kb, fakes, monkeypatch, raw) == SUMMARY_MAX_CHARS


# ── the two independent gates (spec G1, G5, G6, C11, D1) ────────────

def test_compile_persists_one_extraction_file_per_document(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    assert sorted(p.name for p in kb.extraction_dir.iterdir()) == ["a.md", "b.md"]
    stored, reason = exl.load(kb, "raw/a.md")
    assert reason == ""
    assert stored.extraction.summary == "summary of content of a"
    assert stored.provenance.source == "raw/a.md"
    assert stored.provenance.extract_strategy == "chunked"


def test_a_prompt_version_change_re_extracts_and_leaves_the_wiki_alone(kb, fakes,
                                                                      monkeypatch):
    """The whole point of two gates: a prompt edit costs one extraction pass."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))
    fakes["extracted"].clear()
    fakes["created"].clear()
    fakes["merged"].clear()

    monkeypatch.setattr(exl, "extract_prompt_version", lambda: "ffffffffffff")
    out = cm.compile_kb(str(kb.base_dir))

    assert out["extracted"] == 2
    assert sorted(fakes["extracted"]) == ["content of a", "content of b"]
    assert out["compiled"] == 0
    assert fakes["created"] == [] and fakes["merged"] == []
    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.provenance.prompt_version == "ffffffffffff"


def test_an_extract_model_change_re_extracts(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir), extract_model="E")
    fakes["extracted"].clear()

    out = cm.compile_kb(str(kb.base_dir), extract_model="OTHER")

    assert out["extracted"] == 2
    log = (kb.base_dir / ".compile.log").read_text()
    assert "extract_model changed" in log


def test_extract_only_runs_extraction_and_stops(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    out = cm.compile_kb(str(kb.base_dir), extract_only=True)

    assert out["extracted"] == 2
    assert out["compiled"] == 0
    assert out["extract_only"] is True
    assert fakes["created"] == [] and fakes["merged"] == []
    assert kb.load_compile_state() == {}
    # The document catalog still gets rebuilt: it reads summaries out of
    # extraction/, so an extract-only run is exactly when it should refresh.
    assert "index" in fakes["indexed"]
    assert "timeline" not in fakes["indexed"]


def test_extract_only_then_a_normal_run_composes_without_re_extracting(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir), extract_only=True)
    fakes["extracted"].clear()

    out = cm.compile_kb(str(kb.base_dir))

    assert fakes["extracted"] == []
    assert out["compiled"] == 2


def test_the_write_phase_composes_from_the_file_on_disk(kb, fakes, monkeypatch):
    """D1: the extraction is handed over through extraction/, not in memory."""
    seen: list[str] = []

    def capture(article_type, title, sources, model="m"):
        seen.extend(block.extraction.summary for block in sources)
        return "article"

    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir), extract_only=True)

    path = kb.extraction_path("raw/a.md")
    path.write_text(path.read_text().replace("summary of content of a",
                                             "edited by hand"))
    monkeypatch.setattr(cm, "create_new_article", capture)

    cm.compile_kb(str(kb.base_dir))

    assert "edited by hand" in seen


def test_compile_state_records_the_prompt_version_the_articles_came_from(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    entry = kb.load_compile_state()["raw/a.md"]
    assert entry["prompt_version"] == exl.current_prompt_version()
    assert "compiled_at" in entry


def test_wiki_lag_reports_the_first_run_reason(kb, fakes):
    """No pre-existing state entry carries a prompt_version, so every article
    reads as lagging on the first run after this change (G5)."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    state = kb.load_compile_state()
    for entry in state.values():
        entry.pop("prompt_version")
    kb.save_compile_state(state)
    kb.write_raw("raw/c.md", "content of c")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["wiki_lag"] == {"behind_extract_prompt": 2,
                               "behind_write_prompt": 0,
                               "extract_first_run": True,
                               "write_first_run": False}
    assert "expected on the first run" in (kb.base_dir / ".compile.log").read_text()


def test_wiki_lag_reports_a_real_lag_without_the_first_run_reason(kb, fakes,
                                                                 monkeypatch):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    monkeypatch.setattr(exl, "extract_prompt_version", lambda: "ffffffffffff")
    out = cm.compile_kb(str(kb.base_dir))

    assert out["wiki_lag"] == {"behind_extract_prompt": 2,
                               "behind_write_prompt": 0,
                               "extract_first_run": False,
                               "write_first_run": False}
    log = (kb.base_dir / ".compile.log").read_text()
    assert "written from an older extraction" in log
    assert "expected on the first run" not in log


def test_wiki_lag_ignores_documents_no_longer_under_raw(kb, fakes, monkeypatch):
    """.compile-state.json is never garbage-collected, so its entries outlive
    raw/. A document that is gone cannot be behind its own extraction, and
    counting it inflates the one number an operator reads to decide whether the
    wiki needs a recompile."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    (kb.base_dir / "raw" / "b.md").unlink()
    monkeypatch.setattr(exl, "extract_prompt_version", lambda: "ffffffffffff")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["wiki_lag"] == {"behind_extract_prompt": 1,
                               "behind_write_prompt": 0,
                               "extract_first_run": False,
                               "write_first_run": False}
    assert "raw/b.md" in kb.load_compile_state(), "the orphan entry is still there"


def test_compile_state_records_both_prompt_versions(kb, fakes):
    """The write phase had no provenance of its own: an article carried the
    version of the prompt that extracted its source and nothing about the prompt
    that composed it."""
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    entry = kb.load_compile_state()["raw/a.md"]
    assert entry["prompt_version"] == exl.current_prompt_version()
    assert entry["write_prompt_version"] == mg.write_prompt_version()


def test_a_write_prompt_change_is_reported_and_composes_nothing(kb, fakes,
                                                               monkeypatch):
    """Report-only by design: both merge paths are additive, so re-composing an
    article on a prompt edit would layer new content on top of the old and pay the
    whole write phase to inflate it."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    monkeypatch.setattr(cm, "write_prompt_version", lambda: "ffffffffffff")
    kb.write_raw("raw/c.md", "content of c")
    fakes["created"].clear()
    fakes["merged"].clear()

    out = cm.compile_kb(str(kb.base_dir))

    assert out["wiki_lag"]["behind_write_prompt"] == 2
    assert out["wiki_lag"]["behind_extract_prompt"] == 0
    composed = {src for _t, _title, src in fakes["created"]}
    composed |= {src for _art, src in fakes["merged"]}
    assert composed == {"raw/c.md"}, "a and b must not be re-composed"


def test_an_unreadable_write_prompt_does_not_fail_an_extract_only_run(kb, fakes,
                                                                     monkeypatch):
    """The write prompts are not this run's inputs. Failing here would refuse work
    that never reaches them, after the extraction has already been paid for."""
    fakes["classification"] = creates("wiki/concept/a.md")

    def boom():
        raise NoActivePromptError("prompt file not found: merge-diff")

    monkeypatch.setattr(cm, "write_prompt_version", boom)

    out = cm.compile_kb(str(kb.base_dir), extract_only=True)

    assert out["extracted"] == 2
    assert out["errors"] == []
    assert out["wiki_lag"]["behind_write_prompt"] == 0


def test_a_revised_document_names_the_articles_it_was_merged_into(kb, fakes):
    """C11: merge can only add, so those articles still carry the old content."""
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.write_raw("raw/a.md", "revised content of a")
    out = cm.compile_kb(str(kb.base_dir))

    assert out["revised"] == {"raw/a.md": ["wiki/concept/a.md"]}
    log = (kb.base_dir / ".compile.log").read_text()
    assert "[revised] raw/a.md → wiki/concept/a.md" in log


def test_a_first_extraction_is_not_reported_as_revised(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["revised"] == {}


def test_a_revised_duplicate_still_names_its_article(kb, fakes):
    """RP2 against WP7: two paths holding identical bytes collapse into one block,
    and the collapsed one is still a revised document whose article a human should
    re-read. Dropping it from the report would hide the revision behind a
    deduplication that only ever concerned the payload.
    """
    kb.write_raw("raw/a.md", "shared bytes")
    kb.write_raw("raw/b.md", "shared bytes")
    fakes["classification"] = merges("wiki/concept/shared.md")
    cm.compile_kb(str(kb.base_dir))

    kb.write_raw("raw/a.md", "shared bytes, revised")
    kb.write_raw("raw/b.md", "shared bytes, revised")
    out = cm.compile_kb(str(kb.base_dir))

    assert out["revised"] == {"raw/a.md": ["wiki/concept/shared.md"],
                             "raw/b.md": ["wiki/concept/shared.md"]}


# ── the lineage report (RP3-RP5) ────────────────────────────────────

def _dated(title, doc_id, day, source="docs", body="body"):
    return (f"---\nsource: {source}\nid: \"{doc_id}\"\ndate: {day}\n"
            f"title: \"{title}\"\n---\n\n{body}\n")


@pytest.fixture
def versions(tmp_path) -> KBStore:
    """A KB holding v1 and v2 of one document as two separate documents."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/gw-v15.md", _dated("Gateway Design v1.5", "id-a", "2026-03-23"))
    store.write_raw("raw/gw-v17.md", _dated("Gateway Design v1.7", "id-b", "2026-03-30"))
    return store


def test_two_versions_in_one_article_are_reported_as_a_lineage_group(versions, fakes):
    fakes["classification"] = merges("wiki/concept/gw.md")

    out = cm.compile_kb(str(versions.base_dir))

    assert out["lineage"] == {"wiki/concept/gw.md": [{
        "title": "Gateway Design",
        "source": "docs",
        "members": ["raw/gw-v15.md", "raw/gw-v17.md"],
        "versioned": True,
    }]}
    log = (versions.base_dir / ".compile.log").read_text()
    assert "[lineage] wiki/concept/gw.md" in log
    assert "Gateway Design" in log


def test_an_earlier_version_only_named_in_the_articles_sources_is_reported(versions,
                                                                          fakes):
    """The staged fixture's shape (FX2): v1 was composed by an earlier run, so it is
    in the article's `sources:` and not in this run's ops. Reading only this run
    would leave the report silent on exactly the merge paths A1 is measured on.
    """
    versions.write_article("wiki/concept/gw.md",
                           "---\ntitle: Gateway\nsources:\n  - raw/gw-v15.md\n---\n\nbody\n")
    state = {"raw/gw-v15.md": {"checksum": _compute_checksum(
        versions.read_raw("raw/gw-v15.md")), "compiled_at": "2026-03-23T00:00:00",
        "prompt_version": exl.extract_prompt_version(),
        "write_prompt_version": mg.write_prompt_version()}}
    versions.save_compile_state(state)
    fakes["classification"] = merges("wiki/concept/gw.md")

    out = cm.compile_kb(str(versions.base_dir))

    assert out["lineage"]["wiki/concept/gw.md"][0]["members"] == [
        "raw/gw-v15.md", "raw/gw-v17.md"]


def test_the_same_document_revised_is_not_a_lineage_group(kb, fakes):
    """One `id` over two files is shape A, which the revised report already names.
    Reporting it twice would double-count the only failure the corpus adjudicated.
    """
    kb.write_raw("raw/a.md", _dated("Onboarding Plan", "id-a", "2026-04-08"))
    kb.write_raw("raw/b.md", _dated("Onboarding Plan", "id-a", "2026-04-17"))
    fakes["classification"] = merges("wiki/concept/onboarding.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["lineage"] == {}


def test_a_cross_source_collision_is_not_reported(kb, fakes):
    kb.write_raw("raw/a.md", _dated("Card MoneySend", "id-a", "2026-04-13",
                                    source="docs"))
    kb.write_raw("raw/b.md", _dated("Card MoneySend", "id-b", "2026-04-25",
                                    source="meetings"))
    fakes["classification"] = merges("wiki/concept/card.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["lineage"] == {}


def test_a_recurring_one_to_one_titled_with_a_persons_name_is_not_reported(kb, fakes):
    kb.write_article("wiki/person/cara.md", "---\ntitle: Cara\ntype: person\n---\n\nbio\n")
    kb.write_raw("raw/a.md", _dated("Cara", "id-a", "2026-01-01", source="meetings"))
    kb.write_raw("raw/b.md", _dated("Cara", "id-b", "2026-04-21", source="meetings"))
    fakes["classification"] = merges("wiki/decision/one-to-ones.md")

    out = cm.compile_kb(str(kb.base_dir))

    assert out["lineage"] == {}


def test_an_allowlisted_person_is_excluded_before_their_article_exists(kb, fakes):
    """The person articles are stubs a later phase generates, so on the run that
    first ingests a one-to-one there is nothing on disk to match against.
    """
    kb.write_raw("raw/a.md", _dated("Cara", "id-a", "2026-01-01", source="meetings"))
    kb.write_raw("raw/b.md", _dated("Cara", "id-b", "2026-04-21", source="meetings"))
    fakes["classification"] = merges("wiki/decision/one-to-ones.md")

    out = cm.compile_kb(str(kb.base_dir),
                        people_cfg=[{"canonical": "Cara", "aliases": ["cara.zhang"]}])

    assert out["lineage"] == {}


def test_marked_groups_lead_the_report_and_both_counts_are_stated(tmp_path, fakes):
    """A version marker is the operator's triage key: on the reference corpus 40 of
    44 reported groups are recurring series and 4 are real version chains, so the
    marked ones are named first and the summary line states how many of each.
    """
    store = KBStore(str(tmp_path))
    store.write_raw("raw/daily-1.md", _dated("AI Daily", "id-1", "2026-05-01",
                                            source="meetings"))
    store.write_raw("raw/daily-2.md", _dated("AI Daily", "id-2", "2026-05-02",
                                            source="meetings"))
    store.write_raw("raw/gw-v15.md", _dated("Gateway Design v1.5", "id-a", "2026-03-23"))
    store.write_raw("raw/gw-v17.md", _dated("Gateway Design v1.7", "id-b", "2026-03-30"))
    fakes["classification"] = merges("wiki/concept/all.md")

    out = cm.compile_kb(str(store.base_dir))

    groups = out["lineage"]["wiki/concept/all.md"]
    assert [g["title"] for g in groups] == ["Gateway Design", "AI Daily"]
    log = (store.base_dir / ".compile.log").read_text()
    assert "2 lineage group(s)" in log
    assert "1 with a version marker" in log


def test_an_article_whose_write_failed_reports_no_lineage(versions, fakes):
    fakes["classification"] = merges("wiki/concept/gw.md")
    fakes["fail_write"] = {"Gw"}          # the merge→create path titles from the stem

    out = cm.compile_kb(str(versions.base_dir))

    assert out["lineage"] == {}


def test_nothing_from_the_lineage_report_reaches_the_writer(versions, fakes,
                                                           monkeypatch):
    """RP5. The report is a title heuristic, and a heuristic that steers what gets
    written is what D2's gate on build path B refuses. So the writer's arguments are
    the source blocks and nothing else -- there is no argument a group could ride in
    on, and the report is built after the last write op.
    """
    seen: list = []

    def capture_merge(article_path, article_content, sources, model="m"):
        seen.append((article_path, article_content, sources, model))
        return article_content + "merged\n"

    def capture_create(article_type, title, sources, model="m"):
        seen.append((article_type, title, sources, model))
        return f"---\ntitle: {title}\n---\nbody\n"

    monkeypatch.setattr(cm, "merge_into_article", capture_merge)
    monkeypatch.setattr(cm, "create_new_article", capture_create)
    fakes["classification"] = merges("wiki/concept/gw.md")

    out = cm.compile_kb(str(versions.base_dir))

    assert out["lineage"]                     # the report fired ...
    assert seen                               # ... and the writer ran
    for call in seen:
        for arg in call:
            if isinstance(arg, list):
                # The blocks are the only thing the writer is handed, and a block
                # carries a document -- never a judgement about one.
                for block in arg:
                    assert set(vars(block)) == {"source_path", "extraction", "date"}
            else:
                assert "lineage" not in str(arg)
                assert "Gateway Design" not in str(arg)


def test_nothing_from_the_merge_findings_reaches_the_writer(kb, fakes, monkeypatch):
    """SG4, asserted the way RP5 is above. A2's reports carry more than RP3's did --
    a refused action, a dropped trail, a byte delta -- and a report that steered the
    next write would make the writer's input depend on its own failures. Two halves:
    the entry points take source blocks and nothing else, and the findings are built
    after the last write op, so there is no call left for one to reach.
    """
    kb.write_article("wiki/concept/target.md", "existing\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["findings"] = {"wiki/concept/target.md": [
        _finding(mg.EV_SUPERSEDE_REFUSED, "wiki/concept/target.md",
                 "anchor not found", "SENTINEL-ANCHOR")]}
    seen: list = []

    # The fixture's fake, wrapped rather than replaced: it is what emits the
    # finding, so a capture that stood in for it would assert over a clean run.
    real_merge = cm.merge_into_article

    def capture_merge(article_path, article_content, sources, model="m", events=None):
        seen.append((article_path, article_content, sources, model))
        return real_merge(article_path, article_content, sources, model=model, events=events)

    monkeypatch.setattr(cm, "merge_into_article", capture_merge)

    out = cm.compile_kb(str(kb.base_dir))

    assert out["merge_findings"], "the report has to have fired for this to prove anything"
    assert seen, "the writer has to have run"
    for call in seen:
        for arg in call:
            if isinstance(arg, list):
                for block in arg:
                    assert set(vars(block)) == {"source_path", "extraction", "date"}
            else:
                # The anchor is the finding's own text, so a payload carrying it is
                # a report that came back round.
                assert "SENTINEL-ANCHOR" not in str(arg)
                assert "supersede-refused" not in str(arg)


def test_the_revised_report_says_an_article_may_still_carry_the_old_version(kb, fakes):
    """PV6. RP2's guarantee is unchanged -- a revised document still names the
    articles it was merged into -- and the sentence around it is not: A2's merge
    paths can retract a claim, so the report can no longer assert what the article
    holds. It says "may", and it names the trail as what to look for."""
    kb.write_article("wiki/concept/target.md", "existing\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    cm.compile_kb(str(kb.base_dir))
    # A second compile over re-extracted documents is what marks them revised.
    kb.write_raw("raw/a.md", "content of a, edited")
    kb.write_raw("raw/b.md", "content of b, edited")

    out = cm.compile_kb(str(kb.base_dir))
    log = (kb.base_dir / ".compile.log").read_text()

    assert out["revised"], "the revised report has to have fired"
    assert "may still carry" in log
    assert "[Superseded" in log


def test_unreadable_prompts_stop_the_run_without_extracting(kb, fakes, monkeypatch,
                                                            tmp_path):
    def boom():
        raise NoActivePromptError("prompt file not found: extract.md")

    monkeypatch.setattr(exl, "extract_prompt_version", boom)

    out = cm.compile_kb(str(kb.base_dir))

    assert out["compiled"] == 0
    assert "prompt_version unavailable" in out["errors"][0]["error"]
    assert fakes["extracted"] == []


def test_extraction_inherits_the_raw_scan_skip_rules(kb, fakes):
    """A5: nothing under _skipped/ and no dotfile gets an extraction.

    Needs no code of its own -- extraction paths are derived from the raw scan, so
    a document the scan skips is never handed to the layer. Asserted rather than
    assumed, because the alternative (folding over extraction/) would not inherit
    it.
    """
    kb.write_raw("raw/_skipped/costly.md", "content of costly")
    (kb.raw_dir / ".hidden.md").write_text("content of hidden")
    fakes["classification"] = creates("wiki/concept/a.md")

    cm.compile_kb(str(kb.base_dir))

    assert sorted(p.name for p in kb.extraction_dir.rglob("*.md")) == ["a.md", "b.md"]
    assert not (kb.extraction_dir / "_skipped").exists()


# ── the configured extraction strategy (both routes honour one value) ──
#
# The gate used to assert "chunked" whatever the KB was configured for, so an
# extraction the daemon recorded as summarize read as stale on every CLI compile:
# re-extracted once per document and silently downgraded to a different quality
# contract, since summarize never shows the structured pass the original words.

def test_the_gate_compares_against_the_configured_strategy(kb, fakes):
    """A summarize extraction stays fresh under a summarize configuration."""
    exl.persist(kb, "raw/a.md", ExtractionResult(summary="from the UI"),
                source_checksum=_compute_checksum(kb.read_raw("raw/a.md")),
                extract_model="m", extract_strategy=exl.STRATEGY_SUMMARIZE,
                summarize_model="sm")

    out = cm.compile_kb(str(kb.base_dir), extract_model="m",
                        extract_strategy=exl.STRATEGY_SUMMARIZE,
                        summarize_model="sm", extract_only=True)

    assert out["extracted"] == 1, "only raw/b.md, which has no extraction yet"
    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.extraction.summary == "from the UI", "not re-extracted"


def test_a_chunked_configuration_still_finds_a_summarize_extraction_stale(kb, fakes):
    """Not a regression of the fix: under chunked, a summarize extraction really
    is the wrong contract, and re-extracting it is the correct answer."""
    exl.persist(kb, "raw/a.md", ExtractionResult(summary="from the UI"),
                source_checksum=_compute_checksum(kb.read_raw("raw/a.md")),
                extract_model="m", extract_strategy=exl.STRATEGY_SUMMARIZE,
                summarize_model="sm")

    cm.compile_kb(str(kb.base_dir), extract_model="m", extract_only=True)

    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.provenance.extract_strategy == exl.STRATEGY_CHUNKED


def test_a_configured_summarize_is_what_runs_and_what_gets_recorded(kb, fakes):
    cm.compile_kb(str(kb.base_dir), extract_model="m",
                  extract_strategy=exl.STRATEGY_SUMMARIZE,
                  summarize_model="sm", extract_only=True)

    assert fakes["extracted"] == [], "the chunked path must not have run"
    assert [sm for _c, sm, _em in fakes["summarized"]] == ["sm", "sm"]
    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.provenance.extract_strategy == exl.STRATEGY_SUMMARIZE
    assert stored.provenance.summarize_model == "sm"


def test_a_second_run_under_the_same_configured_strategy_extracts_nothing(kb, fakes):
    """The property the divergence broke: an ingested document stays fresh."""
    cm.compile_kb(str(kb.base_dir), extract_model="m",
                  extract_strategy=exl.STRATEGY_SUMMARIZE,
                  summarize_model="sm", extract_only=True)

    out = cm.compile_kb(str(kb.base_dir), extract_model="m",
                        extract_strategy=exl.STRATEGY_SUMMARIZE,
                        summarize_model="sm", extract_only=True)

    assert out == {"compiled": 0, "extracted": 0, "message": "nothing to compile"}


def test_auto_records_the_strategy_that_ran_not_auto(kb, fakes):
    """These two documents are one chunk each, so auto resolves to chunked."""
    cm.compile_kb(str(kb.base_dir), extract_model="m",
                  extract_strategy=ex.STRATEGY_AUTO, summarize_model="sm",
                  extract_only=True)

    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.provenance.extract_strategy == exl.STRATEGY_CHUNKED


def test_an_unknown_configured_strategy_is_refused_before_any_llm_call(kb, fakes):
    with pytest.raises(ValueError, match="unknown extract strategy"):
        cm.compile_kb(str(kb.base_dir), extract_strategy="Chunked")

    assert fakes["extracted"] == []
    assert fakes["summarized"] == []


def test_under_auto_the_gate_resolves_each_document_before_comparing(kb, fakes):
    """auto is the one configuration the gate cannot answer from a constant: the
    router decides on chunk count, so a document already extracted as chunked is
    only fresh if auto would still choose chunked for it."""
    exl.persist(kb, "raw/a.md", ExtractionResult(summary="already chunked"),
                source_checksum=_compute_checksum(kb.read_raw("raw/a.md")),
                extract_model="m", extract_strategy=exl.STRATEGY_CHUNKED)
    kb.write_raw("raw/b.md", "x\n" * 40_000)   # splits into 3+ chunks -> summarize
    exl.persist(kb, "raw/b.md", ExtractionResult(summary="wrongly chunked"),
                source_checksum=_compute_checksum(kb.read_raw("raw/b.md")),
                extract_model="m", extract_strategy=exl.STRATEGY_CHUNKED)

    out = cm.compile_kb(str(kb.base_dir), extract_model="m",
                        extract_strategy=ex.STRATEGY_AUTO, summarize_model="sm",
                        extract_only=True)

    assert out["extracted"] == 1, "raw/a.md stays chunked and fresh"
    stored, _ = exl.load(kb, "raw/b.md")
    assert stored.provenance.extract_strategy == exl.STRATEGY_SUMMARIZE


def test_the_recorded_checksum_names_the_text_that_was_actually_extracted(
        kb, fakes, monkeypatch):
    """The scan and the extract are two reads now, so a document rewritten between
    them would otherwise record the scan's checksum over the later text. Harmless
    while the content keeps moving -- but if it is reverted to what the scan saw,
    the gate calls it fresh and the KB serves an extraction of text that is no
    longer there, which the single-read version could not do."""
    original = KBStore.read_raw

    def rewrite_then_read(self, rel_path):
        if rel_path == "raw/a.md":
            self.write_raw(rel_path, "content of a, rewritten mid-run")
        return original(self, rel_path)

    monkeypatch.setattr(KBStore, "read_raw", rewrite_then_read)

    cm.compile_kb(str(kb.base_dir), extract_model="m", extract_only=True)

    stored, _ = exl.load(kb, "raw/a.md")
    assert stored.provenance.source_checksum == _compute_checksum(
        "content of a, rewritten mid-run")


def test_summarize_without_a_summarize_model_is_refused_before_any_llm_call(kb, fakes):
    """The summarize path drives a second model per chunk. Reaching the API with an
    empty model name fails after the run has started; this file's convention is to
    refuse before spending."""
    with pytest.raises(ValueError, match="summarize_model"):
        cm.compile_kb(str(kb.base_dir), extract_strategy=exl.STRATEGY_SUMMARIZE)

    assert fakes["extracted"] == [] and fakes["summarized"] == []


def test_auto_also_requires_a_summarize_model(kb, fakes):
    """auto can resolve to summarize per document, so the requirement is the same."""
    with pytest.raises(ValueError, match="summarize_model"):
        cm.compile_kb(str(kb.base_dir), extract_strategy=ex.STRATEGY_AUTO)
