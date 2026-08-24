"""Tests for the article-shape audit both FX4 arms run (spec FX4).

Two defects the fixture surfaced and nothing in the pipeline catches. An article
whose `sources` entries pack several paths into one YAML item is not an
attributable unit, which is the claim G2 makes; an article whose frontmatter does
not start at byte 0 has no readable keys at all, because `split_frontmatter`
returns None for content that does not open with a delimiter line -- no title for
the catalog, no date for WP2, and no sources for `derive` to copy.

The audit walks the filesystem rather than the index on purpose: the index is
built from the same frontmatter the second defect hides, so an article with an
unreachable block is invisible to every reader that goes through it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_articles as aa  # noqa: E402


def article(kb: Path, rel: str, content: str) -> None:
    path = kb / "wiki" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fm(*sources: str, title: str = "A") -> str:
    lines = [f"- {s}" for s in sources]
    body = "\n".join(f"  {line}" for line in lines)
    return f"---\ntitle: {title}\nsources:\n{body}\n---\n\nBody.\n"


# ── the clean case ──────────────────────────────────────────────────

def test_a_clean_kb_reports_nothing(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md", "raw/docs/b.md"))
    article(tmp_path, "concept/b.md", fm("raw/docs/c.md"))

    report = aa.audit(tmp_path)

    assert report["articles"] == 2
    assert report["comma_packed"] == {"entries": 0, "articles": []}
    assert report["duplicated_paths"] == {"occurrences": 0, "articles": []}
    assert report["unreachable_frontmatter"] == []
    assert aa.failed(report) is False


# ── comma-packed entries ────────────────────────────────────────────

def test_one_entry_holding_two_paths_is_comma_packed(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md, raw/docs/b.md"))

    report = aa.audit(tmp_path)

    assert report["comma_packed"] == {"entries": 1,
                                     "articles": ["wiki/project/a.md"]}
    assert aa.failed(report) is True


def test_an_entry_is_counted_once_however_many_paths_it_packs(tmp_path):
    """The corpus figure is 91 entries across 46 articles, so the unit being
    counted has to be the entry rather than the path behind it."""
    article(tmp_path, "project/a.md", fm("a.md, b.md, c.md, d.md"))

    assert aa.audit(tmp_path)["comma_packed"]["entries"] == 1


def test_a_trailing_comma_does_not_pack_an_entry(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md,"))

    assert aa.audit(tmp_path)["comma_packed"]["entries"] == 0


# ── duplicated paths ────────────────────────────────────────────────

def test_a_literally_repeated_entry_is_a_duplicate(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md", "raw/docs/a.md"))

    report = aa.audit(tmp_path)

    assert report["duplicated_paths"] == {"occurrences": 1,
                                         "articles": ["wiki/project/a.md"]}


def test_a_duplicate_only_visible_after_splitting_still_counts(tmp_path):
    """21 articles duplicate a literal item and 30 do once the comma-packed items
    are split, which is how the paths have to be read."""
    article(tmp_path, "project/a.md", fm("raw/docs/a.md, raw/docs/b.md",
                                         "raw/docs/b.md"))

    report = aa.audit(tmp_path)

    assert report["duplicated_paths"]["occurrences"] == 1
    assert report["duplicated_paths"]["articles"] == ["wiki/project/a.md"]


def test_a_path_listed_three_times_counts_two_extra_occurrences(tmp_path):
    """47 occurrences across 30 articles: the double-count the U1-U4 controls
    exist to catch is per extra listing, not per article."""
    article(tmp_path, "project/a.md", fm("a.md", "a.md", "a.md"))

    assert aa.audit(tmp_path)["duplicated_paths"]["occurrences"] == 2


# ── unreachable frontmatter ─────────────────────────────────────────

def test_prose_above_the_delimiter_hides_every_key(tmp_path):
    """`wiki/decision/web3-cluster-decision.md`'s shape: the writer's own preamble
    stands above the block."""
    article(tmp_path, "decision/a.md",
            "Looking at the new information, it's largely already captured.\n\n"
            + fm("raw/docs/a.md"))

    report = aa.audit(tmp_path)

    assert report["unreachable_frontmatter"] == [
        {"article": "wiki/decision/a.md", "reason": "no_leading_delimiter"}]
    assert aa.failed(report) is True


def test_a_markdown_fence_above_the_delimiter_is_the_same_defect(tmp_path):
    """`wiki/project/ddq-auto-fill-tool.md` additionally wraps the article in a
    fence."""
    article(tmp_path, "project/a.md", "```markdown\n" + fm("raw/docs/a.md"))

    assert aa.audit(tmp_path)["unreachable_frontmatter"] == [
        {"article": "wiki/project/a.md", "reason": "no_leading_delimiter"}]


def test_a_hidden_block_contributes_no_sources_findings(tmp_path):
    """The point of the check: for these articles every key is invisible to every
    reader, so their sources cannot be audited at all rather than reading clean."""
    article(tmp_path, "project/a.md",
            "preamble\n\n" + fm("a.md, b.md", "a.md"))

    report = aa.audit(tmp_path)

    assert report["comma_packed"]["entries"] == 0
    assert report["duplicated_paths"]["occurrences"] == 0
    assert report["unreachable_frontmatter"][0]["article"] == "wiki/project/a.md"


def test_a_bom_is_reported_apart_from_the_hidden_block(tmp_path):
    """A BOM shifts the delimiter off byte 0 but every reader here strips it, so
    it is not the defect the seven articles carry."""
    article(tmp_path, "project/a.md", "﻿" + fm("raw/docs/a.md"))

    report = aa.audit(tmp_path)

    assert report["unreachable_frontmatter"] == []
    assert report["delimiter_not_at_byte_0"] == ["wiki/project/a.md"]
    assert aa.failed(report) is False


def test_frontmatter_nobody_can_parse_is_reported_rather_than_raised(tmp_path):
    article(tmp_path, "project/a.md", "---\nsources: [a.md\n---\n\nBody.\n")

    report = aa.audit(tmp_path)

    assert report["unparseable_frontmatter"] == ["wiki/project/a.md"]
    assert aa.failed(report) is True


def test_a_bare_string_sources_value_is_still_audited(tmp_path):
    """One article holding `sources: a.md, b.md` as a scalar is making the same
    provenance claim as a one-item list, and packs the same two paths."""
    article(tmp_path, "project/a.md",
            "---\ntitle: A\nsources: raw/docs/a.md, raw/docs/b.md\n---\n\nBody.\n")

    report = aa.audit(tmp_path)

    assert report["comma_packed"]["entries"] == 1
    assert report["without_sources"] == []


def test_an_empty_sources_value_reads_as_no_sources(tmp_path):
    article(tmp_path, "project/a.md", "---\ntitle: A\nsources:\n---\n\nBody.\n")

    assert aa.audit(tmp_path)["without_sources"] == ["wiki/project/a.md"]


def test_frontmatter_that_is_not_a_mapping_is_unparseable(tmp_path):
    article(tmp_path, "project/a.md", "---\n- just\n- a list\n---\n\nBody.\n")

    report = aa.audit(tmp_path)

    assert report["unparseable_frontmatter"] == ["wiki/project/a.md"]
    assert aa.failed(report) is True


def test_a_block_that_is_never_closed_is_its_own_reason(tmp_path):
    """`split_frontmatter` returns None for this too, but the article does open at
    byte 0, so calling it `no_leading_delimiter` would misdescribe it."""
    article(tmp_path, "project/a.md", "---\ntitle: A\nsources:\n  - a.md\n\nBody.\n")

    assert aa.audit(tmp_path)["unreachable_frontmatter"] == [
        {"article": "wiki/project/a.md", "reason": "unclosed_block"}]


def test_an_article_without_sources_is_recorded_but_does_not_fail(tmp_path):
    article(tmp_path, "project/a.md", "---\ntitle: A\n---\n\nBody.\n")

    report = aa.audit(tmp_path)

    assert report["without_sources"] == ["wiki/project/a.md"]
    assert aa.failed(report) is False


# ── what the walk covers ────────────────────────────────────────────

def test_only_wiki_markdown_is_audited(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md"))
    (tmp_path / "raw" / "docs").mkdir(parents=True)
    (tmp_path / "raw" / "docs" / "b.md").write_text("preamble\n", encoding="utf-8")
    (tmp_path / "wiki" / "project" / "notes.txt").write_text("x", encoding="utf-8")

    report = aa.audit(tmp_path)

    assert report["articles"] == 1
    assert report["unreachable_frontmatter"] == []


def test_the_catalog_is_outside_the_walk(tmp_path):
    """The catalog lives at `<kb>/index`, not under `wiki/`, so it needs no
    exclusion — it is never reached."""
    article(tmp_path, "project/a.md", fm("raw/docs/a.md"))
    (tmp_path / "index").mkdir()
    (tmp_path / "index" / "catalog.md").write_text("catalog\n", encoding="utf-8")

    assert aa.audit(tmp_path)["articles"] == 1


def test_a_kb_with_no_wiki_directory_audits_to_nothing(tmp_path):
    report = aa.audit(tmp_path)

    assert report["articles"] == 0
    assert aa.failed(report) is False


# ── the CLI ─────────────────────────────────────────────────────────

def test_the_cli_writes_the_report_and_exits_nonzero_on_a_finding(tmp_path,
                                                                 capsys):
    article(tmp_path, "project/a.md", fm("a.md, b.md"))
    out = tmp_path / "report.json"

    rc = aa.main(["--kb", str(tmp_path), "--out", str(out)])

    assert rc == 1
    assert json.loads(out.read_text(encoding="utf-8"))["comma_packed"][
        "entries"] == 1
    assert "1 comma-packed" in capsys.readouterr().out


def test_the_cli_exits_zero_on_a_clean_kb(tmp_path):
    article(tmp_path, "project/a.md", fm("raw/docs/a.md"))

    assert aa.main(["--kb", str(tmp_path)]) == 0
