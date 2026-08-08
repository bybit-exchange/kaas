"""Offline tests for article merging (kb_ai.core.merge).

The LLM seams are monkeypatched. The interesting logic here is all budget and
text surgery: fitting an extraction into a character budget, section-based
article truncation, choosing rewrite vs diff mode, and applying diff patches to
markdown without corrupting frontmatter.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

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
        return "diffed"

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

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "added" in out


def test_merge_diff_degrades_to_no_patches_on_bad_json(monkeypatch):
    """A model returning unparseable JSON must leave the article intact rather
    than dropping content."""
    def boom(**kwargs):
        raise json.JSONDecodeError("bad", "{}", 0)

    monkeypatch.setattr(mg, "completion_json", boom)

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "body" in out


def test_merge_diff_degrades_on_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(mg, "completion_json", boom)

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", _extraction(), "raw/a.md", "m")

    assert "body" in out


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
