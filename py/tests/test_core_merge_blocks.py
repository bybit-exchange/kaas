"""Per-source blocks in the write payload (supersession spec WP1-WP5, WP7, WP8).

The write phase used to receive one flattened extraction and one source string:
`_combine_extractions` concatenated every source's summary and extended every
list, so a claim could not be attributed to the document that made it, and no
date reached the writer on any route. These tests pin the replacement -- one
labelled block per source, ordered oldest to newest, dated from the document's
own frontmatter.

Budget allocation across blocks is deliberately shallow here: step 2 splits the
budget evenly with the unused share carried forward, and BG1-BG4 (newest-first
priority, whole-block drops, a notice naming the dropped source) land in step 3
with VF3.
"""
from __future__ import annotations

from datetime import date

from kb_ai.core import merge as mg
from kb_ai.core.extract import ExtractionResult


def _extraction(**kwargs) -> ExtractionResult:
    return ExtractionResult(**kwargs)


def _reader(docs: dict[str, str]):
    """A read_raw stand-in over an in-memory {rel_path: content} map."""
    def read_raw(rel_path: str) -> str:
        return docs[rel_path]
    return read_raw


def _dated(day: str) -> str:
    return f"---\ntitle: T\ndate: {day}\n---\nbody\n"


def _build(docs: dict[str, str], items) -> list[mg.SourceBlock]:
    return mg.build_source_blocks(_reader(docs), items)


def _one(content: str, *, rel: str = "raw/a.md", checksum: str = "c1") -> mg.SourceBlock:
    return _build({rel: content}, [(rel, checksum, _extraction())])[0]


# ── the date a block carries (WP2, WP8) ─────────────────────────────

def test_block_carries_the_documents_own_date():
    assert _one(_dated("2020-01-01")).date == date(2020, 1, 1)


def test_block_is_undated_when_the_document_has_no_frontmatter():
    assert _one("just a body, no frontmatter\n").date is None


def test_block_is_undated_when_the_date_key_is_declared_but_empty():
    assert _one("---\ntitle: T\ndate:\n---\nbody\n").date is None


def test_a_timestamp_is_narrowed_to_the_day_it_names():
    """PyYAML resolves a stamp to datetime, and a datetime cannot be compared
    with a date -- mixing the two in one sort key raises TypeError. Narrowing at
    build time is what keeps a corpus holding both kinds sortable at all."""
    assert _one(_dated("2020-01-01T13:45:00Z")).date == date(2020, 1, 1)


def test_a_quoted_date_is_parsed_here(monkeypatch):
    """WP8: the submit route cannot tell a date from a string that looks like
    one, so it preserves what it was given. Resolving it is this layer's job."""
    assert _one('---\ndate: "2020-01-01"\n---\nbody\n').date == date(2020, 1, 1)


def test_a_date_string_nobody_can_parse_leaves_the_block_undated():
    assert _one("---\ndate: last Tuesday\n---\nbody\n").date is None


def test_a_bare_year_leaves_the_block_undated():
    """`date: 2020` is an int to YAML. Reading it as 2020-01-01 would invent a
    day the document never claimed, and ordering is the whole point here."""
    assert _one("---\ndate: 2020\n---\nbody\n").date is None


def test_a_date_no_calendar_accepts_leaves_the_block_undated():
    """The shared reader hands back {} rather than raising (RT11), so the block
    is undated rather than failing the write."""
    assert _one("---\ndate: 0000-01-01\n---\nbody\n").date is None


def test_a_raw_file_that_cannot_be_read_leaves_the_block_undated():
    """The date is a nicety; the article is not. A document whose raw file went
    away between the scan and the write still gets composed, undated (S5).

    Both routes normally have the file: the submit handler writes raw/ before the
    worker composes from it, which is what step 1 was for. So this is the
    exception, and it degrades rather than failing the write."""
    def exploding_read(rel_path: str) -> str:
        raise FileNotFoundError(rel_path)

    blocks = mg.build_source_blocks(
        exploding_read, [("raw/gone.md", "c1", _extraction(summary="s"))])

    assert [(b.source_path, b.date) for b in blocks] == [("raw/gone.md", None)]
    assert blocks[0].extraction.summary == "s"


def test_a_provenance_comment_does_not_hide_the_date():
    """distill prepends `<!-- source: ... -->` to every file it ingests, which
    pushed each document's frontmatter off line 0 -- 0 of 108 documents on the
    reference KB carried a date until the shared reader skipped it."""
    doc = "<!-- source: /tmp/x.md -->\n\n" + _dated("2020-01-01")

    assert _one(doc).date == date(2020, 1, 1)


# ── ordering (WP5, VF2) ─────────────────────────────────────────────

def test_blocks_render_oldest_to_newest():
    docs = {"raw/a.md": _dated("2021-06-01"), "raw/b.md": _dated("2020-01-01")}
    blocks = _build(docs, [("raw/a.md", "c1", _extraction()),
                           ("raw/b.md", "c2", _extraction())])

    assert [b.source_path for b in blocks] == ["raw/b.md", "raw/a.md"]


def test_undated_blocks_come_last_in_path_order():
    """Deterministic across runs: compile writes article groups on 16 workers and
    raw-scan order is not stable across ingests."""
    docs = {"raw/b.md": "no frontmatter\n", "raw/a.md": "no frontmatter\n"}
    blocks = _build(docs, [("raw/b.md", "c1", _extraction()),
                           ("raw/a.md", "c2", _extraction())])

    assert [b.source_path for b in blocks] == ["raw/a.md", "raw/b.md"]


def test_dated_blocks_precede_undated_ones():
    docs = {"raw/a.md": "no frontmatter\n",
            "raw/b.md": _dated("2020-01-01"),
            "raw/c.md": _dated("2019-01-01")}
    blocks = _build(docs, [("raw/a.md", "c1", _extraction()),
                           ("raw/b.md", "c2", _extraction()),
                           ("raw/c.md", "c3", _extraction())])

    assert [b.source_path for b in blocks] == ["raw/c.md", "raw/b.md", "raw/a.md"]


def test_equal_dates_fall_back_to_path_order():
    docs = {"raw/z.md": _dated("2020-01-01"), "raw/a.md": _dated("2020-01-01")}
    blocks = _build(docs, [("raw/z.md", "c1", _extraction()),
                           ("raw/a.md", "c2", _extraction())])

    assert [b.source_path for b in blocks] == ["raw/a.md", "raw/z.md"]


def test_a_date_and_a_timestamp_sort_together():
    """The mixed corpus the narrowing exists for: one document dates itself with
    a day, the next with a stamp. Unnarrowed, this sort raises TypeError."""
    docs = {"raw/a.md": _dated("2021-01-01T09:00:00"), "raw/b.md": _dated("2020-01-01")}
    blocks = _build(docs, [("raw/a.md", "c1", _extraction()),
                           ("raw/b.md", "c2", _extraction())])

    assert [b.source_path for b in blocks] == ["raw/b.md", "raw/a.md"]


# ── identical-checksum duplicates (WP7) ─────────────────────────────

def test_identical_checksums_contribute_one_block():
    """55 lineage groups in the corpus are the same bytes ingested twice. Two
    blocks of one document would double its claims' weight in the payload."""
    doc = _dated("2020-01-01")
    docs = {"raw/a.md": doc, "raw/copy-of-a.md": doc}
    blocks = _build(docs, [("raw/a.md", "same", _extraction(summary="s")),
                           ("raw/copy-of-a.md", "same", _extraction(summary="s"))])

    assert [b.source_path for b in blocks] == ["raw/a.md"]


def test_the_surviving_duplicate_is_the_first_in_path_order():
    """Whichever order the scan hands them over, the payload names the same
    document -- otherwise two runs over one KB disagree about provenance."""
    doc = _dated("2020-01-01")
    docs = {"raw/a.md": doc, "raw/b.md": doc}
    items = [("raw/b.md", "same", _extraction()), ("raw/a.md", "same", _extraction())]

    assert [b.source_path for b in _build(docs, items)] == ["raw/a.md"]


def test_the_same_document_at_the_same_path_twice_contributes_one_block():
    """Two create ops can name one article from one document."""
    docs = {"raw/a.md": _dated("2020-01-01")}
    items = [("raw/a.md", "same", _extraction()), ("raw/a.md", "same", _extraction())]

    assert len(_build(docs, items)) == 1


def test_different_content_at_two_paths_keeps_both_blocks():
    docs = {"raw/a.md": _dated("2020-01-01"), "raw/b.md": _dated("2020-06-01")}
    blocks = _build(docs, [("raw/a.md", "c1", _extraction()),
                           ("raw/b.md", "c2", _extraction())])

    assert len(blocks) == 2


# ── rendering (WP1, WP3) ────────────────────────────────────────────

def _blocks(*specs) -> list[mg.SourceBlock]:
    """Build blocks directly, bypassing the reader: (path, date, extraction)."""
    return [mg.SourceBlock(source_path=p, date=d, extraction=e) for p, d, e in specs]


def test_each_block_names_its_own_source_and_date():
    text = mg._render_blocks(_blocks(
        ("raw/a.md", date(2020, 1, 1), _extraction(summary="older")),
        ("raw/b.md", date(2021, 1, 1), _extraction(summary="newer")),
    ), 100_000)

    assert text.index("- Source: raw/a.md") < text.index("- Source: raw/b.md")
    assert "- Date: 2020-01-01\n- Summary: older" in text
    assert "- Date: 2021-01-01\n- Summary: newer" in text


def test_an_undated_block_emits_no_date_line():
    """Q2: no date line, and the prompt says ordering is unknown (WP6). Never a
    guess -- file mtime is rewritten by derive's copy of raw/."""
    text = mg._render_blocks(_blocks(("raw/a.md", None, _extraction(summary="s"))), 100_000)

    assert "- Date:" not in text
    assert "- Source: raw/a.md\n- Summary: s" in text


def test_blocks_are_separated_by_a_blank_line():
    text = mg._render_blocks(_blocks(
        ("raw/a.md", None, _extraction(summary="one")),
        ("raw/b.md", None, _extraction(summary="two")),
    ), 100_000)

    assert "- Summary: one\n\n- Source: raw/b.md" in text


def test_every_sources_enumerations_reach_the_payload():
    """The guarantee `_combine_extractions` used to carry (issue #41): an
    enumeration is the one field truncation cannot degrade gracefully, and a
    per-source payload must not drop one of two sources' members."""
    text = mg._render_blocks(_blocks(
        ("raw/a.md", date(2020, 1, 1),
         _extraction(enumerations=[{"name": "A", "items": ["a1", "a2"]}])),
        ("raw/b.md", date(2021, 1, 1),
         _extraction(enumerations=[{"name": "B", "items": ["b1"]}])),
    ), 100_000)

    assert '"a1"' in text and '"a2"' in text and '"b1"' in text


def test_estimate_matches_the_text_produced_with_an_ample_budget():
    """The invariant the estimator exists to satisfy, extended to the date line:
    with a budget nothing can exceed, the estimate equals the emitted length --
    otherwise the truncation notice fires on complete output. Both a dated and an
    undated block, because the date line is what is new here."""
    for day in (date(2020, 1, 1), None):
        block = mg.SourceBlock(
            source_path="raw/a.md", date=day,
            extraction=_extraction(summary="s", topics=["a", "b"],
                                   concepts=[{"title": "c"}]))

        assert mg._estimate_block_size(block) == len(
            mg._fit_block_to_budget(block, 1_000_000))


def test_a_single_block_still_gets_the_whole_budget():
    """N=1 must be what it was before blocks existed, plus the date line: every
    single-source call site (compile.py:492, :495, :558) goes through here."""
    block = mg.SourceBlock(source_path="raw/a.md", date=None,
                           extraction=_extraction(summary="s" * 500))

    assert mg._render_blocks([block], 100_000) == mg._fit_block_to_budget(block, 100_000)


def test_the_budget_is_shared_so_no_block_is_starved():
    """Step 2's interim allocation. Under a budget that fits neither block whole,
    both still appear -- the newest is not squeezed out by the oldest getting
    first call on the whole budget. BG1 replaces this with newest-first priority
    and whole-block drops in step 3."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 4000)),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 4000)),
    )

    text = mg._render_blocks(blocks, 2000)

    assert "- Source: raw/old.md" in text
    assert "- Source: raw/new.md" in text
    assert len(text) <= 2000


def test_every_block_is_rendered_whole_when_the_budget_can_hold_them_all():
    """An even split of an *adequate* budget is loss for nothing: a block larger
    than its share is truncated while the remainder goes unspent, because the
    carry only flows forward. The flattened payload it replaces had one budget
    for the whole bag and would not have cut anything here.

    Measured on the shape that makes it worst: the first field to go is
    enumerations, the one field truncation cannot degrade gracefully (issue #41).
    """
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1),
         _extraction(summary="s" * 20_000,
                     enumerations=[{"name": "middleware",
                                    "items": [f"m{i}" for i in range(11)]}])),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 1_000)),
    )
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 1

    text = mg._render_blocks(blocks, needed + 2_000)

    assert len(text) == needed
    assert '"m10"' in text, "no enumeration may be cut while the budget has room"
    assert "s" * 20_000 in text and "n" * 1_000 in text


def test_a_budget_exactly_large_enough_still_renders_everything():
    """The boundary: separators included, nothing to spare."""
    blocks = _blocks(
        ("raw/a.md", date(2020, 1, 1), _extraction(summary="a" * 900)),
        ("raw/b.md", date(2021, 1, 1), _extraction(summary="b" * 300)),
    )
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 1

    assert len(mg._render_blocks(blocks, needed)) == needed


def test_one_char_short_of_whole_still_respects_the_budget():
    """The boundary just below "everything fits": the blocks would fit but the
    separators between them would not, so the allocation has to share instead.
    The budget holds either way -- the separators are deducted before any share is
    computed -- and this pins that the switch does not lose the invariant."""
    blocks = _blocks(
        ("raw/a.md", date(2020, 1, 1), _extraction(summary="a" * 900)),
        ("raw/b.md", date(2021, 1, 1), _extraction(summary="b" * 300)),
    )
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 1

    assert len(mg._render_blocks(blocks, needed - 1)) <= needed - 1


def test_an_unused_share_carries_forward():
    """A block that needs less than its share does not waste the remainder."""
    blocks = _blocks(
        ("raw/small.md", date(2020, 1, 1), _extraction(summary="s")),
        ("raw/big.md", date(2021, 1, 1), _extraction(summary="b" * 3000)),
    )

    text = mg._render_blocks(blocks, 2000)
    big_block = text.split("\n\n")[1]

    assert len(big_block) > 1000
    assert len(text) <= 2000


def test_rendering_never_exceeds_the_budget_it_was_given():
    """Including the separators between blocks, which the caller's budget has to
    cover: three blocks that each fit exactly would still overrun by two."""
    blocks = _blocks(*[(f"raw/{i}.md", date(2020, 1, i + 1),
                        _extraction(summary="x" * 200)) for i in range(3)])

    for budget in (0, 1, 60, 200, 613, 1000):
        assert len(mg._render_blocks(blocks, budget)) <= budget


def test_rendering_no_blocks_at_all_is_empty():
    """No caller sends an empty list -- both routes group at least one op per
    article -- but the loop must not depend on that to stay inside the budget."""
    assert mg._render_blocks([], 500) == ""


def test_a_budget_too_small_for_the_header_never_emits_half_a_date():
    """A truncated source path is cosmetic; half a date is a false ordering
    signal, and dropping the trailing newline runs the next block's header onto
    it. Under that budget the date line goes entirely."""
    block = mg.SourceBlock(source_path="raw/a.md", date=date(2020, 1, 1),
                           extraction=_extraction(summary="s"))
    source_line = "- Source: raw/a.md\n"

    for budget in range(len(source_line), len(source_line) + len("- Date: 2020-01-01\n")):
        out = mg._fit_block_to_budget(block, budget)
        assert out == source_line, f"budget {budget} rendered {out!r}"

    assert mg._fit_block_to_budget(block, len(source_line) - 1) == source_line[:-1]
