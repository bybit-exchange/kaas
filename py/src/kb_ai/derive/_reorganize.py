"""Entity index, canonical mapping, and reorganization plan data structures.

Phase 1 of the derive knowledge reorganization feature: data structures
and the entity/topic/concept frequency index builder. No LLM calls here —
that is Phase 2 (resolve_entities) and Phase 3 (plan_aggregation).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.store import KBStore


# ---------------------------------------------------------------------------
# Data structures (Section 4.2 of the plan)
# ---------------------------------------------------------------------------

@dataclass
class EntityOccurrence:
    """One entity mention in one extraction."""

    source_path: str      # e.g. "raw/chapter-58.md"
    name: str             # raw name from extraction
    entity_type: str      # "person", "tool", etc. from entity dict "type" key
    context: str          # the "context" field from entity dict


@dataclass
class EntityIndex:
    """Aggregated entity/topic/concept frequency across all extractions."""

    # raw entity name -> list of occurrences (before resolution)
    entities: dict[str, list[EntityOccurrence]] = field(default_factory=dict)
    # topic_tag -> list of source_paths
    topics: dict[str, list[str]] = field(default_factory=dict)
    # concept_title -> list of source_paths
    concepts: dict[str, list[str]] = field(default_factory=dict)
    # Total extraction count
    extraction_count: int = 0


@dataclass
class CanonicalMapping:
    """Result of LLM entity name resolution."""

    # canonical_name -> list of alias strings
    aliases: dict[str, list[str]] = field(default_factory=dict)
    # alias -> canonical_name (reverse lookup, built from aliases)
    reverse: dict[str, str] = field(default_factory=dict)
    # names that were filtered out as enumeration-like descriptions
    filtered_out: list[str] = field(default_factory=list)


@dataclass
class ThematicArticle:
    """One planned thematic article from the aggregation plan."""

    path: str          # e.g. "wiki/concept/sun-wukong-character-overview.md"
    type: str          # category type, e.g. "concept"
    title: str         # e.g. "Sun Wukong — Character Overview"
    description: str   # 1-2 sentence description of what this article covers

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "type": self.type,
            "title": self.title,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ThematicArticle:
        return cls(
            path=d.get("path", ""),
            type=d.get("type", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
        )


@dataclass
class ReorganizePlan:
    """Full output of the reorganize phase, passed to compile."""

    topic: str
    articles: list[ThematicArticle]
    canonical_mapping: CanonicalMapping
    entity_index: EntityIndex  # post-resolution

    def to_dict(self) -> dict:
        """Serializable form for the manifest."""
        return {
            "topic": self.topic,
            "articles": [a.to_dict() for a in self.articles],
            "canonical_entities": len(self.canonical_mapping.aliases),
            "filtered_entities": len(self.canonical_mapping.filtered_out),
            "extraction_count": self.entity_index.extraction_count,
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _is_safe_wiki_path(path: str) -> bool:
    """Validate that a path is safe for use under wiki/.

    Mirrors the logic of _under_wiki() in compile.py but without
    needing a KBStore instance — only checks path structure.
    """
    if not path.startswith("wiki/"):
        return False
    # Reject path traversal attempts
    normalized = os.path.normpath(path)
    if not normalized.startswith("wiki" + os.sep):
        return False
    # Must have at least wiki/<type>/<name>.md
    parts = path.split("/")
    if len(parts) < 3 or not parts[-1].endswith(".md"):
        return False
    return True


# ---------------------------------------------------------------------------
# Entity index builder (Section 4.3 of the plan)
# ---------------------------------------------------------------------------

def build_entity_index(store: KBStore) -> EntityIndex:
    """Scan all extraction files and build an entity/topic/concept frequency index.

    Iterates raw files via store.iter_raw_file_meta(), loads each extraction via
    extraction_layer.load(), and aggregates entity names, topics, and concept
    titles into an EntityIndex.

    Skips corrupt/unreadable extraction files with a warning to stderr.
    Raises DeriveError if zero extractions load successfully.
    """
    from kb_ai._errors import DeriveError

    index = EntityIndex()

    for rf in store.iter_raw_file_meta():
        try:
            stored, reason = extraction_layer.load(store, rf.rel_path)
        except Exception as exc:
            print(
                f"[reorganize] skipping {rf.rel_path}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            continue

        if stored is None:
            if reason and reason != "missing":
                print(
                    f"[reorganize] skipping {rf.rel_path}: {reason}",
                    file=sys.stderr,
                    flush=True,
                )
            continue

        extraction = stored.extraction
        source_path = rf.rel_path
        index.extraction_count += 1

        # Entities: list of dicts with {name, type, context}
        for entity in extraction.entities:
            if not isinstance(entity, dict):
                continue
            name = entity.get("name", "")
            if not name:
                continue
            entity_type = entity.get("type", "")
            context = entity.get("context", "")
            occ = EntityOccurrence(
                source_path=source_path,
                name=name,
                entity_type=entity_type,
                context=context,
            )
            index.entities.setdefault(name, []).append(occ)

        # Topics: list of strings
        for topic in extraction.topics:
            if isinstance(topic, str) and topic:
                index.topics.setdefault(topic, []).append(source_path)

        # Concepts: list of dicts with "title" key
        for concept in extraction.concepts:
            if not isinstance(concept, dict):
                continue
            title = concept.get("title", "")
            if not title:
                continue
            index.concepts.setdefault(title, []).append(source_path)

    if index.extraction_count == 0:
        raise DeriveError("no usable extractions for reorganization")

    return index
