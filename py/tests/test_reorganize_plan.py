"""Tests for plan_aggregation() and reorganize() in derive/_reorganize.py.

Covers prompt rendering, LLM response parsing, validation (paths, types,
titles), article count clamping, canonical mapping application, and the
full reorganize() orchestrator chain.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from kb_ai._errors import DeriveError
from kb_ai.core.extract import ExtractionResult
from kb_ai.derive._reorganize import (
    CanonicalMapping,
    EntityIndex,
    EntityOccurrence,
    ReorganizePlan,
    ThematicArticle,
    _apply_canonical_mapping,
    _build_frequency_table,
    _MAX_ARTICLES,
    _MIN_ARTICLES,
    plan_aggregation,
    reorganize,
)
from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.extraction import StoredExtraction, Provenance
from kb_ai.storage.store import KBStore, _compute_checksum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_index(
    entities: dict[str, list[EntityOccurrence]] | None = None,
    topics: dict[str, list[str]] | None = None,
    concepts: dict[str, list[str]] | None = None,
    extraction_count: int = 10,
) -> EntityIndex:
    """Build an EntityIndex from simple data for testing."""
    return EntityIndex(
        entities=entities or {},
        topics=topics or {},
        concepts=concepts or {},
        extraction_count=extraction_count,
    )


def _valid_articles_response(n: int = 5, category: str = "concept") -> dict:
    """Build a valid LLM response with *n* planned articles."""
    articles = []
    for i in range(n):
        articles.append({
            "path": f"wiki/{category}/article-{i}.md",
            "type": category,
            "title": f"Article {i}",
            "description": f"Description for article {i}.",
        })
    return {"articles": articles}


CATEGORIES = ["concept", "reference", "how-to"]


# ---------------------------------------------------------------------------
# _build_frequency_table tests
# ---------------------------------------------------------------------------

class TestBuildFrequencyTable:
    def test_returns_top_n(self):
        items = {
            "a": [1, 2, 3],
            "b": [1],
            "c": [1, 2],
        }
        result = _build_frequency_table(items, 2)
        assert len(result) == 2
        assert result[0] == ("a", 3)
        assert result[1] == ("c", 2)

    def test_returns_all_when_fewer_than_n(self):
        items = {"a": [1]}
        result = _build_frequency_table(items, 50)
        assert len(result) == 1
        assert result[0] == ("a", 1)

    def test_empty_items(self):
        result = _build_frequency_table({}, 10)
        assert result == []


# ---------------------------------------------------------------------------
# _apply_canonical_mapping tests
# ---------------------------------------------------------------------------

class TestApplyCanonicalMapping:
    def test_merges_alias_under_canonical(self):
        occ_wukong = EntityOccurrence("raw/ch1.md", "Sun Wukong", "person", "ctx")
        occ_monkey = EntityOccurrence("raw/ch2.md", "Monkey King", "person", "ctx")
        raw_index = _make_index(
            entities={
                "Sun Wukong": [occ_wukong],
                "Monkey King": [occ_monkey],
            },
        )
        mapping = CanonicalMapping(
            aliases={"Sun Wukong": ["Monkey King"]},
            reverse={"Monkey King": "Sun Wukong"},
        )
        resolved = _apply_canonical_mapping(raw_index, mapping)
        assert "Sun Wukong" in resolved.entities
        assert len(resolved.entities["Sun Wukong"]) == 2
        assert "Monkey King" not in resolved.entities

    def test_preserves_unmapped_names(self):
        occ = EntityOccurrence("raw/ch1.md", "Guanyin", "person", "ctx")
        raw_index = _make_index(entities={"Guanyin": [occ]})
        mapping = CanonicalMapping()
        resolved = _apply_canonical_mapping(raw_index, mapping)
        assert "Guanyin" in resolved.entities
        assert len(resolved.entities["Guanyin"]) == 1

    def test_preserves_topics_and_concepts(self):
        raw_index = _make_index(
            topics={"journey": ["raw/ch1.md"]},
            concepts={"72 Transformations": ["raw/ch1.md"]},
        )
        mapping = CanonicalMapping()
        resolved = _apply_canonical_mapping(raw_index, mapping)
        assert resolved.topics == {"journey": ["raw/ch1.md"]}
        assert resolved.concepts == {"72 Transformations": ["raw/ch1.md"]}

    def test_preserves_extraction_count(self):
        raw_index = _make_index(extraction_count=42)
        mapping = CanonicalMapping()
        resolved = _apply_canonical_mapping(raw_index, mapping)
        assert resolved.extraction_count == 42

    def test_canonical_name_already_exists_as_key(self):
        """If both the canonical and an alias exist as raw keys, merge them."""
        occ1 = EntityOccurrence("raw/ch1.md", "Sun Wukong", "person", "ctx1")
        occ2 = EntityOccurrence("raw/ch2.md", "Monkey King", "person", "ctx2")
        occ3 = EntityOccurrence("raw/ch3.md", "Sun Wukong", "person", "ctx3")
        raw_index = _make_index(
            entities={
                "Sun Wukong": [occ1, occ3],
                "Monkey King": [occ2],
            },
        )
        mapping = CanonicalMapping(
            aliases={"Sun Wukong": ["Monkey King"]},
            reverse={"Monkey King": "Sun Wukong"},
        )
        resolved = _apply_canonical_mapping(raw_index, mapping)
        assert len(resolved.entities["Sun Wukong"]) == 3


# ---------------------------------------------------------------------------
# plan_aggregation tests
# ---------------------------------------------------------------------------

class TestPlanAggregation:
    def test_happy_path(self):
        """Basic successful planning with valid LLM response."""
        index = _make_index(
            entities={"Sun Wukong": [EntityOccurrence("raw/ch1.md", "Sun Wukong", "person", "ctx")]},
            topics={"journey": ["raw/ch1.md"]},
            concepts={"72 Transformations": ["raw/ch1.md"]},
        )
        response = _valid_articles_response(5, "concept")

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation(
                "Sun Wukong", index, categories=CATEGORIES, model="test-model"
            )

        assert len(result) == 5
        assert all(isinstance(a, ThematicArticle) for a in result)
        assert result[0].path == "wiki/concept/article-0.md"
        assert result[0].type == "concept"
        assert result[0].title == "Article 0"

    def test_renders_prompt_with_correct_variables(self):
        """Verify the prompt template is rendered with the expected variables."""
        index = _make_index(
            entities={
                "Sun Wukong": [
                    EntityOccurrence("raw/ch1.md", "Sun Wukong", "person", "ctx"),
                    EntityOccurrence("raw/ch2.md", "Sun Wukong", "person", "ctx"),
                ],
                "Guanyin": [
                    EntityOccurrence("raw/ch1.md", "Guanyin", "person", "ctx"),
                ],
            },
            topics={"journey": ["raw/ch1.md", "raw/ch2.md"]},
            concepts={"Five Elements Mountain": ["raw/ch1.md"]},
            extraction_count=10,
        )
        response = _valid_articles_response(3, "concept")

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response) as mock_llm:
            plan_aggregation(
                "Sun Wukong", index, categories=CATEGORIES, model="test-model"
            )

        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args[1]
        messages = call_kwargs["messages"]

        system_msg = messages[0]["content"]
        # Check template variables were rendered
        assert "Sun Wukong" in system_msg
        assert "10" in system_msg  # extraction_count
        assert "Sun Wukong — 2" in system_msg  # entity frequency
        assert "Guanyin — 1" in system_msg
        assert "journey — 2" in system_msg  # topic frequency
        assert "Five Elements Mountain" in system_msg  # concept titles
        assert "concept, reference, how-to" in system_msg  # categories_str

        user_msg = messages[1]["content"]
        assert "Sun Wukong" in user_msg

    def test_llm_called_with_max_tokens_4096(self):
        """completion_json receives max_tokens=4096."""
        index = _make_index()
        response = _valid_articles_response(3)

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response) as mock_llm:
            plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert mock_llm.call_args[1]["max_tokens"] == 4096

    def test_drops_article_with_invalid_path(self, capsys):
        """Articles with unsafe paths are dropped with a warning."""
        index = _make_index()
        response = {
            "articles": [
                {"path": "wiki/concept/good.md", "type": "concept", "title": "Good", "description": "ok"},
                {"path": "wiki/../raw/evil.md", "type": "concept", "title": "Evil", "description": "bad"},
                {"path": "wiki/concept/also-good.md", "type": "concept", "title": "Also Good", "description": "ok"},
                {"path": "wiki/concept/third-good.md", "type": "concept", "title": "Third", "description": "ok"},
            ]
        }

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert len(result) == 3
        paths = [a.path for a in result]
        assert "wiki/../raw/evil.md" not in paths

        captured = capsys.readouterr()
        assert "invalid path" in captured.err

    def test_drops_article_with_invalid_type(self, capsys):
        """Articles with type not in categories are dropped with a warning."""
        index = _make_index()
        response = {
            "articles": [
                {"path": "wiki/concept/a.md", "type": "concept", "title": "A", "description": "ok"},
                {"path": "wiki/bogus/b.md", "type": "bogus", "title": "B", "description": "bad type"},
                {"path": "wiki/concept/c.md", "type": "concept", "title": "C", "description": "ok"},
                {"path": "wiki/concept/d.md", "type": "concept", "title": "D", "description": "ok"},
            ]
        }

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert len(result) == 3
        types = [a.type for a in result]
        assert "bogus" not in types

        captured = capsys.readouterr()
        assert "invalid type" in captured.err

    def test_drops_article_with_empty_title(self, capsys):
        """Articles with empty title are dropped with a warning."""
        index = _make_index()
        response = {
            "articles": [
                {"path": "wiki/concept/a.md", "type": "concept", "title": "A", "description": "ok"},
                {"path": "wiki/concept/b.md", "type": "concept", "title": "", "description": "empty title"},
                {"path": "wiki/concept/c.md", "type": "concept", "title": "C", "description": "ok"},
                {"path": "wiki/concept/d.md", "type": "concept", "title": "D", "description": "ok"},
            ]
        }

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert len(result) == 3
        assert all(a.title for a in result)

        captured = capsys.readouterr()
        assert "empty title" in captured.err

    def test_clamped_to_15_articles(self):
        """More than 15 valid articles are truncated to 15."""
        index = _make_index()
        response = _valid_articles_response(20, "concept")

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert len(result) == _MAX_ARTICLES

    def test_fewer_than_3_raises_derive_error(self):
        """Fewer than 3 valid articles after filtering raises DeriveError."""
        index = _make_index()
        response = _valid_articles_response(2, "concept")

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            with pytest.raises(DeriveError, match="only 2 valid articles"):
                plan_aggregation("topic", index, categories=CATEGORIES, model="m")

    def test_zero_valid_after_filtering_raises_derive_error(self):
        """All articles invalid → DeriveError."""
        index = _make_index()
        response = {
            "articles": [
                {"path": "bad-path", "type": "concept", "title": "A", "description": "x"},
                {"path": "wiki/../raw/evil.md", "type": "concept", "title": "B", "description": "x"},
            ]
        }

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            with pytest.raises(DeriveError, match="only 0 valid articles"):
                plan_aggregation("topic", index, categories=CATEGORIES, model="m")

    def test_llm_failure_raises_derive_error(self):
        """LLM exception is wrapped in DeriveError."""
        index = _make_index()

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=RuntimeError("LLM down"),
        ):
            with pytest.raises(DeriveError, match="aggregation planning failed"):
                plan_aggregation("topic", index, categories=CATEGORIES, model="m")

    def test_missing_articles_key_raises_derive_error(self):
        """LLM returns JSON without 'articles' key → DeriveError."""
        index = _make_index()

        with patch("kb_ai.derive._reorganize.completion_json", return_value={}):
            with pytest.raises(DeriveError, match="only 0 valid articles"):
                plan_aggregation("topic", index, categories=CATEGORIES, model="m")

    def test_articles_not_a_list_raises_derive_error(self):
        """LLM returns articles as non-list → DeriveError."""
        index = _make_index()

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            return_value={"articles": "not a list"},
        ):
            with pytest.raises(DeriveError, match="missing articles array"):
                plan_aggregation("topic", index, categories=CATEGORIES, model="m")

    def test_non_dict_items_in_articles_skipped(self):
        """Non-dict items in articles array are silently skipped."""
        index = _make_index()
        response = {
            "articles": [
                "not a dict",
                {"path": "wiki/concept/a.md", "type": "concept", "title": "A", "description": "ok"},
                42,
                {"path": "wiki/concept/b.md", "type": "concept", "title": "B", "description": "ok"},
                {"path": "wiki/concept/c.md", "type": "concept", "title": "C", "description": "ok"},
            ]
        }

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response):
            result = plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        assert len(result) == 3

    def test_frequency_tables_top_n_respected(self):
        """Verify that only top-N entities/topics/concepts appear in the prompt."""
        # Create index with many entities (more than 50)
        entities = {}
        for i in range(60):
            entities[f"Entity_{i:03d}"] = [
                EntityOccurrence(f"raw/ch{j}.md", f"Entity_{i:03d}", "person", "ctx")
                for j in range(60 - i)  # Entity_000 has 60 occurrences, Entity_059 has 1
            ]
        index = _make_index(entities=entities, extraction_count=60)
        response = _valid_articles_response(3, "concept")

        with patch("kb_ai.derive._reorganize.completion_json", return_value=response) as mock_llm:
            plan_aggregation("topic", index, categories=CATEGORIES, model="m")

        system_msg = mock_llm.call_args[1]["messages"][0]["content"]
        # Entity_000 (60 occurrences) should be present
        assert "Entity_000 — 60" in system_msg
        # Entity_049 (11 occurrences) should be the 50th
        assert "Entity_049 — 11" in system_msg
        # Entity_050 (10 occurrences) should NOT be present (past top 50)
        assert "Entity_050" not in system_msg


# ---------------------------------------------------------------------------
# reorganize() orchestrator tests
# ---------------------------------------------------------------------------

class TestReorganize:
    def _fixture_kb(self, tmp_path: Path) -> KBStore:
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
            ],
        )
        extraction2 = ExtractionResult(
            summary="The pilgrims meet a demon.",
            entities=[
                {"name": "Monkey King", "type": "person", "context": "fighter"},
                {"name": "Zhu Bajie", "type": "person", "context": "companion"},
            ],
            topics=["journey", "battle"],
            concepts=[
                {"title": "72 Transformations", "definition": "Combat technique."},
            ],
        )

        checksum1 = _compute_checksum("Chapter 1 content.")
        checksum2 = _compute_checksum("Chapter 2 content.")
        extraction_layer.persist(
            store, "raw/chapter-01.md", extraction1,
            source_checksum=checksum1, extract_model="m",
        )
        extraction_layer.persist(
            store, "raw/chapter-02.md", extraction2,
            source_checksum=checksum2, extract_model="m",
        )
        return store

    def test_end_to_end(self, tmp_path: Path):
        """reorganize() chains all steps and returns a ReorganizePlan."""
        store = self._fixture_kb(tmp_path)

        # Mock resolve_entities LLM call
        resolve_response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King"],
                    "type": "person",
                }
            ]
        }

        # Mock plan_aggregation LLM call
        plan_response = _valid_articles_response(5, "concept")

        call_count = 0

        def mock_completion_json(**kwargs):
            nonlocal call_count
            call_count += 1
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            # First call is resolve_entities, second is plan_aggregation
            if "entity name resolver" in system_content.lower():
                return resolve_response
            else:
                return plan_response

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            result = reorganize(
                store, "Sun Wukong", categories=CATEGORIES, model="test-model"
            )

        assert isinstance(result, ReorganizePlan)
        assert result.topic == "Sun Wukong"
        assert len(result.articles) == 5
        assert isinstance(result.canonical_mapping, CanonicalMapping)
        assert isinstance(result.entity_index, EntityIndex)

    def test_canonical_mapping_applied_to_index(self, tmp_path: Path):
        """After resolve_entities, the entity index uses canonical names."""
        store = self._fixture_kb(tmp_path)

        resolve_response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King"],
                    "type": "person",
                }
            ]
        }
        plan_response = _valid_articles_response(3, "concept")

        def mock_completion_json(**kwargs):
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            if "entity name resolver" in system_content.lower():
                return resolve_response
            else:
                return plan_response

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            result = reorganize(
                store, "Sun Wukong", categories=CATEGORIES, model="test-model"
            )

        # "Monkey King" should be merged under "Sun Wukong"
        assert "Monkey King" not in result.entity_index.entities
        assert "Sun Wukong" in result.entity_index.entities
        # Sun Wukong should have occurrences from both raw names
        assert len(result.entity_index.entities["Sun Wukong"]) == 2

    def test_canonical_mapping_stored_in_plan(self, tmp_path: Path):
        """The CanonicalMapping is stored in the result."""
        store = self._fixture_kb(tmp_path)

        resolve_response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King"],
                    "type": "person",
                }
            ]
        }
        plan_response = _valid_articles_response(3, "concept")

        def mock_completion_json(**kwargs):
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            if "entity name resolver" in system_content.lower():
                return resolve_response
            else:
                return plan_response

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            result = reorganize(
                store, "Sun Wukong", categories=CATEGORIES, model="test-model"
            )

        assert "Sun Wukong" in result.canonical_mapping.aliases
        assert result.canonical_mapping.reverse["Monkey King"] == "Sun Wukong"

    def test_plan_serializable(self, tmp_path: Path):
        """ReorganizePlan.to_dict() produces a serializable dict."""
        store = self._fixture_kb(tmp_path)

        resolve_response = {"groups": []}
        plan_response = _valid_articles_response(3, "concept")

        def mock_completion_json(**kwargs):
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            if "entity name resolver" in system_content.lower():
                return resolve_response
            else:
                return plan_response

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            result = reorganize(
                store, "Sun Wukong", categories=CATEGORIES, model="test-model"
            )

        d = result.to_dict()
        assert d["topic"] == "Sun Wukong"
        assert len(d["articles"]) == 3
        assert d["extraction_count"] == 2

    def test_entity_resolution_failure_degrades_gracefully(self, tmp_path: Path):
        """If resolve_entities fails, reorganize still works with un-canonicalized names."""
        store = self._fixture_kb(tmp_path)

        plan_response = _valid_articles_response(3, "concept")
        call_count = 0

        def mock_completion_json(**kwargs):
            nonlocal call_count
            call_count += 1
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            if "entity name resolver" in system_content.lower():
                # Simulate LLM failure (graceful degradation returns empty mapping)
                raise RuntimeError("LLM timeout")
            else:
                return plan_response

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            result = reorganize(
                store, "Sun Wukong", categories=CATEGORIES, model="test-model"
            )

        # Should still produce a plan with un-canonicalized entity names
        assert len(result.articles) == 3
        # Both raw names remain as separate keys
        assert "Sun Wukong" in result.entity_index.entities
        assert "Monkey King" in result.entity_index.entities

    def test_plan_aggregation_failure_raises_derive_error(self, tmp_path: Path):
        """If plan_aggregation LLM fails, DeriveError propagates."""
        store = self._fixture_kb(tmp_path)

        def mock_completion_json(**kwargs):
            messages = kwargs["messages"]
            system_content = messages[0]["content"]
            if "entity name resolver" in system_content.lower():
                return {"groups": []}
            else:
                raise RuntimeError("LLM down")

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=mock_completion_json,
        ):
            with pytest.raises(DeriveError, match="aggregation planning failed"):
                reorganize(
                    store, "Sun Wukong", categories=CATEGORIES, model="test-model"
                )


# ---------------------------------------------------------------------------
# Prompt template rendering test
# ---------------------------------------------------------------------------

class TestPromptTemplate:
    def test_aggregate_plan_template_renders(self):
        """Verify the aggregate-plan template renders without errors."""
        from kb_ai.prompts import default_registry

        prompt = default_registry().get("aggregate-plan")
        rendered = prompt.render(
            topic="Sun Wukong",
            extraction_count=100,
            entity_frequency="Sun Wukong — 66\nGuanyin — 12",
            topic_frequency="journey — 90\nbattle — 45",
            concept_titles="72 Transformations\nFive Elements Mountain",
            categories_str="concept, reference, how-to",
        )
        assert "Sun Wukong" in rendered
        assert "100" in rendered
        assert "Sun Wukong — 66" in rendered
        assert "journey — 90" in rendered
        assert "72 Transformations" in rendered
        assert "concept, reference, how-to" in rendered
        # Double-braces in template should have produced single braces in output
        assert '"articles"' in rendered
        assert '"path"' in rendered

    def test_aggregate_plan_template_has_required_variables(self):
        """The template must accept all documented variables."""
        from kb_ai.prompts import default_registry

        prompt = default_registry().get("aggregate-plan")
        # This should not raise KeyError
        prompt.render(
            topic="t",
            extraction_count=1,
            entity_frequency="",
            topic_frequency="",
            concept_titles="",
            categories_str="concept",
        )
