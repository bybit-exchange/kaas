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
from kb_ai.core import extract as ex
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

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_extract)
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


def test_compile_does_not_promote_a_merge_after_the_same_path_create_failed(
    kb_two, fakes, monkeypatch
):
    """A create that failed this run must not be replaced by a merge promoted to
    a stem-titled create: the article would carry the *other* document's content
    under a title describing the document whose create failed. Leave the path
    absent and report the merge sources so the next compile retries both."""
    def classify_by_source(extraction, existing, model="m", categories=None):
        if "content of a" in extraction.summary:
            return {"merge_into": [], "create_new": [
                {"path": "wiki/reference/policy.md", "type": "reference", "title": "A Policy"},
            ]}
        return merges("wiki/reference/policy.md")

    monkeypatch.setattr(cm, "classify_article", classify_by_source)
    fakes["fail_write"] = {"A Policy"}

    out = cm.compile_kb(str(kb_two.base_dir))

    assert fakes["created"] == [], "no article may be written once its create failed"
    assert not (kb_two.base_dir / "wiki/reference/policy.md").exists()
    assert out["compiled"] == 0
    assert {e["file"] for e in out["errors"]} == {"raw/a.md", "raw/b.md"}
    assert all(e["article"] == "wiki/reference/policy.md" for e in out["errors"])
    assert kb_two.load_compile_state() == {}, "both sources must be retried"
    log = log_of(kb_two)
    assert "[create-error] wiki/reference/policy.md ← raw/a.md" in log
    assert "[merge-skipped] wiki/reference/policy.md ← 1 sources" in log
    assert "[merge→create]" not in log


def test_compile_still_merges_when_a_create_failed_but_the_article_exists(
    kb_two, fakes, monkeypatch
):
    """The skip is conditioned on the article being absent, not on a create having
    failed. An existing target is already properly titled, so a create that failed
    against it -- it merges, the path being taken -- must not hold the others back."""
    kb_two.write_article("wiki/concept/target.md", "prior body\n")
    calls: list[str] = []

    def first_merge_fails(article_path, article_content, extraction, source_path, model="m"):
        calls.append(source_path)
        if len(calls) == 1:
            raise RuntimeError(f"merge failed for {source_path}")
        return article_content + f"\nmerged {source_path}\n"

    def classify_by_source(extraction, existing, model="m", categories=None):
        if "content of a" in extraction.summary:
            return {"merge_into": [], "create_new": [
                {"path": "wiki/concept/target.md", "type": "concept", "title": "A Target"},
            ]}
        return merges("wiki/concept/target.md")

    monkeypatch.setattr(cm, "classify_article", classify_by_source)
    monkeypatch.setattr(cm, "merge_into_article", first_merge_fails)

    out = cm.compile_kb(str(kb_two.base_dir))

    assert calls == ["raw/a.md", "raw/b.md"], "the surviving source must still merge"
    assert "merged raw/b.md" in (kb_two.base_dir / "wiki/concept/target.md").read_text()
    assert out["compiled"] == 1
    assert {e["file"] for e in out["errors"]} == {"raw/a.md"}
    log = log_of(kb_two)
    assert "[create-error] wiki/concept/target.md ← raw/a.md" in log
    assert "[merge] wiki/concept/target.md ← raw/b.md" in log
    assert "[merge-skipped]" not in log


def test_compile_still_promotes_a_merge_when_no_create_was_attempted(kb_two, fakes):
    """The guard above is scoped to the failure route. A merge into a path that
    was never a create target keeps promoting to a create, as before."""
    fakes["classification"] = merges("wiki/concept/target.md")

    out = cm.compile_kb(str(kb_two.base_dir))

    assert fakes["created"] == [("concept", "Target", "raw/a.md, raw/b.md")]
    assert out["compiled"] == 2
    assert "[merge→create] wiki/concept/target.md ← 2 sources" in log_of(kb_two)


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


# ── worker context: op attribution and alert routing ────────────────
#
# contextvars are not inherited by pool threads, so a compile worker starts on a
# default ThreadContext unless the parent's is installed explicitly. That is what
# made a stalled write report op=unknown and kept its warning out of the compile
# log (issue #26).

def creates(path: str, title: str, art_type: str = "concept") -> dict:
    return {"merge_into": [],
            "create_new": [{"path": path, "type": art_type, "title": title}]}


def test_write_worker_labels_its_phase_with_the_article(kb_one, fakes, monkeypatch):
    """op= in an LLM warning must name the phase and the article that stalled."""
    from kb_ai._context import get_context

    seen = {}

    def recording_create(article_type, title, extraction, source_path, model="m"):
        seen["phase"] = get_context().phase
        return "body\n"

    monkeypatch.setattr(cm, "create_new_article", recording_create)
    fakes["classification"] = creates("wiki/concept/target.md", "Target")

    cm.compile_kb(str(kb_one.base_dir))

    assert seen["phase"] == "write:wiki/concept/target.md"


def test_merge_worker_labels_its_phase_with_the_article(kb_one, fakes, monkeypatch):
    from kb_ai._context import get_context

    seen = {}

    def recording_merge(article_path, article_content, extraction, source_path, model="m"):
        seen["phase"] = get_context().phase
        return article_content

    kb_one.write_article("wiki/concept/target.md", "prior body\n")
    monkeypatch.setattr(cm, "merge_into_article", recording_merge)
    fakes["classification"] = merges("wiki/concept/target.md")

    cm.compile_kb(str(kb_one.base_dir))

    assert seen["phase"] == "write:wiki/concept/target.md"


def test_extract_worker_labels_its_phase_with_the_document(kb_one, fakes, monkeypatch):
    """Labelling only the write phase would leave op=unknown meaning "extract",
    which is the same ambiguity by another name."""
    from kb_ai._context import get_context

    seen = {}

    def recording_extract(content, model="m"):
        seen["phase"] = get_context().phase
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    monkeypatch.setattr(ex, "extract_knowledge_chunked", recording_extract)

    cm.compile_kb(str(kb_one.base_dir))

    assert seen["phase"] == "extract:raw/only.md"


def test_worker_keeps_the_parents_request_tracker(kb_one, fakes, monkeypatch):
    """Installing the parent context must not drop what set_request_tracker did:
    a daemon request's cost is accounted against its own tracker.

    Observed in the extract worker because the write worker deliberately nests a
    per-op tracker inside it (see _measure_op_cost), which would mask this.
    """
    from kb_ai._context import get_context
    from kb_ai._cost import CostTracker
    from kb_ai.llm import set_request_tracker

    req = CostTracker()
    set_request_tracker(req)
    seen = {}

    def recording_extract(content, model="m"):
        seen["tracker"] = get_context().request_tracker
        return ExtractionResult(summary=f"summary of {content}", topics=["t"])

    monkeypatch.setattr(ex, "extract_knowledge_chunked", recording_extract)
    try:
        cm.compile_kb(str(kb_one.base_dir))
    finally:
        set_request_tracker(None)

    assert seen["tracker"] is req


def test_write_worker_nests_its_op_tracker_under_the_parents(kb_one, fakes, monkeypatch):
    """The per-op tracker a write worker nests must still fold into the request's,
    or installing the parent context would have quietly changed cost accounting."""
    from kb_ai._cost import CostTracker
    from kb_ai.llm import set_request_tracker

    req = CostTracker()
    set_request_tracker(req)

    def costing_create(article_type, title, extraction, source_path, model="m"):
        from kb_ai.llm import get_request_tracker
        get_request_tracker().record("m", prompt_tokens=10, completion_tokens=5, cost=0.5)
        return "body\n"

    monkeypatch.setattr(cm, "create_new_article", costing_create)
    fakes["classification"] = creates("wiki/concept/target.md", "Target")
    try:
        cm.compile_kb(str(kb_one.base_dir))
    finally:
        set_request_tracker(None)

    assert req.calls == 1
    assert req.total_cost == 0.5


def test_llm_warning_from_a_write_worker_reaches_the_compile_log(
    kb_one, fakes, monkeypatch
):
    """The 15-minute stall showed up only in the backend's stderr; .compile.log
    just stopped advancing with no explanation."""
    from kb_ai.llm._infra import emit_alert

    def stalling_create(article_type, title, extraction, source_path, model="m"):
        emit_alert("op=write model=m attempt=1/3 elapsed=901.7s", "m", 1,
                   "api_timeout_error")
        return "body\n"

    monkeypatch.setattr(cm, "create_new_article", stalling_create)
    fakes["classification"] = creates("wiki/concept/target.md", "Target")

    cm.compile_kb(str(kb_one.base_dir))

    log = log_of(kb_one)
    assert "[LLM-WARN] api_timeout_error" in log
    assert "elapsed=901.7s" in log


def test_the_alert_sink_does_not_outlive_the_compile(kb_one, fakes, capsys):
    """The sink closes over an open file handle, so it must be cleared -- a later
    call on the same thread would otherwise write into a closed compile log."""
    from kb_ai._context import get_context
    from kb_ai.llm._infra import emit_alert

    fakes["classification"] = creates("wiki/concept/target.md", "Target")

    cm.compile_kb(str(kb_one.base_dir))

    assert get_context().alert_sink is None
    emit_alert("after the compile", "m", 1, "api_timeout_error")
    assert "after the compile" in capsys.readouterr().err


# ── end-to-end: the failure issue #26 reported ──────────────────────

def test_a_stalled_write_is_attributable_and_capped(kb_one, fakes, monkeypatch):
    """The whole reported failure, driven through the real write path.

    Before the fix a write inherited the 900s client default and its warning said
    `op=unknown` on stderr only, so a 15-minute stall left .compile.log frozen with
    nothing to attribute it to.
    """
    import time as time_mod
    from unittest.mock import MagicMock, patch

    import httpx
    from openai import APITimeoutError

    import kb_ai.llm as llm_pkg
    from kb_ai.core.merge import _WRITE_CALL_TIMEOUT_S, create_new_article

    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)   # skip retry backoff
    monkeypatch.setattr(cm, "create_new_article", create_new_article)
    fakes["classification"] = creates("wiki/concept/target.md", "Target")

    client = MagicMock()
    client.base_url = "http://test:8080/v1"
    client.chat.completions.create.side_effect = APITimeoutError(
        httpx.Request("POST", "http://test:8080/v1/chat/completions"))
    client.with_options.return_value = client

    with patch.object(llm_pkg, "get_client", return_value=client):
        out = cm.compile_kb(str(kb_one.base_dir))

    # Capped: the write asked for its own timeout instead of the client default.
    assert client.with_options.call_args_list
    assert all(c.kwargs["timeout"] == _WRITE_CALL_TIMEOUT_S
               for c in client.with_options.call_args_list)

    # Attributable: named phase and article, in the log of the KB being compiled.
    log = log_of(kb_one)
    assert "[LLM-WARN] api_timeout_error" in log
    assert "op=write:wiki/concept/target.md" in log
    assert "op=unknown" not in log

    # And the run still reports the failure rather than swallowing it.
    assert out["compiled"] == 0
    assert len(out["errors"]) == 1
