# Batch-Count-Based Early Break in Phase A

## 1. Background and Goals

### Why
Currently, `_merge_batch_split` Phase A only breaks to Phase B when the sub-article budget threshold is exceeded (`budget < _SUB_ARTICLE_BUDGET_THRESHOLD`). For articles with many small sources, this means Phase A runs many serial batches before ever triggering the parallel dispatch. Adding a batch-count limit lets Phase A hand off to Phase B earlier, reducing wall-clock time by exploiting parallelism sooner.

### What we want to achieve
- Phase A in `_merge_batch_split` breaks after N batches (default 3) when enough remaining items exist to benefit from parallelism
- `_run_chain` (used in Phase B child threads) applies the same batch-count condition to finalize sub-articles and start fresh, preventing any single chain from running too many serial batches
- The batch-count limit is configurable via environment variable, following the existing env-var pattern
- Small articles (few remaining items) are protected from unnecessary splitting via a guard condition
- `_BATCH_PARALLEL_MAX_CONCURRENT` default reduced from 6 to 4

### Scope
- **In scope**: New constant + env var + reader function, Phase A early break, `_run_chain` finalize-and-continue, concurrency default change, tests
- **Out of scope**: Changes to `_pre_split_chains`, `_pack_merge_batch`, merge.py budget logic, or `_process_article` call sites

## 2. Current State Analysis

### Phase A break logic (`_merge_batch_split`, lines ~499–516)
```python
while remaining:
    if current_content is not None:
        budget = estimate_merge_budget(current_content)
        if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
            # finalize + break
```
Only one break condition: budget exhaustion. A 30-source article with small extractions may run 10+ serial batches before the article grows large enough to trigger the budget break.

### `_run_chain` split logic (lines ~240–255)
```python
while remaining:
    if current_content is not None:
        budget = estimate_merge_budget(current_content)
        if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
            # finalize, reset, continue (no break)
```
Same single condition, but continues the loop instead of breaking.

### Env-var configuration pattern (lines ~71–116)
All batch-parallel config follows the same three-piece pattern:
1. Module-level constant default (e.g., `_BATCH_PARALLEL_THRESHOLD: int = 4`)
2. Module-level env var name string (e.g., `_BATCH_PARALLEL_THRESHOLD_ENV: str = "KB_BATCH_PARALLEL_THRESHOLD"`)
3. Reader function with `@functools.lru_cache(maxsize=1)` on the warning helper, parsing the env var, warning once on invalid values, falling back to the default

### Existing test patterns (`test_compile_batch_split.py`)
- `TestGetBatchParallelThreshold`: Tests default, valid env, zero, invalid (warns once), negative (warns)
- `TestBatchParallelThreshold`: Uses `_patch_for_split` to force Phase A to split after 1 create, then verifies serial/parallel dispatch based on remaining count vs threshold
- Spy on `ThreadPoolExecutor.__init__` to detect pool creation
- `_reset_batch_threshold_cache()` helper to clear lru_cache between tests

### Current `_BATCH_PARALLEL_MAX_CONCURRENT` default
Value is 6 (line 71). Test `test_defaults_to_six_and_caches` asserts `_batch_parallel_sem_bound == 6`. Test `test_invalid_env_warns_once_and_uses_default` also asserts bound == 6.

### Import binding for `_estimate_full_extraction_size`
`compile.py` imports via `from kb_ai.core.merge import _estimate_full_extraction_size` (line 45). This creates a local name binding in compile.py's module namespace. Both `_pack_merge_batch` (line 424) and `_pre_split_chains` (line 189) call this local reference. **Monkeypatching `"kb_ai.core.merge._estimate_full_extraction_size"` only changes the name in merge.py's module dict — it does NOT affect compile.py's already-imported reference.** To control packing behavior in `_pack_merge_batch` and chunk sizing in `_pre_split_chains`, the patch must target `cm._estimate_full_extraction_size` (where `cm` is the `kb_ai.commands.compile` module imported in the test file).

Existing tests happen to use the merge.py path and still pass because they rely on `estimate_merge_budget → 100` (budget-based break fires immediately), so the exact packing from `_estimate_full_extraction_size` is irrelevant. For the new batch-count tests, packing is the primary mechanism — the patch MUST target compile.py's namespace.

## 3. Technical Design

### 3.1 New constant, env var, and reader

Add a new three-piece configuration block following the exact same pattern as `_get_batch_parallel_threshold`:

- **Constant**: `_BATCH_PARALLEL_BATCH_LIMIT: int = 3` — after 3 batches in Phase A, trigger early break if enough remaining items exist
- **Env var**: `_BATCH_PARALLEL_BATCH_LIMIT_ENV: str = "KB_BATCH_PARALLEL_BATCH_LIMIT"`
- **Warning function**: `_warn_invalid_batch_parallel_batch_limit(raw: str)` with `@functools.lru_cache(maxsize=1)`
- **Reader**: `_get_batch_parallel_batch_limit() -> int` — returns parsed env value (>= 1), or default. Value of 0 is invalid (would cause immediate break on first iteration).

### 3.2 Phase A early break in `_merge_batch_split`

Expand the existing condition at the top of the `while remaining:` loop (lines ~503–516):

**Before:**
```python
if current_content is not None:
    budget = estimate_merge_budget(current_content)
    if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
        # finalize + break
```

**After:**
```python
if current_content is not None:
    budget = estimate_merge_budget(current_content)
    if budget < _SUB_ARTICLE_BUDGET_THRESHOLD or (
        batch_num >= _get_batch_parallel_batch_limit()
        and len(remaining) > _get_batch_parallel_threshold()
    ):
        # finalize + break (existing code unchanged)
```

Key design decisions:
- **Uses `batch_num` not `source_count`**: batch_num is incremented after each LLM call, directly correlating with serial latency. Source count varies with packing efficiency.
- **Guard `len(remaining) > threshold`**: If few items remain, the overhead of thread dispatch outweighs the benefit. Reuses the existing `_get_batch_parallel_threshold()` for this guard, which is the same threshold used in Phase B to decide serial vs parallel dispatch. This means: if remaining items would go to serial fallback anyway, don't break early.
- **Preserves `article_content is not None` path**: The condition is inside `if current_content is not None:`, so the first iteration of a create-path (`article_content=None`) always skips this block. After the first create, `current_content` is set, and `batch_num` is 1. The condition only fires when `batch_num >= 3`, so at least 3 LLM calls complete in Phase A before any early break.

### 3.3 `_run_chain` finalize-and-continue

Same expansion of the existing condition in `_run_chain` (lines ~244–255):

**Before:**
```python
if current_content is not None:
    budget = estimate_merge_budget(current_content)
    if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
        # finalize, reset, continue
```

**After:**
```python
if current_content is not None:
    budget = estimate_merge_budget(current_content)
    if budget < _SUB_ARTICLE_BUDGET_THRESHOLD or (
        batch_num >= _get_batch_parallel_batch_limit()
        and len(remaining) > _get_batch_parallel_threshold()
    ):
        # finalize, reset, continue (existing code unchanged, no break)
```

`_run_chain` does NOT break — it finalizes the current sub-article and continues processing remaining items. This produces more, smaller sub-articles per chain, which is the desired behavior (sub-articles are renumbered in Phase C anyway).

Note: `batch_num` in `_run_chain` is the chain-local counter, not the Phase A counter. After a finalize-and-continue, `batch_num` keeps incrementing (it is NOT reset). If the limit is 3 and the chain has 10 items packed 1-per-batch:
- Batches 1–3: create + 2 merges → finalize at top of iteration 4 (`batch_num == 3 >= 3`)
- Batch 4: create (new sub-article), then at top of iteration 5, `batch_num == 4 >= 3` → finalize immediately
- Batch 5: create, then iteration 6: `batch_num == 5 >= 3` → finalize immediately
- This continues: every sub-article after the first gets exactly 1 batch (a create)

This is intentional — the point is to bound serial work. After the initial N batches, every subsequent sub-article in the chain is small. Phase C renumbers everything, so the count of sub-articles doesn't affect correctness.

### 3.4 Concurrency default change

Change `_BATCH_PARALLEL_MAX_CONCURRENT: int = 6` → `_BATCH_PARALLEL_MAX_CONCURRENT: int = 4` (line 71).

This reduces the default semaphore permits from 6 to 4. With early break triggering more Phase B dispatches, this prevents overloading LLM endpoints.

Update affected tests: `test_defaults_to_six_and_caches` → `test_defaults_to_four_and_caches`, assertions change from `== 6` to `== 4`. `test_invalid_env_warns_once_and_uses_default` assertions change from `== 6` to `== 4`.

### 3.5 Interaction with existing paths

| Scenario | Behavior |
|---|---|
| Small article (few items, all consumed in Phase A) | Fast path: `not remaining` → return immediately. Batch limit never triggers because there are no remaining items after all are consumed. |
| Large article, budget exhaustion before batch limit | Existing budget break fires first. No change. |
| Large article, batch limit reached before budget exhaustion | NEW: batch-count break fires, remaining goes to Phase B. |
| Large article, batch limit reached but few remaining | Guard `len(remaining) > threshold` prevents break. Phase A continues serial processing. |
| `_run_chain` with many items | Batch-count condition causes more frequent sub-article finalization after the Nth batch, producing smaller sub-articles. All items are still processed (finalize-and-continue, NOT early break). |

## 4. Interface Contracts

This change is entirely internal to `compile.py` — no API endpoints, no cross-module interfaces, no data model changes. The contracts are between internal functions.

### 4.1 New function: `_get_batch_parallel_batch_limit() -> int`

**Signature:**
```python
def _get_batch_parallel_batch_limit() -> int:
```

**Behavior contract:**
- Returns `int(os.environ["KB_BATCH_PARALLEL_BATCH_LIMIT"])` when set, parseable, and >= 1
- Returns `_BATCH_PARALLEL_BATCH_LIMIT` (3) otherwise
- Warns once to stderr on invalid values (non-integer, or < 1)
- Value of 0 is invalid (would cause immediate break); logs warning and returns default

**Differences from `_get_batch_parallel_threshold()`:**
- Minimum valid value is 1 (not 0). `_get_batch_parallel_threshold()` allows 0 meaning "always parallelize". For the batch limit, 0 would mean "break after 0 batches" which is nonsensical.

### 4.2 New constants

```python
_BATCH_PARALLEL_BATCH_LIMIT: int = 3
_BATCH_PARALLEL_BATCH_LIMIT_ENV: str = "KB_BATCH_PARALLEL_BATCH_LIMIT"
```

### 4.3 Modified break condition in `_merge_batch_split`

The finalize+break block (lines ~506–516) fires when EITHER:
1. `budget < _SUB_ARTICLE_BUDGET_THRESHOLD` (existing), OR
2. `batch_num >= _get_batch_parallel_batch_limit() and len(remaining) > _get_batch_parallel_threshold()` (new)

Output contract unchanged: `tuple[list[tuple[str, str]], list[str], int]` — same as before. The only behavioral change is that Phase B is reached earlier in some cases.

### 4.4 Modified split condition in `_run_chain`

The finalize+continue block (lines ~247–255) fires when EITHER:
1. `budget < _SUB_ARTICLE_BUDGET_THRESHOLD` (existing), OR
2. `batch_num >= _get_batch_parallel_batch_limit() and len(remaining) > _get_batch_parallel_threshold()` (new)

Output contract unchanged: `_ChainResult` — same fields, same semantics. The only behavioral change is that more sub-articles may be produced per chain. **Critically, all items are still processed** — `_run_chain` never breaks, it finalizes and continues.

### 4.5 Changed default

`_BATCH_PARALLEL_MAX_CONCURRENT`: 6 → 4. Affects `_get_batch_parallel_sem()` return value and the warning message string.

## 5. Implementation Steps

### Step 1: Add new constant, env var, warning function, and reader
**File**: `py/src/kb_ai/commands/compile.py`
**Location**: After the existing `_BATCH_PARALLEL_THRESHOLD` / `_BATCH_PARALLEL_THRESHOLD_ENV` block (after line 75), add:

```python
_BATCH_PARALLEL_BATCH_LIMIT: int = 3
_BATCH_PARALLEL_BATCH_LIMIT_ENV: str = "KB_BATCH_PARALLEL_BATCH_LIMIT"
```

After the existing `_warn_invalid_batch_parallel_threshold` function (after line 93), add:

```python
@functools.lru_cache(maxsize=1)
def _warn_invalid_batch_parallel_batch_limit(raw: str) -> None:
    """Report an ignored batch-limit override once, not once per read."""
    print(f"[compile] invalid {_BATCH_PARALLEL_BATCH_LIMIT_ENV}={raw!r}: expected a "
          f"positive integer \u2014 using {_BATCH_PARALLEL_BATCH_LIMIT}",
          file=sys.stderr, flush=True)


def _get_batch_parallel_batch_limit() -> int:
    """Read the batch-parallel batch limit from the environment.

    Returns ``int(os.environ[_BATCH_PARALLEL_BATCH_LIMIT_ENV])`` when set,
    parseable, and >= 1.  Falls back to ``_BATCH_PARALLEL_BATCH_LIMIT``
    otherwise, warning once for invalid values.
    """
    raw = os.environ.get(_BATCH_PARALLEL_BATCH_LIMIT_ENV, "")
    if not raw:
        return _BATCH_PARALLEL_BATCH_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        _warn_invalid_batch_parallel_batch_limit(raw)
        return _BATCH_PARALLEL_BATCH_LIMIT
    if parsed < 1:
        _warn_invalid_batch_parallel_batch_limit(raw)
        return _BATCH_PARALLEL_BATCH_LIMIT
    return parsed
```

**Verify**: `pytest py/tests/test_compile_batch_split.py -x` passes (no existing tests break).

### Step 2: Change `_BATCH_PARALLEL_MAX_CONCURRENT` default from 6 to 4
**File**: `py/src/kb_ai/commands/compile.py`
**Line 71**: Change `_BATCH_PARALLEL_MAX_CONCURRENT: int = 6` → `_BATCH_PARALLEL_MAX_CONCURRENT: int = 4`

**File**: `py/tests/test_compile_batch_split.py`
**Lines ~873, ~897**: Update assertions from `== 6` to `== 4`
**Line ~868**: Rename `test_defaults_to_six_and_caches` → `test_defaults_to_four_and_caches`

**Verify**: `pytest py/tests/test_compile_batch_split.py::TestGetBatchParallelSem -x` passes.

### Step 3: Add batch-count OR condition to `_merge_batch_split` Phase A
**File**: `py/src/kb_ai/commands/compile.py`
**Location**: Inside `_merge_batch_split`, the `while remaining:` loop, the `if current_content is not None:` block (around line 505).

Change:
```python
if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
```
To:
```python
if budget < _SUB_ARTICLE_BUDGET_THRESHOLD or (
    batch_num >= _get_batch_parallel_batch_limit()
    and len(remaining) > _get_batch_parallel_threshold()
):
```

Everything inside the `if` block (finalize, print, break) remains unchanged.

**Verify**: `pytest py/tests/test_compile_batch_split.py -x` — existing tests pass. Some tests may change behavior if their batch counts cross the new limit. Review test items counts:
- `TestBatchParallelThreshold._patch_for_split` forces Phase A to split after 1 create (merge_budget=100, which is < _SUB_ARTICLE_BUDGET_THRESHOLD). Since batch_num=1 < 3 at that point, the budget condition fires first. No behavioral change for existing tests.
- `TestMergeBatchSplitParallel` similarly relies on budget-based split. No change.

### Step 4: Add batch-count OR condition to `_run_chain`
**File**: `py/src/kb_ai/commands/compile.py`
**Location**: Inside `_run_chain`, the `while remaining:` loop, the `if current_content is not None:` block (around line 246).

Change:
```python
if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
```
To:
```python
if budget < _SUB_ARTICLE_BUDGET_THRESHOLD or (
    batch_num >= _get_batch_parallel_batch_limit()
    and len(remaining) > _get_batch_parallel_threshold()
):
```

Everything inside the `if` block (finalize, print, part_num increment, reset) remains unchanged. No `break` — `_run_chain` continues processing.

**Verify**: `pytest py/tests/test_compile_batch_split.py::TestRunChain -x` — existing tests pass. Test items are small (1-4 items), so batch_num won't reach 3 before items are consumed.

### Step 5: Add tests for `_get_batch_parallel_batch_limit`
**File**: `py/tests/test_compile_batch_split.py`
**Location**: After the `TestGetBatchParallelThreshold` class (around line 1586), add a new section:

```python
# ── _get_batch_parallel_batch_limit ──────────────────────────────────


def _reset_batch_limit_cache():
    """Clear the lru_cache on the warning function so tests see fresh warnings."""
    cm._warn_invalid_batch_parallel_batch_limit.cache_clear()


class TestGetBatchParallelBatchLimit:

    def test_returns_default(self, monkeypatch):
        """No env var set -> returns _BATCH_PARALLEL_BATCH_LIMIT (3)."""
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        assert cm._get_batch_parallel_batch_limit() == 3

    def test_reads_env(self, monkeypatch):
        """Valid env var -> returns parsed value."""
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "5")
        assert cm._get_batch_parallel_batch_limit() == 5

    def test_one_valid(self, monkeypatch):
        """Env var = '1' -> returns 1 (break after first batch)."""
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "1")
        assert cm._get_batch_parallel_batch_limit() == 1

    def test_zero_invalid_warns(self, monkeypatch, capsys):
        """Env var = '0' -> returns default and warns (0 would mean break before any batch)."""
        _reset_batch_limit_cache()
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "0")
        assert cm._get_batch_parallel_batch_limit() == 3
        err = capsys.readouterr().err
        assert cm._BATCH_PARALLEL_BATCH_LIMIT_ENV in err

    def test_invalid_warns_once(self, monkeypatch, capsys):
        """Non-integer env var -> returns default and warns to stderr once."""
        _reset_batch_limit_cache()
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "bad")
        assert cm._get_batch_parallel_batch_limit() == 3
        cm._get_batch_parallel_batch_limit()  # second call should not warn again
        err = capsys.readouterr().err
        assert err.count(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV) == 1
        assert "bad" in err

    def test_negative_warns(self, monkeypatch, capsys):
        """Negative env var -> returns default and warns."""
        _reset_batch_limit_cache()
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "-2")
        assert cm._get_batch_parallel_batch_limit() == 3
        err = capsys.readouterr().err
        assert cm._BATCH_PARALLEL_BATCH_LIMIT_ENV in err
```

**Verify**: `pytest py/tests/test_compile_batch_split.py::TestGetBatchParallelBatchLimit -x` passes.

### Step 6: Add tests for batch-count early break in `_merge_batch_split`
**File**: `py/tests/test_compile_batch_split.py`
**Location**: After `TestBatchParallelThreshold` class (end of file), add:

**Critical: monkeypatch target for `_estimate_full_extraction_size`**

`compile.py` imports via `from kb_ai.core.merge import _estimate_full_extraction_size` (line 45). This creates a local name binding in compile.py's module namespace. Both `_pack_merge_batch` and `_pre_split_chains` call this local reference. Monkeypatching `"kb_ai.core.merge._estimate_full_extraction_size"` only changes the name in merge.py's module dict — it does NOT affect compile.py's already-imported reference.

**All new tests MUST use `monkeypatch.setattr(cm, "_estimate_full_extraction_size", ...)` to patch the reference in compile.py's namespace.** This ensures `_pack_merge_batch` and `_pre_split_chains` see the patched function.

Note: Existing tests (e.g., `_patch_for_split`) patch at the merge.py path and still work because they rely on `estimate_merge_budget → 100` (budget-based break fires immediately), so packing behavior is irrelevant. Our new tests rely on packing behavior being the primary mechanism, so the patch target is critical.

```python
# ── Batch-count early break in Phase A ───────────────────────────────


class TestBatchCountEarlyBreak:
    """Tests for the batch-count-based early break in _merge_batch_split Phase A."""

    @staticmethod
    def _make_items(n: int):
        return [(f"raw/doc_{i}.md", _ext(f"summary {i}")) for i in range(n)]

    @staticmethod
    def _patch_for_many_batches(monkeypatch):
        """Patch so each batch packs exactly 1 item, but budget stays HIGH.

        This means the budget-based split does NOT fire — only the
        batch-count condition can trigger Phase A break.

        Key invariants enforced:
        - estimate_merge_budget → 50000 (>> _SUB_ARTICLE_BUDGET_THRESHOLD ≈ 12000)
          so the budget-based break condition never fires.
        - estimate_create_budget → 50000, capped by min(..., _MAX_BATCH_BUDGET=20000)
          so each create batch also gets budget=20000.
        - _estimate_full_extraction_size → 15000 per item, so only 1 item fits
          per batch (second item would cost 30000 > 20000 budget).

        IMPORTANT: The patch for _estimate_full_extraction_size MUST target
        the compile module's own reference (cm._estimate_full_extraction_size),
        NOT the merge module path ("kb_ai.core.merge._estimate_full_extraction_size").
        compile.py uses `from kb_ai.core.merge import _estimate_full_extraction_size`
        which creates a local binding. _pack_merge_batch and _pre_split_chains
        call this local reference. Patching the merge module would leave
        compile.py's reference unchanged, and real item sizes (~60 chars) would
        mean all items fit in 1 batch — the batch-count condition would never fire.
        """
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 50_000)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 50_000)
        monkeypatch.setattr(
            cm, "_estimate_full_extraction_size",
            lambda ext, rel: 15_000,
        )
        call_log: list[str] = []
        def create_fn(article_type, title, extraction, source_path, model="m"):
            call_log.append(f"create:{source_path}")
            return f"---\ntitle: {title}\n---\ncreated from {source_path}\n"
        def merge_fn(article_path, article_content, extraction, source_path, model="m"):
            call_log.append(f"merge:{source_path}")
            return article_content + f"\nmerged {source_path}\n"
        monkeypatch.setattr(cm, "create_new_article", create_fn)
        monkeypatch.setattr(cm, "merge_into_article", merge_fn)
        return call_log

    def test_breaks_after_batch_limit_with_enough_remaining(self, monkeypatch):
        """Phase A breaks after 3 batches when remaining > threshold.

        12 items, batch_limit=3 (default), threshold=4 (default).
        Phase A: batch 1 = create(item 0), batch 2 = merge(item 1),
        batch 3 = merge(item 2). Top of iteration 4: batch_num=3 >= 3
        and remaining=9 > 4 → finalize + break to Phase B.
        Phase B dispatches remaining 9 items to parallel chains.
        """
        import threading

        items = self._make_items(12)
        self._patch_for_many_batches(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        original_init = ThreadPoolExecutor.__init__
        pool_created = threading.Event()
        def spy_init(self_pool, *args, **kwargs):
            pool_created.set()
            return original_init(self_pool, *args, **kwargs)
        monkeypatch.setattr(
            "concurrent.futures.ThreadPoolExecutor.__init__", spy_init)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Phase A did 3 batches, broke, dispatched remaining to Phase B
        assert pool_created.is_set(), "Should dispatch to parallel after batch limit"
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels
        assert len(articles) >= 2  # At least Phase A sub-article + Phase B result(s)

    def test_all_items_appear_in_article_contents(self, monkeypatch):
        """Every item's source path appears in the final sub-article contents.

        This verifies the completeness invariant: no items are lost during
        the Phase A break + Phase B dispatch handoff.
        """
        items = self._make_items(12)
        self._patch_for_many_batches(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Concatenate all sub-article contents
        all_content = "\n".join(content for _, content in articles)
        # Every item's source path must appear in the combined content
        for rel, _ in items:
            assert rel in all_content, (
                f"Item {rel} missing from final sub-article contents"
            )

    def test_no_break_when_remaining_below_threshold(self, monkeypatch):
        """Phase A does NOT break when remaining <= threshold (small article guard).

        5 items, batch_limit=3 (default), threshold=4 (default).
        Phase A: batch 1 = create(item 0), batch 2 = merge(item 1),
        batch 3 = merge(item 2). Top of iteration 4: batch_num=3 >= 3
        but remaining=2 <= 4 → guard prevents break. Continues serially.
        Phase A consumes all 5 items. Fast path returns.
        """
        items = self._make_items(5)
        self._patch_for_many_batches(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # All items consumed in Phase A, single article at original path
        assert len(articles) == 1
        assert articles[0][0] == "wiki/concept/foo.md"
        assert n_batches == 5
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels

    def test_env_override_batch_limit(self, monkeypatch):
        """Setting batch limit via env var changes break point.

        12 items, batch_limit=1 (via env), threshold=4 (default).
        Phase A: batch 1 = create(item 0). Top of iteration 2:
        batch_num=1 >= 1 and remaining=11 > 4 → break immediately.
        Phase B gets 11 remaining items.
        """
        items = self._make_items(12)
        self._patch_for_many_batches(monkeypatch)
        monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "1")
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Phase A did only 1 batch, then broke to Phase B
        assert len(articles) >= 2
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels
        # Verify all items appear in contents
        all_content = "\n".join(content for _, content in articles)
        for rel, _ in items:
            assert rel in all_content

    def test_budget_break_still_works(self, monkeypatch):
        """Budget-based break still fires when budget is exhausted before batch limit.

        8 items, merge_budget=100 (< _SUB_ARTICLE_BUDGET_THRESHOLD ≈ 12000).
        Budget break fires at iteration 2 (after batch 1 create).
        batch_limit=3 is not reached.
        """
        items = self._make_items(8)
        # Low merge budget triggers budget-based split;
        # _estimate_full_extraction_size can be small since
        # the budget break fires before batch-count matters.
        # Patch at cm to be consistent with the correct pattern.
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 100)
        monkeypatch.setattr(
            cm, "_estimate_full_extraction_size",
            lambda ext, rel: 100,
        )
        monkeypatch.setattr(cm, "create_new_article",
            lambda *a, **kw: "---\ntitle: T\n---\ncreated\n")
        monkeypatch.setattr(cm, "merge_into_article",
            lambda art_path, content, ext, src, model="m": content + "\nmerged\n")
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content=None, article_type="concept", title="Foo")

        # Budget-based split fires after 1 create (merge_budget=100 < threshold).
        # Phase A breaks, remaining goes to Phase B.
        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels
        assert len(articles) >= 2

    def test_article_content_not_none_path(self, monkeypatch):
        """Merge path (article_content is not None) works with batch-count break.

        12 items, article_content provided, merge_budget=50000 (high).
        Phase A: batch 1 = merge(item 0), batch 2 = merge(item 1),
        batch 3 = merge(item 2). Top of iteration 4: batch_num=3 >= 3
        and remaining=9 > 4 → break to Phase B.
        """
        items = self._make_items(12)
        self._patch_for_many_batches(monkeypatch)
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        articles, all_rels, n_batches = cm._merge_batch_split(
            "wiki/concept/foo.md", items, "m",
            article_content="---\ntitle: Existing\n---\nexisting content\n")

        expected_rels = [rel for rel, _ in items]
        assert all_rels == expected_rels
        assert len(articles) >= 2
        # Verify all items appear in contents
        all_content = "\n".join(content for _, content in articles)
        for rel, _ in items:
            assert rel in all_content
```

**Verify**: `pytest py/tests/test_compile_batch_split.py::TestBatchCountEarlyBreak -x` passes.

### Step 7: Add tests for batch-count condition in `_run_chain`
**File**: `py/tests/test_compile_batch_split.py`
**Location**: Inside or after `TestRunChain` class, add:

**Note**: Same monkeypatch target rule applies — use `cm._estimate_full_extraction_size`, NOT the merge.py path.

```python
    def test_batch_limit_triggers_sub_article_split_all_items_processed(self, monkeypatch):
        """_run_chain splits into sub-articles when batch limit is reached.

        Critically, _run_chain does NOT break — it finalizes and continues.
        All 10 items must be processed (finalize-and-continue invariant).

        10 items, batch_limit=3 (default), threshold=4 (default).
        Each batch packs exactly 1 item (cm._estimate_full_extraction_size=15000,
        budget capped at _MAX_BATCH_BUDGET=20000).

        Execution trace:
        - Batch 1: create(item 0)
        - Batch 2: merge(item 1)
        - Batch 3: merge(item 2)
        - Top of iteration 4: batch_num=3 >= 3, remaining=7 > 4 → finalize sub-article 1
        - Batch 4: create(item 3) [new sub-article]
        - Top of iteration 5: batch_num=4 >= 3, remaining=6 > 4 → finalize sub-article 2
        - Batch 5: create(item 4)
        - Top of iteration 6: batch_num=5 >= 3, remaining=5 > 4 → finalize sub-article 3
        - Batch 6: create(item 5)
        - Top of iteration 7: batch_num=6 >= 3, remaining=4 <= 4 → guard prevents split
        - Batch 7: merge(item 6)
        - Top of iteration 8: batch_num=7 >= 3, remaining=3 <= 4 → guard prevents split
        - Batch 8: merge(item 7)
        - ... continues until all consumed
        - Final sub-article 4: items 5–9

        Result: 4 sub-articles, 10 batches, all 10 rels present.
        """
        items = [(f"raw/doc_{i}.md", _ext(f"summary {i}")) for i in range(10)]
        monkeypatch.setattr(cm, "estimate_merge_budget", lambda *a, **kw: 50_000)
        monkeypatch.setattr(cm, "estimate_create_budget", lambda *a, **kw: 50_000)
        monkeypatch.setattr(
            cm, "_estimate_full_extraction_size",
            lambda ext, rel: 15_000,
        )
        call_log: list[str] = []
        def create_fn(article_type, title, ext, src, model="m"):
            call_log.append(f"create:{src}")
            return f"created:{src}"
        def merge_fn(art_path, content, ext, src, model="m"):
            call_log.append(f"merge:{src}")
            return content + f"+merged:{src}"
        monkeypatch.setattr(cm, "create_new_article", create_fn)
        monkeypatch.setattr(cm, "merge_into_article", merge_fn)
        monkeypatch.delenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, raising=False)
        monkeypatch.delenv(cm._BATCH_PARALLEL_THRESHOLD_ENV, raising=False)

        result = cm._run_chain(
            "wiki/concept/foo.md", items, "m",
            article_type="concept", title="Foo",
            start_part_num=1,
            parent_ctx=_make_parent_ctx(), sem=None,
        )

        # ALL items processed (finalize-and-continue, NOT early break)
        assert result.n_batches == 10
        expected_rels = [rel for rel, _ in items]
        assert result.all_rels == expected_rels

        # Multiple sub-articles produced (split after batch 3, then more)
        assert len(result.articles) >= 2

        # Verify all items appear in sub-article contents (not just in all_rels)
        all_content = "\n".join(content for _, content in result.articles)
        for rel, _ in items:
            assert rel in all_content, (
                f"Item {rel} missing from _run_chain sub-article contents"
            )

        # Verify every LLM call was made (10 items = 10 calls)
        assert len(call_log) == 10
```

**Verify**: `pytest py/tests/test_compile_batch_split.py::TestRunChain::test_batch_limit_triggers_sub_article_split_all_items_processed -x` passes.

### Step 8: Run full test suite
**Command**: `pytest py/tests/test_compile_batch_split.py -x -v`
**Command**: `pytest py/tests/ -x` (full suite)

**Verify**: All tests pass, including pre-existing ones.

### Dependencies between steps
- Steps 1, 2 are independent of each other
- Step 3 depends on Step 1 (needs `_get_batch_parallel_batch_limit`)
- Step 4 depends on Step 1
- Step 5 depends on Step 1
- Step 6 depends on Steps 1, 3
- Step 7 depends on Steps 1, 4
- Step 8 depends on all previous steps

## 6. Risks and Mitigations

### Risk 1: Existing tests break due to batch-count condition firing unexpectedly
**Likelihood**: Low. Existing tests that trigger Phase A splits use `estimate_merge_budget → 100`, which is far below `_SUB_ARTICLE_BUDGET_THRESHOLD` (~12000). The budget condition fires on batch 1, well before `batch_num >= 3`. Tests that DON'T trigger splits have few enough items that they're consumed before batch 3, or have high budgets and few items so `len(remaining) <= threshold`.
**Detection**: Step 8 — full test suite run.
**Mitigation**: If a test breaks, verify its item count and budget setup. Adjust the test or add `monkeypatch.setenv(cm._BATCH_PARALLEL_BATCH_LIMIT_ENV, "999")` to disable the new condition for that specific test.

### Risk 2: `_run_chain` produces too many sub-articles
**Likelihood**: Medium. Since `batch_num` never resets in `_run_chain`, after batch 3 every iteration with content and enough remaining items produces a 1-batch sub-article.
**Detection**: New test in Step 7 verifies the exact split behavior with an execution trace.
**Mitigation**: This is by design — the intent is to bound serial work. The guard `len(remaining) > threshold` limits splitting: once remaining drops to ≤ threshold, no more splits happen, and the final sub-article absorbs all remaining items serially. Phase C renumbers everything, so the count of sub-articles doesn't matter functionally. If this produces too many sub-articles in practice, the env var can be increased.

### Risk 3: Batch-count break fires on merge path with existing content
**Likelihood**: Low-medium. When `article_content` is not None, the first iteration enters the `if current_content is not None:` block with `batch_num == 0`. The condition `0 >= 3` is false. The break can only fire after 3 batches. The existing content gets at least 3 merges before any early break.
**Detection**: Test in Step 6 (`test_article_content_not_none_path`) covers this path.
**Mitigation**: If the existing article is small and 3 merges aren't enough, the budget condition wouldn't fire anyway (budget is still high), so the batch-count condition is the only one that triggers. This is correct behavior — we want to parallelize large merge operations.

### Risk 4: Guard condition `len(remaining) > threshold` interacts with threshold=0
**Likelihood**: Low. When `threshold=0`, the guard becomes `len(remaining) > 0`. Since we're inside `while remaining:`, this is always true when we have items. So `threshold=0` makes the batch-count break fire whenever `batch_num >= limit`. This is consistent with the "always parallelize" semantics of threshold=0.
**Detection**: Can add a targeted test if needed.
**Mitigation**: No action needed — this is correct and desirable behavior.

### Risk 5: Concurrent default change (6→4) reduces throughput
**Likelihood**: Low. The early break means more Phase B dispatches, but each chain does less work. The lower concurrency limit prevents LLM endpoint overload. Net effect should be positive (lower latency, same or better throughput).
**Detection**: Manual benchmarking on reference KB.
**Mitigation**: Env var `KB_BATCH_PARALLEL_MAX_CONCURRENT` can override back to 6 or higher if needed.

### Risk 6: `_patch_for_many_batches` values become stale if `_MAX_BATCH_BUDGET` changes
**Likelihood**: Low. `_MAX_BATCH_BUDGET` is currently 20000. The test helper relies on `cm._estimate_full_extraction_size → 15000` so that 2 items (30000) exceed 20000 budget.
**Detection**: If `_MAX_BATCH_BUDGET` is raised above 30000, tests would pack 2+ items per batch, changing batch counts. Test assertions would fail, surfacing the issue immediately.
**Mitigation**: Document the invariant in the helper docstring (already done in Step 6). If `_MAX_BATCH_BUDGET` changes, update the `_estimate_full_extraction_size` return value proportionally.

### Risk 7: Monkeypatch target confusion in future test maintenance
**Likelihood**: Medium. Existing tests patch `_estimate_full_extraction_size` at `"kb_ai.core.merge._estimate_full_extraction_size"` while new tests patch at `cm._estimate_full_extraction_size`. A future contributor might copy the wrong pattern.
**Detection**: Tests that depend on packing behavior would fail if they use the wrong target.
**Mitigation**: The `_patch_for_many_batches` docstring explicitly explains WHY `cm._estimate_full_extraction_size` is required and warns against using the merge.py path. Additionally, a code comment at the top of `TestBatchCountEarlyBreak` references this constraint.
