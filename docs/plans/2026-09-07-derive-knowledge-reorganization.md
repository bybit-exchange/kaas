# Derive Knowledge Reorganization: Entity Resolution, Aggregation Planning, and Topic-Aware Classify

## 1. Background and Goals

### Why are we doing this?

The derive pipeline's topic filter correctly selects documents relevant to a topic, but the downstream compile phases (classify and write) are entirely topic-unaware. For a pervasive topic like "Sun Wukong" in Journey to the West, the filter selects 90/93 articles, then classify creates per-chapter articles identical to the source KB. Result: $7.19 spent on a near-copy with zero knowledge reorganization.

The root cause is that `derive_kb()` never passes the topic to `compile_fn()`, so classify routes each extraction into per-source-document articles rather than thematic cross-cutting articles.

### What do we want to achieve?

1. **Entity name resolution**: Canonicalize the 1,504 unique entity names (1,390 appearing once) into deduplicated canonical forms so that cross-cutting aggregation can find related material across chapters.
2. **Aggregation planning**: Given entity/topic frequency data, produce a thematic article plan — e.g., "Sun Wukong — Character Overview", "Sun Wukong's Battles", "Sun Wukong and Guanyin".
3. **Topic-aware classify**: A derive-specific classify prompt variant that injects the aggregation plan, routing each extraction into thematic articles instead of per-chapter articles.
4. **Topic-aware routing instead of topic-blind recompile**: When `reorganize=True`, the compile still runs classify + write, but classify uses the topic-aware prompt and the aggregation plan to route extractions into thematic cross-cutting articles rather than per-source-document articles. The compile pipeline itself is unchanged — only the classification decisions differ.

### In scope

- New `reorganize` parameter on `derive_kb()` (defaults `False`, backward-compatible)
- New module `derive/_reorganize.py` with entity resolution and aggregation planning
- New prompt templates: `aggregate-plan.md` and `classify-topical.md`
- Modified `compile_kb()` to accept an optional `aggregation_plan` parameter for derive-specific classify routing
- A `_planned_article_meta` dict in `compile_kb()` so the merge→create fallback path can recover planned title/type
- Tests for all new modules

### Out of scope

- Modifying global extract/classify/write prompts
- Changing Go layer or API contracts
- Synthetic extraction files (Option A from analysis — deferred to a future iteration)
- Changes to the streaming pipeline orchestrator (`commands/pipeline/`)
- Entity resolution as a persistent layer (it's computed per-derive, not stored)

## 2. Current State Analysis

### 2.1 The Derive Pipeline Flow

```
derive_kb(source_kb, topic, ...)
  ├── filter: select_by_topic(catalog, topic, MODE_RECALL)  ← topic used
  ├── resolve documents from selected articles' sources:
  ├── copy documents + extractions to derived/<slug>/
  ├── compile_fn(str(derived_dir), ...)                      ← topic NOT passed
  │     ├── Phase 1: Extract (skipped — extractions cached)
  │     ├── Phase 2a: classify_article() per document        ← topic-blind
  │     ├── Phase 2b: write per article group                ← topic-blind
  │     └── Phase 3: Index
  └── (optional) prune via PRECISION pass
```

### 2.2 Classification System

`classify_article()` receives one `ExtractionResult` at a time, the list of existing articles, the model, and optional categories. It uses `prompts/defaults/classify.md` which says "Prefer merging into existing articles over creating new ones" — purely structural, no topic awareness. Each extraction independently creates/merges.

`ClassificationResult` = `{merge_into: [MergeTarget(path, reason)], create_new: [CreateTarget(path, type, title, reason)]}`.

### 2.3 Extraction Entity Dict Schema

Each entity in `ExtractionResult.entities` is a dict with this schema (from `_FIELD_JSON_SCHEMAS` in `core/extract.py`):

```python
{"name": "entity name", "type": "person|tool|project|team|system", "context": "why notable here"}
```

All three keys are strings. The `name` key is what entity resolution operates on. The `type` key is the entity's domain type (not the article category type). The `context` key explains why the entity is notable in the source document.

### 2.4 Write Phase: merge→create Fallback and Title Loss

When classify returns a `merge_into` target pointing at a file that does not yet exist on disk (and no `create` op established it), the write phase in `_process_article()` falls back to creating the article with:

```python
article_type = path_parts[1] if len(path_parts) > 2 else "concept"
title = Path(art_path).stem.replace("-", " ").title()
```

This path-derived title is a lossy fallback. For planned thematic articles seeded via the aggregation plan, the planned title (e.g., "Sun Wukong — Character Overview") would be lost, replaced by "Sun Wukong Character Overview" (no em-dash, title-cased). More critically, if the path slug doesn't match the intended title (e.g., `wiki/concept/wukong-overview.md` → "Wukong Overview" instead of "Sun Wukong — Character Overview"), the article is permanently mislabeled.

This is the core issue that must be solved for the reorganization pipeline.

### 2.5 dedup_create_new and Its Interaction with Planned Articles

`dedup_create_new()` checks if a `create_new` target's title has ≥70% word overlap with an existing article's title. If so, it converts the create into a merge_into targeting the existing article.

When planned articles are seeded into `existing_articles` before the classify loop, dedup_create_new could convert a create_new into a merge_into targeting a planned-but-not-yet-created article. This is actually the *desired* behavior — it routes toward planned articles. But it means the merge→create fallback path must handle these correctly (see Section 3.2).

### 2.6 Key Constraints

1. `compile_kb()` has no `topic` parameter — adding one is the minimal change needed
2. classify processes ONE extraction at a time — cannot see multiple extractions simultaneously
3. Entity name resolution is a prerequisite for meaningful aggregation
4. Write paths are additive, not retractive — first extraction determines article shape
5. Category freezing: derived KB inherits source's frozen category set
6. Prompt budget: MAX_PROMPT_CHARS (~80K) constrains catalog listings
7. Stub-based testing: `derive_kb` accepts injectable `select`, `compile_fn`, `approve`
8. `_under_wiki()` validates that article paths resolve inside the wiki subtree — any LLM-generated path must pass this check

## 3. Technical Design

### 3.1 Architecture Overview

The approach combines Options C and A from the analysis: use topic-aware classify (Option C) powered by a pre-computed aggregation plan, and route the compile's classify decisions through thematic articles. This avoids synthetic extractions (Option A's provenance complexity) while achieving cross-cutting thematic articles.

```
derive_kb(source_kb, topic, reorganize=True, ...)
  ├── filter: select_by_topic(catalog, topic, MODE_RECALL)
  ├── copy documents + extractions
  ├── ★ NEW: reorganize phase (when reorganize=True)
  │     ├── Step 1: Load all extractions, build entity/topic frequency index
  │     ├── Step 2: Entity name resolution (LLM: canonicalize aliases)
  │     ├── Step 3: Aggregation planning (LLM: plan thematic article structure)
  │     ├── Step 4: Validate all planned paths via _under_wiki()
  │     └── Pass aggregation_plan to compile_fn
  ├── compile_fn(derived_dir, aggregation_plan=plan, topic=topic, ...)
  │     ├── Phase 1: Extract (skipped)
  │     ├── Phase 2a: classify_article_topical() ← NEW prompt, with aggregation plan
  │     │    └── dedup_create_new is SKIPPED (see §3.3)
  │     ├── Phase 2b: write — uses _planned_article_meta dict for merge→create (see §3.2)
  │     └── Phase 3: Index
  └── (optional) prune
```

### 3.2 Preserving Planned Article Metadata Through merge→create (Addresses SEVERE #1)

**The problem**: When planned articles are seeded into `existing_articles`, the topical classify prompt routes extractions as `merge_into` targets pointing at planned articles. Since these articles don't exist on disk yet, the write phase's merge→create fallback derives title/type from the path — losing the planned title and type.

**The solution**: `compile_kb()` builds a `_planned_article_meta: dict[str, dict]` lookup from the aggregation plan before the write phase. This maps `art_path → {"title": ..., "type": ...}` for every planned article. The merge→create fallback path in `_process_article()` checks this lookup before falling back to path-derived values.

Concretely, in `_process_article()`, the existing merge→create block:

```python
# CURRENT (lines ~530-535 of compile.py):
path_parts = art_path.split("/")
article_type = path_parts[1] if len(path_parts) > 2 else "concept"
title = Path(art_path).stem.replace("-", " ").title()
```

becomes:

```python
# NEW:
planned = _planned_article_meta.get(art_path)
if planned:
    article_type = planned["type"]
    title = planned["title"]
else:
    path_parts = art_path.split("/")
    article_type = path_parts[1] if len(path_parts) > 2 else "concept"
    title = Path(art_path).stem.replace("-", " ").title()
```

`_planned_article_meta` is populated only when `aggregation_plan is not None`, from the plan's article list. When `aggregation_plan is None`, it's an empty dict — zero behavior change for the existing path.

This is a narrow change: one new local dict, one if/else at the merge→create site. The `_planned_article_meta` dict is built in the classify phase preamble (same scope as `existing_articles`) and captured by `_process_article`'s closure.

### 3.3 dedup_create_new and Topical Classify (Addresses MEDIUM #3)

**The problem**: When topical classify returns `merge_into` targets pointing at planned-but-not-yet-created articles, `dedup_create_new`'s title-overlap check against `existing_articles` could:
1. Convert a `create_new` for a genuinely new theme into a `merge_into` targeting a planned article with a similar title — desirable.
2. But it could also erroneously merge distinct themes if two planned articles have overlapping title words.

**The decision**: `dedup_create_new` is **skipped** when `aggregation_plan is not None`. Rationale:
- The topical classify prompt already has the aggregation plan and is explicitly told to route to planned articles. It makes the merge/create decision with full context.
- `dedup_create_new` was designed for the topic-blind case where the LLM doesn't see the full article list in context. With the topical prompt, the LLM already sees all planned articles.
- Skipping dedup avoids the interference between dedup's heuristic title-matching and the plan's intentional thematic separation.

In code, the classify loop changes from:
```python
result = classify_article(extraction, ...)
result = dedup_create_new(result, existing_articles)
```
to:
```python
if aggregation_plan is not None:
    result = classify_article_topical(extraction, existing_articles, topic, aggregation_plan, ...)
    # No dedup_create_new — the topical prompt handles routing
else:
    result = classify_article(extraction, ...)
    result = dedup_create_new(result, existing_articles)
```

### 3.4 Entity Resolution: Batching and max_tokens (Addresses SEVERE #2)

**The problem**: The entity list can contain hundreds of names. Without batching and max_tokens, a large list risks truncated JSON responses.

**The solution**:

1. **Heuristic pre-filter**: Remove names where `len(name) > 60` or name matches enumeration-like patterns. This typically removes 80-90% of names (1,390 of 1,504 appear only once and many are enumeration-like descriptions).

2. **Batching**: After filtering, if the remaining names exceed `MAX_PROMPT_CHARS - 4000` characters when joined as a newline-separated list, split into batches of ≤500 names each. Each batch gets its own LLM call. Canonical groups from multiple batches are merged post-hoc (a canonical name appearing in multiple batches gets its aliases unioned).

3. **max_tokens**: Each entity resolution call uses `max_tokens=4096`. With 500 names max per batch, the response JSON needs at most ~100 groups × ~80 chars = ~8K chars, well within 4096 tokens (~16K chars). The batching cap ensures the response fits.

4. **Graceful degradation**: If the LLM call fails (timeout, parse error), the pipeline continues with un-canonicalized entity names. The aggregation plan will still work — the most frequent entity ("Sun Wukong") appears 66 times even without alias merging.

### 3.5 Path Validation for LLM-Generated Planned Article Paths (Addresses MEDIUM #6)

The aggregation plan LLM generates article paths like `wiki/concept/sun-wukong-overview.md`. These paths must pass `_under_wiki()` validation (the same security check compile.py applies to classify output).

**Where validation happens**: In `plan_aggregation()` in `_reorganize.py`, after parsing the LLM response and before returning the list of `ThematicArticle`. Each planned article's path is validated:

```python
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
```

Invalid paths are dropped with a stderr warning. Additionally, `compile_kb()` already applies `_under_wiki()` to every classify output path in the write phase op-building loop, providing a second layer of defense.

### 3.6 Prompt Design

#### `aggregate-plan.md`

Input: topic string, entity frequency table (canonical names with occurrence counts), topic tag frequency table, concept titles.

Output: JSON list of thematic article descriptors. The LLM decides how many articles to create and what themes to organize around. The prompt constrains: 3-15 articles, must use the KB's category types, paths under `wiki/<type>/`.

#### `classify-topical.md`

Extends the base classify prompt concept. Additional context injected:
- `{topic}`: the derive topic string
- `{aggregation_plan_json}`: JSON of the planned thematic articles
- Instructions: "Route this extraction into one or more of the planned thematic articles. Create new articles only if the extraction covers a theme not in the plan."

### 3.7 Cost Analysis

For a "Sun Wukong" derive over 100 chapters:

| Step | LLM Calls | Estimated Cost |
|------|-----------|----------------|
| Entity name resolution | 1 (≤500 names after filter) | ~$0.05 |
| Aggregation planning | 1 | ~$0.10 |
| Topic-aware classify (90 extractions) | 90 | ~$1.80 |
| Write thematic articles (5-15 targets) | 5-15 | ~$1-3 |
| **Total** | ~97-106 | **~$3-5** |

vs. current: $7.19 for 90 near-identical articles. Net: cheaper AND thematic.

## 4. Interface Contracts

### 4.1 Extraction Entity Dict Schema (Addresses MEDIUM #4)

Each entity in `ExtractionResult.entities` follows this exact schema, defined in `_FIELD_JSON_SCHEMAS` in `py/src/kb_ai/core/extract.py`:

```python
# Each element of ExtractionResult.entities is a dict:
{
    "name": str,     # Entity name, e.g. "Sun Wukong" or "齊天大聖（孫悟空）"
    "type": str,     # One of: "person", "tool", "project", "team", "system"
    "context": str,  # Why the entity is notable in this document
}
```

All three keys are always present (the extraction prompt enforces this schema). The `name` key is what entity resolution operates on. Code that reads entity dicts MUST use `.get("name", "")` defensively since the extraction is LLM-generated and could occasionally produce malformed entries.

### 4.2 New Data Structures — `derive/_reorganize.py`

#### `EntityOccurrence`

```python
@dataclass
class EntityOccurrence:
    """One entity mention in one extraction."""
    source_path: str          # e.g. "raw/chapter-58.md"
    name: str                 # raw name from extraction
    entity_type: str          # "person", "tool", etc. from entity dict "type" key
    context: str              # the "context" field from entity dict
```

#### `EntityIndex`

```python
@dataclass
class EntityIndex:
    """Aggregated entity/topic/concept frequency across all extractions."""
    # raw entity name → list of occurrences (before resolution)
    # After resolution, keyed by canonical name
    entities: dict[str, list[EntityOccurrence]]
    # topic_tag → list of source_paths
    topics: dict[str, list[str]]
    # concept_title → list of source_paths
    concepts: dict[str, list[str]]
    # Total extraction count
    extraction_count: int
```

#### `CanonicalMapping`

```python
@dataclass
class CanonicalMapping:
    """Result of LLM entity name resolution."""
    # canonical_name → list of alias strings
    aliases: dict[str, list[str]]
    # alias → canonical_name (reverse lookup, built from aliases)
    reverse: dict[str, str]
    # names that were filtered out as enumeration-like descriptions
    filtered_out: list[str]
```

#### `ThematicArticle`

```python
@dataclass
class ThematicArticle:
    """One planned thematic article from the aggregation plan."""
    path: str          # e.g. "wiki/concept/sun-wukong-character-overview.md"
    type: str          # category type, e.g. "concept"
    title: str         # e.g. "Sun Wukong — Character Overview"
    description: str   # 1-2 sentence description of what this article covers

    def to_dict(self) -> dict:
        return {"path": self.path, "type": self.type,
                "title": self.title, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> ThematicArticle:
        return cls(path=d.get("path", ""), type=d.get("type", ""),
                   title=d.get("title", ""), description=d.get("description", ""))
```

#### `ReorganizePlan`

```python
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
```

### 4.3 Function Signatures — `derive/_reorganize.py`

#### `build_entity_index(store: KBStore) -> EntityIndex`

Scans all files under `extraction/` via `extraction_layer.load()`. For each `ExtractionResult`:
- Iterates `extraction.entities` (list of dicts). For each dict, reads:
  - `entity.get("name", "")` → skip if empty
  - `entity.get("type", "")` → `entity_type`
  - `entity.get("context", "")` → `context`
- Iterates `extraction.topics` (list of strings)
- Iterates `extraction.concepts` (list of dicts with `"title"` key)

**Input**: A `KBStore` pointing at the derived KB (after document+extraction copy).

**Output**: `EntityIndex` with raw (un-canonicalized) entity names.

**Error handling**: Extraction files that fail to parse are skipped with a warning to stderr. If zero extractions load successfully, raises `DeriveError("no usable extractions for reorganization")`.

#### `resolve_entities(raw_names: list[str], *, model: str, max_batch_size: int = 500) -> CanonicalMapping`

**Step 1 — Heuristic filter**: Remove names where `len(name) > 60` or name matches enumeration-like patterns via `re.compile(r"(sequence of|steps to|list of|effects of|listed|described|including|such as|for example)", re.IGNORECASE)`. These go into `filtered_out`.

**Step 2 — Batching**: If remaining names exceed `max_batch_size` items, split into batches of `max_batch_size`. Each batch gets its own LLM call.

**Step 3 — LLM canonicalization per batch**: Send names to `completion_json()`.

**LLM Prompt — System message**:
```
You are an entity name resolver. Given a list of entity names extracted from multiple documents, identify groups of names that refer to the same entity (aliases, alternate names, titles, abbreviations).

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
- Do NOT invent entities not in the input list
```

**LLM Prompt — User message**:
```
Entity names:
<names>
name1
name2
...
</names>
```

**LLM call parameters**: `max_tokens=4096`, `cache=True`

**LLM Response JSON shape**:
```json
{
  "groups": [
    {
      "canonical": "Sun Wukong",
      "aliases": ["Monkey King", "Great Sage Equal to Heaven"],
      "type": "person"
    }
  ]
}
```

**Step 4 — Merge batches**: If multiple batches, merge by canonical name. If the same canonical appears in multiple batches, union their aliases.

**Output**: `CanonicalMapping` built from the merged LLM response.

**Error handling**: If the LLM call fails for a batch, that batch's names remain un-canonicalized (no groups from that batch). If ALL batches fail, return a `CanonicalMapping` with empty `aliases` and `reverse` — the pipeline degrades to un-canonicalized names rather than failing.

#### `_is_safe_wiki_path(path: str) -> bool`

Structural validation of LLM-generated article paths. Checks:
1. Starts with `"wiki/"`
2. `os.path.normpath(path)` still starts with `"wiki" + os.sep` (rejects `wiki/../raw/...`)
3. Has at least 3 parts (`wiki/<type>/<name>.md`) and filename ends with `.md`

Returns `False` for any path that fails. This mirrors `_under_wiki()` in `compile.py` but works without a `KBStore` instance — it validates structure only, not filesystem resolution. The compile.py `_under_wiki()` check provides the authoritative second-layer validation at write time.

#### `plan_aggregation(topic: str, entity_index: EntityIndex, *, categories: list[str], model: str) -> list[ThematicArticle]`

**LLM Prompt** — uses new template `aggregate-plan.md`:

**System message** (template variables listed in §4.8):
```
You are planning the article structure for a topic-focused knowledge base.

Topic: {topic}

The knowledge base contains extractions from {extraction_count} source documents. Below are the most frequent entities, topics, and concepts found across these documents.

Top entities (canonical name — occurrence count):
{entity_frequency}

Top topic tags (tag — occurrence count):
{topic_frequency}

Top concept titles:
{concept_titles}

Available article types: {categories_str}

Plan a set of thematic articles that organize this knowledge around the topic. Each article should synthesize information from multiple source documents into a coherent theme.

Return JSON:
{{
  "articles": [
    {{
      "path": "wiki/<type>/suggested-slug.md",
      "type": "<one of: {categories_str}>",
      "title": "Article Title",
      "description": "1-2 sentence description of what this article should cover"
    }}
  ]
}}

Rules:
- Create 3-15 articles depending on the breadth of available material
- path must start with wiki/ and use the type as subdirectory
- path must use lowercase alphanumeric slugs with hyphens (e.g. wiki/concept/sun-wukong-overview.md)
- Focus on cross-cutting themes, not per-source-document articles
- The main topic entity should get a comprehensive overview article
- Related entities and themes each get their own article when there is enough material (>=3 source documents)
- type must be one of: {categories_str}
```

**User message**: `"Plan the article structure for a knowledge base focused on: {topic}"`

**LLM call parameters**: `max_tokens=4096`, `cache=False` (plan is per-derive, not cacheable)

**LLM Response JSON shape**:
```json
{
  "articles": [
    {
      "path": "wiki/concept/sun-wukong-character-overview.md",
      "type": "concept",
      "title": "Sun Wukong — Character Overview",
      "description": "Comprehensive profile of Sun Wukong including his origins, abilities, personality, and character development throughout the journey"
    },
    {
      "path": "wiki/reference/sun-wukong-battles-and-combat.md",
      "type": "reference",
      "title": "Sun Wukong's Battles and Combat Abilities",
      "description": "Catalog of Sun Wukong's major battles, combat techniques, and the 72 transformations"
    }
  ]
}
```

**Post-processing**: Each article is validated:
- `_is_safe_wiki_path(path)` must return True → invalid paths dropped with stderr warning
- `type` must be in `categories` → invalid types dropped with stderr warning
- `title` must be non-empty → dropped if empty
- 3-15 articles total → if <3 after filtering, raise `DeriveError`; if >15, truncate to 15

**Output**: `list[ThematicArticle]` parsed from the LLM response.

**Error handling**: LLM failure raises `DeriveError("aggregation planning failed: {e}")` — without a plan, reorganization cannot proceed.

#### `reorganize(store: KBStore, topic: str, *, categories: list[str], model: str) -> ReorganizePlan`

Top-level orchestrator:
1. `build_entity_index(store)` → raw index
2. Collect unique entity names from raw index: `list(raw_index.entities.keys())`
3. `resolve_entities(raw_names, model=model)` → canonical mapping
4. Apply canonical mapping to raw index → resolved `EntityIndex`:
   - For each raw name that has a canonical mapping, merge its occurrences under the canonical name
   - Names without a mapping keep their raw key
5. `plan_aggregation(topic, resolved_index, categories=categories, model=model)` → articles
6. Return `ReorganizePlan(topic, articles, canonical_mapping, resolved_index)`

### 4.4 Function Signatures — Modified `core/classify.py`

#### New: `classify_article_topical()`

```python
def classify_article_topical(
    extraction: ExtractionResult,
    existing_articles: list[ArticleMeta],
    topic: str,
    aggregation_plan: list[dict],
    *,
    model: str = "claude-sonnet-4-6",
    categories: list[str] | None = None,
) -> ClassificationResult:
```

Uses new prompt template `classify-topical` instead of `classify`. Otherwise follows the same pattern as `classify_article()`: builds user message from extraction, fits articles to budget, calls `completion_json()`.

**LLM System message** (from `classify-topical.md`):
```
You are a knowledge base classifier for a topic-focused knowledge base about: {topic}

Instead of creating one article per source document, organize knowledge into thematic articles that cut across multiple sources.

Planned thematic articles:
{aggregation_plan_json}

Existing articles:
{{ARTICLES_PLACEHOLDER}}

Return JSON:
{{{{
  "merge_into": [
    {{{{"path": "wiki/path/to/article.md", "reason": "why merge here"}}}}
  ],
  "create_new": [
    {{{{"path": "wiki/category/suggested-name.md", "type": "<one of: {categories_str}>", "title": "Article Title", "reason": "why new"}}}}
  ]
}}}}

Rules:
- Route this extraction into one or more of the planned thematic articles via merge_into
- Prefer merging into planned articles over creating new ones
- Create a new article only if the extraction covers a theme not represented in the plan
- An extraction may be routed to multiple thematic articles if it covers multiple themes
- type must be one of: {categories_str}
- path must start with wiki/ and use the type as subdirectory (e.g. wiki/{categories[0]}/)
{category_definitions}
Return ONLY valid JSON.
```

**LLM call parameters**: `max_tokens=2048`, `cache=True` (same as classify_article)

**Return type**: `ClassificationResult` — same as `classify_article()`. No change to the downstream write phase contract.

#### New: `_render_topical_classify_system()`

```python
def _render_topical_classify_system(
    categories: list[str],
    topic: str,
    aggregation_plan: list[dict],
) -> str:
    """Render the topical classify system template, articles placeholder unfilled."""
    import json
    plan_json = json.dumps(aggregation_plan, ensure_ascii=False, indent=2)
    return default_registry().get("classify-topical").render(
        categories_str=", ".join(categories),
        categories=categories,
        category_definitions=category_definitions_block(categories),
        topic=topic,
        aggregation_plan_json=plan_json,
    )
```

### 4.5 Function Signatures — Modified `commands/compile.py`

#### `compile_kb()` — new optional parameters

```python
def compile_kb(
    data_dir: str,
    *,
    extract_model: str = "claude-sonnet-4-6",
    compile_model: str = "claude-sonnet-4-6",
    write_model: str = "claude-sonnet-4-6",
    categories: list | None = None,
    topic_index_min_articles: int = 3,
    summary_max_chars: int = SUMMARY_MAX_CHARS,
    people_cfg: list | None = None,
    workers: int = 0,
    extract_only: bool = False,
    extract_strategy: str = STRATEGY_CHUNKED,
    summarize_model: str = "",
    # NEW: when non-None, Phase 2a uses topic-aware classify
    aggregation_plan: list[dict] | None = None,
    topic: str = "",
) -> dict:
```

**Behavior when `aggregation_plan is not None`**:

1. **Before the classify loop** — Seed `existing_articles` and build `_planned_article_meta`:
```python
_planned_article_meta: dict[str, dict] = {}
if aggregation_plan is not None:
    for planned in aggregation_plan:
        p = planned.get("path", "")
        t = planned.get("title", "")
        tp = planned.get("type", "")
        desc = planned.get("description", "")
        if p and t:
            existing_articles.append(ArticleMeta(
                title=t, path=p, summary=desc, type=tp,
            ))
            _planned_article_meta[p] = {"title": t, "type": tp}
```

2. **In the classify loop** — Use `classify_article_topical()` and skip `dedup_create_new`:
```python
if aggregation_plan is not None:
    result = classify_article_topical(
        extraction, existing_articles, topic, aggregation_plan,
        model=compile_model, categories=categories)
    # No dedup_create_new — topical prompt handles routing
else:
    result = classify_article(extraction, existing_articles,
                              model=compile_model, categories=categories)
    result = dedup_create_new(result, existing_articles)
```

3. **Skip classify cache** when `aggregation_plan is not None`:
```python
if aggregation_plan is not None:
    # Skip cache: the topical classify prompt incorporates the aggregation plan
    # which varies per derive run. Cache key would need to include the plan hash;
    # simpler to skip since reorganize runs are infrequent.
    pass
elif cached is not None:
    # existing cache path...
```

4. **In `_process_article()` merge→create fallback** — Consult `_planned_article_meta` (captured via closure):
```python
# Existing: no creates and article doesn't exist → merge→create fallback
planned = _planned_article_meta.get(art_path)
if planned:
    article_type = planned["type"]
    title = planned["title"]
else:
    path_parts = art_path.split("/")
    article_type = path_parts[1] if len(path_parts) > 2 else "concept"
    title = Path(art_path).stem.replace("-", " ").title()
```

**Behavior when `aggregation_plan is None`** (default): `_planned_article_meta` is an empty dict. All four sites fall through to existing behavior. Zero code path changes.

### 4.6 Function Signatures — Modified `derive/__init__.py`

#### `derive_kb()` — new optional parameter

```python
def derive_kb(
    source_kb: str,
    topic: str,
    *,
    slug: str | None = None,
    force: bool = False,
    prune: bool = False,
    select_from: str = SELECT_FROM_ARTICLES,
    model: str,
    extract_strategy: str = STRATEGY_CHUNKED,
    summarize_model: str = "",
    select: Selector | None = None,
    compile_fn: Callable[..., dict] | None = None,
    approve: Callable[[DeriveReport], bool] | None = None,
    # NEW
    reorganize: bool = False,
) -> DeriveReport:
```

**Behavior when `reorganize=True`**:
1. After `copy_documents` + `flush()`, before compile:
   - Import: `from kb_ai.derive._reorganize import reorganize as run_reorganize`
   - Create store: `derived_store = KBStore(str(derived_dir), read_only=True)`
   - Run: `plan = run_reorganize(derived_store, topic, categories=source_categories, model=model)`
   - Set report field: `report.reorganize_plan = plan.to_dict()`
   - Flush manifest (so plan is recorded before compile)
2. Pass to compile_fn:
   ```python
   compile_result = compile_fn(
       str(derived_dir), extract_model=model, compile_model=model, write_model=model,
       extract_strategy=extract_strategy, summarize_model=summarize_model,
       categories=source_store.load_config().get("categories"),
       aggregation_plan=[a.to_dict() for a in plan.articles],
       topic=topic,
   )
   ```

**Behavior when `reorganize=False`** (default): No new code path executes. `compile_fn` called exactly as before (no `aggregation_plan` or `topic` kwargs).

### 4.7 Modified `derive/_types.py` — DeriveReport

```python
@dataclass
class DeriveReport:
    # ... all existing fields unchanged ...
    
    # NEW: present only when reorganize=True, None otherwise
    reorganize_plan: dict | None = None
```

This is additive. `reorganize_plan` defaults to `None`. Existing code that reads DeriveReport sees no change.

### 4.8 Manifest Changes

When `reorganize=True`, `_manifest_payload()` includes a new optional key:

```python
def _manifest_payload(report, ...) -> dict:
    payload = {
        # ... all existing keys unchanged ...
    }
    if report.reorganize_plan is not None:
        payload["reorganize_plan"] = report.reorganize_plan
    return payload
```

Manifest JSON (when `reorganize=True`):
```json
{
  "schema_version": 1,
  "source_kb": "...",
  "topic": "...",
  "reorganize_plan": {
    "topic": "Sun Wukong",
    "articles": [
      {"path": "wiki/concept/sun-wukong-overview.md", "type": "concept", "title": "Sun Wukong — Character Overview", "description": "..."}
    ],
    "canonical_entities": 42,
    "filtered_entities": 1348,
    "extraction_count": 100
  },
  "... existing keys ..."
}
```

When `reorganize=False`, the `reorganize_plan` key is absent (not null). `schema_version` stays at 1: additive keys are forward-compatible.

### 4.9 Prompt Template Variables

#### `aggregate-plan.md`

| Variable | Type | Description |
|----------|------|-------------|
| `{topic}` | str | The derive topic string |
| `{extraction_count}` | int | Number of extractions scanned |
| `{entity_frequency}` | str | Rendered multi-line: `"canonical_name — N occurrences"` per line, top 50 by count |
| `{topic_frequency}` | str | Rendered multi-line: `"tag — N occurrences"` per line, top 30 by count |
| `{concept_titles}` | str | Rendered multi-line: concept titles, top 30 by frequency |
| `{categories_str}` | str | Comma-joined category names |

#### `classify-topical.md`

| Variable | Type | Description |
|----------|------|-------------|
| `{topic}` | str | The derive topic string |
| `{aggregation_plan_json}` | str | JSON array of planned articles with path/type/title/description |
| `{categories_str}` | str | Comma-joined category names |
| `{categories[0]}` | str | First category (for example path) |
| `{category_definitions}` | str | Category definition block (from existing `category_definitions_block()`) |
| `{ARTICLES_PLACEHOLDER}` | str | Replaced at runtime with existing articles JSON (same as `classify.md`) |

## 5. Implementation Steps

### Phase 1: Data Structures and Entity Index (no LLM)

**Files to create/modify:**
- Create `py/src/kb_ai/derive/_reorganize.py`
- Modify `py/src/kb_ai/derive/_types.py` (add `reorganize_plan` to `DeriveReport`)

**Steps:**
1. Define `EntityOccurrence`, `EntityIndex`, `CanonicalMapping`, `ThematicArticle`, `ReorganizePlan` dataclasses in `_reorganize.py`
2. Define `_is_safe_wiki_path()` utility in `_reorganize.py`
3. Implement `build_entity_index(store)`:
   - Iterate raw files via `store.iter_raw_file_meta()` to get extraction paths
   - For each, call `extraction_layer.load(store, rf.rel_path)` — skip failures
   - For each entity dict in `extraction.entities`: use `entity.get("name", "")`, `entity.get("type", "")`, `entity.get("context", "")` — skip entries with empty name
   - For each concept dict in `extraction.concepts`: use `concept.get("title", "")` — skip entries with empty title
   - For each topic tag in `extraction.topics`: collect as-is (topics are plain strings)
   - Return `EntityIndex` with raw names
4. Add `reorganize_plan: dict | None = None` to `DeriveReport` dataclass in `_types.py`
5. Write unit tests: `py/tests/test_reorganize_index.py`
   - Test `build_entity_index` with fixture extractions
   - Test entity dict defensiveness: missing `name` key, empty name, non-dict entries in entities list
   - Test edge cases: empty KB, corrupt extraction files

**Dependencies:** None. Can be implemented independently.
**Verification:** `pytest tests/test_reorganize_index.py -v` passes.

### Phase 2: Entity Name Resolution (LLM call)

**Files to modify:**
- `py/src/kb_ai/derive/_reorganize.py` (add `resolve_entities`)

**Steps:**
1. Implement heuristic filter: remove names > 60 chars, or matching `re.compile(r"(sequence of|steps to|list of|effects of|listed|described|including|such as|for example)", re.IGNORECASE)`.
2. Implement `resolve_entities(raw_names, model, max_batch_size=500)`:
   - Apply heuristic filter → filtered_out list
   - Split remaining names into batches of `max_batch_size`
   - Per batch: call `completion_json()` with entity resolution prompt, `max_tokens=4096`, `cache=True`
   - Parse each batch response: iterate `response["groups"]`, build per-batch `CanonicalMapping`
   - Merge batch results: union aliases for same canonical name across batches
   - On per-batch LLM failure: log warning, skip that batch (graceful degradation)
   - If all batches fail: return empty `CanonicalMapping` (no aliases, no reverse)
3. Write unit tests: `py/tests/test_reorganize_entities.py`
   - Mock `completion_json` to return known canonicalization
   - Test heuristic filter: long names, enumeration-like patterns
   - Test batching: verify names are split at `max_batch_size` boundary
   - Test batch merging: same canonical across two batches → aliases unioned
   - Test `max_tokens=4096` is passed to `completion_json`
   - Test graceful degradation: LLM failure → empty mapping

**Dependencies:** Phase 1 (uses `CanonicalMapping` dataclass).
**Verification:** `pytest tests/test_reorganize_entities.py -v` passes.

### Phase 3: Aggregation Planning (LLM call) and Prompt Templates

**Files to create/modify:**
- `py/src/kb_ai/derive/_reorganize.py` (add `plan_aggregation`, `reorganize`)
- Create `py/src/kb_ai/prompts/defaults/aggregate-plan.md`

**Steps:**
1. Create `aggregate-plan.md` prompt template with variables from §4.9
2. Implement `plan_aggregation(topic, entity_index, categories, model)`:
   - Build frequency tables: top 50 entities by occurrence count, top 30 topics, top 30 concepts
   - Render `aggregate-plan` prompt via `default_registry().get("aggregate-plan").render(...)`
   - Call `completion_json()` with rendered prompt, `max_tokens=4096`
   - Parse response `articles` array into `list[ThematicArticle]`
   - Validate each: `_is_safe_wiki_path(path)`, type in categories, non-empty title
   - Drop invalid entries with stderr warnings
   - Clamp to 15 articles max (truncate), raise `DeriveError` if <3 after filtering
3. Implement `reorganize(store, topic, categories, model)`:
   - Call `build_entity_index(store)`
   - Collect unique names: `list(raw_index.entities.keys())`
   - Call `resolve_entities(names, model=model)`
   - Apply mapping: for each raw name with a canonical, merge its occurrences under canonical key
   - Call `plan_aggregation(topic, resolved_index, categories=categories, model=model)`
   - Return `ReorganizePlan`
4. Write unit tests: `py/tests/test_reorganize_plan.py`
   - Mock `completion_json` for aggregation planning
   - Test validation: bad paths rejected (traversal, missing wiki/ prefix, no .md)
   - Test validation: invalid types dropped
   - Test validation: too few articles → DeriveError
   - Test validation: >15 articles → truncated to 15
   - Test `reorganize()` end-to-end with mocked LLM

**Dependencies:** Phase 2 (uses `resolve_entities`).
**Verification:** `pytest tests/test_reorganize_plan.py -v` passes.

### Phase 4: Topic-Aware Classify Prompt and Function

**Files to create/modify:**
- Create `py/src/kb_ai/prompts/defaults/classify-topical.md`
- Modify `py/src/kb_ai/core/classify.py` (add `classify_article_topical`, `_render_topical_classify_system`)

**Steps:**
1. Create `classify-topical.md` prompt template per §4.4. Must use the same `{{ARTICLES_PLACEHOLDER}}` convention as `classify.md` for runtime article injection.
2. Add `_render_topical_classify_system(categories, topic, aggregation_plan)` in `classify.py`:
   - Load `classify-topical` from registry
   - Render with `categories_str`, `categories[0]`, `category_definitions`, `topic`, `aggregation_plan_json`
   - Return system template with `{ARTICLES_PLACEHOLDER}` still unfilled
3. Add `classify_article_topical()`:
   - Same flow as `classify_article()`: build user message, fit articles to budget, call completion_json
   - Uses `_render_topical_classify_system()` instead of `_render_classify_system()`
   - `max_tokens=2048` (same as classify_article)
   - Returns `ClassificationResult` (same type, same downstream contract)
4. Write unit tests: `py/tests/test_classify_topical.py`
   - Mock `completion_json` to verify the topical prompt is sent
   - Verify `topic` and `aggregation_plan_json` appear in the system message
   - Verify that planned articles appear in articles listing
   - Verify backward compatibility: `classify_article()` is unchanged (not modified)

**Dependencies:** Phase 3 (needs `ThematicArticle` type for test fixtures). The prompt template and function can be developed in parallel with Phase 3.
**Verification:** `pytest tests/test_classify_topical.py -v` passes; existing classify tests still pass.

### Phase 5: Wire into compile_kb and derive_kb

**Files to modify:**
- `py/src/kb_ai/commands/compile.py` (add `aggregation_plan`, `topic` params, `_planned_article_meta`, skip dedup)
- `py/src/kb_ai/derive/__init__.py` (add `reorganize` param, wire reorganize phase, update manifest)

**Steps:**
1. Modify `compile_kb()` signature: add `aggregation_plan: list[dict] | None = None` and `topic: str = ""`
2. Add import at top of compile.py: `from kb_ai.core.classify import classify_article_topical`
3. Before the classify loop, build `_planned_article_meta` dict and seed `existing_articles` (per §4.5)
4. In the classify loop:
   - When `aggregation_plan is not None`: skip cache lookup, call `classify_article_topical`, skip `dedup_create_new`
   - When `aggregation_plan is None`: existing path unchanged
5. In `_process_article()`, modify the merge→create fallback to consult `_planned_article_meta` (per §3.2)
   - `_planned_article_meta` is captured by the closure — it's defined in the enclosing scope of `_process_article`
6. Modify `derive_kb()` signature: add `reorganize: bool = False`
7. In `derive_kb()`, after copy_documents + flush, before compile:
   - When `reorganize=True`: run `run_reorganize()`, set `report.reorganize_plan`, flush, pass plan to compile_fn
   - When `reorganize=False`: no change
8. Update `_manifest_payload()` to include `reorganize_plan` when present (per §4.8)
9. Write integration tests: `py/tests/test_derive_reorganize.py`
   - Test `derive_kb(reorganize=True)` with mocked select + mocked compile_fn
   - Verify `aggregation_plan` kwarg is passed to compile_fn
   - Verify `topic` kwarg is passed to compile_fn
   - Verify manifest includes `reorganize_plan`
   - Test `derive_kb(reorganize=False)` still works identically to before
   - Test that `_planned_article_meta` correctly provides title/type for merge→create fallback

**Dependencies:** Phases 3 and 4.
**Verification:** `pytest tests/test_derive_reorganize.py -v` passes.

### Phase 6: End-to-End Test and Existing Test Verification

**Steps:**
1. Run all existing derive tests to confirm backward compatibility:
   ```bash
   cd py && python -m pytest tests/test_derive_kb.py tests/test_derive_filter.py tests/test_commands_derive.py -v
   ```
2. Run existing classify tests:
   ```bash
   cd py && python -m pytest tests/test_classify*.py -v
   ```
3. Run all new tests:
   ```bash
   cd py && python -m pytest tests/test_reorganize_index.py tests/test_reorganize_entities.py tests/test_reorganize_plan.py tests/test_classify_topical.py tests/test_derive_reorganize.py -v
   ```
4. Run the full test suite:
   ```bash
   cd py && python -m pytest --tb=short
   ```
5. Verify: `reorganize=False` (default) exercises no new code paths — all existing tests pass without modification
6. Verify: existing `classify_article()` function is not modified — only new functions added

**Dependencies:** Phase 5.
**Verification:** Full test suite green.

## 6. Risks and Mitigations

### 6.1 Planned Article Title/Type Loss in merge→create (ADDRESSED — was SEVERE #1)

**Risk**: Planned articles seeded into `existing_articles` get `merge_into` references from topical classify, but the write phase's merge→create fallback derives title/type from the path stem.

**Mitigation**: `_planned_article_meta` dict preserves planned title/type through the classify→write pipeline. The fallback path checks this dict first. The dict is populated in the classify phase preamble from `aggregation_plan` and captured by `_process_article`'s closure.

**Verification**: Unit test in Phase 5 creates a planned article, sends a merge_into targeting it, and verifies the created article uses the planned title — not the path-derived one.

### 6.2 Entity Resolution Truncation (ADDRESSED — was SEVERE #2)

**Risk**: Large entity lists cause truncated JSON responses from the LLM.

**Mitigation**: Three-layer defense:
1. Heuristic pre-filter removes 80-90% of names (enumeration-like, >60 chars)
2. Remaining names batched at ≤500 per call
3. `max_tokens=4096` specified explicitly on every call
4. Graceful degradation if LLM fails — pipeline continues with un-canonicalized names

### 6.3 dedup_create_new Interference (ADDRESSED — was MEDIUM #3)

**Risk**: `dedup_create_new`'s title-overlap heuristic could redirect create_new targets away from intended thematic articles when planned articles are in `existing_articles`.

**Mitigation**: `dedup_create_new` is skipped entirely when `aggregation_plan is not None`. The topical classify prompt already has the full plan in context and makes explicit merge/create decisions.

### 6.4 Path Traversal in LLM-Generated Paths (ADDRESSED — was MEDIUM #6)

**Risk**: The aggregation plan LLM generates paths like `wiki/../raw/exploit.md`.

**Mitigation**: Two layers:
1. `_is_safe_wiki_path()` in `plan_aggregation()` validates path structure before returning the plan
2. `_under_wiki()` in compile.py's write phase validates every path against the actual filesystem before any write

### 6.5 Merge-Order Dependency (Medium Risk)

**Risk**: The first extraction to target a thematic article determines its initial structure. If a low-quality extraction arrives first, the article's structure is suboptimal.

**Mitigation**: The aggregation plan seeds thematic articles into `existing_articles` with descriptive summaries *before* any classify call. The first extraction to hit a planned article creates it with title and type from `_planned_article_meta`, not from the extraction. The description from the plan guides the write phase's `create_new_article()` call.

### 6.6 Aggregation Plan Quality (Medium Risk)

**Risk**: The LLM might produce a poor thematic structure.

**Mitigation**: Validation constrains the plan to 3-15 articles with valid paths and types. The classify step can still create new articles beyond the plan. The plan is a routing suggestion, not a hard constraint.

### 6.7 Backward Compatibility (Low Risk)

**Risk**: Changes to `compile_kb()` or `classify.py` break existing non-derive usage.

**Mitigation**:
- `compile_kb(aggregation_plan=None)` is the default — `_planned_article_meta` is `{}`, dedup runs, cache runs, classify_article used
- `classify_article()` is not modified — `classify_article_topical()` is a new function
- `derive_kb(reorganize=False)` is the default — no new code path executes
- `classify.md` prompt is not modified — `classify-topical.md` is a new file
- `DeriveReport.reorganize_plan` defaults to `None` — existing code sees no change

### 6.8 Classify Cache (Low Risk)

**Risk**: Cache keying doesn't account for the aggregation plan.

**Mitigation**: Classify cache is skipped entirely when `aggregation_plan is not None`. Reorganize runs are infrequent (one-time per derive topic). The cache key would need to incorporate `topic` + plan hash; skipping is simpler and correct.

### 6.9 Prompt Budget Overflow (Low Risk)

**Risk**: Aggregation plan JSON in classify-topical.md pushes prompt over MAX_PROMPT_CHARS.

**Mitigation**: Plan is 3-15 articles × ~200 chars = ~3K max. Existing budget is ~80K. The plan JSON is part of the system template skeleton, reducing article budget by ~3K — ample headroom.

### 6.10 Cost Overshoot (Low Risk)

**Risk**: Entity resolution and aggregation planning add LLM cost.

**Mitigation**: 2 additional calls (~$0.15 total). The thematic routing produces 5-15 articles instead of 90, so the write phase costs ~$1-3 instead of ~$5. Net cost is lower.
