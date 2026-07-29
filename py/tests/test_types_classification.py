"""Tests for ClassificationResult typed domain objects -- round-trip and edge cases.

Covers:
- from_dict/to_dict round-trip preservation (wire format identity)
- Graceful handling of partial/missing/malformed data
- Typed attribute access on MergeTarget and CreateTarget
"""
from __future__ import annotations

import pytest

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget


class TestRoundTrip:
    """from_dict -> to_dict must produce byte-identical JSON wire format."""

    def test_full_round_trip(self):
        original = {
            "merge_into": [
                {"path": "wiki/concept/python.md", "reason": "same topic"},
                {"path": "wiki/project/kaas.md", "reason": "related project"},
            ],
            "create_new": [
                {"path": "wiki/concept/new.md", "type": "concept", "title": "New Concept", "reason": "novel"},
            ],
        }
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original

    def test_empty_round_trip(self):
        original = {"merge_into": [], "create_new": []}
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original

    def test_merge_only_round_trip(self):
        original = {
            "merge_into": [{"path": "wiki/x.md", "reason": "overlap"}],
            "create_new": [],
        }
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original

    def test_create_only_round_trip(self):
        original = {
            "merge_into": [],
            "create_new": [{"path": "wiki/new.md", "type": "decision", "title": "Dec", "reason": "new"}],
        }
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original

    def test_multiple_entries_round_trip(self):
        original = {
            "merge_into": [
                {"path": "wiki/a.md", "reason": "r1"},
                {"path": "wiki/b.md", "reason": "r2"},
                {"path": "wiki/c.md", "reason": "r3"},
            ],
            "create_new": [
                {"path": "wiki/x.md", "type": "concept", "title": "X", "reason": "rx"},
                {"path": "wiki/y.md", "type": "project", "title": "Y", "reason": "ry"},
            ],
        }
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original


class TestFromDictEdgeCases:
    """ClassificationResult.from_dict handles missing/malformed data gracefully."""

    def test_none_input(self):
        result = ClassificationResult.from_dict(None)
        assert result.merge_into == []
        assert result.create_new == []

    def test_empty_dict(self):
        result = ClassificationResult.from_dict({})
        assert result.merge_into == []
        assert result.create_new == []

    def test_non_dict_input(self):
        result = ClassificationResult.from_dict("not a dict")  # type: ignore
        assert result.merge_into == []
        assert result.create_new == []

    def test_none_merge_into(self):
        result = ClassificationResult.from_dict({"merge_into": None, "create_new": []})
        assert result.merge_into == []

    def test_none_create_new(self):
        result = ClassificationResult.from_dict({"merge_into": [], "create_new": None})
        assert result.create_new == []

    def test_non_dict_entries_filtered(self):
        data = {
            "merge_into": [{"path": "wiki/a.md", "reason": "ok"}, "bad_entry", 42, None],
            "create_new": [{"path": "wiki/b.md", "type": "c", "title": "t", "reason": "r"}, [], "x"],
        }
        result = ClassificationResult.from_dict(data)
        assert len(result.merge_into) == 1
        assert result.merge_into[0].path == "wiki/a.md"
        assert len(result.create_new) == 1
        assert result.create_new[0].path == "wiki/b.md"

    def test_missing_fields_default_to_empty_string(self):
        data = {
            "merge_into": [{"path": "wiki/x.md"}],  # missing reason
            "create_new": [{"path": "wiki/y.md"}],  # missing type, title, reason
        }
        result = ClassificationResult.from_dict(data)
        assert result.merge_into[0].reason == ""
        assert result.create_new[0].type == ""
        assert result.create_new[0].title == ""
        assert result.create_new[0].reason == ""

    def test_only_merge_into_key_present(self):
        data = {"merge_into": [{"path": "wiki/a.md", "reason": "x"}]}
        result = ClassificationResult.from_dict(data)
        assert len(result.merge_into) == 1
        assert result.create_new == []

    def test_only_create_new_key_present(self):
        data = {"create_new": [{"path": "wiki/b.md", "type": "concept", "title": "B", "reason": "y"}]}
        result = ClassificationResult.from_dict(data)
        assert result.merge_into == []
        assert len(result.create_new) == 1


class TestTypedAttributeAccess:
    """Typed objects provide proper attribute access."""

    def test_merge_target_attributes(self):
        mt = MergeTarget(path="wiki/concept/python.md", reason="topic overlap")
        assert mt.path == "wiki/concept/python.md"
        assert mt.reason == "topic overlap"

    def test_create_target_attributes(self):
        ct = CreateTarget(path="wiki/decision/arch.md", type="decision", title="Architecture", reason="new")
        assert ct.path == "wiki/decision/arch.md"
        assert ct.type == "decision"
        assert ct.title == "Architecture"
        assert ct.reason == "new"

    def test_classification_result_list_access(self):
        result = ClassificationResult(
            merge_into=[MergeTarget(path="wiki/a.md", reason="r1")],
            create_new=[CreateTarget(path="wiki/b.md", type="concept", title="B", reason="r2")],
        )
        assert isinstance(result.merge_into, list)
        assert isinstance(result.create_new, list)
        assert isinstance(result.merge_into[0], MergeTarget)
        assert isinstance(result.create_new[0], CreateTarget)

    def test_to_dict_output_format(self):
        """to_dict produces the exact wire format expected by JSON emission."""
        result = ClassificationResult(
            merge_into=[MergeTarget(path="wiki/a.md", reason="r")],
            create_new=[CreateTarget(path="wiki/b.md", type="t", title="T", reason="c")],
        )
        d = result.to_dict()
        assert d == {
            "merge_into": [{"path": "wiki/a.md", "reason": "r"}],
            "create_new": [{"path": "wiki/b.md", "type": "t", "title": "T", "reason": "c"}],
        }

    def test_default_construction(self):
        result = ClassificationResult()
        assert result.merge_into == []
        assert result.create_new == []
        assert result.to_dict() == {"merge_into": [], "create_new": []}
