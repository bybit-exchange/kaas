"""Tests for kb_ai.core.classify — verifies new import paths and basic logic."""
from __future__ import annotations

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.classify import (
    classify_article,
    classify_cache_key,
    dedup_create_new,
    hash_existing_articles,
    _title_words,
)
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import ArticleMeta


def test_classify_importable_from_core():
    """classify_article is importable from kb_ai.core.classify."""
    assert callable(classify_article)


def test_title_words():
    """_title_words extracts lowercase word set from a title."""
    words = _title_words("Hello World-Test")
    assert "hello" in words
    assert "worldtest" in words


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
