from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from kb_ai._context import adopt_context, get_context
from kb_ai._errors import ExtractionFailedError
from kb_ai.llm import (
    MAX_PROMPT_CHARS,
    completion,
    completion_json,
    get_call_timeout,
    set_call_timeout,
)

_DEFAULT_WORKERS = 16

# Per-call timeout for extract pipeline. Tighter than the default 900s because
# extract calls have predictable size (≤16K max_tokens) and a single hung call
# blocks the whole job (see diagnose log 2026-06-01, T4 d35bec86 stall 914s).
#
# "Predictable size" is not the same as predictable duration: the figure assumes a
# hosted model's generation speed. A model served on localhost can be an order of
# magnitude slower, at which point 180s fails on documents a hosted model handles
# without trouble -- a 12B local model exhausted all three attempts on a
# 4386-character prompt. _EXTRACT_TIMEOUT_ENV exists so that is a configuration
# change rather than a source edit.
#
# Size it knowing this phase retries in two places, unlike write: the LLM layer
# retries a timeout twice, and _phase2_with_retry re-dispatches its entire K-call
# set once on any failure, so a hung phase-2 call costs 6*timeout+60s to discover
# rather than 3*timeout+30s.
#
# _EXTRACT_TIMEOUT_ENV is honoured verbatim, including past DEFAULT_CLIENT_TIMEOUT_S.
# The client timeout is a default, not a ceiling -- _completion.py applies an override
# with client.with_options(timeout=...), which replaces the value rather than clamping
# it, so an operator who needs 1200 gets 1200.
_EXTRACT_CALL_TIMEOUT_S = 180.0
_EXTRACT_TIMEOUT_ENV = "KB_AI_EXTRACT_TIMEOUT_S"


@functools.lru_cache(maxsize=1)
def _warn_unusable_extract_timeout(raw: str) -> None:
    """Report an ignored override once, not once per extract call.

    Keyed on the raw string, matching merge.py's write-phase twin and _cost.py's
    handling of KB_AI_PRICING, so a corrected value is reported afresh rather than
    swallowed by the cache.
    """
    print(f"[extract] ignoring {_EXTRACT_TIMEOUT_ENV}={raw!r}: expected a positive "
          f"number of seconds — using {_EXTRACT_CALL_TIMEOUT_S}", file=sys.stderr)


def _extract_call_timeout() -> float:
    """The per-call extract timeout, re-read on every decorated entry.

    Read per call rather than at import like the neighbouring MAX_PROMPT_CHARS, so
    that setting the variable does not have to happen before kb_ai is imported.

    A value that cannot serve as a timeout is reported and ignored rather than
    honoured: '0' or a negative would fail every extract call instantly, and a
    non-finite one would silently remove the cap -- reinstating the hung-call stall
    the default was introduced to bound.
    """
    raw = os.environ.get(_EXTRACT_TIMEOUT_ENV, "")
    if not raw:
        return _EXTRACT_CALL_TIMEOUT_S
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if seconds > 0 and math.isfinite(seconds):
        return seconds
    _warn_unusable_extract_timeout(raw)
    return _EXTRACT_CALL_TIMEOUT_S


def _with_extract_timeout(fn):
    """Apply the extract-phase call timeout to all LLM calls within fn.

    Restoring to prev (not None) keeps nested invocations safe — if a future
    caller wraps extract in its own timeout context, we don't clobber it.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        prev = get_call_timeout()
        set_call_timeout(_extract_call_timeout())
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
    # A set the document enumerates completely, kept as its members rather than
    # as prose about them: {"name", "kind", "ordered", "items"}. Its own field
    # because the other seven all reward compression, and an enumeration is the one
    # shape where compression is the loss -- a model asked for prose about a
    # struct wrote about its timeout handling and dropped eight of eleven field
    # names, unrecoverably, since the write phase never re-reads raw (issue #41).
    enumerations: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    source_path: str = ""


def parse_extraction_result(raw: dict) -> ExtractionResult:
    return ExtractionResult(
        summary=raw.get("summary") or "",
        concepts=raw.get("concepts") or [],
        entities=raw.get("entities") or [],
        decisions=raw.get("decisions") or [],
        action_items=raw.get("action_items") or [],
        claims=raw.get("claims") or [],
        enumerations=raw.get("enumerations") or [],
        topics=raw.get("topics") or [],
    )


def extraction_to_dict(e: ExtractionResult) -> dict:
    return {
        "summary": e.summary, "concepts": e.concepts, "entities": e.entities,
        "decisions": e.decisions, "action_items": e.action_items,
        "claims": e.claims, "enumerations": e.enumerations, "topics": e.topics,
    }


# Every prompt the extraction stage can send. extract_prompt_version() hashes
# exactly this set, and load_prompt() asserts membership, so adding a fifth
# extraction prompt without listing it here fails at first use instead of
# silently narrowing the provenance hash (spec B14).
EXTRACT_STAGE_PROMPTS = ("extract", "extract-types", "merge-summaries", "summarize")


def load_prompt(name: str) -> str:
    """Load a prompt template by name from the file-based PromptRegistry.

    Prompts live as .yaml/.md files under prompts/defaults/ (override the
    directory with the KAAS_PROMPTS_DIR env var).
    """
    assert name in EXTRACT_STAGE_PROMPTS, (
        f"prompt {name!r} is not in EXTRACT_STAGE_PROMPTS; add it there so "
        "extract_prompt_version() keeps covering the whole extraction stage"
    )
    from kb_ai.prompts import default_registry
    return default_registry().get(name).content


def _extract_stage_renderings() -> list[tuple[str, str]]:
    """Every extraction prompt as it currently renders, with a stable name.

    The extract-types template is hashed through _render_type_split_prompt rather
    than verbatim: TYPE_SPLIT_GROUPS_K2/K3 and _FIELD_JSON_SCHEMAS are code
    constants, but they change the text actually sent to the model. Both group
    tables are enumerated here rather than mirrored, so a new group is covered
    the moment it is added.
    """
    out = [(name, load_prompt(name))
           for name in ("extract", "merge-summaries", "summarize")]
    for k, groups in ((2, TYPE_SPLIT_GROUPS_K2), (3, TYPE_SPLIT_GROUPS_K3)):
        for group in groups:
            out.append((f"extract-types#k{k}-{group}",
                        _render_type_split_prompt(group, k)))
    return out


@functools.lru_cache(maxsize=1)
def extract_prompt_version() -> str:
    """12 hex digits over the extraction stage's prompt set as it now renders.

    A pure function of the prompt files plus the two group tables, with no
    reference to which prompts a given run used -- so an extraction's freshness
    is a plain field comparison computable without spending anything. This is the
    convention classify_inputs_hash already established, whose docstring records
    that the previous categories-only hash let "a prompt-only edit silently keep
    serving classifications produced by the previous prompt".

    Memoized (spec B12): the registry caches lazily per name, so a long-lived
    daemon could otherwise hold `extract` from before a prompt edit and
    `summarize` from after it, making the value depend on load order rather than
    only on time. Computing it once pins all four names into the cache together
    and makes "restart the daemon after editing prompts" an exact rule.

    Name and content are framed with a length prefix and a NUL separator, so a
    trailing newline in one prompt cannot collide with the next name.
    """
    h = hashlib.sha256()
    for name, text in _extract_stage_renderings():
        body = text.encode("utf-8")
        h.update(f"{len(name)}\0{name}\0{len(body)}\0".encode("utf-8"))
        h.update(body)
        h.update(b"\0")
    return h.hexdigest()[:12]


_FIELD_JSON_SCHEMAS: dict[str, str] = {
    "summary": '"summary": "1-2 sentence summary of the entire document"',
    "concepts": '"concepts": [{"title": "short title", "summary": "one sentence"}]',
    "entities": '"entities": [{"name": "entity name", "type": "person|tool|project|team|system", "context": "why notable here"}]',
    "decisions": '"decisions": [{"title": "short title", "what": "what was decided", "why": "reasoning", "who": ["people involved"]}]',
    "action_items": '"action_items": [{"task": "description", "owner": "person name if known"}]',
    "claims": '"claims": [{"claim": "the assertion", "source": "who/what said this", "surprising": false}]',
    "enumerations": '"enumerations": [{"name": "what the set is", "kind": "struct fields|call order|const block|option list|steps|participants", "ordered": true, "items": ["every member, verbatim, in document order"]}]',
    "topics": '"topics": ["topic-tag-1", "topic-tag-2"]',
}

# enumerations joins the group that is lightest on document-shaped input, where it
# is heaviest: a source file yields long field lists and almost no decisions or
# action items. The pairing is per-K, not one rule, because the two tables split
# the same eight fields differently.
TYPE_SPLIT_GROUPS_K2: dict[str, tuple[str, ...]] = {
    "A": ("concepts", "entities", "topics", "summary"),
    "B": ("claims", "decisions", "action_items", "enumerations"),
}

TYPE_SPLIT_GROUPS_K3: dict[str, tuple[str, ...]] = {
    "A": ("concepts", "entities"),
    "B": ("claims", "summary", "topics"),
    "C": ("decisions", "action_items", "enumerations"),
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
    parent_ctx = get_context()

    def _merge_in_worker(group: list[str]) -> str:
        adopt_context(parent_ctx)
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

    parent_ctx = get_context()

    def _extract_one_group(group: str) -> dict:
        adopt_context(parent_ctx)
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
    parent_ctx = get_context()

    def _summarize_in_worker(chunk: str) -> str:
        adopt_context(parent_ctx)
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
        # Raise rather than return a bare ExtractionResult, matching the chunked
        # path's `future.result()` with no except. An empty result here was
        # indistinguishable from "the model read the content and had nothing to
        # say", and once extractions are persisted with provenance that ambiguity
        # becomes a file that looks fresh and empty forever. With the raise, an
        # empty extraction means only the legitimate case. Partial chunk failure
        # keeps degrading as before, on the survivors.
        raise ExtractionFailedError(
            f"every chunk summarization failed ({len(chunks)} chunks); "
            "nothing to extract from"
        )

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
    parent_ctx = get_context()

    def _extract_in_worker(chunk: str) -> ExtractionResult:
        adopt_context(parent_ctx)
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
        merged.enumerations.extend(r.enumerations)
        merged.topics.extend(r.topics)

    merged.summary = " ".join(summaries)
    merged.topics = list(set(merged.topics))
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
        combined.enumerations.extend(extraction.enumerations)
        combined.topics.extend(extraction.topics)
        rels.append(rel)
    combined.summary = "\n".join(summaries)
    combined.topics = list(set(combined.topics))
    return combined, rels


# ── the extraction strategy router ──────────────────────────────────
#
# Both ingestion routes resolve a strategy through here rather than each deciding
# for itself. The CLI's freshness gate used to assert "chunked" while the daemon
# recorded whatever it routed to, so a KB configured for summarize had every
# UI-ingested document re-extracted once by the next CLI compile and silently
# downgraded -- the two routes disagreeing about the KB's own configuration.
#
# The two strategies are not coarse and fine versions of one thing. chunked sends
# the document text (split only if it exceeds the window) to the structured
# extractor; summarize summarizes each chunk first and extracts from the joined
# summaries, so the structured pass never sees the original words. Which one
# produced an extraction is therefore part of what staleness compares.

STRATEGY_CHUNKED = "chunked"
STRATEGY_SUMMARIZE = "summarize"
# Resolved on chunk count, never recorded: persist stores the strategy that ran.
STRATEGY_AUTO = "auto"
EXTRACT_STRATEGIES = (STRATEGY_CHUNKED, STRATEGY_SUMMARIZE, STRATEGY_AUTO)

# Below this, auto keeps the document text: summarizing one or two chunks pays a
# second model for a loss of detail it does not need to take.
_AUTO_SUMMARIZE_MIN_CHUNKS = 3


@dataclass(frozen=True)
class ExtractionPlan:
    """What will run for one document, decided without spending anything.

    strategy is what persist records, so it is never "auto". chunks and meta are
    carried because the summarize path needs them and chunking them twice would
    be wasted work -- and because resolving auto requires them anyway.
    """

    strategy: str
    chunks: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)


def validate_strategy(requested: str) -> str:
    """Return requested, or raise if it is not a strategy this code runs.

    One message in one place, called both by the router and by a caller wanting to
    reject a bad configuration before it starts work. Never falls back to chunked:
    silently falling back is what kept this class of bug invisible, since a typo
    in a deployment's configuration would extract every document under a strategy
    nobody chose and the recorded provenance would agree with itself.
    """
    if requested not in EXTRACT_STRATEGIES:
        raise ValueError(
            f"unknown extract strategy {requested!r}, expected one of "
            f"{', '.join(EXTRACT_STRATEGIES)}")
    return requested


def plan_extraction(content: str, requested: str) -> ExtractionPlan:
    """Resolve a requested strategy for one document. No LLM call, no network.

    Chunking costs nothing but CPU, which is what lets the freshness gate compare
    against the strategy a run would actually produce before deciding to pay for
    it. A requested chunked or summarize is honoured as asked and the content is
    not even read; only auto has to look.

    An unrecognised strategy raises rather than falling back to chunked. Silently
    falling back is what kept this class of bug invisible: a typo in a
    deployment's configuration would extract every document under a strategy
    nobody chose, and the recorded provenance would agree with itself.
    """
    validate_strategy(requested)

    if requested == STRATEGY_CHUNKED:
        return ExtractionPlan(strategy=STRATEGY_CHUNKED)

    meta, body = _parse_frontmatter(content)
    chunks = tuple(chunk_transcript(body, meta) if _is_transcript(meta)
                   else chunk_content(content))

    if requested == STRATEGY_SUMMARIZE:
        strategy = STRATEGY_SUMMARIZE
    elif len(chunks) >= _AUTO_SUMMARIZE_MIN_CHUNKS:
        strategy = STRATEGY_SUMMARIZE
    else:
        strategy = STRATEGY_CHUNKED

    return ExtractionPlan(strategy=strategy, chunks=chunks, meta=meta)


def run_planned_extraction(
    plan: ExtractionPlan,
    content: str,
    *,
    extract_model: str,
    summarize_model: str = "",
) -> ExtractionResult:
    """Extract one document under an already-resolved plan.

    Split from plan_extraction so a caller can compare the resolved strategy
    against what is already on disk and decline to spend -- which is the whole
    point of resolving before running.
    """
    if plan.strategy == STRATEGY_SUMMARIZE:
        return extract_knowledge_summarized(
            list(plan.chunks), plan.meta, summarize_model, extract_model)
    return extract_knowledge_chunked(content, model=extract_model)
