"""Tests for the shape-B lineage rule (supersession spec RP4, VF4).

The rule was validated on a 996-document corpus before it was code, and the two
exclusions it carries were forced out by that data rather than invented. Both are
pinned here, along with every version-marker form the corpus actually holds --
`v15`, `v1.0.0`, `(v3)` -- because the script that first measured the rule missed
`v1.0.0` and found one group fewer than the corpus has.
"""
from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

from kb_ai.core import merge as mg
from kb_ai.storage.lineage import (
    DocumentFacts,
    known_person_names,
    lineage_groups,
    read_document_facts,
    strip_version_marker,
)


def doc(rel, title, doc_id, source="docs", day=None):
    return DocumentFacts(rel_path=rel, title=title, doc_id=doc_id, source=source,
                         date=day)


# ── the version marker ──────────────────────────────────────────────

def test_a_trailing_version_marker_is_stripped():
    assert strip_version_marker("Gateway Design v1.7") == "Gateway Design"
    assert strip_version_marker("Gateway Design V15") == "Gateway Design"
    assert strip_version_marker("Gateway Design-v2") == "Gateway Design"
    assert strip_version_marker("Report v1.0.0") == "Report"
    # Quoted from the corpus rather than transliterated: the bracketed marker and
    # its fullwidth form both arrive on CJK titles, and a rule that only ever saw
    # ASCII around the marker is not the rule the corpus needs.
    assert strip_version_marker("API 清单 (v3)") == "API 清单"
    assert strip_version_marker("API 清单（V3）") == "API 清单"


def test_a_trailing_number_without_a_v_is_not_a_version_marker():
    """`Report 2026` and `Report 2025` are different documents, not two versions.

    The corpus has titles ending in a year and in a quarter, and collapsing them
    would merge unrelated documents into one chain -- the one error a report of
    this kind cannot afford, since an operator cannot tell it from a real one.
    """
    assert strip_version_marker("Cost Report 2026") == "Cost Report 2026"
    assert strip_version_marker("2026 H1 Cost Tracking") == "2026 H1 Cost Tracking"


def test_a_marker_that_is_not_trailing_is_left_alone():
    assert strip_version_marker("v2 planning notes") == "v2 planning notes"
    assert strip_version_marker("Gateway v1.7 review") == "Gateway v1.7 review"


def test_surrounding_whitespace_is_normalised():
    assert strip_version_marker("  Gateway   Design  v2 ") == "Gateway Design"


# ── grouping ────────────────────────────────────────────────────────

def test_two_documents_whose_titles_differ_only_by_a_marker_are_one_group():
    groups = lineage_groups([
        doc("raw/docs/gw-v15.md", "Gateway Design v15", "id-a", day=date(2026, 3, 23)),
        doc("raw/docs/gw-v17.md", "Gateway Design v17", "id-b", day=date(2026, 3, 30)),
    ])
    assert len(groups) == 1
    assert groups[0].title == "Gateway Design"
    assert groups[0].members == ("raw/docs/gw-v15.md", "raw/docs/gw-v17.md")
    assert groups[0].versioned is True


def test_identical_titles_with_different_ids_are_one_group():
    """P7, P8 and P9 in the fixture are this shape: no marker anywhere.

    Requiring a marker to be present would drop three of the six shape-B
    positives A1 is scored on, so an identical title with two ids is lineage.
    """
    groups = lineage_groups([
        doc("raw/docs/cost-04.md", "2026 H1 Cost Tracking", "id-a", day=date(2026, 4, 9)),
        doc("raw/docs/cost-05.md", "2026 H1 Cost Tracking", "id-b", day=date(2026, 5, 14)),
    ])
    assert len(groups) == 1
    assert groups[0].versioned is False


def test_the_same_document_revised_is_not_shape_b():
    """One `id` over two files is shape A, which the revised report already names."""
    assert lineage_groups([
        doc("raw/docs/a-04-08.md", "Onboarding Plan", "id-a", day=date(2026, 4, 8)),
        doc("raw/docs/a-04-17.md", "Onboarding Plan", "id-a", day=date(2026, 4, 17)),
    ]) == []


def test_a_group_survives_one_repeated_id_among_several_members():
    """Two ingests of one document plus a genuinely different one is still lineage."""
    groups = lineage_groups([
        doc("raw/docs/m-1.md", "Card MoneySend", "id-a", day=date(2026, 4, 13)),
        doc("raw/docs/m-2.md", "Card MoneySend", "id-a", day=date(2026, 4, 25)),
        doc("raw/docs/m-3.md", "Card MoneySend", "id-b", day=date(2026, 4, 26)),
    ])
    assert len(groups) == 1
    assert len(groups[0].members) == 3


def test_a_lone_document_is_not_a_group():
    assert lineage_groups([doc("raw/docs/a.md", "Gateway Design", "id-a")]) == []


def test_a_document_with_no_title_is_ignored():
    assert lineage_groups([
        doc("raw/docs/a.md", "", "id-a"),
        doc("raw/docs/b.md", "", "id-b"),
    ]) == []


def test_a_title_that_is_only_a_marker_is_ignored():
    """Normalising `v2` leaves nothing to match on, so it groups with nothing."""
    assert lineage_groups([
        doc("raw/docs/a.md", "v2", "id-a"),
        doc("raw/docs/b.md", "v3", "id-b"),
    ]) == []


def test_titles_match_case_insensitively():
    groups = lineage_groups([
        doc("raw/docs/a.md", "Driving AI Forward", "id-a", day=date(2026, 3, 5)),
        doc("raw/docs/b.md", "driving ai forward", "id-b", day=date(2026, 3, 6)),
    ])
    assert len(groups) == 1


# ── exclusion 1: cross-source title collisions ──────────────────────

def test_the_same_title_under_two_sources_is_not_lineage():
    """`raw/docs/` holds a design document, `raw/meetings/` the recording of the
    meeting about it, under one title. Neither supersedes the other.
    """
    assert lineage_groups([
        doc("raw/docs/x.md", "Card MoneySend", "id-a", source="docs",
            day=date(2026, 4, 13)),
        doc("raw/meetings/x.md", "Card MoneySend", "id-b", source="meetings",
            day=date(2026, 4, 25)),
    ]) == []


def test_a_cross_source_collision_keeps_the_same_source_members_together():
    """The exclusion is about the pairing, not about the title.

    Two recordings of one meeting still share a source, so they stay a group; the
    design document under the same title is not joined to them.
    """
    groups = lineage_groups([
        doc("raw/docs/x.md", "Card MoneySend", "id-a", source="docs",
            day=date(2026, 4, 13)),
        doc("raw/meetings/x1.md", "Card MoneySend", "id-b", source="meetings",
            day=date(2026, 4, 25)),
        doc("raw/meetings/x2.md", "Card MoneySend", "id-c", source="meetings",
            day=date(2026, 4, 26)),
    ])
    assert len(groups) == 1
    assert groups[0].source == "meetings"
    assert groups[0].members == ("raw/meetings/x1.md", "raw/meetings/x2.md")


def test_documents_with_no_source_still_group_among_themselves():
    """A hand-authored KB has no `source:` key, and the rule must not need one."""
    groups = lineage_groups([
        doc("raw/a.md", "Plan", "id-a", source="", day=date(2026, 1, 1)),
        doc("raw/b.md", "Plan v2", "id-b", source="", day=date(2026, 2, 1)),
    ])
    assert len(groups) == 1


# ── exclusion 2: person-name collisions ─────────────────────────────

def test_a_person_name_is_not_a_document_title():
    """Three meetings named `Cara` collide under the title rule.

    A recurring one-to-one is titled with the person's name, so the members are
    unrelated conversations rather than versions of one document.
    """
    assert lineage_groups([
        doc("raw/meetings/cara-1.md", "Cara", "id-a", source="meetings",
            day=date(2026, 1, 1)),
        doc("raw/meetings/cara-2.md", "Cara", "id-b", source="meetings",
            day=date(2026, 4, 21)),
    ], person_names=["cara"]) == []


def test_the_person_exclusion_ignores_case_and_marker():
    assert lineage_groups([
        doc("raw/meetings/a.md", "  cara ", "id-a", source="meetings"),
        doc("raw/meetings/b.md", "Cara v2", "id-b", source="meetings"),
    ], person_names=["Cara"]) == []


def test_a_person_name_inside_a_longer_title_is_not_excluded():
    groups = lineage_groups([
        doc("raw/docs/a.md", "Cara onboarding plan", "id-a"),
        doc("raw/docs/b.md", "Cara onboarding plan v2", "id-b"),
    ], person_names=["cara"])
    assert len(groups) == 1


# ── ordering ────────────────────────────────────────────────────────

def test_members_run_oldest_first_with_undated_last_in_path_order():
    """Same order the writer's blocks use (WP5), so the two cannot disagree about
    which member is the later one.
    """
    groups = lineage_groups([
        doc("raw/docs/z.md", "Plan", "id-z"),
        doc("raw/docs/b.md", "Plan v2", "id-b", day=date(2026, 5, 1)),
        doc("raw/docs/a.md", "Plan", "id-a"),
        doc("raw/docs/c.md", "Plan v3", "id-c", day=date(2026, 4, 1)),
    ])
    assert groups[0].members == ("raw/docs/c.md", "raw/docs/b.md",
                                 "raw/docs/a.md", "raw/docs/z.md")


def test_groups_come_back_in_a_deterministic_order():
    docs = [
        doc("raw/docs/b1.md", "Beta", "id-1"), doc("raw/docs/b2.md", "Beta v2", "id-2"),
        doc("raw/docs/a1.md", "Alpha", "id-3"), doc("raw/docs/a2.md", "Alpha v2", "id-4"),
    ]
    assert [g.title for g in lineage_groups(docs)] == ["Alpha", "Beta"]
    assert [g.title for g in lineage_groups(list(reversed(docs)))] == ["Alpha", "Beta"]


# ── reading the facts off disk ───────────────────────────────────────

def test_a_document_that_cannot_be_read_contributes_no_facts():
    """The report runs after the last write op, and a document that went away
    between the scan and the report must not fail the compile it summarises.
    """
    def boom(_rel):
        raise FileNotFoundError("gone")

    assert read_document_facts(boom, "raw/a.md") == DocumentFacts(rel_path="raw/a.md")


def test_facts_come_from_the_documents_own_frontmatter():
    def reader(_rel):
        return ('---\nsource: docs\nid: "id-a"\ndate: 2026-03-23\n'
                'title: "Gateway Design v1.5"\n---\n\nbody\n')

    assert read_document_facts(reader, "raw/gw.md") == DocumentFacts(
        rel_path="raw/gw.md", title="Gateway Design v1.5", doc_id="id-a",
        source="docs", date=date(2026, 3, 23))


def test_an_undated_document_reads_back_undated():
    assert read_document_facts(lambda _r: "no frontmatter here\n",
                              "raw/a.md").date is None


# ── the person names the exclusion is fed ───────────────────────────

def test_person_names_come_from_the_pages_and_the_allowlist(tmp_path):
    (tmp_path / "person").mkdir()
    (tmp_path / "person" / "ada-lovelace.md").write_text(
        "---\ntitle: Ada Lovelace (analyst)\n---\n\nbio\n")

    names = known_person_names(tmp_path, [{"canonical": "Cara",
                                           "aliases": ["cara.zhang"]}])

    assert {"Ada Lovelace (analyst)", "ada lovelace", "Cara", "cara.zhang"} <= names


def test_the_legacy_plural_person_directory_is_read_too():
    """A KB converted from the pre-`person` layout keeps `wiki/people/`."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        wiki = Path(tmp)
        (wiki / "people").mkdir()
        (wiki / "people" / "cara.md").write_text("no frontmatter\n")
        assert "cara" in known_person_names(wiki)


def test_an_unreadable_person_page_still_yields_its_stem(tmp_path):
    """Malformed frontmatter costs the title, not the name: the stem is the file's
    own and is what a stub page is named after.
    """
    (tmp_path / "person").mkdir()
    (tmp_path / "person" / "cara.md").write_text("---\ntitle: [unclosed\n---\n\nbio\n")
    (tmp_path / "person" / "ben.md").write_text("---\ndate: 0000-01-01\n---\n\nbio\n")

    names = known_person_names(tmp_path)

    assert {"cara", "ben"} <= names


def test_a_malformed_allowlist_entry_is_skipped(tmp_path):
    assert known_person_names(tmp_path, ["Cara", {"canonical": "Ben"}]) == {"Ben"}


def test_no_person_pages_and_no_allowlist_is_an_empty_set(tmp_path):
    assert known_person_names(tmp_path) == set()


# ── RP5: the rule stays out of the write path ───────────────────────

def test_the_write_phase_does_not_import_the_lineage_rule():
    """RP5, checked structurally rather than by reading the prompts.

    A title heuristic that steers what gets written is what D2's gate on build path
    B refuses. An import is how that would start, so the absence of one is the
    guarantee -- asserted over the module's imports rather than its text, because
    ``core.merge`` legitimately discusses the corpus's lineage groups in a docstring.
    """
    tree = ast.parse(Path(inspect.getfile(mg)).read_text())
    imported = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("lineage" in name for name in imported)


def test_the_reported_title_keeps_the_casing_of_its_earliest_member():
    groups = lineage_groups([
        doc("raw/docs/b.md", "gateway design v2", "id-b", day=date(2026, 2, 1)),
        doc("raw/docs/a.md", "Gateway Design", "id-a", day=date(2026, 1, 1)),
    ])
    assert groups[0].title == "Gateway Design"
