"""Offline tests for article merging (kb_ai.core.merge).

The LLM seams are monkeypatched. The interesting logic here is all budget and
text surgery: fitting an extraction into a character budget, section-based
article truncation, choosing rewrite vs diff mode, and applying diff patches to
markdown without corrupting frontmatter.
"""
from __future__ import annotations

import json
import threading
from datetime import date

import pytest

from kb_ai._errors import (
    DeadlineExceededError,
    EmptyCompletionError,
    OutputTruncatedError,
)
from kb_ai.core import merge as mg
from kb_ai.core.extract import ExtractionResult

TODAY = date.today().isoformat()


def _extraction(**kwargs) -> ExtractionResult:
    return ExtractionResult(**kwargs)


# ── _estimate_full_extraction_size ──────────────────────────────────

def test_estimate_size_skips_empty_fields():
    """The estimator must skip falsy fields exactly like
    _fit_extraction_to_budget does — otherwise an empty ExtractionResult is
    counted as eight `- Field: []` lines the output never emits, and every merge
    reports a truncation that never happened.
    """
    size = mg._estimate_full_extraction_size(_extraction(), "raw/a.md")

    assert size == len("- Source: raw/a.md\n")


def test_estimate_matches_the_text_produced_with_an_ample_budget():
    """The invariant the estimator exists to satisfy: with a budget nothing can
    exceed, the estimate must equal the emitted length — otherwise the
    truncation warning fires on complete output (or stays silent on truncated
    output). Pins the two functions' skip rules and format strings together.
    """
    e = _extraction(summary="s", topics=["a", "b"], concepts=[{"title": "c"}])

    assert mg._estimate_full_extraction_size(e, "raw/a.md") == len(
        mg._fit_extraction_to_budget(e, "raw/a.md", 1_000_000))


def test_estimate_size_grows_with_content():
    small = mg._estimate_full_extraction_size(_extraction(summary="s"), "raw/a.md")
    large = mg._estimate_full_extraction_size(
        _extraction(summary="s", topics=["a", "b"], concepts=[{"title": "c"}]), "raw/a.md")
    assert large > small


# ── _fit_extraction_to_budget ───────────────────────────────────────

def test_fit_extraction_includes_everything_when_budget_is_ample():
    out = mg._fit_extraction_to_budget(
        _extraction(summary="a summary", topics=["t1"], concepts=[{"title": "c1"}]),
        "raw/a.md", 10_000)

    assert "- Source: raw/a.md" in out
    assert "- Summary: a summary" in out
    assert "- Topics:" in out
    assert "- Concepts:" in out


def test_fit_extraction_zero_budget_is_empty():
    assert mg._fit_extraction_to_budget(_extraction(summary="s"), "raw/a.md", 0) == ""


def test_fit_extraction_tiny_budget_truncates_the_source_prefix():
    out = mg._fit_extraction_to_budget(_extraction(summary="s"), "raw/a.md", 5)
    assert out == "- Sou"


def test_fit_extraction_never_exceeds_the_budget():
    big = _extraction(
        summary="s" * 500,
        concepts=[{"title": f"c{i}", "summary": "x" * 100} for i in range(50)],
        topics=[f"t{i}" for i in range(50)],
    )
    for budget in (200, 500, 1000, 5000):
        out = mg._fit_extraction_to_budget(big, "raw/a.md", budget)
        assert len(out) <= budget, f"budget {budget} exceeded: {len(out)}"


def test_fit_extraction_truncates_a_long_summary_string():
    out = mg._fit_extraction_to_budget(_extraction(summary="s" * 10_000), "raw/a.md", 300)

    assert len(out) <= 300
    assert "- Summary: sss" in out


def test_fit_extraction_halves_list_items_to_fit():
    """List fields back off by halving rather than being dropped entirely."""
    concepts = [{"title": f"concept number {i}", "summary": "y" * 60} for i in range(16)]
    out = mg._fit_extraction_to_budget(_extraction(concepts=concepts), "raw/a.md", 700)

    assert "- Concepts:" in out
    included = json.loads(out.split("- Concepts: ", 1)[1].strip())
    assert 0 < len(included) < 16
    # Backoff keeps a prefix of the original list.
    assert included[0]["title"] == "concept number 0"


def test_fit_extraction_respects_field_priority():
    """Summary outranks action_items, so a tight budget keeps the summary."""
    e = _extraction(summary="important summary",
                    action_items=[{"task": "z" * 200} for _ in range(5)])
    out = mg._fit_extraction_to_budget(e, "raw/a.md", 120)

    assert "important summary" in out
    assert "Action Items" not in out


def test_fit_extraction_ranks_enumerations_above_the_prose_fields():
    """An enumeration is the one field a truncated prompt cannot paraphrase back:
    the writer either receives all eleven members or invents a plausible list
    (issue #41, and issue #42 is what that invention looks like). So it outranks
    concepts and claims, which degrade gracefully.
    """
    e = _extraction(
        enumerations=[{"name": "chain order", "items": ["Trace", "Log", "Recover"]}],
        concepts=[{"title": "c" * 200} for _ in range(5)],
        claims=[{"claim": "c" * 200} for _ in range(5)],
    )
    out = mg._fit_extraction_to_budget(e, "raw/a.md", 150)

    assert "Recover" in out
    assert "Concepts" not in out and "Claims" not in out


def test_fit_extraction_skips_empty_fields():
    out = mg._fit_extraction_to_budget(_extraction(summary="s", topics=[]), "raw/a.md", 1000)
    assert "Topics" not in out


def test_fit_extraction_drops_a_string_field_that_cannot_fit_its_own_label():
    """When the leftover budget is smaller than the `- Summary: ` label itself,
    the field is skipped entirely — emitting a bare label with an empty (or
    negatively sliced) value would ship a misleading field to the model."""
    out = mg._fit_extraction_to_budget(_extraction(summary="s" * 100), "raw/a.md", 24)

    assert out == "- Source: raw/a.md\n"
    assert "Summary" not in out


def test_fit_extraction_warns_when_truncating(capsys):
    mg._fit_extraction_to_budget(_extraction(summary="s" * 5000), "raw/a.md", 300)
    assert "extraction truncated" in capsys.readouterr().err


def test_fit_extraction_silent_when_complete(capsys):
    mg._fit_extraction_to_budget(_extraction(summary="short"), "raw/a.md", 10_000)
    assert "extraction truncated" not in capsys.readouterr().err


# ── _parse_sections ─────────────────────────────────────────────────

def test_parse_sections_splits_on_h2():
    sections = mg._parse_sections("intro text\n## One\nbody one\n## Two\nbody two")

    assert sections[0] == ("", "intro text")
    assert sections[1] == ("## One", "body one")
    assert sections[2] == ("## Two", "body two")


def test_parse_sections_without_headings():
    assert mg._parse_sections("just prose") == [("", "just prose")]


def test_parse_sections_empty_content():
    sections = mg._parse_sections("")
    assert sections == [("", "")]


def test_parse_sections_ignores_h3():
    sections = mg._parse_sections("## One\nbody\n### Sub\nsub body")
    assert len(sections) == 1
    assert "### Sub" in sections[0][1]


# ── _truncate_article_by_sections ───────────────────────────────────

def test_truncate_by_sections_keeps_all_headings_as_anchors():
    article = "\n".join(f"## Section {i}\n" + "x" * 500 for i in range(5))
    out = mg._truncate_article_by_sections(article, topics=[], budget_chars=300)

    for i in range(5):
        assert f"## Section {i}" in out, "headings are diff anchors and must survive"


def test_truncate_by_sections_prefers_topic_relevant_bodies():
    article = (
        "## Pricing Model\n" + "P" * 200 + "\n"
        "## Unrelated Trivia\n" + "U" * 200 + "\n"
    )
    budget = len("## Pricing Model") + len("## Unrelated Trivia") + 2 + 210

    out = mg._truncate_article_by_sections(article, topics=["pricing"], budget_chars=budget)

    assert "P" * 200 in out
    assert "U" * 200 not in out


def test_truncate_by_sections_splits_hyphenated_topics():
    article = "## Cost Review\n" + "C" * 100 + "\n## Other\n" + "O" * 100 + "\n"
    budget = len("## Cost Review") + len("## Other") + 2 + 110

    out = mg._truncate_article_by_sections(article, topics=["cost-review"], budget_chars=budget)

    assert "C" * 100 in out


def test_truncate_by_sections_keeps_original_order():
    article = "## Alpha\nA\n## Beta\nB\n## Gamma\nG\n"
    out = mg._truncate_article_by_sections(article, topics=["gamma"], budget_chars=10_000)

    assert out.index("## Alpha") < out.index("## Beta") < out.index("## Gamma")


def test_truncate_by_sections_extreme_budget_truncates_heading_list():
    article = "\n".join(f"## Section {i}\nbody" for i in range(10))
    out = mg._truncate_article_by_sections(article, topics=[], budget_chars=40)

    assert len(out) <= 40
    assert "## Section 0" in out
    assert "## Section 9" not in out


def test_truncate_by_sections_handles_none_topics():
    article = "## One\nbody\n"
    out = mg._truncate_article_by_sections(article, topics=None, budget_chars=10_000)
    assert "## One" in out


def test_truncate_by_sections_stops_filling_once_the_budget_is_spent():
    """The greedy fill stops at an exhausted budget instead of continuing to
    scan: a later empty-bodied section would otherwise still be "included" and
    inject a stray blank line into the skeleton handed to the diff model."""
    article = "## A\n" + "x" * 10 + "\n## B\n## C"
    # Exactly the three-heading skeleton (each heading costs len + 1) plus
    # section A's 10-char body, so the budget is spent after section A.
    budget = 3 * (len("## A") + 1) + 10

    out = mg._truncate_article_by_sections(article, topics=[], budget_chars=budget)

    assert out == "## A\n" + "x" * 10 + "\n## B\n## C"


def test_truncate_by_sections_reports_truncation(capsys):
    article = "\n".join(f"## S{i}\n" + "x" * 500 for i in range(5))
    mg._truncate_article_by_sections(article, topics=[], budget_chars=300)
    assert "[truncation] article sections" in capsys.readouterr().err


# ── mode selection ──────────────────────────────────────────────────

@pytest.fixture
def spy_modes(monkeypatch):
    """Record which merge mode was chosen."""
    chosen: dict = {}

    def fake_rewrite(article_path, article_content, extraction, source_path, model):
        chosen["mode"] = "rewrite"
        return "rewritten"

    def fake_diff(article_path, article_content, extraction, source_path, model):
        chosen["mode"] = "diff"
        return "diffed", False

    monkeypatch.setattr(mg, "_merge_full_rewrite", fake_rewrite)
    monkeypatch.setattr(mg, "_merge_diff", fake_diff)
    return chosen


def test_small_article_uses_full_rewrite(spy_modes):
    mg.merge_into_article("wiki/a.md", "short article", _extraction(), "raw/a.md")
    assert spy_modes["mode"] == "rewrite"


def test_large_article_uses_diff(spy_modes):
    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")
    assert spy_modes["mode"] == "diff"


def test_large_article_threshold_measured_in_utf8_bytes(spy_modes):
    """A CJK article is 3 bytes per character, so the byte threshold must trip
    well before the character count would."""
    chars = mg._LARGE_ARTICLE_THRESHOLD // 3 + 10
    mg.merge_into_article("wiki/a.md", "世" * chars, _extraction(), "raw/a.md")
    assert spy_modes["mode"] == "diff"


def test_article_over_prompt_budget_uses_diff(monkeypatch, spy_modes):
    """Just under the size threshold but over the prompt budget still has to
    fall back to diff mode."""
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 5000)
    article = "x" * (mg._LARGE_ARTICLE_THRESHOLD - 1)

    mg.merge_into_article("wiki/a.md", article, _extraction(), "raw/a.md")

    assert spy_modes["mode"] == "diff"


# ── configurable full-rewrite threshold ─────────────────────────────

def test_full_rewrite_limit_reads_the_env(monkeypatch):
    monkeypatch.setenv("KB_MERGE_FULL_REWRITE_LIMIT", "12000")
    assert mg._full_rewrite_limit() == 12_000


def test_full_rewrite_limit_without_env_uses_the_default(monkeypatch):
    monkeypatch.delenv("KB_MERGE_FULL_REWRITE_LIMIT", raising=False)
    assert mg._full_rewrite_limit() == 30_000


def test_full_rewrite_limit_invalid_env_warns_and_uses_the_default(monkeypatch, capsys):
    monkeypatch.setenv("KB_MERGE_FULL_REWRITE_LIMIT", "not-a-number")

    assert mg._full_rewrite_limit() == 30_000

    err = capsys.readouterr().err
    assert "KB_MERGE_FULL_REWRITE_LIMIT" in err
    assert "not-a-number" in err


def test_env_lowered_threshold_routes_a_midsize_article_to_diff(spy_modes, monkeypatch):
    """A 15KB article is a full-rewrite article at the shipped default but a
    diff article at the deployment-recommended 12000 -- the whole point of the
    env knob."""
    monkeypatch.setenv("KB_MERGE_FULL_REWRITE_LIMIT", "12000")

    mg.merge_into_article("wiki/a.md", "x" * 15_000, _extraction(), "raw/a.md")

    assert spy_modes["mode"] == "diff"


# ── diff degradation fallback ───────────────────────────────────────

def test_unparsable_diff_falls_back_to_full_rewrite(monkeypatch, capsys):
    """A degraded diff must not silently drop the new extraction's content:
    when the article fits the rewrite budget, the rewrite is paid instead."""
    calls: list[str] = []

    def fake_diff(article_path, article_content, extraction, source_path, model):
        calls.append("diff")
        return "diffed", True

    def fake_rewrite(article_path, article_content, extraction, source_path, model):
        calls.append("rewrite")
        return "rewritten"

    monkeypatch.setattr(mg, "_merge_diff", fake_diff)
    monkeypatch.setattr(mg, "_merge_full_rewrite", fake_rewrite)

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["diff", "rewrite"]
    assert "[merge] diff result unparsable, falling back to full-rewrite" in capsys.readouterr().err


@pytest.mark.parametrize("exc", [
    json.JSONDecodeError("bad", "{}", 0),
    RuntimeError("llm down"),
    EmptyCompletionError("LLM returned an empty body twice"),
    DeadlineExceededError("deadline_too_close to continue"),
    OutputTruncatedError("LLM output truncated at ceiling"),
], ids=["json-decode-error", "runtime-error", "empty-completion",
        "deadline-exceeded", "output-truncated"])
def test_merge_into_article_falls_back_when_diff_result_is_unparsable(
    monkeypatch, capsys, exc
):
    """End-to-end wiring: the real _merge_diff flags the failure and
    merge_into_article pays the rewrite, emitting the fallback log line that
    Phase 5 counts as the fallback-rate metric."""
    def boom(**kwargs):
        raise exc

    monkeypatch.setattr(mg, "completion_json", boom)
    monkeypatch.setattr(mg, "_merge_full_rewrite", lambda *args: "rewritten")

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert "[merge] diff result unparsable, falling back to full-rewrite" in capsys.readouterr().err


def test_a_legitimate_empty_patches_diff_does_not_fall_back(monkeypatch, capsys):
    """`{"patches": []}` is the model answering "nothing to add" -- a healthy
    diff result, not degradation, so no rewrite is paid and no fallback line
    is logged."""
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {"patches": []})

    def must_not_rewrite(*args):
        raise AssertionError("full rewrite must not run on a healthy diff")

    monkeypatch.setattr(mg, "_merge_full_rewrite", must_not_rewrite)

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == big
    assert "falling back to full-rewrite" not in capsys.readouterr().err


def test_a_degraded_diff_that_cannot_fit_a_rewrite_is_returned_as_is(monkeypatch, capsys):
    """Over the prompt budget there is no rewrite to fall back to, so the
    degraded diff content (article kept intact, no patches applied) is the
    result, without the fallback path or its log line -- but never silently:
    the no-rewrite drop line must say the extraction was not merged."""
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 5000)
    monkeypatch.setattr(mg, "_merge_diff", lambda *args: ("kept content", True))

    def must_not_rewrite(*args):
        raise AssertionError("rewrite cannot fit the budget and must not run")

    monkeypatch.setattr(mg, "_merge_full_rewrite", must_not_rewrite)

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == "kept content"
    err = capsys.readouterr().err
    assert "falling back to full-rewrite" not in err
    assert ("[merge] diff result unparsable and no rewrite fits: wiki/a.md keeps "
            "its current content") in err


def test_default_env_non_degraded_diff_result_is_returned_verbatim(monkeypatch):
    """Regression for the Phase 4 refactor: with the env unset, a healthy
    large-article merge is byte-identical to the pre-change behaviour -- the
    diff result is returned exactly as _merge_diff produced it."""
    monkeypatch.delenv("KB_MERGE_FULL_REWRITE_LIMIT", raising=False)
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [{"action": "append_to_section", "section": "## One",
                     "content": "added"}],
    })
    monkeypatch.setattr(mg, "_merge_full_rewrite", lambda *args: "REWRITTEN")

    article = "## One\nbody\n" + "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", article, _extraction(), "raw/a.md")

    expected, degraded = mg._merge_diff(
        "wiki/a.md", article, _extraction(), "raw/a.md", "claude-sonnet-4-6")

    assert degraded is False
    assert out == expected
    assert "added" in out


# ── _merge_user_message ─────────────────────────────────────────────

def test_merge_user_message_wraps_the_article():
    user = mg._merge_user_message("article body", _extraction(summary="s"), "raw/a.md", 10_000)

    assert "<article>" in user and "</article>" in user
    assert "article body" in user
    assert "New information to merge:" in user
    assert "- Source: raw/a.md" in user


def test_merge_user_message_hard_caps_at_budget():
    user = mg._merge_user_message("x" * 5000, _extraction(summary="s" * 5000), "raw/a.md", 1000)
    assert len(user) == 1000


def test_merge_user_message_reserves_a_floor_for_the_extraction():
    """Even when the article eats the whole budget, some extraction text must
    survive — otherwise the merge call carries no new information."""
    user = mg._merge_user_message("x" * 900, _extraction(summary="new fact"), "raw/a.md", 1000)
    assert len(user) == 1000


# ── _apply_diff: frontmatter ────────────────────────────────────────

def test_apply_diff_refreshes_updated_and_appends_source():
    article = (
        "---\n"
        "title: A\n"
        "updated: 2024-01-01\n"
        "sources:\n"
        "  - raw/old.md\n"
        "---\n"
        "## Body\ntext\n"
    )
    out = mg._apply_diff(article, {"patches": []}, "raw/new.md", TODAY)

    assert f"updated: {TODAY}" in out
    assert "updated: 2024-01-01" not in out
    assert "  - raw/old.md" in out
    assert "  - raw/new.md" in out


def test_apply_diff_does_not_duplicate_an_existing_source():
    article = (
        "---\ntitle: A\nupdated: 2024-01-01\nsources:\n  - raw/a.md\n---\nbody\n"
    )
    out = mg._apply_diff(article, {"patches": []}, "raw/a.md", TODAY)

    assert out.count("  - raw/a.md") == 1


def test_apply_diff_is_idempotent_for_a_repeated_source():
    """Re-merging the same source must not grow the frontmatter sources list."""
    out = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    for _ in range(3):
        out = mg._apply_diff(out, {"patches": []}, "raw/a.md", TODAY)

    assert out.count("  - raw/a.md") == 1


def test_apply_diff_adds_updated_when_missing():
    article = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/b.md", TODAY)

    assert f"updated: {TODAY}" in out


def test_apply_diff_without_frontmatter_leaves_body_alone():
    article = "## Body\njust text\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/a.md", TODAY)

    assert out == article


def test_apply_diff_handles_unterminated_frontmatter():
    article = "---\ntitle: A\nno closing delimiter\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/a.md", TODAY)

    assert out == article


def test_apply_diff_inserts_source_when_sources_is_last_key():
    article = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/new.md", TODAY)

    assert "  - raw/new.md" in out


def test_apply_diff_inserts_source_before_a_following_key():
    article = (
        "---\ntitle: A\nsources:\n  - raw/a.md\ncreated: 2024-01-01\n---\nbody\n"
    )
    out = mg._apply_diff(article, {"patches": []}, "raw/new.md", TODAY)

    lines = out.split("\n")
    assert lines.index("  - raw/new.md") < lines.index("created: 2024-01-01")


def test_apply_diff_fills_an_empty_sources_key_before_the_next_key():
    """`sources:` with no items yet: the new source must land under it rather
    than after the following key (or be dropped)."""
    article = "---\ntitle: A\nsources:\ncreated: 2024-01-01\n---\nbody\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/new.md", TODAY)

    lines = out.split("\n")
    assert lines[lines.index("sources:") + 1] == "  - raw/new.md"
    assert lines.index("  - raw/new.md") < lines.index("created: 2024-01-01")


def test_apply_diff_fills_an_empty_sources_key_at_the_end_of_frontmatter():
    """`sources:` with no items as the last frontmatter key: the source is
    appended after the loop ends, so it must not be lost."""
    article = "---\ntitle: A\nupdated: 2024-01-01\nsources:\n---\nbody\n"
    out = mg._apply_diff(article, {"patches": []}, "raw/a.md", TODAY)

    assert "sources:\n  - raw/a.md\n---" in out
    assert f"updated: {TODAY}" in out


@pytest.mark.parametrize("article", [
    # updated refresh + source append, the base case
    "---\ntitle: A\nupdated: 2024-01-01\nsources:\n  - raw/old.md\n---\n## Body\ntext\n",
    # source inserted before a following key
    "---\ntitle: A\nsources:\n  - raw/a.md\ncreated: 2024-01-01\n---\nbody\n",
    # empty sources key at the end of frontmatter
    "---\ntitle: A\nupdated: 2024-01-01\nsources:\n---\nbody\n",
    # no updated key to refresh
    "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n",
    # unterminated frontmatter: returned unchanged
    "---\ntitle: A\nno closing delimiter\n",
    # no frontmatter at all: returned unchanged
    "## Body\njust text\n",
])
def test_update_frontmatter_equals_apply_diff_without_patches(article):
    """The factoring was verbatim: with no patches to apply, _apply_diff must
    produce exactly what _update_frontmatter produces, byte for byte, across
    every frontmatter shape the _apply_diff tests above cover."""
    assert mg._update_frontmatter(article, "raw/new.md", TODAY) == \
        mg._apply_diff(article, {"patches": []}, "raw/new.md", TODAY)


# ── _apply_diff: patches ────────────────────────────────────────────

def test_apply_diff_appends_to_an_existing_section():
    article = "## One\nexisting\n\n## Two\nother\n"
    diff = {"patches": [
        {"action": "append_to_section", "section": "## One", "content": "added line"},
    ]}
    out = mg._apply_diff(article, diff, "raw/a.md", TODAY)

    assert "added line" in out
    # The addition lands inside section One, above section Two.
    assert out.index("added line") < out.index("## Two")


def test_apply_diff_creates_a_new_section_after_an_anchor():
    article = "## One\nbody\n## Three\nbody\n"
    diff = {"patches": [
        {"action": "new_section", "after": "## One", "heading": "## Two", "content": "new body"},
    ]}
    out = mg._apply_diff(article, diff, "raw/a.md", TODAY)

    assert out.index("## One") < out.index("## Two") < out.index("## Three")


def test_apply_diff_applies_several_patches():
    article = "## One\nbody\n"
    diff = {"patches": [
        {"action": "append_to_section", "section": "## One", "content": "first"},
        {"action": "new_section", "after": "## One", "heading": "## Two", "content": "second"},
    ]}
    out = mg._apply_diff(article, diff, "raw/a.md", TODAY)

    assert "first" in out and "second" in out


def test_apply_diff_ignores_unknown_actions():
    article = "## One\nbody\n"
    out = mg._apply_diff(article, {"patches": [{"action": "delete_everything"}]},
                         "raw/a.md", TODAY)
    assert "body" in out


def test_apply_diff_tolerates_a_missing_patches_key():
    article = "## One\nbody\n"
    assert mg._apply_diff(article, {}, "raw/a.md", TODAY) == article


# ── _append_to_section / _insert_section_after ───────────────────────

def test_append_to_section_creates_the_section_when_absent():
    out = mg._append_to_section("## One\nbody\n", "## Missing", "new text")

    assert "## Missing" in out
    assert "new text" in out
    assert out.index("## One") < out.index("## Missing")


def test_append_to_section_stops_at_a_same_level_heading():
    article = "## One\nbody one\n## Two\nbody two\n"
    out = mg._append_to_section(article, "## One", "inserted")

    assert out.index("inserted") < out.index("## Two")


def test_append_to_section_passes_over_deeper_headings():
    """A ### subsection belongs to the section, so content appends after it."""
    article = "## One\nbody\n### Sub\nsub body\n## Two\nx\n"
    out = mg._append_to_section(article, "## One", "inserted")

    assert out.index("### Sub") < out.index("inserted") < out.index("## Two")


def test_append_to_section_at_end_of_document():
    out = mg._append_to_section("## Only\nbody\n", "## Only", "inserted")
    assert out.rstrip().endswith("inserted")


def test_insert_section_after_appends_when_anchor_is_missing():
    out = mg._insert_section_after("## One\nbody\n", "## Ghost", "## New", "new body")

    assert "## New" in out
    assert "new body" in out


def test_insert_section_after_respects_heading_levels():
    article = "## One\nbody\n### Sub\nsub\n## Three\nx\n"
    out = mg._insert_section_after(article, "## One", "## Two", "two body")

    assert out.index("### Sub") < out.index("## Two") < out.index("## Three")


# ── _section_guidance / _strip_markdown_fencing ─────────────────────

@pytest.mark.parametrize("article_type", ["concept", "project", "decision", "person"])
def test_section_guidance_known_types(article_type):
    out = mg._section_guidance(article_type)

    assert f'Article type: "{article_type}"' in out
    assert "Suggested sections:" in out


def test_section_guidance_unknown_type_falls_back():
    out = mg._section_guidance("mystery")

    assert 'Article type: "mystery"' in out
    assert "Choose appropriate sections" in out


@pytest.mark.parametrize("text,expected", [
    ("```markdown\n# Title\n```", "# Title\n"),
    ("```\n# Title\n```", "# Title\n"),
    ("# Title\nno fence", "# Title\nno fence"),
])
def test_strip_markdown_fencing(text, expected):
    assert mg._strip_markdown_fencing(text) == expected


def test_strip_markdown_fencing_open_fence_only():
    """An unterminated fence still has its opening line removed."""
    assert mg._strip_markdown_fencing("```markdown\n# Title") == "# Title"


# ── _merge_full_rewrite / _merge_diff ───────────────────────────────

def test_merge_full_rewrite_strips_fencing(monkeypatch):
    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: "```markdown\n# Merged\nbody\n```")

    out = mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert out.startswith("# Merged")
    assert "```" not in out


# ── _strip_article_wrapper ──────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("<article>\n---\ntitle: A\n---\nbody\n</article>", "---\ntitle: A\n---\nbody"),
    ("<article>\n---\ntitle: A\n---\nbody", "---\ntitle: A\n---\nbody"),
    ("---\ntitle: A\n---\nbody\n", "---\ntitle: A\n---\nbody\n"),
    ("<article>", ""),
])
def test_strip_article_wrapper(text, expected):
    assert mg._strip_article_wrapper(text) == expected


def test_strip_article_wrapper_leaves_an_unwrapped_article_alone():
    """Whitespace must not be touched when no wrapper is present — the fencing
    stripper intentionally leaves the inner document's trailing newline."""
    text = "# Title\n\nbody\n"
    assert mg._strip_article_wrapper(text) == text


def test_strip_article_wrapper_keeps_a_lone_trailing_close_tag():
    """Paired-only: a body legitimately ending with a literal </article>
    (an HTML example, say) must not lose its tail."""
    text = "---\ntitle: A\n---\ndiscusses <article> tags\n</article>"
    assert mg._strip_article_wrapper(text) == text


def test_merge_full_rewrite_strips_the_echoed_article_wrapper(monkeypatch):
    """The rewrite prompt frames the existing article in <article>...</article>,
    and the output is written to disk verbatim — an echoed wrapper would land
    above the frontmatter in the compiled wiki."""
    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: "<article>\n---\ntitle: A\n---\nbody\n</article>")

    out = mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert out.startswith("---")
    assert "<article>" not in out and "</article>" not in out


def test_merge_full_rewrite_strips_fencing_inside_the_echoed_wrapper(monkeypatch):
    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: "<article>\n```markdown\n# Merged\n```\n</article>")

    out = mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert out == "# Merged\n"


def test_merge_full_rewrite_strips_the_wrapper_inside_an_echoed_fence(monkeypatch):
    """The echo can nest the other way too — the whole wrapper inside a
    markdown fence — which a single ordering of the two strippers misses."""
    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: "```markdown\n<article>\n---\ntitle: A\n---\nbody\n</article>\n```")

    out = mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert out.startswith("---")
    assert "<article>" not in out and "</article>" not in out


def test_merge_into_article_heals_a_polluted_article_before_the_diff_path(monkeypatch):
    """An article that already leaked the wrapper has its frontmatter pass
    silently skipped by _apply_diff (lines[0] != "---"), so `updated` never
    refreshes and sources never append. The entry strip must restore that."""
    polluted = (
        "<article>\n"
        "---\ntitle: A\nupdated: 2024-01-01\nsources:\n  - raw/a.md\n---\n"
        + "x" * mg._LARGE_ARTICLE_THRESHOLD + "\n"
        "</article>"
    )
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {"patches": []})

    out = mg.merge_into_article("wiki/a.md", polluted, _extraction(), "raw/a.md")

    assert out.startswith("---")
    assert "<article>" not in out and "</article>" not in out
    assert f"updated: {TODAY}" in out


def test_merge_into_article_heals_a_polluted_article_before_the_rewrite_path(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return "---\ntitle: A\n---\nbody\n"

    monkeypatch.setattr(mg, "completion", fake_completion)

    out = mg.merge_into_article(
        "wiki/a.md", "<article>\n---\ntitle: A\n---\nbody\n</article>",
        _extraction(), "raw/a.md")

    assert out.startswith("---")
    # The model must be shown a clean article, not one double-wrapped in the
    # prompt framing.
    assert captured["user"].count("<article>") == 1


def test_merge_full_rewrite_enables_prompt_caching(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "text"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert captured["cache"] is True


def test_merge_diff_applies_the_returned_patches(monkeypatch):
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [{"action": "append_to_section", "section": "## One", "content": "added"}],
    })

    out, degraded = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "added" in out
    assert degraded is False


def test_merge_diff_degrades_to_no_patches_on_bad_json(monkeypatch):
    """A model returning unparseable JSON must leave the article intact rather
    than dropping content."""
    def boom(**kwargs):
        raise json.JSONDecodeError("bad", "{}", 0)

    monkeypatch.setattr(mg, "completion_json", boom)

    out, degraded = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "body" in out
    assert degraded is True


def test_merge_diff_degrades_on_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(mg, "completion_json", boom)

    out, degraded = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "body" in out
    assert degraded is True


def test_merge_diff_truncates_an_oversized_article(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 4000)

    article = "\n".join(f"## S{i}\n" + "x" * 400 for i in range(20))
    mg._merge_diff("wiki/a.md", article, _extraction(topics=["s1"]), "raw/a.md", "m")

    assert len(captured["user"]) <= 4000


def test_merge_diff_applies_patches_to_the_full_article_not_the_truncated_view(
    monkeypatch,
):
    """BUG 1 regression: the diff prompt is built from a section-truncated view,
    but the patches are applied to the full on-disk article. The pre-fix apply
    rebuilt the article from the view, so every non-relevant section body was
    silently dropped from disk -- and in the extreme branch the frontmatter,
    which _apply_diff's frontmatter pass requires, went with it."""
    captured = {}

    def fake_completion_json(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return {"patches": [
            {"action": "append_to_section", "section": "## Pricing", "content": "added line"},
        ]}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)
    # Low enough that the 70%-of-budget section truncation cuts the view down
    # to the topic-relevant section's body alone -- the frontmatter preamble is
    # sized so it does not fit in what remains, matching the loss the old
    # truncated-view apply produced.
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 20_000)

    article = (
        "---\n"
        "title: A\n"
        "updated: 2024-01-01\n"
        "summary: " + "m" * 3_000 + "\n"
        "sources:\n"
        "  - raw/old.md\n"
        "---\n"
        "## Pricing\n" + "P" * 10_000 + "\n"
        "## Operations\n" + "O" * 10_000 + "\n"
        "## Security\n" + "S" * 10_000 + "\n"
        "## History\n" + "H" * 10_000 + "\n"
    )
    assert len(article) >= 40_000

    out, degraded = mg._merge_diff(
        "wiki/a.md", article, _extraction(topics=["pricing"]), "raw/new.md", "m")

    # The model really only saw the relevant section -- the regression is about
    # what happens to the rest of the article.
    assert "P" * 10_000 in captured["user"]
    assert "O" * 10_000 not in captured["user"]
    assert "m" * 3_000 not in captured["user"]
    assert degraded is False
    # The merged result keeps every non-relevant section body anyway.
    assert "O" * 10_000 in out
    assert "S" * 10_000 in out
    assert "H" * 10_000 in out
    # The frontmatter survived on the full article and was updated by it.
    assert out.startswith("---")
    assert "title: A" in out
    assert "updated: 2024-01-01" not in out
    assert f"updated: {TODAY}" in out
    assert "  - raw/old.md" in out
    assert "  - raw/new.md" in out
    # And the patch itself landed.
    assert "added line" in out


def test_merge_diff_drops_a_malformed_patch_and_degrades(monkeypatch, capsys):
    """BUG 2: a malformed patch is dropped with an alert, and the drop marks
    the response suspect (degraded=True) so the caller can pay the rewrite."""
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [
            {"action": "append_to_section", "section": "## One", "content": "kept"},
            {"action": "append_to_section", "section": "", "content": "dropped"},
        ],
    })

    out, degraded = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert degraded is True
    assert "kept" in out
    assert "dropped" not in out
    assert "[LLM-WARN] merge_patch_dropped" in capsys.readouterr().err


def test_a_dropped_patch_degrades_into_the_full_rewrite_fallback(monkeypatch, capsys):
    """BUG 2 end-to-end: the dropped-patch degraded flag drives the existing
    fallback -- a full rewrite is paid when the article fits its budget, with
    the same log line the fallback-rate metric counts."""
    calls: list[str] = []

    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [
            {"action": "new_section", "after": "## One", "heading": "## Two",
             "content": "valid"},
            {"action": "rewrite_section", "section": "## One", "content": "bogus"},
        ],
    })
    monkeypatch.setattr(
        mg, "_merge_full_rewrite",
        lambda *args: (calls.append("rewrite"), "rewritten")[1])

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["rewrite"]
    err = capsys.readouterr().err
    assert "[LLM-WARN] merge_patch_dropped" in err
    assert "[merge] diff result unparsable, falling back to full-rewrite" in err


def test_merge_diff_sizes_the_call_from_the_extraction_estimate(monkeypatch):
    """The patch payload scales with the extraction, not the article, so the
    first max_tokens rung is estimate_max_tokens(extraction_estimate) with a
    4096 floor -- over-provisioning is free, under-sizing costs a restart."""
    from kb_ai.llm import estimate_max_tokens

    captured = {}

    def fake_completion_json(**kwargs):
        captured["max_tokens"] = kwargs["max_tokens"]
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    e = _extraction(summary="s" * 2_000, topics=["t"])
    mg._merge_diff("wiki/a.md", "## One\nbody\n", e, "raw/a.md", "m")

    assert captured["max_tokens"] == estimate_max_tokens(
        mg._estimate_full_extraction_size(e, "raw/a.md"), minimum=4096)


# ── _validate_patches ───────────────────────────────────────────────

def test_validate_patches_keeps_well_formed_patches(capsys):
    patches = [
        {"action": "append_to_section", "section": "## One", "content": "text"},
        {"action": "new_section", "after": "## One", "heading": "## Two", "content": "text"},
    ]

    valid, dropped = mg._validate_patches({"patches": patches}, "m")

    assert valid == patches
    assert dropped == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("patch", [
    # append_to_section: empty section anchor
    {"action": "append_to_section", "section": "", "content": "text"},
    # append_to_section: content missing entirely
    {"action": "append_to_section", "section": "## One"},
    # new_section: empty heading
    {"action": "new_section", "after": "## One", "heading": "", "content": "text"},
    # new_section: anchor missing
    {"action": "new_section", "heading": "## Two", "content": "text"},
    # new_section: empty content
    {"action": "new_section", "after": "## One", "heading": "## Two", "content": ""},
    # an action the prompt never offered
    {"action": "delete_section", "section": "## One"},
    # not even an object
    "not a patch",
], ids=[
    "append-empty-section",
    "append-no-content",
    "new-empty-heading",
    "new-no-after",
    "new-empty-content",
    "unknown-action",
    "not-an-object",
])
def test_validate_patches_drops_each_malformed_shape(patch, capsys):
    valid, dropped = mg._validate_patches({"patches": [patch]}, "m")

    assert valid == []
    assert dropped == 1
    err = capsys.readouterr().err
    assert "[LLM-WARN] merge_patch_dropped" in err


def test_validate_patches_on_an_empty_response_drops_nothing(capsys):
    """`{"patches": []}` is the model's legitimate nothing-to-add answer and
    must not alert or degrade anything."""
    valid, dropped = mg._validate_patches({"patches": []}, "m")

    assert valid == []
    assert dropped == 0
    assert capsys.readouterr().err == ""


# ── create_new_article ──────────────────────────────────────────────

def test_create_new_article_builds_prompt_and_strips_fencing(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        captured["user"] = kwargs["messages"][1]["content"]
        captured["cache"] = kwargs.get("cache")
        return "```markdown\n---\ntitle: T\n---\nbody\n```"

    monkeypatch.setattr(mg, "completion", fake_completion)

    out = mg.create_new_article("concept", "My Title", _extraction(topics=["t"]), "raw/a.md")

    assert out.startswith("---")
    assert "```" not in out
    assert "- Title: My Title" in captured["user"]
    assert "- Source: raw/a.md" in captured["user"]
    assert f"- Created/Updated: {TODAY}" in captured["user"]
    assert "Suggested sections: Overview, Details" in captured["system"]
    assert captured["cache"] is True


def test_create_new_article_sizes_first_rung_and_continues(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "article text"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("concept", "T", _extraction(topics=["t"]), "raw/a.md")

    expected = 2 * mg._estimate_full_extraction_size(
        _extraction(topics=["t"]), "raw/a.md")
    assert captured["max_tokens"] == mg.estimate_max_tokens(expected, minimum=16384)
    assert captured["continue_on_length"] is True


def test_merge_full_rewrite_sizes_first_rung_and_continues(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "<article>\n---\ntitle: T\n---\nbody\n</article>"

    monkeypatch.setattr(mg, "completion", fake_completion)

    article = "---\ntitle: T\n---\n" + ("x" * 40000)
    extraction = _extraction(topics=["t"])
    mg._merge_full_rewrite("wiki/c/a.md", article, extraction, "raw/a.md", "m")

    expected = len(article) + mg._estimate_full_extraction_size(extraction, "raw/a.md")
    assert captured["max_tokens"] == mg.estimate_max_tokens(expected, minimum=16384)
    assert captured["continue_on_length"] is True


def test_create_new_article_adds_status_for_projects(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("project", "P", _extraction(), "raw/a.md")

    assert "status: active" in captured["system"]


def test_create_new_article_omits_status_for_non_projects(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("concept", "C", _extraction(), "raw/a.md")

    assert "status: active" not in captured["system"]


def test_create_new_article_bounds_the_extraction(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 3000)

    huge = _extraction(summary="s" * 50_000, concepts=[{"t": "x" * 500} for _ in range(50)])
    mg.create_new_article("concept", "T", huge, "raw/a.md")

    assert len(captured["user"]) < 10_000


# ── write-phase provenance ──────────────────────────────────────────
#
# The extraction layer records which extract prompt produced it, so staleness is
# a field comparison. The write phase had no equivalent: editing merge-rewrite.md
# or merge-diff.md invalidated nothing, and neither did editing the article
# creator's own system prompt, which lives in code rather than in a file.

@pytest.fixture(autouse=True)
def clear_write_prompt_version_cache():
    mg.write_prompt_version.cache_clear()
    yield
    mg.write_prompt_version.cache_clear()


def _prompt_dir(tmp_path, **bodies) -> object:
    prompts = tmp_path / "prompts"
    prompts.mkdir(exist_ok=True)
    for name in ("merge-rewrite", "merge-diff", "merge-section-router", "merge-section"):
        (prompts / f"{name}.md").write_text(bodies.get(name, f"[{name}] body"))
    return prompts


def _reset_registry(monkeypatch, prompts):
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(prompts))
    import kb_ai.prompts as prompts_pkg
    monkeypatch.setattr(prompts_pkg, "_registry", None)
    mg.write_prompt_version.cache_clear()


def test_write_prompt_version_is_twelve_hex_digits():
    version = mg.write_prompt_version()
    assert len(version) == 12
    assert all(c in "0123456789abcdef" for c in version)


def test_write_prompt_version_is_memoized_within_a_process(monkeypatch):
    """Same reason extract_prompt_version is (B12): the registry caches per name,
    so an unmemoized hash could mix a pre-edit and a post-edit prompt."""
    calls: list[str] = []
    real = mg._write_stage_renderings

    def counting():
        calls.append("rendered")
        return real()

    monkeypatch.setattr(mg, "_write_stage_renderings", counting)
    first = mg.write_prompt_version()
    assert mg.write_prompt_version() == first
    assert len(calls) == 1


def test_write_prompt_version_moves_when_merge_rewrite_changes(monkeypatch, tmp_path):
    prompts = _prompt_dir(tmp_path)
    _reset_registry(monkeypatch, prompts)
    before = mg.write_prompt_version()

    (prompts / "merge-rewrite.md").write_text("[merge-rewrite] body, one more rule")
    _reset_registry(monkeypatch, prompts)

    assert mg.write_prompt_version() != before


def test_write_prompt_version_moves_when_merge_diff_changes(monkeypatch, tmp_path):
    prompts = _prompt_dir(tmp_path)
    _reset_registry(monkeypatch, prompts)
    before = mg.write_prompt_version()

    (prompts / "merge-diff.md").write_text("[merge-diff] body, one more rule")
    _reset_registry(monkeypatch, prompts)

    assert mg.write_prompt_version() != before


def test_write_prompt_version_moves_when_a_section_template_changes(monkeypatch):
    """The article creator's prompt is a code constant, so hashing the files
    alone would leave it a blind spot -- the same trap B11 covers for extract."""
    before = mg.write_prompt_version()

    edited = dict(mg._SECTION_TEMPLATES)
    edited["concept"] = "Sections: Definition, Why it matters, Open questions"
    monkeypatch.setattr(mg, "_SECTION_TEMPLATES", edited)
    mg.write_prompt_version.cache_clear()

    assert mg.write_prompt_version() != before


def test_write_prompt_version_covers_a_type_with_no_section_template(monkeypatch):
    """_section_guidance falls back for a type it has no template for, and that
    fallback text is part of what gets sent. reference and guide are both in
    DEFAULT_CATEGORIES and neither has a template."""
    before = mg.write_prompt_version()

    monkeypatch.setattr(mg, "_section_guidance",
                        lambda t: "Article type: rewritten guidance")
    mg.write_prompt_version.cache_clear()

    assert mg.write_prompt_version() != before


def test_create_new_article_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    """Ties the hash to the production path: a version over a template the real
    call does not use would report freshness about text nobody sent."""
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("project", "P", _extraction(), "raw/a.md")

    assert captured["system"] == mg._create_system("project")


def test_merge_full_rewrite_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    """The rewrite path composes its system prompt rather than sending the file
    verbatim, so the hash and the send have to read the same helper."""
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")

    assert captured["system"] == mg._merge_rewrite_system()


def test_merge_diff_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert captured["system"] == mg._merge_diff_system()


# ── the grounding constraint (issue #42) ────────────────────────────
#
# The write phase emitted a `MiddlewaresConf` field that does not exist in go-zero
# and an ordered middleware chain that appeared in no extraction. #41 fixed the
# supply of enumerations; these cover the other half, which is that none of the
# three system prompts told the writer to stay inside its input.

def test_grounding_constraint_reaches_every_write_stage_prompt():
    renderings = mg._write_stage_renderings()
    assert renderings, "no write-stage prompts to check"
    for name, text in renderings:
        assert mg._GROUNDING in text, f"{name} carries no grounding constraint"


def test_grounding_constraint_reaches_the_two_merge_paths_as_sent(monkeypatch):
    """_write_stage_renderings could agree with itself and still hash text the
    production call never sends, so assert on the sent messages too."""
    sent: list[str] = []

    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: sent.append(kwargs["messages"][0]["content"]) or "a")
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: sent.append(kwargs["messages"][0]["content"]) or {"patches": []})

    mg._merge_full_rewrite("wiki/a.md", "old", _extraction(), "raw/a.md", "m")
    mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")
    mg.create_new_article("concept", "C", _extraction(), "raw/a.md")

    assert len(sent) == 3
    for system in sent:
        assert mg._GROUNDING in system


def test_grounding_constraint_names_enumerations_and_partial_sets():
    """Wording is load-bearing here: a generic "be accurate" line is what the
    prompts effectively already said. The two behaviours #42 needs are declining
    to complete a set, and treating a given enumeration as closed."""
    text = mg._GROUNDING.lower()
    assert "enumerat" in text
    assert "partial" in text or "incomplete" in text


def test_rewrite_prompt_states_the_article_wrapper_is_not_content():
    """Root cause of the <article> leak: the grounding constraint (#42,
    bd8252e) made the writer faithful to its input, transport wrapper included,
    so the rule that removes the cause must actually reach the rewrite path.
    Wording is load-bearing the same way the grounding text's is."""
    system = mg._merge_rewrite_system()
    assert "<article>" in system
    assert "not article content" in system


def test_write_prompt_version_moves_when_the_grounding_constraint_changes(monkeypatch):
    before = mg.write_prompt_version()

    monkeypatch.setattr(mg, "_GROUNDING", mg._GROUNDING + "\n- one more rule")
    mg.write_prompt_version.cache_clear()

    assert mg.write_prompt_version() != before


def test_the_two_prompt_versions_are_independent(monkeypatch):
    """A write-prompt edit must not move the extraction's version, or every
    document would re-extract at full cost over a prompt extraction never used."""
    from kb_ai.core import extract as ex

    ex.extract_prompt_version.cache_clear()
    extract_before = ex.extract_prompt_version()
    write_before = mg.write_prompt_version()

    edited = dict(mg._SECTION_TEMPLATES)
    edited["concept"] = "Sections: something else entirely"
    monkeypatch.setattr(mg, "_SECTION_TEMPLATES", edited)
    mg.write_prompt_version.cache_clear()
    ex.extract_prompt_version.cache_clear()

    assert mg.write_prompt_version() != write_before
    assert ex.extract_prompt_version() == extract_before


# ── section-level merge (F2b-1): prompts, knobs, and the router ────
#
# The section path replaces whole-article rewrites with a tiny router call plus
# per-section rewrites. This section covers the prompt registration, the two env
# knobs, and the router; the rewriter, dispatch, guard, and fallback chain are
# F2b-2.

def test_write_prompt_version_golden_hash():
    """Golden hash of the write stage's prompt set over the shipped files.

    s2-feat-006 (F2b-1, plan 2026-09-02-distill-real-throughput.md §3.2) added
    the merge-section-router and merge-section prompt files and registered both
    in _write_stage_renderings(), moving the hash from 694b20651199 to
    7acff9f3067b by design: the section path's prompts are write-stage system
    prompts, so provenance must cover them even though the version remains
    reported-never-gated (no re-extraction or rewrite cost). Any further edit
    that moves the hash must update this literal together with a justification
    here, mirroring the extract-side golden test.
    """
    mg.write_prompt_version.cache_clear()
    assert mg.write_prompt_version() == "7acff9f3067b"


def test_write_stage_renderings_cover_the_two_section_prompts():
    names = [name for name, _text in mg._write_stage_renderings()]
    assert "merge-section-router" in names
    assert "merge-section" in names


def test_the_section_prompts_render_file_plus_grounding():
    """The two section prompts compose like the other merge prompts -- file
    content plus the code-appended _GROUNDING -- and use .content so the
    literal JSON braces in merge-section-router.md survive verbatim."""
    registry = mg.default_registry()

    assert mg._merge_section_router_system() == (
        registry.get("merge-section-router").content + "\n" + mg._GROUNDING)
    assert mg._merge_section_system() == (
        registry.get("merge-section").content + "\n" + mg._GROUNDING)


def test_write_prompt_version_moves_when_merge_section_router_changes(monkeypatch, tmp_path):
    prompts = _prompt_dir(tmp_path)
    _reset_registry(monkeypatch, prompts)
    before = mg.write_prompt_version()

    (prompts / "merge-section-router.md").write_text("[merge-section-router] body, one more rule")
    _reset_registry(monkeypatch, prompts)

    assert mg.write_prompt_version() != before


def test_write_prompt_version_moves_when_merge_section_changes(monkeypatch, tmp_path):
    prompts = _prompt_dir(tmp_path)
    _reset_registry(monkeypatch, prompts)
    before = mg.write_prompt_version()

    (prompts / "merge-section.md").write_text("[merge-section] body, one more rule")
    _reset_registry(monkeypatch, prompts)

    assert mg.write_prompt_version() != before


def test_section_merge_mode_off_disables_the_section_path(monkeypatch):
    """KB_MERGE_SECTION_MODE is the section path's rollback knob: off must
    restore the pre-section dispatch exactly."""
    monkeypatch.setenv(mg._SECTION_MERGE_MODE_ENV, "off")
    assert mg._section_merge_enabled() is False


def test_section_merge_mode_default_and_auto_enable(monkeypatch):
    monkeypatch.delenv(mg._SECTION_MERGE_MODE_ENV, raising=False)
    assert mg._section_merge_enabled() is True
    monkeypatch.setenv(mg._SECTION_MERGE_MODE_ENV, "auto")
    assert mg._section_merge_enabled() is True


def test_section_merge_mode_invalid_warns_once_and_falls_back_to_auto(monkeypatch, capsys):
    mg._warn_invalid_section_merge_mode.cache_clear()
    monkeypatch.setenv(mg._SECTION_MERGE_MODE_ENV, "sometimes")

    assert mg._section_merge_enabled() is True
    assert mg._section_merge_enabled() is True

    err = capsys.readouterr().err
    assert err.count(mg._SECTION_MERGE_MODE_ENV) == 1
    assert "sometimes" in err


def _reset_section_sem(monkeypatch):
    """Drop the cached semaphore so a test reads the env afresh (the cache is
    keyed on the bound; the conftest autouse fixture already deletes the env
    per test, but the cached object would otherwise outlive the test that
    sized it)."""
    monkeypatch.delenv(mg._SECTION_CONCURRENCY_ENV, raising=False)
    mg._section_call_sem = None
    mg._section_call_sem_bound = 0


def test_section_semaphore_defaults_to_twelve_and_caches(monkeypatch):
    _reset_section_sem(monkeypatch)

    sem = mg._get_section_sem()

    assert mg._section_call_sem_bound == 12
    assert sem is mg._get_section_sem()


def test_section_semaphore_reads_the_env_and_resizes_when_it_changes(monkeypatch):
    _reset_section_sem(monkeypatch)
    monkeypatch.setenv(mg._SECTION_CONCURRENCY_ENV, "3")
    tight = mg._get_section_sem()
    assert mg._section_call_sem_bound == 3

    monkeypatch.setenv(mg._SECTION_CONCURRENCY_ENV, "5")
    wider = mg._get_section_sem()

    assert mg._section_call_sem_bound == 5
    assert wider is not tight
    assert wider is mg._get_section_sem()


@pytest.mark.parametrize("raw", ["not-a-number", "0", "-4"],
                         ids=["unparseable", "zero", "negative"])
def test_section_semaphore_invalid_env_warns_once_and_uses_the_default(
        monkeypatch, capsys, raw):
    """A bound below 1 would deadlock every section call on the semaphore, so
    it is as invalid as a typo: warn once, use the default."""
    mg._warn_invalid_section_concurrency.cache_clear()
    _reset_section_sem(monkeypatch)
    monkeypatch.setenv(mg._SECTION_CONCURRENCY_ENV, raw)

    assert mg._get_section_sem() is not None
    assert mg._section_call_sem_bound == 12
    mg._get_section_sem()

    err = capsys.readouterr().err
    assert err.count(mg._SECTION_CONCURRENCY_ENV) == 1


_ROUTER_ARTICLE = """---
title: T
---

Intro preamble.

## Alpha

alpha body

## Beta

beta body

## Gamma

gamma body
"""


def test_route_sections_happy_path(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured.update(kwargs)
        return {"sections": ["## Gamma", "## Alpha", "## Gamma"],
                "new_sections": [{"heading": "## Delta", "after": "## Beta"}]}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    extraction = _extraction(summary="a summary", topics=["alpha", "delta"],
                             concepts=[{"title": "c1"}, {"title": "c2"}])
    out = mg._route_sections(_ROUTER_ARTICLE, extraction, "raw/a.md", "m")

    # Duplicates collapse, headings come back as the article's own strings.
    assert out == {"sections": ["## Gamma", "## Alpha"],
                   "new_sections": [{"heading": "## Delta", "after": "## Beta"}]}
    assert captured["max_tokens"] == 1024
    user = captured["messages"][1]["content"]
    assert "1. ## Alpha" in user
    assert "3. ## Gamma" in user
    assert "a summary" in user
    assert "alpha, delta" in user


def test_route_sections_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return {"sections": [], "new_sections": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    mg._route_sections(_ROUTER_ARTICLE, _extraction(), "raw/a.md", "m")

    assert captured["system"] == mg._merge_section_router_system()


@pytest.mark.parametrize("failure", [
    json.JSONDecodeError("bad", "{}", 0),
    RuntimeError("llm down"),
    mg.OutputTruncatedError("still truncated at ceiling"),
], ids=["json-decode-error", "runtime-error", "truncated-ladder"])
def test_route_sections_returns_none_on_call_failure(monkeypatch, failure):
    def boom(**kwargs):
        raise failure

    monkeypatch.setattr(mg, "completion_json", boom)

    assert mg._route_sections(
        _ROUTER_ARTICLE, _extraction(), "raw/a.md", "m") is None


@pytest.mark.parametrize("raw", [
    ["not", "a", "dict"],
    {"unrelated": True},
    {"sections": [], "new_sections": []},
    {"sections": ["## Nope"],
     "new_sections": [{"heading": "## N", "after": "## Also Nope"}]},
], ids=["non-dict", "missing-both-fields", "legitimately-empty", "everything-unknown"])
def test_route_sections_returns_none_when_nothing_valid_survives(monkeypatch, raw):
    """None is the degrade signal: the caller falls through to the legacy chain
    rather than silently merging nothing, including for the router that answers
    with empty lists (it saw a digest, not the full extraction, so "nothing
    fits" is not trusted the way a diff path's legitimate {"patches": []} is)."""
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: raw)

    assert mg._route_sections(
        _ROUTER_ARTICLE, _extraction(), "raw/a.md", "m") is None


def test_route_sections_drops_unknown_headings_with_an_alert(monkeypatch, capsys):
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "sections": ["## Alpha", "## Nope"],
        "new_sections": [
            {"heading": "## Delta", "after": "## Beta"},
            {"heading": "## Epsilon", "after": "## Missing"},
            {"heading": "", "after": "## Beta"},
        ],
    })

    out = mg._route_sections(_ROUTER_ARTICLE, _extraction(), "raw/a.md", "m")

    assert out == {"sections": ["## Alpha"],
                   "new_sections": [{"heading": "## Delta", "after": "## Beta"}]}
    err = capsys.readouterr().err
    assert err.count("section_route_dropped") == 3


def test_concurrent_router_calls_are_bounded_by_the_semaphore(monkeypatch):
    """Opt #1: the router's LLM call runs under _get_section_sem(), so the
    section path cannot multiply the write phase's concurrent calls past the
    bound (default 12). Barrier-style: each mocked call blocks until exactly
    the bound's worth of callers are inside together, so 16 queued callers can
    only finish if at most 12 are inside at once -- a 13th would strand the
    rendezvous at a lower peak and fail the peak assertion."""
    _reset_section_sem(monkeypatch)

    bound = 12
    callers = 16
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    over_bound: list[int] = []
    all_inside = threading.Event()

    def fake_completion_json(**kwargs):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            if state["active"] > bound:
                over_bound.append(state["active"])
            if state["active"] == bound:
                all_inside.set()
        all_inside.wait(timeout=10)
        with lock:
            state["active"] -= 1
        return {"sections": [], "new_sections": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    threads = [threading.Thread(
        target=mg._route_sections,
        args=(_ROUTER_ARTICLE, _extraction(), "raw/a.md", "m"))
        for _ in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads)
    assert all_inside.is_set()
    assert state["peak"] == bound
    assert not over_bound


# ── section-merge machinery and dispatch (F2b-2) ─────────────────────

def _section_article(body_chars=3_200, names=("Alpha", "Beta", "Gamma", "Delta")):
    """A >=12K-byte article with frontmatter, a preamble, and named ##
    sections -- over _SECTION_MERGE_MIN_BYTES at the default size, under the
    diff threshold, each body carrying a per-section filler token so tests
    can tell a kept body from a rewritten one."""
    parts = ["---\ntitle: T\nsources:\n  - raw/first.md\n---\n\nIntro preamble.\n"]
    for name in names:
        filler = f"[{name}-filler] " * (body_chars // (len(name) + 10))
        parts.append(f"\n## {name}\n\n{filler}{name} body\n")
    return "".join(parts)


@pytest.fixture
def spy_section(monkeypatch):
    """Record _merge_sections runs and hand back a healthy result, so dispatch
    tests observe routing without paying the machinery."""
    runs: list[str] = []

    def fake_sections(article_path, article_content, extraction, source_path, model):
        runs.append(article_path)
        return "sectioned", False

    monkeypatch.setattr(mg, "_merge_sections", fake_sections)
    return runs


def test_a_qualifying_article_takes_the_section_path(spy_modes, spy_section):
    out = mg.merge_into_article("wiki/a.md", _section_article(),
                                _extraction(), "raw/a.md")

    assert out == "sectioned"
    assert spy_section == ["wiki/a.md"]
    assert "mode" not in spy_modes  # neither legacy path ran


def test_an_over_size_article_still_qualifies_for_the_section_path(
        spy_modes, spy_section):
    """The section path sits ahead of both legacy legs, so a >=30K article
    with sections also merges at section granularity; only its degraded
    fallback is the diff."""
    out = mg.merge_into_article("wiki/a.md", _section_article(body_chars=8_000),
                                _extraction(), "raw/a.md")

    assert out == "sectioned"
    assert spy_section == ["wiki/a.md"]
    assert "mode" not in spy_modes


def test_below_the_section_threshold_stays_on_the_full_rewrite(spy_modes, spy_section):
    mg.merge_into_article("wiki/a.md", _section_article(body_chars=2_000),
                          _extraction(), "raw/a.md")

    assert spy_modes["mode"] == "rewrite"
    assert spy_section == []


def test_fewer_than_three_sections_stay_on_the_legacy_chain(spy_modes, spy_section):
    article = _section_article(body_chars=7_000, names=("Alpha", "Beta"))
    assert len(article.encode("utf-8")) >= mg._SECTION_MERGE_MIN_BYTES

    mg.merge_into_article("wiki/a.md", article, _extraction(), "raw/a.md")

    assert spy_modes["mode"] == "rewrite"
    assert spy_section == []


def test_a_prompt_overflow_article_skips_the_section_path(monkeypatch, spy_modes,
                                                          spy_section):
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 5_000)

    mg.merge_into_article("wiki/a.md", _section_article(), _extraction(), "raw/a.md")

    assert spy_modes["mode"] == "diff"
    assert spy_section == []


def test_section_mode_off_restores_the_pre_section_dispatch(monkeypatch, spy_modes,
                                                            spy_section):
    """Rollback safety: KB_MERGE_SECTION_MODE=off must leave observable
    dispatch exactly as it was before the section path existed -- a 12K-30K
    article rewrites whole, an over-size article diffs."""
    monkeypatch.setenv(mg._SECTION_MERGE_MODE_ENV, "off")

    mg.merge_into_article("wiki/a.md", _section_article(), _extraction(), "raw/a.md")
    assert spy_modes["mode"] == "rewrite"

    spy_modes.pop("mode")
    mg.merge_into_article("wiki/b.md", _section_article(body_chars=8_000),
                          _extraction(), "raw/a.md")
    assert spy_modes["mode"] == "diff"
    assert spy_section == []


def test_a_degraded_section_merge_falls_back_to_the_full_rewrite_once(monkeypatch):
    """A 12K-30K article's legacy fallback leg is the full rewrite (§3.3 step
    5), paid exactly once -- no loop back into the section path."""
    calls: list[str] = []

    monkeypatch.setattr(mg, "_merge_sections",
                        lambda *a: (calls.append("section"), ("kept", True))[1])
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    def must_not_diff(*args):
        raise AssertionError("a 12K-30K article falls back to the rewrite, not the diff")

    monkeypatch.setattr(mg, "_merge_diff", must_not_diff)

    out = mg.merge_into_article("wiki/a.md", _section_article(),
                                _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["section", "rewrite"]


def test_a_degraded_section_merge_on_an_over_size_article_falls_back_to_diff(
        monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(mg, "_merge_sections",
                        lambda *a: (calls.append("section"), ("kept", True))[1])
    monkeypatch.setattr(mg, "_merge_diff",
                        lambda *a: (calls.append("diff"), ("diffed", False))[1])

    def must_not_rewrite(*args):
        raise AssertionError("an over-size article never pays a full rewrite")

    monkeypatch.setattr(mg, "_merge_full_rewrite", must_not_rewrite)

    out = mg.merge_into_article("wiki/a.md", _section_article(body_chars=8_000),
                                _extraction(), "raw/a.md")

    assert out == "diffed"
    assert calls == ["section", "diff"]


def test_a_router_failure_runs_the_full_rewrite_exactly_once(monkeypatch, capsys):
    """End to end through the real _route_sections: the router call fails, the
    fallback line is logged, and the legacy rewrite leg runs once."""
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(mg, "completion_json", boom)
    calls: list[str] = []
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    out = mg.merge_into_article("wiki/a.md", _section_article(),
                                _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["rewrite"]
    assert "[merge] section-merge fallback: wiki/a.md:" in capsys.readouterr().err


@pytest.mark.parametrize("exc", [
    EmptyCompletionError("LLM returned an empty body twice"),
    DeadlineExceededError("deadline_too_close to continue"),
], ids=["empty-completion", "deadline-exceeded"])
def test_router_kb_errors_degrade_to_the_legacy_chain(monkeypatch, capsys, exc):
    """EmptyCompletionError and DeadlineExceededError inherit KBError, not
    RuntimeError, so the router's degrade tuple names them explicitly --
    otherwise the escape is swallowed per-article by the write phase's generic
    handler and the task Acks as an error instead of falling back (the
    empty-body mode was measured on deepseek-v4-flash, the deadline mode
    exists only on batched calls)."""
    def boom(**kwargs):
        raise exc

    monkeypatch.setattr(mg, "completion_json", boom)
    calls: list[str] = []
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    out = mg.merge_into_article("wiki/a.md", _section_article(),
                                _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["rewrite"]
    assert "[merge] section-merge fallback: wiki/a.md:" in capsys.readouterr().err


def test_an_empty_completion_in_the_diff_degrades_to_the_full_rewrite(
        monkeypatch, capsys):
    """Same contract on the diff leg: an EmptyCompletionError from the patch
    call marks the response degraded, and an article that fits the rewrite
    budget pays the rewrite rather than Acking unmerged."""
    def boom(**kwargs):
        raise EmptyCompletionError("LLM returned an empty body twice")

    monkeypatch.setattr(mg, "completion_json", boom)
    calls: list[str] = []
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    out = mg.merge_into_article("wiki/a.md", big, _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["rewrite"]
    assert "[merge] diff result unparsable, falling back to full-rewrite" in capsys.readouterr().err


def test_duplicate_headings_degrade_to_the_legacy_chain(monkeypatch, capsys):
    """Two sections sharing one heading line: the section path keys bodies by
    heading text, so proceeding would replace BOTH occurrences with one
    rewrite built from the last body -- silently deleting the first
    occurrence's content on disk. The guard fires before the router call."""
    article = _section_article(body_chars=6_000, names=("Alpha", "Beta", "Gamma"))
    article += "\n## Alpha\n\nSECOND alpha body\n"
    assert len(article.encode("utf-8")) >= mg._SECTION_MERGE_MIN_BYTES

    def must_not_route(*args):
        raise AssertionError("the duplicate guard must fire before the router call")

    monkeypatch.setattr(mg, "_route_sections", must_not_route)
    calls: list[str] = []
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    out = mg.merge_into_article("wiki/a.md", article, _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert calls == ["rewrite"]
    assert "duplicate ## headings" in capsys.readouterr().err


def test_merge_one_section_strips_only_a_true_heading_echo(monkeypatch):
    """The echo strip requires the heading's own newline: "## Notes"
    prefix-matching a different echoed heading ("## Notes on X") used to eat
    the start of the section body."""
    monkeypatch.setattr(mg, "completion", lambda **kwargs: "## Notes on X\n\nkept body")
    out = mg._merge_one_section("## Notes", "old body", _extraction(),
                                "raw/a.md", "m", mg.MAX_PROMPT_CHARS)
    assert out == "## Notes on X\n\nkept body"

    monkeypatch.setattr(mg, "completion", lambda **kwargs: "## Notes\n\nrewritten body")
    out = mg._merge_one_section("## Notes", "old body", _extraction(),
                                "raw/a.md", "m", mg.MAX_PROMPT_CHARS)
    assert out == "rewritten body"


@pytest.mark.parametrize("echo", [
    "## Notes \n\nrewritten body",   # trailing space on the echoed line
    "## Notes\r\n\nrewritten body",  # CRLF line ending
], ids=["trailing-space", "crlf"])
def test_merge_one_section_recognizes_a_whitespace_padded_echo(monkeypatch, echo):
    """An echo whose line differs only in trailing whitespace must still be
    stripped: a heading that slips through renders twice, and the duplicate
    then trips the duplicate-heading guard on every later merge of the
    article."""
    monkeypatch.setattr(mg, "completion", lambda **kwargs: echo)
    out = mg._merge_one_section("## Notes", "old body", _extraction(),
                                "raw/a.md", "m", mg.MAX_PROMPT_CHARS)
    assert out == "rewritten body"


def test_route_sections_drops_duplicate_new_section_headings(monkeypatch, capsys):
    """New-section bodies are keyed by heading downstream, so a proposed
    heading duplicating the article's own sections or another proposal would
    overwrite one body and insert another twice (or mint a duplicate heading
    on disk). Both shapes drop with an alert; the valid proposal survives."""
    route = {
        "sections": [],
        "new_sections": [
            {"heading": "## Alpha", "after": "## Beta"},          # existing
            {"heading": "## Fresh", "after": "## Beta"},          # valid
            {"heading": "## Fresh", "after": "## Gamma"},         # duplicate proposal
        ],
    }
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: route)

    out = mg._route_sections(_section_article(), _extraction(), "raw/a.md", "m")

    assert out == {"sections": [], "new_sections": [
        {"heading": "## Fresh", "after": "## Beta"}]}
    err = capsys.readouterr().err
    assert err.count("section_route_dropped") == 2


def test_a_section_failing_twice_degrades_after_one_retry(monkeypatch, capsys):
    attempts = {"n": 0}

    def boom(**kwargs):
        attempts["n"] += 1
        raise RuntimeError("llm down")

    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha"], "new_sections": []})
    monkeypatch.setattr(mg, "completion", boom)
    calls: list[str] = []
    monkeypatch.setattr(mg, "_merge_full_rewrite",
                        lambda *a: (calls.append("rewrite"), "rewritten")[1])

    out = mg.merge_into_article("wiki/a.md", _section_article(),
                                _extraction(), "raw/a.md")

    assert out == "rewritten"
    assert attempts["n"] == 2  # one retry, then degrade -- never a third attempt
    assert calls == ["rewrite"]
    err = capsys.readouterr().err
    assert "[merge] section-merge fallback: wiki/a.md:" in err
    assert "failed twice" in err


def test_merge_sections_happy_path_reassembly(monkeypatch, capsys):
    """The reassembly is deterministic over _parse_sections: untouched sections
    and the preamble survive with their own text, the routed section's body is
    swapped in, the new section lands after its anchor, and the frontmatter
    pass runs on the assembled result."""
    article = _section_article()
    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha"],
        "new_sections": [{"heading": "## Epsilon", "after": "## Beta"}],
    })
    monkeypatch.setattr(mg, "completion", lambda **kwargs: "rewritten body")

    result, degraded = mg._merge_sections(
        "wiki/a.md", article, _extraction(summary="new fact"), "raw/a.md", "m")

    assert degraded is False
    # Kept bodies carry their filler verbatim; the rewritten one does not.
    assert "[Beta-filler]" in result
    assert "[Gamma-filler]" in result and "[Delta-filler]" in result
    assert "[Alpha-filler]" not in result
    assert "rewritten body" in result
    # Preamble text survives and the frontmatter pass refreshed it.
    assert "Intro preamble." in result
    assert f"updated: {TODAY}" in result
    assert "  - raw/first.md" in result and "  - raw/a.md" in result
    # Order: Alpha rewritten in place, Epsilon after Beta and before Gamma.
    assert (result.index("## Alpha") < result.index("## Beta")
            < result.index("## Epsilon") < result.index("## Gamma"))
    err = capsys.readouterr().err
    assert "[merge] section-merge: wiki/a.md (1/4 sections, +1 new)" in err


def test_reassembly_leaves_untouched_parts_byte_identical(monkeypatch):
    """Byte-level pin of the reassembly: the exact article comes back with
    only the routed body swapped, the new section inserted after its anchor,
    and the frontmatter keys the pass touches changed."""
    article = (
        "---\ntitle: T\nsources:\n  - raw/first.md\n---\n\n"
        "Intro preamble.\n"
        "\n## Alpha\n\nalpha body\n"
        "\n## Beta\n\nbeta body\n"
        "\n## Gamma\n\ngamma body\n"
        "\n## Delta\n\ndelta body\n"
    )
    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha"],
        "new_sections": [{"heading": "## New", "after": "## Beta"}],
    })

    def fake_completion(**kwargs):
        user = kwargs["messages"][1]["content"]
        return "REWRITTEN" if "alpha body" in user else "NEWBODY"

    monkeypatch.setattr(mg, "completion", fake_completion)

    result, degraded = mg._merge_sections(
        "wiki/a.md", article, _extraction(summary="s"), "raw/new.md", "m")

    assert degraded is False
    expected = (
        "---\ntitle: T\nsources:\n  - raw/first.md\n  - raw/new.md\n"
        f"updated: {TODAY}\n---\n\n"
        "Intro preamble.\n\n"
        "## Alpha\n\nREWRITTEN\n"
        "\n## Beta\n\nbeta body\n"
        "\n## New\n\nNEWBODY\n"
        "\n## Gamma\n\ngamma body\n"
        "\n## Delta\n\ndelta body\n"
    )
    assert result == expected


def test_the_coverage_guard_skips_to_the_legacy_chain(monkeypatch, capsys):
    """High affinity: past 60% of sections touched, the guard trips after the
    router call -- one wasted 1024-token router call, counted by its own log
    line -- and no section rewrite is paid."""
    router_calls: list[bool] = []
    rewrites: list[bool] = []

    def fake_route(*a):
        router_calls.append(True)
        return {"sections": ["## Alpha", "## Beta", "## Gamma"],
                "new_sections": []}

    monkeypatch.setattr(mg, "_route_sections", fake_route)
    monkeypatch.setattr(mg, "completion",
                        lambda **kw: rewrites.append(True) or "body")

    article = _section_article()
    result, degraded = mg._merge_sections(
        "wiki/a.md", article, _extraction(), "raw/a.md", "m")

    assert degraded is True
    assert result is article
    assert router_calls == [True]
    assert rewrites == []
    err = capsys.readouterr().err
    assert "[merge] section-merge guard: wiki/a.md:" in err
    assert "60%" in err


def test_the_sized_guard_trips_when_the_extraction_dominates(monkeypatch, capsys):
    """Every section call carries the whole extraction, so a fat extraction
    routed into several sections expects more generated tokens than one full
    rewrite -- the sized half of the guard."""
    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha", "## Beta"], "new_sections": []})

    def must_not_run(**kwargs):
        raise AssertionError("the guard must trip before any section rewrite")

    monkeypatch.setattr(mg, "completion", must_not_run)

    result, degraded = mg._merge_sections(
        "wiki/a.md", _section_article(), _extraction(summary="s" * 12_000),
        "raw/a.md", "m")

    assert degraded is True
    err = capsys.readouterr().err
    assert "[merge] section-merge guard: wiki/a.md:" in err
    assert "exceeds the sized full rewrite" in err


def test_an_empty_section_rewrite_is_retried_then_recovers(monkeypatch):
    """A model returning an empty body would silently delete the section's
    content in the reassembly, so it is one more retryable failure."""
    responses = iter(["", "real body"])

    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha"], "new_sections": []})
    monkeypatch.setattr(mg, "completion", lambda **kw: next(responses))

    result, degraded = mg._merge_sections(
        "wiki/a.md", _section_article(), _extraction(), "raw/a.md", "m")

    assert degraded is False
    assert "real body" in result


def test_section_calls_adopt_the_callers_context(fresh_context, monkeypatch):
    """Pool workers must carry the write phase's context (phase label,
    call_timeout) into their LLM calls -- the issue #26 lesson: a worker on a
    default context reports op=unknown and loses the timeout."""
    from kb_ai._context import get_context

    ctx = fresh_context
    ctx.phase = "write:wiki/a.md"
    ctx.call_timeout = 123.0
    seen: dict = {}

    def fake_completion(**kwargs):
        current = get_context()
        seen["phase"] = current.phase
        seen["call_timeout"] = current.call_timeout
        return "body"

    monkeypatch.setattr(mg, "_route_sections", lambda *a: {
        "sections": ["## Alpha"], "new_sections": []})
    monkeypatch.setattr(mg, "completion", fake_completion)

    mg._merge_sections("wiki/a.md", _section_article(), _extraction(),
                       "raw/a.md", "m")

    assert seen == {"phase": "write:wiki/a.md", "call_timeout": 123.0}


def _barriered_completion(expected: int, state: dict, all_inside: threading.Event,
                          over_cap: list[int], lock: threading.Lock):
    """A completion mock that only returns once exactly `expected` callers are
    inside together -- copied from the router test's rendezvous pattern."""
    def fake_completion(**kwargs):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            if state["active"] > expected:
                over_cap.append(state["active"])
            if state["active"] == expected:
                all_inside.set()
        all_inside.wait(timeout=10)
        with lock:
            state["active"] -= 1
        return "body"
    return fake_completion


def _five_task_article():
    names = tuple(f"S{i}" for i in range(10))
    return _section_article(body_chars=1_300, names=names), \
        [f"## S{i}" for i in (0, 2, 4, 6, 8)]


def test_the_per_merge_pool_is_capped_at_four(monkeypatch):
    """min(_SECTION_POOL_CAP, tasks) bounds one article's fan-out even with the
    process-wide semaphore loose (default 12): five section tasks can only
    ever have four calls in flight together."""
    _reset_section_sem(monkeypatch)
    article, routed = _five_task_article()
    monkeypatch.setattr(mg, "_route_sections",
                        lambda *a: {"sections": routed, "new_sections": []})

    expected = 4
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    over_cap: list[int] = []
    all_inside = threading.Event()
    monkeypatch.setattr(mg, "completion",
                        _barriered_completion(expected, state, all_inside, over_cap, lock))

    result, degraded = mg._merge_sections(
        "wiki/a.md", article, _extraction(), "raw/a.md", "m")

    assert degraded is False
    assert all_inside.is_set()
    assert state["peak"] == expected
    assert not over_cap


def test_section_calls_are_bounded_by_the_semaphore(monkeypatch):
    """The pool cap alone is not the bound -- the process-wide semaphore is.
    With the bound at 2 and five tasks on a pool of four, at most two calls
    are in flight together."""
    _reset_section_sem(monkeypatch)
    monkeypatch.setenv(mg._SECTION_CONCURRENCY_ENV, "2")
    article, routed = _five_task_article()
    monkeypatch.setattr(mg, "_route_sections",
                        lambda *a: {"sections": routed, "new_sections": []})

    expected = 2
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    over_cap: list[int] = []
    all_inside = threading.Event()
    monkeypatch.setattr(mg, "completion",
                        _barriered_completion(expected, state, all_inside, over_cap, lock))

    result, degraded = mg._merge_sections(
        "wiki/a.md", article, _extraction(), "raw/a.md", "m")

    assert degraded is False
    assert all_inside.is_set()
    assert state["peak"] == expected
    assert not over_cap


def test_merge_one_section_sizes_continues_and_strips_the_echo(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "```markdown\n## Alpha\n\nmerged body\n```"

    monkeypatch.setattr(mg, "completion", fake_completion)
    extraction = _extraction(summary="s" * 100)

    out = mg._merge_one_section("## Alpha", "old body", extraction,
                                "raw/a.md", "m", 10_000)

    assert out == "merged body"  # the fence and the echoed heading are stripped
    assert captured["continue_on_length"] is True
    assert captured["cache"] is True
    assert captured["max_tokens"] == mg.estimate_max_tokens(
        len("old body") + mg._estimate_full_extraction_size(extraction, "raw/a.md"),
        minimum=4096)
    assert captured["messages"][0]["content"] == mg._merge_section_system()
    user = captured["messages"][1]["content"]
    assert "## Alpha" in user and "old body" in user
    assert "- Source: raw/a.md" in user


def test_merge_one_section_for_a_new_section_carries_the_anchor(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "new section body"

    monkeypatch.setattr(mg, "completion", fake_completion)

    out = mg._merge_one_section("## Epsilon", "", _extraction(summary="s"),
                                "raw/a.md", "m", 10_000, after="## Beta")

    assert out == "new section body"
    user = captured["messages"][1]["content"]
    assert "## Epsilon" in user
    assert "## Beta" in user


def test_merge_into_article_section_path_end_to_end(monkeypatch, capsys):
    """Acceptance, end to end: a >=12K-byte, >=3-section article in auto mode
    merges at section granularity through the real router and reassembly --
    untouched parts byte-identical, frontmatter refreshed, the section-merge
    line logged."""
    article = _section_article()

    def fake_completion_json(**kwargs):
        return {"sections": ["## Gamma"],
                "new_sections": [{"heading": "## Zeta", "after": "## Delta"}]}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)
    monkeypatch.setattr(mg, "completion", lambda **kwargs: "merged section")

    out = mg.merge_into_article("wiki/a.md", article,
                                _extraction(summary="s"), "raw/a.md")

    assert "[Alpha-filler]" in out and "[Beta-filler]" in out
    assert "[Delta-filler]" in out
    assert "[Gamma-filler]" not in out
    assert "merged section" in out
    assert "Intro preamble." in out
    assert f"updated: {TODAY}" in out
    assert "  - raw/first.md" in out and "  - raw/a.md" in out
    assert out.index("## Delta") < out.index("## Zeta")
    err = capsys.readouterr().err
    assert "[merge] section-merge: wiki/a.md (1/4 sections, +1 new)" in err


# ── write-phase call timeout ────────────────────────────────────────

def test_with_write_timeout_sets_and_restores(fresh_context):
    from kb_ai.llm import get_call_timeout, set_call_timeout

    observed = {}

    @mg._with_write_timeout
    def probe():
        observed["inside"] = get_call_timeout()

    set_call_timeout(42.0)
    probe()

    assert observed["inside"] == mg._WRITE_CALL_TIMEOUT_S
    # Restoring to the previous value (not None) keeps nesting safe.
    assert get_call_timeout() == 42.0


def test_with_write_timeout_restores_on_exception(fresh_context):
    from kb_ai.llm import get_call_timeout, set_call_timeout

    @mg._with_write_timeout
    def boom():
        raise RuntimeError("x")

    set_call_timeout(7.0)
    with pytest.raises(RuntimeError):
        boom()

    assert get_call_timeout() == 7.0


def test_with_write_timeout_preserves_metadata():
    @mg._with_write_timeout
    def documented():
        """A docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "A docstring."


def test_write_timeout_sits_between_extract_and_the_client_default():
    """The point of the override: discover a hung write in minutes, not 15.

    Above extract's, because a merge prompt carries the whole existing article
    where an extract prompt carries one document's chunk; below the client
    default, because that is the number this override exists to replace.
    """
    from kb_ai.core.extract import _EXTRACT_CALL_TIMEOUT_S
    from kb_ai.llm._infra import DEFAULT_CLIENT_TIMEOUT_S

    assert _EXTRACT_CALL_TIMEOUT_S < mg._WRITE_CALL_TIMEOUT_S < DEFAULT_CLIENT_TIMEOUT_S


def test_the_default_is_unchanged_by_adding_the_override():
    """Hardcoded, and deliberately still 300.

    A local 27B model needs longer than this -- a 9-source merge was measured at
    348.8s -- but raising the default would double the worst case for everyone:
    _TIMEOUT_RETRIES gives three attempts, so 300 costs at most 930s to discover a
    hung gateway where 600 would cost 1830s. The override carries that case
    instead, so this pins that the shared default did not move.
    """
    assert mg._write_call_timeout() == 300.0


def test_a_slower_model_can_raise_the_write_timeout(monkeypatch):
    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", "1200.5")

    assert mg._write_call_timeout() == 1200.5


def test_the_write_timeout_is_read_per_call_not_frozen_at_import(
    fresh_context, monkeypatch
):
    """Whoever launches a compile sets the env var, usually long after import.

    The neighbouring MAX_PROMPT_CHARS knob reads os.environ at import time; doing
    the same here would make the override depend on import order.
    """
    from kb_ai.llm import get_call_timeout

    observed = []

    @mg._with_write_timeout
    def probe():
        observed.append(get_call_timeout())

    probe()
    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", "1500")
    probe()

    assert observed == [300.0, 1500.0]


@pytest.mark.parametrize("junk", ["abc", "300s", "1200ms", "0", "-5", "nan", "inf"])
def test_an_unusable_write_timeout_falls_back_to_the_default(monkeypatch, junk):
    """A typo must not decide how a compile behaves.

    '0' and '-5' would fail every write call instantly; 'inf' would silently
    remove the cap that this override exists to impose. '300s' and '1200ms' are
    the plausible typos, given the _S suffix in the variable's own name.
    """
    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", junk)

    assert mg._write_call_timeout() == 300.0


def test_an_unusable_write_timeout_says_so_once(monkeypatch, capsys):
    """Silence here means believing an override took effect when it did not.

    Matches _cost.py's handling of a malformed KB_AI_PRICING: warn to stderr,
    ignore the value, carry on -- and once per value, not once per write call.
    """
    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", "1200ms")
    mg._write_call_timeout()
    mg._write_call_timeout()

    warnings = [line for line in capsys.readouterr().err.splitlines()
                if "KB_AI_WRITE_TIMEOUT_S" in line]
    assert len(warnings) == 1
    # The value has to appear, or the reader cannot tell which typo was ignored.
    assert "1200ms" in warnings[0]
    assert "300" in warnings[0]


def test_a_usable_write_timeout_is_not_warned_about(monkeypatch, capsys):
    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", "900")
    assert mg._write_call_timeout() == 900.0
    assert "KB_AI_WRITE_TIMEOUT_S" not in capsys.readouterr().err


def test_an_absent_write_timeout_is_not_warned_about(capsys):
    """Unset is the normal case, not a misconfiguration."""
    assert mg._write_call_timeout() == 300.0
    assert capsys.readouterr().err == ""


def test_create_new_article_applies_the_write_timeout(fresh_context, monkeypatch):
    from kb_ai.llm import get_call_timeout

    seen = {}

    def fake_completion(**kwargs):
        seen["timeout"] = get_call_timeout()
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("concept", "T", _extraction(), "raw/a.md")

    assert seen["timeout"] == mg._WRITE_CALL_TIMEOUT_S
    assert get_call_timeout() is None, "the override must not leak past the call"


def test_merge_into_article_applies_the_write_timeout_on_the_rewrite_path(
    fresh_context, monkeypatch
):
    from kb_ai.llm import get_call_timeout

    seen = {}

    def fake_completion(**kwargs):
        seen["timeout"] = get_call_timeout()
        return "merged"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.merge_into_article("wiki/a.md", "short body", _extraction(), "raw/a.md")

    assert seen["timeout"] == mg._WRITE_CALL_TIMEOUT_S
    assert get_call_timeout() is None


def test_merge_into_article_applies_the_write_timeout_on_the_diff_path(
    fresh_context, monkeypatch
):
    """The diff path calls completion_json, not completion, so it needs its own
    check -- the decorator sits on the public entry point that reaches both."""
    from kb_ai.llm import get_call_timeout

    seen = {}

    def fake_completion_json(**kwargs):
        seen["timeout"] = get_call_timeout()
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    big = "\n".join(f"## S{i}\n" + "x" * 2000 for i in range(20))
    assert len(big.encode("utf-8")) >= mg._LARGE_ARTICLE_THRESHOLD
    mg.merge_into_article("wiki/a.md", big, _extraction(topics=["s1"]), "raw/a.md")

    assert seen["timeout"] == mg._WRITE_CALL_TIMEOUT_S
    assert get_call_timeout() is None


def _drive_create(monkeypatch, record):
    monkeypatch.setattr(mg, "completion", lambda **kw: (record(), "article")[1])
    mg.create_new_article("concept", "T", _extraction(), "raw/a.md")


def _drive_merge_rewrite(monkeypatch, record):
    monkeypatch.setattr(mg, "completion", lambda **kw: (record(), "merged")[1])
    mg.merge_into_article("wiki/a.md", "short body", _extraction(), "raw/a.md")


def _drive_merge_diff(monkeypatch, record):
    monkeypatch.setattr(mg, "completion_json", lambda **kw: (record(), {"patches": []})[1])
    big = "\n".join(f"## S{i}\n" + "x" * 2000 for i in range(20))
    assert len(big.encode("utf-8")) >= mg._LARGE_ARTICLE_THRESHOLD
    mg.merge_into_article("wiki/a.md", big, _extraction(topics=["s1"]), "raw/a.md")


@pytest.mark.parametrize("drive", [_drive_create, _drive_merge_rewrite, _drive_merge_diff],
                         ids=["create", "merge_rewrite", "merge_diff"])
def test_a_raised_write_timeout_reaches_every_write_entry_point(
    drive, fresh_context, monkeypatch
):
    """The override has to arrive through the real functions, not just the decorator.

    The tests above drive a locally-decorated probe, so they would stay green if one
    of these three entry points lost its decorator or got a hardcoded default. 1800
    is deliberately above DEFAULT_CLIENT_TIMEOUT_S: an override is honoured verbatim
    rather than clamped to the client's default, and README.md tells operators to
    size the value from what they measure, which can exceed 900.
    """
    from kb_ai.llm import get_call_timeout

    monkeypatch.setenv("KB_AI_WRITE_TIMEOUT_S", "1800")
    seen = {}

    drive(monkeypatch, lambda: seen.setdefault("timeout", get_call_timeout()))

    assert seen["timeout"] == 1800.0
    assert get_call_timeout() is None, "the override must not leak past the call"
