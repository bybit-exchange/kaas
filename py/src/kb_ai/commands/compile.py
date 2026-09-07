import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from kb_ai.core.classify import (
    classify_article,
    classify_article_topical,
    classify_cache_key,
    classify_inputs_hash,
    dedup_create_new,
    hash_existing_articles,
    resolve_categories,
)
from kb_ai.core.extract import (
    STRATEGY_AUTO,
    STRATEGY_CHUNKED,
    ExtractionResult,
    plan_extraction,
    run_planned_extraction,
    validate_strategy,
    _combine_extractions,
)
from kb_ai.prompts import PromptError
from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.index import (
    SUMMARY_MAX_CHARS,
    update_document_index,
    update_markdown_index,
    update_timeline,
)
from kb_ai.core.people import update_people_stubs
from kb_ai._context import adopt_context, get_context
from kb_ai.llm import CostTracker, tracker, get_request_tracker, set_request_tracker
from kb_ai.core.merge import (
    _SUB_ARTICLE_BUDGET_THRESHOLD,
    _estimate_full_extraction_size,
    create_new_article,
    estimate_create_budget,
    estimate_merge_budget,
    merge_into_article,
    write_prompt_version,
)
from kb_ai.storage.lag import wiki_lag
from kb_ai.storage.store import ArticleMeta, KBStore, _compute_checksum

_DEFAULT_WORKERS = 16


@contextmanager
def _compile_log(log_path: Path):
    """Open the KB's .compile.log and route LLM warnings into it for the duration.

    Yields log(msg, stderr=True). The alert sink writes to the file only, because
    emit_alert has already put the line on stderr.

    Restored on the way out: the sink closes over this file handle, and in the
    long-lived daemon the same thread goes on to serve later requests.
    """
    lock = threading.Lock()
    with open(log_path, "w") as log_file:
        def log(msg: str, *, stderr: bool = True):
            with lock:
                print(msg, file=log_file, flush=True)
                if stderr:
                    print(msg, file=sys.stderr, flush=True)

        ctx = get_context()
        prev = ctx.alert_sink
        ctx.alert_sink = lambda msg: log(msg, stderr=False)
        try:
            yield log
        finally:
            ctx.alert_sink = prev


@contextmanager
def _measure_op_cost():
    """Yield a tracker holding only the LLM spend of the enclosed write op.

    The write phase runs one worker per article group, so a delta of the
    process-wide tracker taken here also captures whatever the other workers
    spent in the same window. On a 16-worker run that made every per-article cost
    line read like the whole fleet's spend: 73 lines summing to 49.57 USD against
    a phase that really cost 3.66 USD.

    A nested tracker sees this op's calls alone, and folds them into the
    enclosing request tracker on the way out so per-request accounting still
    totals correctly. The process-wide tracker is unaffected either way — it
    records every call directly, which is what the phase summaries read.
    """
    op_tracker = CostTracker()
    parent = get_request_tracker()
    set_request_tracker(op_tracker)
    try:
        yield op_tracker
    finally:
        set_request_tracker(parent)
        if parent is not None:
            parent.absorb(op_tracker)


def _under_wiki(store: KBStore, art_path: str) -> bool:
    """Whether art_path resolves inside the wiki subtree.

    Article paths come from LLM output, so the "wiki/" prefix alone is not
    enough: "wiki/../raw/a.md" keeps the prefix and still escapes the subtree,
    where it could clobber a raw source, the compile log or a generated index.
    """
    if not art_path.startswith("wiki/"):
        return False
    wiki_root = store.wiki_dir.resolve()
    return str((store.base_dir / art_path).resolve()).startswith(str(wiki_root) + os.sep)


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
        # Single extraction exceeds budget — take it anyway;
        # _fit_extraction_to_budget will truncate it within the LLM call.
        batch.append(remaining.pop(0))
    return batch, remaining


def _merge_batch_split(
    art_path: str,
    items: list[tuple[str, ExtractionResult]],
    write_model: str,
    *,
    article_content: str | None,
    article_type: str = "",
    title: str = "",
) -> tuple[list[tuple[str, str]], list[str], int]:
    """Iteratively merge sources into an article in batches.

    When the merge budget drops below _SUB_ARTICLE_BUDGET_THRESHOLD during
    iteration, the current article is finalized as a sub-article and a fresh
    article starts for the remaining sources.

    Args:
        art_path: Target article path (e.g. "wiki/concept/foo.md").
        items: The source list, each (rel_path, ExtractionResult). Extracted
               from the merges list by the caller.
        write_model: LLM model name.
        article_content: Existing article text, or None if creating new.
        article_type: Article type (used only when article_content is None).
        title: Article title (used only when article_content is None).

    Returns:
        (articles, all_rel_paths, n_batches):
            articles: List of (path, content) pairs. Single-element when no
                sub-article split occurs (path == art_path); multi-element
                with -part-N paths when a split is triggered.
            all_rel_paths: All source rel_paths processed (same order as items).
            n_batches: Total number of batches across all sub-articles.

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
        - When budget drops below threshold, current article is finalized as
          a sub-article and a new one begins for remaining sources
    """
    all_rels: list[str] = []
    remaining = list(items)
    current_content = article_content
    batch_num = 0
    finalized_articles: list[tuple[str, str]] = []
    part_num = 0
    current_source_count = 0

    while remaining:
        # Check sub-article threshold: after a merge completes and before
        # packing the next batch, see if the current article is too large
        # to continue receiving merges.
        if current_content is not None:
            budget = estimate_merge_budget(current_content)
            if budget < _SUB_ARTICLE_BUDGET_THRESHOLD:
                # Finalize current article as a sub-article and start fresh
                part_num += 1
                sub_path = _sub_article_path(art_path, part_num)
                finalized_articles.append((sub_path, current_content))
                print(f"  [merge-split] {art_path} → sub-article {sub_path} "
                      f"({len(current_content)} chars, {current_source_count} sources)",
                      file=sys.stderr, flush=True)
                current_content = None
                current_source_count = 0
                # budget is stale; will be recomputed below as create budget
            # else: budget is valid, reuse it below for _pack_merge_batch

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
            # Create a new (sub-)article
            part_title = title if not finalized_articles else f"{title} (Part {part_num + 1})"
            print(f"  [merge-split] {art_path} batch {batch_num}: "
                  f"create ← {len(batch)} sources", file=sys.stderr, flush=True)
            current_content = create_new_article(
                article_type, part_title, combined,
                ", ".join(batch_rels), model=write_model)
        else:
            # Merge into existing/intermediate article
            print(f"  [merge-split] {art_path} batch {batch_num}: "
                  f"merge ← {len(batch)} sources", file=sys.stderr, flush=True)
            current_content = merge_into_article(
                art_path, current_content, combined,
                ", ".join(batch_rels), model=write_model)

    # Finalize the last article
    if current_content is not None:
        if finalized_articles:
            # Was a sub-article split: the last chunk is also a sub-article
            part_num += 1
            sub_path = _sub_article_path(art_path, part_num)
            finalized_articles.append((sub_path, current_content))
        else:
            # No split occurred: single article at the original path
            finalized_articles.append((art_path, current_content))

    return finalized_articles, all_rels, batch_num

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
    aggregation_plan: list[dict] | None = None,
    topic: str = "",
) -> dict:
    compile_t0 = time.monotonic()

    # Checked before anything else: a typo here would otherwise be discovered
    # after the scan, or -- if it fell back to chunked, as the daemon used to --
    # never. The strategy is a per-KB contract, so both routes read one value and
    # the gate compares against what a run would actually produce (C4's shape,
    # one field over).
    validate_strategy(extract_strategy)
    # The summarize path drives a second model once per chunk, so an empty name
    # would reach the API. auto counts too: it resolves to summarize per document,
    # which would fail partway through a run that had already paid for the chunked
    # documents ahead of it.
    if extract_strategy != STRATEGY_CHUNKED and not summarize_model:
        raise ValueError(f"extract_strategy={extract_strategy!r} needs a "
                         "summarize_model; the summarize path calls one per chunk")

    people_cfg = people_cfg or []

    store = KBStore(data_dir)
    categories = resolve_categories(store, categories)
    state = store.load_compile_state()
    # Metadata only: both gates need rel_path and checksum, and nothing else here
    # needs a document's text until the extraction gate has selected it. Holding
    # every document's content cost ~62 KB retained per document (6.79 MB over the
    # 108-document reference KB), which scales linearly with the corpus.
    # Materialised as a list because the two gates and the lag report each iterate
    # it; RawFileMeta carries no content, so that costs 0.05 MB at 108 documents.
    #
    # Byte-equivalence with the previous checksum is what makes this migration
    # free rather than a re-extraction of every document: verified over all 108
    # files of data/kb-2026-06, 0 differences.
    raw_files = list(store.iter_raw_file_meta())

    # One per-process constant, computed once before the gate so a broken prompt
    # file is reported once rather than 108 times -- and never silently treated as
    # "fresh", which would keep serving extractions from the previous prompt.
    try:
        prompt_version = extraction_layer.current_prompt_version()
    except PromptError as e:
        return {"compiled": 0, "extracted": 0, "total_raw": len(raw_files),
                "errors": [{"file": "", "error": f"prompt_version unavailable: {e}"}],
                "message": "extraction prompts are unreadable; nothing was compiled"}

    # The write phase's own version, recorded per document and reported, never
    # gated -- see storage/lag.py for why re-composing on a prompt edit would be
    # worse than the lag. Its own try because the write prompts are not this run's
    # inputs: an --extract-only run must not be refused over a prompt it never
    # reaches, least of all after paying for the extraction. Empty means "cannot
    # tell", which the lag report distinguishes from "nothing is behind".
    try:
        write_version = write_prompt_version()
    except PromptError as e:
        write_version = ""
        print(f"[compile] write prompt version unavailable: {e}", file=sys.stderr)

    # ── Gate 1: extraction, gated by the extraction file's own provenance ──
    # Independent of gate 2 by design: a prompt edit re-extracts and stops there.
    # Re-running the write phase would not rewrite articles from the new
    # extraction -- both merge paths can only add -- it would layer new content on
    # top of the old extraction's content (spec G1, G4).
    def _expected_strategy(rel_path: str) -> str:
        """The strategy a run would record for this document.

        chunked and summarize are honoured as configured, so the common case
        compares a constant and reads nothing. Only auto resolves per document,
        which costs a full read and a chunk count per document -- no LLM call, and
        nothing retained past the comparison. Comparing against a literal instead
        is what made every summarize extraction read as stale, forever, once per
        document.
        """
        if extract_strategy != STRATEGY_AUTO:
            return extract_strategy
        return plan_extraction(store.read_raw(rel_path), STRATEGY_AUTO).strategy

    to_extract = []
    extract_reasons: dict[str, str] = {}
    for rf in raw_files:
        stored, reason = extraction_layer.load(store, rf.rel_path)
        if stored is None:
            why = reason
        else:
            why = extraction_layer.staleness(
                stored.provenance,
                source_checksum=rf.checksum,
                extract_model=extract_model,
                extract_strategy=_expected_strategy(rf.rel_path),
                prompt_version=prompt_version,
                summarize_model=summarize_model,
            )
        if why:
            extract_reasons[rf.rel_path] = why
            to_extract.append(rf)

    # ── Gate 2: composition, gated by .compile-state.json as before ──
    to_write = []
    if not extract_only:
        for rf in raw_files:
            file_state = state.get(rf.rel_path, {})
            if file_state.get("checksum") != rf.checksum:
                to_write.append(rf)
            elif file_state.get("completed_ops") and not file_state.get("compiled_at"):
                to_write.append(rf)

    if not to_extract and not to_write:
        return {"compiled": 0, "extracted": 0, "message": "nothing to compile"}

    # The wiki can lag its prompts under two independent gates, and that lag is
    # reported rather than left silent (G5). No pre-existing state entry carries
    # either version, so the first run after each one landed reports every
    # article -- true, but it reads as a defect without the reason.
    lag = wiki_lag(state, present={rf.rel_path for rf in raw_files},
                   extract_prompt_version=prompt_version,
                   write_prompt_version=write_version)

    compiled = 0
    extracted = 0
    revised: list[str] = []
    failed_extract: set[str] = set()
    errors: list[dict] = []
    cfg_workers = workers or int(os.environ.get("KB_WORKERS", 0))
    workers = min(max(len(to_extract), len(to_write)),
                  cfg_workers if cfg_workers > 0 else _DEFAULT_WORKERS)

    _no_delta = {"cost": 0.0, "elapsed": 0.0}
    extract_d = classify_d = write_d = _no_delta

    log_path = Path(data_dir).expanduser() / ".compile.log"

    with _compile_log(log_path) as log:
        # Captured in the parent thread; the pool workers install a copy of it so
        # their LLM calls carry this compile's tracker, alert sink and phase label.
        _parent_ctx = get_context()

        log(f"Starting compile: {len(to_extract)} to extract, "
            f"{len(to_write)} to compose (workers={workers})")
        if lag.behind_extract:
            if lag.extract_first_run:
                log(f"  (wiki lag: {len(lag.behind_extract)} articles were written "
                    "from an older extraction — expected on the first run after the "
                    "extraction layer landed, since no existing compile-state entry "
                    "records a prompt_version)")
            else:
                log(f"  (wiki lag: {len(lag.behind_extract)} articles were written "
                    "from an older extraction; they are rewritten when their source "
                    "text changes)")
        if lag.behind_write:
            because = (" — expected on the first run after write_prompt_version "
                       "landed, since no existing compile-state entry records one"
                       if lag.write_first_run else "")
            log(f"  (wiki lag: {len(lag.behind_write)} articles were composed by an "
                f"older write prompt{because}; that is reported, never re-composed "
                f"— both merge paths only add. Run `kb-ai check --kb {data_dir}` to "
                "list them.)")

        # ── Phase 1: Parallel extraction ──────────────────────────
        extract_snap = tracker.snapshot()

        def _extract_one(rf):
            adopt_context(_parent_ctx, phase=f"extract:{rf.rel_path}")
            # Read here rather than during the scan: this is the one place a
            # document's text is needed, and only for what the gate selected.
            content = store.read_raw(rf.rel_path)
            plan = plan_extraction(content, extract_strategy)
            result = run_planned_extraction(
                plan, content, extract_model=extract_model,
                summarize_model=summarize_model)
            _path, existed = extraction_layer.persist(
                store, rf.rel_path, result,
                # Hashed from the text this extraction was actually made from, not
                # from the scan: the two are separate reads now, and both ingestion
                # routes write into raw/. A document rewritten in between and then
                # reverted would otherwise leave a file whose recorded checksum
                # matches the document while its payload describes text that is no
                # longer there -- and the gate would call it fresh forever.
                source_checksum=_compute_checksum(content),
                extract_model=extract_model,
                # plan.strategy, never the configured value: under auto the router
                # decides on chunk count, and recording "auto" would make the field
                # useless to the gate that compares it.
                extract_strategy=plan.strategy,
                summarize_model=summarize_model,
            )
            return rf.rel_path, existed

        if to_extract:
            log(f"Phase 1: Extracting {len(to_extract)} files in parallel...")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_extract_one, rf): rf for rf in to_extract}
                for future in as_completed(futures):
                    rf = futures[future]
                    try:
                        _rel, existed = future.result()
                    except Exception as e:
                        errors.append({"file": rf.rel_path, "error": str(e)})
                        failed_extract.add(rf.rel_path)
                        log(f"  [extract-error] {rf.rel_path}: {e}")
                        continue
                    extracted += 1
                    if existed:
                        revised.append(rf.rel_path)
                    tag = "re-extracted" if existed else "extracted"
                    log(f"  [{tag}] {rf.rel_path} — {extract_reasons[rf.rel_path]}")
        else:
            log("Phase 1: every extraction is present and fresh, skipping LLM calls.")

        extract_d = tracker.delta(extract_snap)
        log(f"Phase 1 done: {extracted} extracted ({len(revised)} revised), "
            f"{len(errors)} errors, ${extract_d['cost']:.4f}, {extract_d['elapsed']:.1f}s")

        if not to_write:
            reason = ("--extract-only" if extract_only
                      else "no document's composition is behind")
            log(f"Stopping after extraction ({reason}).")

        # ── Phase 2a: Sequential classify ─────────────────────────
        # Classify and write read the extraction off disk (D1), so extraction/ is
        # the only thing handing off between the two gates.
        existing_articles = store.existing_articles()

        _planned_article_meta: dict[str, dict] = {}
        if aggregation_plan is not None:
            for planned in aggregation_plan:
                p = planned.get("path", "")
                t = planned.get("title", "")
                tp = planned.get("type", "")
                desc = planned.get("description", "")
                if p and t:
                    existing_articles.append(ArticleMeta(title=t, path=p, summary=desc))
                    _planned_article_meta[p] = {"title": t, "type": tp}

        classify_snap = tracker.snapshot()

        extractions: dict[str, ExtractionResult] = {}
        used_prompt_version: dict[str, str] = {}
        for rf in to_write:
            stored, reason = extraction_layer.load(store, rf.rel_path)
            if stored is None:
                # A document whose extraction just failed already has its error
                # recorded; reporting the consequence again would double-count it.
                if rf.rel_path not in failed_extract:
                    errors.append({"file": rf.rel_path,
                                   "error": f"no usable extraction ({reason})"})
                log(f"  [no-extraction] {rf.rel_path}: {reason}")
                continue
            stored.extraction.source_path = rf.rel_path
            extractions[rf.rel_path] = stored.extraction
            used_prompt_version[rf.rel_path] = stored.provenance.prompt_version

        if to_write and not extractions:
            log("No usable extraction for any document to compose, aborting compile.")
            return {"compiled": 0, "extracted": extracted, "errors": errors,
                    "total_raw": len(raw_files), "cost": tracker.summary()}

        items_to_classify = []
        for rf in to_write:
            if rf.rel_path not in extractions:
                continue
            items_to_classify.append((rf, extractions[rf.rel_path]))

        classifications: dict[str, dict] = {}
        classify_cache_hits = 0
        art_hash = hash_existing_articles(existing_articles)
        cat_hash = classify_inputs_hash(categories)

        if items_to_classify:
            log(f"Phase 2a: Classifying {len(items_to_classify)} files sequentially...")
        for rf, extraction in items_to_classify:
            if aggregation_plan is not None:
                # Skip classify cache: the topical prompt incorporates the
                # aggregation plan which varies per derive run.
                try:
                    result = classify_article_topical(
                        extraction, existing_articles, topic, aggregation_plan,
                        model=compile_model, categories=categories)
                    # No dedup_create_new — topical prompt handles routing
                    classifications[rf.rel_path] = result
                    log(f"  [classified-topical] {rf.rel_path}")
                    for create in result.get("create_new", []):
                        existing_articles.append(ArticleMeta(
                            title=create.get("title", ""), path=create.get("path", ""), summary="",
                        ))
                except Exception as e:
                    errors.append({"file": rf.rel_path, "error": str(e)})
                    log(f"  [classify-error] {rf.rel_path}: {e}")
                continue

            cache_key = classify_cache_key(rf.checksum, art_hash, cat_hash)
            cached = store.load_classify_cache(cache_key)
            if cached is not None:
                classifications[rf.rel_path] = cached
                classify_cache_hits += 1
                log(f"  [classify-cached] {rf.rel_path}")
                for create in cached.get("create_new", []):
                    existing_articles.append(ArticleMeta(
                        title=create.get("title", ""), path=create.get("path", ""), summary="",
                    ))
                continue

            try:
                result = classify_article(extraction, existing_articles, model=compile_model, categories=categories)
                result = dedup_create_new(result, existing_articles)
                store.save_classify_cache(cache_key, result)
                classifications[rf.rel_path] = result
                log(f"  [classified] {rf.rel_path}")
                for create in result.get("create_new", []):
                    existing_articles.append(ArticleMeta(
                        title=create.get("title", ""), path=create.get("path", ""), summary="",
                    ))
            except Exception as e:
                errors.append({"file": rf.rel_path, "error": str(e)})
                log(f"  [classify-error] {rf.rel_path}: {e}")

        if items_to_classify and classify_cache_hits == len(items_to_classify):
            log(f"Phase 2a: All {classify_cache_hits} files hit classify cache, skipping LLM calls.")

        classify_d = tracker.delta(classify_snap)
        if items_to_classify:
            log(f"Phase 2a done: {len(classifications)} classified ({classify_cache_hits} cached), "
                f"{len(errors)} errors, ${classify_d['cost']:.4f}, {classify_d['elapsed']:.1f}s")

        # ── Phase 2b: Parallel write ──────────────────────────────
        write_snap = tracker.snapshot()
        if items_to_classify:
            log("Phase 2b: Writing articles...")

        article_ops: dict[str, list] = {}
        file_checksums: dict[str, str] = {}
        file_op_counts: dict[str, int] = {}
        file_total_ops: dict[str, int] = {}

        for rf, extraction in items_to_classify:
            if rf.rel_path not in classifications:
                continue
            classification = classifications[rf.rel_path]
            file_checksums[rf.rel_path] = rf.checksum
            previously_done = set(state.get(rf.rel_path, {}).get("completed_ops", []))
            ops = 0
            total_ops = 0

            for merge in classification.get("merge_into", []):
                total_ops += 1
                if not _under_wiki(store, merge["path"]):
                    log(f"  [skip] bad path (not under wiki/): {merge['path']} ← {rf.rel_path}")
                    continue
                if merge["path"] in previously_done:
                    continue
                article_ops.setdefault(merge["path"], []).append(
                    (rf.rel_path, rf.checksum, extraction, "merge", merge))
                ops += 1

            for create in classification.get("create_new", []):
                total_ops += 1
                if not _under_wiki(store, create["path"]):
                    log(f"  [skip] bad path (not under wiki/): {create['path']} ← {rf.rel_path}")
                    continue
                if create["path"] in previously_done:
                    continue
                article_ops.setdefault(create["path"], []).append(
                    (rf.rel_path, rf.checksum, extraction, "create", create))
                ops += 1

            file_op_counts[rf.rel_path] = ops
            file_total_ops[rf.rel_path] = total_ops
            if ops == 0:
                state[rf.rel_path] = {
                    "checksum": rf.checksum,
                    "compiled_at": datetime.now().isoformat(),
                    "prompt_version": used_prompt_version[rf.rel_path],
                    "write_prompt_version": write_version,
                }
                compiled += 1

        skipped_ops = sum(file_total_ops[r] - file_op_counts[r] for r in file_op_counts)
        if skipped_ops:
            log(f"  ({skipped_ops} ops skipped — already completed in prior runs)")

        _write_lock = threading.Lock()
        _file_done_ops: dict[str, int] = {rel: 0 for rel in file_op_counts}
        _file_done_articles: dict[str, set] = {rel: set() for rel in file_op_counts}

        def _process_article(art_path: str, ops: list):
            adopt_context(_parent_ctx, phase=f"write:{art_path}")
            creates = [(rel, cs, ext, det) for rel, cs, ext, action, det in ops if action == "create"]
            merges = [(rel, cs, ext, det) for rel, cs, ext, action, det in ops if action == "merge"]
            create_failed = False

            for rel, _cs, extraction, details in creates:
                try:
                    with _measure_op_cost() as op_cost:
                        full = store.base_dir / details["path"]
                        full.parent.mkdir(parents=True, exist_ok=True)
                        if full.exists():
                            old_content = full.read_text()
                            new_content = merge_into_article(
                                details["path"], old_content, extraction, rel, model=write_model)
                        else:
                            new_content = create_new_article(
                                details["type"], details["title"], extraction, rel, model=write_model)
                        store.write_article(details["path"], new_content)
                    log(f"  [create] {art_path} ← {rel} — ${op_cost.total_cost:.4f}")
                    with _write_lock:
                        _file_done_ops[rel] += 1
                        _file_done_articles[rel].add(art_path)
                except Exception as e:
                    create_failed = True
                    with _write_lock:
                        errors.append({"file": rel, "error": str(e), "article": art_path})
                    log(f"  [create-error] {art_path} ← {rel}: {e}")

            if not merges:
                return

            full = store.base_dir / art_path
            if not full.exists():
                if create_failed:
                    # The create meant to establish this article failed, so promoting
                    # a merge would title the article from the path stem while filling
                    # it with a different document's content -- a permanent mislabel on
                    # the catalog line that page selection reads. Report the merge
                    # sources instead, so the next compile retries them against a
                    # create that succeeds.
                    with _write_lock:
                        for rel, _cs, _ext, _det in merges:
                            errors.append({
                                "file": rel,
                                "error": f"merge skipped: create of {art_path} failed in this run",
                                "article": art_path,
                            })
                    log(f"  [merge-skipped] {art_path} ← {len(merges)} sources: create failed in this run")
                    return
                full.parent.mkdir(parents=True, exist_ok=True)
                planned = _planned_article_meta.get(art_path)
                if planned:
                    article_type = planned["type"]
                    title = planned["title"]
                else:
                    path_parts = art_path.split("/")
                    article_type = path_parts[1] if len(path_parts) > 2 else "concept"
                    title = Path(art_path).stem.replace("-", " ").title()
                items = [(rel, ext) for rel, _cs, ext, _det in merges]
                total_size = sum(_estimate_full_extraction_size(ext, rel) for rel, ext in items)
                budget = estimate_create_budget(article_type, title, items)
                needs_split = total_size > budget and len(items) > 1
                if needs_split:
                    try:
                        with _measure_op_cost() as op_cost:
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
                        sub_info = f", {len(articles)} sub-articles" if len(articles) > 1 else ""
                        log(f"  [merge→create-split] {art_path} ← {len(merges)} sources "
                            f"({n_batches} batches{sub_info}) — ${op_cost.total_cost:.4f}")
                        with _write_lock:
                            for rel, _cs, _ext, _det in merges:
                                _file_done_ops[rel] += 1
                                _file_done_articles[rel].add(art_path)
                    except Exception as e:
                        with _write_lock:
                            for rel, _cs, _ext, _det in merges:
                                errors.append({"file": rel, "error": str(e), "article": art_path})
                        log(f"  [merge→create-split-error] {art_path} ← {len(merges)} sources: {e}")
                else:
                    combined, merge_rels = _combine_extractions(items)
                    try:
                        with _measure_op_cost() as op_cost:
                            new_content = create_new_article(
                                article_type, title, combined, ", ".join(merge_rels), model=write_model)
                            store.write_article(art_path, new_content)
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
                        log(f"  [merge→create-error] {art_path} ← {len(merges)} sources: {e}")
                return

            if len(merges) == 1:
                rel, _cs, extraction, details = merges[0]
                try:
                    with _measure_op_cost() as op_cost:
                        old_content = store.read_article(art_path)
                        new_content = merge_into_article(
                            art_path, old_content, extraction, rel, model=write_model)
                        store.write_article(art_path, new_content)
                    log(f"  [merge] {art_path} ← {rel} — ${op_cost.total_cost:.4f}")
                    with _write_lock:
                        _file_done_ops[rel] += 1
                        _file_done_articles[rel].add(art_path)
                except Exception as e:
                    with _write_lock:
                        errors.append({"file": rel, "error": str(e), "article": art_path})
                    log(f"  [merge-error] {art_path} ← {rel}: {e}")
            else:
                items = [(rel, ext) for rel, _cs, ext, _det in merges]
                old_content = store.read_article(art_path)
                total_size = sum(_estimate_full_extraction_size(ext, rel) for rel, ext in items)
                budget = estimate_merge_budget(old_content)
                needs_split = total_size > budget and len(items) > 1
                if needs_split:
                    try:
                        with _measure_op_cost() as op_cost:
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
                        sub_info = f", {len(articles)} sub-articles" if len(articles) > 1 else ""
                        log(f"  [merge-batch-split] {art_path} ← {len(merges)} sources "
                            f"({n_batches} batches{sub_info}) — ${op_cost.total_cost:.4f}")
                        with _write_lock:
                            for rel, _cs, _ext, _det in merges:
                                _file_done_ops[rel] += 1
                                _file_done_articles[rel].add(art_path)
                    except Exception as e:
                        with _write_lock:
                            for rel, _cs, _ext, _det in merges:
                                errors.append({"file": rel, "error": str(e), "article": art_path})
                        log(f"  [merge-batch-split-error] {art_path} ← {len(merges)} sources: {e}")
                else:
                    combined, merge_rels = _combine_extractions(items)
                    try:
                        with _measure_op_cost() as op_cost:
                            new_content = merge_into_article(
                                art_path, old_content, combined, ", ".join(merge_rels), model=write_model)
                            store.write_article(art_path, new_content)
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
                        log(f"  [merge-batch-error] {art_path} ← {len(merges)} sources: {e}")

        try:
            if article_ops:
                n_groups = len(article_ops)
                write_workers = min(n_groups, workers)
                log(f"  {n_groups} article groups, {write_workers} workers")
                with ThreadPoolExecutor(max_workers=write_workers) as pool:
                    futures = {pool.submit(_process_article, path, ops): path
                               for path, ops in article_ops.items()}
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            log(f"  [group-error] {futures[future]}: {e}")
        finally:
            for rel, pending in file_op_counts.items():
                if pending == 0:
                    continue
                done_now = _file_done_articles.get(rel, set())
                prev_done = set(state.get(rel, {}).get("completed_ops", []))
                all_done = prev_done | done_now
                if _file_done_ops.get(rel, 0) >= pending:
                    state[rel] = {"checksum": file_checksums[rel],
                                  "compiled_at": datetime.now().isoformat(),
                                  "prompt_version": used_prompt_version[rel],
                                  "write_prompt_version": write_version}
                    compiled += 1
                elif done_now:
                    state[rel] = {"checksum": file_checksums[rel],
                                  "completed_ops": sorted(all_done),
                                  "prompt_version": used_prompt_version[rel],
                                  "write_prompt_version": write_version}
            store.save_compile_state(state)

        write_d = tracker.delta(write_snap)
        if items_to_classify:
            log(f"Phase 2b done: ${write_d['cost']:.4f}, {write_d['elapsed']:.1f}s")

        # A revised document's articles were merged into, not rewritten: both
        # merge paths are additive -- merge-diff.md offers only append_to_section
        # and new_section, and merge-rewrite.md says nothing about supersession --
        # so what the previous version contributed is still in there. Naming the
        # articles is the whole point: it says which ones a human should re-read.
        revised_articles = {rel: sorted(_file_done_articles[rel])
                            for rel in revised
                            if _file_done_articles.get(rel)}
        if revised_articles:
            log(f"Revised documents: {len(revised_articles)} re-extracted document(s) "
                "were merged into existing articles, which still carry the previous "
                "version's content (merge cannot retract):")
            for rel, arts in sorted(revised_articles.items()):
                log(f"  [revised] {rel} → {', '.join(arts)}")

        log(f"Compile done: {compiled} compiled, {extracted} extracted, "
            f"{len(errors)} errors, ${tracker.total_cost:.4f} total")

    # Phase 3: Index
    index_t0 = time.monotonic()
    update_markdown_index(store, min_articles=topic_index_min_articles,
                          summary_max_chars=summary_max_chars)
    # Built here so it cannot drift from raw/, and so a later derive over
    # documents reads it instead of recomputing every summary. Rebuilt after an
    # extract-only run too: the catalog reads its summaries out of extraction/.
    update_document_index(store, summary_max_chars=summary_max_chars)
    if to_write:
        update_timeline(store, [rf.rel_path for rf in to_write])
    update_people_stubs(store, people_cfg)
    index_elapsed = round(time.monotonic() - index_t0, 2)

    total_elapsed = round(time.monotonic() - compile_t0, 2)

    tracker.print_summary()
    print(f"[Timing] total={total_elapsed}s | extract={extract_d['elapsed']}s | "
          f"classify={classify_d['elapsed']}s | write={write_d['elapsed']}s | "
          f"index={index_elapsed}s", file=sys.stderr)

    return {
        "compiled": compiled,
        "extracted": extracted,
        "extract_only": extract_only,
        # Documents whose extraction overwrote an existing one, mapped to the
        # articles they were merged into (C11). Empty on a first compile.
        "revised": revised_articles,
        # How far the wiki is behind each gate's prompts (G5). Counts only, since
        # `kb-ai check` names the documents for free. The first_run flags are per
        # gate: each says "no entry records a version for THIS gate", which is what
        # makes a large count on the run after that version landed expected rather
        # than a bug -- and keeps one gate's landing from excusing the other's
        # genuine lag.
        "wiki_lag": {"behind_extract_prompt": len(lag.behind_extract),
                     "behind_write_prompt": len(lag.behind_write),
                     "extract_first_run": lag.extract_first_run,
                     "write_first_run": lag.write_first_run},
        "errors": errors,
        "total_raw": len(raw_files),
        "cost": tracker.summary(),
        "timing": {
            "total_seconds": total_elapsed,
            "phases": {
                "extract": {"seconds": extract_d["elapsed"], "cost": round(extract_d["cost"], 4)},
                "classify": {"seconds": classify_d["elapsed"], "cost": round(classify_d["cost"], 4)},
                "write": {"seconds": write_d["elapsed"], "cost": round(write_d["cost"], 4)},
                "index": {"seconds": index_elapsed},
            },
        },
    }


def run_compile():
    from kb_ai._protocol import read_input, respond_ok

    input_data = read_input()
    result = compile_kb(
        input_data["data_dir"],
        extract_model=input_data.get("extract_model", "claude-sonnet-4-6"),
        compile_model=input_data.get("compile_model", "claude-sonnet-4-6"),
        write_model=input_data.get("write_model", "claude-sonnet-4-6"),
        categories=input_data.get("categories"),
        topic_index_min_articles=int(input_data.get("topic_index_min_articles") or 3),
        summary_max_chars=int(input_data.get("summary_max_chars") or SUMMARY_MAX_CHARS),
        people_cfg=input_data.get("people") or [],
        workers=input_data.get("workers", 0) or 0,
        extract_only=bool(input_data.get("extract_only")),
        extract_strategy=(input_data.get("extract_strategy")
                          or os.environ.get("LLM_EXTRACT_STRATEGY")
                          or STRATEGY_CHUNKED),
        # Same fallback chain as the daemon's extract handler and the distill CLI:
        # a summarize run reaching the API with an empty model name is refused by
        # compile_kb, and falling back here is what keeps that from happening
        # merely because the request omitted a field the environment already has.
        summarize_model=(input_data.get("summarize_model")
                         or os.environ.get("LLM_SUMMARIZE_MODEL")
                         or os.environ.get("LLM_MODEL", "")),
    )
    respond_ok(data=result)
