"""Tests for kb_ai._types module."""

from __future__ import annotations

import pytest

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget


class TestMergeTarget:
    def test_from_dict_normal(self):
        target = MergeTarget.from_dict({"path": "wiki/article.md", "reason": "same topic"})
        assert target.path == "wiki/article.md"
        assert target.reason == "same topic"

    def test_from_dict_missing_reason(self):
        target = MergeTarget.from_dict({"path": "wiki/article.md"})
        assert target.path == "wiki/article.md"
        assert target.reason == ""

    def test_from_dict_none(self):
        target = MergeTarget.from_dict(None)
        assert target.path == ""
        assert target.reason == ""

    def test_from_dict_empty(self):
        target = MergeTarget.from_dict({})
        assert target.path == ""
        assert target.reason == ""

    def test_from_dict_non_dict(self):
        target = MergeTarget.from_dict("not a dict")  # type: ignore
        assert target.path == ""


class TestCreateTarget:
    def test_from_dict_normal(self):
        target = CreateTarget.from_dict({
            "path": "wiki/new.md",
            "type": "concept",
            "title": "New Article",
            "reason": "novel topic",
        })
        assert target.path == "wiki/new.md"
        assert target.type == "concept"
        assert target.title == "New Article"
        assert target.reason == "novel topic"

    def test_from_dict_partial(self):
        target = CreateTarget.from_dict({"path": "wiki/new.md"})
        assert target.path == "wiki/new.md"
        assert target.type == ""
        assert target.title == ""
        assert target.reason == ""

    def test_from_dict_none(self):
        target = CreateTarget.from_dict(None)
        assert target.path == ""
        assert target.type == ""
        assert target.title == ""
        assert target.reason == ""


class TestClassificationResult:
    def test_from_dict_full(self):
        data = {
            "merge_into": [
                {"path": "wiki/a.md", "reason": "related"},
                {"path": "wiki/b.md", "reason": "overlaps"},
            ],
            "create_new": [
                {"path": "wiki/new.md", "type": "concept", "title": "New", "reason": "novel"},
            ],
        }
        result = ClassificationResult.from_dict(data)
        assert len(result.merge_into) == 2
        assert isinstance(result.merge_into[0], MergeTarget)
        assert result.merge_into[0].path == "wiki/a.md"
        assert result.merge_into[0].reason == "related"
        assert result.merge_into[1].path == "wiki/b.md"
        assert len(result.create_new) == 1
        assert isinstance(result.create_new[0], CreateTarget)
        assert result.create_new[0].path == "wiki/new.md"
        assert result.create_new[0].title == "New"

    def test_from_dict_with_merge_targets(self):
        """AC1: from_dict({'merge_into': [{'path': 'x'}]}) returns correct dataclass."""
        result = ClassificationResult.from_dict({"merge_into": [{"path": "x"}]})
        assert len(result.merge_into) == 1
        assert isinstance(result.merge_into[0], MergeTarget)
        assert result.merge_into[0].path == "x"
        assert result.merge_into[0].reason == ""
        assert result.create_new == []

    def test_from_dict_none(self):
        result = ClassificationResult.from_dict(None)
        assert result.merge_into == []
        assert result.create_new == []

    def test_from_dict_empty(self):
        result = ClassificationResult.from_dict({})
        assert result.merge_into == []
        assert result.create_new == []

    def test_from_dict_malformed_entries_filtered(self):
        """Non-dict entries in merge_into/create_new are filtered out."""
        data = {
            "merge_into": [{"path": "valid.md"}, "not_a_dict", None, 42],
            "create_new": [{"path": "new.md"}, "garbage"],
        }
        result = ClassificationResult.from_dict(data)
        assert len(result.merge_into) == 1
        assert result.merge_into[0].path == "valid.md"
        assert len(result.create_new) == 1
        assert result.create_new[0].path == "new.md"

    def test_to_dict(self):
        result = ClassificationResult(
            merge_into=[MergeTarget(path="wiki/a.md", reason="related")],
            create_new=[CreateTarget(path="wiki/new.md", type="concept", title="T", reason="r")],
        )
        d = result.to_dict()
        assert d == {
            "merge_into": [{"path": "wiki/a.md", "reason": "related"}],
            "create_new": [{"path": "wiki/new.md", "type": "concept", "title": "T", "reason": "r"}],
        }

    def test_roundtrip(self):
        """from_dict -> to_dict preserves data."""
        original = {
            "merge_into": [{"path": "a.md", "reason": "r1"}],
            "create_new": [{"path": "b.md", "type": "t", "title": "T", "reason": "r2"}],
        }
        result = ClassificationResult.from_dict(original)
        assert result.to_dict() == original
