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


def _block(extraction: ExtractionResult | None = None, *,
           source_path: str = "raw/a.md", day: date | None = None) -> mg.SourceBlock:
    """One source's block. Undated unless asked, so these tests render exactly
    what they did before per-source blocks existed: a `- Source:` line and the
    fields under it. Ordering and dates are pinned in test_core_merge_blocks.py.
    """
    return mg.SourceBlock(
        source_path=source_path,
        extraction=_extraction() if extraction is None else extraction,
        date=day,
    )


def _blocks(*source_paths: str) -> list[mg.SourceBlock]:
    """A payload named by path only, for the cases that care about `sources:`
    bookkeeping rather than about dates. _apply_diff takes blocks because RA3's
    order guard reads their dates; these tests emit no supersede action, so
    undated blocks say what the bare path list they replace used to say."""
    return [_block(source_path=path) for path in source_paths]


# ── _estimate_block_size ──────────────────────────────────

def test_estimate_size_skips_empty_fields():
    """The estimator must skip falsy fields exactly like
    _fit_block_to_budget does — otherwise an empty ExtractionResult is
    counted as eight `- Field: []` lines the output never emits, and every merge
    reports a truncation that never happened.
    """
    size = mg._estimate_block_size(_block(_extraction()))

    assert size == len("- Source: raw/a.md\n")


def test_estimate_matches_the_text_produced_with_an_ample_budget():
    """The invariant the estimator exists to satisfy: with a budget nothing can
    exceed, the estimate must equal the emitted length — otherwise the
    truncation warning fires on complete output (or stays silent on truncated
    output). Pins the two functions' skip rules and format strings together.
    """
    e = _extraction(summary="s", topics=["a", "b"], concepts=[{"title": "c"}])

    assert mg._estimate_block_size(_block(e)) == len(
        mg._fit_block_to_budget(_block(e), 1_000_000))


def test_estimate_size_grows_with_content():
    small = mg._estimate_block_size(_block(_extraction(summary="s")))
    large = mg._estimate_block_size(
        _block(_extraction(summary="s", topics=["a", "b"], concepts=[{"title": "c"}])))
    assert large > small


# ── _fit_block_to_budget ───────────────────────────────────────

def test_fit_extraction_includes_everything_when_budget_is_ample():
    out = mg._fit_block_to_budget(
        _block(_extraction(summary="a summary", topics=["t1"],
                           concepts=[{"title": "c1"}])), 10_000)

    assert "- Source: raw/a.md" in out
    assert "- Summary: a summary" in out
    assert "- Topics:" in out
    assert "- Concepts:" in out


def test_fit_extraction_zero_budget_is_empty():
    assert mg._fit_block_to_budget(_block(_extraction(summary="s")), 0) == ""


def test_fit_extraction_tiny_budget_truncates_the_source_prefix():
    out = mg._fit_block_to_budget(_block(_extraction(summary="s")), 5)
    assert out == "- Sou"


def test_fit_extraction_never_exceeds_the_budget():
    big = _extraction(
        summary="s" * 500,
        concepts=[{"title": f"c{i}", "summary": "x" * 100} for i in range(50)],
        topics=[f"t{i}" for i in range(50)],
    )
    for budget in (200, 500, 1000, 5000):
        out = mg._fit_block_to_budget(_block(big), budget)
        assert len(out) <= budget, f"budget {budget} exceeded: {len(out)}"


def test_fit_extraction_truncates_a_long_summary_string():
    out = mg._fit_block_to_budget(_block(_extraction(summary="s" * 10_000)), 300)

    assert len(out) <= 300
    assert "- Summary: sss" in out


def test_fit_extraction_halves_list_items_to_fit():
    """List fields back off by halving rather than being dropped entirely."""
    concepts = [{"title": f"concept number {i}", "summary": "y" * 60} for i in range(16)]
    out = mg._fit_block_to_budget(_block(_extraction(concepts=concepts)), 700)

    assert "- Concepts:" in out
    included = json.loads(out.split("- Concepts: ", 1)[1].strip())
    assert 0 < len(included) < 16
    # Backoff keeps a prefix of the original list.
    assert included[0]["title"] == "concept number 0"


def test_fit_extraction_respects_field_priority():
    """Summary outranks action_items, so a tight budget keeps the summary."""
    e = _extraction(summary="important summary",
                    action_items=[{"task": "z" * 200} for _ in range(5)])
    out = mg._fit_block_to_budget(_block(e), 120)

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
    out = mg._fit_block_to_budget(_block(e), 150)

    assert "Recover" in out
    assert "Concepts" not in out and "Claims" not in out


def test_fit_extraction_skips_empty_fields():
    out = mg._fit_block_to_budget(_block(_extraction(summary="s", topics=[])), 1000)
    assert "Topics" not in out


def test_fit_extraction_drops_a_string_field_that_cannot_fit_its_own_label():
    """When the leftover budget is smaller than the `- Summary: ` label itself,
    the field is skipped entirely — emitting a bare label with an empty (or
    negatively sliced) value would ship a misleading field to the model."""
    out = mg._fit_block_to_budget(_block(_extraction(summary="s" * 100)), 24)

    assert out == "- Source: raw/a.md\n"
    assert "Summary" not in out


def test_fit_extraction_warns_when_truncating(capsys):
    mg._fit_block_to_budget(_block(_extraction(summary="s" * 5000)), 300)
    assert "extraction truncated" in capsys.readouterr().err


def test_fit_extraction_silent_when_complete(capsys):
    mg._fit_block_to_budget(_block(_extraction(summary="short")), 10_000)
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

    def fake_rewrite(article_path, article_content, sources, model, events=None):
        chosen["mode"] = "rewrite"
        chosen["events"] = events
        return "rewritten"

    def fake_diff(article_path, article_content, sources, model, events=None):
        chosen["mode"] = "diff"
        chosen["events"] = events
        return "diffed"

    monkeypatch.setattr(mg, "_merge_full_rewrite", fake_rewrite)
    monkeypatch.setattr(mg, "_merge_diff", fake_diff)
    return chosen


def test_small_article_uses_full_rewrite(spy_modes):
    mg.merge_into_article("wiki/a.md", "short article", [_block()])
    assert spy_modes["mode"] == "rewrite"


def test_large_article_uses_diff(spy_modes):
    big = "x" * mg._LARGE_ARTICLE_THRESHOLD
    mg.merge_into_article("wiki/a.md", big, [_block()])
    assert spy_modes["mode"] == "diff"


def test_large_article_threshold_measured_in_utf8_bytes(spy_modes):
    """A CJK article is 3 bytes per character, so the byte threshold must trip
    well before the character count would."""
    chars = mg._LARGE_ARTICLE_THRESHOLD // 3 + 10
    mg.merge_into_article("wiki/a.md", "世" * chars, [_block()])
    assert spy_modes["mode"] == "diff"


def test_article_over_prompt_budget_uses_diff(monkeypatch, spy_modes):
    """Just under the size threshold but over the prompt budget still has to
    fall back to diff mode."""
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 5000)
    article = "x" * (mg._LARGE_ARTICLE_THRESHOLD - 1)

    mg.merge_into_article("wiki/a.md", article, [_block()])

    assert spy_modes["mode"] == "diff"


# ── _merge_user_message ─────────────────────────────────────────────

def test_merge_user_message_wraps_the_article():
    user = mg._merge_user_message("article body", [_block(_extraction(summary="s"))], 10_000)

    assert "<article>" in user and "</article>" in user
    assert "article body" in user
    assert "New information to merge." in user
    assert "- Source: raw/a.md" in user


def test_merge_user_message_hard_caps_at_budget():
    user = mg._merge_user_message("x" * 5000, [_block(_extraction(summary="s" * 5000))], 1000)
    assert len(user) == 1000


def test_merge_user_message_reserves_a_floor_for_the_extraction():
    """Even when the article eats the whole budget, some extraction text must
    survive — otherwise the merge call carries no new information."""
    user = mg._merge_user_message("x" * 900, [_block(_extraction(summary="new fact"))], 1000)
    assert len(user) == 1000


def test_merge_user_message_dates_each_block(monkeypatch):
    """WP1 at the merge site: `core/merge.py` rendered `- Source:` and nothing
    else, so no date reached the writer on any route -- an article composed from
    a plan and its revision had no way to tell which was current."""
    user = mg._merge_user_message("article body", [
        _block(_extraction(summary="older"), source_path="raw/a.md", day=date(2020, 1, 1)),
        _block(_extraction(summary="newer"), source_path="raw/b.md", day=date(2021, 1, 1)),
    ], 10_000)

    assert "- Source: raw/a.md\n- Date: 2020-01-01\n- Summary: older" in user
    assert "- Source: raw/b.md\n- Date: 2021-01-01\n- Summary: newer" in user


def test_merge_user_message_lists_every_source_for_the_frontmatter():
    """The merge prompt asks the model to add the source to the article's
    `sources:` list, and the flattened payload handed it one string to copy. With
    per-source blocks the paths are spread across N block headers, so they are
    also named as a list -- the same thing create_new_article's header does, and
    for the same reason: a source missing from `sources:` is a document `derive`
    then refuses to copy into a derived KB.
    """
    user = mg._merge_user_message("article body", [
        _block(_extraction(summary="older"), source_path="raw/a.md", day=date(2020, 1, 1)),
        _block(_extraction(summary="newer"), source_path="raw/b.md", day=date(2021, 1, 1)),
    ], 10_000)

    assert "Sources:\n  - raw/a.md\n  - raw/b.md\n" in user


def test_a_source_whose_block_was_dropped_is_still_listed():
    """The consequence BG2 accepts, pinned rather than only described: a block the
    budget could not hold is absent from the payload, and the article is still
    asked to name its source. `derive` reads that key to decide which raw
    documents a derived KB gets (derive/_sources.py), so dropping the name too
    would cost the document its only route into one -- at the price of an article
    naming a source the writer was shown nothing from."""
    user = mg._merge_user_message("article body", [
        _block(_extraction(summary="o" * 4000), source_path="raw/a.md", day=date(2020, 1, 1)),
        _block(_extraction(summary="n" * 4000), source_path="raw/b.md", day=date(2021, 1, 1)),
    ], 4600)

    assert "Sources:\n  - raw/a.md\n  - raw/b.md\n" in user
    assert "- Source: raw/a.md\n" not in user, "its block did not fit"
    assert "- Source: raw/b.md\n" in user


def test_merge_user_message_keeps_the_source_list_inside_the_budget():
    """The list is part of the message, so the blocks' budget has to pay for it."""
    user = mg._merge_user_message("x" * 900, [
        _block(_extraction(summary="s" * 500), source_path="raw/a-very-long-name.md"),
        _block(_extraction(summary="s" * 500), source_path="raw/b-very-long-name.md"),
    ], 1000)

    assert len(user) <= 1000


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
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/new.md"), TODAY)

    assert f"updated: {TODAY}" in out
    assert "updated: 2024-01-01" not in out
    assert "  - raw/old.md" in out
    assert "  - raw/new.md" in out


def test_apply_diff_appends_every_source_as_its_own_item():
    """The batch merge paths hand over several sources at once. Flattened, they
    arrived comma-joined and were written as one item -- `  - raw/a.md, raw/b.md`
    -- which no YAML reader resolves back to two paths, so the article's own
    provenance list was unusable for exactly the multi-source articles that need
    it most."""
    article = "---\ntitle: A\nsources:\n  - raw/old.md\n---\nbody\n"

    out, _ = mg._apply_diff(article, {"patches": []},
                         _blocks("raw/a.md", "raw/b.md"), TODAY)

    assert "  - raw/a.md\n" in out and "  - raw/b.md\n" in out
    assert "raw/a.md, raw/b.md" not in out
    assert out.index("  - raw/old.md") < out.index("  - raw/a.md")


def test_apply_diff_appends_only_the_sources_the_article_lacks():
    article = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"

    out, _ = mg._apply_diff(article, {"patches": []},
                         _blocks("raw/a.md", "raw/b.md"), TODAY)

    assert out.count("  - raw/a.md") == 1
    assert "  - raw/b.md" in out


def test_apply_diff_does_not_duplicate_an_existing_source():
    article = (
        "---\ntitle: A\nupdated: 2024-01-01\nsources:\n  - raw/a.md\n---\nbody\n"
    )
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/a.md"), TODAY)

    assert out.count("  - raw/a.md") == 1


def test_apply_diff_is_idempotent_for_a_repeated_source():
    """Re-merging the same source must not grow the frontmatter sources list."""
    out = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    for _ in range(3):
        out, _ = mg._apply_diff(out, {"patches": []}, _blocks("raw/a.md"), TODAY)

    assert out.count("  - raw/a.md") == 1


def test_apply_diff_adds_updated_when_missing():
    article = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/b.md"), TODAY)

    assert f"updated: {TODAY}" in out


def test_apply_diff_without_frontmatter_leaves_body_alone():
    article = "## Body\njust text\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/a.md"), TODAY)

    assert out == article


def test_apply_diff_handles_unterminated_frontmatter():
    article = "---\ntitle: A\nno closing delimiter\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/a.md"), TODAY)

    assert out == article


def test_apply_diff_inserts_source_when_sources_is_last_key():
    article = "---\ntitle: A\nsources:\n  - raw/a.md\n---\nbody\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/new.md"), TODAY)

    assert "  - raw/new.md" in out


def test_apply_diff_inserts_source_before_a_following_key():
    article = (
        "---\ntitle: A\nsources:\n  - raw/a.md\ncreated: 2024-01-01\n---\nbody\n"
    )
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/new.md"), TODAY)

    lines = out.split("\n")
    assert lines.index("  - raw/new.md") < lines.index("created: 2024-01-01")


def test_apply_diff_fills_an_empty_sources_key_before_the_next_key():
    """`sources:` with no items yet: the new source must land under it rather
    than after the following key (or be dropped)."""
    article = "---\ntitle: A\nsources:\ncreated: 2024-01-01\n---\nbody\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/new.md"), TODAY)

    lines = out.split("\n")
    assert lines[lines.index("sources:") + 1] == "  - raw/new.md"
    assert lines.index("  - raw/new.md") < lines.index("created: 2024-01-01")


def test_apply_diff_fills_an_empty_sources_key_at_the_end_of_frontmatter():
    """`sources:` with no items as the last frontmatter key: the source is
    appended after the loop ends, so it must not be lost."""
    article = "---\ntitle: A\nupdated: 2024-01-01\nsources:\n---\nbody\n"
    out, _ = mg._apply_diff(article, {"patches": []}, _blocks("raw/a.md"), TODAY)

    assert "sources:\n  - raw/a.md\n---" in out
    assert f"updated: {TODAY}" in out


# ── _apply_diff: patches ────────────────────────────────────────────

def test_apply_diff_appends_to_an_existing_section():
    article = "## One\nexisting\n\n## Two\nother\n"
    diff = {"patches": [
        {"action": "append_to_section", "section": "## One", "content": "added line"},
    ]}
    out, _ = mg._apply_diff(article, diff, _blocks("raw/a.md"), TODAY)

    assert "added line" in out
    # The addition lands inside section One, above section Two.
    assert out.index("added line") < out.index("## Two")


def test_apply_diff_creates_a_new_section_after_an_anchor():
    article = "## One\nbody\n## Three\nbody\n"
    diff = {"patches": [
        {"action": "new_section", "after": "## One", "heading": "## Two", "content": "new body"},
    ]}
    out, _ = mg._apply_diff(article, diff, _blocks("raw/a.md"), TODAY)

    assert out.index("## One") < out.index("## Two") < out.index("## Three")


def test_apply_diff_applies_several_patches():
    article = "## One\nbody\n"
    diff = {"patches": [
        {"action": "append_to_section", "section": "## One", "content": "first"},
        {"action": "new_section", "after": "## One", "heading": "## Two", "content": "second"},
    ]}
    out, _ = mg._apply_diff(article, diff, _blocks("raw/a.md"), TODAY)

    assert "first" in out and "second" in out


def test_apply_diff_ignores_unknown_actions():
    article = "## One\nbody\n"
    out, _ = mg._apply_diff(article, {"patches": [{"action": "delete_everything"}]},
                         _blocks("raw/a.md"), TODAY)
    assert "body" in out


def test_apply_diff_tolerates_a_missing_patches_key():
    article = "## One\nbody\n"
    assert mg._apply_diff(article, {}, _blocks("raw/a.md"), TODAY)[0] == article


# ── _apply_diff: supersede ──────────────────────────────────────────
#
# A2 step 1: the replace primitive and its trail (spec-a2.md RA1-RA5, TR1-TR5),
# verified per VA1-VA3. No prompt offers the action yet, so every case here is
# reached only by handing _apply_diff a patch set directly.

V2 = date(2026, 5, 14)
V3 = date(2026, 6, 1)


def _supersede(**fields) -> dict:
    """One supersede patch, with the four RA1 fields defaulted to a valid case."""
    return {"action": "supersede",
            "anchor": "Progress: 0%",
            "replacement": "Progress: 50%",
            "by": "raw/v2.md",
            "was": "the earlier figure was 0%", **fields}


def _v2_only() -> list[mg.SourceBlock]:
    """The single-block payload RA3 passes vacuously: v2 merging into v1's article."""
    return [_block(source_path="raw/v2.md", day=V2)]


def test_supersede_replaces_the_anchor_and_renders_the_trail():
    """RA2 single match, TR1's format verbatim from D1, TR2's placement, TR3's date."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]},
                                   _v2_only(), TODAY)

    assert refusals == []
    assert out == (
        "## Status\n"
        "Progress: 50% [Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_dates_the_trail_from_the_superseding_document_not_today():
    """TR3. The compile date moves on every recompile and would rewrite the
    history the trail records, so a run today must not leave today's date."""
    out, _ = mg._apply_diff("## Status\nProgress: 0%\n", {"patches": [_supersede()]},
                            _v2_only(), TODAY)

    assert "2026-05-14" in out
    assert TODAY not in out.split("[Superseded ")[1]


def test_supersede_passes_vacuously_on_a_single_block_payload():
    """RA3's stated limit, pinned rather than described: the guard orders blocks
    against each other and cannot order one against the article, so the common
    case -- v2 merging into the article v1 wrote -- is not caught by code."""
    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n",
                                   {"patches": [_supersede()]}, _v2_only(), TODAY)

    assert refusals == []
    assert "Progress: 50%" in out


def test_supersede_with_no_matching_anchor_is_a_no_op_and_reports():
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(
        article, {"patches": [_supersede(anchor="Progress: 99%")]}, _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor not found"]
    assert refusals[0].anchor == "Progress: 99%"


def test_supersede_with_an_ambiguous_anchor_is_a_no_op_and_reports():
    """RA2. Two occurrences and the action cannot say which one it meant."""
    article = "## Status\nProgress: 0%\n\n## Summary\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]},
                                   _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor ambiguous"]


def test_supersede_reports_only_the_first_80_characters_of_the_anchor():
    """SG3. An anchor is as long as it needs to be unique (RA7), and a report
    line is read by an operator."""
    long_anchor = "x" * 200
    _out, refusals = mg._apply_diff("## Status\nbody\n",
                                    {"patches": [_supersede(anchor=long_anchor)]},
                                    _v2_only(), TODAY)

    assert refusals[0].anchor == "x" * 80


def test_supersede_matches_the_body_and_not_the_frontmatter():
    """RA2 says the article body. A phrase the frontmatter happens to repeat is
    not a second occurrence of the claim."""
    article = ("---\n"
               "title: 0% done\n"
               "updated: 2024-01-01\n"
               "sources:\n"
               "  - raw/v2.md\n"
               "---\n"
               "## Status\nProgress: 0%\n")

    out, refusals = mg._apply_diff(
        article, {"patches": [_supersede(anchor="0%", replacement="50%")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert "title: 0% done" in out
    assert "Progress: 50% [Superseded 2026-05-14 by raw/v2.md:" in out


def test_supersede_does_not_anchor_inside_an_existing_trail():
    """RA5. A later supersession edits the article's claims, never its history."""
    article = ("## Status\nProgress: 50% "
               "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="the earlier figure was 0%",
                                replacement="x", by="raw/v3.md", was="w")]},
        [_block(source_path="raw/v3.md", day=V3)], TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor not found"]


def test_supersede_does_not_anchor_inside_a_trail_this_patch_set_wrote():
    """RA5's second half: two actions in one merge cannot chain onto each
    other's bookkeeping."""
    diff = {"patches": [
        _supersede(),
        _supersede(anchor="the earlier figure was 0%", replacement="x", was="w"),
    ]}

    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n", diff,
                                   _v2_only(), TODAY)

    assert [r.reason for r in refusals] == ["anchor not found"]
    assert out.endswith("[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_chains_a_new_trail_ahead_of_the_existing_one():
    """TR4, D10: entries accumulate newest first, and the v2 note is not
    rewritten by the v3 merge (story S7)."""
    article = ("## Status\nProgress: 50% "
               "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="Progress: 50%", replacement="Progress: 80%",
                                by="raw/v3.md", was="the earlier figure was 50%")]},
        [_block(source_path="raw/v3.md", day=V3)], TODAY)

    assert refusals == []
    assert out == (
        "## Status\nProgress: 80% "
        "[Superseded 2026-06-01 by raw/v3.md: the earlier figure was 50%] "
        "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_escapes_pipes_in_a_table_row():
    """TR5. Four of P4's writer-owned survivors are DDL cells, so the row's
    column count has to survive the trail."""
    article = "## DDL\n| col | type |\n| --- | --- |\n| id | INT |\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="INT", replacement="BIGINT",
                                was="was INT | nullable")]},
        _v2_only(), TODAY)

    assert refusals == []
    row = out.split("\n")[3]
    assert row == ("| id | BIGINT [Superseded 2026-05-14 by raw/v2.md: "
                   "was INT \\| nullable] |")
    assert row.count("|") - row.count("\\|") == 3


def test_supersede_leaves_pipes_alone_outside_a_table_row():
    """TR5 is scoped to the row, because a `|` in prose is just a character."""
    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n",
                                   {"patches": [_supersede(was="0% | unstarted")]},
                                   _v2_only(), TODAY)

    assert refusals == []
    assert ": 0% | unstarted]" in out
    assert "\\|" not in out


def test_supersede_with_an_empty_replacement_leaves_the_trail_in_its_place():
    """RA1 lets `replacement` be empty: the claim is withdrawn rather than
    restated, and the trail is what makes the deletion recoverable (G7)."""
    out, refusals = mg._apply_diff(
        "## Status\nProgress: 0%\n", {"patches": [_supersede(replacement="")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert out == (
        "## Status\n"
        "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_with_an_absent_replacement_field_deletes_the_same_way():
    """A patch that omits the field means the same as one that empties it, so a
    writer cannot delete by accident of serialization and keep the record."""
    patch = {"action": "supersede", "anchor": "Progress: 0%",
             "by": "raw/v2.md", "was": "the earlier figure was 0%"}

    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n",
                                   {"patches": [patch]}, _v2_only(), TODAY)

    assert refusals == []
    assert out.endswith("[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_refuses_an_empty_was():
    """`was` is the field that cannot be left out. An empty replacement is a
    deletion the trail records; an empty `was` deletes the record itself, and G7
    is the whole reason D1 chose a trail over a deletion."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(
        article, {"patches": [_supersede(replacement="", was="")]}, _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["was is empty"]


def test_supersede_refuses_an_empty_was_even_with_a_replacement():
    """The rule is about the record, not about whether a value stands: a trail
    rendering as `[Superseded ...: ]` names no superseded claim either."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede(was="")]},
                                   _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["was is empty"]


def test_supersede_refuses_a_whitespace_only_was():
    """The required-field guard is about the record, so a `was` that renders as
    blank fails it: with an empty replacement beside it the claim is deleted and
    the trail says nothing about what stood there."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(
        article, {"patches": [_supersede(replacement="", was="  \t ")]},
        _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["was is empty"]


def test_supersede_refuses_an_anchor_spanning_a_table_row_boundary():
    """TR5. An anchor crossing a newline deletes the boundary between the lines it
    replaces; where either side is a table row that merges two rows into one, and
    one `was` would stand as the record for both deleted claims."""
    article = "## DDL\n| id | INT |\n| name | TEXT |\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="| id | INT |\n| name | TEXT |",
                                replacement="| id | BIGINT |", was="was two rows")]},
        _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor spans a table row boundary"]


def test_supersede_refuses_an_anchor_reaching_from_prose_into_a_table_row():
    """The guard is on the lines the anchor touches, not only on where it starts:
    an anchor beginning in prose and ending inside a row corrupts the row just the
    same."""
    article = "## DDL\nThe schema:\n| id | INT |\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="The schema:\n| id | INT",
                                replacement="The revised schema:\n| id | BIGINT",
                                was="was INT")]},
        _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor spans a table row boundary"]


def test_supersede_allows_a_multi_line_anchor_in_prose():
    """The refusal is scoped to tables: replacing a two-line paragraph is an
    ordinary anchored replacement and must not be caught."""
    article = "## Status\nProgress: 0%\nOwner: Dana\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="Progress: 0%\nOwner: Dana",
                                replacement="Progress: 50%\nOwner: Sam",
                                was="the earlier pair was 0% under Dana")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert out == (
        "## Status\nProgress: 50%\nOwner: Sam "
        "[Superseded 2026-05-14 by raw/v2.md: the earlier pair was 0% under Dana]\n")


def test_escape_table_cell_does_not_double_escape_an_escaped_pipe():
    """A model copying an existing DDL cell can hand back text that is already
    escaped. Escaping it again yields `\\\\|`, which GFM reads as an escaped
    backslash followed by a cell delimiter -- the column break the escape exists
    to prevent."""
    assert mg._escape_table_cell("a|b") == "a\\|b"
    assert mg._escape_table_cell("a\\|b") == "a\\|b"


def test_supersede_escapes_pipes_in_the_replacement_inside_a_table_row():
    """TR5 covers everything the action writes into the row. A `|` in the
    replacement adds a column exactly as one in `was` does, and D8 chose anchored
    replacement so the neighbouring cells survive."""
    article = "## DDL\n| col | type |\n| --- | --- |\n| id | INT |\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="INT", replacement="BIGINT | NOT NULL",
                                was="was INT")]},
        _v2_only(), TODAY)

    assert refusals == []
    row = out.split("\n")[3]
    assert row == ("| id | BIGINT \\| NOT NULL "
                   "[Superseded 2026-05-14 by raw/v2.md: was INT] |")
    assert row.count("|") - row.count("\\|") == 3


def test_supersede_refuses_a_replacement_with_a_newline_inside_a_table_row():
    """A newline has no escape -- it splits the row in two -- so TR5 refuses
    rather than corrupting the table."""
    article = "## DDL\n| id | INT |\n"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="INT", replacement="BIG\nINT", was="was INT")]},
        _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == [
        "replacement contains a newline in a table row"]


def test_supersede_allows_a_multi_line_replacement_outside_a_table_row():
    """The newline refusal is scoped to the row: in prose a multi-line
    replacement is ordinary content, so the guard must not reach it."""
    out, refusals = mg._apply_diff(
        "## Status\nProgress: 0%\n",
        {"patches": [_supersede(replacement="Progress: 50%\n\nRevised at v2.")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert "Progress: 50%\n\nRevised at v2. [Superseded 2026-05-14" in out


def test_supersede_folds_a_multi_line_anchor_onto_one_report_line():
    """SG3's line is read by an operator, and an anchor spanning two lines would
    print as two apparent refusals."""
    _out, refusals = mg._apply_diff(
        "## Status\nbody\n", {"patches": [_supersede(anchor="no\nsuch\ntext")]},
        _v2_only(), TODAY)

    assert refusals[0].anchor == "no such text"


def test_supersede_applies_when_the_payload_mixes_dated_and_undated_blocks():
    """RA3 orders `by` against the *dated* blocks only. An undated block's
    position carries no ordering claim (WP6), so it cannot beat a strict maximum
    and must not block the action either."""
    blocks = [_block(source_path="raw/v2.md", day=V2),
              _block(source_path="raw/unknown.md")]

    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n",
                                   {"patches": [_supersede()]}, blocks, TODAY)

    assert refusals == []
    assert "Progress: 50% [Superseded 2026-05-14 by raw/v2.md:" in out


def test_two_supersede_actions_in_one_patch_set_both_land():
    """Emission order within the supersede group (RA4), with both actions
    succeeding -- the refusing pair is covered separately."""
    article = "## Status\nProgress: 0%\n\n## Owner\nOwner: Dana\n"
    diff = {"patches": [
        _supersede(),
        _supersede(anchor="Owner: Dana", replacement="Owner: Sam",
                   was="the earlier owner was Dana"),
    ]}

    out, refusals = mg._apply_diff(article, diff, _v2_only(), TODAY)

    assert refusals == []
    assert "Progress: 50% [Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]" in out
    assert "Owner: Sam [Superseded 2026-05-14 by raw/v2.md: the earlier owner was Dana]" in out


def test_supersede_escapes_pipes_in_a_table_row_at_the_end_of_the_article():
    """TR5 with no trailing newline: the containing line runs to the end of the
    body, which is the branch a fixture article's final row takes."""
    article = "## DDL\n| id | INT |"

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="INT", replacement="BIGINT",
                                was="was INT | nullable")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert out.endswith("was INT \\| nullable] |")


def test_supersede_matches_a_multi_byte_anchor_past_the_frontmatter():
    """_body_offset counts characters and the body is sliced by character, so a
    non-ASCII frontmatter must not shift the anchor's offset."""
    article = ("---\n"
               "title: 缓存层设计\n"
               "sources:\n"
               "  - raw/v2.md\n"
               "---\n"
               "## 状态\n进度：0%\n")

    out, refusals = mg._apply_diff(
        article,
        {"patches": [_supersede(anchor="进度：0%", replacement="进度：50%",
                                was="此前为 0%")]},
        _v2_only(), TODAY)

    assert refusals == []
    assert out.endswith("进度：50% [Superseded 2026-05-14 by raw/v2.md: 此前为 0%]\n")
    assert "title: 缓存层设计" in out


def test_supersede_refuses_an_empty_anchor():
    """An empty anchor names no text and str.find would report it at every
    offset, so it is refused rather than applied at position zero."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede(anchor="")]},
                                   _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["anchor not found"]


def test_supersede_treats_unterminated_frontmatter_as_body():
    """_body_offset draws no boundary on an article whose frontmatter never
    closes, matching _apply_diff's own decision to leave it alone: there is no
    body to scope to, and refusing every action would cost more than the stray
    match it prevents."""
    article = "---\ntitle: A\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]},
                                   _v2_only(), TODAY)

    assert refusals == []
    assert out == (
        "---\ntitle: A\n"
        "Progress: 50% [Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")


def test_supersede_refuses_a_was_containing_a_newline():
    """TR5. A multi-line value in a table cell has no correct rendering, and the
    trail is single-line everywhere else too."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede(was="a\nb")]},
                                   _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["was contains a newline"]


def test_supersede_refuses_a_by_that_is_not_in_the_payload():
    """RA3, VA2. The trail names the document that replaced the value, so a `by`
    this merge never received names nothing checkable."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede(by="raw/ghost.md")]},
                                   _v2_only(), TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["by not in payload"]


def test_supersede_refuses_when_every_block_is_undated():
    """RA3/VA3. No block establishes an order, so there is nothing to supersede
    across -- G8 in code. Reported as `by undated` rather than as the absent
    maximum RA3 pairs this shape with: both are true, the specific one is the one
    an operator can act on, and FA5 counts refusals by reason."""
    article = "## Status\nProgress: 0%\n"

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]},
                                   [_block(source_path="raw/v2.md")], TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["by undated"]


def test_supersede_refuses_when_every_dated_block_shares_one_day():
    """RA3/VA3, and WP9 in code: the system prompt states that a same-day pair
    carries no ordering claim, so an action superseding across one would
    contradict the prompt that carried it."""
    article = "## Status\nProgress: 0%\n"
    blocks = [_block(source_path="raw/v1.md", day=V2),
              _block(source_path="raw/v2.md", day=V2)]

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]}, blocks, TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["no strictly-newest block"]


def test_supersede_applies_when_by_names_the_strictly_newest_block():
    """RA3/VA3, the case the guard exists to let through."""
    blocks = [_block(source_path="raw/v1.md", day=date(2026, 4, 9)),
              _block(source_path="raw/v2.md", day=V2)]

    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n",
                                   {"patches": [_supersede()]}, blocks, TODAY)

    assert refusals == []
    assert "Progress: 50% [Superseded 2026-05-14 by raw/v2.md:" in out


def test_supersede_refuses_a_by_that_is_dated_but_not_the_newest():
    """RA3/VA3. A block exists that this payload says is later, so the value
    `by` would install is not the one that stands."""
    article = "## Status\nProgress: 0%\n"
    blocks = [_block(source_path="raw/v2.md", day=V2),
              _block(source_path="raw/v3.md", day=V3)]

    out, refusals = mg._apply_diff(article, {"patches": [_supersede()]}, blocks, TODAY)

    assert out == article
    assert [r.reason for r in refusals] == ["by is not the newest dated block"]


def test_supersede_applies_before_an_append_that_would_duplicate_the_anchor():
    """RA4. Anchors were chosen against the article as it entered the prompt, so
    an additive action applied first can make one of them ambiguous. The append
    is emitted first here and must still land second."""
    diff = {"patches": [
        {"action": "append_to_section", "section": "## Status", "content": "Progress: 0%"},
        _supersede(),
    ]}

    out, refusals = mg._apply_diff("## Status\nProgress: 0%\n", diff,
                                   _v2_only(), TODAY)

    assert refusals == []
    assert "Progress: 50% [Superseded 2026-05-14 by raw/v2.md:" in out
    # The append still lands, and lands second: its copy of the claim sits past
    # the trail, so it could not have made the anchor ambiguous.
    assert out.index("[Superseded") < out.rindex("Progress: 0%\n")


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

    out = mg._merge_full_rewrite("wiki/a.md", "old", [_block()], "m")

    assert out.startswith("# Merged")
    assert "```" not in out


def test_merge_full_rewrite_enables_prompt_caching(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "text"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg._merge_full_rewrite("wiki/a.md", "old", [_block()], "m")

    assert captured["cache"] is True


# ── the rewrite path's trail validation ─────────────────────────────
#
# A2 step 2, TR6 verified per VA6. The diff path renders its own trail, so its
# shape is the code's; the rewrite path returns a whole article and the model
# writes the trail text itself. Code checks the shape, the date and the `by`
# path, and *reports* what fails without rejecting the write: a malformed trail
# is prose a human can fix, where a rejected merge loses information.
#
# The reason strings are hardcoded here rather than read off mg._TRAIL_*. They
# are operator-facing report text, so a test that asserted the constant appears
# in its own output would stay green through any rewording of it.

def _rewriting(monkeypatch, article: str) -> None:
    monkeypatch.setattr(mg, "completion", lambda **kwargs: article)


def _v2_payload() -> list[mg.SourceBlock]:
    return [_block(source_path="raw/v2.md", day=V2)]


def test_rewrite_reports_a_malformed_trail_and_still_writes(monkeypatch, capsys):
    """TR6: no date where the format needs one. The write lands anyway."""
    _rewriting(monkeypatch, "# A\n\nProgress: 50% [Superseded by raw/v2.md: was 0%]\n")

    out = mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert "[Superseded by raw/v2.md: was 0%]" in out
    err = capsys.readouterr().err
    assert "wiki/a.md" in err
    assert "trail block is malformed" in err


def test_rewrite_reports_a_trail_that_does_not_close_on_its_line(monkeypatch, capsys):
    """TR1 makes the block single-line, so a wrapped one is malformed rather than
    a block whose tail happens to live elsewhere."""
    _rewriting(monkeypatch,
               "Progress: 50%\n\n[Superseded 2026-05-14 by raw/v2.md: the earlier\nfigure was 0%]\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert "trail block is malformed" in capsys.readouterr().err


def test_rewrite_reports_a_trail_date_that_is_not_a_date(monkeypatch, capsys):
    """The shape is right and the day is not resolvable — a distinct report,
    because it points an operator at the date rather than at the format."""
    _rewriting(monkeypatch, "Progress: 50% [Superseded 2026-13-99 by raw/v2.md: was 0%]\n")

    merged = mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")
    err = capsys.readouterr().err

    # The write lands with the bad date in it -- VA6's "reported, not rejected".
    assert "Superseded 2026-13-99" in merged
    assert "trail date is not a date" in err


def test_rewrite_reports_a_trail_naming_a_source_outside_the_payload(monkeypatch, capsys):
    """A `by` no source in this payload carries is a path a reader cannot land in
    from the material the writer was handed."""
    _rewriting(monkeypatch, "Progress: 50% [Superseded 2026-05-14 by raw/invented.md: was 0%]\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert "trail names a source that is not in this payload" in capsys.readouterr().err


def test_rewrite_accepts_a_by_path_containing_spaces(monkeypatch, capsys):
    """The two halves of TR6 have to agree about the format, and a source path can
    hold spaces: distill's _raw_rel joins the file's path parts verbatim, so
    `My Notes/design doc.md` ingests under a name with two of them. The block here
    is what _render_trail itself emits for that source, so reporting it malformed
    would be the validator rejecting the renderer's own output."""
    spaced = "raw/kb__My Notes__design doc.md"
    day = date(2026, 5, 14)
    rendered = mg._render_trail(day, spaced, "the earlier figure was 0%", in_table_row=False)
    _rewriting(monkeypatch, f"Progress: 50% {rendered}\n")

    mg._merge_full_rewrite("wiki/a.md", "old",
                           [_block(source_path=spaced, day=day)], "m")

    assert "trail" not in capsys.readouterr().err


def test_rewrite_does_not_report_an_empty_was(monkeypatch, capsys):
    """Pinning an asymmetry rather than endorsing it. The diff path refuses an empty
    `was` outright (RA1, `_REFUSE_WAS_EMPTY`) because G7 is why D1 chose a trail over
    a deletion; TR6 enumerates three checks and this is not one, so a trail recording
    nothing passes here. Recorded in spec-a2.md as an open bound — this test is what
    makes closing it a visible change rather than a silent one."""
    _rewriting(monkeypatch, "Progress: 50% [Superseded 2026-05-14 by raw/v2.md: ]\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert "trail" not in capsys.readouterr().err


def test_rewrite_reports_nothing_for_a_well_formed_trail(monkeypatch, capsys):
    """D1's shape, rendered as _render_trail renders it on the sibling path."""
    _rewriting(monkeypatch,
               "Progress: 50% [Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert "trail" not in capsys.readouterr().err


def test_rewrite_does_not_report_a_trail_the_article_already_carried(monkeypatch, capsys):
    """The case TR6 read literally would get wrong, and the one D10 designs for:
    v3 arrives after v2 superseded v1, so the preserved v2 entry names a document
    the v3 payload does not contain. Only blocks new in the output are checked."""
    carried = "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]"
    before = f"Progress: 50% {carried}\n"
    _rewriting(monkeypatch, f"Progress: 80% [Superseded 2026-06-01 by raw/v3.md: it was 50%] {carried}\n")

    mg._merge_full_rewrite("wiki/a.md", before,
                           [_block(source_path="raw/v3.md", day=V3)], "m")

    assert "trail" not in capsys.readouterr().err


def test_rewrite_checks_the_later_blocks_of_a_chain_on_one_line(monkeypatch, capsys):
    """TR4's chains sit one entry after another on a single line, and a later entry
    is what a scan running to the end of the line never reaches: the first block
    here is well formed, so only a per-block scan reports the second."""
    _rewriting(monkeypatch,
               "Progress: 80% [Superseded 2026-06-01 by raw/v3.md: it was 50%] "
               "[Superseded 2026-06-01 by raw/gone.md: it was 0%]\n")

    mg._merge_full_rewrite("wiki/a.md", "old",
                           [_block(source_path="raw/v3.md", day=V3)], "m")

    assert "raw/gone.md" in capsys.readouterr().err


def test_a_malformed_trail_reports_as_one_line(monkeypatch, capsys):
    """SG3's rule for anchors, applied to TR6's blocks: one defect must not print as
    two. A block that never closes runs into whatever follows it, so what is reported
    is bounded by its own line and cannot carry the newline that would split it."""
    opener = "[Superseded 2026-05-14 by raw/v2.md was 0%"
    _rewriting(monkeypatch, f"{opener}\nand a paragraph the report must not reach\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")
    err = capsys.readouterr().err.rstrip("\n")

    assert err.count("\n") == 0
    assert err.endswith(opener)


def test_a_long_malformed_trail_is_reported_to_eighty_characters(monkeypatch, capsys):
    """The same bound SG3 puts on an anchor. A trail block is as long as the claim it
    records, and a report line is not the place to read one."""
    opener = "[Superseded 2026-05-14 by raw/v2.md the earlier figure was " + "x" * 200
    _rewriting(monkeypatch, f"{opener}\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")

    assert capsys.readouterr().err.rstrip("\n").endswith(f": {opener[:80]}")


def test_rewrite_reports_every_malformed_trail_not_only_the_first(monkeypatch, capsys):
    """One report per block: an operator fixing the first should not have to
    recompile to discover the second."""
    _rewriting(monkeypatch,
               "a [Superseded by raw/v2.md: x]\nb [Superseded 2026-99-99 by raw/v2.md: y]\n")

    mg._merge_full_rewrite("wiki/a.md", "old", _v2_payload(), "m")
    err = capsys.readouterr().err

    assert "trail block is malformed" in err
    assert "trail date is not a date" in err


# ── the rewrite path's trail preservation guard ──────────────────────
#
# A2 step 3, SG1 verified per VA4. D9's append-only rule is structural on the diff
# path (no action deletes a trail) and checkable only against the output here: the
# model re-emits the whole article, so every trail block the pre-write article
# carried has to come back verbatim. A missing one buys one retry; still missing,
# the merge is abandoned and the article keeps every byte it had.
#
# The assertions are on the returned article rather than on the report, per VA4:
# what SG1 promises is that no history is lost, and a log line saying so is not
# that promise.

CARRIED = "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]"


def _carrying() -> str:
    """v1's article after v2 superseded a claim in it -- the pre-write state a
    third source now merges into (D10's chain)."""
    return f"# Gateway\n\nProgress: 50% {CARRIED}\n"


def _v3_payload() -> list[mg.SourceBlock]:
    return [_block(source_path="raw/v3.md", day=V3)]


def _rewriting_in_turn(monkeypatch, *outputs: str) -> list[list[dict]]:
    """Successive rewrite outputs, returning the messages each call was sent.

    A call past the last output is an assertion failure rather than a repeat of
    it, so "retried once" is pinned by every test that hands this two outputs:
    a third send fails here instead of passing quietly.
    """
    sent: list[list[dict]] = []

    def fake_completion(**kwargs):
        # Copied, not aliased: what is asserted afterwards has to be the list this
        # call was given, not one a later line could still append to.
        sent.append(list(kwargs["messages"]))
        assert len(sent) <= len(outputs), "more rewrite calls than this test allows"
        return outputs[len(sent) - 1]

    monkeypatch.setattr(mg, "completion", fake_completion)
    return sent


def test_a_dropped_trail_buys_one_retry_and_the_retry_lands(monkeypatch):
    """SG1's first half. The retry preserved the block, so its article is written
    -- the guard costs a call, not the merge."""
    kept = f"# Gateway\n\nProgress: 80% [Superseded 2026-06-01 by raw/v3.md: it was 50%] {CARRIED}\n"
    sent = _rewriting_in_turn(monkeypatch, "# Gateway\n\nProgress: 80%\n", kept)

    out = mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")

    assert out == kept.strip()
    assert len(sent) == 2


def test_a_trail_dropped_twice_leaves_the_article_byte_identical(monkeypatch):
    """SG1's second half, and the price D9 accepts: the merge is lost so that the
    history is not. Byte-identical, not merely trail-preserving -- an abandoned
    write must not land a partial rewrite either."""
    before = _carrying()
    sent = _rewriting_in_turn(monkeypatch,
                              "# Gateway\n\nProgress: 80%\n",
                              "# Gateway\n\nProgress: 80%, and more prose.\n")

    out = mg._merge_full_rewrite("wiki/a.md", before, _v3_payload(), "m")

    assert out == before
    assert len(sent) == 2


def test_a_trail_dropped_twice_reports_the_article_and_the_block(monkeypatch, capsys):
    """SG1's report: the path, because the layer that knows it is this one, and the
    block, because an operator cannot go looking for what was lost otherwise."""
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")

    mg._merge_full_rewrite("wiki/gateway.md", _carrying(), _v3_payload(), "m")
    err = capsys.readouterr().err

    assert "wiki/gateway.md" in err
    assert CARRIED in err
    # Hardcoded for the reason the TR6 section states: a test that read the reason
    # off mg._TRAIL_LOST would stay green through any rewording of it.
    assert "pre-existing trail missing from the rewrite" in err


def test_the_same_block_carried_twice_is_reported_once(monkeypatch, capsys):
    """Where a claim is stated in two places the prompt asks for a note at each, so
    an article legitimately carries identical blocks. Losing them is one loss to
    act on, not two identical report lines to read."""
    before = f"Progress: 50% {CARRIED}\n\n## Also\nProgress: 50% {CARRIED}\n"
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")

    mg._merge_full_rewrite("wiki/a.md", before, _v3_payload(), "m")

    assert capsys.readouterr().err.count("[abandoned]") == 1


def test_a_lost_trail_is_reported_to_eighty_characters(monkeypatch, capsys):
    """The bound SG3 puts on an anchor and TR6 on a malformed block, here too: a
    trail block is as long as the claim it records, and a report line is not the
    place to read one. The prefix is enough to find what was lost."""
    long_block = "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was " + "x" * 200 + "]"
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")

    mg._merge_full_rewrite("wiki/a.md", f"Progress: 50% {long_block}\n",
                           _v3_payload(), "m")

    assert capsys.readouterr().err.rstrip("\n").endswith(f": {long_block[:80]}")


def test_a_preserved_trail_costs_no_second_call(monkeypatch):
    """The ordinary case. One output only, so a needless retry fails the test."""
    kept = f"# Gateway\n\nProgress: 80% {CARRIED}\n"
    sent = _rewriting_in_turn(monkeypatch, kept)

    out = mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")

    assert out == kept.strip()
    assert len(sent) == 1


def test_an_article_with_no_trail_is_rewritten_freely(monkeypatch):
    """The guard is about history the article already holds. An article that has
    none constrains nothing, however little of it the rewrite keeps."""
    sent = _rewriting_in_turn(monkeypatch, "# Gateway\n\nEverything is different.\n")

    out = mg._merge_full_rewrite("wiki/a.md", "# Gateway\n\nProgress: 50%\n",
                                 _v3_payload(), "m")

    assert out == "# Gateway\n\nEverything is different."
    assert len(sent) == 1


def test_a_paraphrased_trail_does_not_count_as_preserved(monkeypatch):
    """The bound SG1 states rather than hides: verbatim is the only grain a code
    guard has. A reworded note keeps the claim's history in prose and still trips
    the guard, so the failure mode is a wasted retry, never a silent loss."""
    reworded = "# Gateway\n\nProgress: 80% [Superseded 2026-05-14 by raw/v2.md: it was 0% before]\n"
    sent = _rewriting_in_turn(monkeypatch, reworded, reworded)

    out = mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")

    assert out == _carrying()
    assert len(sent) == 2


def test_the_later_block_of_a_chain_is_guarded_too(monkeypatch):
    """TR4's chains sit one entry after another on one line, and the entries after
    the first are what a line-wide scan never reaches. The output here keeps the
    newest of two and drops the one behind it."""
    older = "[Superseded 2026-05-14 by raw/v2.md: the earlier figure was 0%]"
    newer = "[Superseded 2026-06-01 by raw/v3.md: it was 50%]"
    before = f"# Gateway\n\nProgress: 80% {newer} {older}\n"
    sent = _rewriting_in_turn(monkeypatch, f"# Gateway\n\nProgress: 80% {newer}\n",
                              f"# Gateway\n\nProgress: 80% {newer} {older}\n")

    mg._merge_full_rewrite("wiki/a.md", before,
                           [_block(source_path="raw/v4.md", day=date(2026, 7, 1))], "m")

    assert len(sent) == 2


def test_the_retry_names_the_missing_block_and_keeps_the_first_prompt(monkeypatch):
    """What makes the retry worth a call: the block it has to bring back, verbatim,
    added to the prompt the first attempt already saw rather than replacing it --
    the article and its sources are still the material being merged."""
    sent = _rewriting_in_turn(monkeypatch, "gone\n",
                              f"kept {CARRIED}\n")

    mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")
    first, retry = sent

    assert retry[:2] == first
    assert len(retry) == 3
    assert CARRIED in retry[2]["content"]
    # The other half of SG1's retry clause -- "with the constraint restated". The
    # phrase is hardcoded rather than read off mg._TRAIL_RETRY_HEAD, which would
    # assert nothing: an empty head would satisfy a test built from the head.
    assert "append-only" in retry[2]["content"]


def _five_lost_blocks(monkeypatch) -> str:
    """An article carrying five long trail blocks, with the prompt budget squeezed
    to what the first send leaves the retry.

    The squeeze is the point. At the real 80 000 characters a note naming all five
    fits with room to spare, so an assertion about the budget passes whether or not
    the note is bounded at all -- which is what a mutation run caught. Here the
    first send is capped at _SAFETY_MARGIN's worth of user message, so the note has
    the margin and nothing else, exactly the position a full-sized article puts it
    in.
    """
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS",
                        len(mg._merge_rewrite_system()) + 2 * mg._SAFETY_MARGIN)
    blocks = [f"[Superseded 2026-05-1{i} by raw/v2.md: {'x' * 150}]" for i in range(5)]
    return "# Gateway\n\n" + "\n".join(f"Claim {i} {b}" for i, b in enumerate(blocks)) + "\n"


def test_the_retry_note_fits_the_prompt_budget_the_first_send_left(monkeypatch):
    """The retry appends to a prompt already sized to the budget, so its own text
    has to fit what _SAFETY_MARGIN reserved -- otherwise a merge that SG1 means to
    retry raises PromptTooLargeError instead, losing the article's history to a
    crash rather than to the guard. Five long blocks is more than the margin holds,
    so the note names what fits and drops the rest."""
    before = _five_lost_blocks(monkeypatch)
    sent = _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")

    mg._merge_full_rewrite("wiki/a.md", before, _v3_payload(), "m")

    assert len(sent) == 2
    assert sum(len(m["content"]) for m in sent[1]) <= mg.MAX_PROMPT_CHARS


def test_every_missing_block_is_reported_even_when_the_note_could_not_name_it(
        monkeypatch, capsys):
    """The bound above applies to the prompt, not to the operator: the note is what
    one call can carry, where the report is the whole loss."""
    before = _five_lost_blocks(monkeypatch)
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")

    mg._merge_full_rewrite("wiki/a.md", before, _v3_payload(), "m")
    err = capsys.readouterr().err

    assert err.count("wiki/a.md") == 5


def test_the_retry_note_is_shorter_than_the_margin_it_has_to_fit():
    """The invariant the bound above rests on, asserted directly so that growing
    the note's prose fails here rather than at a live call: the fixed text must fit
    _SAFETY_MARGIN with room left for at least one block."""
    fixed = len(mg._TRAIL_RETRY_HEAD) + len(mg._TRAIL_RETRY_TAIL)

    assert fixed < mg._SAFETY_MARGIN


def test_an_abandoned_merge_reports_no_trail_defects(monkeypatch, capsys):
    """TR6 reports the format of prose that is now in the article. An abandoned
    write put nothing there, so naming its malformed block would send an operator
    looking for text no file contains."""
    output = "Progress: 80% [Superseded by raw/v3.md: it was 50%]\n"
    _rewriting_in_turn(monkeypatch, output, output)

    mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")
    err = capsys.readouterr().err

    assert "trail block is malformed" not in err


def test_the_article_that_lands_is_the_one_validated(monkeypatch, capsys):
    """The other side of it: the retry's output is what gets written, so TR6 reads
    that one rather than the attempt SG1 threw away."""
    landed = f"Progress: 80% [Superseded by raw/v3.md: it was 50%] {CARRIED}\n"
    _rewriting_in_turn(monkeypatch, "gone\n", landed)

    out = mg._merge_full_rewrite("wiki/a.md", _carrying(), _v3_payload(), "m")

    assert out == landed.strip()
    assert "trail block is malformed" in capsys.readouterr().err


# ── the report sink ─────────────────────────────────────────────────
#
# A2 step 4. SG1's abandonments, SG3's refusals and TR6's defects are what the
# compile report has to name, and until now each printed itself to stderr from
# inside the merge, where no caller could count it. A caller that passes a sink
# collects them instead; one that does not keeps the stderr behaviour, which is
# what every direct caller and the daemon's own logs still rely on.
#
# Collected *instead of* printed, not as well as: both routes log the report to
# stderr themselves, so printing at both layers would tell an operator the same
# refusal twice and make a count of report lines wrong.

def test_a_refusal_reaches_the_sink_with_the_article_named(monkeypatch):
    """SG3's report, structured. The reason and the anchor are what an operator
    acts on, and the article is what only this layer knows."""
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: {"patches": [_supersede(anchor="absent text")]})
    events: list[mg.MergeEvent] = []

    mg._merge_diff("wiki/gateway.md", "## Status\nProgress: 0%\n", _v2_only(), "m",
                   events=events)

    assert [(e.kind, e.article, e.reason) for e in events] == [
        (mg.EV_SUPERSEDE_REFUSED, "wiki/gateway.md", "anchor not found")]
    assert events[0].detail == "absent text"


def test_a_refusal_prints_when_no_sink_is_passed(monkeypatch, capsys):
    """The behaviour every direct caller had before the sink existed. A merge that
    reports nowhere would make the daemon's logs quieter than its output."""
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: {"patches": [_supersede(anchor="absent text")]})

    mg._merge_diff("wiki/gateway.md", "## Status\nProgress: 0%\n", _v2_only(), "m")

    assert "anchor not found" in capsys.readouterr().err


def test_a_refusal_does_not_print_when_it_reaches_the_sink(monkeypatch, capsys):
    """One refusal, one report line. The sink's owner logs it, so printing here as
    well would double every entry in the compile report's own count."""
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: {"patches": [_supersede(anchor="absent text")]})

    mg._merge_diff("wiki/gateway.md", "## Status\nProgress: 0%\n", _v2_only(), "m",
                   events=[])

    assert "anchor not found" not in capsys.readouterr().err


def test_a_malformed_trail_reaches_the_sink_and_the_write_still_lands(monkeypatch, capsys):
    """TR6 through the sink: reported, never rejected."""
    _rewriting(monkeypatch, "Progress: 50% [Superseded by raw/v2.md: was 0%]\n")
    events: list[mg.MergeEvent] = []

    out = mg._merge_full_rewrite("wiki/gateway.md", "old", _v2_payload(), "m", events=events)

    assert "[Superseded by raw/v2.md: was 0%]" in out
    assert [(e.kind, e.article, e.reason) for e in events] == [
        (mg.EV_TRAIL_MALFORMED, "wiki/gateway.md", "trail block is malformed")]
    assert "trail" not in capsys.readouterr().err


def test_an_abandoned_merge_reaches_the_sink_with_the_missing_block(monkeypatch):
    """SG1 through the sink. This is the event the compile report turns into its own
    status, so the block has to travel with it: an operator reading `abandoned`
    needs to know which note the writer dropped."""
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")
    events: list[mg.MergeEvent] = []

    out = mg._merge_full_rewrite("wiki/gateway.md", _carrying(), _v3_payload(), "m",
                                 events=events)

    assert out == _carrying()
    assert [(e.kind, e.article, e.reason) for e in events] == [
        (mg.EV_TRAIL_LOST, "wiki/gateway.md",
         "pre-existing trail missing from the rewrite")]
    assert events[0].detail == CARRIED


def test_the_entry_point_carries_the_sink_down_the_diff_route(monkeypatch):
    """Routing must not drop it. An article past the large-article threshold takes
    the diff path, and a sink the entry point forgets to pass is a report that is
    empty for exactly the articles most likely to need one."""
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: {"patches": [_supersede(anchor="absent text")]})
    article = "## Status\nProgress: 0%\n" + "filler prose. " * 3000
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/gateway.md", article, _v2_only(), model="m", events=events)

    assert [e.kind for e in events] == [mg.EV_SUPERSEDE_REFUSED]


def test_the_entry_point_carries_the_sink_down_the_rewrite_route(monkeypatch):
    """The other route, for the same reason."""
    _rewriting(monkeypatch, "Progress: 50% [Superseded by raw/v2.md: was 0%]\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/gateway.md", "small article\n", _v2_payload(), model="m",
                          events=events)

    assert [e.kind for e in events] == [mg.EV_TRAIL_MALFORMED]


def test_an_event_formats_as_one_report_line(monkeypatch):
    """The report's line shape lives with the events rather than in each route, so
    the CLI and the daemon cannot word the same finding two ways. One line, because
    a count of findings is read off the lines."""
    event = mg.MergeEvent(kind=mg.EV_SUPERSEDE_REFUSED, article="wiki/gateway.md",
                          reason="anchor not found", detail="Progress: 0%")

    line = mg.format_merge_event(event)

    assert line.count("\n") == 0
    assert "wiki/gateway.md" in line
    assert "anchor not found" in line
    assert "Progress: 0%" in line


def test_an_event_with_no_detail_formats_without_a_dangling_separator():
    """SG2's shrink lines carry their whole finding in the reason."""
    event = mg.MergeEvent(kind=mg.EV_ARTICLE_SHRANK, article="wiki/gateway.md",
                          reason="shrank 120 bytes (1 000 → 880)")

    line = mg.format_merge_event(event)

    assert line.rstrip().endswith("880)")


# ── SG2: the shrink report ──────────────────────────────────────────
#
# Recorded by the merge op rather than by its callers, though both callers hold
# the pre- and post-write text: two routes computing the same delta is two
# chances to word it differently, and the entry point is the one layer both go
# through. A1's NG7 asked whether an article can shrink and A2 answers yes, so
# the Size column stops being a growth meter -- which only works if the delta is
# reported the same way whoever wrote the article.

def _rewrites_to(monkeypatch, article: str) -> None:
    """The rewrite route returning a whole article, for the byte-delta cases."""
    monkeypatch.setattr(mg, "completion", lambda **kwargs: article)


def test_a_merge_that_shrinks_the_article_records_the_delta(monkeypatch):
    """SG2: named with its delta, no threshold and no block."""
    _rewrites_to(monkeypatch, "short\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", "a much longer article than what came back\n",
                          _v2_payload(), model="m", events=events)

    assert [(e.kind, e.article) for e in events] == [(mg.EV_ARTICLE_SHRANK, "wiki/a.md")]
    # 42 bytes in, 5 back: the reason carries both ends, so a reader does not have
    # to hold the article's size in their head to read the delta.
    assert "37" in events[0].reason
    assert "42" in events[0].reason and "5" in events[0].reason


def test_a_merge_that_grows_the_article_records_nothing(monkeypatch):
    """The ordinary case, and the reason SG2 needs no threshold: growth is silent."""
    _rewrites_to(monkeypatch, "a much longer article than what went in\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", "short\n", _v2_payload(), model="m", events=events)

    assert events == []


def test_a_merge_that_keeps_the_size_records_nothing(monkeypatch):
    """The boundary. Equal is not smaller, so a rewrite that reworded a sentence
    into the same number of bytes is not a shrink to investigate. The article here
    carries no trailing newline, which is what makes the comparison equal -- see the
    next test for why that is not incidental."""
    _rewrites_to(monkeypatch, "abcde\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", "edcba", _v2_payload(), model="m", events=events)

    assert events == []


def test_a_rewrite_that_drops_the_trailing_newline_reports_one_byte(monkeypatch):
    """A one-byte floor under the rewrite route, pinned rather than filtered out.
    The route strips what the model returns and the store writes it verbatim, so an
    article that was stored with a trailing newline really does lose a byte on disk.
    SG2 has no threshold on purpose, and inventing one here to hide a byte would be
    the guessed threshold D9 rejected -- so the honest report is a 1-byte line."""
    _rewrites_to(monkeypatch, "same text\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", "same text\n", _v2_payload(), model="m",
                          events=events)

    assert [e.kind for e in events] == [mg.EV_ARTICLE_SHRANK]
    assert "shrank 1 bytes" in events[0].reason


def test_the_shrink_delta_is_measured_in_utf8_bytes(monkeypatch):
    """Bytes, as SG2 says and as the Size column reads. Three CJK characters are
    three characters and nine bytes, so a rewrite that drops them for one ASCII
    word grows in characters while shrinking on disk."""
    _rewrites_to(monkeypatch, "abcd")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", "网关文", _v2_payload(), model="m", events=events)

    assert [e.kind for e in events] == [mg.EV_ARTICLE_SHRANK]
    assert "9" in events[0].reason and "4" in events[0].reason


def test_an_abandoned_merge_records_no_shrink(monkeypatch):
    """SG1 returned the article untouched, so there is no delta to report -- and a
    shrink line beside an abandonment would read as though the write had landed."""
    _rewriting_in_turn(monkeypatch, "gone\n", "still gone\n")
    events: list[mg.MergeEvent] = []

    mg.merge_into_article("wiki/a.md", _carrying(), _v3_payload(), model="m", events=events)

    assert [e.kind for e in events] == [mg.EV_TRAIL_LOST]


def test_a_shrink_prints_when_no_sink_is_passed(monkeypatch, capsys):
    """Same rule as the other three findings: the report goes somewhere."""
    _rewrites_to(monkeypatch, "short\n")

    mg.merge_into_article("wiki/a.md", "a much longer article than what came back\n",
                          _v2_payload(), model="m")

    assert "[shrank] wiki/a.md" in capsys.readouterr().err


def test_merge_diff_applies_the_returned_patches(monkeypatch):
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [{"action": "append_to_section", "section": "## One", "content": "added"}],
    })

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")

    assert "added" in out


def test_merge_diff_names_the_article_when_a_supersede_is_refused(monkeypatch, capsys):
    """SG3 on the layer that knows which article was being written. An action the
    code throws away has to reach an operator, or a clean Staleness column cannot
    be told from a writer that never tried (FA5)."""
    monkeypatch.setattr(mg, "completion_json", lambda **kwargs: {
        "patches": [{"action": "supersede", "anchor": "no such text",
                     "replacement": "x", "by": "raw/v2.md", "was": "w"}],
    })

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n",
                         [_block(source_path="raw/v2.md", day=V2)], "m")

    err = capsys.readouterr().err
    assert "[supersede-refused] wiki/a.md" in err
    assert "anchor not found" in err
    assert "no such text" in err
    assert "body" in out


def test_merge_diff_degrades_to_no_patches_on_bad_json(monkeypatch):
    """A model returning unparseable JSON must leave the article intact rather
    than dropping content."""
    def boom(**kwargs):
        raise json.JSONDecodeError("bad", "{}", 0)

    monkeypatch.setattr(mg, "completion_json", boom)

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")

    assert "body" in out


def test_merge_diff_degrades_on_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(mg, "completion_json", boom)

    out = mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")

    assert "body" in out


def test_merge_diff_truncates_an_oversized_article(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 4000)

    article = "\n".join(f"## S{i}\n" + "x" * 400 for i in range(20))
    mg._merge_diff("wiki/a.md", article, [_block(_extraction(topics=["s1"]))], "m")

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

    out = mg.create_new_article("concept", "My Title",
                                [_block(_extraction(topics=["t"]))])

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

    mg.create_new_article("project", "P", [_block()])

    assert "status: active" in captured["system"]


def test_create_new_article_omits_status_for_non_projects(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("concept", "C", [_block()])

    assert "status: active" not in captured["system"]


def test_create_new_article_bounds_the_extraction(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)
    monkeypatch.setattr(mg, "MAX_PROMPT_CHARS", 3000)

    huge = _extraction(summary="s" * 50_000, concepts=[{"t": "x" * 500} for _ in range(50)])
    mg.create_new_article("concept", "T", [_block(huge)])

    assert len(captured["user"]) < 10_000


def test_create_new_article_lists_every_source_in_its_header(monkeypatch):
    """The frontmatter format in the system prompt asks for a `sources:` list, so
    the header names them as list items. Flattened, several sources arrived as one
    comma-joined string, which is a single item whatever it contains."""
    captured = {}

    def fake_completion(**kwargs):
        captured["user"] = kwargs["messages"][1]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("concept", "T", [
        _block(_extraction(topics=["shared", "older"]),
               source_path="raw/a.md", day=date(2020, 1, 1)),
        _block(_extraction(topics=["shared", "newer"]),
               source_path="raw/b.md", day=date(2021, 1, 1)),
    ])

    assert "- Sources:\n  - raw/a.md\n  - raw/b.md\n" in captured["user"]
    # Tags are every block's topics, first-seen order and no repeats: the
    # flattening this replaces returned list(set(...)), so the same input
    # produced a different tag order run to run.
    assert "- Tags: ['shared', 'older', 'newer']" in captured["user"]


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
    for name in ("merge-rewrite", "merge-diff"):
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


# PV5's claim, verified per VA7. Six sites asserted the merge paths could not
# retract, and A2 falsifies all six. A grep over the tree rather than a check of
# six line numbers, because line numbers move and what a future reader believes
# is the sentence, not its address.

_ADDITIVE_CLAIMS = (
    "both merge paths are additive",
    "merge paths are additive",
    "merge cannot retract",
    # The _SOURCE_ORDER comment's own wording. Left as a separate pattern rather
    # than folded into the one above, because "merge cannot retract" does not
    # match "the merge paths cannot retract" and PV5 names that site first.
    "paths cannot retract",
    "still the additive ones",
    "which still carry the previous",
)


def test_no_source_file_claims_the_merge_paths_cannot_retract():
    """PV5. The positive control is load-bearing, not decoration: a pattern with a
    typo in it matches nothing, and this test would then pass over a tree that
    still tells its reader the write paths only append."""
    from pathlib import Path

    sample = ("both merge paths are additive -- merge-diff.md offers only "
              "append_to_section and new_section")
    assert any(claim in sample for claim in _ADDITIVE_CLAIMS), \
        "the patterns match nothing, so a clean result would prove nothing"

    src = Path(__file__).resolve().parents[1] / "src" / "kb_ai"
    offenders = [
        f"{path.relative_to(src)}: {claim}"
        for path in sorted(src.rglob("*.py"))
        for claim in _ADDITIVE_CLAIMS
        if claim in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_create_new_article_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    """Ties the hash to the production path: a version over a template the real
    call does not use would report freshness about text nobody sent."""
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg.create_new_article("project", "P", [_block()])

    assert captured["system"] == mg._create_system("project")


def test_merge_full_rewrite_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    """The rewrite path composes its system prompt rather than sending the file
    verbatim, so the hash and the send have to read the same helper."""
    captured = {}

    def fake_completion(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return "article"

    monkeypatch.setattr(mg, "completion", fake_completion)

    mg._merge_full_rewrite("wiki/a.md", "old", [_block()], "m")

    assert captured["system"] == mg._merge_rewrite_system()


def test_merge_diff_sends_exactly_the_prompt_that_was_hashed(monkeypatch):
    captured = {}

    def fake_completion_json(**kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return {"patches": []}

    monkeypatch.setattr(mg, "completion_json", fake_completion_json)

    mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")

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

    mg._merge_full_rewrite("wiki/a.md", "old", [_block()], "m")
    mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")
    mg.create_new_article("concept", "C", [_block()])

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


# ── the source-order statement (supersession WP6) ───────────────────
#
# The payload now carries one dated block per source, oldest to newest, with the
# undated ones last (WP5). Nothing told the writer that, and a sequence whose
# meaning is never stated is a sequence the model is free to read backwards -- or
# to read an undated block's trailing position as recency, which is a claim the
# corpus cannot support.

def test_source_order_statement_reaches_every_write_stage_prompt():
    renderings = mg._write_stage_renderings()
    assert renderings, "no write-stage prompts to check"
    for name, text in renderings:
        assert mg._SOURCE_ORDER in text, f"{name} carries no source-order statement"


def test_source_order_statement_reaches_the_three_paths_as_sent(monkeypatch):
    """It goes in the system prompt, not the user message (WP6), and
    _write_stage_renderings agreeing with itself is not evidence the production
    calls send it."""
    sent: list[str] = []

    monkeypatch.setattr(mg, "completion",
                        lambda **kwargs: sent.append(kwargs["messages"][0]["content"]) or "a")
    monkeypatch.setattr(mg, "completion_json",
                        lambda **kwargs: sent.append(kwargs["messages"][0]["content"]) or {"patches": []})

    mg._merge_full_rewrite("wiki/a.md", "old", [_block()], "m")
    mg._merge_diff("wiki/a.md", "## One\nbody\n", [_block()], "m")
    mg.create_new_article("concept", "C", [_block()])

    assert len(sent) == 3
    for system in sent:
        assert mg._SOURCE_ORDER in system


def _order_bullets(*tokens: str) -> list[str]:
    """The `_SOURCE_ORDER` bullets naming any of ``tokens``, lowercased.

    The statement now carries two disclaimers with the same vocabulary, so a check
    run over the whole constant passes on either of them and stops detecting the
    deletion of the other. Both disclaimer tests therefore assert inside the bullet
    that raises their own case.
    """
    bullets = [b.lower() for b in mg._SOURCE_ORDER.split("\n- ")]
    return [b for b in bullets if any(t in b for t in tokens)]


def test_source_order_statement_gives_the_direction_and_disclaims_the_undated():
    """Wording is load-bearing, as it is for the grounding constraint. Both halves
    of WP6 have to be there: which way the blocks run, and that an undated block's
    position is not an ordering claim (S5). Half of it is worse than neither --
    "blocks are ordered" with no disclaimer invites reading the undated tail,
    which sorts last for determinism alone, as the newest material."""
    assert "oldest to newest" in mg._SOURCE_ORDER.lower()
    undated = _order_bullets("undated")

    assert undated, "the statement never mentions an undated block"
    for bullet in undated:
        assert "unknown" in bullet or "no ordering claim" in bullet, \
            "an undated block's position is raised without disclaiming it"


def test_source_order_statement_withdraws_the_claim_between_same_day_blocks():
    """WP9. "The blocks run oldest to newest" is a positive ordering claim, and for
    two blocks sharing a `- Date:` line there is nothing behind it: they render in
    path order, which buys reproducibility and not recency. Left unqualified the
    statement misinforms the writer about a pair in two of every five multi-source
    articles on the reference KB, and the fixture holds a live inversion -- P5's v3
    renders first because `-` sorts before `.`. The measurement is recorded once, in
    `_budget_priority`'s docstring, rather than restated here.

    Asserted inside the bullet that raises the case, and on the withdrawal being
    stated positively: "no ordering claim ... so read the path order instead" would
    satisfy a laxer check while instructing exactly the tie-breaker V20 rejected."""
    same_day = _order_bullets("same day", "same date")

    assert same_day, "the statement never mentions two sources sharing a day"
    for bullet in same_day:
        assert "no ordering claim" in bullet, \
            "the same-day case is raised without withdrawing the ordering claim"
        assert "reproducib" in bullet, \
            "path order is offered without saying what it is there for"
        assert "unknown" in bullet, \
            "the withdrawal is gestured at rather than stated: nothing says which "\
            "of the two came first is unknown"


def test_source_order_statement_names_the_label_the_renderer_emits():
    """The statement quotes a literal line label. Renaming it in _block_header
    would leave the prompt describing a line no payload contains, and the
    renderer's own tests would move in the same edit without noticing."""
    from datetime import date as _d

    assert "`- Date:`" in mg._SOURCE_ORDER
    assert "- Date:" in mg._block_header(_block(day=_d(2020, 1, 1)))


def test_source_order_statement_grants_no_retraction():
    """A1 adds a signal and no action (NG1, G4). The rewrite path returns a whole
    article and could therefore drop text if asked to, so the statement must not
    ask: the replace primitive and the [Superseded ...] trail are A2's, and a
    prompt that pre-empts them would also contaminate the fixture arm that decides
    whether A2 is needed at all (FX7)."""
    text = mg._SOURCE_ORDER.lower()
    for word in ("supersede", "superseded", "replace", "remove", "delete", "retract"):
        assert word not in text, f"the source-order statement asks the writer to {word}"


def test_write_prompt_version_moves_when_the_source_order_statement_changes(monkeypatch):
    """PV1: WP6 edits every write-stage system prompt, so the hash has to move --
    otherwise the lag report calls articles composed under the old prompts current."""
    before = mg.write_prompt_version()

    monkeypatch.setattr(mg, "_SOURCE_ORDER", mg._SOURCE_ORDER + "\n- one more rule")
    mg.write_prompt_version.cache_clear()

    assert mg.write_prompt_version() != before


def test_merge_rewrite_asks_for_every_source_in_the_frontmatter():
    """The rule was written for a payload that handed the writer one flattened
    source string to copy into `sources:`. It now gets N of them (WP3, WP4), and a
    source missing from that list is a document `derive` will not copy into a
    derived KB (derive/_sources.py reads exactly that key)."""
    from kb_ai.prompts import default_registry

    text = default_registry().get("merge-rewrite").render()

    assert "add source to" not in text
    # Asserted on the one rule that governs `sources:`, not on the whole prompt:
    # "already" appears in an unrelated rule about not duplicating content, so a
    # whole-text search would pass on a prompt that never says it here.
    rule = next(line for line in text.splitlines() if "'sources'" in line)
    assert "add every source" in rule
    # Without an "unless it is already there", a revised document re-merging into
    # an article that already names it adds a second identical item -- and a
    # duplicate in an article's frontmatter is written once and read forever
    # (the same reasoning _apply_diff's dedupe carries).
    assert "already" in rule


# A2 step 2: the prompts learn the action (RA6, RA7). The prompt files are what
# changes behaviour, so the rules RA7 enumerates are pinned here -- a rule silently
# dropped from a prompt is invisible everywhere else until an arm is bought.

def test_the_diff_prompt_offers_supersede_with_its_four_fields():
    """RA1: four fields and no others, and the action named in the example rather
    than only in prose, since the example is what a JSON-emitting model copies."""
    from kb_ai.prompts import default_registry

    # .content, not .render(): the file holds literal JSON braces (_merge_diff_system).
    text = default_registry().get("merge-diff").content

    assert '"action": "supersede"' in text
    # Asserted as JSON keys rather than as bare names: every one of the four is
    # also discussed in the prose below the example, so a search for the name
    # alone stays green over an example that has stopped showing the field.
    for field in ("anchor", "replacement", "by", "was"):
        assert f'"{field}":' in text


def test_the_diff_prompt_example_is_valid_json():
    """The example is the thing a JSON-emitting model copies, so a prompt whose own
    example does not parse teaches output the diff path then throws away
    (`_merge_diff` swallows a JSONDecodeError into an empty patch set, so the cost
    is a silently no-op merge). Asserted by parsing rather than by eye, which is
    also what catches a brace lost while editing the actions."""
    import json
    from kb_ai.prompts import default_registry

    lines = default_registry().get("merge-diff").content.splitlines()
    # Bounded by the two lines that are a lone brace, not by the first and last
    # brace in the file: the Rules below carry a literal `{"patches": []}`.
    start = next(i for i, line in enumerate(lines) if line == "{")
    end = next(i for i, line in enumerate(lines) if i > start and line == "}")

    example = json.loads("\n".join(lines[start:end + 1]))
    actions = [patch["action"] for patch in example["patches"]]
    assert actions == ["append_to_section", "new_section", "supersede"]


# Every rule either prompt states, as one list per prompt, because a rule deleted
# from a prompt is invisible everywhere else until an arm is bought. Each entry is
# the rule's own wording paired with the criterion it comes from -- so a deletion
# fails here, and a rewording fails here with the criterion named.
_SHARED_SUPERSEDE_RULES = [
    ("RA7 `by` is the newest block", "newer than every other date"),
    ("RA7/WP9 no order to act on", "the newest date shared by two"),
    ("RA7 one action per occurrence", "more than one place"),
    ("RA7 the prohibition", "older than the one the article already reflects"),
]

_DIFF_ONLY_RULES = [
    ("RA1 the action is named in Rules", '"supersede": correct an existing statement'),
    ("RA1 four fields and no others", "these four fields and no others"),
    ("RA2/RA7 the anchor is unique", "exactly once"),
    ("RA7 how to make it unique", "Include enough surrounding text"),
    ("RA1 `was` cannot be omitted", '"was" is required'),
    ("RA1 withdrawal is allowed", '"replacement" may be empty'),
    ("RA1 the trail's text is code's", "Do NOT write the bracketed note yourself"),
]

_REWRITE_ONLY_RULES = [
    ("RA6 the rule has a heading of its own", "Superseded claims"),
    ("TR1 the block is single-line", "The note is one line"),
    # The one sentence aimed at the shape A1's arm actually produced. Nothing else
    # in either prompt stands against coequal presentation.
    ("D1 coequal presentation is the failure", "as though both were current"),
    ("D1 one value has to hold", "which value holds now"),
    ("TR3 not the compile date", "never today's date"),
    ("D9 the history is append-only", "must appear in your output word for word"),
    ("TR4 newest first", "newest first"),
]


@pytest.mark.parametrize("prompt,accessor,extra", [
    ("merge-diff", "content", _DIFF_ONLY_RULES),
    ("merge-rewrite", "render", _REWRITE_ONLY_RULES),
])
def test_both_prompts_state_every_rule_supersede_needs(prompt, accessor, extra):
    """RA7's four requirements and its one prohibition on both paths, plus the rules
    only one path can state. The strings are the rules' own wording, so this fails on
    a deletion rather than only on a rewrite -- which is the failure with no other
    detector. RA7's anchor rules are diff-only by construction: the rewrite path
    returns a whole article and has no anchor to make unique."""
    from kb_ai.prompts import default_registry

    entry = default_registry().get(prompt)
    text = entry.content if accessor == "content" else entry.render()

    missing = [f"{criterion}: {rule!r}"
               for criterion, rule in _SHARED_SUPERSEDE_RULES + extra
               if rule not in text]
    assert missing == []


def test_the_rewrite_prompt_teaches_a_trail_its_own_validator_accepts():
    """The two halves of TR6 have to agree: the prompt teaches the format by
    example and _trail_defects reads it back. D1's example is line-wrapped where it
    is written in design-options.md and TR1 makes the block single-line, so a
    verbatim copy of the wrapped form would teach a shape this same code reports as
    malformed on every use. Asserted across the two artifacts rather than inside
    either one, which is the only place the disagreement is visible."""
    from kb_ai.prompts import default_registry

    text = default_registry().get("merge-rewrite").render()
    example = next(line.strip() for line in text.splitlines()
                   if line.strip().startswith("[Superseded "))

    payload = [_block(source_path="raw/plan-v2.md", day=date(2026, 6, 14))]
    assert mg._trail_defects("", example, payload) == []


def test_create_prompt_asks_for_every_source_in_the_frontmatter():
    """The same defect merge-rewrite.md carried, in the sibling path: the
    frontmatter template shows one `sources:` item because the flattened payload
    sent one path. `compile.py` is what writes a multi-source article's *initial*
    list through here, and neither create nor rewrite repairs frontmatter in code
    -- only _apply_diff does -- so completeness on this path is prompt-only."""
    text = mg._create_system("concept")

    assert "one item per path" in text


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

    mg.create_new_article("concept", "T", [_block()])

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

    mg.merge_into_article("wiki/a.md", "short body", [_block()])

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
    mg.merge_into_article("wiki/a.md", big, [_block(_extraction(topics=["s1"]))])

    assert seen["timeout"] == mg._WRITE_CALL_TIMEOUT_S
    assert get_call_timeout() is None
