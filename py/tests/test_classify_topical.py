"""Tests for classify_article_topical() and _render_topical_classify_system()."""
from __future__ import annotations

from unittest.mock import patch

from kb_ai._types import ClassificationResult, MergeTarget
from kb_ai.core.classify import (
    DEFAULT_CATEGORIES,
    _render_topical_classify_system,
    category_definitions_block,
    classify_article_topical,
    effective_categories,
)
from kb_ai.core.extract import ExtractionResult
from kb_ai.prompts import default_registry
from kb_ai.storage.store import ArticleMeta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_PLAN = [
    {
        "path": "wiki/concept/sun-wukong-character-overview.md",
        "type": "concept",
        "title": "Sun Wukong — Character Overview",
        "description": "Covers Sun Wukong's powers, personality, and character arc.",
    },
    {
        "path": "wiki/concept/journey-themes.md",
        "type": "concept",
        "title": "Journey Themes",
        "description": "Recurring moral and spiritual themes across the journey.",
    },
]

_SAMPLE_EXTRACTION = ExtractionResult(
    summary="Sun Wukong defeats the demon king using his shape-shifting powers.",
    topics=["sun wukong", "combat", "shape-shifting"],
    entities=[{"name": "Sun Wukong", "type": "person", "context": "protagonist"}],
    concepts=[],
    decisions=[],
)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def test_topical_template_exists():
    """classify-topical prompt can be loaded from the registry."""
    prompt = default_registry().get("classify-topical")
    assert prompt.content  # non-empty


def test_topical_template_renders_all_variables():
    """All required variables are accepted by the template."""
    rendered = default_registry().get("classify-topical").render(
        topic="Sun Wukong",
        aggregation_plan_json='[{"path": "wiki/concept/test.md"}]',
        categories_str=", ".join(DEFAULT_CATEGORIES),
        categories=DEFAULT_CATEGORIES,
        category_definitions=category_definitions_block(DEFAULT_CATEGORIES),
    )
    assert "Sun Wukong" in rendered
    assert "wiki/concept/test.md" in rendered
    assert "{ARTICLES_PLACEHOLDER}" in rendered


def test_topical_template_has_topic_variable():
    """The rendered prompt contains the topic string."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "Sun Wukong", _SAMPLE_PLAN,
    )
    assert "Sun Wukong" in rendered


def test_topical_template_has_aggregation_plan():
    """The rendered prompt contains the aggregation plan JSON."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "test topic", _SAMPLE_PLAN,
    )
    assert "sun-wukong-character-overview" in rendered
    assert "journey-themes" in rendered


def test_topical_template_has_articles_placeholder():
    """The template keeps {ARTICLES_PLACEHOLDER} for runtime replacement."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "test", _SAMPLE_PLAN,
    )
    assert "{ARTICLES_PLACEHOLDER}" in rendered


def test_topical_template_has_category_definitions():
    """Category definitions are injected into the topical template."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "test", _SAMPLE_PLAN,
    )
    assert "Category definitions" in rendered


def test_topical_template_has_categories_str():
    """The comma-joined category list appears in the prompt."""
    cats = ["concept", "guide"]
    rendered = _render_topical_classify_system(cats, "test", [])
    assert "concept, guide" in rendered


def test_topical_template_has_first_category_in_example_path():
    """The first category appears in the example path."""
    cats = ["reference", "guide"]
    rendered = _render_topical_classify_system(cats, "test", [])
    assert "wiki/reference/" in rendered


def test_topical_template_routing_instructions():
    """The prompt instructs routing to planned articles, not creating per-chapter ones."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "test", _SAMPLE_PLAN,
    )
    assert "planned" in rendered.lower() or "thematic" in rendered.lower()
    # Should mention creating new only for uncovered themes
    assert "new" in rendered.lower()


def test_topical_template_json_braces_are_literal():
    """JSON example braces are literal after rendering (double-brace escaping works)."""
    rendered = _render_topical_classify_system(
        DEFAULT_CATEGORIES, "test", [],
    )
    # The rendered output should have literal JSON braces, not Python format placeholders
    assert '"merge_into"' in rendered
    assert '"create_new"' in rendered


# ---------------------------------------------------------------------------
# classify_article_topical() function
# ---------------------------------------------------------------------------


def test_classify_article_topical_returns_classification_result():
    """classify_article_topical() returns a ClassificationResult."""
    mock_response = {
        "merge_into": [{"path": "wiki/concept/sun-wukong-character-overview.md", "reason": "character info"}],
        "create_new": [],
    }
    with patch("kb_ai.core.classify.completion_json", return_value=mock_response) as mock_llm:
        result = classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="Sun Wukong",
            aggregation_plan=_SAMPLE_PLAN,
        )

    assert isinstance(result, ClassificationResult)
    assert len(result.merge_into) == 1
    assert result.merge_into[0].path == "wiki/concept/sun-wukong-character-overview.md"


def test_classify_article_topical_sends_topic_in_system():
    """The system message sent to the LLM contains the topic string."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="Sun Wukong",
            aggregation_plan=_SAMPLE_PLAN,
        )

    system_msg = captured_messages[0]["content"]
    assert "Sun Wukong" in system_msg


def test_classify_article_topical_sends_plan_in_system():
    """The system message contains the aggregation plan JSON."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=_SAMPLE_PLAN,
        )

    system_msg = captured_messages[0]["content"]
    assert "sun-wukong-character-overview" in system_msg
    assert "journey-themes" in system_msg


def test_classify_article_topical_sends_extraction_in_user():
    """The user message contains the extraction summary."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=[],
        )

    user_msg = captured_messages[1]["content"]
    assert "Sun Wukong defeats the demon king" in user_msg


def test_classify_article_topical_uses_max_tokens_2048():
    """The LLM call uses max_tokens=2048."""
    captured_kwargs = {}

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_kwargs["max_tokens"] = max_tokens
        captured_kwargs["cache"] = cache
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=[],
        )

    assert captured_kwargs["max_tokens"] == 2048
    assert captured_kwargs["cache"] is True


def test_classify_article_topical_includes_existing_articles():
    """Existing articles appear in the system message (via ARTICLES_PLACEHOLDER)."""
    captured_messages = []
    existing = [
        ArticleMeta(
            title="Sun Wukong — Character Overview",
            path="wiki/concept/sun-wukong-character-overview.md",
            summary="Overview of Sun Wukong",
        ),
    ]

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=existing,
            topic="Sun Wukong",
            aggregation_plan=_SAMPLE_PLAN,
        )

    system_msg = captured_messages[0]["content"]
    # The placeholder should be replaced with actual articles JSON
    assert "{ARTICLES_PLACEHOLDER}" not in system_msg
    assert "Sun Wukong" in system_msg
    assert "sun-wukong-character-overview" in system_msg


def test_classify_article_topical_accepts_custom_categories():
    """Custom categories are passed through to the prompt."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=[],
            categories=["concept", "guide"],
        )

    system_msg = captured_messages[0]["content"]
    assert "concept, guide" in system_msg


def test_classify_article_topical_defaults_categories_to_default():
    """When categories=None, defaults are used."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=[],
        )

    system_msg = captured_messages[0]["content"]
    assert ", ".join(DEFAULT_CATEGORIES) in system_msg


def test_classify_article_topical_uses_topical_template_not_base():
    """The topical classify uses classify-topical, not classify template."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="My Topic",
            aggregation_plan=_SAMPLE_PLAN,
        )

    system_msg = captured_messages[0]["content"]
    # Topical template has "topic-focused knowledge base" which the base does not
    assert "topic-focused" in system_msg or "thematic" in system_msg


def test_classify_article_topical_no_articles_placeholder_in_final():
    """The final system message has no unfilled placeholder."""
    captured_messages = []

    def fake_completion_json(*, model, messages, max_tokens, cache):
        captured_messages.extend(messages)
        return {"merge_into": [], "create_new": []}

    with patch("kb_ai.core.classify.completion_json", side_effect=fake_completion_json):
        classify_article_topical(
            extraction=_SAMPLE_EXTRACTION,
            existing_articles=[],
            topic="test",
            aggregation_plan=[],
        )

    system_msg = captured_messages[0]["content"]
    assert "{ARTICLES_PLACEHOLDER}" not in system_msg
