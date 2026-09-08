# Parallelize Batch-Level LLM Calls Within the Write Phase

## 1. Background and Goals

### Why are we doing this?
The `_merge_batch_split` function in `compile.py` processes batches serially: each LLM call (create/merge) waits for the previous one to complete before starting. When one article accumulates many source documents (common in topical derives), this serial loop becomes a long-tail bottleneck — one `_process_article` worker holds up the entire write phase while other workers idle. Real-world traces show 20+ serial batches turning a 15-minute-capable run into 38 minutes.

### What do we want to achieve?
- **Target**: Reduce 38-min derive to ~15 min.
- **Mechanism**: When `_merge_batch_split` detects a sub-article split (budget below `_SUB_ARTICLE_BUDGET_THRESHOLD`), the remaining items start fresh `create_new_article` chains that are fully independent. Pre-split all remaining items into multiple independent chunks and run them as concurrent chains.
- **Example**: 20 serial batches (40 min) → Chain 0 runs 4 batches serially (8 min), then 4 concurrent chains of ~4 batches each (8 min) → total ~16 min.

### Scope
- **In scope**: Refactoring `_merge_batch_split` to detect sub-article split boundaries and fan out continuation chains in parallel; adding a process-wide semaphore for write-LLM concurrency; new tests.
- **Out of scope**: Changing extract/classify phases; changing the outer `_process_article` dispatch; async rewrite; changing LLM call internals.

## 2. Current State Analysis

### The serial bottleneck
`_merge_batch_split` (compile.py ~lines 190–305) runs a `while remaining:` loop. Each iteration:
1. Checks if `budget < _SUB_ARTICLE_BUDGET_THRESHOLD` → if so, finalizes the current sub-article and sets `current_content = None`.
2. Packs one batch via `_pack_merge_batch`.
3. Calls `create_new_article` (if `current_content is None`) or `merge_into_article` (otherwise).
4. Updates `current_content` with the result.

**Within a single sub-article chain**, batch N+1 depends on batch N's output — inherently serial. **Across sub-article chains**, there is zero dependency: after a split, remaining items start a fresh `create_new_article` that reads nothing from the finalized sub-article.

### Key observation for parallelism
After Chain 0's first sub-article split, all remaining items will start fresh chains with `article_content=None`. For fresh chains:
- `estimate_create_budget` depends only on `(article_type, title, items)` — all known upfront.
- `_pack_merge_batch` is a pure function.
- We can **pre-split** the remaining items into multiple independent chunks and launch each chunk as a concurrent chain.

This pre-splitting produces potentially more sub-articles than the serial code (because the serial code might fit items from two "would-be chains" into one sub-article when the first chain has room after its initial batches). This is an acceptable semantic difference: sub-articles are already a supported output format, and having slightly more smaller sub-articles does not degrade quality.

### Existing concurrency patterns followed
1. **Section-merge semaphore** (`merge.py`): `_SECTION_MERGE_MAX_CONCURRENT=12` semaphore, `_get_section_sem()` with env override, per-invalid-value warning.
2. **Context propagation**: `adopt_context(parent_ctx, phase=...)` in worker threads.
3. **Cost tracking**: `_measure_op_cost()` installs a nested `CostTracker`; child threads inherit `request_tracker` by reference.

### Thread safety (all green)
All components touched by `_run_chain` are thread-safe: `completion()`, `create_new_article`, `merge_into_article` (pure functions + contextvars), `CostTracker` (internal lock), `log()` (internal lock), `_write_lock`-protected state. `store.write_article()` has no internal lock but paths never collide across chains (each chain writes to different `-part-N.md` paths).

## 3. Technical Design

### 3.1 Three-phase architecture for `_merge_batch_split`

**Phase A — Serial Chain 0 (calling thread):** Runs the existing serial `while remaining:` loop verbatim until either (a) all items are processed (no split → fast path return, identical to today) or (b) a sub-article split is detected. On split: break out of the loop with `finalized_articles`, `remaining`, `part_num`, `batch_num`, `all_rels` captured.

**Critical**: Phase A reuses the existing serial loop code directly on the calling thread. It does NOT use `_run_chain` and does NOT call `adopt_context`. The calling thread's context already has `_measure_op_cost`'s `op_tracker` installed as `request_tracker`. This preserves the existing cost propagation chain without disruption.

**Phase B — Pre-split + parallel dispatch (child threads):** The remaining items (with `article_content=None`) are pre-split into independent chunks using `_pre_split_chains()`. Each chunk is dispatched to `_run_chain` via a `ThreadPoolExecutor`. Each `_run_chain` call:
- Calls `adopt_context(chain_ctx, phase=...)` where `chain_ctx` was captured inside the `_measure_op_cost` block (so `request_tracker` = `op_tracker`).
- Runs its own serial `while remaining:` loop, handling internal sub-article splits serially.
- Acquires the process-wide semaphore before each LLM call.
- Returns a `_ChainResult`.

**Phase C — Collect + re-number:** Wait on all futures. Merge results. Re-number all sub-articles sequentially (1, 2, 3, ...) to produce clean part paths.

### 3.2 Pre-splitting algorithm: `_pre_split_chains`

After Chain 0 splits, all remaining items need fresh `create_new_article` chains. We greedily partition them:

```python
def _pre_split_chains(
    items: list[tuple[str, ExtractionResult]],
    article_type: str,
    title: str,
    target_batches_per_chain: int = 3,
) -> list[list[tuple[str, ExtractionResult]]]:
```

Algorithm:
1. Estimate `create_budget` for the items.
2. Greedily pack items into batches via `_pack_merge_batch` to count how many batches the full set would need.
3. Divide into `ceil(total_batches / target_batches_per_chain)` chains, each getting `target_batches_per_chain` worth of items.
4. Return list of item-lists, one per chain.

`target_batches_per_chain=3` is a tuning knob: lower = more parallelism + more sub-articles; higher = fewer sub-articles + less parallelism. 3 is chosen because it keeps chain latency at ~3 LLM calls (~6 min) while the typical split scenario has 15-20 total batches → 5-7 chains → good parallelism.

**Simpler alternative**: Instead of batch-counting, split by item count. Estimate items_per_batch from `create_budget / avg_item_size`, multiply by `target_batches_per_chain`, and chunk the items list. This avoids the cost of pre-running `_pack_merge_batch` over all items.

We use the simpler alternative:
```python
def _pre_split_chains(items, article_type, title, target_batches_per_chain=3):
    budget = estimate_create_budget(article_type, title, items)
    budget = min(budget, _MAX_BATCH_BUDGET)
    avg_size = sum(_estimate_full_extraction_size(ext, rel) for rel, ext in items) / len(items)
    items_per_batch = max(1, int(budget / avg_size))
    chunk_size = max(1, items_per_batch * target_batches_per_chain)
    return [items[i:i+chunk_size] for i in range(0, len(items), chunk_size)]
```

### 3.3 Concurrency control: `_BATCH_PARALLEL_MAX_CONCURRENT`

Process-wide `threading.Semaphore`, default 6 permits. Follows the exact pattern of `_get_section_sem()` in merge.py.

- **Environment variable**: `KB_BATCH_PARALLEL_MAX_CONCURRENT` (positive integer).
- **Each LLM call in `_run_chain`** acquires one permit before the call, releases after.
- **Phase A (Chain 0) does NOT use the semaphore** — it runs on the calling thread within the existing `_process_article` worker, same as today.
- **Interaction with `_SECTION_MERGE_MAX_CONCURRENT`**: Independent semaphores. A thread may hold both (batch-parallel acquired first, then section-merge inside `merge_into_article`). No deadlock: both are always acquired then released; no circular dependency.
- **Default 6**: Chosen to keep total write-phase LLM concurrency reasonable. With `write_workers` (default 16) already running, plus section-merge fan-out (12), adding 6 more for batch-parallel keeps the process at ~34 concurrent LLM calls maximum — well within typical LLM proxy capacity.

### 3.4 Context propagation in child threads

Each `_run_chain` child thread must have the correct context for LLM calls. The chain:

1. `_merge_batch_split` is called from `_process_article`, which already ran `adopt_context(_parent_ctx, phase=...)`.
2. `_process_article` wraps the `_merge_batch_split` call in `_measure_op_cost()`, which installs an `op_tracker` as `request_tracker` on the calling thread's context.
3. Before dispatching Phase B, capture `chain_ctx = get_context()` — this snapshot has `op_tracker` as `request_tracker`.
4. Each child thread calls `adopt_context(chain_ctx, phase=f"write-chain:{art_path}")`, which creates a **copy** of `chain_ctx`. The `request_tracker` is shared by reference (intentional per `ThreadContext` docs), so all child LLM costs flow into `op_tracker`.
5. On `_measure_op_cost` exit, `op_tracker.absorb()` folds into the parent tracker. ✓

**Phase A does NOT call `adopt_context`** — it runs on the same thread that entered `_process_article`, which already installed the correct context. Running Phase A through `_run_chain` with `adopt_context` would replace the context that `_measure_op_cost` installed, breaking cost propagation.

### 3.5 Error handling

- If any `_run_chain` future raises, Phase C re-raises the **first** exception encountered (matching current `_merge_batch_split` behavior).
- Remaining futures are allowed to complete naturally (thread cancellation is unreliable and partial results are discarded by the caller's `except` block anyway).
- The caller (`_process_article`) wraps `_merge_batch_split` in a try/except that records errors via `_write_lock`. No change needed there.
- `_run_chain` propagates all exceptions from `create_new_article` / `merge_into_article` without catching them. The `RuntimeError` type is preserved.

### 3.6 Part numbering and re-compaction

Each chain assigns local part numbers starting from a chain-local counter. After all chains complete, Phase C re-numbers all articles sequentially:

```python
# Phase C: collect and re-number
all_articles = list(phase_a_articles)  # Chain 0's sub-articles
for future in as_completed(futures):
    result = future.result()
    all_articles.extend(result.articles)
    all_rels.extend(result.all_rels)
    total_batches += result.n_batches

# Re-number sequentially
renumbered = []
for i, (_old_path, content) in enumerate(all_articles, 1):
    renumbered.append((_sub_article_path(art_path, i), content))
```

This produces clean sequential paths regardless of chain completion order. Chain ordering is preserved because we process futures in chain-index order (not `as_completed`), to maintain deterministic part assignment matching the item order in the original `items` list.

### 3.7 When parallelism doesn't apply

1. **No split occurs**: Phase A runs to completion, returns directly. Zero overhead (no threads, no semaphore).
2. **Only 1 item remaining after split**: No pre-splitting needed; run `_run_chain` on calling thread synchronously (or dispatch to a 1-thread pool — either way, the result is the same).
3. **Pre-split produces only 1 chunk**: Same as above.

## 4. Interface Contracts

### 4.1 New dataclass: `_ChainResult`

**File**: `py/src/kb_ai/commands/compile.py`

```python
@dataclass
class _ChainResult:
    """Result of one independent batch chain within _merge_batch_split."""
    articles: list[tuple[str, str]]
    # (path, content) pairs; paths use chain-local part numbers, re-numbered by caller.
    all_rels: list[str]
    # Source rel_paths processed by this chain, in insertion order.
    n_batches: int
    # Count of LLM calls (create + merge) made by this chain.
```

**Notes**:
- `articles` may contain 1 entry (no internal split) or N entries (internal splits within the chain).
- `articles[i][0]` paths use temporary chain-local numbering; the caller re-numbers them in Phase C.
- `all_rels` order matches the order items were processed (same as the input `items` order).

### 4.2 New function: `_run_chain`

**File**: `py/src/kb_ai/commands/compile.py`

```python
def _run_chain(
    art_path: str,
    items: list[tuple[str, ExtractionResult]],
    write_model: str,
    *,
    article_type: str,
    title: str,
    start_part_num: int,
    parent_ctx: ThreadContext,
    sem: threading.Semaphore | None,
) -> _ChainResult:
    """Run one independent batch chain to completion in a child thread.

    Called ONLY from Phase B child threads, never from Phase A (Chain 0).
    Calls adopt_context(parent_ctx, ...) at entry to install context.

    Args:
        art_path: Base article path.
        items: Source items for this chain (non-empty).
        write_model: LLM model name.
        article_type: Article type string.
        title: Article title for this chain's sub-article(s).
        start_part_num: Starting part number for local numbering.
        parent_ctx: Context captured inside _measure_op_cost block;
                    request_tracker points to the op_tracker.
        sem: Process-wide semaphore; acquired before each LLM call.
             None disables gating (for testing).

    Returns:
        _ChainResult with chain's articles, rels, and batch count.

    Raises:
        RuntimeError: if any LLM call fails (propagated from create/merge).
    """
```

**Contract details**:
- `parent_ctx` MUST be captured via `get_context()` on the calling thread inside the `_measure_op_cost()` block. Child thread calls `adopt_context(parent_ctx, phase=f"write-chain:{art_path}")`.
- When `sem` is not None, each `create_new_article` / `merge_into_article` call is bracketed by `sem.acquire()` / `sem.release()`.
- `article_content` is always `None` for continuation chains (fresh create).
- The function runs the same serial batch loop as the current `_merge_batch_split`, but scoped to this chain's items.
- Internal sub-article splits are handled within the loop (not spawning further threads).

### 4.3 New function: `_pre_split_chains`

**File**: `py/src/kb_ai/commands/compile.py`

```python
def _pre_split_chains(
    items: list[tuple[str, ExtractionResult]],
    article_type: str,
    title: str,
    target_batches_per_chain: int = 3,
) -> list[list[tuple[str, ExtractionResult]]]:
    """Split items into chunks for parallel chain execution.

    Each chunk is sized to require approximately target_batches_per_chain
    LLM batches, estimated from the create budget and average item size.

    Args:
        items: Non-empty list of (rel_path, ExtractionResult) pairs.
        article_type: Article type string.
        title: Base title (used for budget estimation).
        target_batches_per_chain: Target number of batches per chain.
            Lower = more parallelism + more sub-articles.
            Higher = fewer sub-articles + less parallelism.
            Default 3.

    Returns:
        List of item-lists (1 or more), each non-empty. If items has
        fewer items than one chunk, returns [items] (single chunk).
    """
```

**Contract details**:
- Always returns at least 1 chunk.
- Each chunk is non-empty.
- The union of all chunks equals the input `items` in the same order.
- Pure function, no side effects.

### 4.4 New function: `_get_batch_parallel_sem`

**File**: `py/src/kb_ai/commands/compile.py`

```python
_BATCH_PARALLEL_MAX_CONCURRENT: int = 6
_BATCH_PARALLEL_ENV: str = "KB_BATCH_PARALLEL_MAX_CONCURRENT"

_batch_parallel_sem: threading.Semaphore | None = None
_batch_parallel_sem_bound: int = 0

def _get_batch_parallel_sem() -> threading.Semaphore:
    """Process-wide semaphore for batch-parallel LLM calls.

    Follows the _get_section_sem() pattern: reads env per call,
    warns once on invalid values, caches the Semaphore keyed on bound.

    Returns:
        threading.Semaphore with the configured number of permits.
    """
```

**Environment variable contract**:
- `KB_BATCH_PARALLEL_MAX_CONCURRENT`: positive integer.
- Default: 6.
- Invalid (non-integer, ≤0): warn once to stderr, use default.
- Changed at runtime: re-creates semaphore with new bound.

### 4.5 New context manager: `_sem_guard`

**File**: `py/src/kb_ai/commands/compile.py`

```python
@contextmanager
def _sem_guard(sem: threading.Semaphore | None):
    """Acquire/release a semaphore, or no-op if None."""
    if sem is None:
        yield
    else:
        sem.acquire()
        try:
            yield
        finally:
            sem.release()
```

### 4.6 Modified function: `_merge_batch_split`

**File**: `py/src/kb_ai/commands/compile.py`

**Signature unchanged**:
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

**Return type unchanged**: `(articles, all_rel_paths, n_batches)`.

**Behavioral changes**:
1. After Chain 0's first sub-article split, remaining items are pre-split via `_pre_split_chains` and dispatched as concurrent chains.
2. May produce more sub-articles than the serial version (because items that the serial version would merge into a growing chain are instead split across independent fresh chains).
3. Part numbering in returned articles is always sequential (1, 2, 3, ...).
4. When no split occurs, behavior is identical to the current serial code (zero overhead).

**No changes to callers**: `_process_article` receives the same `(articles, all_rels, n_batches)` tuple and writes/logs/tracks state identically.

## 5. Implementation Steps

### Step 1: Add supporting infrastructure

**File**: `py/src/kb_ai/commands/compile.py`

1. Add `from dataclasses import dataclass` to imports.
2. Add `_ChainResult` dataclass after `_DEFAULT_WORKERS` (line ~53).
3. Add `_BATCH_PARALLEL_MAX_CONCURRENT`, `_BATCH_PARALLEL_ENV`, module-level semaphore state, `_get_batch_parallel_sem()` — following the exact pattern of `_get_section_sem()` in `merge.py`.
4. Add `_sem_guard` context manager.
5. Add `_pre_split_chains` function.

**Verification**: Unit test `_get_batch_parallel_sem()` (returns semaphore, respects env, warns on invalid). Unit test `_pre_split_chains` (correct chunking, preserves order, handles edge cases).

### Step 2: Implement `_run_chain`

**File**: `py/src/kb_ai/commands/compile.py`

1. Add `_run_chain` function. The body is the existing `while remaining:` loop from `_merge_batch_split`, adapted:
   - Calls `adopt_context(parent_ctx, phase=f"write-chain:{art_path}")` at entry.
   - Each LLM call wrapped in `with _sem_guard(sem):`.
   - Part numbering starts from `start_part_num`.
   - Returns `_ChainResult` instead of mutating outer variables.
   - `article_content` is always `None` (continuation chains are always fresh creates).
   - Internal sub-article splits handled within the loop (same logic as current code).

**Dependency**: Step 1 (needs `_ChainResult`, `_sem_guard`).

**Verification**: Unit test `_run_chain` directly with monkeypatched LLM seams: single-batch, multi-batch, internal-split scenarios.

### Step 3: Refactor `_merge_batch_split` to three-phase structure

**File**: `py/src/kb_ai/commands/compile.py`

Replace the body of `_merge_batch_split` with:

**Phase A**: Existing serial `while remaining:` loop, but with one change: when a sub-article split is detected (budget < threshold), after finalizing the sub-article and setting `current_content = None`, **break** out of the loop instead of continuing.

**Fast path check**: After Phase A, if `remaining` is empty, finalize and return (same as today). No threads spawned.

**Phase B**: When `remaining` is non-empty after Phase A:
```python
chain_ctx = get_context()  # has op_tracker as request_tracker
sem = _get_batch_parallel_sem()
chunks = _pre_split_chains(remaining, article_type, title)

if len(chunks) == 1 and len(chunks[0]) <= 1:
    # Single item or single chunk — run synchronously on calling thread
    # to avoid thread overhead. Use _run_chain but on this thread.
    result = _run_chain(art_path, chunks[0], write_model,
                        article_type=article_type,
                        title=f"{title} (Part {part_num + 1})",
                        start_part_num=part_num + 1,
                        parent_ctx=chain_ctx, sem=None)
    # ... merge result
else:
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        futures = []
        for i, chunk in enumerate(chunks):
            chunk_title = f"{title} (Part {part_num + 1 + i})"
            fut = pool.submit(
                _run_chain, art_path, chunk, write_model,
                article_type=article_type,
                title=chunk_title,
                start_part_num=part_num + 1 + i * 100,  # sparse numbering
                parent_ctx=chain_ctx,
                sem=sem,
            )
            futures.append(fut)
        # Collect in submission order (preserves item ordering)
        for fut in futures:
            result = fut.result()  # re-raises on error
            all_rels.extend(result.all_rels)
            batch_num += result.n_batches
            chain_articles.extend(result.articles)
```

**Phase C**: Re-number all articles sequentially:
```python
all_sub_articles = list(finalized_articles)  # Chain 0's sub-articles
all_sub_articles.extend(chain_articles)       # continuation chains' articles
renumbered = []
for i, (_path, content) in enumerate(all_sub_articles, 1):
    renumbered.append((_sub_article_path(art_path, i), content))
return renumbered, all_rels, batch_num
```

**Dependency**: Steps 1 and 2.

**Verification**: Run existing `TestMergeBatchSplit` tests — they must pass unchanged (behavior-preserving for non-split and single-chain-split cases). New tests for multi-chain parallel scenarios.

### Step 4: Add tests for parallel paths

**File**: `py/tests/test_compile_batch_split.py`

Add new test class `TestMergeBatchSplitParallel`:

1. **`test_parallel_chains_produce_correct_sub_articles`**: Force Chain 0 to split early (tiny merge budget), verify that continuation chains run and produce sub-articles with sequential part numbers.

2. **`test_parallel_chains_preserve_all_rels`**: All source rel_paths appear in `all_rels` exactly once.

3. **`test_parallel_chains_concurrent_execution`**: Use `threading.Barrier` in fake LLM calls to verify that multiple chains execute concurrently (not serially).

4. **`test_no_parallelism_without_split`**: When no split occurs, verify no threads are spawned (zero overhead).

5. **`test_error_in_continuation_chain_propagates`**: If one chain's LLM call fails, the error propagates as RuntimeError.

6. **`test_semaphore_limits_concurrency`**: Set `KB_BATCH_PARALLEL_MAX_CONCURRENT=2`, launch 4 chains, verify at most 2 are in LLM calls simultaneously (use a threading counter + assertion).

7. **`test_cost_tracking_across_chains`**: Verify that op_tracker receives costs from all chains (not just Chain 0).

8. **`test_pre_split_chains_basic`**: Unit test for `_pre_split_chains` — correct chunking, all items covered, order preserved.

9. **`test_pre_split_chains_single_item`**: Single item returns single chunk.

10. **`test_pre_split_chains_fewer_items_than_chunk`**: All items fit in one chunk.

**Dependency**: Step 3.

### Step 5: Integration test with `compile_kb`

**File**: `py/tests/test_compile_batch_split.py`

Verify that the existing integration tests pass:
- `test_process_article_merge_create_split`
- `test_process_article_merge_batch_split`
- `test_process_article_writes_sub_articles`
- `test_process_article_sub_article_state_tracking`
- `test_stale_sub_article_cleanup_on_recompile`
- `test_merge_batch_split_deletes_original_on_sub_split`
- `test_backward_compat_under_threshold_groups_unchanged`

Add one new integration test:

11. **`test_compile_parallel_chains_end_to_end`**: Set up a KB with 6+ raw files classified to one article, force tiny budgets to trigger multi-chain parallelism, verify compile completes with correct sub-articles and state.

**Dependency**: Step 4.

### Step 6: Add env-var documentation

**File**: `py/src/kb_ai/commands/compile.py` (module-level comment or docstring).

Document `KB_BATCH_PARALLEL_MAX_CONCURRENT` alongside the existing `KB_WORKERS` and other env-based tuning knobs. Add a stderr warning message matching the pattern used by `_get_section_sem`.

**Dependency**: Step 1.

## 6. Risks and Mitigations

### Risk 1: Increased sub-article count
**What**: Pre-splitting items into multiple chains produces more sub-articles than the serial code. The serial code might merge 15 items into 3 sub-articles; the parallel code might produce 5.
**Impact**: Slightly more files in wiki/, slightly smaller articles.
**Mitigation**: `target_batches_per_chain=3` keeps chunks reasonably large (3 batches ≈ 9-15 items). The sub-article format is already supported and indexed. Monitor sub-article count in CI.
**Detection**: Compare sub-article count between serial and parallel runs on the reference KB.

### Risk 2: Thundering-herd LLM rate limits
**What**: Multiple chains launching simultaneously could trigger 429 errors from the LLM proxy.
**Impact**: Failed LLM calls (429 is not in the retryable set).
**Mitigation**: `_BATCH_PARALLEL_MAX_CONCURRENT=6` semaphore limits concurrent calls. The semaphore interacts safely with the existing section-merge semaphore (12). Operators can tune via env var.
**Detection**: Monitor 429 error rate in compile logs. If elevated, lower `KB_BATCH_PARALLEL_MAX_CONCURRENT`.

### Risk 3: Context/cost propagation errors
**What**: Child threads might not correctly inherit the `op_tracker`, causing cost lines to read as 0 or as the full fleet's spend.
**Impact**: Incorrect per-op cost reporting (but global tracker is always correct).
**Mitigation**: Phase A uses the calling thread's context verbatim (no `adopt_context`). Phase B captures `chain_ctx = get_context()` inside `_measure_op_cost`, and child threads `adopt_context(chain_ctx, ...)` — `request_tracker` is shared by reference. Unit test verifies `op_tracker.total_cost > 0` after parallel chains run.
**Detection**: Compare per-op cost logs with global tracker totals.

### Risk 4: Part-number ordering inconsistency
**What**: Chains completing out of order could produce non-sequential part numbers.
**Impact**: Part numbers with gaps (e.g., part-1, part-3, part-5) or wrong ordering.
**Mitigation**: Phase C collects futures in submission order (not `as_completed`) and re-numbers all sub-articles sequentially. Unit test verifies sequential numbering.
**Detection**: Assert `articles[i].path.endswith(f"-part-{i+1}.md")` in tests.

### Risk 5: Semaphore starvation
**What**: If `_BATCH_PARALLEL_MAX_CONCURRENT` is set very low (e.g., 1) and many articles' continuation chains compete, chains may stall waiting for permits.
**Impact**: Slower than serial in pathological cases.
**Mitigation**: Default of 6 is generous. Phase A (Chain 0) does not use the semaphore, so at least one chain per article always makes progress. The semaphore has no timeout — threads wait indefinitely, which is correct (they will eventually get permits as other chains release them).
**Detection**: Log elapsed time per chain. If disproportionately long, raise the semaphore limit.

### Risk 6: Thread pool overhead for small cases
**What**: Creating a `ThreadPoolExecutor` for 1-2 chains adds latency.
**Impact**: Negligible (pool creation is ~1ms), but unnecessary.
**Mitigation**: If `_pre_split_chains` returns a single chunk, run `_run_chain` on the calling thread synchronously — no pool created.
