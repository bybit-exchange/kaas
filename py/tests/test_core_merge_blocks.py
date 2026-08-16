"""Per-source blocks in the write payload (supersession spec WP1-WP5, WP7, WP8).

The write phase used to receive one flattened extraction and one source string:
`_combine_extractions` concatenated every source's summary and extended every
list, so a claim could not be attributed to the document that made it, and no
date reached the writer on any route. These tests pin the replacement -- one
labelled block per source, ordered oldest to newest, dated from the document's
own frontmatter.

Budget allocation is here too (BG1-BG4 with VF3): newest dated block first and
undated blocks last, whole blocks dropped from the bottom of that order rather
than left broken, each dropped source named, and a budget too small for even the
first block spent on truncating that one instead of emitting nothing.
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


# ── budget allocation (BG1-BG4, VF3) ────────────────────────────────

def test_the_newest_block_survives_a_budget_that_fits_only_one():
    """BG1. Allocating in render order spends the budget on the oldest source and
    cuts the newest, which is backwards: supersession is a question about what
    the latest document says. Step 2's even split kept both and cut both."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 4000)),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 4000)),
    )

    text = mg._render_blocks(blocks, 4200)

    assert "- Source: raw/new.md" in text
    assert "n" * 4000 in text, "the surviving block is whole"
    assert "raw/old.md" not in text
    assert len(text) <= 4200


def test_an_undated_block_gives_way_before_any_dated_one():
    """BG1 over WP5's order, not against it. Undated blocks sort last for
    determinism and WP6 tells the model their position carries no ordering claim,
    so taking the render order and reversing it would put them first in the queue
    and drop the one source known to be newest -- BG1 inverted on a guess. Checked
    against a dated block newer *and* older than the undated one, because the
    undated one outranks neither."""
    for day in (date(2021, 1, 1), date(2019, 1, 1)):
        blocks = _blocks(
            ("raw/dated.md", day, _extraction(summary="d" * 3000)),
            ("raw/unknown.md", None, _extraction(summary="u" * 3000)),
        )
        budget = mg._estimate_block_size(blocks[0]) + 100

        text = mg._render_blocks(blocks, budget)

        assert "raw/dated.md" in text, f"dated {day} lost to an undated block"
        assert "raw/unknown.md" not in text


def test_sources_dated_the_same_day_break_to_path_order_for_stability():
    """WP9 rewrote what this pins. Two sources sharing a day are peers: the queue
    serves one of them first because a drop has to be reproducible, not because it
    is the newer, and nothing downstream may read the priority as recency -- which
    is why _SOURCE_ORDER withdraws the ordering claim for exactly this pair. It
    decides real drops either way: 156 of the reference KB's 397 multi-source
    articles carry a same-day pair, 384 pairs, counting one block per checksum as
    WP7 requires.

    Stability is therefore the property under test, and it is asserted the only way
    that can distinguish it from a caller-inherited order: both permutations of the
    same pair, which must queue identically and drop the same source. The earlier
    version handed over one permutation and asserted the survivor, which a queue
    that simply kept its input order would also have passed."""
    for first, second in (("raw/b.md", "raw/a.md"), ("raw/a.md", "raw/b.md")):
        blocks = _blocks(
            (first, date(2021, 1, 1), _extraction(summary="x" * 2000)),
            (second, date(2021, 1, 1), _extraction(summary="y" * 2000)),
        )
        budget = mg._estimate_block_size(blocks[0]) + 100

        queued = [blocks[i].source_path for i in mg._budget_priority(blocks)]
        text = mg._render_blocks(blocks, budget)

        assert queued == ["raw/a.md", "raw/b.md"], \
            f"the queue inherited the order it was handed ({first} first)"
        assert "raw/a.md" in text and "raw/b.md" not in text


def test_a_block_that_is_nothing_but_its_header_still_fits_whole():
    """The boundary the fits-whole branch creates: an extraction with every
    priority field empty estimates at exactly its header, and a budget of exactly
    that much used to be refused -- so a block measured as fitting whole came back
    without its date line, silently, with the rest of the budget unspent. Losing
    the date is not cosmetic: WP6 reads an absent date as "makes no ordering
    claim", which is the opposite of what this document says about itself."""
    blocks = _blocks(
        ("raw/old.md", date(2019, 2, 1), _extraction()),
        ("raw/new.md", date(2021, 11, 1), _extraction()),
    )
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 1

    text = mg._render_blocks(blocks, needed)

    assert text.count("- Date:") == 2
    assert len(text) == needed


def test_undated_blocks_claim_the_budget_in_path_order():
    """The tiebreaker among sources that make no recency claim is the one WP5
    already imposed, so two runs over one KB drop the same block. Handed over
    out of path order, so the sort is doing the work and not the caller."""
    blocks = _blocks(
        ("raw/b.md", None, _extraction(summary="b" * 2000)),
        ("raw/a.md", None, _extraction(summary="a" * 2000)),
    )
    budget = mg._estimate_block_size(blocks[0]) + 100

    text = mg._render_blocks(blocks, budget)

    assert "raw/a.md" in text and "raw/b.md" not in text


def test_a_block_that_does_not_fit_is_dropped_whole():
    """BG2. A block cut to its header and a halved enumeration is worse than no
    block: the writer cannot tell a thin source from a truncated one, and #41's
    partial-set failure is exactly what a broken block hands it."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 3000)),
        ("raw/mid.md", date(2021, 1, 1), _extraction(summary="m" * 1000)),
        ("raw/new.md", date(2022, 1, 1), _extraction(summary="n" * 1000)),
    )
    ample = 100_000
    keepers = [mg._fit_block_to_budget(b, ample) for b in blocks[1:]]

    text = mg._render_blocks(blocks, 2500)

    assert "raw/old.md" not in text
    assert text == "\n".join(keepers), "survivors are whole, in oldest-to-newest order"


def test_survivors_are_always_the_newest_run_never_a_hole_in_the_middle():
    """BG2 drops from the bottom of the priority order and stops there: dropping
    whichever block happens not to fit and carrying on would keep an old source
    over a newer one, so the payload would read as a set of sources with a gap the
    writer cannot see. Every block here is dated, so the priority order is the
    render order reversed and the survivors are a suffix of the newest end.

    The middle block is the large one on purpose: with the oldest block largest,
    skipping past a block that does not fit would leave nothing behind it small
    enough to keep, and the two policies would be indistinguishable."""
    sizes = {0: 200, 1: 2000, 2: 300}
    blocks = _blocks(*[(f"raw/{i}.md", date(2020, i + 1, 1),
                        _extraction(summary=str(i) * sizes[i])) for i in range(3)])

    for budget in range(0, 3000, 97):
        text = mg._render_blocks(blocks, budget)
        present = [f"raw/{i}.md" in text for i in range(3)]
        # A suffix of the newest end: once a block is present, every newer one is.
        assert present == sorted(present), f"budget {budget} kept {present}"


def test_the_dropped_source_is_named_on_stderr(capsys):
    """BG3. The cut notice already names its source; a drop emitted nothing at
    all, so the one source that contributed no content to the article was the one
    the operator had no way to find."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 4000)),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 4000)),
    )

    mg._render_blocks(blocks, 4200)

    err = capsys.readouterr().err
    assert "raw/old.md" in err
    assert "raw/new.md" not in err, "the block that was kept whole was not cut"


def test_a_budget_too_small_for_the_newest_block_truncates_it(capsys):
    """BG4. Dropping every block because none fits whole would send the writer an
    article and no new information at all, and it would do it silently -- the
    merge would look successful and change nothing."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 4000)),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 4000)),
    )

    text = mg._render_blocks(blocks, 600)

    assert "- Source: raw/new.md" in text
    assert "n" * 500 in text, "truncated by field priority, not emptied"
    assert "raw/old.md" not in text
    assert len(text) <= 600
    err = capsys.readouterr().err
    assert "raw/new.md" in err, "BG3: the cut source is named"
    assert "raw/old.md" in err, "BG3: so is the dropped one"


def test_every_block_is_rendered_whole_when_the_budget_can_hold_them_all():
    """An adequate budget cuts nothing, however unevenly the blocks are sized:
    each one is measured against everything left rather than a share of it, so a
    block twenty times its neighbour still comes out whole. The flattened payload
    this replaces had one budget for the whole bag and would not have cut
    anything here either.

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


def test_one_char_short_of_whole_drops_the_oldest_block():
    """The boundary just below "everything fits": both blocks would fit but the
    separator between them would not. One char is enough to cost the oldest source
    its whole block -- the alternative is two blocks cut by a character each, which
    is a broken block under BG2 for the sake of one character."""
    blocks = _blocks(
        ("raw/a.md", date(2020, 1, 1), _extraction(summary="a" * 900)),
        ("raw/b.md", date(2021, 1, 1), _extraction(summary="b" * 300)),
    )
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 1

    text = mg._render_blocks(blocks, needed - 1)

    assert text == mg._fit_block_to_budget(blocks[1], needed - 1)
    assert len(text) <= needed - 1


def test_the_block_after_the_newest_gets_everything_the_newest_left():
    """Not a share of it. The newest block is allocated first and whole, and what
    it leaves is the next block's entire budget -- so a block larger than half of
    what remains still comes out intact, which step 2's even split could not do."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o" * 1400)),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n" * 1000)),
    )
    sizes = [mg._estimate_block_size(b) for b in blocks]
    budget = sum(sizes) + 1

    assert sizes[0] > budget // 2, "the case only discriminates if a split would cut"
    assert mg._render_blocks(blocks, budget) == "\n".join(
        mg._fit_block_to_budget(b, 100_000) for b in blocks)


def test_rendering_never_exceeds_the_budget_it_was_given():
    """Including the separators between blocks, which the caller's budget has to
    cover: three blocks that each fit exactly would still overrun by two."""
    blocks = _blocks(*[(f"raw/{i}.md", date(2020, 1, i + 1),
                        _extraction(summary="x" * 200)) for i in range(3)])

    for budget in (0, 1, 60, 200, 613, 1000):
        assert len(mg._render_blocks(blocks, budget)) <= budget


def test_three_blocks_one_char_short_still_respect_the_budget():
    """Every separator has to come out of the budget as it is spent, not just the
    first: with three blocks and one char less than they all need, charging two
    separators but deducting one overruns by exactly that char. The sweep above
    lands either side of this boundary without hitting it."""
    blocks = _blocks(*[(f"raw/{i}.md", date(2020, i + 1, 1),
                        _extraction(summary="x" * 200)) for i in range(3)])
    needed = sum(mg._estimate_block_size(b) for b in blocks) + 2

    text = mg._render_blocks(blocks, needed - 1)

    assert len(text) <= needed - 1
    assert "raw/0.md" not in text, "the oldest block is what gives way"


def test_a_budget_of_nothing_still_names_every_source(capsys):
    """No production caller floors below 200 chars, so this is the empty-output
    branch pinned directly: when not one block emitted a character, every source
    is dropped and every source is named. A payload that silently contained no
    new information is the failure the notice exists to make visible."""
    blocks = _blocks(
        ("raw/old.md", date(2020, 1, 1), _extraction(summary="o")),
        ("raw/new.md", date(2021, 1, 1), _extraction(summary="n")),
    )

    assert mg._render_blocks(blocks, 0) == ""

    err = capsys.readouterr().err
    assert "raw/old.md" in err and "raw/new.md" in err
    assert err.index("raw/old.md") < err.index("raw/new.md"), \
        "the notices read in the order the payload would have"


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
