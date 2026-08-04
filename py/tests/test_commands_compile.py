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
from kb_ai.core.extract import ExtractionResult
from kb_ai.llm import get_request_tracker
from kb_ai.storage.store import KBStore


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
        "fail_extract": set(),
        "fail_write": set(),
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

    monkeypatch.setattr(cm, "extract_knowledge_chunked", fake_extract)
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

    assert out == {"compiled": 0, "message": "nothing to compile"}
    assert fakes["extracted"] == []


def test_compile_skips_unchanged_files(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")

    first = cm.compile_kb(str(kb.base_dir))
    assert first["compiled"] == 2

    # Second run: checksums match and everything completed, so nothing reruns.
    second = cm.compile_kb(str(kb.base_dir))
    assert second == {"compiled": 0, "message": "nothing to compile"}


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

    def create_costing_three_dollars(article_type, title, extraction, source_path, model="m"):
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
    assert "Starting compile: 2 files" in log
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

    def fake_create(article_type, title, extraction, source_path, model="m"):
        seen["write_model"] = model
        return "article"

    monkeypatch.setattr(cm, "extract_knowledge_chunked", fake_extract)
    monkeypatch.setattr(cm, "classify_article", fake_classify)
    monkeypatch.setattr(cm, "create_new_article", fake_create)

    cm.compile_kb(str(kb.base_dir), extract_model="E", compile_model="C",
                  write_model="W", categories=["cat"])

    assert seen["extract_model"] == "E"
    assert seen["compile_model"] == "C"
    assert seen["write_model"] == "W"
    assert seen["categories"] == ["cat"]


# ── caches ──────────────────────────────────────────────────────────

def test_compile_uses_the_extract_cache(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    # Force a recompile without changing content: drop the state file only.
    kb.save_compile_state({})
    fakes["extracted"].clear()

    cm.compile_kb(str(kb.base_dir))

    assert fakes["extracted"] == [], "extraction cache should have served both files"


def test_compile_uses_the_classify_cache(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))

    kb.save_compile_state({})
    fakes["classified"].clear()

    cm.compile_kb(str(kb.base_dir))

    assert fakes["classified"] == [], "classify cache should have served both files"


def test_compile_logs_full_cache_hits(kb, fakes):
    fakes["classification"] = creates("wiki/concept/a.md")
    cm.compile_kb(str(kb.base_dir))
    kb.save_compile_state({})

    cm.compile_kb(str(kb.base_dir))

    log = (kb.base_dir / ".compile.log").read_text()
    assert "hit extraction cache" in log
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
    assert "All extractions failed" in log


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
