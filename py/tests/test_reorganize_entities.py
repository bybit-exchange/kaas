"""Tests for resolve_entities() in derive/_reorganize.py.

Covers heuristic filtering, batching, LLM call parameters, batch merging,
and graceful degradation on LLM failure.
"""
from __future__ import annotations

from unittest.mock import patch, call, MagicMock

import pytest

from kb_ai.derive._reorganize import (
    CanonicalMapping,
    _ENUMERATION_RE,
    _heuristic_filter,
    _merge_batch_results,
    _parse_groups,
    resolve_entities,
)


# ---------------------------------------------------------------------------
# _heuristic_filter tests
# ---------------------------------------------------------------------------

class TestHeuristicFilter:
    def test_keeps_short_normal_names(self):
        kept, filtered = _heuristic_filter(["Sun Wukong", "Guanyin"])
        assert kept == ["Sun Wukong", "Guanyin"]
        assert filtered == []

    def test_filters_names_longer_than_60_chars(self):
        long_name = "A" * 61
        normal_name = "Sun Wukong"
        kept, filtered = _heuristic_filter([normal_name, long_name])
        assert kept == [normal_name]
        assert filtered == [long_name]

    def test_exactly_60_chars_is_kept(self):
        name_60 = "A" * 60
        kept, filtered = _heuristic_filter([name_60])
        assert kept == [name_60]
        assert filtered == []

    def test_filters_enumeration_patterns(self):
        patterns = [
            "Sequence of events in the battle",
            "Steps to enlightenment",
            "List of demons encountered",
            "Effects of the elixir",
            "Characters listed in the chapter",
            "Techniques described by the master",
            "Weapons including the staff",
            "Demons such as Red Boy",
            "Transformations for example cloud riding",
        ]
        kept, filtered = _heuristic_filter(patterns)
        assert kept == []
        assert len(filtered) == len(patterns)

    def test_enumeration_pattern_case_insensitive(self):
        kept, filtered = _heuristic_filter(["LIST OF things"])
        assert kept == []
        assert filtered == ["LIST OF things"]

    def test_mixed_names(self):
        names = ["Sun Wukong", "list of demons", "A" * 100, "Guanyin"]
        kept, filtered = _heuristic_filter(names)
        assert kept == ["Sun Wukong", "Guanyin"]
        assert len(filtered) == 2

    def test_empty_input(self):
        kept, filtered = _heuristic_filter([])
        assert kept == []
        assert filtered == []

    def test_enumeration_regex_matches_expected_patterns(self):
        """Verify the regex matches all required enumeration phrases."""
        phrases = [
            "sequence of", "steps to", "list of", "effects of",
            "listed", "described", "including", "such as", "for example",
        ]
        for phrase in phrases:
            assert _ENUMERATION_RE.search(phrase), f"Regex should match '{phrase}'"

    def test_normal_entity_not_matched_by_regex(self):
        """Normal entity names should not be caught by the regex."""
        safe_names = [
            "Sun Wukong", "Guanyin", "Tang Sanzang",
            "72 Transformations", "Five Elements Mountain",
        ]
        for name in safe_names:
            assert not _ENUMERATION_RE.search(name), (
                f"Regex should NOT match '{name}'"
            )


# ---------------------------------------------------------------------------
# _parse_groups tests
# ---------------------------------------------------------------------------

class TestParseGroups:
    def test_valid_groups(self):
        response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King", "Great Sage"],
                    "type": "person",
                },
            ]
        }
        result = _parse_groups(response)
        assert "Sun Wukong" in result
        assert result["Sun Wukong"]["aliases"] == ["Monkey King", "Great Sage"]
        assert result["Sun Wukong"]["type"] == "person"

    def test_skips_empty_canonical(self):
        response = {"groups": [{"canonical": "", "aliases": ["a"], "type": "x"}]}
        assert _parse_groups(response) == {}

    def test_skips_non_dict_groups(self):
        response = {"groups": ["not a dict"]}
        assert _parse_groups(response) == {}

    def test_skips_groups_with_empty_aliases(self):
        response = {"groups": [{"canonical": "A", "aliases": [], "type": "x"}]}
        assert _parse_groups(response) == {}

    def test_filters_non_string_aliases(self):
        response = {
            "groups": [
                {"canonical": "A", "aliases": ["valid", 42, "", None], "type": "x"},
            ]
        }
        result = _parse_groups(response)
        assert result["A"]["aliases"] == ["valid"]

    def test_handles_missing_groups_key(self):
        assert _parse_groups({}) == {}

    def test_handles_non_list_groups(self):
        assert _parse_groups({"groups": "not a list"}) == {}

    def test_missing_type_defaults_to_empty_string(self):
        response = {"groups": [{"canonical": "A", "aliases": ["B"]}]}
        result = _parse_groups(response)
        assert result["A"]["type"] == ""


# ---------------------------------------------------------------------------
# _merge_batch_results tests
# ---------------------------------------------------------------------------

class TestMergeBatchResults:
    def test_single_batch(self):
        batches = [{"Sun Wukong": {"aliases": ["Monkey King"], "type": "person"}}]
        merged = _merge_batch_results(batches)
        assert merged == {"Sun Wukong": {"aliases": ["Monkey King"], "type": "person"}}

    def test_disjoint_batches(self):
        batches = [
            {"Sun Wukong": {"aliases": ["Monkey King"], "type": "person"}},
            {"Guanyin": {"aliases": ["Goddess of Mercy"], "type": "person"}},
        ]
        merged = _merge_batch_results(batches)
        assert "Sun Wukong" in merged
        assert "Guanyin" in merged

    def test_same_canonical_aliases_unioned(self):
        batches = [
            {"Sun Wukong": {"aliases": ["Monkey King"], "type": "person"}},
            {"Sun Wukong": {"aliases": ["Great Sage"], "type": "person"}},
        ]
        merged = _merge_batch_results(batches)
        assert "Sun Wukong" in merged
        assert set(merged["Sun Wukong"]["aliases"]) == {"Monkey King", "Great Sage"}

    def test_same_canonical_duplicate_alias_deduplicated(self):
        batches = [
            {"Sun Wukong": {"aliases": ["Monkey King", "Great Sage"], "type": "person"}},
            {"Sun Wukong": {"aliases": ["Monkey King", "Wukong"], "type": "person"}},
        ]
        merged = _merge_batch_results(batches)
        aliases = merged["Sun Wukong"]["aliases"]
        assert len(aliases) == len(set(aliases)), "Aliases should be deduplicated"
        assert set(aliases) == {"Monkey King", "Great Sage", "Wukong"}

    def test_type_preserved_from_first_batch(self):
        batches = [
            {"A": {"aliases": ["B"], "type": "person"}},
            {"A": {"aliases": ["C"], "type": "place"}},
        ]
        merged = _merge_batch_results(batches)
        assert merged["A"]["type"] == "person"

    def test_type_filled_from_later_batch_if_first_empty(self):
        batches = [
            {"A": {"aliases": ["B"], "type": ""}},
            {"A": {"aliases": ["C"], "type": "place"}},
        ]
        merged = _merge_batch_results(batches)
        assert merged["A"]["type"] == "place"

    def test_empty_batches(self):
        assert _merge_batch_results([]) == {}


# ---------------------------------------------------------------------------
# resolve_entities tests
# ---------------------------------------------------------------------------

class TestResolveEntities:
    def test_all_names_filtered_returns_empty_mapping(self):
        """If heuristic filter removes all names, no LLM call is made."""
        names = ["list of demons", "A" * 100]
        with patch("kb_ai.derive._reorganize.completion_json") as mock_llm:
            result = resolve_entities(names, model="test-model")

        mock_llm.assert_not_called()
        assert result.aliases == {}
        assert result.reverse == {}
        assert set(result.filtered_out) == set(names)

    def test_basic_resolution(self):
        """Happy path: LLM groups aliases correctly."""
        names = ["Sun Wukong", "Monkey King", "Great Sage", "Guanyin"]
        llm_response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King", "Great Sage"],
                    "type": "person",
                },
            ]
        }

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            result = resolve_entities(names, model="test-model")

        mock_llm.assert_called_once()
        assert result.aliases == {"Sun Wukong": ["Monkey King", "Great Sage"]}
        assert result.reverse == {
            "Monkey King": "Sun Wukong",
            "Great Sage": "Sun Wukong",
        }
        assert result.filtered_out == []

    def test_llm_called_with_correct_params(self):
        """Verify max_tokens=4096 and cache=True are passed."""
        names = ["Sun Wukong", "Guanyin"]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model")

        mock_llm.assert_called_once()
        _, kwargs = mock_llm.call_args
        assert kwargs["model"] == "test-model"
        assert kwargs["max_tokens"] == 4096
        assert kwargs["cache"] is True

    def test_prompt_contains_names_in_xml_tags(self):
        """The user message should wrap names in <names> tags."""
        names = ["Sun Wukong", "Guanyin"]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model")

        messages = mock_llm.call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "<names>" in user_msg
        assert "</names>" in user_msg
        assert "Sun Wukong" in user_msg
        assert "Guanyin" in user_msg

    def test_prompt_system_message_asks_for_json_groups(self):
        """System message should ask for JSON with {groups: [...]}."""
        names = ["Sun Wukong"]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model")

        messages = mock_llm.call_args[1]["messages"]
        system_msg = messages[0]["content"]
        assert '"groups"' in system_msg
        assert '"canonical"' in system_msg
        assert '"aliases"' in system_msg
        assert '"type"' in system_msg

    def test_batching_at_max_batch_size(self):
        """Names exceeding max_batch_size are split into multiple batches."""
        names = [f"Entity_{i}" for i in range(750)]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model", max_batch_size=500)

        # Should be called twice: batch of 500 + batch of 250
        assert mock_llm.call_count == 2

        # First batch has 500 names
        first_call_messages = mock_llm.call_args_list[0][1]["messages"]
        first_user_msg = first_call_messages[1]["content"]
        first_names = first_user_msg.split("<names>\n")[1].split("\n</names>")[0].split("\n")
        assert len(first_names) == 500

        # Second batch has 250 names
        second_call_messages = mock_llm.call_args_list[1][1]["messages"]
        second_user_msg = second_call_messages[1]["content"]
        second_names = second_user_msg.split("<names>\n")[1].split("\n</names>")[0].split("\n")
        assert len(second_names) == 250

    def test_exactly_max_batch_size_single_batch(self):
        """Exactly max_batch_size names should produce a single batch."""
        names = [f"Entity_{i}" for i in range(500)]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model", max_batch_size=500)

        assert mock_llm.call_count == 1

    def test_batch_merging_same_canonical(self):
        """Same canonical across batches gets aliases unioned."""
        names = [f"Entity_{i}" for i in range(10)]

        def side_effect(**kwargs):
            messages = kwargs["messages"]
            user_msg = messages[1]["content"]
            if "Entity_0" in user_msg:
                return {
                    "groups": [
                        {
                            "canonical": "Sun Wukong",
                            "aliases": ["Monkey King"],
                            "type": "person",
                        }
                    ]
                }
            else:
                return {
                    "groups": [
                        {
                            "canonical": "Sun Wukong",
                            "aliases": ["Great Sage"],
                            "type": "person",
                        }
                    ]
                }

        with patch(
            "kb_ai.derive._reorganize.completion_json", side_effect=side_effect
        ):
            result = resolve_entities(names, model="test-model", max_batch_size=5)

        assert "Sun Wukong" in result.aliases
        assert set(result.aliases["Sun Wukong"]) == {"Monkey King", "Great Sage"}
        assert result.reverse["Monkey King"] == "Sun Wukong"
        assert result.reverse["Great Sage"] == "Sun Wukong"

    def test_one_batch_fails_graceful_degradation(self, capsys):
        """If one batch fails, its names are skipped; other batches succeed."""
        names = [f"Entity_{i}" for i in range(10)]
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM timeout")
            return {
                "groups": [
                    {
                        "canonical": "Guanyin",
                        "aliases": ["Goddess of Mercy"],
                        "type": "person",
                    }
                ]
            }

        with patch(
            "kb_ai.derive._reorganize.completion_json", side_effect=side_effect
        ):
            result = resolve_entities(names, model="test-model", max_batch_size=5)

        # Second batch succeeded
        assert "Guanyin" in result.aliases
        assert result.reverse["Goddess of Mercy"] == "Guanyin"

        # Warning printed for the failed batch
        captured = capsys.readouterr()
        assert "entity resolution batch failed" in captured.err
        assert "LLM timeout" in captured.err

    def test_all_batches_fail_returns_empty_mapping(self, capsys):
        """If all batches fail, return empty CanonicalMapping (not an error)."""
        names = ["Sun Wukong", "Guanyin"]

        with patch(
            "kb_ai.derive._reorganize.completion_json",
            side_effect=RuntimeError("LLM down"),
        ):
            result = resolve_entities(names, model="test-model")

        assert result.aliases == {}
        assert result.reverse == {}
        assert result.filtered_out == []
        assert isinstance(result, CanonicalMapping)

    def test_filtered_names_and_llm_combined(self):
        """Filtered names go to filtered_out; kept names go to LLM."""
        names = [
            "Sun Wukong",
            "list of demons encountered",
            "A" * 61,
            "Guanyin",
        ]
        llm_response = {
            "groups": [
                {
                    "canonical": "Sun Wukong",
                    "aliases": ["Monkey King"],
                    "type": "person",
                }
            ]
        }

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            result = resolve_entities(names, model="test-model")

        # Only 2 names sent to LLM (Sun Wukong, Guanyin)
        mock_llm.assert_called_once()
        messages = mock_llm.call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "Sun Wukong" in user_msg
        assert "Guanyin" in user_msg
        assert "list of demons" not in user_msg

        # Filtered out names tracked
        assert len(result.filtered_out) == 2
        assert "list of demons encountered" in result.filtered_out

        # LLM result present
        assert result.aliases == {"Sun Wukong": ["Monkey King"]}

    def test_empty_input_returns_empty_mapping(self):
        """Empty name list returns empty mapping without LLM call."""
        with patch("kb_ai.derive._reorganize.completion_json") as mock_llm:
            result = resolve_entities([], model="test-model")

        mock_llm.assert_not_called()
        assert result.aliases == {}
        assert result.reverse == {}
        assert result.filtered_out == []

    def test_custom_max_batch_size(self):
        """Custom max_batch_size is respected."""
        names = [f"Entity_{i}" for i in range(15)]
        llm_response = {"groups": []}

        with patch(
            "kb_ai.derive._reorganize.completion_json", return_value=llm_response
        ) as mock_llm:
            resolve_entities(names, model="test-model", max_batch_size=10)

        # 15 names / batch_size 10 = 2 batches (10 + 5)
        assert mock_llm.call_count == 2
