"""How far the wiki is behind the prompts that produced it.

The wiki lags under two independent prompt sets: the extraction prompts, whose
version the extraction layer records per document, and the write-phase prompts,
which had no version at all -- editing merge-rewrite.md or merge-diff.md
invalidated nothing and no report named the articles it left behind.

Both are reported and neither gates. Re-composing an article layers new content
on top of the old rather than replacing it, so a prompt edit that fed the
composition gate would inflate every article and pay the full write phase to do
it.
"""
from __future__ import annotations

from kb_ai.storage import lag


def _state(**entries) -> dict:
    return dict(entries)


def _compiled(extract: str = "e1", write: str = "w1") -> dict:
    entry = {"checksum": "c", "compiled_at": "2026-08-08T10:00:00"}
    if extract is not None:
        entry["prompt_version"] = extract
    if write is not None:
        entry["write_prompt_version"] = write
    return entry


CURRENT = {"extract_prompt_version": "e1", "write_prompt_version": "w1"}


def test_everything_current_is_not_behind():
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled()}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == []
    assert report.behind_write == []
    assert report.extract_first_run is False
    assert report.write_first_run is False


def test_an_older_extract_prompt_is_behind_on_extraction_only():
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(extract="e0")}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == ["raw/a.md"]
    assert report.behind_write == []


def test_an_older_write_prompt_is_behind_on_composition_only():
    """The gap this exists for: the extraction is current and the article is not."""
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(write="w0")}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_write == ["raw/a.md"]
    assert report.behind_extract == []


def test_a_document_can_be_behind_on_both():
    report = lag.wiki_lag(
        _state(**{"raw/a.md": _compiled(extract="e0", write="w0")}),
        present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == ["raw/a.md"]
    assert report.behind_write == ["raw/a.md"]


def test_a_document_no_longer_under_raw_is_not_counted():
    """State entries are never garbage-collected, and a document that is gone
    cannot be behind anything. Counting it inflates the number an operator reads
    to decide whether a recompile is worth paying for."""
    report = lag.wiki_lag(
        _state(**{"raw/a.md": _compiled(extract="e0"),
                  "raw/deleted.md": _compiled(extract="e0")}),
        present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == ["raw/a.md"]


def test_an_entry_that_was_never_composed_is_not_counted():
    """No compiled_at means no article was written from it, so there is nothing
    for the wiki to be behind on -- the composition gate already has it queued."""
    report = lag.wiki_lag(
        _state(**{"raw/a.md": {"checksum": "c", "completed_ops": ["wiki/a.md"],
                               "prompt_version": "e0"}}),
        present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == []
    assert report.behind_write == []


def test_a_missing_extract_version_reads_as_first_run():
    """No pre-existing entry records a prompt_version, so the first run after the
    extraction layer landed reports every article -- true, but it reads as a
    defect without the reason."""
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(extract=None)}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == ["raw/a.md"]
    assert report.extract_first_run is True


def test_a_missing_write_version_reads_as_first_run_too():
    """Same shape one gate over: no entry written before write_prompt_version
    existed carries one."""
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(write=None)}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_write == ["raw/a.md"]
    assert report.write_first_run is True


def test_results_are_sorted_so_two_runs_agree():
    report = lag.wiki_lag(
        _state(**{"raw/c.md": _compiled(write="w0"),
                  "raw/a.md": _compiled(write="w0"),
                  "raw/b.md": _compiled(write="w0")}),
        present={"raw/a.md", "raw/b.md", "raw/c.md"}, **CURRENT)

    assert report.behind_write == ["raw/a.md", "raw/b.md", "raw/c.md"]


def test_an_unknown_write_version_reports_nothing_rather_than_everything():
    """When the write prompts cannot be read there is nothing to compare against,
    and reporting every article as behind would be a guess dressed as a count."""
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(write="w0")}),
                          present={"raw/a.md"},
                          extract_prompt_version="e1", write_prompt_version="")

    assert report.behind_write == []
    assert report.write_version_known is False


def test_one_gates_first_run_does_not_excuse_the_other_gates_real_lag():
    """One flag for both gates captioned a real extract lag as expected noise.

    Every KB compiled between the extraction layer landing and write_prompt_version
    landing is in exactly this state -- prompt_version recorded, write_prompt_version
    absent -- so the first genuine extract-prompt edit afterwards would be reported
    as "expected on the first run" and ignored.
    """
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(extract="e0",
                                                          write=None)}),
                          present={"raw/a.md"}, **CURRENT)

    assert report.behind_extract == ["raw/a.md"]
    assert report.extract_first_run is False, "this entry records a prompt_version"
    assert report.behind_write == ["raw/a.md"]
    assert report.write_first_run is True


def test_an_unknown_extract_version_reports_nothing_rather_than_everything():
    """Symmetric with the write gate: no version to compare against means we
    cannot tell, and every document is not the honest answer."""
    report = lag.wiki_lag(_state(**{"raw/a.md": _compiled(extract="e0")}),
                          present={"raw/a.md"},
                          extract_prompt_version="", write_prompt_version="w1")

    assert report.behind_extract == []
    assert report.extract_version_known is False
    assert report.write_version_known is True


def test_the_summary_names_both_gates():
    report = lag.wiki_lag(
        _state(**{"raw/a.md": _compiled(extract="e0"),
                  "raw/b.md": _compiled(write="w0")}),
        present={"raw/a.md", "raw/b.md"}, **CURRENT)

    summary = report.summary()
    assert "1 behind the extract prompt" in summary
    assert "1 behind the write prompt" in summary
