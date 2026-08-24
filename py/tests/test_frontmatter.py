"""Tests for _frontmatter.py -- splitting a YAML frontmatter block from a body,
and the looser raw-document reader layered on top of it.
"""
from __future__ import annotations

import datetime

import pytest
import yaml

from kb_ai._frontmatter import read_document_frontmatter, split_frontmatter


def test_splits_a_normal_article():
    assert split_frontmatter("---\ntitle: One\n---\n\n# Body\n") == (
        "title: One\n", "\n# Body\n")


def test_a_value_containing_three_dashes_stays_whole():
    # The defect this module exists for: splitting on the first "---" anywhere
    # cut the value in half and dropped every key after it.
    fm, body = split_frontmatter(
        "---\nsources:\n  - raw/a---b.md\ncreated: 2026-08-06\n---\n\n# Body\n")
    assert "raw/a---b.md" in fm
    assert "created: 2026-08-06" in fm
    assert body == "\n# Body\n"


def test_a_horizontal_rule_in_the_body_stays_in_the_body():
    fm, body = split_frontmatter("---\ntitle: One\n---\n\nabove\n\n---\n\nbelow\n")
    assert fm == "title: One\n"
    assert body == "\nabove\n\n---\n\nbelow\n"


def test_content_without_a_leading_delimiter_has_no_frontmatter():
    assert split_frontmatter("# Body only\n") is None


def test_an_unterminated_block_has_no_frontmatter():
    assert split_frontmatter("---\ntitle: One\n\n# Body\n") is None


def test_a_first_line_that_only_starts_with_dashes_is_not_a_delimiter():
    # "---" must be the whole line; "----" or "--- title" is not an opener.
    assert split_frontmatter("--- title: One\n---\n\n# Body\n") is None


def test_empty_frontmatter_is_still_a_block():
    assert split_frontmatter("---\n---\n\n# Body\n") == ("", "\n# Body\n")


def test_carriage_returns_around_the_delimiter_are_tolerated():
    fm, body = split_frontmatter("---\r\ntitle: One\r\n---\r\n\r\n# Body\r\n")
    assert "title: One" in fm
    assert "# Body" in body


def test_an_empty_document_has_no_frontmatter():
    assert split_frontmatter("") is None


def test_an_indented_delimiter_does_not_close_the_block():
    """PyYAML renders a value containing a bare "---" line as a multi-line quoted
    scalar whose continuation lines are indented. Closing on strip() read that
    continuation as the end of the block: it truncated mid-scalar, safe_load then
    raised, and every key after the truncation point was lost.
    """
    import yaml

    content = "---\n" + yaml.safe_dump(
        {"summary": "first\n\n---\n\nsecond", "schema_version": 1},
        default_flow_style=False, width=10 ** 6) + "---\n\n# Body\n"

    fm, body = split_frontmatter(content)

    loaded = yaml.safe_load(fm)
    assert loaded["summary"] == "first\n\n---\n\nsecond"
    assert loaded["schema_version"] == 1, "no key after the indented --- was lost"
    assert body == "\n# Body\n"


def test_trailing_whitespace_on_a_real_delimiter_still_closes_the_block():
    """The one case strip() was buying, kept by rstrip()."""
    assert split_frontmatter("---\ntitle: One\n---  \n\n# Body\n") == (
        "title: One\n", "\n# Body\n")


# ── read_document_frontmatter: the raw-document reader ──────────────
#
# Moved here from test_storage_index.py when the reader was promoted out of
# storage.index so the write phase could share it (spec RT6).

def test_a_document_without_frontmatter_reads_as_body_only():
    content = "# Just a heading\n\nand prose.\n"
    assert read_document_frontmatter(content) == ({}, content)


def test_an_empty_document_reads_as_body_only():
    assert read_document_frontmatter("") == ({}, "")


def test_a_document_frontmatter_is_returned_as_a_mapping():
    fm, body = read_document_frontmatter(
        "---\ntitle: One\ndate: 2026-06-01\n---\n\nbody\n")
    assert fm == {"title": "One", "date": datetime.date(2026, 6, 1)}
    assert body == "\nbody\n"


def test_an_iso_date_arrives_as_a_date_and_a_stamp_as_a_datetime():
    """What the write phase will consume, pinned: PyYAML resolves both spellings
    the submit route may write, so a reader of `date` must expect an object and
    not a string. The catalog only ever str()s it, so this has been invisible.
    """
    fm, _body = read_document_frontmatter("---\ndate: 2026-08-12T09:15:00Z\n---\n\nb\n")
    assert isinstance(fm["date"], datetime.datetime)
    assert str(fm["date"]) == "2026-08-12 09:15:00+00:00"


def test_a_malformed_date_stays_the_raw_scalar_rather_than_raising():
    """A date nobody can parse must leave the document listed and selectable, just
    unordered -- the same bargain the whole reader makes for malformed frontmatter.
    """
    fm, body = read_document_frontmatter("---\ndate: last Tuesday-ish\n---\n\nbody\n")
    assert fm == {"date": "last Tuesday-ish"}
    assert body == "\nbody\n"


def test_a_declared_but_empty_date_is_none_not_a_missing_key():
    """`date:` with nothing after it parses to None. Callers must test the value,
    not the key: `"date" in fm` is True here and there is still no date.
    """
    fm, _body = read_document_frontmatter("---\ndate:\ntitle: One\n---\n\nbody\n")
    assert fm == {"date": None, "title": "One"}


def test_a_date_no_calendar_accepts_leaves_the_document_unlabelled():
    """`date: 0000-01-01` is well-formed YAML that datetime refuses, and the
    ValueError it raises is not a yaml.YAMLError. One such file under raw/ used to
    abort build_document_catalog for every document beside it.
    """
    fm, body = read_document_frontmatter("---\ndate: 0000-01-01\ntitle: One\n---\n\nbody\n")
    assert fm == {}
    assert body == "\nbody\n"


def test_frontmatter_that_is_not_a_mapping_reads_as_no_frontmatter():
    fm, body = read_document_frontmatter("---\n- one\n- two\n---\n\nbody\n")
    assert fm == {}
    assert body == "\nbody\n"


def test_keeps_content_whole_when_the_comment_hides_no_mapping():
    """The retry adopts a mapping only. A comment followed by a horizontal rule would
    otherwise parse the first paragraph as frontmatter and return a body missing
    everything above the second rule -- content loss, where the status quo costs
    only labels.
    """
    content = "<!-- source: /tmp/a.md -->\n\n---\n\nThe only paragraph.\n\n---\n\ntail\n"
    assert read_document_frontmatter(content) == ({}, content)


def test_keeps_content_whole_on_broken_frontmatter_behind_a_comment():
    content = '<!-- source: /tmp/a.md -->\n\n---\ntitle: "unclosed\n---\n\nbody\n'
    assert read_document_frontmatter(content) == ({}, content)


def test_still_needs_a_closing_delimiter_behind_a_comment():
    """The comment skip consumes blank lines and nothing else, so an indented `---`
    still fails to close a block -- the case split_frontmatter's rstrip() exists for.
    Note the *opening* delimiter is matched on strip(), so indenting that one has
    never mattered."""
    content = "<!-- source: /tmp/a.md -->\n\n---\ntitle: Sneaky\n  ---\n\nbody\n"
    assert read_document_frontmatter(content) == ({}, content)


@pytest.mark.parametrize("content, expected_title", [
    # A POSIX filename may contain a newline, so distill's comment can span lines.
    ("<!-- source: /tmp/two\nlines.md -->\n\n---\ntitle: Wrapped\n---\n\nbody\n", "Wrapped"),
    # No blank line between the comment and the delimiter.
    ("<!-- source: /tmp/a.md -->\n---\ntitle: Tight\n---\n\nbody\n", "Tight"),
    # CRLF throughout, as a document exported from Windows arrives.
    ("<!-- source: /tmp/a.md -->\r\n\r\n---\r\ntitle: Crlf\r\n---\r\n\r\nbody\r\n", "Crlf"),
    # Re-ingesting a file distill already ingested stacks a second comment.
    ("<!-- source: /kb/raw/a.md -->\n\n<!-- source: /tmp/a.md -->\n\n"
     "---\ntitle: Stacked\n---\n\nbody\n", "Stacked"),
])
def test_reads_frontmatter_behind_comment_shapes(content, expected_title):
    fm, _body = read_document_frontmatter(content)
    assert fm == {"title": expected_title}


def test_reads_the_block_the_submit_route_writes():
    """Parity fixture for the Go writer (spec RT2): this is byte-for-byte what
    internal/frontmatter.WithDate emits, asserted in
    TestWithDate_PrependedBlockCarriesExtraFields. The two ends have no shared
    definition of the format, so each pins the same bytes.
    """
    content = ('---\ndate: 2026-06-01\nsource: "paste"\n'
               'title: "Q3: the \\"plan\\""\n---\n\nbody\n')

    fm, body = read_document_frontmatter(content)

    assert fm == {
        "date": datetime.date(2026, 6, 1),
        "source": "paste",
        "title": 'Q3: the "plan"',
    }
    assert body == "\nbody\n"


def test_reads_the_stamped_block_the_submit_route_writes_without_a_caller_date():
    """The other spelling that route emits: RFC3339 when it stamps its own clock."""
    fm, _body = read_document_frontmatter(
        '---\ndate: 2026-08-12T09:15:00Z\nsource: "url"\n---\n\nbody\n')

    assert isinstance(fm["date"], datetime.datetime)
    assert fm["source"] == "url"


def test_reads_a_date_the_submit_route_inserted_into_a_document_of_its_own():
    """Second RT9 shape: the date goes inside the document's own block, so the
    document keeps the keys it brought. Parity fixture for
    TestWithDate_InsertsIntoAnExistingBlockRatherThanStackingOne.
    """
    fm, body = read_document_frontmatter(
        "---\ndate: 2026-06-01\ntitle: The Plan\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "The Plan"}
    assert body == "\nbody\n"


def test_reads_a_date_inserted_into_an_indented_block():
    """A mapping indented as a whole is valid YAML, and a date written at column 0
    inside one makes PyYAML read the entire block as nothing -- the document's own
    labels lost along with the date. Parity fixture for
    TestWithDate_MatchesTheIndentationOfAnIndentedBlock.
    """
    fm, body = read_document_frontmatter(
        "---\n  date: 2026-06-01\n  title: The Plan\n  author: bob\n---\n\nbody\n")

    assert fm == {
        "date": datetime.date(2026, 6, 1),
        "title": "The Plan",
        "author": "bob",
    }
    assert body == "\nbody\n"


def test_reads_a_date_inserted_into_a_crlf_document():
    """Parity fixture for TestWithDate_KeepsCRLFWhenInsertingIntoABlock. The
    writer keeps the document's own line ending, and splitlines/rstrip here have
    to agree that "---\\r\\n" still closes the block.
    """
    fm, body = read_document_frontmatter(
        "---\r\ndate: 2026-06-01\r\ntitle: One\r\n---\r\n\r\nbody\r\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "One"}
    assert body == "\r\nbody\r\n"


def test_reads_a_date_inserted_behind_a_provenance_comment():
    """Parity fixture for TestWithDate_InsertsBehindAProvenanceComment: a document
    distill already ingested keeps the comment and gains a date behind it.
    """
    fm, body = read_document_frontmatter(
        "<!-- source: /tmp/a.md -->\n\n---\ndate: 2026-06-01\ntitle: One\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "One"}
    assert body == "\nbody\n"


def test_reads_a_date_inserted_above_a_yaml_comment():
    """Parity fixture for TestWithDate_InsertsAtTheKeyIndentationNotACommentsOwn.
    The block's level is the level its keys sit at; taking it from the comment put
    the date two columns in, above a key at column 0, and PyYAML then read the
    whole block as nothing -- so this fixture is what proves the level was right.
    """
    fm, body = read_document_frontmatter(
        "---\ndate: 2026-06-01\n  # written by hand\ntitle: One\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "One"}
    assert body == "\nbody\n"


def test_reads_a_date_inserted_into_a_document_with_a_byte_order_mark():
    """Parity fixture for TestWithDate_InsertsPastAByteOrderMarkKeepingIt.

    A BOM is an encoding artefact, not content, and leaving it to shadow the whole
    block made a BOM'd document read as having no frontmatter -- which on the
    write side is what let the ingest clock be stamped over an authored date.
    """
    fm, body = read_document_frontmatter(
        "﻿---\ndate: 2026-06-01\ntitle: The Plan\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "The Plan"}
    assert body == "\nbody\n"


def test_a_byte_order_mark_alone_does_not_invent_frontmatter():
    fm, body = read_document_frontmatter("﻿# Just a heading\n\nprose.\n")

    assert fm == {}
    assert body == "# Just a heading\n\nprose.\n"


def test_reads_the_block_stacked_over_frontmatter_the_writer_cannot_edit():
    """Parity fixture for TestWithDate_StacksABlockRatherThanBreakingAnUnreadableOne.

    A flow mapping is frontmatter PyYAML reads and the Go writer cannot edit, so
    an explicit caller date is stacked above it rather than inserted into it.
    Inserting would have made the block invalid YAML and cost the document every
    label it had; stacking keeps all of its bytes and still parses.
    """
    fm, body = read_document_frontmatter(
        "---\ndate: 2026-06-01\n---\n\n---\n{date: 2020-01-01, title: One}\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1)}
    assert "{date: 2020-01-01, title: One}" in body


def test_a_duplicate_date_resolves_to_the_last_occurrence():
    """Why the writer rewrites the *last* date line rather than the first: this is
    the resolution order it has to write for. Pinned because rewriting the first
    one left the document's own date standing and dropped the caller's.
    """
    fm, _body = read_document_frontmatter(
        "---\ndate: 2020-01-01\ntitle: One\ndate: 2026-06-01\n---\n\nbody\n")

    assert fm == {"date": datetime.date(2026, 6, 1), "title": "One"}


def test_a_tab_indented_block_is_unreadable_on_both_sides():
    """YAML forbids tabs as indentation, so this block is not a mapping here. The
    Go writer therefore treats it as frontmatter it cannot read and never inserts
    into it -- an inserted date would land in a block nothing can parse.
    """
    fm, _body = read_document_frontmatter("---\n\tdate: 2026-06-01\n---\n\nbody\n")

    assert fm == {}


def test_a_date_no_calendar_accepts_reads_as_no_frontmatter():
    """RT11. PyYAML's timestamp constructor is not calendar-aware: year zero is
    well-formed YAML that datetime refuses with a bare ValueError, which is not a
    yaml.YAMLError. One such file under raw/ took the whole document catalog down.
    """
    fm, body = read_document_frontmatter("---\ndate: 0000-01-01\n---\n\nbody\n")

    assert fm == {}
    assert body == "\nbody\n"


def test_a_date_that_overflows_the_calendar_reads_as_no_frontmatter(monkeypatch):
    """The other half of RT11's guard, which no pinned PyYAML reproduces: 6.0
    subtracted a timestamp's UTC offset instead of attaching it as tzinfo, so a
    date near datetime.min raised OverflowError -- again not a yaml.YAMLError, and
    again fatal to every document in the catalog. Forced here rather than left to a
    version bump to notice.
    """
    def boom(_text):
        raise OverflowError("date value out of range")

    monkeypatch.setattr(yaml, "safe_load", boom)

    assert read_document_frontmatter("---\ndate: 0001-01-01T00:00:00+02:00\n---\n\nbody\n") == (
        {}, "\nbody\n")


def test_a_date_whose_value_is_a_mapping_reads_as_that_mapping():
    """Why the Go writer must not rewrite such a `date:` line: the value is real
    and lives on the lines below the key. Rewriting the key orphaned them, and this
    document went from a date and a title to no frontmatter at all.
    """
    fm, _body = read_document_frontmatter(
        "---\ndate:\n  start: 2020-01-01\n  end: 2020-06-01\ntitle: The Plan\n---\n\nbody\n")

    assert fm == {
        "date": {"start": datetime.date(2020, 1, 1), "end": datetime.date(2020, 6, 1)},
        "title": "The Plan",
    }


def test_reads_the_block_stacked_over_a_structured_date():
    """Parity fixture for TestWithDate_StacksOverADateWhoseValueIsAMapping."""
    original = "---\ndate:\n  start: 2020-01-01\ntitle: The Plan\n---\n\nbody\n"
    fm, body = read_document_frontmatter(
        "---\ndate: 2026-06-01\n---\n\n" + original)

    assert fm == {"date": datetime.date(2026, 6, 1)}
    assert "start: 2020-01-01" in body
