"""Offline tests for RAG answering (kb_ai.retrieval.query).

The completion() call is monkeypatched, so these run without network. The
assertions focus on what actually reaches the model: the full article bodies as
grounding context, and the citation instructions.
"""
from __future__ import annotations

import pytest

from kb_ai.retrieval import query


def _fake_completion(reply: str, capture: dict | None = None):
    def fake(*, model, messages, **kwargs):
        if capture is not None:
            capture["model"] = model
            capture["messages"] = messages
            capture.update(kwargs)
        return reply

    return fake


# ── _assemble_article_context ───────────────────────────────────────

def test_assemble_context_includes_title_path_and_body():
    out = query._assemble_article_context([
        {"title": "One", "path": "wiki/one.md", "content": "first body"},
    ])
    assert out == "### One (/wiki/one.md)\nfirst body"


def test_assemble_context_joins_articles_with_blank_line():
    out = query._assemble_article_context([
        {"title": "One", "path": "wiki/one.md", "content": "a"},
        {"title": "Two", "path": "wiki/two.md", "content": "b"},
    ])
    assert out == "### One (/wiki/one.md)\na\n\n### Two (/wiki/two.md)\nb"


def test_assemble_context_tolerates_missing_content():
    out = query._assemble_article_context([{"title": "One", "path": "wiki/one.md"}])
    assert out == "### One (/wiki/one.md)\n"


def test_assemble_context_slashes_the_path_only_once():
    """A stored path already carrying a leading slash must not become `//wiki/...`."""
    out = query._assemble_article_context([{"title": "One", "path": "/wiki/one.md"}])
    assert out == "### One (/wiki/one.md)\n"


def test_assemble_context_empty():
    assert query._assemble_article_context([]) == ""


# ── answer_question ─────────────────────────────────────────────────

def test_answer_question_returns_answer_and_sources(monkeypatch):
    monkeypatch.setattr(query, "completion", _fake_completion("  The answer.  "))

    out = query.answer_question("what is kaas?", [
        {"title": "One", "path": "wiki/one.md", "content": "kaas is a platform"},
        {"title": "Two", "path": "wiki/two.md", "content": "more detail"},
    ])

    assert out["answer"] == "The answer."   # surrounding whitespace stripped
    assert out["sources"] == [
        {"title": "One", "path": "wiki/one.md"},
        {"title": "Two", "path": "wiki/two.md"},
    ]


def test_answer_question_grounds_prompt_in_article_bodies(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(query, "completion", _fake_completion("ok", capture))

    query.answer_question("what is kaas?", [
        {"title": "One", "path": "wiki/one.md", "content": "kaas is a platform"},
    ], model="claude-opus-4-6")

    system = capture["messages"][0]["content"]
    assert "kaas is a platform" in system
    assert "<knowledge>" in system and "</knowledge>" in system
    assert "Cite sources" in system
    assert capture["messages"][1] == {"role": "user", "content": "what is kaas?"}
    assert capture["model"] == "claude-opus-4-6"


def test_answer_question_with_no_articles(monkeypatch):
    monkeypatch.setattr(query, "completion",
                        _fake_completion("I don't have enough information."))

    out = query.answer_question("anything?", [])

    assert out["sources"] == []
    assert out["answer"] == "I don't have enough information."


def test_answer_question_sources_drop_content(monkeypatch):
    """Sources are returned to the client, so bodies must not ride along."""
    monkeypatch.setattr(query, "completion", _fake_completion("ok"))

    out = query.answer_question("q", [
        {"title": "One", "path": "wiki/one.md", "content": "secret body"},
    ])

    assert out["sources"] == [{"title": "One", "path": "wiki/one.md"}]
    assert "content" not in out["sources"][0]


def test_answer_question_propagates_llm_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(query, "completion", boom)

    with pytest.raises(RuntimeError, match="llm down"):
        query.answer_question("q", [{"title": "One", "path": "wiki/one.md", "content": "x"}])


def test_answer_question_logs_context_size_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(query, "completion", _fake_completion("ok"))

    query.answer_question("q", [{"title": "One", "path": "wiki/one.md", "content": "body"}])

    err = capsys.readouterr().err
    assert "[RAG] 1 full articles" in err
