"""Tests for _frontmatter.py -- splitting a YAML frontmatter block from a body."""
from __future__ import annotations

from kb_ai._frontmatter import split_frontmatter


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
