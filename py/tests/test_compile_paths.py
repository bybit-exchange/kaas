"""Offline tests for compile_kb's remaining write-phase branches.

Complements tests/test_commands_compile.py by driving the paths that need a
specific op shape to reach: a single merge into an already-existing article
(as opposed to the batch path), the three merge failure branches
(merge→create / merge / merge-batch), the completed_ops skip on a *merge* op,
and the executor's catch-all for an exception escaping _process_article.

Every LLM seam is monkeypatched; the store is a real KBStore on tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai.commands import compile as cm
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import KBStore


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def kb_one(tmp_path) -> KBStore:
    """A KB store with exactly one raw file, so merge groups have size 1."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/only.md", "content of only")
    return store


@pytest.fixture
def kb_two(tmp_path) -> KBStore:
    """A KB store with two raw files, so merges into one article batch."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "content of a")
    store.write_raw("raw/b.md", "content of b")
    return store


@pytest.fixture
def fakes(monkeypatch):
    """Replace every LLM/index seam compile_kb reaches for.

    `classification` steers classify_article's return value; `fail_write`
    holds titles (creates) or article paths (merges) that must raise.
    """
    state: dict = {
        "extracted": [],
        "created": [],
        "merged": [],
        "classification": {"merge_into": [], "create_new": []},
        "fail_write": set(),
    }

    def fake_extract(content, model="m"):
        state["extracted"].append(content)
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    def fake_classify(extraction, existing, model="m", categories=None):
        return json.loads(json.dumps(state["classification"]))   # deep copy per call

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
    monkeypatch.setattr(cm, "update_markdown_index", lambda store, min_articles, summary_max_chars: None)
    monkeypatch.setattr(cm, "update_timeline", lambda store, rels: None)
    monkeypatch.setattr(cm, "update_people_stubs", lambda store, cfg: None)
    return state


def merges(*paths) -> dict:
    return {"merge_into": [{"path": p} for p in paths], "create_new": []}


def log_of(store: KBStore) -> str:
    return (store.base_dir / ".compile.log").read_text()


# ── single merge into an existing article ───────────────────────────

def test_compile_single_merge_updates_the_existing_article(kb_one, fakes):
    """One source merging into an existing article takes the single-merge path:
    the old content is read and handed to merge_into_article, not recreated."""
    kb_one.write_article("wiki/concept/target.md", "---\ntitle: T\n---\nprior body\n")
    fakes["classification"] = merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_one.base_dir))

    assert fakes["merged"] == [("wiki/concept/target.md", "raw/only.md")]
    assert fakes["created"] == [], "an existing article must not be recreated"
    body = (kb_one.base_dir / "wiki/concept/target.md").read_text()
    assert "prior body" in body and "merged raw/only.md" in body
    assert out["compiled"] == 1
    assert out["errors"] == []
    log = log_of(kb_one)
    assert "[merge] wiki/concept/target.md ← raw/only.md" in log
    assert "[merge-batch]" not in log


def test_compile_records_single_merge_failure(kb_one, fakes):
    """A failed single merge is recorded against both file and article, and the
    file is left uncompiled so a rerun retries it."""
    kb_one.write_article("wiki/concept/target.md", "prior body\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["fail_write"] = {"wiki/concept/target.md"}

    out = cm.compile_kb(str(kb_one.base_dir))

    assert out["compiled"] == 0
    assert out["errors"] == [{"file": "raw/only.md",
                              "error": "merge failed for wiki/concept/target.md",
                              "article": "wiki/concept/target.md"}]
    assert (kb_one.base_dir / "wiki/concept/target.md").read_text() == "prior body\n"
    assert "raw/only.md" not in kb_one.load_compile_state()
    assert "[merge-error] wiki/concept/target.md ← raw/only.md" in log_of(kb_one)


# ── merge→create failure ────────────────────────────────────────────

def test_compile_records_merge_create_failure_for_every_source(kb_two, fakes):
    """When the merge target is missing and the fresh create fails, every
    source feeding that article gets an error entry."""
    # Title derived from the path stem: "target" → "Target".
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["fail_write"] = {"Target"}

    out = cm.compile_kb(str(kb_two.base_dir))

    assert out["compiled"] == 0
    assert {e["file"] for e in out["errors"]} == {"raw/a.md", "raw/b.md"}
    assert all(e["article"] == "wiki/concept/target.md" for e in out["errors"])
    assert not (kb_two.base_dir / "wiki/concept/target.md").exists()
    assert "[merge→create-error] wiki/concept/target.md ← 2 sources" in log_of(kb_two)


# ── merge-batch failure ─────────────────────────────────────────────

def test_compile_records_merge_batch_failure_for_every_source(kb_two, fakes):
    """A failed batch merge must not leave the article half-written, and must
    fan the single exception out to all contributing sources."""
    kb_two.write_article("wiki/concept/target.md", "prior body\n")
    fakes["classification"] = merges("wiki/concept/target.md")
    fakes["fail_write"] = {"wiki/concept/target.md"}

    out = cm.compile_kb(str(kb_two.base_dir))

    assert out["compiled"] == 0
    assert {e["file"] for e in out["errors"]} == {"raw/a.md", "raw/b.md"}
    assert all(e["article"] == "wiki/concept/target.md" for e in out["errors"])
    assert (kb_two.base_dir / "wiki/concept/target.md").read_text() == "prior body\n"
    assert kb_two.load_compile_state() == {}, "nothing succeeded, so no op is recorded"
    assert "[merge-batch-error] wiki/concept/target.md ← 2 sources" in log_of(kb_two)


# ── completed_ops skip on a merge op ────────────────────────────────

def test_compile_skips_merge_ops_completed_in_a_prior_run(kb_two, fakes):
    """A merge already recorded in completed_ops is not redone; the file has no
    remaining work and is finally marked compiled."""
    kb_two.save_compile_state({
        rf.rel_path: {"checksum": rf.checksum, "completed_ops": ["wiki/concept/target.md"]}
        for rf in kb_two.list_raw_files()
    })
    fakes["classification"] = merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_two.base_dir))

    assert fakes["merged"] == [] and fakes["created"] == []
    assert out["compiled"] == 2
    state = kb_two.load_compile_state()
    assert all("compiled_at" in state[rel] for rel in ("raw/a.md", "raw/b.md"))
    assert all("completed_ops" not in state[rel] for rel in ("raw/a.md", "raw/b.md"))
    assert "(2 ops skipped" in log_of(kb_two)


# ── executor catch-all ──────────────────────────────────────────────

def test_compile_logs_a_group_error_when_an_article_task_raises(kb_two, fakes, monkeypatch):
    """An exception outside _process_article's per-op try blocks must be caught
    by the executor loop so the remaining phases (state save, index) still run."""
    def boom(items):
        raise RuntimeError("combine blew up")

    monkeypatch.setattr(cm, "_combine_extractions", boom)
    kb_two.write_article("wiki/concept/target.md", "prior body\n")
    fakes["classification"] = merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_two.base_dir))

    assert out["compiled"] == 0
    assert "timing" in out, "compile still completed through the index phase"
    assert kb_two.load_compile_state() == {}
    log = log_of(kb_two)
    assert "[group-error] wiki/concept/target.md: combine blew up" in log
    assert "Compile done: 0 compiled" in log


# ── regression guards for the wiki containment fix ───────────────────

@pytest.mark.parametrize("art_path, expected", [
    ("wiki/concept/a.md", True),
    ("wiki/./a.md", True),
    ("wiki/sub/../a.md", True),
    ("notwiki/a.md", False),          # missing prefix
    ("wiki/../raw/a.md", False),      # clobbers a raw source
    ("wiki/../.compile.log", False),  # clobbers the compile log
    ("wiki/../index/master-index.md", False),  # clobbers a generated index
    ("wiki/../wiki-old/a.md", False), # sibling dir sharing the prefix
    ("wiki/../../outside.md", False),
])
def test_under_wiki_accepts_only_paths_resolving_inside_the_wiki_subtree(
    kb_one: KBStore, art_path: str, expected: bool
):
    """Article paths come from LLM output, so the wiki/ prefix alone is not a
    containment check -- compile_kb had only the prefix check and could write
    outside the wiki subtree."""
    assert cm._under_wiki(kb_one, art_path) is expected
