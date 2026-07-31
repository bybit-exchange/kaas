"""Tests for the retrieval bridge entrypoint and the article-reading paths.

Covers kb_ai.retrieval.query.run_query (stdin -> JSON stdout) and the
kb_ai.retrieval.retrieve helpers that degrade on bad LLM output or unreadable
files. No network: completion / completion_json are monkeypatched.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from kb_ai.retrieval import query, retrieve
from kb_ai.storage.store import ArticleMeta, KBStore


def _feed_stdin(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def _make_kb(tmp_path: Path, articles: dict[str, str], index: str | None = None) -> str:
    store = KBStore(str(tmp_path))
    for rel, body in articles.items():
        store.write_article(rel, body)
    if index is not None:
        store.index_dir.mkdir(parents=True, exist_ok=True)
        (store.index_dir / "master-index.md").write_text(index, encoding="utf-8")
    return str(tmp_path)


# ── run_query (bridge entrypoint) ───────────────────────────────────

def test_run_query_answers_from_stdin_and_prints_ok_envelope(monkeypatch, capsys):
    monkeypatch.setattr(query, "completion", lambda **kw: "The answer.")
    _feed_stdin(monkeypatch, {
        "question": "what is kaas?",
        "articles": [{"title": "One", "path": "wiki/one.md", "content": "kaas is a platform"}],
    })

    query.run_query()

    resp = json.loads(capsys.readouterr().out.strip())
    assert resp["ok"] is True
    assert resp["data"]["answer"] == "The answer."
    assert resp["data"]["sources"] == [{"title": "One", "path": "wiki/one.md"}]


def test_run_query_attaches_cost_summary(monkeypatch, capsys):
    monkeypatch.setattr(query, "completion", lambda **kw: "answer")
    _feed_stdin(monkeypatch, {"question": "q", "articles": []})

    query.run_query()

    cost = json.loads(capsys.readouterr().out.strip())["data"]["cost"]
    assert set(cost) >= {"total_cost_usd", "calls", "total_prompt_tokens"}


def test_run_query_keeps_stdout_to_one_json_line(monkeypatch, capsys):
    """Diagnostics (RAG size, cost summary) go to stderr; the Go bridge parses
    stdout, so it must stay exactly one JSON line."""
    monkeypatch.setattr(query, "completion", lambda **kw: "answer")
    _feed_stdin(monkeypatch, {"question": "q", "articles": []})

    query.run_query()
    captured = capsys.readouterr()

    assert len(captured.out.strip().splitlines()) == 1
    assert json.loads(captured.out.strip())["ok"] is True
    assert "[RAG]" in captured.err
    assert "[RAG]" not in captured.out


def test_run_query_defaults_the_model(monkeypatch, capsys):
    seen: dict = {}

    def fake(*, model, messages, **kw):
        seen["model"] = model
        return "answer"

    monkeypatch.setattr(query, "completion", fake)
    _feed_stdin(monkeypatch, {"question": "q", "articles": []})

    query.run_query()
    capsys.readouterr()

    assert seen["model"] == "claude-opus-4-6"


def test_run_query_honors_model_from_input(monkeypatch, capsys):
    seen: dict = {}

    def fake(*, model, messages, **kw):
        seen["model"] = model
        return "answer"

    monkeypatch.setattr(query, "completion", fake)
    _feed_stdin(monkeypatch, {"question": "q", "articles": [], "model": "claude-haiku-4-6"})

    query.run_query()
    capsys.readouterr()

    assert seen["model"] == "claude-haiku-4-6"


def test_run_query_requires_a_question(monkeypatch):
    _feed_stdin(monkeypatch, {"articles": []})

    with pytest.raises(KeyError, match="question"):
        query.run_query()


def test_run_query_rejects_invalid_json_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

    with pytest.raises(json.JSONDecodeError):
        query.run_query()


# ── _select_relevant: malformed LLM payloads ────────────────────────

def test_select_returns_empty_when_paths_key_missing(monkeypatch):
    catalog = [ArticleMeta("One", "wiki/one.md", "x")]
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {"answer": "oops"})

    assert retrieve._select_relevant(catalog, "q", "m", max_select=6) == []


def test_select_returns_empty_when_paths_is_not_a_list(monkeypatch):
    catalog = [ArticleMeta("One", "wiki/one.md", "x")]
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {"paths": "wiki/one.md"})

    assert retrieve._select_relevant(catalog, "q", "m", max_select=6) == []


def test_select_returns_empty_when_result_is_not_a_dict(monkeypatch):
    catalog = [ArticleMeta("One", "wiki/one.md", "x")]
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: ["wiki/one.md"])

    assert retrieve._select_relevant(catalog, "q", "m", max_select=6) == []


def test_select_drops_non_string_and_duplicate_paths(monkeypatch):
    catalog = [ArticleMeta("One", "wiki/one.md", "x"), ArticleMeta("Two", "wiki/two.md", "y")]
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {
        "paths": [None, "wiki/one.md", 42, "wiki/one.md", "wiki/two.md"]})

    assert retrieve._select_relevant(catalog, "q", "m", max_select=6) == [
        "wiki/one.md", "wiki/two.md"]


def test_select_sends_the_catalog_and_question_to_the_llm(monkeypatch):
    catalog = [ArticleMeta("One", "wiki/one.md", "first summary")]
    seen: dict = {}

    def fake(**kw):
        seen["prompt"] = kw["messages"][0]["content"]
        return {"paths": []}

    monkeypatch.setattr(retrieve, "completion_json", fake)
    retrieve._select_relevant(catalog, "how do workers run?", "m", max_select=3)

    assert "wiki/one.md — One: first summary" in seen["prompt"]
    assert "how do workers run?" in seen["prompt"]
    assert "up to 3 article" in seen["prompt"]


# ── _strip_frontmatter edge cases ───────────────────────────────────

def test_strip_frontmatter_keeps_unterminated_block():
    content = "---\ntitle: X\nno closing fence"
    assert retrieve._strip_frontmatter(content) == content


def test_strip_frontmatter_keeps_horizontal_rule_in_body():
    """A '---' divider mid-body must not be mistaken for frontmatter."""
    content = "# Title\n\nintro\n\n---\n\nmore"
    assert retrieve._strip_frontmatter(content) == content


def test_strip_frontmatter_drops_leading_blank_lines_after_fence():
    assert retrieve._strip_frontmatter("---\ntitle: X\n---\n\n\nbody") == "body"


# ── _read_selected / read_articles ──────────────────────────────────

def test_read_selected_skips_non_string_paths(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/a.md": "alpha body"})
    store = KBStore(kb, read_only=True)

    arts = retrieve._read_selected(store, {}, [None, "wiki/a.md", 7])

    assert [a["path"] for a in arts] == ["wiki/a.md"]


def test_read_selected_skips_unreadable_paths(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/a.md": "alpha body"})
    store = KBStore(kb, read_only=True)

    arts = retrieve._read_selected(store, {}, ["wiki/ghost.md", "wiki/a.md"])

    assert [a["path"] for a in arts] == ["wiki/a.md"]


def test_read_selected_skips_a_directory_path(tmp_path: Path):
    """A path pointing at a directory raises IsADirectoryError (an OSError)."""
    kb = _make_kb(tmp_path, {"wiki/a.md": "alpha body"})
    store = KBStore(kb, read_only=True)

    assert retrieve._read_selected(store, {}, ["wiki"]) == []


def test_read_articles_returns_titles_from_the_index(tmp_path: Path):
    kb = _make_kb(
        tmp_path,
        {"wiki/alpha.md": "---\ntitle: Alpha\n---\nworker content"},
        index="# Index\n- [Alpha](wiki/alpha.md) — about workers\n",
    )

    arts = retrieve.read_articles(["wiki/alpha.md"], kb)

    assert arts == [{"title": "Alpha", "path": "wiki/alpha.md",
                     "content": "worker content"}]


def test_read_articles_falls_back_to_filename_title_without_index(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/people/grace.md": "profile body"})

    arts = retrieve.read_articles(["wiki/people/grace.md"], kb)

    assert arts[0]["title"] == "grace"
    assert arts[0]["content"] == "profile body"


def test_read_articles_preserves_caller_order(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/a.md": "a", "wiki/b.md": "b"})

    arts = retrieve.read_articles(["wiki/b.md", "wiki/a.md"], kb)

    assert [a["path"] for a in arts] == ["wiki/b.md", "wiki/a.md"]


def test_read_articles_truncates_at_max_article_chars(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/big.md": "worker " * 5000})

    arts = retrieve.read_articles(["wiki/big.md"], kb)

    assert len(arts[0]["content"]) == retrieve.MAX_ARTICLE_CHARS


def test_read_articles_with_empty_paths_makes_no_reads(tmp_path: Path, monkeypatch):
    kb = _make_kb(tmp_path, {"wiki/a.md": "a"})
    monkeypatch.setattr(KBStore, "read_article",
                        lambda self, p: pytest.fail("should not read anything"))

    assert retrieve.read_articles([], kb) == []


def test_read_articles_skips_missing_files_without_raising(tmp_path: Path):
    kb = _make_kb(tmp_path, {"wiki/a.md": "a body"})

    arts = retrieve.read_articles(["wiki/gone.md", "wiki/a.md", "wiki/also-gone.md"], kb)

    assert [a["path"] for a in arts] == ["wiki/a.md"]


def test_iterative_retrieve_returns_empty_when_llm_selects_nothing(tmp_path: Path,
                                                                  monkeypatch):
    kb = _make_kb(tmp_path, {"wiki/a.md": "body"},
                  index="# Index\n- [A](wiki/a.md) — x\n")
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {"paths": []})

    assert retrieve.iterative_retrieve("q", kb, model="m") == []


def test_iterative_retrieve_returns_empty_when_llm_output_is_garbage(tmp_path: Path,
                                                                    monkeypatch):
    kb = _make_kb(tmp_path, {"wiki/a.md": "body"},
                  index="# Index\n- [A](wiki/a.md) — x\n")
    monkeypatch.setattr(retrieve, "completion_json", lambda **kw: {"paths": {"a": 1}})

    assert retrieve.iterative_retrieve("q", kb, model="m") == []


def test_iterative_retrieve_skips_indexed_articles_that_vanished(tmp_path: Path,
                                                                monkeypatch):
    """The index can outlive the file; retrieval must degrade, not crash."""
    kb = _make_kb(tmp_path, {"wiki/a.md": "a body"},
                  index="# Index\n- [A](wiki/a.md) — x\n- [B](wiki/b.md) — y\n")
    monkeypatch.setattr(retrieve, "completion_json",
                        lambda **kw: {"paths": ["wiki/b.md", "wiki/a.md"]})

    arts = retrieve.iterative_retrieve("q", kb, model="m")

    assert [a["path"] for a in arts] == ["wiki/a.md"]


def test_read_articles_skips_an_escaping_path_but_keeps_the_good_ones(tmp_path: Path, capsys):
    """paths arrives from the MCP ask tool's client-controlled argument. One bad
    entry must not discard the articles that did resolve, and the escape must be
    reported on stderr rather than to the caller."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (tmp_path / "secret.md").write_text("TOPSECRET", encoding="utf-8")
    store = KBStore(str(kb))
    store.write_article("wiki/good.md", "---\ntitle: Good\n---\ngood body")

    articles = retrieve.read_articles(["../secret.md", "wiki/good.md"], str(kb))

    assert [a["path"] for a in articles] == ["wiki/good.md"]
    assert "TOPSECRET" not in json.dumps(articles)
    assert "escapes kb_dir" in capsys.readouterr().err
