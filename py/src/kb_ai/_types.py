"""Shared type definitions for kb_ai.

This module defines domain types that are used across multiple layers
(core, storage, retrieval, commands) to avoid circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArticleMeta:
    title: str
    path: str
    summary: str = ""
    type: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = ""


@dataclass
class ExtractionResult:
    summary: str = ""
    concepts: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    action_items: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    source_path: str = ""


# ── Classification result types ───────────────────────────────────────


@dataclass
class MergeTarget:
    """A target article to merge extracted knowledge into."""

    path: str
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> MergeTarget:
        """Create from a classification dict entry, tolerant of missing fields."""
        if not data or not isinstance(data, dict):
            return cls(path="", reason="")
        return cls(
            path=data.get("path", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class CreateTarget:
    """A new article to create from extracted knowledge."""

    path: str
    type: str = ""
    title: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> CreateTarget:
        """Create from a classification dict entry, tolerant of missing fields."""
        if not data or not isinstance(data, dict):
            return cls(path="", type="", title="", reason="")
        return cls(
            path=data.get("path", ""),
            type=data.get("type", ""),
            title=data.get("title", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class ClassificationResult:
    """Typed wrapper for classify_article() return value.

    Converts the raw dict from LLM classification into a structured object
    with proper field access and defaults for missing data.
    """

    merge_into: list[MergeTarget] = field(default_factory=list)
    create_new: list[CreateTarget] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> ClassificationResult:
        """Create from classify_article() output dict.

        Handles missing fields, None values, and malformed entries gracefully.
        """
        if not data or not isinstance(data, dict):
            return cls(merge_into=[], create_new=[])

        raw_merge = data.get("merge_into") or []
        raw_create = data.get("create_new") or []

        # Filter out non-dict entries that may come from malformed LLM output
        merge_into = [
            MergeTarget.from_dict(entry)
            for entry in raw_merge
            if isinstance(entry, dict)
        ]
        create_new = [
            CreateTarget.from_dict(entry)
            for entry in raw_create
            if isinstance(entry, dict)
        ]

        return cls(merge_into=merge_into, create_new=create_new)

    def to_dict(self) -> dict:
        """Convert back to the dict format expected by downstream pipeline code."""
        return {
            "merge_into": [
                {"path": m.path, "reason": m.reason}
                for m in self.merge_into
            ],
            "create_new": [
                {"path": c.path, "type": c.type, "title": c.title, "reason": c.reason}
                for c in self.create_new
            ],
        }

    # ── Dict-compatible access (for un-migrated callers) ─────────────

    def get(self, key: str, default=None):
        """Dict-like .get() for backward compatibility with un-migrated code."""
        d = self.to_dict()
        return d.get(key, default)

    def __getitem__(self, key: str):
        """Dict-like [] access for backward compatibility."""
        d = self.to_dict()
        return d[key]

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator for backward compatibility."""
        return key in ("merge_into", "create_new")
