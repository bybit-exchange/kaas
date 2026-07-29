"""Tests for kb_ai.core.extract._combine_extractions — verifies the function
moved correctly from compile.py and produces expected output."""
from __future__ import annotations

from kb_ai.core.extract import _combine_extractions, ExtractionResult


def test_combine_extractions_importable():
    """_combine_extractions is importable from kb_ai.core.extract."""
    assert callable(_combine_extractions)


def test_combine_extractions_merges_fields():
    """_combine_extractions merges multiple ExtractionResults into one."""
    e1 = ExtractionResult(
        summary="First summary",
        concepts=[{"title": "A"}],
        entities=[{"name": "X"}],
        topics=["topic-a", "topic-b"],
        connections=["conn-1"],
    )
    e2 = ExtractionResult(
        summary="Second summary",
        concepts=[{"title": "B"}],
        entities=[{"name": "Y"}],
        topics=["topic-b", "topic-c"],
        connections=["conn-1", "conn-2"],
    )

    combined, rels = _combine_extractions([("raw/a.md", e1), ("raw/b.md", e2)])

    assert rels == ["raw/a.md", "raw/b.md"]
    assert "First summary" in combined.summary
    assert "Second summary" in combined.summary
    assert len(combined.concepts) == 2
    assert len(combined.entities) == 2
    # Topics are deduplicated
    assert set(combined.topics) == {"topic-a", "topic-b", "topic-c"}
    # Connections are deduplicated
    assert set(combined.connections) == {"conn-1", "conn-2"}


def test_combine_extractions_empty_list():
    """_combine_extractions with empty input returns empty result."""
    combined, rels = _combine_extractions([])
    assert rels == []
    assert combined.summary == ""
    assert combined.concepts == []
    assert combined.topics == []


def test_combine_extractions_skips_empty_summaries():
    """_combine_extractions skips entries with empty summaries."""
    e1 = ExtractionResult(summary="", concepts=[{"title": "A"}])
    e2 = ExtractionResult(summary="Has summary", concepts=[{"title": "B"}])

    combined, rels = _combine_extractions([("raw/a.md", e1), ("raw/b.md", e2)])

    assert combined.summary == "Has summary"
    assert len(combined.concepts) == 2
