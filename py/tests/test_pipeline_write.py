"""Offline tests for the pipeline write phase (kb_ai.commands.pipeline._phase_write).

The article writers are monkeypatched. What matters here is the orchestration:
path validation (wiki/ prefix and no escape out of wiki/), grouping several
sources into one article call, per-article error containment, cancellation, and
the per-item result / emit contract the streaming protocol depends on.
"""
from __future__ import annotations

import threading

import pytest

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.commands.pipeline import _phase_write as pw
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import KBStore


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path) -> KBStore:
    return KBStore(str(tmp_path))


@pytest.fixture
def writers(monkeypatch):
    """Fake create/merge article writers with a call log and a failure switch."""
    state = {"created": [], "merged": [], "fail": set(), "cancel_on": set()}

    def fake_create(article_type, title, extraction, source_path, model="m"):
        if title in state["fail"]:
            raise RuntimeError(f"create failed: {title}")
        state["created"].append({"type": article_type, "title": title,
                                 "sources": source_path})
        return f"---\ntitle: {title}\n---\nbody\n"

    def fake_merge(art_path, old_content, extraction, source_path, model="m"):
        if art_path in state["fail"]:
            raise RuntimeError(f"merge failed: {art_path}")
        state["merged"].append({"path": art_path, "sources": source_path})
        return old_content + "\nmerged\n"

    monkeypatch.setattr(pw, "create_new_article", fake_create)
    monkeypatch.setattr(pw, "merge_into_article", fake_merge)
    return state


def item(content_hash: str, *, creates=(), merges=(), source_ref="raw/a.md"):
    """Build one classified_items entry."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path=p, type=t, title=ti) for p, t, ti in creates],
        merge_into=[MergeTarget(path=p) for p in merges],
    )
    return (content_hash, source_ref, ExtractionResult(summary=f"sum {content_hash}"),
            classification)


def by_hash(results: list[dict]) -> dict[str, dict]:
    return {r["content_hash"]: r for r in results}


# ── _ensure_write_result ────────────────────────────────────────────

def test_ensure_write_result_creates_the_slot():
    results: dict[str, dict] = {}
    pw._ensure_write_result(results, "h1")
    assert results["h1"] == {"created": [], "merged": [], "errors": []}


def test_ensure_write_result_is_idempotent():
    results = {"h1": {"created": ["x"], "merged": [], "errors": []}}
    pw._ensure_write_result(results, "h1")
    assert results["h1"]["created"] == ["x"]


# ── create path ─────────────────────────────────────────────────────

def test_write_creates_a_new_article(store, writers):
    items = [item("h1", creates=[("wiki/concept/topic.md", "concept", "Topic")])]

    results, written = pw.run_write_phase(items, store)

    assert written == 1
    assert (store.base_dir / "wiki/concept/topic.md").exists()
    assert by_hash(results)["h1"]["created"] == ["wiki/concept/topic.md"]
    assert by_hash(results)["h1"]["status"] == "ok"


def test_write_uses_the_classifier_type_and_title(store, writers):
    items = [item("h1", creates=[("wiki/project/x.md", "project", "My Project")])]

    pw.run_write_phase(items, store)

    assert writers["created"][0]["type"] == "project"
    assert writers["created"][0]["title"] == "My Project"


def test_write_derives_type_and_title_when_classifier_omits_them(store, writers):
    items = [item("h1", creates=[("wiki/concept/my-cool-topic.md", "", "")])]

    pw.run_write_phase(items, store)

    assert writers["created"][0]["type"] == "concept"
    assert writers["created"][0]["title"] == "My Cool Topic"


def test_write_falls_back_to_concept_for_a_shallow_path(store, writers):
    items = [item("h1", creates=[("wiki/flat.md", "", "")])]

    pw.run_write_phase(items, store)

    assert writers["created"][0]["type"] == "concept"


# ── merge path ──────────────────────────────────────────────────────

def test_write_merges_into_an_existing_article(store, writers):
    store.write_article("wiki/concept/topic.md", "---\ntitle: T\n---\nexisting\n")
    items = [item("h1", merges=["wiki/concept/topic.md"])]

    results, written = pw.run_write_phase(items, store)

    assert written == 1
    assert writers["merged"][0]["path"] == "wiki/concept/topic.md"
    assert by_hash(results)["h1"]["merged"] == ["wiki/concept/topic.md"]


def test_write_turns_a_merge_into_a_create_when_the_article_is_absent(store, writers):
    items = [item("h1", merges=["wiki/concept/absent.md"])]

    results, _ = pw.run_write_phase(items, store)

    assert writers["created"], "a missing merge target must be created"
    assert writers["merged"] == []
    assert by_hash(results)["h1"]["created"] == ["wiki/concept/absent.md"]


def test_write_batches_several_sources_into_one_call(store, writers):
    store.write_article("wiki/concept/shared.md", "existing")
    items = [
        item("h1", merges=["wiki/concept/shared.md"], source_ref="raw/a.md"),
        item("h2", merges=["wiki/concept/shared.md"], source_ref="raw/b.md"),
    ]

    results, written = pw.run_write_phase(items, store)

    assert written == 1
    assert len(writers["merged"]) == 1, "one LLM call should cover both sources"
    assert "raw/a.md" in writers["merged"][0]["sources"]
    assert "raw/b.md" in writers["merged"][0]["sources"]
    # Both items are credited with the write.
    assert by_hash(results)["h1"]["merged"] == ["wiki/concept/shared.md"]
    assert by_hash(results)["h2"]["merged"] == ["wiki/concept/shared.md"]


def test_write_handles_create_and_merge_for_one_item(store, writers):
    store.write_article("wiki/concept/old.md", "existing")
    items = [item("h1", creates=[("wiki/concept/new.md", "concept", "New")],
                  merges=["wiki/concept/old.md"])]

    results, written = pw.run_write_phase(items, store)

    assert written == 2
    r = by_hash(results)["h1"]
    assert r["created"] == ["wiki/concept/new.md"]
    assert r["merged"] == ["wiki/concept/old.md"]


# ── path validation ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad_path", ["notwiki/a.md", "raw/a.md", "a.md", ""])
def test_write_rejects_paths_outside_wiki(store, writers, bad_path):
    items = [item("h1", creates=[(bad_path, "concept", "T")])]

    results, written = pw.run_write_phase(items, store)

    assert written == 0
    assert writers["created"] == []
    r = by_hash(results)["h1"]
    assert r["status"] == "error"
    assert "must start with wiki/" in r["error"]
    assert r["phase"] == "write"


def test_write_rejects_a_path_escaping_the_wiki_dir(store, writers):
    """A wiki/-prefixed path can still escape via .., so the resolved path is
    checked too."""
    items = [item("h1", creates=[("wiki/../../etc/passwd", "concept", "T")])]

    results, written = pw.run_write_phase(items, store)

    assert written == 0
    assert writers["created"] == []
    assert "escapes wiki/" in by_hash(results)["h1"]["error"]


def test_write_rejects_bad_merge_paths(store, writers):
    items = [item("h1", merges=["notwiki/a.md"])]

    results, _ = pw.run_write_phase(items, store)

    assert writers["merged"] == []
    assert "must start with wiki/" in by_hash(results)["h1"]["error"]


def test_write_rejects_merge_paths_escaping_the_wiki_dir(store, writers):
    items = [item("h1", merges=["wiki/../../outside.md"])]

    results, _ = pw.run_write_phase(items, store)

    assert "escapes wiki/" in by_hash(results)["h1"]["error"]
    assert writers["created"] == [] and writers["merged"] == []


@pytest.mark.parametrize("escaping_path", [
    "wiki/../raw/a.md",                  # clobbers a raw source file
    "wiki/../.compile.log",              # clobbers the compile log
    "wiki/../index/master-index.md",     # clobbers a generated index
])
def test_write_rejects_paths_leaving_the_wiki_subtree(store, writers, escaping_path):
    items = [item("h1", creates=[(escaping_path, "concept", "Outside")])]

    results, _ = pw.run_write_phase(items, store)

    assert by_hash(results)["h1"]["status"] == "error"
    assert writers["created"] == []


def test_write_keeps_good_ops_when_a_sibling_path_is_bad(store, writers):
    items = [item("h1", creates=[
        ("wiki/concept/good.md", "concept", "Good"),
        ("notwiki/bad.md", "concept", "Bad"),
    ])]

    results, written = pw.run_write_phase(items, store)

    assert written == 1
    assert len(writers["created"]) == 1
    statuses = {r["status"] for r in results if r["content_hash"] == "h1"}
    assert statuses == {"error", "ok"}


# ── no-op items ─────────────────────────────────────────────────────

def test_write_reports_an_item_with_no_targets_as_ok(store, writers):
    items = [item("h1")]

    results, written = pw.run_write_phase(items, store)

    assert written == 0
    assert by_hash(results)["h1"] == {
        "content_hash": "h1", "status": "ok", "created": [], "merged": [],
    }


def test_write_emits_no_op_items(store, writers):
    emitted = []
    pw.run_write_phase([item("h1")], store, emit=emitted.append)

    assert emitted == [{"content_hash": "h1", "status": "ok",
                        "created": [], "merged": []}]


def test_write_handles_an_empty_item_list(store, writers):
    results, written = pw.run_write_phase([], store)
    assert results == []
    assert written == 0


# ── error containment ───────────────────────────────────────────────

def test_write_contains_a_failing_article(store, writers):
    writers["fail"] = {"Bad"}
    items = [
        item("h1", creates=[("wiki/concept/bad.md", "concept", "Bad")]),
        item("h2", creates=[("wiki/concept/good.md", "concept", "Good")]),
    ]

    results, written = pw.run_write_phase(items, store)

    assert written == 2
    assert by_hash(results)["h1"]["status"] == "error"
    assert "create failed" in by_hash(results)["h1"]["error"]
    # The healthy article still got written.
    assert by_hash(results)["h2"]["status"] == "ok"


def test_write_labels_llm_errors_distinctly(store, writers, monkeypatch):
    from openai import APIError as LLMAPIError

    def boom(article_type, title, extraction, source_path, model="m"):
        raise LLMAPIError("rate limited", request=None, body=None)

    monkeypatch.setattr(pw, "create_new_article", boom)
    items = [item("h1", creates=[("wiki/concept/a.md", "concept", "A")])]

    results, _ = pw.run_write_phase(items, store)

    assert "LLM Error" in by_hash(results)["h1"]["error"]


def test_write_prefixes_non_llm_errors_with_error(store, writers):
    writers["fail"] = {"A"}
    items = [item("h1", creates=[("wiki/concept/a.md", "concept", "A")])]

    results, _ = pw.run_write_phase(items, store)

    error = by_hash(results)["h1"]["error"]
    assert error.startswith("Error (Write/create:")


def test_write_joins_multiple_errors_for_one_item(store, writers):
    writers["fail"] = {"A", "B"}
    items = [item("h1", creates=[
        ("wiki/concept/a.md", "concept", "A"),
        ("wiki/concept/b.md", "concept", "B"),
    ])]

    results, _ = pw.run_write_phase(items, store)

    error = by_hash(results)["h1"]["error"]
    assert "; " in error


def test_write_failure_is_shared_across_batched_sources(store, writers):
    store.write_article("wiki/concept/shared.md", "existing")
    writers["fail"] = {"wiki/concept/shared.md"}
    items = [
        item("h1", merges=["wiki/concept/shared.md"]),
        item("h2", merges=["wiki/concept/shared.md"]),
    ]

    results, _ = pw.run_write_phase(items, store)

    assert by_hash(results)["h1"]["status"] == "error"
    assert by_hash(results)["h2"]["status"] == "error"


def test_write_records_a_worker_crash_as_an_item_error(store, writers, monkeypatch):
    """_process_article contains its own writer errors, so a future that raises
    means the worker itself died (context propagation, MemoryError, ...). Those
    items must still get an error result instead of vanishing from the output."""
    def crash(*args, **kwargs):
        raise RuntimeError("worker died")

    monkeypatch.setattr(pw, "_process_article", crash)
    items = [
        item("h1", creates=[("wiki/concept/a.md", "concept", "A")]),
        item("h2", creates=[("wiki/concept/b.md", "concept", "B")]),
    ]
    emitted = []

    results, written = pw.run_write_phase(items, store, emit=emitted.append)

    assert written == 2
    assert by_hash(results)["h1"]["status"] == "error"
    assert by_hash(results)["h1"]["error"] == "worker died"
    assert by_hash(results)["h2"]["error"] == "worker died"
    assert {e["content_hash"] for e in emitted} == {"h1", "h2"}


def test_write_credits_every_batched_source_of_a_crashed_worker(store, writers, monkeypatch):
    """One dead worker covers several items when sources were batched into one
    article -- all of them need the error, not just the first."""
    store.write_article("wiki/concept/shared.md", "existing")

    def crash(*args, **kwargs):
        raise RuntimeError("worker died")

    monkeypatch.setattr(pw, "_process_article", crash)
    items = [
        item("h1", merges=["wiki/concept/shared.md"]),
        item("h2", merges=["wiki/concept/shared.md"]),
    ]

    results, _ = pw.run_write_phase(items, store)

    assert by_hash(results)["h1"]["error"] == "worker died"
    assert by_hash(results)["h2"]["error"] == "worker died"


# ── cancellation ────────────────────────────────────────────────────

def test_write_records_cancellation_as_an_item_error(store, writers, monkeypatch):
    from kb_ai._errors import PipelineCancelledError

    def boom(article_type, title, extraction, source_path, model="m"):
        raise PipelineCancelledError("client gone")

    monkeypatch.setattr(pw, "create_new_article", boom)
    items = [item("h1", creates=[("wiki/concept/a.md", "concept", "A")])]

    results, _ = pw.run_write_phase(items, store, cancel_event=threading.Event())

    r = by_hash(results)["h1"]
    assert r["status"] == "error"
    assert "pipeline cancelled" in r["error"]


def test_write_stops_early_when_cancelled_before_start(store, writers, capsys):
    cancel = threading.Event()
    cancel.set()
    items = [item(f"h{i}", creates=[(f"wiki/concept/a{i}.md", "concept", f"A{i}")])
             for i in range(4)]

    pw.run_write_phase(items, store, workers=1, cancel_event=cancel)

    assert "cancel detected in write" in capsys.readouterr().err


def test_write_still_reports_a_finished_write_when_cancelled_afterwards(store, writers, monkeypatch):
    """Cancelling right after a write lands makes the result loop break before
    emitting, so the finished article has to be reported by the final pass --
    otherwise a completed write would be dropped from the response."""
    cancel = threading.Event()
    store.write_article("wiki/concept/topic.md", "existing")

    def merge_then_cancel(art_path, old_content, extraction, source_path, model="m"):
        # The client disconnects while this write is in flight.
        cancel.set()
        return old_content + "\nmerged\n"

    monkeypatch.setattr(pw, "merge_into_article", merge_then_cancel)
    emitted = []

    results, _ = pw.run_write_phase([item("h1", merges=["wiki/concept/topic.md"])], store,
                                    cancel_event=cancel, emit=emitted.append)

    r = by_hash(results)["h1"]
    assert r["status"] == "ok"
    assert r["merged"] == ["wiki/concept/topic.md"]
    assert emitted == [r]


def test_write_still_reports_an_error_when_cancelled_afterwards(store, writers, monkeypatch):
    """Same final pass, failing article: the error must survive the early break
    instead of leaving the item with no result at all."""
    cancel = threading.Event()

    def fail_then_cancel(article_type, title, extraction, source_path, model="m"):
        cancel.set()
        raise RuntimeError("disk full")

    monkeypatch.setattr(pw, "create_new_article", fail_then_cancel)
    emitted = []

    results, _ = pw.run_write_phase([item("h1", creates=[("wiki/concept/a.md", "concept", "A")])],
                                    store, cancel_event=cancel, emit=emitted.append)

    r = by_hash(results)["h1"]
    assert r["status"] == "error"
    assert "disk full" in r["error"]
    assert emitted == [r]


# ── emit contract ───────────────────────────────────────────────────

def test_write_emits_one_result_per_item(store, writers):
    emitted = []
    items = [
        item("h1", creates=[("wiki/concept/a.md", "concept", "A")]),
        item("h2", creates=[("wiki/concept/b.md", "concept", "B")]),
    ]

    results, _ = pw.run_write_phase(items, store, emit=emitted.append)

    assert {e["content_hash"] for e in emitted} == {"h1", "h2"}
    assert len(emitted) == 2, "no item may be emitted twice"


def test_write_emits_each_hash_only_once_when_batched(store, writers):
    store.write_article("wiki/concept/shared.md", "existing")
    emitted = []
    items = [
        item("h1", merges=["wiki/concept/shared.md", "wiki/concept/other.md"]),
    ]

    pw.run_write_phase(items, store, emit=emitted.append)

    hashes = [e["content_hash"] for e in emitted]
    assert hashes.count("h1") == 1


def test_write_emit_result_matches_returned_result(store, writers):
    emitted = []
    items = [item("h1", creates=[("wiki/concept/a.md", "concept", "A")])]

    results, _ = pw.run_write_phase(items, store, emit=emitted.append)

    assert emitted == [r for r in results if r["content_hash"] == "h1"]


def test_write_works_without_an_emit_callback(store, writers):
    items = [item("h1", creates=[("wiki/concept/a.md", "concept", "A")])]
    results, written = pw.run_write_phase(items, store, emit=None)
    assert written == 1
    assert by_hash(results)["h1"]["status"] == "ok"


# ── worker sizing ───────────────────────────────────────────────────

def test_write_caps_workers_at_article_count(store, writers):
    items = [item("h1", creates=[("wiki/concept/only.md", "concept", "Only")])]

    # A huge worker budget with one article must not raise.
    results, written = pw.run_write_phase(items, store, workers=64)

    assert written == 1


def test_write_processes_many_articles(store, writers):
    items = [item(f"h{i}", creates=[(f"wiki/concept/a{i}.md", "concept", f"A{i}")])
             for i in range(12)]

    results, written = pw.run_write_phase(items, store, workers=4)

    assert written == 12
    assert len(writers["created"]) == 12
    assert all(by_hash(results)[f"h{i}"]["status"] == "ok" for i in range(12))
