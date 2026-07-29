from __future__ import annotations

import functools
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kb_ai.llm import (
    MAX_PROMPT_CHARS,
    completion,
    completion_json,
    get_call_timeout,
    get_phase_context,
    get_request_tracker,
    set_call_timeout,
    set_phase_context,
    set_request_tracker,
)

_DEFAULT_WORKERS = 16

# Per-call timeout for extract pipeline. Tighter than the default 900s because
# extract calls have predictable size (≤16K max_tokens) and a single hung call
# blocks the whole job (see diagnose log 2026-06-01, T4 d35bec86 stall 914s).
_EXTRACT_CALL_TIMEOUT_S = 180.0


def _with_extract_timeout(fn):
    """Apply _EXTRACT_CALL_TIMEOUT_S to all LLM calls within fn, restoring on exit.

    Restoring to prev (not None) keeps nested invocations safe — if a future
    caller wraps extract in its own timeout context, we don't clobber it.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        prev = get_call_timeout()
        set_call_timeout(_EXTRACT_CALL_TIMEOUT_S)
        try:
            return fn(*args, **kwargs)
        finally:
            set_call_timeout(prev)
    return wrapper


@dataclass
class ExtractionResult:
    summary: str = ""
    concepts: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    action_items: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    source_path: str = ""


def parse_extraction_result(raw: dict) -> ExtractionResult:
    return ExtractionResult(
        summary=raw.get("summary") or "",
        concepts=raw.get("concepts") or [],
        entities=raw.get("entities") or [],
        decisions=raw.get("decisions") or [],
        action_items=raw.get("action_items") or [],
        claims=raw.get("claims") or [],
        topics=raw.get("topics") or [],
        connections=raw.get("connections") or [],
    )


def extraction_to_dict(e: ExtractionResult) -> dict:
    return {
        "summary": e.summary, "concepts": e.concepts, "entities": e.entities,
        "decisions": e.decisions, "action_items": e.action_items,
        "claims": e.claims, "topics": e.topics, "connections": e.connections,
    }


def load_prompt(name: str) -> str:
    """Load a prompt template by name from the file-based PromptRegistry.

    Prompts live as .yaml/.md files under prompts/defaults/ (override the
    directory with the KAAS_PROMPTS_DIR env var).
    """
    from kb_ai.prompts import default_registry
    return default_registry().get(name).content


_FIELD_JSON_SCHEMAS: dict[str, str] = {
    "summary": '"summary": "1-2 sentence summary of the entire document"',
    "concepts": '"concepts": [{"title": "short title", "summary": "one sentence"}]',
    "entities": '"entities": [{"name": "entity name", "type": "person|tool|project|team|system", "context": "why notable here"}]',
    "decisions": '"decisions": [{"title": "short title", "what": "what was decided", "why": "reasoning", "who": ["people involved"]}]',
    "action_items": '"action_items": [{"task": "description", "owner": "person name if known"}]',
    "claims": '"claims": [{"claim": "the assertion", "source": "who/what said this", "surprising": false}]',
    "topics": '"topics": ["topic-tag-1", "topic-tag-2"]',
    "connections": '"connections": ["suggested-wiki-article-title-1", "suggested-wiki-article-title-2"]',
}

TYPE_SPLIT_GROUPS_K2: dict[str, tuple[str, ...]] = {
    "A": ("concepts", "entities", "topics", "summary"),
    "B": ("claims", "decisions", "action_items", "connections"),
}

TYPE_SPLIT_GROUPS_K3: dict[str, tuple[str, ...]] = {
    "A": ("concepts", "entities"),
    "B": ("claims", "summary", "topics"),
    "C": ("decisions", "action_items", "connections"),
}


def _render_type_split_prompt(group: str, k: int) -> str:
    """Render extract-types.md with field subset for a given (k, group) combo.

    Loads the extract-types.md template, then replaces {FIELDS_LIST} with the
    comma-separated assigned field names and {TYPES_JSON_SCHEMA} with a JSON
    object containing only the assigned field schema lines.
    """
    if k == 2:
        groups = TYPE_SPLIT_GROUPS_K2
    elif k == 3:
        groups = TYPE_SPLIT_GROUPS_K3
    else:
        raise ValueError(f"unsupported K for type-split: {k} (expected 2 or 3)")
    if group not in groups:
        raise ValueError(
            f"unknown group {group!r} for K={k} (expected one of {sorted(groups)})"
        )

    fields = groups[group]
    fields_list = ", ".join(fields)
    schema_lines = [_FIELD_JSON_SCHEMAS[f] for f in fields]
    schema_json = "{\n  " + ",\n  ".join(schema_lines) + "\n}"

    template = load_prompt("extract-types")
    return template.replace("{FIELDS_LIST}", fields_list).replace(
        "{TYPES_JSON_SCHEMA}", schema_json
    )


def extract_knowledge(
    content: str,
    model: str = "claude-sonnet-4-6",
    prompt_name: str = "extract",
    max_tokens: int = 16384,
) -> ExtractionResult:
    instructions = load_prompt(prompt_name)
    raw = completion_json(
        model=model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"<document>\n{content}\n</document>"},
        ],
        max_tokens=max_tokens,
    )
    return parse_extraction_result(raw)


_SUPER_SUMMARY_FALLBACK_LIMIT = 2500


def _bounded_join(parts: list[str], sep: str, limit: int) -> str:
    """Join parts with sep; if joined exceeds limit, truncate keeping the prefix.

    Used to enforce hard caps:
    - Per-group fallback: keep ~2500 chars of original summaries when L2 merge fails
      so each super-summary slot stays bounded.
    - Phase 2 input guard: keep joined super-summaries under MAX_PROMPT_CHARS - 8K
      to avoid prompt_too_large hard fail in pathological L2-all-fail scenarios.

    Truncation drops the document tail (lossy on coverage) but never raises.
    Negative limit is clamped to 0 (empty result) to guard against degenerate
    callers that subtract a margin from a small MAX_PROMPT_CHARS.
    """
    joined = sep.join(parts)
    if len(joined) <= limit:
        return joined
    return joined[:max(0, limit)]


def _merge_one_group(
    summaries: list[str],
    model: str = "claude-haiku-4-5",
) -> str:
    """Merge several adjacent chunk summaries into one super-summary via Haiku.

    Uses prompts/merge-summaries.md. Output is plain-text super-summary
    (same shape as a Phase 1 summarize_chunk output) targeting 1500-2500 chars.
    """
    instructions = load_prompt("merge-summaries")
    user_content = "\n---\n".join(summaries)
    return completion(
        model=model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2048,
    )


def merge_summaries_l2(
    summaries: list[str],
    fanout: int = 5,
    model: str = "claude-haiku-4-5",
) -> list[str]:
    """Hierarchically merge `summaries` in groups of `fanout` (parallel Haiku).

    No-op when len(summaries) <= fanout. Otherwise partition into ceil(N/fanout)
    contiguous groups (last group may be smaller), merge each group via Haiku
    in parallel, and return the list of super-summaries.

    Per-group failure is contained: the failing group falls back to a bounded
    join of the original summaries (truncated to _SUPER_SUMMARY_FALLBACK_LIMIT)
    so each output slot stays sized like a real super-summary. Whole-list size
    bounding for the Phase 2 input is the caller's responsibility (see
    _bounded_join + Phase 2 dispatch in s27-feat-004).

    Per ADR-0005: fanout=5 keeps each Haiku input around 7500 chars (well within
    Haiku's effective attention window for cross-section dedup), produces a 3x
    compression ratio, and bounds the worst-case super count at ceil(1M/5/2500).
    """
    if not summaries:
        return []
    if len(summaries) <= fanout:
        return list(summaries)

    groups: list[list[str]] = [
        summaries[i:i + fanout] for i in range(0, len(summaries), fanout)
    ]
    workers = min(
        len(groups),
        int(os.environ.get("KB_WORKERS", _DEFAULT_WORKERS)),
    )
    phase = get_phase_context()
    timeout = get_call_timeout()
    req_tracker = get_request_tracker()

    def _merge_in_worker(group: list[str]) -> str:
        set_phase_context(phase)
        set_call_timeout(timeout)
        set_request_tracker(req_tracker)
        return _merge_one_group(group, model=model)

    results: list[str | None] = [None] * len(groups)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_merge_in_worker, g): idx for idx, g in enumerate(groups)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                # Per-group fallback: keep the slot but bound its size to the
                # super-summary budget so callers can rely on stable per-slot length.
                fallback = _bounded_join(
                    groups[idx], "\n", _SUPER_SUMMARY_FALLBACK_LIMIT
                )
                print(
                    f"[warn] merge_summaries_l2: group {idx} ({len(groups[idx])} summaries) "
                    f"failed, falling back to bounded join ({len(fallback)} chars): {e}",
                    file=sys.stderr,
                    flush=True,
                )
                results[idx] = fallback

    # All slots are non-None at this point (fallback fills any failure).
    return [r for r in results if r is not None]


def extract_knowledge_type_split(
    content: str,
    k: int,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 16384,
) -> ExtractionResult:
    """Phase 2 type-split: K parallel Sonnet calls each emit only their assigned fields.

    All K calls receive the same `content` (joined summaries or super-summaries).
    Each call uses extract-types.md rendered with its (k, group) field subset.
    Results are merged by field ownership: each ExtractionResult field is filled
    by exactly one group's response.

    Per ADR-0006: input duplicated K times trades +10% (K=2) / +21% (K=3) cost
    for K-way output parallelism. Prompt cache deliberately not used — parallel
    K calls all cache-miss + write costs more than no-cache.

    Failure handling: any K call raising propagates immediately; caller is
    responsible for retry (see _phase2_with_retry in s27-feat-004).
    """
    if k == 2:
        groups = TYPE_SPLIT_GROUPS_K2
    elif k == 3:
        groups = TYPE_SPLIT_GROUPS_K3
    else:
        raise ValueError(f"unsupported K for type-split: {k} (expected 2 or 3)")

    phase = get_phase_context()
    timeout = get_call_timeout()
    req_tracker = get_request_tracker()

    def _extract_one_group(group: str) -> dict:
        set_phase_context(phase)
        set_call_timeout(timeout)
        set_request_tracker(req_tracker)
        prompt = _render_type_split_prompt(group, k)
        return completion_json(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"<document>\n{content}\n</document>"},
            ],
            max_tokens=max_tokens,
        )

    raw_by_group: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=k) as pool:
        futures = {pool.submit(_extract_one_group, g): g for g in groups}
        for future in as_completed(futures):
            g = futures[future]
            raw_by_group[g] = future.result()

    merged_dict: dict = {}
    for group, fields in groups.items():
        parsed = parse_extraction_result(raw_by_group[group])
        for fname in fields:
            merged_dict[fname] = getattr(parsed, fname)

    return parse_extraction_result(merged_dict)


def chunk_content(content: str, max_tokens: int = 4000) -> list[str]:
    max_chars = max_tokens * 4
    if len(content) <= max_chars:
        return [content]
    chunks = []
    lines = content.split("\n")
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if len(line) > max_chars:
            for i in range(0, len(line), max_chars):
                chunks.append(line[i:i + max_chars])
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_SPEAKER_RE = re.compile(r"^\*\*@[\w.]+\*\*\s+\d{2}:\d{2}:\d{2}")
_TIMESTAMP_RE = re.compile(r"\d{2}:\d{2}:\d{2}")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        # Don't swallow silently: a broken frontmatter (e.g. unescaped backslash
        # in a double-quoted title) otherwise misattributes the file as
        # no-date / no-source in cost-review and other downstream consumers.
        print(
            f"[warn] _parse_frontmatter: invalid YAML, treating as empty meta: {e}",
            file=sys.stderr,
            flush=True,
        )
        meta = {}
    return meta, content[m.end():]


def _is_transcript(meta: dict) -> bool:
    return (
        meta.get("source") == "meetings"
        and meta.get("artifact_kind") == "vc_note_transcript"
    )


_HEADER_TITLE_RE = re.compile(r"^>\s*Title:\s*(.+)", re.MULTILINE)
_HEADER_TIME_RE = re.compile(r"^>\s*Time:\s*(.+)", re.MULTILINE)


def _parse_transcript_header(body: str) -> tuple[dict, str]:
    """Extract the structured header (# heading + > blockquote) from transcript body.

    Returns (header_info, remaining_body_after_header).
    """
    info: dict = {}
    lines = body.split("\n")
    header_end = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Header region: # heading, > blockquote lines, or blank lines
        if stripped.startswith("#") or stripped.startswith(">") or stripped == "":
            header_end = i + 1
        else:
            break

    header_text = "\n".join(lines[:header_end])

    m = _HEADER_TITLE_RE.search(header_text)
    if m:
        info["title"] = m.group(1).strip()

    m = _HEADER_TIME_RE.search(header_text)
    if m:
        info["time"] = m.group(1).strip()

    remaining = "\n".join(lines[header_end:])
    return info, remaining


def _build_transcript_context(meta: dict, header: dict, speakers: list[str], time_start: str, time_end: str) -> str:
    lines = ["[会议逐字稿]"]
    header_title = header.get("title", "")
    meta_title = meta.get("title", "")
    if header_title:
        lines.append(f"主题: {header_title}")
    if meta_title and meta_title != header_title:
        lines.append(f"会议: {meta_title}")
    if meta.get("date"):
        lines.append(f"日期: {meta['date']}")
    if header.get("time"):
        lines.append(f"会议时间: {header['time']}")
    if time_start and time_end:
        lines.append(f"当前片段: {time_start} - {time_end}")
    if speakers:
        lines.append(f"参会者: {', '.join(speakers)}")
    lines.append("---\n")
    return "\n".join(lines)


def chunk_transcript(body: str, meta: dict, max_tokens: int = 4000) -> list[str]:
    """Split meeting transcript by speaker turns, injecting context into each chunk."""
    max_chars = max_tokens * 4

    header, content = _parse_transcript_header(body)

    lines = content.split("\n")

    # Split into speaker turns
    turns: list[str] = []
    current_turn: list[str] = []
    for line in lines:
        if _SPEAKER_RE.match(line) and current_turn:
            turns.append("\n".join(current_turn))
            current_turn = []
        current_turn.append(line)
    if current_turn:
        turns.append("\n".join(current_turn))

    if not turns:
        return [body]

    # Collect all speakers for context
    all_speakers: list[str] = []
    seen: set[str] = set()
    for turn in turns:
        m = re.match(r"^\*\*@([\w.]+)\*\*", turn)
        if m and m.group(1) not in seen:
            all_speakers.append(m.group(1))
            seen.add(m.group(1))

    # Aggregate turns into chunks
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for turn in turns:
        turn_len = len(turn)
        # Single turn exceeds max: flush buffer, then fallback to line-based split
        if turn_len > max_chars:
            if buf:
                chunks.append("\n\n".join(buf))
                buf, buf_len = [], 0
            chunks.extend(chunk_content(turn, max_tokens=max_tokens))
            continue
        if buf_len + turn_len > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, buf_len = [], 0
        buf.append(turn)
        buf_len += turn_len + 2  # account for \n\n join

    if buf:
        chunks.append("\n\n".join(buf))

    if len(chunks) <= 1:
        return [body]

    # Inject context prefix into each chunk
    result: list[str] = []
    for chunk in chunks:
        timestamps = _TIMESTAMP_RE.findall(chunk)
        time_start = timestamps[0] if timestamps else ""
        time_end = timestamps[-1] if timestamps else ""
        ctx = _build_transcript_context(meta, header, all_speakers, time_start, time_end)
        result.append(ctx + chunk)

    return result


def _build_summarize_context(frontmatter: dict) -> str:
    """Build a context prefix from frontmatter fields (source, date, title)."""
    lines: list[str] = []
    if frontmatter.get("title"):
        lines.append(f"Title: {frontmatter['title']}")
    if frontmatter.get("source"):
        lines.append(f"Source: {frontmatter['source']}")
    if frontmatter.get("date"):
        lines.append(f"Date: {frontmatter['date']}")
    if lines:
        lines.append("---")
    return "\n".join(lines)


def summarize_chunk(chunk_text: str, frontmatter: dict, model: str) -> str:
    """Summarize a single chunk of text using the summarize prompt.

    Args:
        chunk_text: The text content to summarize.
        frontmatter: Metadata dict (source, date, title) injected as context.
        model: LLM model identifier to use for the completion.

    Returns:
        Plain text summary (200-500 words, guided by prompt).
    """
    instructions = load_prompt("summarize")
    context_prefix = _build_summarize_context(frontmatter)
    if context_prefix:
        user_content = f"{context_prefix}\n{chunk_text}"
    else:
        user_content = chunk_text

    return completion(
        model=model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        max_tokens=2048,
    )


@_with_extract_timeout
def extract_knowledge_summarized(
    chunks: list[str],
    frontmatter: dict,
    summarize_model: str,
    extract_model: str,
    prompt_name: str = "extract",
    max_tokens: int = 16384,
) -> ExtractionResult:
    """Two-phase extraction: summarize each chunk, then extract from joined summaries.

    Phase 1: Parallel summarize all chunks using summarize_chunk().
    Phase 2: Join summaries and run single-shot extract_knowledge().

    Args:
        chunks: List of text chunks to process.
        frontmatter: Metadata dict passed to summarize_chunk for context.
        summarize_model: Model for Phase 1 (summarization).
        extract_model: Model for Phase 2 (structured extraction).
        prompt_name: Name of the prompt template for extraction (default "extract").
        max_tokens: Max tokens for the extraction LLM call (default 16384).

    Returns:
        ExtractionResult from the joined summaries.
    """
    print(f"[extract] extract_knowledge_summarized: summarize_model={summarize_model} extract_model={extract_model} chunks={len(chunks)}",
          file=sys.stderr, flush=True)
    if not chunks:
        return ExtractionResult()

    # Phase 1: parallel summarization
    workers = min(len(chunks), int(os.environ.get("KB_WORKERS", _DEFAULT_WORKERS)))
    phase = get_phase_context()
    timeout = get_call_timeout()
    req_tracker = get_request_tracker()

    def _summarize_in_worker(chunk: str) -> str:
        set_phase_context(phase)
        set_call_timeout(timeout)
        set_request_tracker(req_tracker)
        return summarize_chunk(chunk, frontmatter, summarize_model)

    summaries: list[str | None] = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_summarize_in_worker, chunk): idx
                   for idx, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                summaries[idx] = future.result()
            except Exception as e:
                print(
                    f"[warn] extract_knowledge_summarized: chunk {idx} summarization failed, skipping: {e}",
                    file=sys.stderr,
                    flush=True,
                )

    # Collect successful summaries in order
    successful = [s for s in summaries if s is not None]
    if not successful:
        return ExtractionResult()

    # Phase 2: K-adaptive dispatch with optional L2 hierarchical merge.
    #
    #   chunks ≤ 3        → K=1 single Sonnet (byte-equivalent to pre-s27 behavior)
    #   chunks 4-7        → K=2 type-split (parallel Sonnet, A/B field groups)
    #   chunks 8-19       → K=3 type-split (parallel Sonnet, A/B/C field groups)
    #   chunks ≥ 20 OR    → L2 fanout=5 Haiku merge → K=3 type-split
    #   joined > 60K
    #
    # _bounded_join enforces the Phase 2 input cap (MAX_PROMPT_CHARS - 8K, ≈72K).
    # For all K=1 paths with realistic summaries this is a no-op join, preserving
    # byte-equivalence with the prior implementation.
    n = len(successful)
    naive_joined = "\n\n".join(successful)
    phase2_limit = max(0, MAX_PROMPT_CHARS - 8000)

    if n >= 20 or len(naive_joined) > 60_000:
        super_summaries = merge_summaries_l2(successful, fanout=5, model=summarize_model)
        joined = _bounded_join(super_summaries, "\n\n", phase2_limit)
        return _phase2_with_retry(joined, k=3, model=extract_model, max_tokens=max_tokens)

    joined = naive_joined if len(naive_joined) <= phase2_limit else naive_joined[:phase2_limit]

    if n <= 3:
        return extract_knowledge(joined, model=extract_model, prompt_name=prompt_name, max_tokens=max_tokens)
    if n <= 7:
        return _phase2_with_retry(joined, k=2, model=extract_model, max_tokens=max_tokens)
    return _phase2_with_retry(joined, k=3, model=extract_model, max_tokens=max_tokens)


def _phase2_with_retry(
    content: str,
    k: int,
    model: str,
    max_tokens: int,
) -> ExtractionResult:
    """Run K-call type-split, retrying the entire Phase 2 once on any failure.

    Any of the K parallel calls failing causes the entire K-call set to be
    retried (full re-dispatch). Partial-K-result degradation is intentionally
    NOT used: leaving empty fields in ExtractionResult would silently pollute
    downstream wiki output. Two consecutive failures propagate to the caller
    (Go bridge surfaces the error in the extract job protocol).
    """
    try:
        return extract_knowledge_type_split(content, k=k, model=model, max_tokens=max_tokens)
    except Exception as e:
        print(
            f"[warn] _phase2_with_retry: K={k} type-split failed, retrying once: {e}",
            file=sys.stderr,
            flush=True,
        )
        return extract_knowledge_type_split(content, k=k, model=model, max_tokens=max_tokens)


@_with_extract_timeout
def extract_knowledge_chunked(
    content: str,
    model: str = "claude-sonnet-4-6",
    prompt_name: str = "extract",
    max_tokens: int = 16384,
) -> ExtractionResult:
    meta, body = _parse_frontmatter(content)

    if _is_transcript(meta):
        chunks = chunk_transcript(body, meta)
    else:
        chunks = chunk_content(content)

    print(f"[extract] extract_knowledge_chunked: model={model} chunks={len(chunks)}",
          file=sys.stderr, flush=True)

    if len(chunks) == 1:
        return extract_knowledge(chunks[0], model=model, prompt_name=prompt_name, max_tokens=max_tokens)

    workers = min(len(chunks), int(os.environ.get("KB_WORKERS", _DEFAULT_WORKERS)))
    phase = get_phase_context()
    timeout = get_call_timeout()
    req_tracker = get_request_tracker()

    def _extract_in_worker(chunk: str) -> ExtractionResult:
        set_phase_context(phase)
        set_call_timeout(timeout)
        set_request_tracker(req_tracker)
        return extract_knowledge(chunk, model, prompt_name=prompt_name, max_tokens=max_tokens)

    all_results: list[ExtractionResult] = [None] * len(chunks)  # type: ignore
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_in_worker, chunk): idx
                   for idx, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            idx = futures[future]
            all_results[idx] = future.result()

    merged = ExtractionResult()
    summaries = []
    for r in all_results:
        if r.summary:
            summaries.append(r.summary)
        merged.concepts.extend(r.concepts)
        merged.entities.extend(r.entities)
        merged.decisions.extend(r.decisions)
        merged.action_items.extend(r.action_items)
        merged.claims.extend(r.claims)
        merged.topics.extend(r.topics)
        merged.connections.extend(r.connections)

    merged.summary = " ".join(summaries)
    merged.topics = list(set(merged.topics))
    merged.connections = list(set(merged.connections))
    return merged


def _combine_extractions(items: list[tuple[str, ExtractionResult]]) -> tuple[ExtractionResult, list[str]]:
    combined = ExtractionResult()
    summaries: list[str] = []
    rels: list[str] = []
    for rel, extraction in items:
        if extraction.summary:
            summaries.append(extraction.summary)
        combined.concepts.extend(extraction.concepts)
        combined.entities.extend(extraction.entities)
        combined.decisions.extend(extraction.decisions)
        combined.action_items.extend(extraction.action_items)
        combined.claims.extend(extraction.claims)
        combined.topics.extend(extraction.topics)
        combined.connections.extend(extraction.connections)
        rels.append(rel)
    combined.summary = "\n".join(summaries)
    combined.topics = list(set(combined.topics))
    combined.connections = list(set(combined.connections))
    return combined, rels
