"""Tests for the supersession case selector (spec FX1).

The selector recovers what a throwaway script measured on a 996-document corpus
and then took with it when it was deleted. Its output survived as `cases.json`, so
each rule below was reconstructed against that file and reproduces it exactly on
the corpus: all 79 non-identical chains' diffstats, and all 134 strata. The rules
are pinned here rather than the corpus numbers, because the corpus is gitignored.

Where the selector *deliberately* differs from that output, the reason is a defect
in the original rather than a change of rule, and each has a test: comma-joined
`sources:` entries (which the original read as one path, undercounting the
shared-article column), and the two exclusions the shape-B rule carries.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kb_ai.storage.store import KBStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import select_cases as sc  # noqa: E402


def raw(title, doc_id, day, body, source="docs", checksum="c0"):
    return (f"---\nsource: {source}\nid: \"{doc_id}\"\ndate: {day}\n"
            f"title: \"{title}\"\nchecksum: {checksum}\n---\n\n{body}")


# ── the diffed text ─────────────────────────────────────────────────

def test_the_frontmatter_is_not_diffed():
    """Every version differs in `date`, `id` and `checksum`, so diffing the whole
    file reports three changed lines on documents whose bodies are identical.
    """
    a = sc.body_lines(raw("Plan", "id-a", "2026-01-01", "one\ntwo\n"))
    b = sc.body_lines(raw("Plan", "id-b", "2026-02-01", "one\ntwo\n"))

    assert sc.diffstat(a, b) == (0, 0, 1.0)


def test_a_document_with_no_frontmatter_is_diffed_whole():
    assert sc.body_lines("one\ntwo\n") == ["", "one", "two"]


def test_the_body_keeps_the_lines_the_frontmatter_left_behind():
    """Two empty leading lines, and both are the recorded corpus counts'.

    One is the line break that ended the closing delimiter, which the original
    kept because it split on the delimiter rather than on lines; the other is the
    blank line every fetched document carries between its frontmatter and its
    body. A count that disagreed by one per document would move every stratum
    boundary case.
    """
    assert sc.body_lines(raw("Plan", "id-a", "2026-01-01", "one\n")) == ["", "", "one"]


# ── diffstat ────────────────────────────────────────────────────────

def test_diffstat_counts_added_and_removed_lines_and_similarity():
    added, removed, sim = sc.diffstat(["", "a", "b", "c"], ["", "a", "x", "y", "z"])

    assert (added, removed) == (3, 2)
    assert sim == pytest.approx(0.444, abs=0.001)


def test_a_replaced_line_counts_on_both_sides():
    assert sc.diffstat(["a"], ["b"]) == (1, 1, 0.0)


def test_identical_text_is_similarity_one():
    assert sc.diffstat(["a", "b"], ["a", "b"]) == (0, 0, 1.0)


# ── strata ──────────────────────────────────────────────────────────

def test_identical_bytes_are_the_duplicate_stratum():
    assert sc.stratum(True, 0, 0, 1.0) == "D-duplicate"


def test_a_pure_append_is_a_negative_control_however_much_it_adds():
    """The rule the reconstruction got wrong first, and the corpus settled.

    A later version that only appends is a negative control — marking anything in
    it superseded is a false positive. Two corpus groups add 134 and 182 lines
    while removing 2 and 1, which drives similarity to 0.056 and 0.367; ordering
    the similarity test first classified both as rewrites, so the append test has
    to come first.
    """
    assert sc.stratum(False, 134, 2, 0.056) == "B-append-only"
    assert sc.stratum(False, 182, 1, 0.367) == "B-append-only"


def test_a_small_edit_on_both_sides_is_noise():
    assert sc.stratum(False, 3, 3, 0.99) == "C-noise"


def test_a_large_removal_at_high_similarity_is_an_edit():
    assert sc.stratum(False, 200, 100, 0.878) == "A2-edit"


def test_a_low_similarity_rewrite_that_also_removes_is_a_rewrite():
    assert sc.stratum(False, 276, 45, 0.042) == "A1-rewrite"


# ── chains ──────────────────────────────────────────────────────────

@pytest.fixture
def kb(tmp_path) -> KBStore:
    return KBStore(str(tmp_path))


def test_one_id_over_two_files_is_a_shape_a_chain(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))

    cases = sc.select_cases(kb)

    assert [(c["shape"], c["key"], c["chain"]) for c in cases] == [
        ("A", "id-a", ["raw/a.md", "raw/b.md"])]


def test_two_ids_under_one_title_are_a_shape_b_chain(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n"))
    kb.write_raw("raw/b.md", raw("Plan v2", "id-b", "2026-02-01", "two\n"))

    cases = sc.select_cases(kb)

    assert [(c["shape"], c["key"]) for c in cases] == [("B", "Plan")]


def test_a_chain_runs_in_date_order(kb):
    kb.write_raw("raw/late.md", raw("Plan", "id-a", "2026-03-01", "c\n"))
    kb.write_raw("raw/early.md", raw("Plan", "id-a", "2026-01-01", "a\n"))

    assert sc.select_cases(kb)[0]["chain"] == ["raw/early.md", "raw/late.md"]


def test_the_diffstat_spans_the_first_and_last_member(kb):
    """A four-version chain is scored end to end, not step by step: what an article
    has to get right is the latest version against the earliest it absorbed.
    """
    for i, day in enumerate(("2026-01-01", "2026-02-01", "2026-03-01")):
        kb.write_raw(f"raw/v{i}.md", raw("Plan", "id-a", day, "line\n" * (i + 1),
                                        checksum=f"c{i}"))

    case = sc.select_cases(kb)[0]

    assert case["n"] == 3
    assert (case["linesV1"], case["linesVn"]) == (3, 5)


def test_identical_checksums_across_a_chain_mark_it_duplicate(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="same"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="same"))

    case = sc.select_cases(kb)[0]

    assert case["identical"] is True
    assert case["stratum"] == "D-duplicate"


def test_a_lone_document_is_no_chain(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n"))

    assert sc.select_cases(kb) == []


def test_the_shape_b_exclusions_apply(kb):
    """The selector groups shape B through storage.lineage, so a cross-source
    collision and a person-named meeting are excluded here too — the original
    script had neither exclusion in the file it emitted, which is why its 40 groups
    include three cross-source pairs and a set of one-to-ones.
    """
    kb.write_raw("raw/d.md", raw("Card", "id-a", "2026-01-01", "x\n", source="docs"))
    kb.write_raw("raw/m.md", raw("Card", "id-b", "2026-02-01", "y\n", source="meetings"))

    assert [c["shape"] for c in sc.select_cases(kb)] == []


# ── shared articles ─────────────────────────────────────────────────

def test_an_article_citing_every_member_is_the_shared_article(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))
    kb.write_article("wiki/concept/p.md",
                     "---\ntitle: P\nsources:\n  - raw/a.md\n  - raw/b.md\n---\n\nbody\n")

    assert sc.select_cases(kb)[0]["shared_article"] == ["wiki/concept/p.md"]


def test_an_article_citing_only_one_member_is_not_shared(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))
    kb.write_article("wiki/concept/p.md",
                     "---\ntitle: P\nsources:\n  - raw/a.md\n---\n\nbody\n")

    assert sc.select_cases(kb)[0]["shared_article"] == []


def test_a_comma_joined_sources_entry_still_counts_as_citing_both(kb):
    """Articles written before per-source blocks put a whole batch in one entry.

    Reading that as a single path is what made the original script report 34
    duplicate-stratum groups as sharing an article where the corpus has 43, and
    10 rewrites where it has 12 — the column that decides which cases are worth
    labelling at all.
    """
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))
    kb.write_article("wiki/concept/p.md",
                     "---\ntitle: P\nsources:\n  - raw/a.md, raw/b.md\n---\n\nbody\n")

    assert sc.select_cases(kb)[0]["shared_article"] == ["wiki/concept/p.md"]


def test_an_article_with_unreadable_frontmatter_is_skipped(kb):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))
    kb.write_article("wiki/concept/bad.md", "no frontmatter at all\n")

    assert sc.select_cases(kb)[0]["shared_article"] == []


# ── output ──────────────────────────────────────────────────────────

def test_cases_come_back_in_a_deterministic_order(kb):
    kb.write_raw("raw/b1.md", raw("Beta", "id-1", "2026-01-01", "x\n"))
    kb.write_raw("raw/b2.md", raw("Beta", "id-1", "2026-02-01", "y\n", checksum="c2"))
    kb.write_raw("raw/a1.md", raw("Alpha", "id-2", "2026-01-01", "x\n"))
    kb.write_raw("raw/a2.md", raw("Alpha", "id-2", "2026-02-01", "y\n", checksum="c2"))

    assert [c["title"] for c in sc.select_cases(kb)] == ["Alpha", "Beta"]


# ── the command line ────────────────────────────────────────────────

def test_main_writes_the_cases_to_the_named_file(kb, tmp_path, capsys):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))
    # With an article citing the whole chain, so the summary's shared-article count
    # is exercised -- that column is what decides which cases are worth labelling.
    kb.write_article("wiki/concept/p.md",
                     "---\ntitle: P\nsources:\n  - raw/a.md\n  - raw/b.md\n---\n\nbody\n")
    out = tmp_path / "cases.json"

    assert sc.main(["--kb", str(kb.base_dir), "--out", str(out)]) == 0

    import json
    assert [c["key"] for c in json.loads(out.read_text())] == ["id-a"]
    assert "1 chains" in capsys.readouterr().err


def test_main_prints_the_cases_when_no_file_is_named(kb, capsys):
    kb.write_raw("raw/a.md", raw("Plan", "id-a", "2026-01-01", "one\n", checksum="c1"))
    kb.write_raw("raw/b.md", raw("Plan", "id-a", "2026-02-01", "two\n", checksum="c2"))

    assert sc.main(["--kb", str(kb.base_dir)]) == 0

    captured = capsys.readouterr()
    assert '"key": "id-a"' in captured.out
    assert "A1-rewrite" in captured.err or "C-noise" in captured.err
