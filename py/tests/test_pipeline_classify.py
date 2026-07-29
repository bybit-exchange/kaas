"""Tests for kb_ai.commands.pipeline._phase_classify."""
from __future__ import annotations

import pytest

from kb_ai.commands.pipeline._phase_classify import _cluster_by_topic_overlap


class TestClusterByTopicOverlap:
    def test_empty_list(self):
        groups = _cluster_by_topic_overlap([])
        assert groups == [[]]

    def test_single_item(self):
        items = [{"extraction": {"topics": ["python"]}}]
        groups = _cluster_by_topic_overlap(items)
        assert groups == [[0]]

    def test_two_unrelated_items(self):
        items = [
            {"extraction": {"topics": ["python", "web"]}},
            {"extraction": {"topics": ["java", "mobile"]}},
        ]
        groups = _cluster_by_topic_overlap(items)
        # Should be two separate groups
        assert len(groups) == 2
        all_indices = sorted(idx for g in groups for idx in g)
        assert all_indices == [0, 1]

    def test_two_related_items(self):
        items = [
            {"extraction": {"topics": ["python", "web", "flask"]}},
            {"extraction": {"topics": ["python", "web", "django"]}},
        ]
        groups = _cluster_by_topic_overlap(items)
        # Should be one group (high overlap)
        assert len(groups) == 1
        assert sorted(groups[0]) == [0, 1]

    def test_max_group_size_enforced(self):
        # Create 10 items all with same topic -- cap should prevent one huge group
        items = [{"extraction": {"topics": ["shared_topic"]}} for _ in range(10)]
        groups = _cluster_by_topic_overlap(items, max_group_size=4)
        for g in groups:
            assert len(g) <= 4

    def test_concepts_field_used(self):
        items = [
            {"extraction": {"topics": [], "concepts": [{"title": "React"}]}},
            {"extraction": {"topics": [], "concepts": [{"title": "React"}]}},
        ]
        groups = _cluster_by_topic_overlap(items)
        assert len(groups) == 1

    def test_string_concepts(self):
        items = [
            {"extraction": {"topics": [], "concepts": ["kubernetes", "docker"]}},
            {"extraction": {"topics": [], "concepts": ["kubernetes", "helm"]}},
        ]
        groups = _cluster_by_topic_overlap(items)
        assert len(groups) == 1

    def test_no_topics_no_concepts(self):
        items = [
            {"extraction": {"topics": [], "concepts": []}},
            {"extraction": {"topics": [], "concepts": []}},
        ]
        groups = _cluster_by_topic_overlap(items)
        # No overlap possible with empty sets -- each in own group
        assert len(groups) == 2

    def test_threshold_sensitivity(self):
        # Low overlap (1/3 = 0.33) should cluster at 0.3 threshold but not at 0.5
        items = [
            {"extraction": {"topics": ["a", "b", "c"]}},
            {"extraction": {"topics": ["a", "d", "e"]}},
        ]
        groups_low = _cluster_by_topic_overlap(items, string_threshold=0.3)
        assert len(groups_low) == 1

        groups_high = _cluster_by_topic_overlap(items, string_threshold=0.5)
        assert len(groups_high) == 2
