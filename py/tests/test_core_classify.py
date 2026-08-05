"""Tests for kb_ai.core.classify — verifies new import paths and basic logic."""
from __future__ import annotations

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.classify import (
    CATEGORY_DEFINITIONS,
    DEFAULT_CATEGORIES,
    category_definitions_block,
    classify_article,
    classify_cache_key,
    dedup_create_new,
    hash_existing_articles,
    _title_words,
)
from kb_ai.core.extract import ExtractionResult
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
