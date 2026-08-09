"""Offline tests for the pipeline entry points (kb_ai.commands.pipeline._entry).

These are the bridge/HTTP seams, so what is tested here is the contract with the
Go backend: input parsing and defaults, ThreadContext setup (deadline +
cancel_event) and its teardown, and the JSON envelope the stdin-based entry
points print. The orchestrator itself is stubbed -- it has its own tests.
"""
from __future__ import annotations

import io
import json
import threading

import pytest

from kb_ai._context import get_context
from kb_ai.commands.pipeline import _entry
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage import extraction as exl
from kb_ai.storage.index import SUMMARY_MAX_CHARS
from kb_ai.storage.store import KBStore


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def kb_dir(tmp_path) -> str:
    return str(tmp_path)


@pytest.fixture
def orchestrator(monkeypatch):
    """Stub run_pipeline_orchestrated; records the PipelineContext and the
    ThreadContext state it observed."""
    state: dict = {"calls": [], "results": []}

    def fake_run(pipeline_ctx, items):
        ctx = get_context()
        state["calls"].append({
            "pipeline_ctx": pipeline_ctx,
            "items": items,
            "seen_deadline": ctx.deadline_abs,
            "seen_cancel_event": ctx.cancel_event,
        })
        return list(state["results"])

    monkeypatch.setattr(_entry, "run_pipeline_orchestrated", fake_run)
    return state


@pytest.fixture
def indexers(monkeypatch):
    """Stub the two index writers, recording their arguments."""
    state: dict = {"index": [], "people": []}

    def fake_index(store, *, min_articles=3, summary_max_chars=SUMMARY_MAX_CHARS):
        state["index"].append({"base_dir": str(store.base_dir), "min_articles": min_articles,
                               "summary_max_chars": summary_max_chars})

    def fake_people(store, people_cfg):
        state["people"].append({"base_dir": str(store.base_dir), "cfg": people_cfg})

    monkeypatch.setattr(_entry, "update_markdown_index", fake_index)
    monkeypatch.setattr(_entry, "update_people_stubs", fake_people)
    return state


def payload(kb_dir: str, **overrides) -> dict:
    data = {"kb_dir": kb_dir, "items": []}
    data.update(overrides)
    return data


def write_article(kb_dir: str, rel_path: str, title: str) -> None:
    KBStore(kb_dir).write_article(
        rel_path, f"---\ntitle: {title}\ntype: concept\ntags: [t]\n---\n\nBody.\n")


# ── run_server_pipeline_with_input: context setup ───────────────────

def test_pipeline_input_arms_the_cancel_event_for_the_run(
        kb_dir, fresh_context, orchestrator, indexers):
    cancel = threading.Event()

    _entry.run_server_pipeline_with_input(payload(kb_dir), cancel_event=cancel)

    assert orchestrator["calls"][0]["seen_cancel_event"] is cancel
    assert get_context().cancel_event is None, "the event must be cleared afterwards"


def test_pipeline_input_forwards_the_cancel_event_to_the_pipeline_context(
        kb_dir, fresh_context, orchestrator, indexers):
    cancel = threading.Event()

    _entry.run_server_pipeline_with_input(payload(kb_dir), cancel_event=cancel)

    assert orchestrator["calls"][0]["pipeline_ctx"].cancel_event is cancel


def test_pipeline_input_leaves_the_cancel_event_unset_when_none_is_given(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(payload(kb_dir))

    assert orchestrator["calls"][0]["seen_cancel_event"] is None


def test_pipeline_input_sets_a_deadline_and_clears_it_afterwards(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(payload(kb_dir, deadline_seconds=120))

    assert orchestrator["calls"][0]["seen_deadline"] > 0
    assert get_context().deadline_abs == 0.0


@pytest.mark.parametrize("deadline", [None, 0, -5])
def test_pipeline_input_ignores_a_non_positive_deadline(
        kb_dir, fresh_context, orchestrator, indexers, deadline):
    _entry.run_server_pipeline_with_input(payload(kb_dir, deadline_seconds=deadline))

    assert orchestrator["calls"][0]["seen_deadline"] == 0.0


def test_pipeline_input_clears_the_context_even_when_the_pipeline_raises(
        kb_dir, fresh_context, monkeypatch, indexers):
    def boom(pipeline_ctx, items):
        raise RuntimeError("orchestrator died")

    monkeypatch.setattr(_entry, "run_pipeline_orchestrated", boom)
    cancel = threading.Event()

    with pytest.raises(RuntimeError, match="orchestrator died"):
        _entry.run_server_pipeline_with_input(
            payload(kb_dir, deadline_seconds=60), cancel_event=cancel)

    assert get_context().cancel_event is None
    assert get_context().deadline_abs == 0.0


# ── run_server_pipeline_with_input: input parsing ───────────────────

def test_pipeline_input_defaults_the_configuration(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(payload(kb_dir))

    ctx = orchestrator["calls"][0]["pipeline_ctx"]
    assert ctx.model == "claude-sonnet-4-6"
    assert ctx.classify_model == "claude-sonnet-4-6"
    assert ctx.categories == ["concept", "decision", "project", "reference", "guide", "person"]
    assert ctx.workers == 16
    assert str(ctx.store.base_dir) == str(KBStore(kb_dir).base_dir)


def test_pipeline_input_falls_back_to_the_write_model_for_classification(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(
        payload(kb_dir, model="claude-opus-4-5", classify_model=""))

    assert orchestrator["calls"][0]["pipeline_ctx"].classify_model == "claude-opus-4-5"


def test_pipeline_input_honours_an_explicit_configuration(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(payload(
        kb_dir,
        model="claude-opus-4-5",
        classify_model="claude-haiku-4-5",
        categories=["concept"],
        workers=3,
    ))

    ctx = orchestrator["calls"][0]["pipeline_ctx"]
    assert ctx.model == "claude-opus-4-5"
    assert ctx.classify_model == "claude-haiku-4-5"
    assert ctx.categories == ["concept"]
    assert ctx.workers == 3


def test_pipeline_input_loads_each_items_extraction_from_disk(
        kb_dir, fresh_context, orchestrator, indexers):
    """D1: the item names a document; the extraction comes off disk."""
    store = KBStore(kb_dir)
    exl.persist(store, "raw/a.md", ExtractionResult(summary="from disk"),
                source_checksum="0" * 16, extract_model="m")
    items = [{"content_hash": "h1", "source_ref": "raw/a.md"}]

    _entry.run_server_pipeline_with_input(payload(kb_dir, items=items))

    forwarded = orchestrator["calls"][0]["items"]
    assert len(forwarded) == 1
    assert forwarded[0]["content_hash"] == "h1"
    assert forwarded[0]["source_ref"] == "raw/a.md"
    assert forwarded[0]["extraction"]["summary"] == "from disk"


def test_pipeline_input_reports_an_item_with_no_extraction_and_drops_it(
        kb_dir, fresh_context, orchestrator, indexers):
    items = [{"content_hash": "h1", "source_ref": "raw/gone.md"}]
    events: list[dict] = []

    results = _entry.run_server_pipeline_with_input(
        payload(kb_dir, items=items), emit=events.append)

    assert orchestrator["calls"][0]["items"] == []
    assert results[0]["status"] == "error"
    assert "no usable extraction" in results[0]["error"]
    assert results[0]["phase"] == "extract"
    assert events == [results[0]]


def test_pipeline_input_returns_the_orchestrator_results(
        kb_dir, fresh_context, orchestrator, indexers):
    orchestrator["results"] = [{"content_hash": "h1", "status": "ok"}]

    results = _entry.run_server_pipeline_with_input(payload(kb_dir))

    assert results == [{"content_hash": "h1", "status": "ok"}]


def test_pipeline_input_forwards_the_emit_callback(
        kb_dir, fresh_context, orchestrator, indexers):
    def emit(event):
        pass

    _entry.run_server_pipeline_with_input(payload(kb_dir), emit=emit)

    assert orchestrator["calls"][0]["pipeline_ctx"].emit is emit


@pytest.mark.parametrize("missing", ["kb_dir", "items"])
def test_pipeline_input_requires_the_mandatory_fields(
        kb_dir, fresh_context, orchestrator, indexers, missing):
    data = payload(kb_dir)
    del data[missing]

    with pytest.raises(KeyError, match=missing):
        _entry.run_server_pipeline_with_input(data)


# ── run_server_pipeline_with_input: index refresh ───────────────────

def test_pipeline_input_refreshes_both_indices_once(
        kb_dir, fresh_context, orchestrator, indexers):
    people_cfg = [{"canonical": "Alice", "aliases": ["alice"]}]

    _entry.run_server_pipeline_with_input(
        payload(kb_dir, topic_index_min_articles=7, people=people_cfg))

    assert indexers["index"] == [{"base_dir": str(KBStore(kb_dir).base_dir),
                                  "min_articles": 7,
                                  "summary_max_chars": SUMMARY_MAX_CHARS}]
    assert indexers["people"][0]["cfg"] == people_cfg


@pytest.mark.parametrize("raw", [None, 0, "5"])
def test_pipeline_input_normalises_the_topic_index_threshold(
        kb_dir, fresh_context, orchestrator, indexers, raw):
    _entry.run_server_pipeline_with_input(payload(kb_dir, topic_index_min_articles=raw))

    expected = 5 if raw == "5" else 3
    assert indexers["index"][0]["min_articles"] == expected


def test_pipeline_input_defaults_the_people_config_to_empty(
        kb_dir, fresh_context, orchestrator, indexers):
    _entry.run_server_pipeline_with_input(payload(kb_dir, people=None))

    assert indexers["people"][0]["cfg"] == []


def test_pipeline_input_skips_the_index_refresh_when_the_pipeline_fails(
        kb_dir, fresh_context, monkeypatch, indexers):
    def boom(pipeline_ctx, items):
        raise RuntimeError("boom")

    monkeypatch.setattr(_entry, "run_pipeline_orchestrated", boom)

    with pytest.raises(RuntimeError, match="boom"):
        _entry.run_server_pipeline_with_input(payload(kb_dir))

    assert indexers["index"] == []


# ── run_server_pipeline: stdin/stdout bridge ────────────────────────

def test_pipeline_bridge_reads_stdin_and_prints_an_ok_envelope(
        kb_dir, fresh_context, monkeypatch, capsys):
    captured: list[dict] = []

    def fake_core(input_data, emit=None, cancel_event=None):
        captured.append(input_data)
        return [{"content_hash": "h1", "status": "ok"}]

    monkeypatch.setattr(_entry, "run_server_pipeline_with_input", fake_core)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload(kb_dir, workers=2))))

    _entry.run_server_pipeline()

    assert captured[0]["kb_dir"] == kb_dir
    assert captured[0]["workers"] == 2

    resp = json.loads(capsys.readouterr().out)
    assert resp["ok"] is True
    assert resp["data"]["results"] == [{"content_hash": "h1", "status": "ok"}]
    assert "total_cost_usd" in resp["data"]["cost"]


def test_pipeline_bridge_rejects_malformed_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

    with pytest.raises(json.JSONDecodeError):
        _entry.run_server_pipeline()


# ── run_server_index_with_input ─────────────────────────────────────

def test_index_input_counts_the_wiki_articles(kb_dir, fresh_context):
    write_article(kb_dir, "wiki/concept/a.md", "A")
    write_article(kb_dir, "wiki/project/nested/b.md", "B")

    result = _entry.run_server_index_with_input({"kb_dir": kb_dir})

    assert result == {"indexed": 2}


def test_index_input_reports_zero_when_there_is_no_wiki_dir(kb_dir, fresh_context):
    result = _entry.run_server_index_with_input({"kb_dir": kb_dir})

    assert result == {"indexed": 0}


def test_index_input_actually_writes_the_master_index(kb_dir, fresh_context):
    write_article(kb_dir, "wiki/concept/a.md", "Alpha")

    _entry.run_server_index_with_input({"kb_dir": kb_dir})

    index = (KBStore(kb_dir).index_dir / "master-index.md").read_text()
    assert "[Alpha](wiki/concept/a.md)" in index


def test_index_input_forwards_the_threshold_and_people_config(kb_dir, fresh_context, indexers):
    people_cfg = [{"canonical": "Alice", "aliases": ["alice"]}]

    _entry.run_server_index_with_input({
        "kb_dir": kb_dir, "topic_index_min_articles": 9, "people": people_cfg,
    })

    assert indexers["index"][0]["min_articles"] == 9
    assert indexers["people"][0]["cfg"] == people_cfg


@pytest.mark.parametrize("raw", [None, 0])
def test_index_input_defaults_the_threshold_to_three(kb_dir, fresh_context, indexers, raw):
    _entry.run_server_index_with_input({"kb_dir": kb_dir, "topic_index_min_articles": raw})

    assert indexers["index"][0]["min_articles"] == 3


def test_index_input_forwards_the_summary_budget(kb_dir, fresh_context, indexers):
    _entry.run_server_index_with_input({"kb_dir": kb_dir, "summary_max_chars": 220})

    assert indexers["index"][0]["summary_max_chars"] == 220


@pytest.mark.parametrize("raw", [None, 0])
def test_index_input_defaults_the_summary_budget(kb_dir, fresh_context, indexers, raw):
    _entry.run_server_index_with_input({"kb_dir": kb_dir, "summary_max_chars": raw})

    assert indexers["index"][0]["summary_max_chars"] == SUMMARY_MAX_CHARS


def test_index_input_requires_kb_dir(fresh_context):
    with pytest.raises(KeyError, match="kb_dir"):
        _entry.run_server_index_with_input({})


# ── run_server_index: stdin/stdout bridge ───────────────────────────

def test_index_bridge_reads_stdin_and_prints_an_ok_envelope(
        kb_dir, fresh_context, monkeypatch, capsys):
    write_article(kb_dir, "wiki/concept/a.md", "A")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"kb_dir": kb_dir})))

    _entry.run_server_index()

    resp = json.loads(capsys.readouterr().out)
    assert resp == {"ok": True, "data": {"indexed": 1}}


def test_index_bridge_rejects_malformed_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{"))

    with pytest.raises(json.JSONDecodeError):
        _entry.run_server_index()
