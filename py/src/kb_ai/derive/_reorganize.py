"""Entity index, canonical mapping, and reorganization plan data structures.

Phase 1: data structures and entity index builder.
Phase 2: resolve_entities — LLM-based entity name canonicalization.
Phase 3 (plan_aggregation) is in a future feature.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from kb_ai.llm import completion_json
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


# ---------------------------------------------------------------------------
# Entity name resolution (Section 4.3 of the plan)
# ---------------------------------------------------------------------------

_ENUMERATION_RE = re.compile(
    r"(sequence of|steps to|list of|effects of|listed|described|including|such as|for example)",
    re.IGNORECASE,
)

_ENTITY_RESOLVE_SYSTEM = """You are an entity name resolver. Given a list of entity names extracted from multiple documents, identify groups of names that refer to the same entity (aliases, alternate names, titles, abbreviations).

Return JSON:
{
  "groups": [
    {"canonical": "primary name", "aliases": ["alias1", "alias2"], "type": "person|place|thing|organization"}
  ]
}

Rules:
- The canonical name should be the most complete/formal version
- Only group names that clearly refer to the same entity
- Names that appear unique should not be in any group
- Do NOT invent entities not in the input list"""


def _heuristic_filter(names: list[str]) -> tuple[list[str], list[str]]:
    """Split *names* into (kept, filtered_out).

    Filtered out: names longer than 60 characters or matching enumeration-like
    patterns (e.g. "list of ...", "including ...").
    """
    kept: list[str] = []
    filtered_out: list[str] = []
    for name in names:
        if len(name) > 60 or _ENUMERATION_RE.search(name):
            filtered_out.append(name)
        else:
            kept.append(name)
    return kept, filtered_out


def _parse_groups(response: dict) -> dict[str, dict]:
    """Parse LLM response into {canonical: {"aliases": [...], "type": str}}.

    Returns only groups where *canonical* and *aliases* are well-formed.
    """
    result: dict[str, dict] = {}
    groups = response.get("groups", [])
    if not isinstance(groups, list):
        return result
    for group in groups:
        if not isinstance(group, dict):
            continue
        canonical = group.get("canonical", "")
        if not canonical or not isinstance(canonical, str):
            continue
        aliases = group.get("aliases", [])
        if not isinstance(aliases, list):
            continue
        # Keep only non-empty string aliases
        aliases = [a for a in aliases if isinstance(a, str) and a]
        if not aliases:
            continue
        entity_type = group.get("type", "")
        if not isinstance(entity_type, str):
            entity_type = ""
        result[canonical] = {"aliases": aliases, "type": entity_type}
    return result


def _merge_batch_results(
    batch_results: list[dict[str, dict]],
) -> dict[str, dict]:
    """Merge multiple batch results, unioning aliases for same canonical."""
    merged: dict[str, dict] = {}
    for batch in batch_results:
        for canonical, info in batch.items():
            if canonical in merged:
                existing_aliases = set(merged[canonical]["aliases"])
                existing_aliases.update(info["aliases"])
                merged[canonical]["aliases"] = sorted(existing_aliases)
                # Keep type from first batch that set it
                if not merged[canonical]["type"] and info["type"]:
                    merged[canonical]["type"] = info["type"]
            else:
                merged[canonical] = {
                    "aliases": list(info["aliases"]),
                    "type": info["type"],
                }
    return merged


def resolve_entities(
    raw_names: list[str],
    *,
    model: str,
    max_batch_size: int = 500,
) -> CanonicalMapping:
    """Canonicalize entity names via heuristic filter + LLM resolution.

    Steps:
        1. Heuristic filter removes names >60 chars or matching enumeration
           patterns.
        2. Remaining names batched at *max_batch_size* boundary.
        3. Each batch sent to completion_json() for LLM canonicalization.
        4. Results merged across batches (same canonical → aliases unioned).

    Graceful degradation: LLM failure for one batch skips that batch.
    If all batches fail, returns an empty CanonicalMapping (not an error).
    """
    kept, filtered_out = _heuristic_filter(raw_names)

    if not kept:
        return CanonicalMapping(filtered_out=filtered_out)

    # Split into batches
    batches: list[list[str]] = []
    for i in range(0, len(kept), max_batch_size):
        batches.append(kept[i : i + max_batch_size])

    batch_results: list[dict[str, dict]] = []
    for batch in batches:
        names_block = "\n".join(batch)
        messages = [
            {"role": "system", "content": _ENTITY_RESOLVE_SYSTEM},
            {
                "role": "user",
                "content": f"Entity names:\n<names>\n{names_block}\n</names>",
            },
        ]
        try:
            response = completion_json(
                model=model,
                messages=messages,
                max_tokens=4096,
                cache=True,
            )
            parsed = _parse_groups(response)
            batch_results.append(parsed)
        except Exception as exc:
            print(
                f"[reorganize] entity resolution batch failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            # Graceful degradation: skip this batch
            continue

    # Merge batch results
    merged = _merge_batch_results(batch_results)

    # Build CanonicalMapping
    aliases: dict[str, list[str]] = {}
    reverse: dict[str, str] = {}
    for canonical, info in merged.items():
        aliases[canonical] = info["aliases"]
        for alias in info["aliases"]:
            reverse[alias] = canonical

    return CanonicalMapping(
        aliases=aliases,
        reverse=reverse,
        filtered_out=filtered_out,
    )
