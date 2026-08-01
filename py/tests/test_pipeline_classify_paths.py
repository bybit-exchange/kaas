"""Offline tests for the classify phase paths (kb_ai.commands.pipeline._phase_classify).

`classify_article` (the only LLM boundary) is monkeypatched with a fake that
records its arguments, so what is under test here is the orchestration around it:
the classify cache, within-group `existing` accumulation, per-item error
containment, the parallel multi-group branch, and cancellation.

The last section checks that the error dicts this phase produces actually reach
the caller of run_pipeline_orchestrated().
"""
from __future__ import annotations

import hashlib
import json
import threading

import pytest
from openai import APIError as LLMAPIError

from kb_ai._types import ClassificationResult, CreateTarget
from kb_ai.commands.pipeline import _orchestrator as orch
from kb_ai.commands.pipeline import _phase_classify as pc
from kb_ai.commands.pipeline._orchestrator import PipelineContext, run_pipeline_orchestrated
from kb_ai.commands.pipeline._phase_classify import run_classify_phase
from kb_ai.core.classify import classify_cache_key, hash_existing_articles
from kb_ai.storage.store import KBStore

CATS = ["concept"]
DEFAULT_CATS = ["concept", "project", "decision", "person"]


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path) -> KBStore:
    """Empty KB: no master-index, so existing_articles() is []."""
    return KBStore(str(tmp_path))


@pytest.fixture
def store_with_index(tmp_path) -> KBStore:
    """KB whose master-index lists one article named "Existing"."""
    store = KBStore(str(tmp_path))
    store.index_dir.mkdir(parents=True, exist_ok=True)
    (store.index_dir / "master-index.md").write_text(
        "# Index\n- [Existing](wiki/concept/existing.md) — an existing article\n"
    )
    return store


@pytest.fixture
def classifier(monkeypatch):
    """Fake classify_article with a call log, a failure switch and a create plan.

    Keys are source_ref values (which the phase copies onto
    extraction.source_path before calling out).
    """
    state: dict = {"calls": [], "raise": {}, "creates": {}}

    def fake_classify_article(extraction, existing, model="claude-sonnet-4-6", categories=None):
        ref = extraction.source_path
        state["calls"].append({
            "source_ref": ref,
            "existing": [a.title for a in existing],
            "model": model,
            "categories": list(categories or []),
            "summary": extraction.summary,
        })
        if ref in state["raise"]:
            raise state["raise"][ref]
        return ClassificationResult(create_new=[
            CreateTarget(path=p, type="concept", title=t)
            for p, t in state["creates"].get(ref, [])
        ])

    monkeypatch.setattr(pc, "classify_article", fake_classify_article)
    return state


def make_item(content_hash: str, topics: list[str]) -> dict:
    return {
        "content_hash": content_hash,
        "source_ref": f"raw/{content_hash}.md",
        "extraction": {"summary": f"sum {content_hash}", "topics": topics},
    }


def cache_key_for(store: KBStore, content_hash: str, categories: list[str]) -> str:
    """Recompute the cache key exactly the way run_classify_phase does."""
    cat_hash = hashlib.sha256(
        json.dumps(categories, sort_keys=True).encode()
    ).hexdigest()[:8]
    art_hash = hash_existing_articles(store.existing_articles())
    return classify_cache_key(content_hash, art_hash, cat_hash)


def errors_by_hash(errors: list[dict]) -> dict[str, dict]:
    return {e["content_hash"]: e for e in errors}


# ── classify cache ──────────────────────────────────────────────────

def test_classify_uses_a_cached_classification_instead_of_the_llm(store, classifier):
    key = cache_key_for(store, "h1", CATS)
    store.save_classify_cache(key, {
        "merge_into": [{"path": "wiki/concept/cached.md", "reason": "from cache"}],
        "create_new": [],
    })

    classified, errors = run_classify_phase([make_item("h1", ["t"])], store, categories=CATS)

    assert classifier["calls"] == [], "a cache hit must not call the LLM"
    assert errors == []
    assert [m.path for m in classified[0][3].merge_into] == ["wiki/concept/cached.md"]


def test_classify_caches_a_fresh_result_so_the_second_run_is_free(store, classifier):
    items = [make_item("h1", ["t"])]

    run_classify_phase(items, store, categories=CATS)
    run_classify_phase(items, store, categories=CATS)

    assert len(classifier["calls"]) == 1


def test_classify_cache_is_keyed_by_the_category_list(store, classifier):
    items = [make_item("h1", ["t"])]

    run_classify_phase(items, store, categories=["concept"])
    run_classify_phase(items, store, categories=["concept", "project"])

    assert len(classifier["calls"]) == 2


def test_classify_skips_the_cache_for_an_item_without_a_content_hash(store, classifier):
    item = {"source_ref": "raw/nohash.md", "extraction": {"summary": "s", "topics": ["t"]}}

    run_classify_phase([item], store, categories=CATS)
    run_classify_phase([item], store, categories=CATS)

    assert len(classifier["calls"]) == 2
    assert not (store.base_dir / ".classify-cache").exists()


# ── model / category plumbing ───────────────────────────────────────

def test_classify_defaults_the_category_list(store, classifier):
    run_classify_phase([make_item("h1", ["t"])], store)

    assert classifier["calls"][0]["categories"] == DEFAULT_CATS


def test_classify_forwards_the_classify_model(store, classifier):
    run_classify_phase(
        [make_item("h1", ["t"])], store, classify_model="claude-haiku-4-5", categories=CATS)

    assert classifier["calls"][0]["model"] == "claude-haiku-4-5"


# ── single group: accumulation and error containment ────────────────

def test_classify_accumulates_new_articles_within_a_group(store_with_index, classifier):
    """Items sharing a topic run serially so the later one sees the earlier's creates."""
    classifier["creates"]["raw/h1.md"] = [("wiki/concept/foo.md", "Foo")]
    items = [make_item("h1", ["shared"]), make_item("h2", ["shared"])]

    classified, errors = run_classify_phase(items, store_with_index, categories=CATS)

    assert errors == []
    assert len(classified) == 2
    assert classifier["calls"][0]["existing"] == ["Existing"]
    assert classifier["calls"][1]["existing"] == ["Existing", "Foo"]


def test_classify_contains_one_failing_item_without_dropping_its_group_siblings(
        store, classifier):
    classifier["raise"]["raw/h1.md"] = RuntimeError("boom")
    items = [make_item("h1", ["shared"]), make_item("h2", ["shared"])]

    classified, errors = run_classify_phase(items, store, categories=CATS)

    assert [c[0] for c in classified] == ["h2"]
    assert errors == [{
        "content_hash": "h1",
        "status": "error",
        "error": "Error (Classify): boom",
        "phase": "classify",
    }]


def test_classify_labels_llm_errors_distinctly(store, classifier):
    classifier["raise"]["raw/h1.md"] = LLMAPIError("rate limited", request=None, body=None)

    classified, errors = run_classify_phase([make_item("h1", ["t"])], store, categories=CATS)

    assert classified == []
    assert errors[0]["error"].startswith("LLM Error (Classify): ")


def test_classify_does_not_cache_a_failed_item(store, classifier):
    classifier["raise"]["raw/h1.md"] = RuntimeError("boom")
    items = [make_item("h1", ["t"])]

    run_classify_phase(items, store, categories=CATS)
    classifier["raise"].clear()
    classified, errors = run_classify_phase(items, store, categories=CATS)

    assert len(classifier["calls"]) == 2, "the failure must not have been cached"
    assert errors == []
    assert len(classified) == 1


def test_classify_reports_the_clustering_on_stderr(store, classifier, capsys):
    items = [make_item("h1", ["shared"]), make_item("h2", ["shared"])]

    run_classify_phase(items, store, categories=CATS)

    assert "clustered 2 items into 1 groups (max group size: 2)" in capsys.readouterr().err


# ── multiple groups: parallel branch ────────────────────────────────

def test_classify_processes_every_group_in_the_parallel_branch(store, classifier):
    items = [make_item(f"h{i}", [f"topic{i}"]) for i in range(4)]

    classified, errors = run_classify_phase(items, store, categories=CATS)

    assert errors == []
    assert sorted(c[0] for c in classified) == ["h0", "h1", "h2", "h3"]


def test_classify_gives_each_group_the_same_untouched_baseline(store_with_index, classifier):
    """Groups run in parallel, so none may observe another group's creates."""
    for i in range(3):
        classifier["creates"][f"raw/h{i}.md"] = [(f"wiki/concept/c{i}.md", f"C{i}")]
    items = [make_item(f"h{i}", [f"topic{i}"]) for i in range(3)]

    run_classify_phase(items, store_with_index, categories=CATS)

    assert [c["existing"] for c in classifier["calls"]] == [["Existing"]] * 3


def test_classify_contains_a_failing_item_in_the_parallel_branch(store, classifier):
    classifier["raise"]["raw/h0.md"] = RuntimeError("boom")
    items = [make_item("h0", ["alpha"]), make_item("h1", ["beta"])]

    classified, errors = run_classify_phase(items, store, categories=CATS)

    assert [c[0] for c in classified] == ["h1"]
    assert errors_by_hash(errors)["h0"] == {
        "content_hash": "h0",
        "status": "error",
        "error": "Error (Classify): boom",
        "phase": "classify",
    }


def test_classify_turns_a_crashed_group_into_one_error_per_item(store, monkeypatch, classifier):
    """A group task that dies outside _classify_group's own try must still be
    reported per item rather than losing the items silently."""
    def boom(*args, **kwargs):
        raise RuntimeError("group exploded")

    monkeypatch.setattr(pc, "_classify_group", boom)
    items = [make_item("h0", ["alpha"]), make_item("h1", ["beta"])]

    classified, errors = run_classify_phase(items, store, categories=CATS)

    assert classified == []
    assert {e["content_hash"] for e in errors} == {"h0", "h1"}
    assert all(e["error"] == "group exploded" for e in errors)
    assert all(e["phase"] == "classify" and e["status"] == "error" for e in errors)


# ── cancellation ────────────────────────────────────────────────────

def test_classify_stops_collecting_groups_when_cancelled(store, classifier, capsys):
    """Cancelled before the first future is drained: nothing is collected and the
    reason is logged."""
    cancel = threading.Event()
    cancel.set()
    items = [make_item(f"h{i}", [f"topic{i}"]) for i in range(3)]

    classified, errors = run_classify_phase(
        items, store, categories=CATS, cancel_event=cancel)

    assert classified == []
    assert errors == []
    err = capsys.readouterr().err
    assert "cancel detected in classify" in err
    assert "completed=0/3 groups" in err


def test_classify_single_group_still_returns_results_when_cancelled(store, classifier):
    """The serial branch has no cancel check of its own -- documents that a
    single group runs to completion."""
    cancel = threading.Event()
    cancel.set()
    items = [make_item("h1", ["shared"]), make_item("h2", ["shared"])]

    classified, errors = run_classify_phase(
        items, store, categories=CATS, cancel_event=cancel)

    assert [c[0] for c in classified] == ["h1", "h2"]
    assert errors == []


def test_classify_arms_the_cancel_event_in_the_serial_branch(store, monkeypatch):
    """cancellable() must arm the context so in-flight LLM calls can abort."""
    cancel = threading.Event()
    seen = []

    def record(extraction, existing, model="m", categories=None):
        seen.append(pc.get_context().cancel_event)
        return ClassificationResult()

    monkeypatch.setattr(pc, "classify_article", record)
    run_classify_phase(
        [make_item("h1", ["shared"]), make_item("h2", ["shared"])],
        store, categories=CATS, cancel_event=cancel,
    )

    assert seen == [cancel, cancel]


@pytest.mark.xfail(strict=True, reason=(
    "BUG: contextual_submit shares ONE ThreadContext object between all parallel "
    "classify groups, and cancellable()'s finally sets ctx.cancel_event = None. "
    "The first group to finish therefore disarms cancellation for the groups still "
    "running, so a client disconnect / deadline can no longer abort their in-flight "
    "LLM calls -- the pipeline keeps burning tokens after it was cancelled."
))
def test_classify_keeps_the_cancel_event_armed_while_another_group_finishes(
        store, monkeypatch):
    from contextlib import contextmanager

    cancel = threading.Event()  # left unset: what matters is that it stays reachable
    slow_inside = threading.Event()   # group A is inside its cancellable block
    a_group_exited = threading.Event()  # some group's cancellable block has exited
    seen: list = []

    real_cancellable = pc.cancellable

    @contextmanager
    def spy_cancellable(event):
        with real_cancellable(event):
            yield
        a_group_exited.set()

    def record(extraction, existing, model="m", categories=None):
        if extraction.source_path == "raw/slow.md":
            slow_inside.set()
            assert a_group_exited.wait(5), "the other group never finished"
            seen.append(pc.get_context().cancel_event)
        else:
            assert slow_inside.wait(5), "the slow group never started"
        return ClassificationResult()

    monkeypatch.setattr(pc, "cancellable", spy_cancellable)
    monkeypatch.setattr(pc, "classify_article", record)

    items = [
        {"content_hash": "slow", "source_ref": "raw/slow.md",
         "extraction": {"summary": "s", "topics": ["alpha"]}},
        {"content_hash": "fast", "source_ref": "raw/fast.md",
         "extraction": {"summary": "s", "topics": ["beta"]}},
    ]
    run_classify_phase(items, store, categories=CATS, cancel_event=cancel)

    assert seen == [cancel]


# ── the phase's errors reach the orchestrator's caller ──────────────

@pytest.fixture
def stub_phases(monkeypatch):
    """Stub all three phases; classify returns whatever errors the test wants."""
    state: dict = {"classify_errors": []}

    monkeypatch.setattr(orch, "run_classify_phase",
                        lambda **kwargs: ([], list(state["classify_errors"])))
    monkeypatch.setattr(orch, "run_dedup_phase", lambda **kwargs: ([], 0))
    monkeypatch.setattr(orch, "run_write_phase", lambda **kwargs: ([], 0))
    return state


def test_orchestrator_returns_classify_errors_as_item_results(
        tmp_path, fresh_context, stub_phases):
    err = {"content_hash": "h1", "status": "error",
           "error": "Error (Classify): boom", "phase": "classify"}
    stub_phases["classify_errors"] = [err]

    results = run_pipeline_orchestrated(
        PipelineContext(store=KBStore(str(tmp_path))), [make_item("h1", ["t"])])

    assert results == [err]


def test_orchestrator_emits_classify_errors_before_the_phase_event(
        tmp_path, fresh_context, stub_phases):
    err = {"content_hash": "h1", "status": "error", "error": "boom", "phase": "classify"}
    stub_phases["classify_errors"] = [err]
    events: list[dict] = []

    run_pipeline_orchestrated(
        PipelineContext(store=KBStore(str(tmp_path)), emit=events.append),
        [make_item("h1", ["t"])],
    )

    assert events[0] == err
    assert events[1]["type"] == "phase" and events[1]["phase"] == "classify"


def test_orchestrator_keeps_every_classify_error(tmp_path, fresh_context, stub_phases):
    stub_phases["classify_errors"] = [
        {"content_hash": f"h{i}", "status": "error", "error": "boom", "phase": "classify"}
        for i in range(3)
    ]

    results = run_pipeline_orchestrated(
        PipelineContext(store=KBStore(str(tmp_path))), [])

    assert [r["content_hash"] for r in results] == ["h0", "h1", "h2"]
