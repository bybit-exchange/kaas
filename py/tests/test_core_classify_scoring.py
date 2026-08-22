"""Offline tests for classification scoring and budgeting (kb_ai.core.classify).

Covers the relevance ranking that decides which existing articles make it into
the prompt, the budget fit that cuts the catalog, and the title-overlap dedup
that stops the classifier creating near-duplicate articles.
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


def test_relevance_score_ranks_a_chinese_title_above_an_unrelated_one():
    """The ranking is what decides which articles survive the budget cut, so a
    Chinese-titled KB whose scores are all 0.0 has no ranking at all -- the merge
    target is then kept or dropped by list position."""
    topics = ["网关成本", "评审"]

    assert cl._relevance_score(article("网关成本评审"), topics) > 0.0
    assert cl._relevance_score(article("周末团建安排"), topics) == 0.0
    assert (cl._relevance_score(article("网关成本评审"), topics)
            > cl._relevance_score(article("周末团建安排"), topics))


def test_relevance_score_scores_a_mixed_script_title():
    """A title mixing Latin and Chinese scores on either side's terms."""
    assert cl._relevance_score(article("LiteLLM 网关"), ["litellm"]) == 1.0
    assert cl._relevance_score(article("LiteLLM 网关"), ["网关"]) > 0.0


def test_relevance_score_splits_hyphenated_titles():
    """Proof the shared tokeniser is in use: the ASCII-only predecessor stripped
    the hyphen and produced the single token `costreview`, which no topic list
    ever matches."""
    assert cl._relevance_score(article("Cost-Review"), ["review"]) == 1.0


# ── _fit_articles_to_budget ─────────────────────────────────────────

def entries(n: int, summary_chars: int = 80) -> list[dict]:
    return [{"title": f"Article {i}", "path": f"wiki/a{i}.md",
             "summary": "x" * summary_chars} for i in range(n)]


def test_fit_articles_under_budget_keeps_everything():
    articles = [{"title": "A", "path": "wiki/a.md", "summary": "s"}]
    out = cl._fit_articles_to_budget(articles, 10_000)
    assert json.loads(out) == articles


def test_fit_articles_renders_exactly_what_json_dumps_would():
    """The fit builds the array entry by entry to know each one's cost, so the
    rendering has to stay byte-identical to json.dumps or the prompt's article
    list changes shape the first time the budget is not hit."""
    articles = entries(3) + [{"title": "中文标题", "path": "wiki/zh.md", "summary": "摘要"}]

    out = cl._fit_articles_to_budget(articles, 100_000)

    assert out == json.dumps(articles, ensure_ascii=False, indent=2)


def test_fit_articles_keeps_every_entry_the_budget_holds(capsys):
    """Halving threw away up to half of what the budget could hold: 32 entries
    against a budget for 30 kept 16. The budget is the only limit that should
    decide, because every dropped entry is an article the classifier cannot
    merge into."""
    articles = entries(32)
    room_for_30 = len(json.dumps(articles[:30], ensure_ascii=False, indent=2))

    out = cl._fit_articles_to_budget(articles, room_for_30)

    kept = json.loads(out)
    assert len(kept) == 30
    assert len(out) <= room_for_30
    assert [e["title"] for e in kept] == [e["title"] for e in articles[:30]]
    assert "[truncation] classify articles: 32 → 30 items" in capsys.readouterr().err


def test_fit_articles_skips_an_oversized_entry_and_keeps_the_rest():
    """The list arrives ranked, so one entry too large to fit must not discard
    every smaller entry below it (same rule as retrieve._fit_catalog)."""
    articles = [
        {"title": "Huge", "path": "wiki/huge.md", "summary": "x" * 5_000},
        {"title": "Small", "path": "wiki/small.md", "summary": "s"},
    ]

    kept = json.loads(cl._fit_articles_to_budget(articles, 400))

    assert [e["title"] for e in kept] == ["Small"]


def test_fit_articles_charges_the_separator_between_entries():
    """With many small entries the separators are most of the slack, so charging
    them wrong admits an entry the budget cannot hold. Sized for 30 of 80: a fit
    that charges one character per separator instead of two keeps 31 and overruns.
    """
    articles = [{"title": f"t{i}"} for i in range(80)]
    room_for_30 = len(json.dumps(articles[:30], ensure_ascii=False, indent=2))

    out = cl._fit_articles_to_budget(articles, room_for_30)

    assert len(json.loads(out)) == 30
    assert len(out) <= room_for_30


@pytest.mark.parametrize("char", ["", " ", " "])
def test_fit_articles_keeps_titles_holding_line_break_codepoints_intact(char):
    """ensure_ascii=False emits these raw, and str.splitlines() treats all three
    as line breaks -- indenting through it injected two spaces into the title, so
    the model read a title no article has."""
    articles = [{"title": f"网关{char}评审", "path": "wiki/a.md", "summary": "s"}]

    out = cl._fit_articles_to_budget(articles, 10_000)

    assert out == json.dumps(articles, ensure_ascii=False, indent=2)
    assert json.loads(out)[0]["title"] == f"网关{char}评审"


def test_fit_articles_charges_the_array_brackets_to_the_first_entry():
    """The rendered array costs four characters more than its entries, so an
    entry that fits only by ignoring them must be dropped -- otherwise the fit
    returns a prompt fragment slightly over the budget it was given."""
    articles = entries(1)
    rendered = len(json.dumps(articles, ensure_ascii=False, indent=2))

    out = cl._fit_articles_to_budget(articles, rendered - 1)

    assert out == "[]"


def test_fit_articles_reports_nothing_when_everything_fits(capsys):
    cl._fit_articles_to_budget(entries(3), 100_000)
    assert capsys.readouterr().err == ""


def test_fit_articles_returns_empty_json_when_nothing_fits(capsys):
    articles = [{"title": "A" * 500, "path": "p", "summary": "s"}]

    out = cl._fit_articles_to_budget(articles, 5)

    assert out == "[]"
    assert "classify articles: 1 → 0 items" in capsys.readouterr().err


def test_fit_articles_empty_list():
    assert json.loads(cl._fit_articles_to_budget([], 1000)) == []


def test_fit_articles_negative_budget():
    assert cl._fit_articles_to_budget([{"title": "A"}], -5) == "[]"


def test_fit_articles_measures_chinese_entries_by_rendered_chars():
    """ensure_ascii=False means a Chinese entry costs its characters, not the
    six-fold \\uXXXX escape -- budgeting the escaped form would keep a third of
    what fits."""
    articles = [{"title": "网关成本评审", "path": "wiki/zh.md", "summary": "摘要" * 20}]
    rendered = json.dumps(articles, ensure_ascii=False, indent=2)

    out = cl._fit_articles_to_budget(articles, len(rendered))

    assert json.loads(out) == articles


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


def test_classify_article_orders_chinese_articles_by_relevance(fake_llm):
    """The bug this fixes: with every score 0.0 the sort was stable and therefore
    a no-op, so at 500 articles the budget cut kept whichever came first and the
    merge target was dropped by position -- one duplicate article per miss."""
    extraction = ExtractionResult(summary="s", topics=["网关成本"])
    articles = [
        article("周末团建安排", "wiki/trivia.md"),
        article("网关成本评审", "wiki/gateway-cost.md"),
    ]

    cl.classify_article(extraction, articles)

    system = fake_llm["system"]
    assert system.index("wiki/gateway-cost.md") < system.index("wiki/trivia.md")


def test_classify_article_keeps_the_ranked_head_when_the_budget_cuts(fake_llm, monkeypatch):
    """End to end over the two halves of the fix: the relevant Chinese article
    sits last in the input and still reaches a prompt with room for a fraction of
    the catalog."""
    monkeypatch.setattr(cl, "MAX_PROMPT_CHARS", 6_000)
    filler = [article(f"无关记录 {i}", f"wiki/filler{i}.md", summary="摘" * 80)
              for i in range(200)]
    target = article("网关成本评审", "wiki/gateway-cost.md", summary="摘" * 80)

    cl.classify_article(ExtractionResult(summary="s", topics=["网关成本"]), filler + [target])

    assert "wiki/gateway-cost.md" in fake_llm["system"]


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


def test_dedup_converts_a_chinese_near_duplicate_into_a_merge():
    """The dedup was the backstop for a classification that missed its merge
    target, and it rode the same ASCII-only tokeniser -- so on a Chinese KB the
    backstop never fired either."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/concept/gateway-cost-review.md",
                                 type="concept", title="网关成本评审")],
    )
    existing = [article("网关成本评审", "wiki/concept/gateway-cost.md")]

    out = cl.dedup_create_new(classification, existing)

    assert out.create_new == []
    assert out.merge_into[0].path == "wiki/concept/gateway-cost.md"


@pytest.mark.parametrize("new_title,existing_title", [
    # Every character of the shorter title appears in the longer one, so single
    # characters normalised by the smaller set scored these a perfect match.
    ("上海", "海上运输"),
    ("数据安全", "安全数据库"),
    ("成本评审流程", "成员入职指南"),
])
def test_dedup_keeps_distinct_chinese_articles(new_title, existing_title):
    """The direction that decides whether the threshold is safe: a Chinese title
    made of another's characters is a different article, and merging it writes a
    document's knowledge into an article that never claimed the subject."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title=new_title)],
    )

    out = cl.dedup_create_new(classification, [article(existing_title, "wiki/b.md")])

    assert len(out.create_new) == 1
    assert out.merge_into == []


@pytest.mark.parametrize("new_title,existing_title", [
    ("发言复盘 2026-03", "发言复盘 2026-01"),
    ("Weekly Report 2026-03", "Weekly Report 2026-01"),
    ("API v3 Design", "API v2 Design"),
])
def test_dedup_keeps_the_next_instance_of_a_numbered_series(new_title, existing_title):
    """Splitting a date into its own tokens is what makes these titles look alike,
    so the tokeniser change has to pay for the consequence: titles differing only
    in their numbers are consecutive instances of a series."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title=new_title)],
    )

    out = cl.dedup_create_new(classification, [article(existing_title, "wiki/b.md")])

    assert len(out.create_new) == 1
    assert out.merge_into == []


def test_dedup_merges_at_exactly_the_threshold():
    """0.7 is reachable, so the boundary decides real cases: ten tokens against
    ten sharing seven scores exactly 0.7 and merges."""
    new = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    existing = "alpha beta gamma delta epsilon zeta eta lambda mu nu"
    assert cl._duplicate_score(new, existing) == 0.7

    out = cl.dedup_create_new(
        ClassificationResult(create_new=[CreateTarget(path="wiki/a.md", title=new)]),
        [article(existing, "wiki/b.md")],
    )

    assert out.create_new == []
    assert out.merge_into[0].path == "wiki/b.md"


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


def test_dedup_merges_a_title_that_only_adds_a_qualifier():
    """The collision the cross-group dedup phase exists for: two groups name the
    same subject and one adds a word."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Vector Search Basics")])

    out = cl.dedup_create_new(classification, [article("Vector Search", "wiki/vs.md")])

    assert out.create_new == []
    assert out.merge_into[0].path == "wiki/vs.md"


@pytest.mark.parametrize("new_title", [
    "Pricing Model",                # 2 tokens against 1 -- ratio 2.0
    "Pricing Model Review Notes",   # ratio 4.0
])
def test_dedup_refuses_a_title_far_longer_than_the_one_it_contains(new_title):
    """Containment alone is weak evidence, so the two titles must be comparable in
    length: otherwise a short generic title absorbs every article that starts with
    it, and every character of 上海 sits inside 海上运输."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title=new_title)])

    out = cl.dedup_create_new(classification, [article("Pricing", "wiki/partial.md")])

    assert len(out.create_new) == 1
    assert out.merge_into == []


def test_dedup_breaks_a_tie_by_list_order():
    """Two candidates scoring the same keep the first, so the outcome does not
    depend on dict or filesystem ordering."""
    classification = ClassificationResult(
        create_new=[CreateTarget(path="wiki/a.md", title="Pricing Model")])
    existing = [
        article("Pricing Model", "wiki/first.md"),
        article("Pricing Model", "wiki/second.md"),
    ]

    out = cl.dedup_create_new(classification, existing)

    assert out.create_new == []
    assert out.merge_into[0].path == "wiki/first.md"


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
