"""Tests for derive/_reorganize.py: data structures and build_entity_index."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kb_ai._errors import DeriveError
from kb_ai.core.extract import ExtractionResult
from kb_ai.derive._reorganize import (
    CanonicalMapping,
    EntityIndex,
    EntityOccurrence,
    ReorganizePlan,
    ThematicArticle,
    _is_safe_wiki_path,
    build_entity_index,
)
from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.extraction import StoredExtraction, Provenance
from kb_ai.storage.store import KBStore, _compute_checksum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixture_kb(tmp_path: Path) -> KBStore:
    """A KB with two raw files and corresponding extractions."""
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "raw" / "chapter-01.md").write_text("Chapter 1 content.")
    (kb / "raw" / "chapter-02.md").write_text("Chapter 2 content.")

    store = KBStore(str(kb))

    extraction1 = ExtractionResult(
        summary="Sun Wukong escapes the mountain.",
        entities=[
            {"name": "Sun Wukong", "type": "person", "context": "protagonist"},
            {"name": "Guanyin", "type": "person", "context": "rescuer"},
        ],
        topics=["journey", "escape"],
        concepts=[
            {"title": "Five Elements Mountain", "definition": "The mountain prison."},
            {"title": "The Great Sage", "definition": "Sun Wukong's title."},
        ],
    )
    extraction2 = ExtractionResult(
        summary="The pilgrims meet a demon.",
        entities=[
            {"name": "Sun Wukong", "type": "person", "context": "fighter"},
            {"name": "Zhu Bajie", "type": "person", "context": "companion"},
        ],
        topics=["journey", "battle"],
        concepts=[
            {"title": "72 Transformations", "definition": "Combat technique."},
        ],
    )

    checksum1 = _compute_checksum("Chapter 1 content.")
    checksum2 = _compute_checksum("Chapter 2 content.")
    extraction_layer.persist(store, "raw/chapter-01.md", extraction1,
                             source_checksum=checksum1, extract_model="m")
    extraction_layer.persist(store, "raw/chapter-02.md", extraction2,
                             source_checksum=checksum2, extract_model="m")
    return store


# ---------------------------------------------------------------------------
# Dataclass smoke tests
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_entity_occurrence(self):
        occ = EntityOccurrence(
            source_path="raw/ch1.md", name="Sun Wukong",
            entity_type="person", context="hero",
        )
        assert occ.name == "Sun Wukong"
        assert occ.entity_type == "person"

    def test_entity_index_defaults(self):
        idx = EntityIndex()
        assert idx.entities == {}
        assert idx.topics == {}
        assert idx.concepts == {}
        assert idx.extraction_count == 0

    def test_canonical_mapping_defaults(self):
        cm = CanonicalMapping()
        assert cm.aliases == {}
        assert cm.reverse == {}
        assert cm.filtered_out == []

    def test_thematic_article_round_trip(self):
        art = ThematicArticle(
            path="wiki/concept/overview.md", type="concept",
            title="Overview", description="A description.",
        )
        d = art.to_dict()
        assert d["path"] == "wiki/concept/overview.md"
        art2 = ThematicArticle.from_dict(d)
        assert art2.title == "Overview"
        assert art2.description == "A description."

    def test_thematic_article_from_dict_defaults(self):
        art = ThematicArticle.from_dict({})
        assert art.path == ""
        assert art.type == ""
        assert art.title == ""
        assert art.description == ""

    def test_reorganize_plan_to_dict(self):
        plan = ReorganizePlan(
            topic="Sun Wukong",
            articles=[
                ThematicArticle("wiki/concept/a.md", "concept", "A", "desc"),
            ],
            canonical_mapping=CanonicalMapping(
                aliases={"Sun Wukong": ["Monkey King"]},
                reverse={"Monkey King": "Sun Wukong"},
                filtered_out=["list of things"],
            ),
            entity_index=EntityIndex(extraction_count=5),
        )
        d = plan.to_dict()
        assert d["topic"] == "Sun Wukong"
        assert len(d["articles"]) == 1
        assert d["canonical_entities"] == 1
        assert d["filtered_entities"] == 1
        assert d["extraction_count"] == 5


# ---------------------------------------------------------------------------
# _is_safe_wiki_path tests
# ---------------------------------------------------------------------------

class TestIsSafeWikiPath:
    def test_valid_path(self):
        assert _is_safe_wiki_path("wiki/concept/sun-wukong-overview.md") is True

    def test_valid_nested_path(self):
        assert _is_safe_wiki_path("wiki/reference/combat/battles.md") is True

    def test_rejects_no_wiki_prefix(self):
        assert _is_safe_wiki_path("raw/chapter-01.md") is False

    def test_rejects_traversal_attack(self):
        assert _is_safe_wiki_path("wiki/../raw/x.md") is False

    def test_rejects_double_traversal(self):
        assert _is_safe_wiki_path("wiki/concept/../../raw/x.md") is False

    def test_rejects_too_few_parts(self):
        # Only "wiki/file.md" — no type subdirectory
        assert _is_safe_wiki_path("wiki/file.md") is False

    def test_rejects_no_md_extension(self):
        assert _is_safe_wiki_path("wiki/concept/file.txt") is False

    def test_rejects_empty_string(self):
        assert _is_safe_wiki_path("") is False

    def test_rejects_wiki_only(self):
        assert _is_safe_wiki_path("wiki/") is False

    def test_rejects_absolute_path(self):
        assert _is_safe_wiki_path("/wiki/concept/file.md") is False


# ---------------------------------------------------------------------------
# build_entity_index tests
# ---------------------------------------------------------------------------

class TestBuildEntityIndex:
    def test_happy_path(self, tmp_path: Path):
        store = _fixture_kb(tmp_path)
        index = build_entity_index(store)

        # Extraction count
        assert index.extraction_count == 2

        # Entities
        assert "Sun Wukong" in index.entities
        assert len(index.entities["Sun Wukong"]) == 2  # appears in both chapters
        assert "Guanyin" in index.entities
        assert len(index.entities["Guanyin"]) == 1
        assert "Zhu Bajie" in index.entities
        assert len(index.entities["Zhu Bajie"]) == 1

        # Entity occurrence details
        wukong_occs = index.entities["Sun Wukong"]
        source_paths = {occ.source_path for occ in wukong_occs}
        assert "raw/chapter-01.md" in source_paths
        assert "raw/chapter-02.md" in source_paths
        assert wukong_occs[0].entity_type == "person"

        # Topics
        assert "journey" in index.topics
        assert len(index.topics["journey"]) == 2
        assert "escape" in index.topics
        assert len(index.topics["escape"]) == 1
        assert "battle" in index.topics
        assert len(index.topics["battle"]) == 1

        # Concepts
        assert "Five Elements Mountain" in index.concepts
        assert "The Great Sage" in index.concepts
        assert "72 Transformations" in index.concepts

    def test_defensive_get_for_entity_name(self, tmp_path: Path):
        """Entities missing the 'name' key or with empty name are skipped."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "doc.md").write_text("Document content.")

        store = KBStore(str(kb))
        extraction = ExtractionResult(
            summary="Test",
            entities=[
                {"name": "Valid", "type": "person", "context": "ok"},
                {"type": "person", "context": "missing name key"},  # no name
                {"name": "", "type": "person", "context": "empty name"},  # empty name
                "not-a-dict",  # not a dict at all
            ],
            topics=["test"],
            concepts=[],
        )
        checksum = _compute_checksum("Document content.")
        extraction_layer.persist(store, "raw/doc.md", extraction,
                                 source_checksum=checksum, extract_model="m")

        index = build_entity_index(store)

        assert index.extraction_count == 1
        assert "Valid" in index.entities
        assert len(index.entities) == 1  # only "Valid" survived

    def test_skips_malformed_concepts(self, tmp_path: Path):
        """Concepts missing 'title' or not dicts are skipped."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "doc.md").write_text("Document content.")

        store = KBStore(str(kb))
        extraction = ExtractionResult(
            summary="Test",
            entities=[{"name": "E", "type": "t", "context": "c"}],
            topics=[],
            concepts=[
                {"title": "Good Concept", "definition": "ok"},
                {"definition": "no title"},  # missing title
                {"title": "", "definition": "empty title"},  # empty title
                "not-a-dict",  # not a dict
            ],
        )
        checksum = _compute_checksum("Document content.")
        extraction_layer.persist(store, "raw/doc.md", extraction,
                                 source_checksum=checksum, extract_model="m")

        index = build_entity_index(store)

        assert "Good Concept" in index.concepts
        assert len(index.concepts) == 1

    def test_skips_non_string_topics(self, tmp_path: Path):
        """Non-string or empty topics are skipped."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "doc.md").write_text("Document content.")

        store = KBStore(str(kb))
        extraction = ExtractionResult(
            summary="Test",
            entities=[{"name": "E", "type": "t", "context": "c"}],
            topics=["valid-topic", "", 42],
            concepts=[],
        )
        checksum = _compute_checksum("Document content.")
        extraction_layer.persist(store, "raw/doc.md", extraction,
                                 source_checksum=checksum, extract_model="m")

        index = build_entity_index(store)

        assert "valid-topic" in index.topics
        assert len(index.topics) == 1

    def test_empty_kb_raises_derive_error(self, tmp_path: Path):
        """A KB with no raw files raises DeriveError."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)

        store = KBStore(str(kb))
        with pytest.raises(DeriveError, match="no usable extractions"):
            build_entity_index(store)

    def test_corrupt_extraction_is_skipped_with_warning(self, tmp_path: Path, capsys):
        """A corrupt extraction file is skipped, not crashed on."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "good.md").write_text("Good content.")
        (kb / "raw" / "bad.md").write_text("Bad content.")

        store = KBStore(str(kb))

        # Write a valid extraction for good.md
        good_extraction = ExtractionResult(
            summary="Good",
            entities=[{"name": "Hero", "type": "person", "context": "protagonist"}],
            topics=["adventure"],
            concepts=[],
        )
        good_checksum = _compute_checksum("Good content.")
        extraction_layer.persist(store, "raw/good.md", good_extraction,
                                 source_checksum=good_checksum, extract_model="m")

        # Write a corrupt extraction for bad.md
        bad_path = store.extraction_path("raw/bad.md")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("---\nthis is not valid extraction yaml\n---\n\ngarbage")

        index = build_entity_index(store)

        # Good extraction was processed
        assert index.extraction_count == 1
        assert "Hero" in index.entities

        # Warning was printed for bad.md
        captured = capsys.readouterr()
        assert "bad.md" in captured.err

    def test_missing_extraction_is_silently_skipped(self, tmp_path: Path, capsys):
        """A raw file with no extraction file is silently skipped (no warning)."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "no-extraction.md").write_text("Content without extraction.")

        store = KBStore(str(kb))

        # No extraction file exists for this raw file
        with pytest.raises(DeriveError, match="no usable extractions"):
            build_entity_index(store)

        # No warning printed for missing extractions
        captured = capsys.readouterr()
        assert "no-extraction.md" not in captured.err

    def test_exception_during_load_is_caught(self, tmp_path: Path, capsys):
        """An unexpected exception during extraction_layer.load() is caught."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "exploding.md").write_text("Content.")
        (kb / "raw" / "good.md").write_text("Good content.")

        store = KBStore(str(kb))

        # Write a valid extraction for good.md
        good_extraction = ExtractionResult(
            summary="Good",
            entities=[{"name": "Hero", "type": "person", "context": "ok"}],
            topics=[],
            concepts=[],
        )
        good_checksum = _compute_checksum("Good content.")
        extraction_layer.persist(store, "raw/good.md", good_extraction,
                                 source_checksum=good_checksum, extract_model="m")

        original_load = extraction_layer.load

        def patched_load(s, rel_path):
            if "exploding" in rel_path:
                raise RuntimeError("disk on fire")
            return original_load(s, rel_path)

        with patch.object(extraction_layer, "load", side_effect=patched_load):
            # Wrapping: extraction_layer is a module, patch the function directly
            with patch("kb_ai.derive._reorganize.extraction_layer.load",
                       side_effect=patched_load):
                index = build_entity_index(store)

        assert index.extraction_count == 1
        assert "Hero" in index.entities

        captured = capsys.readouterr()
        assert "exploding" in captured.err
        assert "disk on fire" in captured.err

    def test_all_extractions_corrupt_raises_derive_error(self, tmp_path: Path):
        """If every extraction is unreadable, DeriveError is raised."""
        kb = tmp_path / "kb"
        (kb / "raw").mkdir(parents=True)
        (kb / "raw" / "bad.md").write_text("Bad content.")

        store = KBStore(str(kb))

        # Write a corrupt extraction
        bad_path = store.extraction_path("raw/bad.md")
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("---\ngarbage: true\n---\n\nnot yaml sections")

        with pytest.raises(DeriveError, match="no usable extractions"):
            build_entity_index(store)


# ---------------------------------------------------------------------------
# DeriveReport.reorganize_plan field test
# ---------------------------------------------------------------------------

class TestDeriveReportField:
    def test_reorganize_plan_defaults_to_none(self):
        from kb_ai.derive._types import DeriveReport
        report = DeriveReport(derived_kb="/tmp/kb", slug="test", topic="topic")
        assert report.reorganize_plan is None

    def test_reorganize_plan_can_be_set(self):
        from kb_ai.derive._types import DeriveReport
        plan_dict = {"topic": "Sun Wukong", "articles": [], "extraction_count": 5}
        report = DeriveReport(derived_kb="/tmp/kb", slug="test", topic="topic",
                              reorganize_plan=plan_dict)
        assert report.reorganize_plan == plan_dict
