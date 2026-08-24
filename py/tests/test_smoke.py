"""Offline smoke tests for the migrated KaaS AI engine.

Covers the pieces that don't require an LLM or network: prompt registry
loading + render escaping, the chunker, the file store, and merge diff
application.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kb_ai.core.classify import category_definitions_block
from kb_ai.prompts import default_registry
from kb_ai.storage.store import KBStore, ArticleMeta


# ── Prompt registry ────────────────────────────────────────────────

ALL_PROMPTS = [
    "extract", "extract-types", "summarize", "merge-summaries",
    "classify", "merge-rewrite", "merge-diff",
    "chat-with-sources", "chat-no-sources", "rewrite", "suggest",
]


@pytest.mark.parametrize("name", ALL_PROMPTS)
def test_default_registry_loads_all_prompts(name):
    inst = default_registry().get(name)
    assert inst.content.strip(), f"prompt {name} is empty"


def test_classify_render_then_replace_pipeline():
    """classify.py renders with categories then substitutes ARTICLES_PLACEHOLDER.

    Verifies the format-escaping survives so the placeholder stays intact and
    category substitution works (the critical MySQL→file migration contract).
    """
    cats = ["concept", "project", "decision", "person"]
    rendered = default_registry().get("classify").render(
        categories_str=", ".join(cats), categories=cats,
        category_definitions=category_definitions_block(cats),
    )
    assert "{ARTICLES_PLACEHOLDER}" in rendered
    assert "wiki/concept/" in rendered  # categories[0] substituted
    final = rendered.replace("{ARTICLES_PLACEHOLDER}", "[]")
    assert "{ARTICLES_PLACEHOLDER}" not in final


def test_registry_unknown_prompt_raises():
    from kb_ai.prompts import NoActivePromptError
    with pytest.raises(NoActivePromptError):
        default_registry().get("no-such-prompt-name")


# ── Chunker ────────────────────────────────────────────────────────

def test_chunk_content_splits_long_text():
    from kb_ai.core.extract import chunk_content
    text = "para\n\n" * 5000
    chunks = chunk_content(text)
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)


# ── Store ──────────────────────────────────────────────────────────

def test_store_roundtrip_article(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_article("wiki/concept/foo.md", "# Foo\nbody")
    assert store.read_article("wiki/concept/foo.md") == "# Foo\nbody"


def test_store_read_only_blocks_write(tmp_path: Path):
    store = KBStore(str(tmp_path), read_only=True)
    with pytest.raises(PermissionError):
        store.write_article("wiki/x.md", "x")


def test_store_compile_state_roundtrip(tmp_path: Path):
    store = KBStore(str(tmp_path))
    assert store.load_compile_state() == {}
    store.save_compile_state({"raw/a.md": {"checksum": "abc"}})
    assert store.load_compile_state() == {"raw/a.md": {"checksum": "abc"}}


def test_store_existing_articles_parses_master_index(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.index_dir.mkdir(parents=True, exist_ok=True)
    (store.index_dir / "master-index.md").write_text(
        "# Index\n- [Title One](wiki/concept/one.md) — a summary\n"
        "- [Title Two](wiki/project/two.md) — another\n"
    )
    arts = store.existing_articles()
    assert {a.title for a in arts} == {"Title One", "Title Two"}
    assert {a.path for a in arts} == {"wiki/concept/one.md", "wiki/project/two.md"}


# ── Merge diff application (pure function, no LLM) ──────────────────

def test_apply_diff_appends_to_section():
    from kb_ai.core.merge import _apply_diff
    article = "## Overview\n\nExisting line.\n"
    diff = {"patches": [
        {"action": "append_to_section", "section": "## Overview", "content": "New line."},
    ]}
    out = _apply_diff(article, diff, ["raw/src.md"], "2026-06-20")
    assert "Existing line." in out
    assert "New line." in out
