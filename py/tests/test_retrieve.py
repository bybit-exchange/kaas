"""Offline tests for LLM-iterative retrieval (kb_ai.retrieve) and its wiring
into the chat core. The only non-deterministic piece — the LLM select call and
the streaming completion — is monkeypatched, so these run without network.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kb_ai.retrieval import retrieve
from kb_ai.storage.store import KBStore


# ── fixtures ────────────────────────────────────────────────────────

def _make_kb(tmp_path: Path, articles: dict[str, str], index: str | None = None) -> str:
    """Build a KB dir with wiki articles and (optionally) a master-index."""
    store = KBStore(str(tmp_path))
    for rel, body in articles.items():
        store.write_article(rel, body)
    if index is not None:
        store.index_dir.mkdir(parents=True, exist_ok=True)
        (store.index_dir / "master-index.md").write_text(index)
    return str(tmp_path)


# ── _select_relevant ────────────────────────────────────────────────

def test_select_filters_to_existing_paths(monkeypatch):
    catalog = [
        retrieve.ArticleMeta("One", "wiki/one.md", "first"),
        retrieve.ArticleMeta("Two", "wiki/two.md", "second"),
    ]
    monkeypatch.setattr(retrieve, "completion_json",
                        lambda **kw: {"paths": ["wiki/two.md", "wiki/ghost.md"]})
    out = retrieve._select_relevant(catalog, "q", "m", max_select=6)
    assert out == ["wiki/two.md"]   # ghost filtered out


def test_select_empty_catalog_skips_llm(monkeypatch):
    called = False

    def boom(**kw):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(retrieve, "completion_json", boom)
    assert retrieve._select_relevant([], "q", "m", max_select=6) == []
    assert not called


def test_select_degrades_on_llm_error(monkeypatch):
    catalog = [retrieve.ArticleMeta("One", "wiki/one.md", "x")]

    def boom(**kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(retrieve, "completion_json", boom)
    assert retrieve._select_relevant(catalog, "q", "m", max_select=6) == []


# ── _strip_frontmatter ──────────────────────────────────────────────

def test_strip_frontmatter():
    assert retrieve._strip_frontmatter("---\ntitle: X\n---\nbody here") == "body here"
    assert retrieve._strip_frontmatter("no frontmatter") == "no frontmatter"


# ── iterative_retrieve ──────────────────────────────────────────────

def test_iterative_selects_reads_ranks_and_caps(tmp_path: Path, monkeypatch):
    index = (
        "# Index\n"
        "- [Alpha](wiki/alpha.md) — about workers\n"
        "- [Beta](wiki/beta.md) — about queues\n"
        "- [Gamma](wiki/gamma.md) — about leases\n"
    )
    kb = _make_kb(tmp_path, {
        "wiki/alpha.md": "---\ntitle: Alpha\n---\nworker content",
        "wiki/beta.md": "queue content",
        "wiki/gamma.md": "lease content",
    }, index=index)

    # LLM ranks beta first, then alpha; gamma not selected.
    monkeypatch.setattr(retrieve, "completion_json",
                        lambda **kw: {"paths": ["wiki/beta.md", "wiki/alpha.md"]})

    arts = retrieve.iterative_retrieve("worker pool", kb, model="m", max_articles=5)
    paths = [a["path"] for a in arts]

    assert paths == ["wiki/beta.md", "wiki/alpha.md"]   # selection order preserved
    # title comes from the index meta.
    assert arts[0]["title"] == "Beta"
    # frontmatter stripped on alpha (which had one).
    alpha = next(a for a in arts if a["path"] == "wiki/alpha.md")
    assert not alpha["content"].startswith("---")
    assert alpha["content"].strip() == "worker content"


def test_iterative_caps_at_max_articles(tmp_path: Path, monkeypatch):
    index = "# Index\n" + "".join(
        f"- [A{i}](wiki/a{i}.md) — x\n" for i in range(5))
    kb = _make_kb(tmp_path, {f"wiki/a{i}.md": f"body {i}" for i in range(5)}, index=index)
    monkeypatch.setattr(retrieve, "completion_json",
                        lambda **kw: {"paths": [f"wiki/a{i}.md" for i in range(5)]})
    arts = retrieve.iterative_retrieve("q", kb, model="m", max_articles=2)
    assert len(arts) == 2


def test_iterative_no_index_returns_empty(tmp_path: Path, monkeypatch):
    # Without a master-index there is no catalog to navigate; the LLM must not
    # even be called, and retrieval yields nothing.
    kb = _make_kb(tmp_path, {"wiki/a.md": "dispatcher"})  # no master-index
    monkeypatch.setattr(retrieve, "completion_json",
                        lambda **kw: pytest.fail("LLM should not be called without a catalog"))
    assert retrieve.iterative_retrieve("dispatcher", kb, model="m") == []


def test_iterative_truncates_long_article(tmp_path: Path, monkeypatch):
    big = "worker " * 10000  # well over MAX_ARTICLE_CHARS
    kb = _make_kb(tmp_path, {"wiki/big.md": big},
                  index="# Index\n- [Big](wiki/big.md) — x\n")
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {"paths": ["wiki/big.md"]})
    arts = retrieve.iterative_retrieve("worker", kb, model="m")
    assert len(arts[0]["content"]) <= retrieve.MAX_ARTICLE_CHARS


# ── _run_chat_core integration (fake LLM stream) ─────────────────────

def _fake_stream_chunks():
    """Delta chunks (one carrying a citation link) then a usage-only chunk,
    mimicking the OpenAI streaming response."""
    delta = lambda c: SimpleNamespace(  # noqa: E731
        choices=[SimpleNamespace(delta=SimpleNamespace(content=c))], usage=None)
    usage = SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                              prompt_tokens_details=None),
    )
    return [delta("Workers run the pipeline "),
            delta("[W](wiki/w.md)."), usage]


def test_chat_core_triggers_retrieval_and_emits_sources(tmp_path: Path, monkeypatch):
    from kb_ai.commands import chat as server_chat

    kb = _make_kb(tmp_path, {"wiki/w.md": "worker pool details"},
                  index="# Index\n- [W](wiki/w.md) — workers\n")

    # Exercise the REAL iterative_retrieve over real files; only the LLM
    # select call is stubbed.
    import kb_ai.retrieval.retrieve as r
    monkeypatch.setattr(r, "completion_json", lambda **kw: {"paths": ["wiki/w.md"]})

    # Fake the streaming client so no network/LLM is hit.
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: iter(_fake_stream_chunks()))
        )
    )
    import kb_ai.commands.chat as _chat_mod
    monkeypatch.setattr(_chat_mod, "get_client", lambda: fake_client)
    server_chat._reset_cache_state()

    events: list[dict] = []
    server_chat._run_chat_core(
        {"query": "how do workers run?", "kb_dir": kb, "model": "m"},
        events.append,
    )

    types = [e["type"] for e in events]
    assert "status" in types          # retrieval status event emitted
    assert "done" in types
    status = next(e for e in events if e["type"] == "status")
    assert status["sources"] == [{"title": "W", "path": "wiki/w.md"}]
    done = next(e for e in events if e["type"] == "done")
    assert done["retrieved_sources"] == [{"title": "W", "path": "wiki/w.md"}]
    # Citation extraction ran end to end: the [W](wiki/w.md) link in the answer
    # intersects the retrieved paths.
    assert done["cited_sources"] == [{"title": "W", "path": "wiki/w.md"}]
    # The streamed answer text came through as deltas.
    answer = "".join(e["content"] for e in events if e["type"] == "delta")
    assert answer == "Workers run the pipeline [W](wiki/w.md)."
