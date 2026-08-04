import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from kb_ai.core.classify import classify_article, classify_cache_key, dedup_create_new, hash_existing_articles
from kb_ai.core.extract import ExtractionResult, extract_knowledge_chunked, extraction_to_dict, parse_extraction_result, _combine_extractions
from kb_ai.storage.index import SUMMARY_MAX_CHARS, update_markdown_index, update_timeline
from kb_ai.core.people import update_people_stubs
from kb_ai.llm import CostTracker, tracker, get_request_tracker, set_request_tracker
from kb_ai.core.merge import create_new_article, merge_into_article
from kb_ai.storage.store import ArticleMeta, KBStore

_DEFAULT_WORKERS = 16


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
) -> dict:
    compile_t0 = time.monotonic()

    people_cfg = people_cfg or []

    store = KBStore(data_dir)
    state = store.load_compile_state()
    # TODO(2026-06-03): list_raw_files() preloads all raw content into memory.
    # The estimate path was migrated to iter_raw_file_meta() in
    # docs/kaas/plans/2026-06-03-cost-estimate-memory-optimization.md.
    # Compile path is harder to migrate (needs content for chunking/extraction)
    # but cached files could skip the read; revisit when memory pressure shows up.
    raw_files = store.list_raw_files()

    to_compile = []
    for rf in raw_files:
        file_state = state.get(rf.rel_path, {})
        if file_state.get("checksum") != rf.checksum:
            to_compile.append(rf)
        elif file_state.get("completed_ops") and not file_state.get("compiled_at"):
            to_compile.append(rf)

    if not to_compile:
        return {"compiled": 0, "message": "nothing to compile"}

    compiled = 0
    errors: list[dict] = []
    total = len(to_compile)
    cfg_workers = workers or int(os.environ.get("KB_WORKERS", 0))
    workers = min(total, cfg_workers if cfg_workers > 0 else _DEFAULT_WORKERS)

    log_path = Path(data_dir).expanduser() / ".compile.log"
    _log_lock = threading.Lock()

    with open(log_path, "w") as log_file:
        def log(msg: str):
            with _log_lock:
                print(msg, file=log_file, flush=True)
                print(msg, file=sys.stderr, flush=True)

        log(f"Starting compile: {total} files to process (workers={workers})")

        # ── Phase 1: Parallel extraction ──────────────────────────
        extract_snap = tracker.snapshot()
        extractions: dict[str, ExtractionResult] = {}
        cache_hits = 0

        need_extract = []
        for rf in to_compile:
            cached = store.load_extract_cache(rf.checksum)
            if cached is not None:
                extractions[rf.rel_path] = parse_extraction_result(cached)
                cache_hits += 1
                log(f"  [cached] {rf.rel_path}")
            else:
                need_extract.append(rf)

        _compile_req_tracker = get_request_tracker()

        def _extract_one(rf):
            set_request_tracker(_compile_req_tracker)
            result = extract_knowledge_chunked(rf.content, model=extract_model)
            store.save_extract_cache(rf.checksum, extraction_to_dict(result))
            return rf.rel_path, result

        if need_extract:
            log(f"Phase 1: Extracting {len(need_extract)} files in parallel ({cache_hits} cached)...")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_extract_one, rf): rf for rf in need_extract}
                for future in as_completed(futures):
                    rf = futures[future]
                    try:
                        _, extraction = future.result()
                        extractions[rf.rel_path] = extraction
                        log(f"  [extracted] {rf.rel_path}")
                    except Exception as e:
                        errors.append({"file": rf.rel_path, "error": str(e)})
                        log(f"  [extract-error] {rf.rel_path}: {e}")
        else:
            log(f"Phase 1: All {cache_hits} files hit extraction cache, skipping LLM calls.")

        extract_d = tracker.delta(extract_snap)
        log(f"Phase 1 done: {len(extractions)} extracted ({cache_hits} cached), "
            f"{len(errors)} errors, ${extract_d['cost']:.4f}, {extract_d['elapsed']:.1f}s")

        if not extractions:
            log("All extractions failed, aborting compile.")
            return {"compiled": 0, "errors": errors, "total_raw": len(raw_files),
                    "cost": tracker.summary()}

        # ── Phase 2a: Sequential classify ─────────────────────────
        existing_articles = store.existing_articles()
        classify_snap = tracker.snapshot()

        items_to_classify = []
        for rf in to_compile:
            if rf.rel_path not in extractions:
                continue
            extraction = extractions[rf.rel_path]
            extraction.source_path = rf.rel_path
            items_to_classify.append((rf, extraction))

        classifications: dict[str, dict] = {}
        classify_cache_hits = 0
        art_hash = hash_existing_articles(existing_articles)
        cat_hash = hashlib.sha256(json.dumps(categories or [], sort_keys=True).encode()).hexdigest()[:8]

        log(f"Phase 2a: Classifying {len(items_to_classify)} files sequentially...")
        for rf, extraction in items_to_classify:
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

        if classify_cache_hits == len(items_to_classify):
            log(f"Phase 2a: All {classify_cache_hits} files hit classify cache, skipping LLM calls.")

        classify_d = tracker.delta(classify_snap)
        log(f"Phase 2a done: {len(classifications)} classified ({classify_cache_hits} cached), "
            f"{len(errors)} errors, ${classify_d['cost']:.4f}, {classify_d['elapsed']:.1f}s")

        # ── Phase 2b: Parallel write ──────────────────────────────
        write_snap = tracker.snapshot()
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
                state[rf.rel_path] = {"checksum": rf.checksum, "compiled_at": datetime.now().isoformat()}
                compiled += 1

        skipped_ops = sum(file_total_ops[r] - file_op_counts[r] for r in file_op_counts)
        if skipped_ops:
            log(f"  ({skipped_ops} ops skipped — already completed in prior runs)")

        _write_lock = threading.Lock()
        _file_done_ops: dict[str, int] = {rel: 0 for rel in file_op_counts}
        _file_done_articles: dict[str, set] = {rel: set() for rel in file_op_counts}

        _write_req_tracker = get_request_tracker()

        def _process_article(art_path: str, ops: list):
            set_request_tracker(_write_req_tracker)
            creates = [(rel, cs, ext, det) for rel, cs, ext, action, det in ops if action == "create"]
            merges = [(rel, cs, ext, det) for rel, cs, ext, action, det in ops if action == "merge"]

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
                    with _write_lock:
                        errors.append({"file": rel, "error": str(e), "article": art_path})
                    log(f"  [create-error] {art_path} ← {rel}: {e}")

            if not merges:
                return

            full = store.base_dir / art_path
            if not full.exists():
                full.parent.mkdir(parents=True, exist_ok=True)
                path_parts = art_path.split("/")
                article_type = path_parts[1] if len(path_parts) > 2 else "concept"
                title = Path(art_path).stem.replace("-", " ").title()
                combined, merge_rels = _combine_extractions(
                    [(rel, ext) for rel, _cs, ext, _det in merges])
                try:
                    with _measure_op_cost() as op_cost:
                        new_content = create_new_article(
                            article_type, title, combined, ", ".join(merge_rels), model=write_model)
                        store.write_article(art_path, new_content)
                    log(f"  [merge→create] {art_path} ← {len(merges)} sources "
                        f"— ${op_cost.total_cost:.4f}")
                    with _write_lock:
                        for rel in merge_rels:
                            _file_done_ops[rel] += 1
                            _file_done_articles[rel].add(art_path)
                except Exception as e:
                    with _write_lock:
                        for rel in merge_rels:
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
                combined, merge_rels = _combine_extractions(
                    [(rel, ext) for rel, _cs, ext, _det in merges])
                try:
                    with _measure_op_cost() as op_cost:
                        old_content = store.read_article(art_path)
                        new_content = merge_into_article(
                            art_path, old_content, combined, ", ".join(merge_rels), model=write_model)
                        store.write_article(art_path, new_content)
                    log(f"  [merge-batch] {art_path} ← {len(merges)} sources "
                        f"— ${op_cost.total_cost:.4f}")
                    with _write_lock:
                        for rel in merge_rels:
                            _file_done_ops[rel] += 1
                            _file_done_articles[rel].add(art_path)
                except Exception as e:
                    with _write_lock:
                        for rel in merge_rels:
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
                                  "compiled_at": datetime.now().isoformat()}
                    compiled += 1
                elif done_now:
                    state[rel] = {"checksum": file_checksums[rel],
                                  "completed_ops": sorted(all_done)}
            store.save_compile_state(state)

        write_d = tracker.delta(write_snap)
        log(f"Phase 2b done: ${write_d['cost']:.4f}, {write_d['elapsed']:.1f}s")
        log(f"Compile done: {compiled} compiled, {len(errors)} errors, ${tracker.total_cost:.4f} total")

    # Phase 3: Index
    index_t0 = time.monotonic()
    update_markdown_index(store, min_articles=topic_index_min_articles,
                          summary_max_chars=summary_max_chars)
    update_timeline(store, [rf.rel_path for rf in to_compile])
    update_people_stubs(store, people_cfg)
    index_elapsed = round(time.monotonic() - index_t0, 2)

    total_elapsed = round(time.monotonic() - compile_t0, 2)

    tracker.print_summary()
    print(f"[Timing] total={total_elapsed}s | extract={extract_d['elapsed']}s | "
          f"classify={classify_d['elapsed']}s | write={write_d['elapsed']}s | "
          f"index={index_elapsed}s", file=sys.stderr)

    return {
        "compiled": compiled,
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
    )
    respond_ok(data=result)
