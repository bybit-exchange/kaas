# Batch Parallel Threshold & Two-Round Aggregation Feedback

## 1. Background and Goals

### 1.1 batch_parallel_threshold for `_merge_batch_split`

**Why:** Currently, when Phase A detects a sub-article split, _all_ remaining items are handed to Phase B (parallel `ThreadPoolExecutor`) regardless of count. Even 2 remaining items spawn a thread pool, incurring context-snapshot overhead (`get_context()` / `adopt_context()`), semaphore setup, and `_pre_split_chains()` computation — all for negligible parallelism benefit.

**Goal:** Introduce a configurable threshold (`_BATCH_PARALLEL_THRESHOLD`) below which remaining items are processed serially via a single `_run_chain()` call (no thread pool), and above which the existing parallel dispatch proceeds.

**Scope:**
- In scope: threshold constant, env var override, serial fallback path in `_merge_batch_split`, tests.
- Out of scope: changes to `_run_chain`, `_pre_split_chains`, or the Phase A loop itself.

### 1.2 Two-Round Feedback for `plan_aggregation`

**Why:** The current `plan_aggregation()` makes a single LLM call, then validates and returns. There is no mechanism to verify that high-frequency entities, topics, and concepts from the frequency tables are adequately covered by the planned articles. This can result in blind spots where important themes get no article.

**Goal:** Add a second LLM round that critiques the first-round plan against the frequency data and produces a refined plan with better coverage.

**Scope:**
- In scope: new `aggregate-plan-feedback.md` prompt template, second `completion_json()` call in `plan_aggregation()`, dedup + validation of refined plan, tests.
- Out of scope: changes to `reorganize()` orchestrator, `build_entity_index()`, `resolve_entities()`, data structures.

## 2. Current State Analysis

### 2.1 `_merge_batch_split` Phase A→B Transition (compile.py:525-575)

After Phase A breaks on the first sub-article split:
1. `if not remaining: return` — fast path (no split, all consumed).
2. `chain_ctx = get_context()` — capture context for child threads.
3. `sem = _get_batch_parallel_sem()` — get process-wide semaphore.
4. `chunks = _pre_split_chains(remaining, ...)` — split remaining into chunks.
5. If `len(chunks) == 1 and len(chunks[0]) <= 1` → single synchronous `_run_chain()`.
6. Otherwise → `ThreadPoolExecutor(max_workers=len(chunks))` dispatching `_run_chain()` per chunk.

**Problem:** Step 5's condition (`len(chunks[0]) <= 1`) only catches the trivial 1-item case. With 2-4 remaining items, `_pre_split_chains` may produce 1 chunk (below chunk_size threshold), but the code still enters the `else` branch which creates a `ThreadPoolExecutor` with 1 worker — pure overhead for serial execution.

### 2.2 `plan_aggregation` (derive/_reorganize.py:320-400)

Current single-round flow:
1. Build frequency tables: top 50 entities, top 30 topics, top 30 concepts.
2. Render `aggregate-plan.md` prompt with frequency data.
3. Single `completion_json()` call → `{"articles": [...]}`.
4. Validate each article: `_is_safe_wiki_path`, type in categories, non-empty title.
5. Clamp to `_MAX_ARTICLES = 15`, require `_MIN_ARTICLES = 3`.
6. Return `valid` list.

**Problem:** No self-critique. High-frequency entities/topics may not be covered. The LLM has no opportunity to see its own output and identify gaps.

### 2.3 Existing Concurrency Control

- `_BATCH_PARALLEL_MAX_CONCURRENT = 6` (default), overridable via `KB_BATCH_PARALLEL_MAX_CONCURRENT` env var.
- `_get_batch_parallel_sem()` manages a process-wide `threading.Semaphore`.
- Pattern: env var read per-call, warns once for invalid values, re-sizes if value changes.

### 2.4 Prompt Registry

- `default_registry().get("aggregate-plan")` loads `py/src/kb_ai/prompts/defaults/aggregate-plan.md`.
- Templates use Python `str.format()` with double-brace escaping for JSON.
- New prompt files added to `py/src/kb_ai/prompts/defaults/` are auto-discovered by filename.

## 3. Technical Design

### 3.1 `batch_parallel_threshold` — Serial Fallback in Phase B

**Constant and env var:**

```python
_BATCH_PARALLEL_THRESHOLD: int = 4
_BATCH_PARALLEL_THRESHOLD_ENV: str = "KB_BATCH_PARALLEL_THRESHOLD"
```

A threshold of 4 items means: with typical budget/item ratios, ≤4 remaining items produce 1-2 batches — not enough to justify parallelism overhead.

**Decision logic in `_merge_batch_split`** (exact sequence after Phase A break):

1. `if not remaining: return` — fast path, no split (unchanged).
2. Capture context: `chain_ctx = get_context()`.
3. Read threshold: `threshold = _get_batch_parallel_threshold()`.
4. **Threshold check**: `if len(remaining) <= threshold:` → serial fallback.
   - Call `_run_chain(...)` synchronously with `sem=None` (no semaphore needed for serial).
   - Collect result, proceed to Phase C re-numbering.
5. **Else**: proceed to `_pre_split_chains()`, semaphore setup, `ThreadPoolExecutor` dispatch (existing Phase B logic).

This means `_pre_split_chains()` is called ONLY when `len(remaining) > threshold`. The serial fallback skips `_pre_split_chains()` entirely and passes all remaining items as a single chunk to `_run_chain()`.

**Why `_pre_split_chains` is NOT called before the threshold check:** `_pre_split_chains` estimates budgets and splits — work that is only useful if we're going parallel. For the serial path, `_run_chain` handles its own batch loop internally, so pre-splitting is unnecessary overhead.

**`_get_batch_parallel_threshold()` helper** (follows `_get_batch_parallel_sem()` pattern):

```python
def _get_batch_parallel_threshold() -> int:
    raw = os.environ.get(_BATCH_PARALLEL_THRESHOLD_ENV, "")
    if not raw:
        return _BATCH_PARALLEL_THRESHOLD
    try:
        parsed = int(raw)
    except ValueError:
        _warn_invalid_batch_parallel_threshold(raw)
        return _BATCH_PARALLEL_THRESHOLD
    if parsed < 0:
        _warn_invalid_batch_parallel_threshold(raw)
        return _BATCH_PARALLEL_THRESHOLD
    return parsed
```

Note: `threshold=0` is valid and means "always parallelize" (restores current behavior). Negative values are rejected.

### 3.2 Two-Round Feedback for `plan_aggregation`

#### 3.2.1 New Prompt Template: `aggregate-plan-feedback.md`

Template variables:
- `{topic}` — the KB topic
- `{first_round_articles}` — JSON string of the validated first-round articles
- `{entity_frequency}` — same frequency table from round 1
- `{topic_frequency}` — same frequency table from round 1
- `{concept_titles}` — same concept list from round 1
- `{categories_str}` — available article types

Output schema: same as round 1 (`{"articles": [...]}`) — the complete refined plan, not a diff.

#### 3.2.2 Prompt Content

The feedback prompt asks the LLM to:
1. Review the first-round plan against the frequency data.
2. Identify high-frequency entities/topics/concepts not adequately covered.
3. Identify redundant or overly narrow articles that could be merged.
4. Return a complete refined plan (same JSON schema as round 1).

The key instruction: "Return the FULL refined plan, not just changes. Every article from the original plan that should be kept must appear in your output."

#### 3.2.3 `plan_aggregation` Two-Round Flow

```python
def plan_aggregation(topic, entity_index, *, categories, model) -> list[ThematicArticle]:
    # --- Round 1 (unchanged) ---
    top_entities = _build_frequency_table(entity_index.entities, 50)
    top_topics = _build_frequency_table(entity_index.topics, 30)
    top_concepts = _build_frequency_table(entity_index.concepts, 30)
    # ... render aggregate-plan prompt, call completion_json ...
    # ... validate → round1_valid: list[ThematicArticle] ...

    if len(round1_valid) < _MIN_ARTICLES:
        raise DeriveError(...)

    # --- Round 2: feedback ---
    first_round_json = json.dumps(
        [a.to_dict() for a in round1_valid], indent=2
    )
    feedback_prompt = default_registry().get("aggregate-plan-feedback").render(
        topic=topic,
        first_round_articles=first_round_json,
        entity_frequency=entity_freq_lines,
        topic_frequency=topic_freq_lines,
        concept_titles=concept_lines,
        categories_str=categories_str,
    )
    feedback_messages = [
        {"role": "system", "content": feedback_prompt},
        {"role": "user", "content": f"Review and refine the article plan for: {topic}"},
    ]

    try:
        feedback_response = completion_json(
            model=model, messages=feedback_messages, max_tokens=4096,
        )
    except Exception as exc:
        # Graceful degradation: if round 2 fails, return round 1 results
        print(f"[reorganize] feedback round failed, using round 1: {exc}",
              file=sys.stderr, flush=True)
        return round1_valid

    # Parse and validate round 2 (same logic as round 1)
    raw_articles_r2 = feedback_response.get("articles", [])
    if not isinstance(raw_articles_r2, list):
        print("[reorganize] feedback round returned invalid format, using round 1",
              file=sys.stderr, flush=True)
        return round1_valid

    # ... same validation loop as round 1 → rebalanced_valid ...
    rebalanced_valid = rebalanced_valid[:_MAX_ARTICLES]
```

#### 3.2.4 Dedup by Path

The LLM may return duplicate paths in the refined plan. Dedup by `path`:

```python
    seen_paths: set[str] = set()
    deduped: list[ThematicArticle] = []
    for article in rebalanced_valid:
        if article.path not in seen_paths:
            seen_paths.add(article.path)
            deduped.append(article)
    rebalanced_valid = deduped
```

#### 3.2.5 Guard: Refined Plan Must Not Shrink

After round-2 validation, if the refined plan has fewer valid articles than round 1, discard round 2 and use round 1. This prevents the feedback round from hallucinating a worse plan.

#### 3.2.6 Complete Post-Round-2 Sequence (fixes SEVERE review issue)

The exact order after parsing round 2's `raw_articles_r2` is:

```python
    # 1. Validate each article (same loop as round 1)
    rebalanced_valid: list[ThematicArticle] = []
    for item in raw_articles_r2:
        # ... _is_safe_wiki_path, type check, title check ...
        rebalanced_valid.append(ThematicArticle(...))

    # 2. Clamp to max
    rebalanced_valid = rebalanced_valid[:_MAX_ARTICLES]

    # 3. Dedup by path (BEFORE the count check)
    seen_paths: set[str] = set()
    deduped: list[ThematicArticle] = []
    for article in rebalanced_valid:
        if article.path not in seen_paths:
            seen_paths.add(article.path)
            deduped.append(article)
    rebalanced_valid = deduped

    # 4. Guard: refined plan must not shrink (AFTER dedup)
    if len(rebalanced_valid) < len(round1_valid):
        print("[reorganize] feedback round shrunk the plan, using round 1",
              file=sys.stderr, flush=True)
        return round1_valid

    return rebalanced_valid
```

**Key fix (addressing SEVERE from Round 2 review):** Deduplication (step 3) runs BEFORE the count comparison (step 4). This means the count check compares the actual unique-path count against round 1, not a count inflated by duplicates. Without this ordering, a round-2 plan with 6 articles but 2 duplicate paths would pass the `>= len(round1_valid)` check with count 6, then deliver only 4 unique articles after a hypothetical later dedup — violating the no-shrink invariant.

## 4. Interface Contracts

### 4.1 `_get_batch_parallel_threshold()` — Internal Function

**Signature:**
```python
def _get_batch_parallel_threshold() -> int:
```

**Behavior:**
- Returns `int(os.environ["KB_BATCH_PARALLEL_THRESHOLD"])` if set, valid, and ≥ 0.
- Returns `_BATCH_PARALLEL_THRESHOLD` (default 4) otherwise.
- Warns once to stderr for invalid values (same pattern as `_warn_invalid_batch_parallel`).

**Module-level constants** (added near line 71 of `compile.py`):
```python
_BATCH_PARALLEL_THRESHOLD: int = 4
_BATCH_PARALLEL_THRESHOLD_ENV: str = "KB_BATCH_PARALLEL_THRESHOLD"
```

### 4.2 `_merge_batch_split()` — Modified Internal Function

**Signature:** unchanged.

**Behavioral change:** After Phase A break, before Phase B dispatch:
- Reads threshold via `_get_batch_parallel_threshold()`.
- If `len(remaining) <= threshold`: runs single synchronous `_run_chain()` (serial fallback), skips `_pre_split_chains()` and `ThreadPoolExecutor`.
- If `len(remaining) > threshold`: proceeds to existing Phase B logic (unchanged).

**Return type:** unchanged: `tuple[list[tuple[str, str]], list[str], int]`.

### 4.3 `plan_aggregation()` — Modified Internal Function

**Signature:** unchanged.

```python
def plan_aggregation(
    topic: str,
    entity_index: EntityIndex,
    *,
    categories: list[str],
    model: str,
) -> list[ThematicArticle]:
```

**Behavioral change:** After round 1 validation (unchanged), performs a second LLM call using the `aggregate-plan-feedback` prompt. The round 2 result undergoes the same validation, then dedup-by-path, then a count guard (must not shrink vs round 1). On any round-2 failure, degrades gracefully to round 1 results.

**Return type:** unchanged: `list[ThematicArticle]`.

### 4.4 `aggregate-plan-feedback.md` — New Prompt Template

**Template variables (all required):**

| Variable | Type | Description |
|----------|------|-------------|
| `{topic}` | `str` | The KB topic. |
| `{first_round_articles}` | `str` | JSON array of round-1 articles (serialized via `json.dumps`). |
| `{entity_frequency}` | `str` | Entity frequency lines (`"name — count\n..."`). |
| `{topic_frequency}` | `str` | Topic frequency lines (`"tag — count\n..."`). |
| `{concept_titles}` | `str` | Concept titles, one per line. |
| `{categories_str}` | `str` | Comma-separated category names. |

**Output schema** (same as round 1):
```json
{
  "articles": [
    {
      "path": "string (required, must match wiki/<type>/slug.md)",
      "type": "string (required, must be one of categories)",
      "title": "string (required, non-empty)",
      "description": "string (required, 1-2 sentence description)"
    }
  ]
}
```

**LLM call parameters:**
- `model`: passthrough from `plan_aggregation` argument
- `max_tokens`: 4096
- `cache`: not set (unlike `resolve_entities`, the feedback prompt is unique per run)

### 4.5 Data Model: No Changes

No new dataclasses. `ThematicArticle`, `ReorganizePlan`, `EntityIndex` are unchanged. The two-round logic is internal to `plan_aggregation()` — the function's interface and return type remain identical.

## 5. Implementation Steps

### Step 1: batch_parallel_threshold

#### Step 1.1: Add constant, env var, and helper

**File:** `py/src/kb_ai/commands/compile.py`

Near line 71 (after `_BATCH_PARALLEL_MAX_CONCURRENT` and `_BATCH_PARALLEL_ENV`):

1. Add `_BATCH_PARALLEL_THRESHOLD: int = 4`.
2. Add `_BATCH_PARALLEL_THRESHOLD_ENV: str = "KB_BATCH_PARALLEL_THRESHOLD"`.
3. Add `_warn_invalid_batch_parallel_threshold()` — `@functools.lru_cache(maxsize=1)`, prints warning to stderr, same pattern as `_warn_invalid_batch_parallel()`.
4. Add `_get_batch_parallel_threshold() -> int` — reads env var, validates ≥ 0, warns on invalid, returns default on failure.

#### Step 1.2: Modify `_merge_batch_split` Phase B entry

**File:** `py/src/kb_ai/commands/compile.py`

In `_merge_batch_split()`, after the `if not remaining: return` fast-path block (line ~525) and before the current `# -- Phase B` comment:

Replace the current Phase B block with:

```python
    # -- Phase B: dispatch for remaining items ---------------------
    chain_ctx = get_context()
    threshold = _get_batch_parallel_threshold()

    if len(remaining) <= threshold:
        # Serial fallback: not enough items to justify thread pool overhead.
        result = _run_chain(
            art_path, remaining, write_model,
            article_type=article_type,
            title=f"{title} (Part {part_num + 1})",
            start_part_num=part_num + 1,
            parent_ctx=chain_ctx, sem=None,
        )
        all_rels.extend(result.all_rels)
        batch_num += result.n_batches
        chain_articles = result.articles
    else:
        # Parallel dispatch (existing logic)
        sem = _get_batch_parallel_sem()
        chunks = _pre_split_chains(remaining, article_type, title)
        chain_articles = []

        if len(chunks) == 1 and len(chunks[0]) <= 1:
            result = _run_chain(
                art_path, chunks[0], write_model,
                article_type=article_type,
                title=f"{title} (Part {part_num + 1})",
                start_part_num=part_num + 1,
                parent_ctx=chain_ctx, sem=None,
            )
            all_rels.extend(result.all_rels)
            batch_num += result.n_batches
            chain_articles.extend(result.articles)
        else:
            with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
                futures = []
                for i, chunk in enumerate(chunks):
                    chunk_title = f"{title} (Part {part_num + 1 + i})"
                    fut = pool.submit(
                        _run_chain, art_path, chunk, write_model,
                        article_type=article_type,
                        title=chunk_title,
                        start_part_num=part_num + 1 + i * 100,
                        parent_ctx=chain_ctx,
                        sem=sem,
                    )
                    futures.append(fut)
                for fut in futures:
                    result = fut.result()
                    all_rels.extend(result.all_rels)
                    batch_num += result.n_batches
                    chain_articles.extend(result.articles)

    # -- Phase C: collect + re-number all sub-articles -------------
    all_sub_articles = list(finalized_articles) + chain_articles
    # ... (rest unchanged)
```

Note: `chain_articles` is either a `list` (serial) or built up via `extend` (parallel). Phase C is unchanged.

#### Step 1.3: Add tests for threshold

**File:** `py/tests/test_compile_batch_split.py`

Add to `TestMergeBatchSplitParallel`:

1. **`test_serial_fallback_below_threshold`**: Set up 6 items with budgets that cause Phase A to split after 2. Remaining = 4 items. Set `KB_BATCH_PARALLEL_THRESHOLD=4`. Monkeypatch `ThreadPoolExecutor.__init__` to set a flag. Assert `ThreadPoolExecutor` was NOT created. Assert all rels present and articles correctly numbered.

2. **`test_parallel_above_threshold`**: Same setup but with 12 items (remaining = 10 after Phase A). Set `KB_BATCH_PARALLEL_THRESHOLD=4`. Assert `ThreadPoolExecutor` WAS created. Assert correct output.

3. **`test_threshold_zero_always_parallel`**: Set `KB_BATCH_PARALLEL_THRESHOLD=0`. Even with 2 remaining items, thread pool is created.

4. **`test_threshold_env_invalid_uses_default`**: Set `KB_BATCH_PARALLEL_THRESHOLD=abc`. Assert default behavior (4).

5. **`test_threshold_env_negative_uses_default`**: Set `KB_BATCH_PARALLEL_THRESHOLD=-1`. Assert default behavior.

Also add a standalone test class `TestGetBatchParallelThreshold`:

1. **`test_returns_default`**: No env var → returns 4.
2. **`test_reads_env`**: Env var = "8" → returns 8.
3. **`test_zero_valid`**: Env var = "0" → returns 0.
4. **`test_invalid_warns_once`**: Env var = "bad" → returns default, warns to stderr.
5. **`test_negative_warns`**: Env var = "-5" → returns default, warns.

**Depends on:** Step 1.1, 1.2.

### Step 2: Two-Round Feedback

#### Step 2.1: Create feedback prompt template

**File:** `py/src/kb_ai/prompts/defaults/aggregate-plan-feedback.md`

Content:

```markdown
You are refining the article plan for a topic-focused knowledge base.

Topic: {topic}

Below is the initial article plan:
{first_round_articles}

Below are the frequency tables from the source documents:

Top entities (canonical name — occurrence count):
{entity_frequency}

Top topic tags (tag — occurrence count):
{topic_frequency}

Top concept titles:
{concept_titles}

Available article types: {categories_str}

Review the initial plan against the frequency data and improve it:
1. Identify high-frequency entities, topics, or concepts that are NOT adequately covered by any article.
2. Identify articles that are too narrow or redundant and could be merged.
3. Ensure the main topic entity has a comprehensive overview article.
4. Check that major themes (appearing in >=3 source documents) have dedicated articles.

Return the FULL refined plan as JSON — every article that should be in the final plan must appear in your output, including articles from the original plan that need no changes.

Return JSON:
{{{{
  "articles": [
    {{{{
      "path": "wiki/<type>/suggested-slug.md",
      "type": "<one of: {categories_str}>",
      "title": "Article Title",
      "description": "1-2 sentence description of what this article should cover"
    }}}}
  ]
}}}}

Rules:
- Return 3-15 articles
- path must start with wiki/ and use the type as subdirectory
- path must use lowercase alphanumeric slugs with hyphens
- type must be one of: {categories_str}
- Do NOT return duplicate paths
```

#### Step 2.2: Implement two-round logic in `plan_aggregation`

**File:** `py/src/kb_ai/derive/_reorganize.py`

Add `import json` at top (if not already present).

In `plan_aggregation()`, after the existing round 1 validation (after `valid = valid[:_MAX_ARTICLES]` and the `len(valid) < _MIN_ARTICLES` check):

1. Rename the existing `valid` variable to `round1_valid` for clarity (or keep as `valid` and assign `round1_valid = valid` after the min check).
2. Build `first_round_json = json.dumps([a.to_dict() for a in round1_valid], indent=2)`.
3. Render `aggregate-plan-feedback` prompt using `default_registry().get("aggregate-plan-feedback")`.
4. Call `completion_json(model=model, messages=feedback_messages, max_tokens=4096)`.
5. Parse `raw_articles_r2`, validate with same loop (path, type, title), build `rebalanced_valid`.
6. Clamp: `rebalanced_valid = rebalanced_valid[:_MAX_ARTICLES]`.
7. Dedup by path: iterate, track `seen_paths`, build `deduped`.
8. Assign `rebalanced_valid = deduped`.
9. Guard: `if len(rebalanced_valid) < len(round1_valid): return round1_valid`.
10. Return `rebalanced_valid`.

Wrap steps 3-10 in a try/except for graceful degradation: if anything fails, print warning and return `round1_valid`.

**Depends on:** Step 2.1.

#### Step 2.3: Add tests for two-round feedback

**File:** `py/tests/test_reorganize_plan.py`

Add a new test class `TestPlanAggregationFeedback`:

1. **`test_feedback_round_refines_plan`**: Mock `completion_json` to return 5 articles on round 1, then 6 articles (adding one new article) on round 2. Assert final result has 6 articles.

2. **`test_feedback_round_dedup_by_path`**: Round 2 returns articles with duplicate paths. Assert duplicates are removed.

3. **`test_feedback_shrink_falls_back_to_round1`**: Round 2 returns fewer valid articles than round 1. Assert round 1 result is returned. Assert warning printed to stderr.

4. **`test_feedback_llm_failure_falls_back_to_round1`**: Round 2 `completion_json` raises `RuntimeError`. Assert round 1 result is returned. Assert warning.

5. **`test_feedback_invalid_format_falls_back_to_round1`**: Round 2 returns `{"articles": "not a list"}`. Assert round 1 is returned.

6. **`test_feedback_prompt_contains_round1_articles`**: Capture the `completion_json` calls. Assert round 2's system message contains the JSON of round 1 articles.

7. **`test_feedback_prompt_contains_frequency_data`**: Assert round 2's system message contains entity/topic/concept frequency data.

8. **`test_feedback_validates_paths_and_types`**: Round 2 returns articles with invalid paths/types mixed with valid ones. Assert only valid ones survive.

9. **`test_feedback_dedup_before_count_check`**: Round 2 returns 5 articles with 2 duplicate paths (3 unique). Round 1 had 4 valid. Assert round 1 is returned (3 unique < 4 round-1), confirming dedup runs before the count guard.

10. **`test_feedback_clamped_to_max_articles`**: Round 2 returns 20 articles. Assert clamped to 15.

Also update existing `TestReorganize.test_end_to_end` to expect 3 `completion_json` calls instead of 2 (resolve_entities + round 1 + round 2), or make the mock handle the feedback round.

#### Step 2.4: Add prompt template rendering test

**File:** `py/tests/test_reorganize_plan.py`

Add to `TestPromptTemplate`:

1. **`test_aggregate_plan_feedback_template_renders`**: Load `aggregate-plan-feedback` from `default_registry()`, render with all variables, assert key content present.

2. **`test_aggregate_plan_feedback_template_has_required_variables`**: Render with minimal values, assert no `KeyError`.

**Depends on:** Step 2.1.

## 6. Risks and Mitigations

### Risk 1: Threshold too high → never parallelize

**Impact:** Large remaining item sets run serially, regressing performance.
**Mitigation:** Default threshold of 4 is conservative. With typical budget/item ratios (100-200 budget, items ~100 chars), 4 items means 1-2 batches — serial is faster. The env var `KB_BATCH_PARALLEL_THRESHOLD` allows tuning without code changes. Setting it to 0 restores the current always-parallel behavior.

### Risk 2: Two-round feedback doubles LLM cost for aggregation planning

**Impact:** Every `plan_aggregation` call makes 2 LLM calls instead of 1.
**Mitigation:** Aggregation planning is called once per reorganize run (not per document), so cost is bounded: 2 calls × ~4K tokens each = ~8K tokens total. This is negligible compared to the extraction phase (1 call per document × many documents). The feedback round's graceful degradation (fall back to round 1 on failure) means it never blocks the pipeline.

### Risk 3: Round 2 LLM hallucinates worse plan

**Impact:** Feedback round produces fewer/worse articles than round 1.
**Mitigation:** The count guard ensures round 2 is used ONLY if it has ≥ as many valid articles as round 1. Dedup runs before the count check (fixing the SEVERE from Round 2 review), so duplicate paths cannot inflate the count. On any validation failure, we fall back to round 1.

### Risk 4: Dedup changes ordering

**Impact:** If the LLM returns duplicates, the first occurrence wins. This could theoretically drop a "better" description for a path.
**Mitigation:** Acceptable trade-off. The LLM is instructed not to return duplicates ("Do NOT return duplicate paths"). Dedup is a safety net, not the primary mechanism. First-occurrence-wins preserves the LLM's intended ordering.

### Risk 5: Existing test suite breaks

**Impact:** Changes to `_merge_batch_split` internal flow could break existing parallel tests.
**Mitigation:** Existing tests use 8-12 items with Phase A taking 1-2. With default threshold=4, remaining 6-10 items exceed threshold → parallel path unchanged. Tests for `test_parallel_chains_concurrent_execution` (8 items, remaining ~7) and `test_semaphore_limits_concurrency` (10 items) both exceed 4. The `test_no_parallelism_without_split` test doesn't trigger Phase B at all. No existing test should break.

For the `test_end_to_end` reorganize test: the mock `completion_json` dispatches on system message content. Adding a third call (feedback round) requires the mock to handle it. Fix: update the mock to return a valid plan for any non-entity-resolver call (which it already does — the `else` branch returns `plan_response`).
