# Auto-Split Oversized Intermediate Articles into Sub-Articles

## 1. Background and Goals

### Why are we doing this?

The `_merge_batch_split` function iteratively merges sources into a single article in budget-sized batches. However, as the intermediate article grows through successive merges, `estimate_merge_budget(current_content)` shrinks monotonically. With 68–80 source groups, the intermediate article eventually reaches ~76K chars, at which point the budget hits the floor of 200 chars. At that point:

1. `_pack_merge_batch` takes only 1 item per batch (every extraction exceeds 200 chars)
2. `_fit_extraction_to_budget` truncates each extraction to ~200 chars, losing most content
3. Each merge adds more text, further shrinking the budget — a death spiral
4. `merge_into_article` may hit the RuntimeError path ("diff result unparsable and no rewrite fits")

The result: either an error or an article where later sources are barely represented.

### What do we want to achieve?

When the merge budget drops below a usable threshold during iterative batch-split merging, **finalize the current intermediate article as a sub-article** and **start a fresh sub-article** for the remaining sources. This ensures every source gets a meaningful extraction budget rather than being starved by a bloated intermediate article.

### In scope

- `py/src/kb_ai/commands/compile.py`: modify `_merge_batch_split` to detect budget exhaustion and produce sub-articles; add stale sub-article cleanup; add sub-article path helper
- `py/src/kb_ai/core/merge.py`: new constant for the budget threshold
- Sub-article naming: `-part-N` suffix before `.md` extension
- Sub-article frontmatter: each sub-article is a standalone valid article
- State tracking integration: `completed_ops`, `_file_done_ops`, `_file_done_articles`
- Stale sub-article cleanup (orphan `-part-N` files from prior runs)
- Content deduplication strategy when splitting from merge-into-existing path
- Log tags for sub-article splits
- Tests for all new/changed behavior

### Out of scope

- Go server, API, DB, frontend
- Phase 1 (extraction), Phase 2a (classification)
- Single-source merge path (`[merge]`)
- Changes to `create_new_article()` or `merge_into_article()` signatures
- Changes to prompt templates
- Master index changes (sub-articles are picked up automatically by `rglob("*.md")`)
- Cross-referencing between sub-articles (future enhancement)

## 2. Current State Analysis

### How `_merge_batch_split` works now

```
remaining = all items
current_content = existing article content (or None)

while remaining:
    budget = estimate_merge_budget(current_content) or estimate_create_budget(...)
    batch, remaining = _pack_merge_batch(remaining, budget)
    current_content = create_new_article(...) or merge_into_article(...)

return (current_content, all_rels, n_batches)
```

**Key issue**: `current_content` grows monotonically. The budget can only shrink. With many sources, the article hits the budget floor long before all sources are processed.

### Budget arithmetic

- `MAX_PROMPT_CHARS = 80_000`
- System prompt ≈ 3,000 chars
- `_MERGE_FRAMING_CHARS ≈ 90`
- `_SAFETY_MARGIN = 500`
- Available for article + extraction ≈ 76,400 chars
- When article reaches ~76K chars → budget = 200 (the floor)
- A typical extraction is 2,000–10,000 chars. At budget=200, only the source path and a few words survive.

### State tracking

- `_file_done_ops[rel]` counts how many article-ops were completed for each raw file
- `_file_done_articles[rel]` tracks which article paths were written for each raw file
- `completed_ops` in `.compile-state.json` stores article paths that have been completed, checked via `merge["path"] in previously_done`
- On next compile, `completed_ops` entries are checked against the **classified** article path (e.g., `wiki/concept/foo.md`), not sub-article paths

### Index building

`update_markdown_index` uses `store.wiki_dir.rglob("*.md")` to discover all articles. Sub-articles placed under `wiki/<type>/` will be discovered automatically — no index changes needed.

### Constraints

1. `_process_article` is called with the **classified** `art_path` (e.g., `wiki/concept/foo.md`)
2. `article_ops` dict is keyed by this classified path
3. The `completed_ops` check uses the classified path, not sub-article paths
4. Sub-articles must not break the "skip if already done" logic on re-compile
5. Groups of ops from the same raw file to the same article path must complete atomically

## 3. Technical Design

### Architecture Decision: Sub-Article Split Inside `_merge_batch_split`

The split point is inside `_merge_batch_split`'s main loop. When the merge budget drops below a **usable threshold**, the current intermediate article is finalized as a sub-article and a new one starts.

**Why inside `_merge_batch_split`?**

- It is the only place where the iterative budget-shrinking problem manifests
- The outer `_process_article` function calls `_merge_batch_split` and gets back the final content — for sub-articles, it gets back a **list of (path, content) pairs** instead
- The change is localized: `_process_article` only needs to handle writing multiple files, cleaning up stale parts, and adjusting the log tag

### Sub-Article Naming

Given a base article path `wiki/concept/foo.md`:
- Part 1: `wiki/concept/foo-part-1.md`
- Part 2: `wiki/concept/foo-part-2.md`
- Part N: `wiki/concept/foo-part-N.md`

The `-part-N` suffix is appended to the stem before the `.md` extension.

### Usable Budget Threshold

**`_SUB_ARTICLE_BUDGET_THRESHOLD = 2000`** (characters)

When `estimate_merge_budget(current_content)` drops below this threshold and there are remaining items to merge, the current article is finalized and a new sub-article begins.

**Why 2000?**

- A typical minimal useful extraction (source path + summary + a few list items) is ~500–1500 chars
- At 200 (the current floor), truncation is catastrophic — only 1–2 lines of summary survive
- At 2000, the extraction can include a summary and at least partial lists from one source
- At 2000, the article is approximately 74K chars — large but not unreasonable as a standalone reference
- The threshold is conservative: it triggers only when the article has genuinely consumed ~92% of prompt budget

### Frontmatter for Sub-Articles

Each sub-article gets valid frontmatter. The **first sub-article** keeps the LLM-generated frontmatter from `create_new_article`. **Subsequent sub-articles** are created fresh via `create_new_article` with a modified title:

- Part 1: title = original title (LLM generates it naturally)
- Part 2+: title = `"{original_title} (Part N)"`

The `sources:` frontmatter field naturally reflects only the sources that went into that sub-article, since each sub-article is created/merged independently.

### Return Type Change for `_merge_batch_split`

Current: `tuple[str, list[str], int]` — `(final_content, all_rel_paths, n_batches)`

New: `tuple[list[tuple[str, str]], list[str], int]` — `(articles, all_rel_paths, n_batches)` where `articles` is a list of `(article_path, content)` pairs.

- When no sub-article split occurs: `articles = [(original_art_path, content)]`
- When sub-article split occurs: `articles = [(part1_path, content1), (part2_path, content2), ...]`

### Stale Sub-Article Cleanup (Addresses Review Medium #1)

**Problem**: When re-compiles produce fewer sub-articles than a prior run, orphaned `-part-N` files persist with outdated content. This is a **new** failure mode introduced by this feature — today `_merge_batch_split` writes to exactly one path, so no orphans can exist.

**Solution**: Before writing new sub-articles in `_process_article`, scan the parent directory for existing `{stem}-part-*.md` files and remove any that exist. Then write the new sub-articles. This is a clean "delete all, write all" approach that avoids complex "keep some, delete some" logic.

```python
def _cleanup_stale_sub_articles(store: KBStore, art_path: str) -> list[str]:
    """Remove any existing -part-N.md files for the given article path.
    
    Returns the list of removed file paths (relative) for logging.
    """
    stem = Path(art_path).stem  # e.g. "foo"
    parent = (store.base_dir / art_path).parent
    if not parent.exists():
        return []
    removed = []
    # Match foo-part-1.md, foo-part-2.md, etc. but NOT foo-bar-part-1.md
    import re
    pattern = re.compile(rf"^{re.escape(stem)}-part-\d+\.md$")
    for p in sorted(parent.iterdir()):
        if p.is_file() and pattern.match(p.name):
            p.unlink()
            removed.append(str(p.relative_to(store.base_dir)))
    return removed
```

**When invoked**: In both call sites in `_process_article` that call `_merge_batch_split`, BEFORE writing any sub-article files:
- Before the `for sub_path, sub_content in articles:` write loop

This cleanup also runs when `len(articles) == 1` (no sub-article split). If a prior run produced sub-articles but the current run doesn't (e.g., fewer sources), the stale `-part-N` files are cleaned up and the single article is written to the original path. This is correct: the original path's content is the complete merged result.

### Content Deduplication on Merge-Batch-Split Path (Addresses Review Medium #2)

**Problem**: When `article_content` is not None (merging into existing article, e.g., `foo.md` has 10 sources from Run 1, Run 2 adds 60 more), `foo-part-1.md` starts from the existing `foo.md` content and merges more sources into it. Both `foo.md` and `foo-part-1.md` exist on disk, with `foo-part-1.md` being a superset of `foo.md`. The index lists both, duplicating content.

**Solution**: When sub-articles are produced (regardless of whether `article_content` was None or not), **delete the original `art_path` file** if it exists on disk, then write only the sub-article files. The original file's content is not lost — it was used as the starting point for `foo-part-1.md`.

Concretely, in `_process_article`, after `_merge_batch_split` returns and when `len(articles) > 1`:
1. Call `_cleanup_stale_sub_articles(store, art_path)` — removes old `-part-N` files
2. Remove the original `art_path` file if it exists on disk
3. Write each sub-article file

When `len(articles) == 1` (no split):
1. Call `_cleanup_stale_sub_articles(store, art_path)` — removes old `-part-N` files from prior runs
2. Write the single article to its original `art_path` — this is the existing behavior

This means:
- **Run 1** (10 sources → `foo.md`): writes `foo.md` only
- **Run 2** (60 more sources, split triggered): deletes `foo.md`, writes `foo-part-1.md` (built on top of old `foo.md` content + new sources) and `foo-part-2.md`
- **Run 3** (fewer sources, no split): deletes `foo-part-1.md` and `foo-part-2.md`, writes `foo.md` only

### Integration with State Tracking

When sub-articles are produced, state tracking records the **original classified `art_path`** (not the sub-article paths) in:

- `_file_done_articles[rel].add(art_path)` — the original path, so that `completed_ops` contains the classified path
- `_file_done_ops[rel] += 1` — the op count, unchanged

**Why the original path?** Because the re-compile skip logic checks `merge["path"] in previously_done` where `merge["path"]` is the classified path (`wiki/concept/foo.md`). If we recorded sub-article paths instead, the skip logic would never match and sources would be re-processed every compile.

### Flow Diagram

```
_merge_batch_split() with 80 items, article_content=None:

  Budget = 70000 → pack 15 items → create_new_article → article = 12K chars
  Budget = 64000 → pack 12 items → merge_into_article → article = 24K chars
  Budget = 52000 → pack 10 items → merge_into_article → article = 38K chars
  Budget = 38000 → pack 8 items  → merge_into_article → article = 52K chars
  Budget = 24000 → pack 6 items  → merge_into_article → article = 64K chars
  Budget = 12000 → pack 3 items  → merge_into_article → article = 70K chars
  Budget = 6000  → pack 2 items  → merge_into_article → article = 74K chars
  Budget = 1800  → BELOW THRESHOLD! Finalize as foo-part-1.md
  
  New article_content=None, remaining = 24 items
  Budget = 70000 → pack 15 items → create_new_article → article = 12K chars
  ... (repeat, may produce foo-part-2.md, foo-part-3.md, etc.)
  
  Final remaining batch → finalize as foo-part-N.md (last part)
```

## 4. Interface Contracts

There are no new HTTP API endpoints. All changes are internal to the Python compile pipeline. The contracts below define internal function signatures, constants, return types, and log output formats.

### 4.1 New Constant: `_SUB_ARTICLE_BUDGET_THRESHOLD`

**Location**: `py/src/kb_ai/core/merge.py`

```python
# When the merge budget for an intermediate article drops below this threshold
# during iterative batch-split merging, the article is finalized as a sub-article
# and a new article starts for the remaining sources. Set above the budget floor
# (200) to ensure each extraction gets meaningful content.
_SUB_ARTICLE_BUDGET_THRESHOLD = 2000
```

**Type**: `int`
**Visibility**: module-level, exported (imported in compile.py via leading-underscore import, following the existing pattern of `_estimate_full_extraction_size`)
**Placement**: After `_MERGE_FRAMING_CHARS` definition (currently at merge.py line ~44)

### 4.2 New Function: `_sub_article_path`

**Location**: `py/src/kb_ai/commands/compile.py` (private to compile module)

```python
def _sub_article_path(base_path: str, part_num: int) -> str:
    """Derive a sub-article path by appending '-part-N' before the .md extension.

    Args:
        base_path: The original article path, e.g. "wiki/concept/foo.md".
        part_num: The part number (1-indexed).

    Returns:
        The sub-article path, e.g. "wiki/concept/foo-part-1.md".

    Examples:
        >>> _sub_article_path("wiki/concept/foo.md", 1)
        'wiki/concept/foo-part-1.md'
        >>> _sub_article_path("wiki/concept/foo.md", 3)
        'wiki/concept/foo-part-3.md'
    """
    stem = base_path[:-3]  # strip ".md"
    return f"{stem}-part-{part_num}.md"
```

**Return type**: `str`
**Invariants**:
- Always ends with `.md`
- The directory portion is preserved exactly
- `part_num` is always ≥ 1
- Input always ends in `.md` (all wiki article paths do by construction)
- No fallback for non-`.md` paths — caller ensures `.md` suffix

### 4.3 New Function: `_cleanup_stale_sub_articles`

**Location**: `py/src/kb_ai/commands/compile.py` (private to compile module)

```python
import re as _re

def _cleanup_stale_sub_articles(store: KBStore, art_path: str) -> list[str]:
    """Remove existing -part-N.md files for the given base article path.

    Called before writing new sub-articles (or a single merged article) to
    prevent orphaned sub-article files from prior runs.

    Args:
        store: The KBStore instance.
        art_path: The base article path, e.g. "wiki/concept/foo.md".

    Returns:
        List of removed file paths (relative to store.base_dir), for logging.
        Empty if no stale files existed.
    """
```

**Return type**: `list[str]`
**Behavior**:
- Scans the parent directory of `art_path` for files matching `{stem}-part-\d+\.md`
- Only matches the exact stem — `foo-part-1.md` matches for `foo.md`, but `foo-bar-part-1.md` does NOT match
- Removes matched files via `Path.unlink()`
- Returns relative paths of removed files for logging
- If parent directory doesn't exist, returns empty list
- Thread-safe: each article group writes to a unique directory path, so no two threads scan the same directory for the same stem

### 4.4 Modified Function: `_merge_batch_split`

**Location**: `py/src/kb_ai/commands/compile.py`

**New signature**:
```python
def _merge_batch_split(
    art_path: str,
    items: list[tuple[str, ExtractionResult]],
    write_model: str,
    *,
    article_content: str | None,
    article_type: str = "",
    title: str = "",
) -> tuple[list[tuple[str, str]], list[str], int]:
```

**Return type**: `tuple[list[tuple[str, str]], list[str], int]`

**Return type detail**:
- `articles: list[tuple[str, str]]` — each tuple is `(path, content)`:
  - `path`: the file path where the content should be written (either the original `art_path` when no split, or `_sub_article_path(art_path, N)` for sub-articles)
  - `content`: the full article content including frontmatter
- `all_rel_paths: list[str]` — source rel paths in order
- `n_batches: int` — total batch count

**Behavior contract**:
- When ALL items fit without hitting the threshold: returns `[(art_path, content)]` — single entry, the original path
- When sub-article split triggers: returns `[(part1_path, content1), (part2_path, content2), ...]`
- Part numbering always starts at 1

**Budget caching (Addresses Review Optimization #1)**: The budget from `estimate_merge_budget` is computed once per loop iteration. When the threshold check passes (budget >= threshold), the same budget value is reused for `_pack_merge_batch` — no redundant call.

**Pseudocode**:

```python
def _merge_batch_split(...) -> tuple[list[tuple[str, str]], list[str], int]:
    all_rels: list[str] = []
    remaining = list(items)
    current_content = article_content
    batch_num = 0
    finalized_articles: list[tuple[str, str]] = []
    part_num = 0
    current_source_count = 0

    while remaining:
        # Check sub-article threshold
        if current_content is not None:
            budget = estimate_merge_budget(current_content)
            if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
                part_num += 1
                sub_path = _sub_article_path(art_path, part_num)
                finalized_articles.append((sub_path, current_content))
                print(f"  [merge-split] {art_path} → sub-article {sub_path} "
                      f"({len(current_content)} chars, {current_source_count} sources)",
                      file=sys.stderr, flush=True)
                current_content = None
                current_source_count = 0
                # budget is stale now; will be recomputed below as create budget
            # else: budget is valid, reuse it below

        batch_num += 1

        # Compute budget for batch packing
        if current_content is None:
            part_title = title if not finalized_articles else f"{title} (Part {part_num + 1})"
            budget = estimate_create_budget(article_type, part_title, remaining)
        # else: budget already set from the threshold check above (no redundant call)

        batch, remaining = _pack_merge_batch(remaining, budget)
        combined, batch_rels = _combine_extractions(batch)
        all_rels.extend(batch_rels)
        current_source_count += len(batch)

        if current_content is None:
            part_title = title if not finalized_articles else f"{title} (Part {part_num + 1})"
            print(f"  [merge-split] {art_path} batch {batch_num}: "
                  f"create ← {len(batch)} sources", file=sys.stderr, flush=True)
            current_content = create_new_article(
                article_type, part_title, combined,
                ", ".join(batch_rels), model=write_model)
        else:
            print(f"  [merge-split] {art_path} batch {batch_num}: "
                  f"merge ← {len(batch)} sources", file=sys.stderr, flush=True)
            current_content = merge_into_article(
                art_path, current_content, combined,
                ", ".join(batch_rels), model=write_model)

    # Finalize the last article
    if current_content is not None:
        if finalized_articles:
            part_num += 1
            sub_path = _sub_article_path(art_path, part_num)
            finalized_articles.append((sub_path, current_content))
        else:
            finalized_articles.append((art_path, current_content))

    return finalized_articles, all_rels, batch_num
```

**Note on `merge_into_article` path argument**: When constructing sub-article parts 2+ (batches after the first create for a new sub-article), `merge_into_article` receives the original `art_path` rather than the sub-article-in-progress path. This is because `art_path` is used inside `merge_into_article` only for logging and diff path context — it does not affect content generation correctness. Passing the original path keeps the log messages traceable to the classified article group. (Addresses Review Optimization #5 — acknowledged, not changed.)

### 4.5 Modified Callers in `_process_article`

#### 4.5a. The `[merge→create-split]` path (~line 689)

**Current code**:
```python
new_content, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=None, article_type=article_type, title=title)
store.write_article(art_path, new_content)
```

**New code**:
```python
articles, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=None, article_type=article_type, title=title)
_cleanup_stale_sub_articles(store, art_path)
if len(articles) > 1:
    # Delete original if it existed (shouldn't on create path, but defensive)
    orig = store.base_dir / art_path
    if orig.exists():
        orig.unlink()
for sub_path, sub_content in articles:
    store.write_article(sub_path, sub_content)
```

**Log format**:
```python
sub_info = f", {len(articles)} sub-articles" if len(articles) > 1 else ""
log(f"  [merge→create-split] {art_path} ← {len(merges)} sources "
    f"({n_batches} batches{sub_info}) — ${op_cost.total_cost:.4f}")
```

**State tracking**: unchanged — records the original `art_path` in `_file_done_articles` and `_file_done_ops`.

#### 4.5b. The `[merge-batch-split]` path (~line 749)

**Current code**:
```python
new_content, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=old_content)
store.write_article(art_path, new_content)
```

**New code**:
```python
articles, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=old_content)
_cleanup_stale_sub_articles(store, art_path)
if len(articles) > 1:
    # Delete original article — its content is incorporated into part-1
    orig = store.base_dir / art_path
    if orig.exists():
        orig.unlink()
for sub_path, sub_content in articles:
    store.write_article(sub_path, sub_content)
```

**State tracking**: unchanged.

**Log format**: same pattern as 4.5a.

### 4.6 Imports Update

**File**: `py/src/kb_ai/commands/compile.py`

The existing import block (lines 39-46):
```python
from kb_ai.core.merge import (
    _estimate_full_extraction_size,
    create_new_article,
    estimate_create_budget,
    estimate_merge_budget,
    merge_into_article,
    write_prompt_version,
)
```

**Add** `_SUB_ARTICLE_BUDGET_THRESHOLD` to this existing import:
```python
from kb_ai.core.merge import (
    _SUB_ARTICLE_BUDGET_THRESHOLD,
    _estimate_full_extraction_size,
    create_new_article,
    estimate_create_budget,
    estimate_merge_budget,
    merge_into_article,
    write_prompt_version,
)
```

Also add `import re` at the top of the file (for `_cleanup_stale_sub_articles`). The `re` module is from the standard library and should be placed with other stdlib imports.

### 4.7 Updated `.compile.log` Format

**Existing tags** (unchanged when no sub-article split):
```
  [merge→create-split] wiki/concept/foo.md ← 9 sources (3 batches) — $0.0234
  [merge-batch-split] wiki/concept/bar.md ← 7 sources (2 batches) — $0.0189
```

**Updated tags when sub-article split occurs**:
```
  [merge→create-split] wiki/concept/foo.md ← 80 sources (12 batches, 3 sub-articles) — $0.1234
  [merge-batch-split] wiki/concept/bar.md ← 60 sources (9 batches, 2 sub-articles) — $0.0989
```

**New stderr line when sub-article is finalized**:
```
  [merge-split] wiki/concept/foo.md → sub-article wiki/concept/foo-part-1.md (74123 chars, 27 sources)
```

**Stderr line when stale sub-articles are cleaned up** (only when files are actually removed):
```
  [merge-split] wiki/concept/foo.md: cleaned up 3 stale sub-article(s)
```

### 4.8 Unchanged External Interfaces

- No changes to Go bridge protocol
- No changes to `compile_kb()` return dict shape
- No changes to `DeriveReport` or derive types
- No new environment variables (see note below)
- `create_new_article()` and `merge_into_article()` signatures unchanged
- `_combine_extractions()` signature unchanged
- `.compile-state.json` format unchanged
- `_pack_merge_batch()` signature unchanged
- Master index rebuilt from disk — sub-articles discovered automatically

**Note on env-var configurability (Addresses Review Optimization #4)**: The threshold constant is not exposed as an env var in this plan. Unlike `_WRITE_CALL_TIMEOUT_S` (which needs per-deployment tuning for local vs. cloud models), the budget threshold has a single correct regime: it should trigger when the article has consumed ~92% of prompt budget. If tuning is needed, the constant is a single line change. Env-var exposure can be added later if operators request it.

## 5. Implementation Steps

### Step 1: Add `_SUB_ARTICLE_BUDGET_THRESHOLD` to merge.py

**File**: `py/src/kb_ai/core/merge.py`

Add the constant after `_MERGE_FRAMING_CHARS` (currently defined around line 44):

```python
# When the merge budget for an intermediate article drops below this threshold
# during iterative batch-split merging, the article is finalized as a sub-article
# and a new article starts for the remaining sources. Set above the budget floor
# (200) to ensure each extraction gets meaningful content — at 2000 chars, a
# source's summary and partial list fields survive truncation.
_SUB_ARTICLE_BUDGET_THRESHOLD = 2000
```

**Depends on**: nothing.
**Verification**: import succeeds; constant is accessible from compile.py.

### Step 2: Add `_sub_article_path` and `_cleanup_stale_sub_articles` to compile.py

**File**: `py/src/kb_ai/commands/compile.py`

Add `import re` to the stdlib imports at the top of the file (after `import os`).

Add two helper functions before `_pack_merge_batch` (currently at line ~119):

```python
def _sub_article_path(base_path: str, part_num: int) -> str:
    """Derive a sub-article path by appending '-part-N' before .md extension.

    >>> _sub_article_path("wiki/concept/foo.md", 1)
    'wiki/concept/foo-part-1.md'
    >>> _sub_article_path("wiki/concept/foo-bar.md", 2)
    'wiki/concept/foo-bar-part-2.md'
    """
    stem = base_path[:-3]  # strip ".md"; all wiki paths end in .md by construction
    return f"{stem}-part-{part_num}.md"


def _cleanup_stale_sub_articles(store: KBStore, art_path: str) -> list[str]:
    """Remove existing -part-N.md files for the given base article path.

    Called before writing new sub-articles (or a single merged article) to
    prevent orphaned sub-article files from prior runs appearing in the index.

    Returns list of removed file paths (relative to store.base_dir).
    """
    stem = Path(art_path).stem  # e.g. "foo" from "wiki/concept/foo.md"
    parent = (store.base_dir / art_path).parent
    if not parent.exists():
        return []
    removed: list[str] = []
    pattern = re.compile(rf"^{re.escape(stem)}-part-\d+\.md$")
    for p in sorted(parent.iterdir()):
        if p.is_file() and pattern.match(p.name):
            p.unlink()
            removed.append(str(p.relative_to(store.base_dir)))
    return removed
```

**Depends on**: nothing.
**Verification**: unit tests in Step 6.

### Step 3: Update the import in compile.py

**File**: `py/src/kb_ai/commands/compile.py`

Add `_SUB_ARTICLE_BUDGET_THRESHOLD` to the existing import from `kb_ai.core.merge`:

```python
from kb_ai.core.merge import (
    _SUB_ARTICLE_BUDGET_THRESHOLD,
    _estimate_full_extraction_size,
    create_new_article,
    estimate_create_budget,
    estimate_merge_budget,
    merge_into_article,
    write_prompt_version,
)
```

**Depends on**: Step 1.
**Verification**: import succeeds.

### Step 4: Modify `_merge_batch_split` to support sub-article splitting

**File**: `py/src/kb_ai/commands/compile.py`

Replace the current `_merge_batch_split` function body with the sub-article-aware version. Key changes:

1. **Return type changes** from `tuple[str, list[str], int]` to `tuple[list[tuple[str, str]], list[str], int]`
2. **Add sub-article finalization logic**: when `estimate_merge_budget(current_content) < _SUB_ARTICLE_BUDGET_THRESHOLD` and remaining items exist, finalize current content as a sub-article and reset `current_content = None`
3. **Cache budget**: reuse the budget computed in the threshold check (no redundant call to `estimate_merge_budget`)
4. **Track `finalized_articles`**: list of `(path, content)` pairs
5. **Track `current_source_count`**: for the stderr log
6. **Part numbering**: starts at 0, incremented on each finalization
7. **Title for subsequent parts**: `"{title} (Part N)"`
8. **Final article**: if any sub-articles were finalized, the last batch is also a sub-article; otherwise single article at original path

Full implementation follows the pseudocode in Section 4.4.

**Depends on**: Steps 1, 2, 3.
**Verification**: unit tests in Step 6.

### Step 5: Update the two call sites in `_process_article`

**File**: `py/src/kb_ai/commands/compile.py`

#### 5a. Update existing tests for new return type (MANDATORY — must be done before running tests)

The 3 existing tests in `py/tests/test_compile_batch_split.py` (`test_creates_then_merges`, `test_merge_only`, `test_single_batch`) that destructure the return as `content, all_rels, n_batches` must be updated:

```python
# Before:
content, all_rels, n_batches = cm._merge_batch_split(...)
assert "merged" in content

# After:
articles, all_rels, n_batches = cm._merge_batch_split(...)
assert len(articles) == 1
content = articles[0][1]
assert "merged" in content
```

Each of these tests uses monkeypatched budgets that produce small fake articles (~50 chars), so the merge budget stays well above the threshold and no sub-article split occurs → `len(articles) == 1`.

The `test_error_mid_batch` test doesn't check the return value (it asserts an exception is raised) and needs no change.

#### 5b. The `[merge→create-split]` path (~line 689)

Update to handle the new return type, clean up stale sub-articles, and delete the original file when splitting:

```python
articles, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=None, article_type=article_type, title=title)
removed = _cleanup_stale_sub_articles(store, art_path)
if removed:
    print(f"  [merge-split] {art_path}: cleaned up {len(removed)} stale sub-article(s)",
          file=sys.stderr, flush=True)
if len(articles) > 1:
    orig = store.base_dir / art_path
    if orig.exists():
        orig.unlink()
for sub_path, sub_content in articles:
    store.write_article(sub_path, sub_content)
```

Log line update:
```python
sub_info = f", {len(articles)} sub-articles" if len(articles) > 1 else ""
log(f"  [merge→create-split] {art_path} ← {len(merges)} sources "
    f"({n_batches} batches{sub_info}) — ${op_cost.total_cost:.4f}")
```

#### 5c. The `[merge-batch-split]` path (~line 749)

Same pattern as 5b:

```python
articles, merge_rels, n_batches = _merge_batch_split(
    art_path, items, write_model,
    article_content=old_content)
removed = _cleanup_stale_sub_articles(store, art_path)
if removed:
    print(f"  [merge-split] {art_path}: cleaned up {len(removed)} stale sub-article(s)",
          file=sys.stderr, flush=True)
if len(articles) > 1:
    orig = store.base_dir / art_path
    if orig.exists():
        orig.unlink()
for sub_path, sub_content in articles:
    store.write_article(sub_path, sub_content)
```

Log line update: same pattern as 5b.

**Depends on**: Step 4.
**Verification**: integration tests in Step 6.

### Step 6: Write tests

**File**: `py/tests/test_compile_batch_split.py`

#### 6a. Update existing tests (as described in Step 5a)

Update the 3 tests that check `_merge_batch_split` return values to use the new `articles` return shape.

#### 6b. New unit tests

1. **`test_sub_article_path`**: Unit test for the `_sub_article_path` helper.
   ```python
   def test_sub_article_path():
       assert cm._sub_article_path("wiki/concept/foo.md", 1) == "wiki/concept/foo-part-1.md"
       assert cm._sub_article_path("wiki/concept/foo.md", 3) == "wiki/concept/foo-part-3.md"
       assert cm._sub_article_path("wiki/concept/foo-bar.md", 2) == "wiki/concept/foo-bar-part-2.md"
   ```

2. **`test_cleanup_stale_sub_articles`**: Unit test for cleanup helper.
   ```python
   def test_cleanup_stale_sub_articles(tmp_path):
       store = KBStore(str(tmp_path))
       parent = tmp_path / "wiki" / "concept"
       parent.mkdir(parents=True)
       # Create stale sub-articles and an unrelated file
       (parent / "foo-part-1.md").write_text("old part 1")
       (parent / "foo-part-2.md").write_text("old part 2")
       (parent / "foo-part-3.md").write_text("old part 3")
       (parent / "foo-bar-part-1.md").write_text("different article")
       (parent / "foo.md").write_text("original")
       
       removed = cm._cleanup_stale_sub_articles(store, "wiki/concept/foo.md")
       
       assert len(removed) == 3
       assert not (parent / "foo-part-1.md").exists()
       assert not (parent / "foo-part-2.md").exists()
       assert not (parent / "foo-part-3.md").exists()
       assert (parent / "foo-bar-part-1.md").exists()  # not touched
       assert (parent / "foo.md").exists()  # not touched by cleanup
   ```

3. **`test_cleanup_stale_sub_articles_no_dir`**: Cleanup on nonexistent dir returns empty.
   ```python
   def test_cleanup_stale_sub_articles_no_dir(tmp_path):
       store = KBStore(str(tmp_path))
       removed = cm._cleanup_stale_sub_articles(store, "wiki/concept/foo.md")
       assert removed == []
   ```

4. **`test_merge_batch_split_produces_sub_articles`**: Monkeypatch `estimate_merge_budget` to return below `_SUB_ARTICLE_BUDGET_THRESHOLD` after the first create's article is "large". Verify:
   - `len(articles) > 1`
   - Each article path has the `-part-N` suffix
   - `all_rels` contains all source rel paths
   - Part numbering is sequential starting at 1

5. **`test_merge_batch_split_no_sub_article_when_budget_ok`**: Monkeypatch budgets to stay above threshold. Verify `len(articles) == 1` and path is the original `art_path`.

6. **`test_merge_batch_split_sub_article_titles`**: Verify that the first sub-article uses the original title and subsequent sub-articles have `"(Part N)"` in the title. Capture the `title` argument passed to `create_new_article`.

7. **`test_merge_batch_split_budget_reuse`**: Verify that `estimate_merge_budget` is called exactly once per iteration (not twice). Use a side-effect counter on the monkeypatched function.

#### 6c. New integration tests

8. **`test_process_article_sub_article_files_written`**: Integration test via `compile_kb`. Monkeypatch to trigger sub-article split by making `create_new_article` return a large article (~75K chars) for the first create call, and `estimate_merge_budget` return below threshold for that content. Verify that `-part-1.md` and `-part-2.md` files exist on disk and the original `art_path` file does NOT exist.

9. **`test_process_article_sub_article_state_tracking`**: Integration test. Verify that after sub-article split, the `.compile-state.json` records the original `art_path` in `completed_ops`, NOT the sub-article paths.

10. **`test_process_article_sub_article_log_tag`**: Integration test. Verify that the compile log contains `sub-articles` text when a split occurs.

11. **`test_stale_sub_article_cleanup_on_recompile`**: Integration test. First compile produces sub-articles. Second compile (with different monkeypatch) produces a single article. Verify that the stale `-part-N` files are removed and only the single article file exists.

12. **`test_merge_batch_split_deletes_original_on_sub_split`**: Integration test for the merge-into-existing path. Create `foo.md` on disk, then compile with enough sources to trigger sub-article split. Verify `foo.md` is deleted and `foo-part-1.md`, `foo-part-2.md` exist.

#### 6d. Existing tests — no changes needed

`test_process_article_merge_create_split`, `test_process_article_merge_batch_split`, and `test_process_article_under_threshold_unchanged` should still pass because:
- The monkeypatched `create_new_article` returns small articles (~50 chars)
- The monkeypatched/real `estimate_merge_budget` returns well above 2000 for ~50 char articles
- No sub-article split is triggered
- The new return type is handled uniformly (single-element list)

Wait — these tests destructure the return of `compile_kb`, not `_merge_batch_split` directly. They check log output and error counts. The internal change to `_merge_batch_split`'s return type is handled by the updated call sites in `_process_article`. These tests should pass without modification.

**Depends on**: Steps 1–5.
**Verification**: `pytest py/tests/test_compile_batch_split.py -v` passes all tests.

## 6. Risks and Mitigations

### R1: Sub-articles may fragment knowledge awkwardly

**Risk**: The split point is determined by article size, not by semantic boundaries.

**Mitigation**: The threshold (~74K article) means each sub-article is substantial and standalone. The LLM creates each via the same quality-controlled paths. Splitting is better than the status quo (catastrophic truncation at 200-char budget). The stderr log `→ sub-article` lines make split points easy to identify for review.

### R2: Stale sub-article cleanup race condition

**Risk**: `_cleanup_stale_sub_articles` scans the directory and deletes files. If two article groups write sub-articles to the same directory concurrently, could they interfere?

**Mitigation**: No. Each article group has a unique `art_path` and the cleanup regex matches only `{exact_stem}-part-\d+\.md`. Two different articles (e.g., `foo.md` and `bar.md`) have different stems, so their cleanups don't interfere. Two groups cannot have the same `art_path` because `article_ops` is keyed by path.

### R3: Re-compile with different sources may produce different part counts

**Risk**: Old `-part-N` files linger from prior runs.

**Mitigation**: The `_cleanup_stale_sub_articles` function runs before every write in the sub-article path, removing ALL existing `-part-N` files regardless of how many the current run produces. This handles: fewer parts (orphans removed), more parts (old ones removed before new ones written), and zero parts (single article written, all parts removed).

### R4: Original file deletion on merge-batch-split path

**Risk**: When `article_content is not None` and sub-articles are produced, the original file is deleted. If the sub-article writes fail after the deletion, content is lost.

**Mitigation**: The deletion happens after `_merge_batch_split` returns successfully (the content is in memory). `store.write_article` is a simple `Path.write_text()` — it can only fail on disk-full or permission errors, which would also fail the original single-file write. The risk is equal to the existing behavior where `merge_into_article` overwrites the original file atomically.

### R5: State tracking records original path for sub-article splits

**Risk**: The `completed_ops` state records `wiki/concept/foo.md` even though the actual files are `-part-N`. If the original `foo.md` is later recreated (e.g., by a different source's create op), the state appears inconsistent.

**Mitigation**: This is the correct behavior. The state tracks "which classified article paths have been processed for this source file", not "which files exist on disk". The re-compile skip logic checks `merge["path"] in previously_done` where `merge["path"]` comes from classification output. The skip works correctly regardless of what files exist on disk.

### R6: Budget threshold may need tuning

**Risk**: `_SUB_ARTICLE_BUDGET_THRESHOLD = 2000` may not be optimal for all content profiles.

**Mitigation**: The constant is a single line change with no structural impact. The stderr log shows article size at each finalization point. If env-var configurability is needed later, it's a trivial addition (following the `_WRITE_CALL_TIMEOUT_S` pattern).

### R7: Existing tests break due to return type change

**Risk**: The 3 existing `TestMergeBatchSplit` tests destructure the return as `content, all_rels, n_batches`.

**Mitigation**: Step 5a explicitly requires updating these tests before running the test suite. The update is mechanical: `articles, all_rels, n_batches = ...` and `content = articles[0][1]`. The `test_error_mid_batch` test needs no change (it asserts an exception).
