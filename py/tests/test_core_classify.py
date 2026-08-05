"""Tests for kb_ai.core.classify — verifies new import paths and basic logic."""
from __future__ import annotations

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.classify import (
    CATEGORY_DEFINITIONS,
    DEFAULT_CATEGORIES,
    category_definitions_block,
    classify_article,
    classify_cache_key,
    classify_inputs_hash,
    dedup_create_new,
    hash_existing_articles,
    _title_words,
)
from kb_ai.core.extract import ExtractionResult
from kb_ai import prompts as prompts_module
from kb_ai.prompts import default_registry
from kb_ai.storage.store import ArticleMeta


def test_classify_importable_from_core():
    """classify_article is importable from kb_ai.core.classify."""
    assert callable(classify_article)


def test_title_words():
    """_title_words extracts lowercase word set from a title."""
    words = _title_words("Hello World-Test")
    assert "hello" in words
    assert "worldtest" in words


def test_default_categories_hold_the_measured_six():
    """The default menu is the six measured in docs/classify-taxonomy-measurements.md.

    `reference` and `guide` were absent from the original four despite taking the
    right documents; `person` is retained for core/people.py even though a
    docs-only corpus never selects it.
    """
    assert DEFAULT_CATEGORIES == [
        "concept", "decision", "project", "reference", "guide", "person",
    ]
    # categories[0] is substituted into the prompt's example path, so the first
    # entry has to be a real category name.
    assert DEFAULT_CATEGORIES[0] in CATEGORY_DEFINITIONS


def test_every_default_category_has_a_definition():
    """A default category without a definition would leave the model guessing."""
    missing = [c for c in DEFAULT_CATEGORIES if c not in CATEGORY_DEFINITIONS]
    assert missing == []


def test_definitions_block_covers_only_known_categories():
    """A custom menu gets no definitions rather than wrong ones."""
    block = category_definitions_block(["concept", "sprint", "okr"])
    assert "concept:" in block
    assert "sprint" not in block and "okr" not in block


def test_definitions_block_is_empty_for_a_wholly_custom_menu():
    """Nothing is injected when no active category has a known definition."""
    assert category_definitions_block(["sprint", "okr"]) == ""


def test_classify_prompt_renders_the_definitions():
    """The rendered prompt carries the definitions and keeps its placeholder."""
    rendered = default_registry().get("classify").render(
        categories_str=", ".join(DEFAULT_CATEGORIES),
        categories=DEFAULT_CATEGORIES,
        category_definitions=category_definitions_block(DEFAULT_CATEGORIES),
    )
    assert "Category definitions" in rendered
    assert CATEGORY_DEFINITIONS["project"] in rendered
    assert "{ARTICLES_PLACEHOLDER}" in rendered


def test_dedup_create_new_no_overlap():
    """dedup_create_new keeps items with no title overlap."""
    classification = ClassificationResult(
        create_new=[CreateTarget(title="Brand New Topic", path="wiki/concept/new.md")],
        merge_into=[],
    )
    existing = [ArticleMeta(title="Unrelated", path="wiki/concept/old.md")]
    result = dedup_create_new(classification, existing)
    assert len(result.create_new) == 1
    assert result.create_new[0].title == "Brand New Topic"


def test_hash_existing_articles_deterministic():
    """hash_existing_articles produces consistent hash for same input."""
    articles = [
        ArticleMeta(title="A", path="wiki/a.md", summary="x"),
        ArticleMeta(title="B", path="wiki/b.md", summary="y"),
    ]
    h1 = hash_existing_articles(articles)
    h2 = hash_existing_articles(articles)
    assert h1 == h2
    assert len(h1) == 12


def test_classify_cache_key_format():
    """classify_cache_key joins components with dashes."""
    key = classify_cache_key("abc123", "art456", "cat789")
    assert key == "abc123-art456-cat789"


# ── classify_inputs_hash: what must move the cache ──────────────────

def test_inputs_hash_is_stable_for_the_same_categories():
    assert classify_inputs_hash(["concept"]) == classify_inputs_hash(["concept"])


def test_inputs_hash_moves_when_the_category_list_changes():
    assert classify_inputs_hash(["concept"]) != classify_inputs_hash(["concept", "guide"])


def test_inputs_hash_treats_an_empty_category_list_as_the_defaults():
    """compile_kb passes categories=None and hashed it as `[]`, but
    classify_article falls back to the defaults -- so the old key described a run
    that never happened. Both falsy forms must hash as the defaults."""
    assert classify_inputs_hash(None) == classify_inputs_hash(DEFAULT_CATEGORIES)
    assert classify_inputs_hash([]) == classify_inputs_hash(DEFAULT_CATEGORIES)


def test_inputs_hash_moves_when_the_prompt_text_changes(monkeypatch, tmp_path):
    """Editing classify.md must invalidate the cache. Without this, a prompt-only
    edit leaves every cached classification in place and the edit does nothing."""
    before = classify_inputs_hash(["concept"])

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    original = default_registry().get("classify").content
    (prompts_dir / "classify.md").write_text(
        original + "\nAn extra instruction that changes the model's behaviour.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setattr(prompts_module, "_registry", None)

    assert classify_inputs_hash(["concept"]) != before


def test_inputs_hash_moves_when_a_category_definition_changes(monkeypatch):
    """The definitions live in code, not in the prompt file, and the old
    categories-only hash could not see an edit to them."""
    before = classify_inputs_hash(["concept"])
    monkeypatch.setitem(CATEGORY_DEFINITIONS, "concept", "a completely different meaning")

    assert classify_inputs_hash(["concept"]) != before
