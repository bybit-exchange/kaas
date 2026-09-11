# Derive Pipeline Quality Fix: Multi-Round Voting and Language Directives

## 1. Background and Goals

### Why
Two quality issues plague the derive pipeline:

1. **Filter selection randomness** — Claude Sonnet 4 is non-deterministic even at temperature=0. Five identical derive runs produce 23–41 articles with a 52% flip rate on borderline articles. The `seed` parameter is silently discarded by Anthropic's API. This instability propagates downstream: irrelevant chapters get classified into off-topic standalone articles.

2. **Language inconsistency** — Only `summarize.md` has a language directive. When extracting Chinese source documents, the LLM defaults to English for concept names, summaries, and claims. The write phase then sees mixed Chinese/English input and picks a language randomly per article, producing 25–49% English-body articles from an all-Chinese corpus.

### Goals
- Stabilise filter selection to ~78% cross-run agreement (from 52%) via 3-round voting with ≥2/3 threshold.
- Ensure all pipeline outputs match the source document language by adding language directives to `extract.md`, `extract-types.md`, `_create_system()`, `merge-rewrite.md`, `merge-section.md`, and `merge-diff.md`.

### Scope
- **In scope**: `_filter.py` voting, `derive_kb()` config propagation, CLI/daemon entry points, six prompt changes, associated tests.
- **Out of scope**: `merge-section-router.md`, `classify.md`, `classify-topical.md` (these either operate on already-corrected input or are language-neutral JSON routers). Scored selection (empirically rejected — see diagnosis). PRECISION pass voting (uses the same `select_by_topic`, gets voting for free).

## 2. Current State Analysis

### Filter Path
1. `derive_kb()` creates a `select` closure binding `model` → calls `select_by_topic(catalog, topic, mode, model=model)`.
2. `select_by_topic()` packs catalog into batches, calls `completion_json()` once per batch, unions results.
3. `Selector` type alias: `Callable[[list[ArticleMeta], str, str], SelectionResult]` — the `model` is bound via closure. New `filter_rounds` must follow the same closure-binding pattern.

### Prompt System
- Prompt files live in `py/src/kb_ai/prompts/defaults/`.
- `extract.md` and `extract-types.md` feed `extract_prompt_version()` — any content change to either file invalidates all cached extractions (known, acceptable side-effect). `extract-types.md` is hashed through `_render_type_split_prompt()` which loads the template and substitutes field subsets, so a content change to the template propagates through all rendered variants.
- `merge-rewrite.md`, `merge-section.md`, `merge-diff.md` feed `write_prompt_version()` via `_write_stage_renderings()` — changes invalidate write-phase cache.
- `_create_system()` is code-built, also hashed by `_write_stage_renderings()`.
- `_GROUNDING` is appended to all write prompts. The language directive goes per-prompt (not into `_GROUNDING`) because the wording differs: extraction says "field values", write prompts say "article" or "content values", and adding to `_GROUNDING` would also affect `merge-section-router.md` (a JSON router).

### Config Propagation
- No `derive_*` config keys exist yet. The pattern is: `derive_kb()` receives individual kwargs, callers (`commands/derive.py`, `server_daemon.py`) read from their own source (argparse / JSON payload / env var).
- Environment-variable pattern in the codebase: `KB_*` or `LLM_*` prefix, warning-on-invalid, fallback-to-default.

## 3. Technical Design

### 3.1 Multi-Round Voting Architecture

**Per-batch N-round voting**, not per-catalog:
- Each batch is independently called N times (N = `filter_rounds`, default 3).
- For each path in a batch, count how many rounds selected it.
- Retain the path only if `votes >= threshold` where `threshold = ceil(N * 2 / 3)`.
- Union across batches as before (a path appears in exactly one batch, so there is no cross-batch conflict).

**Threshold formula**: `threshold = ceil(N * 2 / 3)` — for N=1: 1, N=3: 2, N=5: 4. This is the ≥2/3 supermajority from the diagnosis. An inline comment will clarify: `# supermajority: at least ⌈2N/3⌉ rounds must select a path`.

**`dropped_invented` semantics — deduplicated across rounds**: To preserve backward compatibility of this field's meaning ("number of unique invented paths"), invented paths are collected into a `set` across all rounds within a batch. The final `dropped_invented` count reflects unique invented paths across the entire `select_by_topic()` call, not total occurrences. This avoids inflating the count with `filter_rounds` and ensures the manifest's `dropped_invented_paths` field, CLI response, and daemon response remain comparable across runs with different `filter_rounds` values.

**Error handling**: All-or-nothing per batch. If any round in a batch fails, raise `DeriveError` immediately. Rationale: partial rounds produce biased counts (a path that would have been selected in the failed round loses a vote it deserved).

**Cost**: 3× the current filter LLM cost. For a 93-article catalog in 1 batch, this is 3 calls instead of 1. Acceptable per diagnosis.

### 3.2 Language Directive Placement

Add a language-matching instruction to each prompt, using `summarize.md`'s wording as reference:

| Target | Directive text |
|--------|---------------|
| `extract.md` | "Write all extracted field values in the same language as the source document." |
| `extract-types.md` | "Write all extracted field values in the same language as the source document." |
| `_create_system()` | "Write the article in the same language as the source documents provided." |
| `merge-rewrite.md` | "Write in the same language as the source documents and the existing article." |
| `merge-section.md` | "Write in the same language as the existing section content." |
| `merge-diff.md` | "Write all patch content values in the same language as the source documents and the existing article." |

Each wording is tailored to what that prompt receives as input, so the LLM knows which content's language to match. `extract-types.md` uses the same wording as `extract.md` because it performs the same extraction task (type-split variant for >3 chunks). `merge-diff.md` says "patch content values" because its output is a JSON array of patches whose `content` fields contain natural language text.

### 3.3 Config Flow

```
CLI (--filter-rounds)  ──→  derive_kb(filter_rounds=N)  ──→  closure binds filter_rounds
Daemon (inner["filter_rounds"])  ──→  derive_kb(filter_rounds=N)  ──→  select_by_topic(..., filter_rounds=N)
```

No `kaas.json` config key needed — this is a runtime tuning knob (like `model`), not a per-KB property. It flows the same way as `model`: CLI flag → `derive_kb()` kwarg → closure.

**Validation**: `select_by_topic()` validates `filter_rounds >= 1` and raises `ValueError` for invalid values. CLI and daemon callers pass `None` when unset and let `derive_kb()` apply the default of 3. This ensures `filter_rounds=0` propagates to `select_by_topic()` and raises `ValueError`, rather than being silently coerced to 3.

## 4. Interface Contracts

### 4.1 Config Schema Changes

#### CLI (`commands/derive.py` — `build_parser()`)

**New flag**: `--filter-rounds`

```python
parser.add_argument("--filter-rounds", type=int, default=None,
                    help="number of LLM voting rounds for the topic filter "
                         "(default: 3; 1 = no voting)")
```

- Type: `int | None` (argparse default is `None`)
- Valid range: ≥ 1, enforced at `select_by_topic()` level
- Environment variable fallback: none

**Propagation** in `run_derive()`:
```python
# Pass only when explicitly provided; let derive_kb() apply its default of 3.
kw = {}
if args.filter_rounds is not None:
    kw["filter_rounds"] = args.filter_rounds
report = derive_kb(..., **kw)
```

This avoids the `or 3` pattern that would swallow `filter_rounds=0`. When `filter_rounds` is `None` (unset), `derive_kb()` uses its default of 3. When explicitly set to 0, it flows through to `select_by_topic()` which raises `ValueError`.

#### Daemon (`server_daemon.py` — `_handle_derive()`)

**New payload field**: `filter_rounds`

```json
{
  "payload": {
    "kb_dir": "string (required)",
    "topic": "string (required)",
    "filter_rounds": "integer (optional, default: 3, min: 1)"
  }
}
```

**Propagation** in `_handle_derive()`:
```python
# After existing inner.get() calls, before derive_kb():
derive_kw = {}
if inner.get("filter_rounds") is not None:
    derive_kw["filter_rounds"] = inner["filter_rounds"]
# ...
report = derive_kb(..., **derive_kw)
```

Same pattern as the CLI: pass-through only when explicitly set, so `0` raises `ValueError` and `None`/absent uses the default.

#### `derive_kb()` signature change

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
    filter_rounds: int = 3,        # ← NEW
    select: Selector | None = None,
    compile_fn: Callable[..., dict] | None = None,
    approve: Callable[[DeriveReport], bool] | None = None,
    reorganize: bool = False,
) -> DeriveReport:
```

- `filter_rounds` defaults to 3
- When `select` is None (the normal path), the closure binds `filter_rounds` into `select_by_topic`
- When `select` is provided (tests), `filter_rounds` is ignored — the caller controls the stub

### 4.2 Function Signature Changes

#### `select_by_topic()` — new `filter_rounds` kwarg

```python
# BEFORE
def select_by_topic(catalog: list[ArticleMeta], topic: str, mode: str,
                    *, model: str) -> SelectionResult:

# AFTER
def select_by_topic(catalog: list[ArticleMeta], topic: str, mode: str,
                    *, model: str, filter_rounds: int = 3) -> SelectionResult:
```

- `filter_rounds` is keyword-only, default 3
- Validates `filter_rounds >= 1`; raises `ValueError` for invalid values
- `Selector` type alias is **unchanged** — `filter_rounds` is bound in the closure, not exposed through `Selector`

#### `Selector` type alias — **UNCHANGED**

```python
Selector = Callable[[list[ArticleMeta], str, str], SelectionResult]
```

#### `SelectionResult` — **UNCHANGED**

```python
@dataclass(frozen=True)
class SelectionResult:
    paths: list[str]
    batches: int
    dropped_invented: int
    skipped: list[Skipped]
```

No new fields. The `dropped_invented` counter reflects **unique invented paths** across all rounds (deduplicated via a set). This preserves the pre-voting semantics of the field.

### 4.3 Prompt Template Diffs

All diffs below show the **complete tail** of each file / code block so insertion points are unambiguous.

#### `extract.md` — Add language directive

**File**: `py/src/kb_ai/prompts/defaults/extract.md`

**Before** (last 7 lines of the file):
```markdown
- Extract only what is explicitly stated or clearly implied
- topic tags: lowercase, hyphenated (e.g. "api-gateway")
- Empty array for fields with no relevant data
- An enumeration you record is complete: every member, in document order, never abridged
- For meeting transcripts: focus on Q3 (decisions) and Q2 (entities)
- For documents: focus on Q1 (concepts), Q4 (claims) and Q5 (enumerations)

Return ONLY valid JSON, no markdown fencing.
```

**After** (last 8 lines — one rule added):
```markdown
- Extract only what is explicitly stated or clearly implied
- topic tags: lowercase, hyphenated (e.g. "api-gateway")
- Empty array for fields with no relevant data
- An enumeration you record is complete: every member, in document order, never abridged
- For meeting transcripts: focus on Q3 (decisions) and Q2 (entities)
- For documents: focus on Q1 (concepts), Q4 (claims) and Q5 (enumerations)
- Write all extracted field values in the same language as the source document

Return ONLY valid JSON, no markdown fencing.
```

**Change**: Insert `- Write all extracted field values in the same language as the source document` as a new line after the `- For documents:` rule and before the blank line preceding `Return ONLY valid JSON`.

**Impact**: `extract_prompt_version()` hash changes → all cached extractions become stale → next compile triggers full re-extraction. This is documented and acceptable.

#### `extract-types.md` — Add language directive

**File**: `py/src/kb_ai/prompts/defaults/extract-types.md`

**Before** (last 8 lines of the file):
```markdown
- Extract only what is explicitly stated or clearly implied
- topic tags: lowercase, hyphenated (e.g. "api-gateway")
- Empty array for fields with no relevant data
- An enumeration you record is complete: every member, in document order, never abridged
- Of the emphases below, apply only the ones covering a field assigned to you
- For meeting transcripts: focus on Q3 (decisions) and Q2 (entities)
- For documents: focus on Q1 (concepts), Q4 (claims) and Q5 (enumerations)
- Output ONLY the assigned fields above. Do not include any unassigned fields.

Return ONLY valid JSON, no markdown fencing.
```

**After** (last 9 lines — one rule added):
```markdown
- Extract only what is explicitly stated or clearly implied
- topic tags: lowercase, hyphenated (e.g. "api-gateway")
- Empty array for fields with no relevant data
- An enumeration you record is complete: every member, in document order, never abridged
- Of the emphases below, apply only the ones covering a field assigned to you
- For meeting transcripts: focus on Q3 (decisions) and Q2 (entities)
- For documents: focus on Q1 (concepts), Q4 (claims) and Q5 (enumerations)
- Write all extracted field values in the same language as the source document
- Output ONLY the assigned fields above. Do not include any unassigned fields.

Return ONLY valid JSON, no markdown fencing.
```

**Change**: Insert `- Write all extracted field values in the same language as the source document` as a new line after the `- For documents:` rule and before the `- Output ONLY the assigned fields` rule. The "Output ONLY" rule stays last among the bullets because it is the final structural constraint.

**Impact**: `extract_prompt_version()` hash changes — same hash that the `extract.md` change also affects. The `extract-types.md` template is hashed via `_render_type_split_prompt()` which loads the file and substitutes `{FIELDS_LIST}` and `{TYPES_JSON_SCHEMA}` per (k, group) combo; since the language directive line contains no placeholders, it passes through all rendered variants unchanged.

#### `merge-rewrite.md` — Add language directive

**File**: `py/src/kb_ai/prompts/defaults/merge-rewrite.md`

**Before** (complete file, 11 lines):
```markdown
You are maintaining a knowledge base wiki article. Merge new information into the existing article.

Rules:
- Preserve the existing YAML frontmatter structure, but update 'updated' date and add source to 'sources' list
- Rewrite the 'summary' line when the merge broadens what the article covers, so it still names what is actually here (one sentence, under 150 characters); add the line if it is missing
- If the article has a 'status' field (project articles), preserve it unless new information clearly indicates the project has been completed or archived — then update accordingly (active/completed/archived)
- Integrate new information naturally into existing sections
- Do not duplicate information already in the article
- Maintain consistent tone and formatting
- Add [[wikilinks]] for related concepts
- If new sections are needed, add them in a logical position
- The existing article arrives wrapped in an `<article>` tag; the tag delimits the input and is not article content. Return the article itself, starting at its `---` frontmatter, with no wrapper

Return the complete updated article (including frontmatter).
```

**After** (complete file, 12 lines — one rule added):
```markdown
You are maintaining a knowledge base wiki article. Merge new information into the existing article.

Rules:
- Preserve the existing YAML frontmatter structure, but update 'updated' date and add source to 'sources' list
- Rewrite the 'summary' line when the merge broadens what the article covers, so it still names what is actually here (one sentence, under 150 characters); add the line if it is missing
- If the article has a 'status' field (project articles), preserve it unless new information clearly indicates the project has been completed or archived — then update accordingly (active/completed/archived)
- Integrate new information naturally into existing sections
- Do not duplicate information already in the article
- Maintain consistent tone and formatting
- Add [[wikilinks]] for related concepts
- If new sections are needed, add them in a logical position
- The existing article arrives wrapped in an `<article>` tag; the tag delimits the input and is not article content. Return the article itself, starting at its `---` frontmatter, with no wrapper
- Write in the same language as the source documents and the existing article

Return the complete updated article (including frontmatter).
```

**Change**: Insert `- Write in the same language as the source documents and the existing article` as the last rule bullet, after the `<article>` tag rule and before the blank line preceding `Return the complete updated article`.

**Impact**: `write_prompt_version()` hash changes.

#### `merge-section.md` — Add language directive

**File**: `py/src/kb_ai/prompts/defaults/merge-section.md`

**Before** (complete file, 9 lines):
```markdown
You are rewriting one section of a large knowledge base wiki article. You will see the section's current body and the new information to integrate into it.

Rules:
- Integrate the new information into this section
- Keep every existing statement unless the new material directly contradicts it; where contradicted, prefer the new material and say so
- Do not compress, reorder, or drop existing content to make room
- Maintain the section's existing tone and formatting
- Add [[wikilinks]] for related concepts mentioned in the new material

Output only the section body — no heading, no markdown fencing.
```

**After** (complete file, 10 lines — one rule added):
```markdown
You are rewriting one section of a large knowledge base wiki article. You will see the section's current body and the new information to integrate into it.

Rules:
- Integrate the new information into this section
- Keep every existing statement unless the new material directly contradicts it; where contradicted, prefer the new material and say so
- Do not compress, reorder, or drop existing content to make room
- Maintain the section's existing tone and formatting
- Add [[wikilinks]] for related concepts mentioned in the new material
- Write in the same language as the existing section content

Output only the section body — no heading, no markdown fencing.
```

**Change**: Insert `- Write in the same language as the existing section content` after the `[[wikilinks]]` rule and before the blank line preceding `Output only the section body`.

**Impact**: `write_prompt_version()` hash changes.

#### `merge-diff.md` — Add language directive

**File**: `py/src/kb_ai/prompts/defaults/merge-diff.md`

**Before** (last 8 lines of the file):
```markdown
Rules:
- Do NOT reproduce existing content — only describe additions
- "append_to_section": append content at the end of the named section (before the next heading)
- "new_section": insert a new section after the specified existing section
- If ALL information is already in the article, return: {"patches": []}
- Use [[wikilinks]] in content
- Keep patches focused and concise

Return ONLY valid JSON, no markdown fencing.
```

**After** (last 9 lines — one rule added):
```markdown
Rules:
- Do NOT reproduce existing content — only describe additions
- "append_to_section": append content at the end of the named section (before the next heading)
- "new_section": insert a new section after the specified existing section
- If ALL information is already in the article, return: {"patches": []}
- Use [[wikilinks]] in content
- Keep patches focused and concise
- Write all patch content values in the same language as the source documents and the existing article

Return ONLY valid JSON, no markdown fencing.
```

**Change**: Insert `- Write all patch content values in the same language as the source documents and the existing article` as the last rule bullet, after `- Keep patches focused and concise` and before the blank line preceding `Return ONLY valid JSON`.

The wording says "patch content values" because the `merge-diff.md` output is a JSON object with a `patches` array, where each patch has a `content` field containing natural language text. The `action`, `section`, `after`, and `heading` fields are structural (section headings, action verbs) but the `content` field is free-text that must match the source language. Saying "content values" precisely targets the natural language portion of the JSON output.

**Impact**: `write_prompt_version()` hash changes — same hash that the `merge-rewrite.md`, `merge-section.md`, and `_create_system()` changes also affect. The `merge-diff.md` template is loaded via `.content` (not `.render()`) in `_merge_diff_system()` because it contains literal `{...}` JSON example braces; since the language directive line contains no braces, it is unaffected by this loading strategy.

#### `_create_system()` in `core/merge.py` — Add language directive

**File**: `py/src/kb_ai/core/merge.py`, function `_create_system()` (starts at line ~1489)

**Before** — the complete return statement of the function (lines 1501–1524):
```python
    return f"""You are a knowledge base article creator.

Required frontmatter format:
---
title: "{{title}}"
type: {{type}}{status_line}
summary: "{{one sentence}}"
tags: [topic tags]
sources:
  - {{source_path}}
created: {{date}}
updated: {{date}}
---

{_section_guidance(article_type)}

Write a well-structured article following the section guidance above.
{_GROUNDING}

The `summary` line is the article's entry in the knowledge-base catalog, which is
the only surface a reader searches before opening anything. Write one sentence
under 150 characters naming the specific things covered here — subsystems, key
parameters, decisions — not a restatement of the title.

Use [[wikilinks]] for references to related concepts.
Return the complete article including frontmatter."""
```

**After** — the complete return statement (one line inserted after `{_GROUNDING}`):
```python
    return f"""You are a knowledge base article creator.

Required frontmatter format:
---
title: "{{title}}"
type: {{type}}{status_line}
summary: "{{one sentence}}"
tags: [topic tags]
sources:
  - {{source_path}}
created: {{date}}
updated: {{date}}
---

{_section_guidance(article_type)}

Write a well-structured article following the section guidance above.
{_GROUNDING}
Write the article in the same language as the source documents provided.

The `summary` line is the article's entry in the knowledge-base catalog, which is
the only surface a reader searches before opening anything. Write one sentence
under 150 characters naming the specific things covered here — subsystems, key
parameters, decisions — not a restatement of the title.

Use [[wikilinks]] for references to related concepts.
Return the complete article including frontmatter."""
```

**Change**: Insert `Write the article in the same language as the source documents provided.` on a new line immediately after `{_GROUNDING}`, replacing the blank line between `{_GROUNDING}` and `The \`summary\` line...` paragraph with the directive followed by a blank line. This places the language directive after the grounding block and before the summary-line guidance paragraph.

**Why not inside `_GROUNDING`**: Adding to `_GROUNDING` would also affect `merge-diff.md` and `merge-section-router.md`. Per-prompt placement is more precise.

**Impact**: `write_prompt_version()` hash changes (same hash that `merge-rewrite.md`, `merge-section.md`, and `merge-diff.md` changes also affect).

### 4.4 Manifest / Report Changes

**No changes** to the manifest schema or `DeriveReport`. The voting mechanism is transparent to callers — it produces the same `SelectionResult` shape. The `filter_batches` field in the report still counts batches (not rounds × batches). The `dropped_invented_paths` field retains its original semantics (unique paths).

**Optimization**: `filter_rounds` is added to the manifest payload for reproducibility. In `_manifest_payload()` in `py/src/kb_ai/derive/__init__.py`:

```python
# Add after "filter_model": model,
"filter_rounds": filter_rounds,
```

This is additive and does not require bumping `MANIFEST_SCHEMA_VERSION` — schema_version=1 readers that predate this field simply ignore it.

### 4.5 Logging

Add stderr log lines in `select_by_topic()` when `filter_rounds > 1`, matching the existing `print(..., file=sys.stderr)` pattern used throughout the derive pipeline:

```
[filter] voting: {filter_rounds} rounds, threshold ≥{threshold}/{filter_rounds}
```

And per-batch summary when `filter_rounds > 1`:
```
[filter] batch {i+1}/{len(batches)}: {len(survivors)} of {len(candidates)} paths passed voting ({filter_rounds} rounds)
```

**DEBUG-level per-path vote counts** (optimization suggestion): Add a per-path vote log at the batch level:
```
[filter]   {path}: {votes}/{filter_rounds} votes {"✓" if votes >= threshold else "✗"}
```
This is emitted only when the environment variable `KAAS_FILTER_DEBUG=1` is set, to avoid cluttering normal output. Implemented as:
```python
_FILTER_DEBUG = os.environ.get("KAAS_FILTER_DEBUG") == "1"
```

## 5. Implementation Steps

### Phase 1: Multi-Round Voting (core logic)

**Step 1.1**: Modify `select_by_topic()` in `py/src/kb_ai/derive/_filter.py`

- Add `import math` and `import os` at top of file.
- Add `_FILTER_DEBUG = os.environ.get("KAAS_FILTER_DEBUG") == "1"` module-level constant.
- Add `filter_rounds: int = 3` keyword argument.
- Add validation: `if filter_rounds < 1: raise ValueError(f"filter_rounds must be ≥ 1, got {filter_rounds}")`.
- Compute `threshold = math.ceil(filter_rounds * 2 / 3)` with inline comment: `# supermajority: at least ⌈2N/3⌉ rounds must select a path`.
- Log voting config when `filter_rounds > 1`.
- Refactor the per-batch loop:
  - For each batch, run `filter_rounds` rounds of `completion_json()`.
  - For each round, collect valid paths returned (same validation as current: check `isinstance(p, str)`, check `p in valid`).
  - Collect invented paths into a per-batch `invented: set[str]` — each invented path string is added to the set (deduplicating across rounds within a batch).
  - After all rounds for a batch, count votes per path: `votes[p] = number of rounds that returned p`.
  - Retain only paths where `votes[p] >= threshold`.
  - Add `len(invented)` to the running `dropped` counter (unique invented paths per batch).
  - Deduplicate across batches using the existing `seen` set.
  - Log per-batch summary when `filter_rounds > 1`.
  - Log per-path votes when `_FILTER_DEBUG` is set.

**Pseudocode for the refactored loop**:
```python
for i, batch in enumerate(batches):
    listing = "\n".join(render_catalog_line(a) for a in batch)
    prompt = build_prompt(topic, mode, listing)
    batch_valid = {a.path for a in batch}  # paths in this batch
    vote_counts: dict[str, int] = {}
    invented: set[str] = set()

    for _round in range(filter_rounds):
        try:
            result = completion_json(model=model,
                                     messages=[{"role": "user", "content": prompt}])
        except Exception as e:
            raise DeriveError(f"topic filter failed: {e}") from e

        raw = result.get("paths") if isinstance(result, dict) else None
        if not isinstance(raw, list):
            raise DeriveError(
                "topic filter returned no paths list; refusing to treat that "
                "as 'nothing matches'"
            )
        for p in raw:
            if not isinstance(p, str) or p not in valid:
                invented.add(repr(p))  # repr to handle non-strings uniformly
                continue
            if p in batch_valid:
                vote_counts[p] = vote_counts.get(p, 0) + 1

    dropped += len(invented)

    for p, v in vote_counts.items():
        if v >= threshold and p not in seen:
            seen.add(p)
            paths.append(p)
```

**Dependencies**: None.

**Files**: `py/src/kb_ai/derive/_filter.py`

**Step 1.2**: Update `derive_kb()` in `py/src/kb_ai/derive/__init__.py`

- Add `filter_rounds: int = 3` parameter to `derive_kb()` signature (after `summarize_model`).
- Update the default `select` closure to pass `filter_rounds`:
  ```python
  if select is None:
      def select(catalog, topic_, mode):
          return select_by_topic(catalog, topic_, mode, model=model,
                                 filter_rounds=filter_rounds)
  ```
- Add `filter_rounds` to `_manifest_payload()`: pass it as a new kwarg and include `"filter_rounds": filter_rounds` in the payload dict (after `"filter_model"`).
- Update the `_manifest_payload` signature to accept `filter_rounds: int`.
- Update the `flush()` closure to pass `filter_rounds=filter_rounds`.

**Dependencies**: Step 1.1.

**Files**: `py/src/kb_ai/derive/__init__.py`

**Step 1.3**: Add `--filter-rounds` CLI flag in `py/src/kb_ai/commands/derive.py`

- Add `--filter-rounds` argument to `build_parser()`.
- In `run_derive()`, use conditional dict construction to avoid the `or 3` swallowing pattern:
  ```python
  derive_kw: dict = {}
  if args.filter_rounds is not None:
      derive_kw["filter_rounds"] = args.filter_rounds
  report = derive_kb(
      args.kb, args.topic,
      ...,
      **derive_kw,
  )
  ```

**Dependencies**: Step 1.2.

**Files**: `py/src/kb_ai/commands/derive.py`

**Step 1.4**: Add `filter_rounds` to daemon handler in `py/src/kb_ai/server_daemon.py`

- In `_handle_derive()`, use conditional dict construction:
  ```python
  derive_kw: dict = {}
  if inner.get("filter_rounds") is not None:
      derive_kw["filter_rounds"] = inner["filter_rounds"]
  report = derive_kb(
      kb_dir, topic,
      ...,
      **derive_kw,
  )
  ```

**Dependencies**: Step 1.2.

**Files**: `py/src/kb_ai/server_daemon.py`

### Phase 2: Voting Tests

**Step 2.1**: Update existing tests in `py/tests/test_derive_filter.py`

The `test_batches_when_the_listing_exceeds_the_budget` test currently asserts `result.batches == len(calls)`. With the default `filter_rounds=3`, `len(calls)` will be `batches * 3`. **Fix**: Pass `filter_rounds=1` explicitly to preserve original single-call-per-batch semantics:

```python
def test_batches_when_the_listing_exceeds_the_budget(monkeypatch):
    catalog = _catalog(40, summary="x" * 3000)
    calls: list[str] = []

    def capture(**kwargs):
        content = kwargs["messages"][0]["content"]
        calls.append(content)
        return {"paths": [a.path for a in catalog if f"- {a.path} " in content]}

    monkeypatch.setattr(_filter, "completion_json", capture)
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m",
                                     filter_rounds=1)  # ← explicit single round

    assert result.batches > 1
    assert result.batches == len(calls)
    assert sorted(result.paths) == sorted(a.path for a in catalog)
    from kb_ai.llm import MAX_PROMPT_CHARS
    assert all(len(c) <= MAX_PROMPT_CHARS for c in calls)
```

All other existing tests use fixed `completion_json` stubs that return the same result every time. With the default `filter_rounds=3`, every path gets 3/3 votes, passing the threshold of 2. These tests pass unchanged — verified by analysis:
- The stub is called 3× instead of 1× per batch, but returns identical paths.
- `dropped_invented` is deduplicated into a set, so invented paths counted once per batch regardless of rounds.
- No test asserts on `len(calls)` except `test_batches_when_the_listing_exceeds_the_budget` (fixed above).

**Step 2.2**: Add new voting tests to `py/tests/test_derive_filter.py`

New test cases:

1. **`test_voting_retains_paths_meeting_threshold`** — 3 rounds; path A in 3/3 rounds → retained; path B in 2/3 → retained; path C in 1/3 → excluded.
2. **`test_voting_single_round_is_backward_compatible`** — `filter_rounds=1` produces identical behavior to the pre-voting code.
3. **`test_voting_all_rounds_agree`** — All 3 rounds return the same paths → all retained.
4. **`test_voting_no_path_meets_threshold`** — Each round returns a different non-overlapping set → empty result.
5. **`test_voting_dropped_invented_counts_unique_paths`** — An invented path "wiki/fake.md" appears in 2 rounds but counts as 1 in `dropped_invented`. Verifies the dedup semantics.
6. **`test_voting_error_in_any_round_raises`** — Round 2 fails → `DeriveError`.
7. **`test_invalid_filter_rounds_raises`** — `filter_rounds=0` → `ValueError`. Also test `filter_rounds=-1`.
8. **`test_voting_with_multiple_batches`** — Voting works correctly when catalog is split into multiple batches, using `filter_rounds=3`.

**Monkeypatch strategy**: Use a counter to vary `completion_json` return values per call:
```python
call_count = [0]
def varying_completion(**kw):
    call_count[0] += 1
    round_idx = (call_count[0] - 1) % filter_rounds
    return {"paths": round_results[round_idx]}
monkeypatch.setattr(_filter, "completion_json", varying_completion)
```

**Dependencies**: Step 1.1.

**Files**: `py/tests/test_derive_filter.py`

### Phase 3: Language Directives

**Step 3.1**: Add language directive to `extract.md`

- Add `- Write all extracted field values in the same language as the source document` as the last rule before the blank line preceding "Return ONLY valid JSON".

**Dependencies**: None.

**Files**: `py/src/kb_ai/prompts/defaults/extract.md`

**Step 3.2**: Add language directive to `_create_system()` in `merge.py`

- Insert `Write the article in the same language as the source documents provided.\n` after the `{_GROUNDING}` line in the f-string, replacing the empty line that follows `{_GROUNDING}`.

Concretely, change line ~1517 from:
```python
{_GROUNDING}

The `summary` line
```
to:
```python
{_GROUNDING}
Write the article in the same language as the source documents provided.

The `summary` line
```

**Dependencies**: None.

**Files**: `py/src/kb_ai/core/merge.py`

**Step 3.3**: Add language directive to `merge-rewrite.md`

- Add `- Write in the same language as the source documents and the existing article` as the last rule before the blank line preceding "Return the complete updated article".

**Dependencies**: None.

**Files**: `py/src/kb_ai/prompts/defaults/merge-rewrite.md`

**Step 3.4**: Add language directive to `merge-section.md`

- Add `- Write in the same language as the existing section content` as the last rule before the blank line preceding "Output only the section body".

**Dependencies**: None.

**Files**: `py/src/kb_ai/prompts/defaults/merge-section.md`

**Step 3.5**: Add language directive to `extract-types.md`

- Add `- Write all extracted field values in the same language as the source document` as a new line after the `- For documents:` rule and before the `- Output ONLY the assigned fields` rule.

The "Output ONLY" rule stays last among the bullets because it is the final structural constraint for the type-split variant.

**Dependencies**: None.

**Files**: `py/src/kb_ai/prompts/defaults/extract-types.md`

**Impact**: `extract_prompt_version()` hash changes — same hash that the `extract.md` change (Step 3.1) also affects. The combined effect is a single hash invalidation covering both extraction prompt variants.

**Step 3.6**: Add language directive to `merge-diff.md`

- Add `- Write all patch content values in the same language as the source documents and the existing article` as the last rule bullet, after `- Keep patches focused and concise` and before the blank line preceding "Return ONLY valid JSON".

**Dependencies**: None.

**Files**: `py/src/kb_ai/prompts/defaults/merge-diff.md`

**Impact**: `write_prompt_version()` hash changes — same hash that the `merge-rewrite.md` (Step 3.3), `merge-section.md` (Step 3.4), and `_create_system()` (Step 3.2) changes also affect. The combined effect is a single hash invalidation covering all write-phase prompts.

### Phase 4: Language Directive Regression Test

**Step 4.1**: Add regression test for `_create_system()` language directive

In `py/tests/test_core_merge.py`, add a test that asserts the language directive is present in the code-built system prompt:

```python
def test_create_system_contains_language_directive():
    """Regression: the language directive in _create_system() is code-built,
    not file-based, so a future refactor could accidentally drop it."""
    for article_type in ("concept", "project", "decision", "person"):
        system = mg._create_system(article_type)
        assert "same language as the source documents" in system, (
            f"_create_system({article_type!r}) is missing the language directive"
        )
```

This test does not require monkeypatching — it calls the real function and checks its output string. It covers all known article types.

**Dependencies**: Step 3.2.

**Files**: `py/tests/test_core_merge.py`

### Phase 5: Verification

**Step 5.1**: Run existing test suite

```bash
cd py && python -m pytest tests/test_derive_filter.py tests/test_core_merge.py -v
```

Verify:
- All existing filter tests pass (with `test_batches_when_the_listing_exceeds_the_budget` updated to `filter_rounds=1`).
- All other existing filter tests pass unchanged (deterministic mocks → all paths get 3/3 votes → same result as single-round).
- All merge tests pass.
- All new voting tests pass.
- The new `test_create_system_contains_language_directive` test passes.

**Step 5.2**: Verify prompt version invalidation

Manually confirm that `extract_prompt_version()` and `write_prompt_version()` produce different hashes after the prompt changes.

**Step 5.3**: Run full test suite

```bash
cd py && python -m pytest -x
```

## 6. Risks and Mitigations

### Risk 1: 3× LLM cost for filter phase
- **Impact**: Filter cost rises from ~$0.05 to ~$0.15 per derive run (93-article catalog).
- **Mitigation**: `filter_rounds=1` disables voting entirely. CLI flag and daemon payload allow per-run override. Default of 3 is the empirically validated sweet spot (78% stability at 3× cost, vs 85% at 5×).

### Risk 2: `test_batches_when_the_listing_exceeds_the_budget` breaks
- **Impact**: The test asserts `result.batches == len(calls)`. With default `filter_rounds=3`, `len(calls)` would be `batches × 3`.
- **Mitigation**: Explicitly pass `filter_rounds=1` in this test (Step 2.1). All other existing tests use fixed mocks that return the same paths every round — every path gets 3/3 votes, all pass the threshold, result is identical.

### Risk 3: `extract.md` and `extract-types.md` changes trigger full re-extraction
- **Impact**: Next compile of any KB re-extracts every document. For a 93-document KB, ~$2–5 in extraction cost.
- **Mitigation**: This is a known, documented side-effect (diagnosis document, section "Side effect"). The extraction quality improvement (consistent language) justifies the one-time cost. Both prompts feed into the same `extract_prompt_version()` hash, so the invalidation happens once regardless of the order changes are applied.

### Risk 4: Language directive is too weak — LLM still switches languages
- **Impact**: Prompt instructions are not guarantees; the LLM may still occasionally produce mixed-language output.
- **Mitigation**: The directive in `summarize.md` has been effective in practice (diagnosis confirms summarize output follows source language). Using the same pattern across all prompts leverages proven wording. If needed in the future, a stronger directive ("You MUST write in {language}") can be added, but that requires language detection which is out of scope.

### Risk 5: `_GROUNDING` modification considered but rejected
- **Impact**: Adding the language directive to `_GROUNDING` would also affect `merge-diff.md` and `merge-section-router.md`.
- **Mitigation**: Deliberately not done. `merge-section-router.md` returns JSON (language-neutral). `merge-diff.md` now has its own per-prompt directive (Step 3.6) with wording tailored to its patch-based output format ("patch content values"), which is more precise than a generic directive in `_GROUNDING`. Per-prompt placement avoids unintended side effects on `merge-section-router.md`.

### Risk 6: `write_prompt_version()` is `lru_cache(maxsize=1)` — cached value must be cleared
- **Impact**: In a long-lived daemon, if `write_prompt_version()` is called before and after a prompt file edit, the cached value doesn't update.
- **Mitigation**: This is an existing behavior, not introduced by this change. The daemon's `lru_cache` is cleared on code restart. Our changes are to the prompt file content itself, not runtime edits — the hash will be correct for the version of code deployed. No action needed.

### Risk 7: `filter_rounds=0` silently coerced to 3
- **Impact**: Using `or 3` in CLI/daemon code swallows `0` as falsy.
- **Mitigation**: Both CLI and daemon use conditional `if ... is not None` pass-through (Section 4.1), letting `derive_kb()` apply its default. If `0` is explicitly passed, it flows to `select_by_topic()` which raises `ValueError("filter_rounds must be ≥ 1, got 0")`. Tested by `test_invalid_filter_rounds_raises`.

### Risk 8: `merge-diff.md` language directive affects structured JSON fields
- **Impact**: The `merge-diff.md` output is a JSON object with structural fields (`action`, `section`, `after`, `heading`) and natural language fields (`content`). A generic "write in the same language" directive could theoretically cause the model to translate section headings or action verbs.
- **Mitigation**: The directive explicitly says "patch **content** values", targeting only the `content` field which contains natural language text. The `action` field is an enum (`append_to_section`, `new_section`), `section` and `after` must match existing headings exactly, and `heading` is a new heading that should also match the existing article's language — which the directive implicitly encourages. If heading-language issues arise, a follow-up can add "section headings should match the existing article's heading language" as a separate rule.
