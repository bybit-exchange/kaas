# Hierarchical Batch Splitting for Oversized Merge Prompts

## 1. Background and Goals

### Why are we doing this?

When the Phase 2b write step processes an article with many source documents (the `[merge-batch]` and `[merge→create]` code paths in `compile.py`), all source extractions are combined via `_combine_extractions()` into a single `ExtractionResult` and sent to one LLM call. With 4-9+ sources, the combined extraction can:

1. Exceed `MAX_PROMPT_CHARS` (80K), triggering `PromptTooLargeError` (hard rejection in `_completion_inner`).
2. Fit within the prompt budget but produce an output so large the model times out (measured: 348-507s for 4-9 sources on local models, exceeding `_WRITE_CALL_TIMEOUT_S = 300s`).
3. Cause `_fit_extraction_to_budget()` to aggressively truncate the combined extraction, silently losing extraction content from later sources.

### What do we want to achieve?

When the estimated prompt size for a multi-source merge exceeds the available budget, automatically split the source documents into smaller batches, compile each batch into an intermediate article (or merge each batch sequentially), and produce a final article that incorporates all sources — so that no single LLM call gets a prompt too large to complete.

### In scope

- `py/src/kb_ai/commands/compile.py`: the `_process_article()` function's `[merge-batch]` and `[merge→create]` code paths
- `py/src/kb_ai/core/merge.py`: new helper for prompt-size estimation, exported for use by compile.py
- New `.compile.log` tags for split operations
- Tests for the new splitting logic

### Out of scope

- Go server, API, DB, frontend
- Phase 1 (extraction), Phase 2a (classification)
- Single-source merge path (`[merge]`)
- Changes to existing merge dispatch chain (section-merge → diff → full-rewrite)
- Changes to LLM retry/timeout logic
- Changes to prompt templates
- New environment variables (budget derives from existing `KB_AI_MAX_PROMPT_CHARS`)

## 2. Current State Analysis

### How the merge-batch paths work now

In `_process_article()`, when multiple sources are classified to the same article:

**Path A — `[merge→create]`** (article does not exist on disk, multiple merge ops):
```python
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
new_content = create_new_article(article_type, title, combined, ", ".join(merge_rels), model=write_model)
```
All N extractions are combined into one and sent in a single `create_new_article()` call.

**Path B — `[merge-batch]`** (article exists, multiple merge ops):
```python
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
old_content = store.read_article(art_path)
new_content = merge_into_article(art_path, old_content, combined, ", ".join(merge_rels), model=write_model)
```
All N extractions are combined into one and sent in a single `merge_into_article()` call.

### What existing mitigation does

- `_fit_extraction_to_budget()`: truncates individual extraction fields with exponential backoff on lists. Works on a single combined extraction, so with many sources the summary and lists are all concatenated before truncation — later sources' content gets silently dropped.
- `_merge_user_message()`: hard-truncates if the user message exceeds the budget after extraction fitting.
- The merge dispatch chain (section → diff → full-rewrite → RuntimeError) handles articles that grow large, but not the input extraction being too large.

### What doesn't exist

1. No prompt-size estimation *before* the LLM call at the batch level.
2. No splitting of source documents before `_combine_extractions()`.
3. No iterative merge (create from batch 1, merge batch 2, merge batch 3…).
4. No `.compile.log` tag for a hierarchically split merge.

### Constraints

- `MAX_PROMPT_CHARS` = 80K chars (env: `KB_AI_MAX_PROMPT_CHARS`).
- `_SAFETY_MARGIN` = 500 chars.
- `_WRITE_CALL_TIMEOUT_S` = 300s (env: `KB_AI_WRITE_TIMEOUT_S`).
- Write phase runs in parallel across article groups via `ThreadPoolExecutor`.
- Each `_process_article()` call is single-threaded within its article group.
- `_with_write_timeout` decorator sets the per-call timeout on both `create_new_article` and `merge_into_article`.

## 3. Technical Design

### Architecture Decision: Sequential Iterative Merge

Two strategies were considered:

**Option A — Parallel tree merge**: Split N sources into batches, create/merge each batch in parallel, then merge the intermediate results. This maximizes parallelism but introduces complexity: intermediate articles need to be merged together, requiring a novel "merge article into article" path.

**Option B — Sequential iterative merge**: Create an article from batch 1, then merge batch 2 into it, then merge batch 3 into it, etc. Each step is a standard `create_new_article()` or `merge_into_article()` call that already exists. Simpler, deterministic ordering, and the article grows incrementally.

**Chosen: Option B** — Sequential iterative merge.

Rationale:
- Reuses existing `create_new_article()` and `merge_into_article()` with zero changes to those functions.
- The article grows through the same code paths every single-source merge uses, so quality is identical.
- Sequential ordering is deterministic and debuggable.
- No new prompt templates needed.
- The cost is serial latency within one article group, but these are already serialized per-article within `_process_article()`, and the one large call was timing out anyway.

### How the splitting works

1. **Estimate prompt size** before calling `_combine_extractions()`. For each source `(rel, extraction)`, compute `_estimate_full_extraction_size(extraction, rel)`. Sum them.

2. **Compute the merge budget dynamically**:
   - For `[merge→create]` first batch: compute the actual `user_header` from the batch's `source_path` (joined rel paths) and `extraction.topics`, then `budget = MAX_PROMPT_CHARS - len(system) - len(user_header) - _SAFETY_MARGIN`.
   - For `[merge-batch]` and subsequent `[merge→create]` batches: `budget = MAX_PROMPT_CHARS - len(system) - len(article_content) - _MERGE_FRAMING_CHARS - _SAFETY_MARGIN`.

3. **If total extraction size ≤ budget**: proceed as today (single call, no split). Backward compatible.

4. **If total extraction size > budget**: enter the iterative merge loop:
   - **Batch 1** (when no existing article): `create_new_article(type, title, combined_batch_1, rels_1, model)` → produces `intermediate_article`
   - **Batch 1** (when article exists): `merge_into_article(path, old_content, combined_batch_1, rels_1, model)` → produces `intermediate_article`
   - **Batch 2+**: `merge_into_article(path, intermediate_article, combined_batch_N, rels_N, model)` → produces updated `intermediate_article`
   - Final result is the last `intermediate_article`, written to disk once.

5. **Batches are NOT pre-computed.** Each batch is computed on-the-fly after the previous batch completes, because the article grows and the available budget shrinks. After each batch, the next budget is re-computed from the actual intermediate article size.

### Budget computation (dynamic, per-batch)

**For `create_new_article` (first batch, no existing article)**:

The budget must account for the actual `user_header` that `create_new_article` builds. Looking at the actual code (merge.py lines ~1449-1459):
```python
user_header = f"""Create article:
- Title: {title}
- Type: {article_type}
- Source: {source_path}
- Created/Updated: {today}
- Tags: {extraction.topics}

Knowledge to include:
"""
budget = MAX_PROMPT_CHARS - len(system) - len(user_header) - _SAFETY_MARGIN
```

The `source_path` parameter is `", ".join(batch_rels)` and `extraction.topics` is the combined batch's topic list — both grow with the number of items in the batch. A static constant cannot capture this.

**Solution**: `estimate_create_budget()` takes the actual `title`, `article_type`, and the batch's `(rel, extraction)` items, builds a synthetic `user_header` from them (using the same f-string template `create_new_article` uses), and returns the precise budget.

**For `merge_into_article` (all other cases)**:

The budget computation mirrors `_merge_full_rewrite`:
```
system = _merge_rewrite_system()
budget = MAX_PROMPT_CHARS - len(system) - len(article_content) - _MERGE_FRAMING_CHARS - _SAFETY_MARGIN
```

**Known approximation**: This budget matches the full-rewrite path. The section-merge and diff paths have slightly different prompt structures. Since the full-rewrite path has the tightest budget (it sends the full article + full extraction), using it as the estimate is conservative — the other paths use less budget, so items that fit the full-rewrite budget also fit those paths. This is documented explicitly and is acceptable because `_fit_extraction_to_budget` handles any remaining overflow downstream.

### Greedy batch packing

```python
def _pack_merge_batch(items, budget):
    """Pack items into one batch that fits within budget chars.
    Returns (batch, remaining). Items are (rel, extraction) tuples."""
    batch, remaining = [], []
    batch_size = 0
    for rel, ext in items:
        cost = _estimate_full_extraction_size(ext, rel)
        if batch and batch_size + cost > budget:
            remaining.append((rel, ext))
        else:
            batch.append((rel, ext))
            batch_size += cost
    if not batch and remaining:
        # Single extraction exceeds budget — take it anyway;
        # _fit_extraction_to_budget will truncate it within the LLM call.
        batch.append(remaining.pop(0))
    return batch, remaining
```

Key: if a single extraction exceeds the budget, it is taken anyway because `_fit_extraction_to_budget()` inside `create_new_article()` / `merge_into_article()` will handle the truncation — exactly as happens today for a single oversized source.

### Backward compatibility

- When all sources fit in one batch, the code path is identical to today: `_combine_extractions()` → single call. No behavioral change.
- No new env vars.
- `create_new_article()` and `merge_into_article()` signatures unchanged.
- `_combine_extractions()` signature unchanged.

### Log output

New `.compile.log` tags:
- `[merge→create-split]` — when a `merge→create` is split into batches
- `[merge-batch-split]` — when a `merge-batch` is split into batches

Format:
```
  [merge→create-split] wiki/concept/foo.md ← 9 sources (3 batches) — $0.0234
  [merge-batch-split] wiki/concept/bar.md ← 7 sources (2 batches) — $0.0189
```

Individual batch progress is logged to stderr only (not `.compile.log`) for debugging. No total estimate is logged — the batch count is only known after completion because the article grows and shrinks the budget dynamically:
```
  [merge-split] wiki/concept/foo.md batch 1: create ← 3 sources
  [merge-split] wiki/concept/foo.md batch 2: merge ← 3 sources
  [merge-split] wiki/concept/foo.md batch 3: merge ← 3 sources
```

## 4. Interface Contracts

There are no new HTTP API endpoints in this feature — all changes are internal to the Python compile pipeline. The contracts below define internal function signatures, configuration, and log formats.

### 4.1 New function: `estimate_create_budget()`

**Location**: `py/src/kb_ai/core/merge.py`

```python
def estimate_create_budget(
    article_type: str,
    title: str,
    batch_items: list[tuple[str, ExtractionResult]],
) -> int:
    """Estimate the character budget available for extraction text in a create_new_article call.

    Builds a synthetic user_header from the batch's actual fields (matching
    create_new_article's f-string template) to account for variable-length
    source_path (joined rel paths) and extraction.topics.

    Args:
        article_type: Article type string (e.g. "concept", "project").
        title: Article title.
        batch_items: The (rel_path, ExtractionResult) pairs that will be in this batch.
                     Used to compute source_path and topics from the combined batch.

    Returns:
        Available characters for extraction text. Always >= 200.
    """
```

**Return type**: `int` (always ≥ 200)

**Visibility**: module-level, exported (imported in compile.py).

**Implementation detail**: The function combines the batch items' topics (deduped, matching `_combine_extractions` behavior) and joins their rel paths to build `source_path = ", ".join(rels)`, then constructs the user_header from the same f-string template `create_new_article` uses, and subtracts `len(_create_system(article_type)) + len(user_header) + _SAFETY_MARGIN` from `MAX_PROMPT_CHARS`.

### 4.2 New function: `estimate_merge_budget()`

**Location**: `py/src/kb_ai/core/merge.py`

```python
def estimate_merge_budget(article_content: str) -> int:
    """Estimate the character budget available for extraction text in a merge_into_article call.

    Args:
        article_content: The existing article text to merge into.

    Returns:
        Available characters for extraction text. Always >= 200.

    Notes:
        Budget = MAX_PROMPT_CHARS - len(_merge_rewrite_system())
               - len(article_content) - _MERGE_FRAMING_CHARS - _SAFETY_MARGIN.
        This matches the full-rewrite path's budget. The section-merge and diff
        paths have slightly different structures, but the full-rewrite budget is
        the tightest (it sends the full article in a single prompt), so using it
        as the estimate is conservative. Any remaining overflow is handled by
        _fit_extraction_to_budget inside the actual merge call.
    """
```

**Return type**: `int` (always ≥ 200)

**Visibility**: module-level, exported (imported in compile.py).

### 4.3 New constant: `_MERGE_FRAMING_CHARS`

**Location**: `py/src/kb_ai/core/merge.py`

**Placement**: Must come after `_ARTICLE_OPEN` and `_ARTICLE_CLOSE` definitions (currently at lines ~33-34).

```python
# Character cost of _merge_user_message's framing around the article and extraction:
# "Existing article:\n<article>\n" (header) + "\n</article>\n\nNew information to merge:\n" (footer)
# Measured from the actual strings in _merge_user_message; constant so it is not
# re-computed per call. Placed after _ARTICLE_OPEN/_ARTICLE_CLOSE which it references.
_MERGE_FRAMING_CHARS = (
    len(f"Existing article:\n{_ARTICLE_OPEN}\n")
    + len(f"\n{_ARTICLE_CLOSE}\n\nNew information to merge:\n")
)
```

### 4.4 New function: `_pack_merge_batch()`

**Location**: `py/src/kb_ai/commands/compile.py` (private to compile module)

```python
def _pack_merge_batch(
    items: list[tuple[str, ExtractionResult]],
    budget: int,
) -> tuple[list[tuple[str, ExtractionResult]], list[tuple[str, ExtractionResult]]]:
    """Greedily pack (rel_path, extraction) pairs into one batch fitting budget.

    Args:
        items: Source items to pack, ordered. Each is (rel_path, ExtractionResult).
        budget: Maximum total extraction chars for this batch.

    Returns:
        (batch, remaining): batch is the items that fit; remaining is the rest.
        If a single item exceeds budget, it is taken alone (truncation happens
        downstream in _fit_extraction_to_budget).
        If items is empty, returns ([], []).
    """
```

**Return type**: `tuple[list[tuple[str, ExtractionResult]], list[tuple[str, ExtractionResult]]]`

**Invariants**:
- `len(batch) + len(remaining) == len(items)` always
- `len(batch) >= 1` when `len(items) >= 1`
- Items preserve their original ordering
- The batch's total `sum(_estimate_full_extraction_size(ext, rel) for rel, ext in batch)` ≤ `budget`, except when a single item exceeds budget (taken alone for downstream truncation)

### 4.5 New function: `_merge_batch_split()`

**Location**: `py/src/kb_ai/commands/compile.py` (private to compile module)

```python
def _merge_batch_split(
    art_path: str,
    items: list[tuple[str, ExtractionResult]],
    write_model: str,
    *,
    article_content: str | None,
    article_type: str = "",
    title: str = "",
) -> tuple[str, list[str], int]:
    """Iteratively merge sources into an article in batches.

    Args:
        art_path: Target article path (e.g. "wiki/concept/foo.md").
        items: The source list, each (rel_path, ExtractionResult). Extracted
               from the merges list by the caller.
        write_model: LLM model name.
        article_content: Existing article text, or None if creating new.
        article_type: Article type (used only when article_content is None).
        title: Article title (used only when article_content is None).

    Returns:
        (final_content, all_rel_paths, n_batches):
            final_content: The merged article content.
            all_rel_paths: All source rel_paths that were processed (same order as items).
            n_batches: Number of batches actually used.

    Raises:
        RuntimeError: if any batch's LLM call fails (propagated from
        create_new_article / merge_into_article).

    Notes:
        - Batch 1 when article_content is None: calls create_new_article()
        - Batch 1 when article_content is str: calls merge_into_article()
        - Batch 2+: always calls merge_into_article() into the intermediate result
        - Each batch computes its own budget dynamically from the current
          intermediate article size — batches are NOT pre-computed
        - Per-batch progress logged to stderr: [merge-split] art_path batch N: ...
    """
```

**Return type**: `tuple[str, list[str], int]`

### 4.6 Existing function import: `_estimate_full_extraction_size`

**Location**: `py/src/kb_ai/core/merge.py` (already exists at module scope)

Currently used only within merge.py. Must be importable by compile.py. It is already at module scope — the `_` prefix is a convention, not an access restriction. Import: `from kb_ai.core.merge import _estimate_full_extraction_size, estimate_create_budget, estimate_merge_budget`.

### 4.7 Updated `.compile.log` format

**Existing tags** (unchanged):
```
  [merge→create] wiki/concept/foo.md ← 3 sources — $0.0080
  [merge-batch] wiki/concept/bar.md ← 5 sources — $0.0120
```

**New tags**:
```
  [merge→create-split] wiki/concept/foo.md ← 9 sources (3 batches) — $0.0234
  [merge-batch-split] wiki/concept/bar.md ← 7 sources (2 batches) — $0.0189
```

**Stderr per-batch progress** (not in .compile.log):
```
  [merge-split] wiki/concept/foo.md batch 1: create ← 3 sources
  [merge-split] wiki/concept/foo.md batch 2: merge ← 3 sources
  [merge-split] wiki/concept/foo.md batch 3: merge ← 3 sources
```

### 4.8 Unchanged external interfaces

- No changes to the Go bridge protocol.
- No changes to `compile_kb()`'s return dict.
- No changes to `DeriveReport` or derive types.
- No new env vars (the budget derives from existing `KB_AI_MAX_PROMPT_CHARS`).
- `create_new_article()` and `merge_into_article()` signatures unchanged.
- `_combine_extractions()` signature unchanged.
- `.compile-state.json` format unchanged.

## 5. Implementation Steps

### Step 1: Add budget estimation helpers to merge.py

**File**: `py/src/kb_ai/core/merge.py`

1. Add `_MERGE_FRAMING_CHARS` constant, placed **after** the `_ARTICLE_OPEN` / `_ARTICLE_CLOSE` definitions (currently at lines ~33-34):
   ```python
   _MERGE_FRAMING_CHARS = (
       len(f"Existing article:\n{_ARTICLE_OPEN}\n")
       + len(f"\n{_ARTICLE_CLOSE}\n\nNew information to merge:\n")
   )
   ```

2. Add `estimate_merge_budget()` function (public, near the other budget-related code):
   ```python
   def estimate_merge_budget(article_content: str) -> int:
       """Estimate extraction budget for a merge_into_article call.

       Matches the full-rewrite path's budget, which is the tightest of the three
       merge paths (section-merge, diff, full-rewrite). Conservative: items that
       fit this budget also fit the other paths. Any remaining overflow is handled
       by _fit_extraction_to_budget inside the actual merge call.
       """
       system = _merge_rewrite_system()
       budget = MAX_PROMPT_CHARS - len(system) - len(article_content) - _MERGE_FRAMING_CHARS - _SAFETY_MARGIN
       return max(budget, 200)
   ```

3. Add `estimate_create_budget()` function (public):
   ```python
   def estimate_create_budget(
       article_type: str,
       title: str,
       batch_items: list[tuple[str, ExtractionResult]],
   ) -> int:
       """Estimate extraction budget for a create_new_article call.

       Builds the actual user_header from the batch's fields (matching
       create_new_article's f-string template) so the budget accounts for
       variable-length source_path and topics.
       """
       from datetime import date
       today = date.today().isoformat()

       # Combine topics the same way _combine_extractions does
       all_topics: list[str] = []
       rels: list[str] = []
       for rel, ext in batch_items:
           all_topics.extend(ext.topics)
           rels.append(rel)
       topics = list(set(all_topics))
       source_path = ", ".join(rels)

       system = _create_system(article_type)
       # Same f-string template as create_new_article
       user_header = f"""Create article:
   - Title: {title}
   - Type: {article_type}
   - Source: {source_path}
   - Created/Updated: {today}
   - Tags: {topics}

   Knowledge to include:
   """
       budget = MAX_PROMPT_CHARS - len(system) - len(user_header) - _SAFETY_MARGIN
       return max(budget, 200)
   ```

**Depends on**: nothing.
**Verification**: unit tests in Step 5 (`test_estimate_create_budget_*`, `test_estimate_merge_budget_*`).

### Step 2: Add `_pack_merge_batch()` and `_merge_batch_split()` to compile.py

**File**: `py/src/kb_ai/commands/compile.py`

1. Expand the existing import from `kb_ai.core.merge`:
   ```python
   from kb_ai.core.merge import (
       create_new_article,
       merge_into_article,
       write_prompt_version,
       estimate_create_budget,
       estimate_merge_budget,
       _estimate_full_extraction_size,
   )
   ```

2. Add `_pack_merge_batch()` function before `_process_article()`:
   ```python
   def _pack_merge_batch(
       items: list[tuple[str, ExtractionResult]],
       budget: int,
   ) -> tuple[list[tuple[str, ExtractionResult]], list[tuple[str, ExtractionResult]]]:
       batch: list[tuple[str, ExtractionResult]] = []
       batch_size = 0
       remaining: list[tuple[str, ExtractionResult]] = []
       for rel, ext in items:
           cost = _estimate_full_extraction_size(ext, rel)
           if batch and batch_size + cost > budget:
               remaining.append((rel, ext))
           else:
               batch.append((rel, ext))
               batch_size += cost
       if not batch and remaining:
           batch.append(remaining.pop(0))
       return batch, remaining
   ```

3. Add `_merge_batch_split()` function:
   ```python
   def _merge_batch_split(
       art_path: str,
       items: list[tuple[str, ExtractionResult]],
       write_model: str,
       *,
       article_content: str | None,
       article_type: str = "",
       title: str = "",
   ) -> tuple[str, list[str], int]:
       """Iteratively merge sources in budget-sized batches."""
       all_rels: list[str] = []
       remaining = list(items)
       current_content = article_content
       batch_num = 0

       while remaining:
           batch_num += 1

           # Compute budget dynamically for each batch
           if current_content is None:
               # First batch, create path: budget depends on batch contents
               # Use remaining items as worst case for header estimation
               budget = estimate_create_budget(article_type, title, remaining)
           else:
               # Merge path: budget depends on current article size
               budget = estimate_merge_budget(current_content)

           batch, remaining = _pack_merge_batch(remaining, budget)
           combined, batch_rels = _combine_extractions(batch)
           all_rels.extend(batch_rels)

           if current_content is None:
               # First batch, no existing article: create
               print(f"  [merge-split] {art_path} batch {batch_num}: "
                     f"create ← {len(batch)} sources", file=sys.stderr, flush=True)
               current_content = create_new_article(
                   article_type, title, combined, ", ".join(batch_rels), model=write_model)
           else:
               # Merge into existing/intermediate article
               print(f"  [merge-split] {art_path} batch {batch_num}: "
                     f"merge ← {len(batch)} sources", file=sys.stderr, flush=True)
               current_content = merge_into_article(
                   art_path, current_content, combined, ", ".join(batch_rels), model=write_model)

       return current_content, all_rels, batch_num
   ```

**Note on `estimate_create_budget` call**: The first-batch budget is estimated from `remaining` (all items still to process), which overestimates the `source_path` length (joins all remaining rels, not just the batch). This is conservative — the batch will actually use fewer rels, so the actual budget inside `create_new_article` will be *larger* than estimated. The packing always stays on the safe side.

**Depends on**: Step 1.
**Verification**: unit tests in Step 5.

### Step 3: Modify `_process_article()` to use batch splitting

**File**: `py/src/kb_ai/commands/compile.py`

#### 3a. The `[merge→create]` path (article does not exist on disk, multiple merges)

Currently (around line ~440, the block starting with `combined, merge_rels = _combine_extractions`):

Replace with:
```python
items = [(rel, ext) for rel, _cs, ext, _det in merges]
total_size = sum(_estimate_full_extraction_size(ext, rel) for rel, ext in items)
budget = estimate_create_budget(article_type, title, items)
needs_split = total_size > budget and len(items) > 1
try:
    with _measure_op_cost() as op_cost:
        if needs_split:
            new_content, merge_rels, n_batches = _merge_batch_split(
                art_path, items, write_model,
                article_content=None, article_type=article_type, title=title)
        else:
            combined, merge_rels = _combine_extractions(items)
            new_content = create_new_article(
                article_type, title, combined, ", ".join(merge_rels), model=write_model)
        store.write_article(art_path, new_content)
    if needs_split:
        log(f"  [merge→create-split] {art_path} ← {len(merges)} sources "
            f"({n_batches} batches) — ${op_cost.total_cost:.4f}")
    else:
        log(f"  [merge→create] {art_path} ← {len(merges)} sources "
            f"— ${op_cost.total_cost:.4f}")
    with _write_lock:
        for rel, _cs, _ext, _det in merges:
            _file_done_ops[rel] += 1
            _file_done_articles[rel].add(art_path)
except Exception as e:
    with _write_lock:
        for rel, _cs, _ext, _det in merges:
            errors.append({"file": rel, "error": str(e), "article": art_path})
    tag = "merge→create-split-error" if needs_split else "merge→create-error"
    log(f"  [{tag}] {art_path} ← {len(merges)} sources: {e}")
```

**Key changes from R1 plan addressing review issues**:
- Error handler uses `for rel, _cs, _ext, _det in merges:` (the original 4-tuple list), NOT `merge_rels` — handles both split and non-split cases, and works even if `_merge_batch_split` raises before returning.
- Success handler also uses the original `merges` to iterate for `_file_done_ops` — this is correct regardless of path because all sources are always processed.
- `n_batches` is returned directly from `_merge_batch_split` (third return element).

#### 3b. The `[merge-batch]` path (article exists, multiple merges)

Currently the `else:` branch with `combined, merge_rels = _combine_extractions(...)`:

Replace with:
```python
items = [(rel, ext) for rel, _cs, ext, _det in merges]
old_content = store.read_article(art_path)
total_size = sum(_estimate_full_extraction_size(ext, rel) for rel, ext in items)
budget = estimate_merge_budget(old_content)
needs_split = total_size > budget and len(items) > 1
try:
    with _measure_op_cost() as op_cost:
        if needs_split:
            new_content, merge_rels, n_batches = _merge_batch_split(
                art_path, items, write_model,
                article_content=old_content)
        else:
            combined, merge_rels = _combine_extractions(items)
            new_content = merge_into_article(
                art_path, old_content, combined, ", ".join(merge_rels), model=write_model)
        store.write_article(art_path, new_content)
    if needs_split:
        log(f"  [merge-batch-split] {art_path} ← {len(merges)} sources "
            f"({n_batches} batches) — ${op_cost.total_cost:.4f}")
    else:
        log(f"  [merge-batch] {art_path} ← {len(merges)} sources "
            f"— ${op_cost.total_cost:.4f}")
    with _write_lock:
        for rel, _cs, _ext, _det in merges:
            _file_done_ops[rel] += 1
            _file_done_articles[rel].add(art_path)
except Exception as e:
    with _write_lock:
        for rel, _cs, _ext, _det in merges:
            errors.append({"file": rel, "error": str(e), "article": art_path})
    tag = "merge-batch-split-error" if needs_split else "merge-batch-error"
    log(f"  [{tag}] {art_path} ← {len(merges)} sources: {e}")
```

**Same error handling pattern**: error handler always iterates the original `merges` list.

**Depends on**: Steps 1, 2.
**Verification**: integration tests in Step 4.

### Step 4: Write tests

**File**: `py/tests/test_compile_batch_split.py` (new file)

Tests follow existing patterns from `py/tests/test_compile_paths.py`: monkeypatch LLM seams, real `KBStore` on `tmp_path`.

**Unit tests for budget estimation**:

1. **`test_estimate_create_budget_positive`**: Budget for create path with typical items is positive and < MAX_PROMPT_CHARS.
2. **`test_estimate_create_budget_scales_with_rels`**: Budget shrinks as more items (longer source_path) are added.
3. **`test_estimate_create_budget_floor`**: With huge topics/rels, budget floors at 200.
4. **`test_estimate_merge_budget_positive`**: Budget for merge path with short article is positive and < MAX_PROMPT_CHARS.
5. **`test_estimate_merge_budget_shrinks_with_article`**: Budget shrinks as article_content grows.
6. **`test_estimate_merge_budget_floor`**: Very large article → budget floor of 200.

**Unit tests for packing**:

7. **`test_pack_merge_batch_all_fit`**: All items fit in one batch → batch = all, remaining = [].
8. **`test_pack_merge_batch_splits`**: Items that exceed budget → split into batch + remaining.
9. **`test_pack_merge_batch_single_oversized`**: One item exceeds budget → taken alone.
10. **`test_pack_merge_batch_empty`**: Empty input → ([], []).
11. **`test_pack_merge_batch_preserves_order`**: Items appear in batch and remaining in original order.

**Unit tests for `_merge_batch_split`**:

12. **`test_merge_batch_split_creates_then_merges`**: Mock `create_new_article` and `merge_into_article`. Provide 6 items that require 3 batches. Verify: batch 1 calls create, batches 2-3 call merge, return has correct content and 3 batches.
13. **`test_merge_batch_split_merge_only`**: Provide existing `article_content`. All batches call `merge_into_article`.
14. **`test_merge_batch_split_error_mid_batch`**: Batch 2 raises RuntimeError. Verify it propagates (not swallowed).
15. **`test_merge_batch_split_single_batch`**: All items fit → 1 batch, correct return.

**Integration tests for `_process_article`**:

16. **`test_process_article_merge_create_split`**: Monkeypatched LLM seams. N sources whose extractions exceed budget → split tag `[merge→create-split]` in log.
17. **`test_process_article_merge_batch_split`**: Same for existing-article path → `[merge-batch-split]` in log.
18. **`test_process_article_under_threshold_unchanged`**: N sources under budget → original path, no split tag.

**Depends on**: Steps 1–3.

## 6. Risks and Mitigations

### R1: Article quality degradation from iterative merging

**Risk**: Merging sources one batch at a time may produce lower-quality articles than merging all at once, because later batches see the intermediate article rather than the raw extraction from earlier sources.

**Mitigation**: Each batch goes through the same `create_new_article()` / `merge_into_article()` path that every single-source merge uses. The quality is identical to merging sources one-at-a-time over multiple compile runs — which is the normal case for long-lived KBs. The alternative (one huge call that times out) produces nothing at all, so any result is better.

**Detection**: Compare article quality for 3-4 articles in the reference KB before/after. The `.compile.log` split tags make split articles easy to identify.

### R2: Growing article shrinks budget for later batches

**Risk**: After merging batch 1, the intermediate article may be so large that subsequent batches have very little extraction budget, leading to aggressive truncation or single-source batches.

**Mitigation**: The batch packing is dynamic — it re-computes the budget after each batch using the actual intermediate article size. In the worst case, each remaining source gets its own batch, which is equivalent to N sequential single-source merges — the same outcome as if those sources had been compiled in separate runs. The floor of 200 chars ensures even a maximally-large article leaves room for the source path and a truncated summary.

**Detection**: The per-batch stderr log shows the source count per batch. A batch with 1 source when many remain indicates the article has grown large. This is informational, not an error.

### R3: Partial failure leaves sources unrecorded

**Risk**: If batch 2 of 3 fails, batch 1's sources are already merged into the intermediate article but the `_merge_batch_split()` call raises, so nothing is written to disk.

**Mitigation**: This is the correct behavior — it mirrors how the existing batch path works. The entire article group either succeeds or fails. The error handler in `_process_article()` records the error for all source rels (using the original `merges` list, not the partial `all_rels`). On the next compile run, the same sources will be retried (none are recorded in `completed_ops` because the error prevented the state update).

### R4: Performance regression for under-threshold cases

**Risk**: The size estimation adds a `sum(_estimate_full_extraction_size(...))` call before every multi-source merge, even when no split is needed.

**Mitigation**: `_estimate_full_extraction_size()` is pure computation (string length arithmetic, no I/O, no LLM calls). For typical merge groups of 2-5 sources, this is microseconds — negligible compared to the LLM call that follows. The check is O(N) in the number of sources for that article, and N is typically < 20.

### R5: Thread safety

**Risk**: `_merge_batch_split()` is called inside `_process_article()` which runs in a thread pool.

**Mitigation**: `_merge_batch_split()` is stateless — it takes all inputs as arguments and returns the result. The only shared state it touches is through `create_new_article()` and `merge_into_article()`, which already handle thread safety (they use the shared OpenAI client which is thread-safe, and the `_with_write_timeout` decorator uses thread-local call timeout). No new shared state is introduced.

### R6: Budget estimation is conservative for create first batch

**Risk**: `estimate_create_budget()` is called with all remaining items to compute the first batch's budget, overestimating `source_path` length (joins all rels, not just the batch's). This may produce a smaller-than-necessary first batch.

**Mitigation**: Being conservative is the safe direction — the first batch may be slightly smaller than optimal, causing one extra batch. Since the whole point is that the previous single-batch approach was timing out, an extra batch is negligible. The actual `create_new_article` call always gets the correct budget internally from `_fit_extraction_to_budget`.
