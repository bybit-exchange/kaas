"""Offline tests for classification scoring and budgeting (kb_ai.core.classify).

Covers the relevance ranking that decides which existing articles make it into
the prompt, the exponential-backoff budget fit, and the title-overlap dedup that
stops the classifier creating near-duplicate articles.
"""
from __future__ import annotations

import json

import pytest

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core import classify as cl
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage.store import ArticleMeta


def article(title: str, path: str = "", summary: str = "") -> ArticleMeta:
    return ArticleMeta(title=title, path=path or f"wiki/{title.lower()}.md", summary=summary)


# ── _title_words ────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Hello World", {"hello", "world"}),
    ("Cost-Review Report!", {"costreview", "report"}),
    ("", set()),
    ("...", set()),
    ("MiXeD CaSe", {"mixed", "case"}),
    ("API v2 Design", {"api", "v2", "design"}),
])
def test_title_words(title, expected):
    assert cl._title_words(title) == expected


# ── _relevance_score ────────────────────────────────────────────────

def test_relevance_score_full_overlap():
    assert cl._relevance_score(article("Pricing Model"), ["pricing", "model"]) == 1.0


def test_relevance_score_no_overlap():
    assert cl._relevance_score(article("Pricing Model"), ["unrelated"]) == 0.0


def test_relevance_score_partial_overlap():
    score = cl._relevance_score(article("Pricing Model"), ["pricing", "other"])
    assert 0 < score < 1


def test_relevance_score_empty_title_is_zero():
    assert cl._relevance_score(article(""), ["pricing"]) == 0.0


def test_relevance_score_empty_topics_is_zero():
    assert cl._relevance_score(article("Pricing"), []) == 0.0


def test_relevance_score_ignores_punctuation_in_topics():
    assert cl._relevance_score(article("Cost Review"), ["cost!", "review?"]) == 1.0


def test_relevance_score_coerces_non_string_topics():
    """Topics come from LLM output and may not be strings."""
    assert cl._relevance_score(article("Version 2"), [2, "version"]) == 1.0


def test_relevance_score_normalises_by_the_smaller_set():
    """A one-word title fully matched scores 1.0 even against many topics, so
    short titles are not penalised."""
    assert cl._relevance_score(article("Pricing"), ["pricing", "a", "b", "c"]) == 1.0


# ── _fit_articles_to_budget ─────────────────────────────────────────

def test_fit_articles_under_budget_keeps_everything():
    articles = [{"title": "A", "path": "wiki/a.md", "summary": "s"}]
    out = cl._fit_articles_to_budget(articles, 10_000)
    assert json.loads(out) == articles


def test_fit_articles_halves_until_it_fits(capsys):
    articles = [{"title": f"Article {i}", "path": f"wiki/a{i}.md",
                 "summary": "x" * 80} for i in range(32)]

    out = cl._fit_articles_to_budget(articles, 2000)

    kept = json.loads(out)
    assert 0 < len(kept) < 32
    assert len(out) <= 2000
    # Backoff keeps the highest-ranked prefix.
    assert kept[0]["title"] == "Article 0"
    assert "[truncation] classify articles" in capsys.readouterr().err


def test_fit_articles_backs_off_to_zero_items(capsys):
    """With a budget that fits '[]' but nothing else, the halving loop reaches
    zero items and reports that rather than hitting the hopeless path."""
    articles = [{"title": "A" * 500, "path": "p", "summary": "s"}]

    out = cl._fit_articles_to_budget(articles, 5)

    assert out == "[]"
    assert "classify articles: 1 → 0 items" in capsys.readouterr().err


def test_fit_articles_returns_empty_json_when_budget_is_hopeless(capsys):
    """Below 2 chars even '[]' does not fit, so the loop exhausts and the
    hopeless-budget branch reports it."""
    articles = [{"title": "A" * 500, "path": "p", "summary": "s"}]

    out = cl._fit_articles_to_budget(articles, 1)

    assert out == "[]"
    assert "budget too small" in capsys.readouterr().err


def test_fit_articles_empty_list():
    assert json.loads(cl._fit_articles_to_budget([], 1000)) == []


def test_fit_articles_negative_budget():
    assert cl._fit_articles_to_budget([{"title": "A"}], -5) == "[]"


# ── classify_article ────────────────────────────────────────────────

@pytest.fixture
def fake_llm(monkeypatch):
    """Capture the prompt classify_article builds and return a canned result."""
    captured: dict = {"result": {"merge_into": [], "create_new": []}}

    def fake_completion_json(*, model, messages, max_tokens, cache=None):
        captured["model"] = model
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        captured["cache"] = cache
        return captured["result"]

    monkeypatch.setattr(cl, "completion_json", fake_completion_json)
    return captured


def test_classify_article_builds_the_user_message(fake_llm):
    extraction = ExtractionResult(
        summary="a summary", topics=["t1"],
        decisions=[{"title": "d1"}],
    )

    cl.classify_article(extraction, [])

    user = fake_llm["user"]
    assert "- Summary: a summary" in user
    assert "t1" in user
    assert "d1" in user


def test_classify_article_enables_prompt_caching(fake_llm):
    cl.classify_article(ExtractionResult(summary="s"), [])
    assert fake_llm["cache"] is True


def test_classify_article_default_categories(fake_llm):
    cl.classify_article(ExtractionResult(summary="s"), [])

    for category in ("concept", "project", "decision", "person"):
        assert category in fake_llm["system"]


def test_classify_article_custom_categories(fake_llm):
    cl.classify_article(ExtractionResult(summary="s"), [], categories=["runbook", "postmortem"])

    assert "runbook" in fake_llm["system"]
    assert "postmortem" in fake_llm["system"]


def test_classify_article_orders_articles_by_relevance(fake_llm):
    extraction = ExtractionResult(summary="s", topics=["pricing"])
    articles = [
        article("Unrelated Trivia", "wiki/trivia.md"),
        article("Pricing Model", "wiki/pricing.md"),
    ]

    cl.classify_article(extraction, articles)

    system = fake_llm["system"]
    assert system.index("wiki/pricing.md") < system.index("wiki/trivia.md")


def test_classify_article_truncates_long_summaries(fake_llm):
    cl.classify_article(ExtractionResult(summary="s" * 500_000), [])

    assert len(fake_llm["user"]) <= cl.MAX_PROMPT_CHARS // 2


def test_classify_article_returns_a_typed_result(fake_llm):
    fake_llm["result"] = {
        "merge_into": [{"path": "wiki/a.md", "reason": "r"}],
        "create_new": [{"path": "wiki/b.md", "type": "concept", "title": "B"}],
    }

    out = cl.classify_article(ExtractionResult(summary="s"), [])

    assert isinstance(out, ClassificationResult)
    assert out.merge_into[0].path == "wiki/a.md"
    assert out.create_new[0].title == "B"


def test_classify_article_truncates_article_summaries_to_80_chars(fake_llm):
    long_summary = "z" * 500
    cl.classify_article(ExtractionResult(summary="s"),
                        [article("A", "wiki/a.md", long_summary)])

    assert "z" * 80 in fake_llm["system"]
    assert "z" * 81 not in fake_llm["system"]


# ── dedup_create_new ────────────────────────────────────────────────

def test_dedup_converts_a_near_duplicate_into_a_merge():
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/concept/pricing-model.md",
                                 type="concept", title="Pricing Model")],
    )
    existing = [article("Pricing Model", "wiki/concept/pricing.md")]

    out = cl.dedup_create_new(classification, existing)

    assert out.create_new == []
    assert len(out.merge_into) == 1
    assert out.merge_into[0].path == "wiki/concept/pricing.md"
    assert "dedup: title overlap" in out.merge_into[0].reason


def test_dedup_keeps_a_distinct_new_article():
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/concept/new.md", title="Totally Different Thing")],
    )
    existing = [article("Pricing Model", "wiki/concept/pricing.md")]

    out = cl.dedup_create_new(classification, existing)

    assert len(out.create_new) == 1
    assert out.merge_into == []


def test_dedup_is_a_noop_without_creates():
    classification = ClassificationResult(merge_into=[MergeTarget(path="wiki/a.md")])
    assert cl.dedup_create_new(classification, [article("A")]) is classification


def test_dedup_is_a_noop_without_existing_articles():
    classification = ClassificationResult(create_new=[CreateTarget(path="wiki/a.md", title="A")])
    assert cl.dedup_create_new(classification, []) is classification


def test_dedup_keeps_an_untitled_create():
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="")],
    )
    out = cl.dedup_create_new(classification, [article("Anything")])

    assert len(out.create_new) == 1


def test_dedup_skips_untitled_existing_articles():
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Pricing Model")],
    )
    out = cl.dedup_create_new(classification, [article("")])

    assert len(out.create_new) == 1


def test_dedup_preserves_existing_merges():
    classification = ClassificationResult(
        merge_into=[MergeTarget(path="wiki/original.md", reason="classifier")],
        create_new=[CreateTarget(path="wiki/dup.md", title="Pricing Model")],
    )
    existing = [article("Pricing Model", "wiki/pricing.md")]

    out = cl.dedup_create_new(classification, existing)

    paths = {m.path for m in out.merge_into}
    assert paths == {"wiki/original.md", "wiki/pricing.md"}


def test_dedup_threshold_is_seventy_percent():
    """Three-word title sharing two words scores 0.67 and must stay a create;
    sharing all three scores 1.0 and becomes a merge."""
    below = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Alpha Beta Gamma")])
    out_below = cl.dedup_create_new(below, [article("Alpha Beta Delta")])
    assert len(out_below.create_new) == 1

    at_or_above = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Alpha Beta Gamma")])
    out_above = cl.dedup_create_new(at_or_above, [article("Alpha Beta Gamma")])
    assert out_above.create_new == []


def test_dedup_treats_a_subset_title_as_a_full_match():
    """Overlap is normalised by the smaller word set, so an existing title that
    is a strict subset of the new one also scores 1.0. Ties are broken by list
    order, so the first candidate wins rather than the exact match.
    """
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Pricing Model")])
    existing = [
        article("Pricing", "wiki/partial.md"),
        article("Pricing Model", "wiki/exact.md"),
    ]

    out = cl.dedup_create_new(classification, existing)

    assert out.create_new == []
    assert out.merge_into[0].path == "wiki/partial.md"


def test_dedup_handles_several_creates():
    classification = ClassificationResult(create_new=[
        CreateTarget(path="wiki/a.md", title="Pricing Model"),
        CreateTarget(path="wiki/b.md", title="Something Entirely Novel"),
    ])
    existing = [article("Pricing Model", "wiki/pricing.md")]

    out = cl.dedup_create_new(classification, existing)

    assert len(out.create_new) == 1
    assert out.create_new[0].title == "Something Entirely Novel"
    assert len(out.merge_into) == 1
