from __future__ import annotations

import functools
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as _date
from typing import Callable, Sequence

from kb_ai._frontmatter import as_day, read_document_frontmatter
from kb_ai.core.extract import ExtractionResult
from kb_ai.llm import (
    MAX_PROMPT_CHARS,
    completion,
    completion_json,
    get_call_timeout,
    set_call_timeout,
)
from kb_ai.prompts import default_registry

_SAFETY_MARGIN = 500

# Per-call timeout for the write phase, mirroring extract's override. Without one
# a write inherits DEFAULT_CLIENT_TIMEOUT_S, and a gateway that hangs on a 6-8K
# prompt then costs 15 minutes to discover -- three derive runs each lost roughly
# that to a single stalled call (issue #26).
#
# Sized above extract's 180s because a merge prompt carries the whole existing
# article on top of the extraction, and below the client default because that is
# the number this exists to replace. The one stall-free reference run
# (docs/articles/kaas-bootstrap-case-study: 48 article groups, 16 workers) spent
# 255.27s on the *entire* write phase, so no single call in it came close to this.
#
# Known bound: completion() retries a truncated response with max_tokens doubled,
# and a write escalated past its 16384 default could plausibly need longer than
# this. No run has produced one -- an article that overruns 16K output tokens is
# already pathological -- so this is not scaled per attempt until one shows up.
_WRITE_CALL_TIMEOUT_S = 300.0


def _with_write_timeout(fn):
    """Apply _WRITE_CALL_TIMEOUT_S to all LLM calls within fn, restoring on exit.

    On the entry points rather than on their callers, so that every write path
    reaching them is covered: both compile_kb's write phase and the pipeline's
    run_write_phase, and anything added later.

    Restoring to prev (not None) keeps nested invocations safe, matching
    extract's _with_extract_timeout.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        prev = get_call_timeout()
        set_call_timeout(_WRITE_CALL_TIMEOUT_S)
        try:
            return fn(*args, **kwargs)
        finally:
            set_call_timeout(prev)
    return wrapper


# Order is survival order under a tight budget: _fit_block_to_budget adds fields
# from the top and halves a list that does not fit.
#
# enumerations sits second because it is the one field truncation cannot degrade
# gracefully. A writer given six of eleven middleware names does not produce a
# shorter list, it produces a confident wrong one (issue #41, and #42 is what that
# looks like in a compiled article), while a halved concepts list reads as a
# thinner article and nothing more.
_FIELD_PRIORITY = [
    ("summary",      "str"),
    ("enumerations", "list"),
    ("concepts",     "list"),
    ("entities",     "list"),
    ("decisions",    "list"),
    ("topics",       "list"),
    ("claims",       "list"),
    ("action_items", "list"),
]


@dataclass(frozen=True)
class SourceBlock:
    """One source's contribution to a write payload: what it said, and when.

    The write phase used to receive one flattened ``ExtractionResult`` and one
    source string -- for a multi-source article, every summary concatenated and
    every list extended, under a comma-joined list of paths. Two things were
    unrecoverable from that shape: which document made a given claim, and which
    of them is the later one. An article composed from a plan and its revision
    could therefore state both and contradict itself (supersession spec WP3).

    ``date`` is the day the *document* names, not the day it was ingested, and
    ``None`` means the document does not say. It is deliberately not filled in
    from a guess: ``derive`` copies ``raw/`` (``derive/_layout.py:193``), which
    rewrites mtime to the copy time, so mtime dates the copy and not the content
    (spec Q2).
    """

    source_path: str
    extraction: ExtractionResult
    date: _date | None = None


def _document_date(read_raw: Callable[[str], str], source_path: str) -> _date | None:
    """The day a raw document dates itself, read at write time (spec WP2, D4).

    A deliberate exception to the extraction layer's rule that the write phase
    reads only from ``extraction/``. The alternative -- a provenance field on the
    stored extraction -- costs a ``schema_version`` bump, and a bump refuses every
    existing extraction file, re-extracting the whole KB at 0.0551 USD per
    document to recover a value ``raw/`` already holds.

    An unreadable document degrades to undated rather than failing the write. The
    date is a nicety and the article is not: a document whose raw file went away
    between the scan and the write, or that is not valid UTF-8, still deserves to
    be composed. ValueError covers both a decoding failure and KBStore's
    containment check, which cannot be satisfied here by returning a date anyway.
    Reported on stderr because a date going quietly missing is the corpus defect
    this whole increment exists to fix.
    """
    try:
        content = read_raw(source_path)
    except (OSError, ValueError) as e:
        print(f"[merge] no date read for {source_path}: {e}", file=sys.stderr, flush=True)
        return None
    frontmatter, _body = read_document_frontmatter(content)
    return as_day(frontmatter.get("date"))


def build_source_blocks(
    read_raw: Callable[[str], str],
    items: Sequence[tuple[str, str, ExtractionResult]],
) -> list[SourceBlock]:
    """Turn (source_path, checksum, extraction) triples into ordered blocks.

    Both write routes build their payload through here, so the CLI and the daemon
    cannot disagree about ordering or duplicates (spec VF6). ``read_raw`` is
    passed rather than a store so that this module keeps knowing nothing about
    storage layout.

    Duplicates collapse on checksum (WP7): 55 lineage groups in the corpus are
    the same bytes ingested twice, and two blocks of one document would double
    its claims' weight in the payload. The survivor is the first in path order,
    so two runs over one KB name the same document as the source.

    One consequence, accepted: the collapsed path is no longer named in the
    article's ``sources:`` either, where the comma-joined item used to carry both
    and ``derive/_sources.py`` split them apart again. So a duplicate is recorded
    as compiled into an article the article does not name, and ``derive`` will not
    copy that file. It costs the derived KB no content -- the bytes are identical
    to the survivor's, which is copied -- only the second path's name. Compile
    state still records both, because the ops bookkeeping reads the merge list
    rather than the surviving blocks (``compile.py``).

    Blocks come back oldest to newest, undated last in path order (WP5). Both
    orders are total and path-derived, because ``compile.py`` writes article
    groups on 16 workers and raw-scan order is not stable across ingests -- an
    ordering that varied per run would make the payload unreproducible. Sources
    sharing a day sit in path order for that reason alone, which is why the prompt
    withdraws the ordering claim between them rather than letting the render imply
    one (WP9).
    """
    by_checksum: dict[str, SourceBlock] = {}
    for source_path, checksum, extraction in sorted(items, key=lambda item: item[0]):
        if checksum in by_checksum:
            continue
        by_checksum[checksum] = SourceBlock(
            source_path=source_path,
            extraction=extraction,
            date=_document_date(read_raw, source_path),
        )

    blocks = list(by_checksum.values())
    dated = sorted((b for b in blocks if b.date is not None),
                   key=lambda b: (b.date, b.source_path))
    undated = sorted((b for b in blocks if b.date is None), key=lambda b: b.source_path)
    return dated + undated


def _block_header(block: SourceBlock) -> str:
    """The ``- Source:`` line, and the ``- Date:`` line when there is one (WP1).

    An undated source gets no date line at all rather than a placeholder: the
    system prompt states that blocks run oldest to newest, that an undated source's
    position carries no ordering claim (WP6) and that two blocks sharing a day make
    none about each other (WP9), and a rendered "unknown"
    would be a second, weaker statement of the same thing in the place where the
    model is least likely to apply it.
    """
    header = f"- Source: {block.source_path}\n"
    if block.date is not None:
        header += f"- Date: {block.date.isoformat()}\n"
    return header


def _block_topics(blocks: Sequence[SourceBlock]) -> list[str]:
    """Every block's topics, in first-seen order.

    Deterministic where the flattening it replaces was not:
    ``_combine_extractions`` returned ``list(set(topics))``, so the tag list a
    create prompt carried varied between runs over identical input.
    """
    out: list[str] = []
    seen: set = set()
    for block in blocks:
        for topic in block.extraction.topics:
            if topic not in seen:
                seen.add(topic)
                out.append(topic)
    return out


def _min_blocks_chars(blocks: Sequence[SourceBlock]) -> int:
    """Floor for "can a full rewrite hold the new information at all".

    Per block, so that the route chosen scales with how many sources are waiting
    rather than with one of them. It is only a routing floor: clearing it does not
    mean every source contributes, because BG2 drops whole blocks that do not fit
    once the rewrite path has been chosen.
    """
    return sum(len(block.source_path) + 50 for block in blocks)


def _estimate_block_size(block: SourceBlock) -> int:
    """Estimate full untruncated character count of one block's text."""
    size = len(_block_header(block))
    for field_name, field_type in _FIELD_PRIORITY:
        value = getattr(block.extraction, field_name, None)
        # Skip falsy the same way _fit_block_to_budget does, otherwise the
        # estimate counts lines the output never emits and every merge would
        # report a truncation that never happened.
        if not value:
            continue
        if field_type == "str":
            size += len(f"- {field_name.replace('_', ' ').title()}: {value}\n")
        else:
            size += len(f"- {field_name.replace('_', ' ').title()}: {json.dumps(value, ensure_ascii=False)}\n")
    return size


def _budget_priority(blocks: Sequence[SourceBlock]) -> list[int]:
    """Indices into ``blocks``, in the order they may claim the budget (BG1).

    Dated blocks first, newest day to oldest, then the undated ones in the path order
    WP5 already put them in. Not simply the render order reversed: WP5 sorts
    undated blocks *last* for determinism, so reversing would put the blocks that
    make no recency claim at the front of the queue and drop the one source we
    know to be the newest. Measured on two 3,000-char blocks against a budget for
    one: the undated block survived and the 2021 document was dropped.

    An undated source is therefore the first to give way, including to a dated
    source older than it may turn out to be. Ranking it above older dated blocks
    would be a recency claim WP6 tells the model not to read into its position,
    made on nothing; what BG1 buys is that the newest *known* source is in the
    payload, and this is the order that pays it.

    Stated as BG1's own basis: newest known *day* first, ties broken on path for
    stability, with no claim that the block served first is the newer of a same-day
    pair. WP9 withdraws that claim in the prompt, and priority here must not
    reinstate it -- one of two peers is served first because a drop has to be
    reproducible, not because it is later.

    Sources sharing a day therefore break to path order, the same direction the
    undated ones take, and both keys are read off the blocks rather than inherited
    from the order they arrive in -- so the queue is a total order for any input, not
    only for what ``build_source_blocks`` happens to emit. It decides real drops: on
    the reference KB **160 of the 397 multi-source articles carry a same-day pair,
    412 pairs** after WP7 collapses identical checksums (414 before it, and the
    dedup removes 2 pairs because only one article holds a byte-identical duplicate
    of its own source). Two earlier figures for this line were both measured on
    something else: 160 of 395 predates two articles being added, and V20's recorded
    156 of 397 / 384 pairs deduped on the *body* with frontmatter stripped, which
    collapses 84 within-article groups of which 83 hold documents whose frontmatter
    dates differ -- the distinction the same-day population is about, and one WP7
    does not make, since its key is sha256 over the whole file (``storage/store.py``
    ``_compute_checksum``, applied at ``:172``).
    """
    dated = sorted((i for i, b in enumerate(blocks) if b.date is not None),
                   key=lambda i: (-blocks[i].date.toordinal(), blocks[i].source_path))
    undated = sorted((i for i, b in enumerate(blocks) if b.date is None),
                     key=lambda i: blocks[i].source_path)
    return dated + undated


def _render_blocks(blocks: Sequence[SourceBlock], budget_chars: int) -> str:
    """Render blocks in the order given, allocating the budget newest first (BG1).

    Oldest to newest is the caller's guarantee, not this function's: every
    production payload comes from ``build_source_blocks``, which sorts (WP5), and
    the system prompt states that order to the model (_SOURCE_ORDER).

    The rendered order is therefore WP5's and does not change; only the order in which
    blocks claim the budget does, which is ``_budget_priority``'s. Allocating in
    render order would spend the budget on the oldest source and cut the newest,
    which is backwards for the thing this increment exists to fix: whether a claim
    has been superseded is a question about what the *latest* document says.

    Each block is kept only if it fits whole in what is left, separator included,
    and the first one that does not ends the walk -- so what survives is a prefix
    of the priority order and what is dropped is whole blocks from the bottom of it
    (BG2). A block cut down to its header and a halved list is worse than an absent
    one: the writer cannot tell a thin source from a truncated one, and a partial
    enumeration is what it turns into a confident wrong list (#41, #42). Stopping
    rather than skipping to smaller blocks further down the queue is what keeps the
    payload a run of the sources that rank highest, instead of whichever ones
    happened to fit.

    A budget too small for even the highest-priority block is spent truncating that
    one block by field priority (BG4). The alternative is a merge that sends the
    article and no new information, silently: it would look successful and change
    nothing.

    Every source that contributed nothing is named on stderr (BG3). The cut notice
    in ``_fit_block_to_budget`` covers a block that was trimmed; a dropped block
    emits no text at all, so the one source the operator most needs to know about
    would otherwise be the only one that leaves no trace. Both callers
    (``_merge_user_message``, ``create_new_article``) still name a dropped source
    under ``sources:``, so ``derive`` still copies the document and compile state
    still records it as compiled. That is deliberate -- the alternative is a
    document no article names, which therefore never reaches a derived KB -- but it
    does mean an article can name a source the writer was shown nothing from.
    """
    remaining = budget_chars
    texts: dict[int, str] = {}
    dropped: list[int] = []
    priority = _budget_priority(blocks)

    for position, index in enumerate(priority):
        block = blocks[index]
        # The separator between two blocks is part of what the caller's budget
        # has to cover: three blocks that each fit exactly would overrun it by
        # two. It is charged per kept block rather than deducted up front,
        # because how many blocks survive is not known until the walk ends.
        separator = 1 if texts else 0
        if _estimate_block_size(block) + separator <= remaining:
            # Clamped to the budget minus that separator rather than handed all of
            # it, which renders the same text today: the block fits whole by the
            # line above. It matters if the two ever disagree -- the estimator and
            # the renderer spell the same lines out twice and could drift -- and
            # then this cuts the block instead of overrunning the caller.
            text = _fit_block_to_budget(block, remaining - separator)
            texts[index] = text
            remaining -= len(text) + separator
            continue

        if texts:
            dropped = priority[position:]
            break

        # BG4: nothing has been kept, so this block gets what there is.
        text = _fit_block_to_budget(block, remaining)
        if text:
            texts[index] = text
            dropped = priority[position + 1:]
        else:
            # Too small even for a bare source line. Nothing was kept at all, so
            # this block is named among the dropped like every other one.
            dropped = priority[position:]
        break

    for index in sorted(dropped):  # render order, so the notices read as the payload does
        block = blocks[index]
        print(f"[merge] block dropped, over budget: "
              f"{_estimate_block_size(block)} chars (source={block.source_path})",
              file=sys.stderr, flush=True)

    return "\n".join(texts[index] for index in sorted(texts))


def _fit_block_to_budget(block: SourceBlock, budget_chars: int) -> str:
    """Build one block's text fitting within budget_chars.

    Fields are added in priority order. List fields use exponential backoff
    (halving item count) when full content exceeds remaining budget.
    """
    extraction = block.extraction
    source_path = block.source_path
    prefix = _block_header(block)
    if budget_chars < len(prefix):
        # Strictly under, not at: a budget of exactly the header renders the
        # header, and `_render_blocks` hands that budget to a block it has
        # measured as fitting whole -- an extraction with every priority field
        # empty is nothing but its header. Rejecting it at equality dropped the
        # date line from a block reported as kept, silently and with the rest of
        # the budget unspent.
        #
        # The date line is dropped whole rather than cut: `- Date: 2020-` is a
        # false ordering signal where a half-written source path is only
        # cosmetic, and a prefix cut mid-line loses the newline that separates it
        # from whatever the caller renders next.
        source_line = f"- Source: {source_path}\n"
        if budget_chars >= len(source_line):
            return source_line
        return source_line[:budget_chars] if budget_chars > 0 else ""

    parts: list[str] = [prefix]
    used = len(prefix)

    for field_name, field_type in _FIELD_PRIORITY:
        value = getattr(extraction, field_name, None)
        if not value:
            continue

        available = budget_chars - used
        if available <= 0:
            break

        label = field_name.replace("_", " ").title()

        if field_type == "str":
            line = f"- {label}: {value}"
            if len(line) + 1 > available:
                # Truncate string value to fit
                max_val_len = available - len(f"- {label}: ") - 1
                if max_val_len > 0:
                    line = f"- {label}: {value[:max_val_len]}"
                else:
                    continue
            parts.append(line + "\n")
            used += len(line) + 1
        else:
            # List field: try full, then exponential backoff
            full_json = json.dumps(value, ensure_ascii=False)
            line = f"- {label}: {full_json}\n"
            if len(line) <= available:
                parts.append(line)
                used += len(line)
            else:
                # Exponential backoff: halve until it fits
                n = len(value)
                while n > 0:
                    n = n // 2
                    if n == 0:
                        break
                    truncated_json = json.dumps(value[:n], ensure_ascii=False)
                    line = f"- {label}: {truncated_json}\n"
                    if len(line) <= available:
                        parts.append(line)
                        used += len(line)
                        break

    result = "".join(parts)
    full_size = _estimate_block_size(block)
    if len(result) < full_size:
        print(
            f"[merge] extraction truncated: {full_size} -> {len(result)} chars "
            f"(source={source_path})",
            file=sys.stderr,
            flush=True,
        )
    return result


def _parse_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown by ## heading into [(heading_line, body_text), ...]"""
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_heading or current_body_lines:
                sections.append((current_heading, "\n".join(current_body_lines)))
            current_heading = line
            current_body_lines = []
        else:
            current_body_lines.append(line)

    if current_heading or current_body_lines:
        sections.append((current_heading, "\n".join(current_body_lines)))

    return sections


def _truncate_article_by_sections(article_content: str, topics: list[str], budget_chars: int) -> str:
    """Section-based article truncation for diff mode.

    Algorithm:
    1. Parse ## heading structure
    2. Always keep all headings as skeleton (diff patch anchors)
    3. Score sections by heading word overlap with topics
    4. Greedily fill relevant section bodies until budget exhausted
    5. Non-relevant sections keep only heading
    """
    sections = _parse_sections(article_content)

    # Skeleton size (all headings)
    skeleton_size = sum(len(h) + 1 for h, _ in sections)
    if skeleton_size >= budget_chars:
        # Extreme: even headings don't fit, truncate heading list
        result_parts: list[str] = []
        remaining = budget_chars
        for h, _ in sections:
            if remaining < len(h) + 1:
                break
            result_parts.append(h)
            remaining -= len(h) + 1
        return "\n".join(result_parts)

    # Compute topic word set
    topic_words: set[str] = set()
    for t in (topics or []):
        topic_words.update(t.lower().replace("-", " ").split())

    # Score each section by topic relevance
    scored: list[tuple[int, int, str, str]] = []
    for i, (heading, body) in enumerate(sections):
        heading_words = set(heading.lower().replace("#", "").strip().split())
        overlap = len(heading_words & topic_words)
        scored.append((overlap, i, heading, body))

    scored.sort(key=lambda x: -x[0])

    # Greedy fill
    remaining = budget_chars - skeleton_size
    included_bodies: set[int] = set()

    for _score, idx, _heading, body in scored:
        if remaining <= 0:
            break
        if len(body) <= remaining:
            included_bodies.add(idx)
            remaining -= len(body)

    # Reassemble in original order
    result_parts = []
    for i, (heading, body) in enumerate(sections):
        result_parts.append(heading)
        if i in included_bodies:
            result_parts.append(body)

    result = "\n".join(result_parts)
    if len(result) < len(article_content):
        print(f"  [truncation] article sections: {len(article_content)} → {len(result)} chars",
              file=sys.stderr)
    return result


_LARGE_ARTICLE_THRESHOLD = 30_000


# Appended to all three write-stage system prompts (issue #42).
#
# #41 fixed the supply: extraction now carries enumerations verbatim. This is the
# other half. Compiling go-zero produced a MiddlewaresConf table with an `Auth`
# field that does not exist in the framework and a numbered middleware chain that
# appeared in no extraction -- 9 of 11 correct, which is the tell. Nothing in the
# three prompts said the article was bounded by its input, so with a thin
# enumeration in hand, completing it from what the model already knew about a
# popular open-source framework was the *fluent* thing to do, and fluency was the
# only thing being asked for.
#
# A code constant rather than a fourth prompt file, for two reasons. It has to
# reach all three system prompts and one of them (_create_system) is already code,
# so a file would leave the rule written in two places to drift apart. And a
# registry lookup would make an operator's existing KAAS_PROMPTS_DIR raise
# NoActivePromptError on the first write after upgrade.
#
# The last bullet is the one that does the work. Told only "do not invent", a
# writer with a six-member list still produces six members and no sign that the
# set was larger; it needs an action it is allowed to take instead.
_GROUNDING = """
Grounding — this article is a compilation of the material you were given, not a
composition about its subject:
- Every named thing you write — a field, function, parameter, option, step, person
  — must appear in the material. If you recognise the subject and know more about
  it than the material states, that knowledge does not belong in this article.
- A set given under Enumerations is closed. Carry every member, in the order
  given, under the names given; add nothing to it and rename nothing in it.
- Never complete a partial set. When the material names some members of a set that
  evidently has more, write the ones you were given and say plainly that the list
  is what the material records. An incomplete list labelled as such is useful; a
  completed one is a fabrication, and it reads exactly like the real thing.
- Prefer saying the material does not cover something over supplying it. A gap a
  reader can see is a gap someone can fill; a gap you filled is one nobody finds.
"""


# Appended to all three write-stage system prompts, after the grounding block
# (supersession spec WP6, with the same-day withdrawal of WP9).
#
# The same-day bullet is a withdrawal and not a tie-breaker, ruled as queue item
# V20: two blocks sharing a day are ordered by path here, which carries no recency
# evidence, and on the reference KB that reaches 160 of 397 multi-source articles
# (412 pairs, measured in _budget_priority below). No signal covers that population
# -- a filename version marker appears on 9 of the pairs and survives inspection on
# 1 -- and reading the body's own date is A2's question, where 109 of the 505
# documents stating one point earlier than their frontmatter against 101 later. So
# the prompt stops claiming a relation it cannot support instead of guessing one.
#
# The payload changed shape under this increment: one block per source, dated
# where the document dates itself, rendered oldest to newest with the undated ones
# last (WP1, WP3, WP5). A sequence whose meaning is never stated is one the writer
# is free to read either way -- and the undated tail is the trap, because it sorts
# last for determinism and not for recency, so an unexplained order invites reading
# the sources that make no recency claim as the newest material.
#
# In the system prompt rather than the user message because that is where an
# instruction is applied reliably, and a code constant rather than a fourth prompt
# file for _GROUNDING's reasons above: it has to reach all three system prompts,
# one of which (_create_system) is already code, and a registry lookup would make
# an operator's existing KAAS_PROMPTS_DIR raise NoActivePromptError on the first
# write after upgrade.
#
# It states facts and asks for nothing, and that division is still deliberate now
# that the writer has an action to take. What to *do* about a contradiction lives
# in the two prompt files, which A2 gave the replace primitive and its
# [Superseded ...] trail (merge-diff.md's `supersede`, merge-rewrite.md's prose
# rule). This block is the evidence the judgement runs on -- which document is
# newer, and when the payload says nothing about it -- so a rule about the action
# would be split across two places to drift apart. `_create_system` keeps this
# block and gains no action either, per NG13: a fresh article states the newest
# value and has nothing to retract.
#
# Two known approximations in what it asserts, both narrower than the statement and
# neither worth A1's scope to close. "One block per source" is one block per source
# the budget kept: BG2 drops whole blocks the `Sources:` list still names. And
# `_fit_block_to_budget`'s bare-source-line branch can emit a dated block's header
# without its `- Date:` line, which reads here as a source making no ordering claim
# -- the inverse of what that document says. It needs a source path longer than the
# 200-character floor both callers apply, and the corpus maximum is 148.
_SOURCE_ORDER = """
Source order — the material you were given is one block per source document:
- The blocks run oldest to newest. A block's `- Date:` line is the day that source
  document is dated, which is not the day it was ingested or compiled.
- Two blocks sharing the same day carry no ordering claim relative to each other.
  They sit in path order for reproducibility, not because the one that appears
  first is the earlier document: which of them came first that day is unknown.
- A block with no `- Date:` line is undated. Undated blocks come last for
  reproducibility, not because they are recent: where such a source sits among the
  others is unknown, and its position carries no ordering claim to read.
"""


def _merge_rewrite_system() -> str:
    """The rewrite path's system prompt: file, grounding constraint, source order.

    One function for the three callers that need it -- the budget calculation in
    merge_into_article, the send in _merge_full_rewrite, and the hash in
    _write_stage_renderings. Composed rather than sent verbatim, so a budget
    computed from the file alone would under-reserve by the appended blocks and a
    hash over the file alone would not move when one of them is edited.
    """
    return (default_registry().get("merge-rewrite").render()
            + "\n" + _GROUNDING + _SOURCE_ORDER)


def _merge_diff_system() -> str:
    """The diff path's system prompt: file, grounding constraint, source order.

    .content, not .render(): merge-diff.md holds literal `{...}` JSON example
    braces, which str.format would read as placeholders.
    """
    return (default_registry().get("merge-diff").content
            + "\n" + _GROUNDING + _SOURCE_ORDER)


# SG1's, SG2's and SG3's findings, as the compile report consumes them. One flat
# record rather than four, because the report prints one line per finding and the
# arm counts them by kind (FA5): a shape per rule would put the same loop in both
# write routes and let them word the same finding two ways.
#
# The reasons stay where they are produced (_REFUSE_*, _TRAIL_*) -- this carries
# them, it does not restate them.
EV_SUPERSEDE_REFUSED = "supersede-refused"
EV_TRAIL_MALFORMED = "malformed-trail"
EV_TRAIL_LOST = "abandoned"
EV_ARTICLE_SHRANK = "shrank"


@dataclass(frozen=True)
class MergeEvent:
    """One report line about one merge op, per SG4.

    Operator-facing and terminal: nothing built from these re-enters a prompt, and
    the write entry points take source blocks and nothing else, so an event cannot
    reach the model that produced it. ``detail`` is the anchor, trail block or
    delta -- already cut to 80 characters and folded onto one line by whichever
    rule produced it, so a formatter cannot turn one finding into two lines.
    """

    kind: str
    article: str
    reason: str
    detail: str = ""


def format_merge_event(event: MergeEvent) -> str:
    """The report's line shape, in one place for both write routes."""
    tail = f": {event.detail}" if event.detail else ""
    return f"  [{event.kind}] {event.article}: {event.reason}{tail}"


def _report(events: list[MergeEvent] | None, kind: str, article: str,
            reason: str, detail: str = "") -> None:
    """Collect a finding, or print it when the caller keeps no sink.

    Collected *instead of* printed, not as well as: the sink's owner logs the
    report itself, so emitting at both layers would tell an operator the same
    refusal twice and make a count of report lines wrong. Callers that pass no
    sink -- direct callers and every test written before step 4 -- keep the stderr
    behaviour they had, which is the only report those have.
    """
    event = MergeEvent(kind=kind, article=article, reason=reason, detail=detail)
    if events is None:
        print(f"[merge] {format_merge_event(event).strip()}",
              file=sys.stderr, flush=True)
    else:
        events.append(event)


@_with_write_timeout
def merge_into_article(
    article_path: str,
    article_content: str,
    sources: Sequence[SourceBlock],
    model: str = "claude-sonnet-4-6",
    events: list[MergeEvent] | None = None,
) -> str:
    """Merge ``sources`` into an existing article, by rewrite or by diff.

    ``sources`` is expected oldest to newest with the undated last -- what
    ``build_source_blocks`` returns (WP5). The system prompt tells the model the
    blocks arrive in that order (_SOURCE_ORDER), so a caller that sorts differently
    makes the payload say something untrue rather than merely unordered.

    ``events``, when given, collects this op's findings for the compile report
    (SG1-SG3) instead of printing them. A caller that keeps one is the only layer
    that can count them or turn an abandoned merge into its own status; the events
    are terminal per SG4 and never travel back into a prompt.
    """
    if len(article_content.encode("utf-8")) >= _LARGE_ARTICLE_THRESHOLD:
        merged = _merge_diff(article_path, article_content, sources, model, events)
    else:
        # Budget-aware: check if full rewrite fits.
        # Registry caches per-process, so this call here + same call inside
        # _merge_full_rewrite both hit the cache after the first lookup.
        full_rewrite_system = _merge_rewrite_system()
        budget = MAX_PROMPT_CHARS - len(full_rewrite_system) - _SAFETY_MARGIN
        if len(article_content) + _min_blocks_chars(sources) > budget:
            merged = _merge_diff(article_path, article_content, sources, model, events)
        else:
            merged = _merge_full_rewrite(article_path, article_content, sources, model,
                                         events)

    _report_shrink(events, article_path, article_content, merged)
    return merged


def _report_shrink(events: list[MergeEvent] | None, article_path: str,
                   before: str, after: str) -> None:
    """SG2: the byte delta of a merge that made its article smaller.

    Bytes rather than characters, because that is what the Size column reads and
    what a reader sees on disk -- a rewrite can drop three CJK characters for one
    ASCII word and grow in characters while shrinking by six bytes.

    Reported here rather than by the callers, though both of them hold the two
    strings: the delta is one number that must not depend on which route wrote the
    article, and this is the layer both routes go through. Equal is not smaller, and
    an abandoned merge returns what it was given, so neither reports anything.
    """
    pre, post = len(before.encode("utf-8")), len(after.encode("utf-8"))
    if post >= pre:
        return
    _report(events, EV_ARTICLE_SHRANK, article_path,
            f"shrank {pre - post} bytes ({pre} → {post})")


def _merge_full_rewrite(
    article_path: str, article_content: str,
    sources: Sequence[SourceBlock], model: str,
    events: list[MergeEvent] | None = None,
) -> str:
    system = _merge_rewrite_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN
    user = _merge_user_message(article_content, sources, budget)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    def send(msgs: list[dict]) -> str:
        text = completion(model=model, messages=msgs,
                          max_tokens=16384, cache=True).strip()
        return _strip_markdown_fencing(text)

    # SG1, per D9. The diff path cannot delete a trail block; this one re-emits
    # the whole article, so preservation is only checkable against the output.
    merged = send(messages)
    missing = _lost_trails(article_content, merged)
    if missing:
        note = _trail_retry_note(missing, MAX_PROMPT_CHARS - len(system) - len(user))
        merged = send(messages + [{"role": "user", "content": note}])
        missing = _lost_trails(article_content, merged)
    if missing:
        # The one loss that cannot be recovered from the article itself, so the
        # merge is dropped instead: every other kind of write defect leaves text a
        # human can still read and fix. One line per block, cut where SG3 and TR6
        # cut theirs -- a trail block is as long as the claim it records.
        for block in missing:
            _report(events, EV_TRAIL_LOST, article_path, _TRAIL_LOST, block[:80])
        return article_content

    # TR6's report. This path writes its own trail text, so a malformed block is
    # reported and the write still lands: the note is prose a human can fix, where
    # dropping the merge loses everything else it carried. Read off the article that
    # lands, and only reached when one does -- reporting the format of prose in an
    # abandoned rewrite would send an operator to text no file holds.
    for defect in _trail_defects(article_content, merged, sources):
        _report(events, EV_TRAIL_MALFORMED, article_path, defect.reason, defect.trail)
    return merged


def _merge_diff(
    article_path: str, article_content: str,
    sources: Sequence[SourceBlock], model: str,
    events: list[MergeEvent] | None = None,
) -> str:
    from datetime import date
    today = date.today().isoformat()

    system = _merge_diff_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN

    # If article exceeds 70% of budget, apply section-based truncation. Scored
    # against every block's topics, not one source's: with several sources the
    # sections worth keeping are the ones any of them touches.
    article_budget = int(budget * 0.7)
    if len(article_content) > article_budget:
        article_content = _truncate_article_by_sections(
            article_content, _block_topics(sources), article_budget)

    user = _merge_user_message(article_content, sources, budget)

    try:
        raw = completion_json(model=model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=4096, cache=True)
    except (json.JSONDecodeError, RuntimeError):
        raw = {"patches": []}

    content, refusals = _apply_diff(article_content, raw, sources, today)
    # SG3's report. Named here because this is the layer that knows which article
    # was being written, and because an action the code throws away is the one thing
    # the arm needs counted (FA5) -- dropping it silently would make a clean column
    # indistinguishable from a writer that never tried.
    for refusal in refusals:
        _report(events, EV_SUPERSEDE_REFUSED, article_path,
                refusal.reason, refusal.anchor)
    return content


def _merge_user_message(article_content: str, sources: Sequence[SourceBlock],
                        budget_chars: int) -> str:
    header = "Existing article:\n<article>\n"
    # The paths are named as a list as well as inside each block, because
    # merge-rewrite.md asks the model to add the source to the article's
    # `sources:` list and the flattened payload handed it one string to copy.
    # Spread across N block headers, a path can go unlisted -- and a source
    # missing from `sources:` is a document `derive` then refuses to copy into a
    # derived KB (derive/_sources.py reads exactly that key). The diff path gets
    # the same guarantee in code (_apply_diff) and the create path in its own
    # header, so this is the third of three, not a new idea.
    source_list = "".join(f"  - {block.source_path}\n" for block in sources)
    footer = f"\n</article>\n\nNew information to merge.\nSources:\n{source_list}\n"
    blocks_budget = max(budget_chars - len(header) - len(article_content) - len(footer), 0)
    blocks_text = _render_blocks(sources, max(blocks_budget, 200))

    user = header + article_content + footer + blocks_text
    # Final guard: hard truncate if still over budget (extreme edge case)
    if len(user) > budget_chars:
        user = user[:budget_chars]
    return user


# One supersession trail block (A2 spec TR1): opens `[Superseded `, closes at the
# first `]`, never spans a line. Rendered by _render_trail and read back by
# _anchor_offsets, which is what makes RA5's exclusion and TR4's chaining work off
# the article text alone -- no sidecar record of what an earlier merge wrote.
#
# Known bound: a `was` containing `]` renders a block this pattern reads as
# ending early, so the tail of that one entry is not excluded from anchor
# matching. Not refused, because SG3 fixes the refusal reasons and `]` is not
# among them; the cost is bounded to a fuzzier RA5 on an entry the code wrote.
_TRAIL_RE = re.compile(r"\[Superseded [^\n\]]*\]")

# SG3's reasons, verbatim, because they are operator-facing report text.
_REFUSE_ANCHOR_MISSING = "anchor not found"
_REFUSE_ANCHOR_AMBIGUOUS = "anchor ambiguous"
_REFUSE_ANCHOR_CROSSES_ROW = "anchor spans a table row boundary"
_REFUSE_REPLACEMENT_NEWLINE_IN_ROW = "replacement contains a newline in a table row"
_REFUSE_BY_ABSENT = "by not in payload"
_REFUSE_BY_UNDATED = "by undated"
_REFUSE_NO_NEWEST = "no strictly-newest block"
_REFUSE_BY_NOT_NEWEST = "by is not the newest dated block"
_REFUSE_WAS_EMPTY = "was is empty"
_REFUSE_WAS_NEWLINE = "was contains a newline"


@dataclass(frozen=True)
class SupersedeRefusal:
    """A `supersede` action the code would not apply, for SG3's report.

    Carries no article path: ``_apply_diff`` is not told which article it is
    editing, and the layers that surface this (``_merge_diff`` on stderr, the
    compile report) both know it. ``anchor`` arrives already cut to 80 characters
    and folded onto one line -- RA7 asks for anchors long enough to be unique, so
    the whole one is not a report line, and one refusal must not print as two.
    """

    reason: str
    anchor: str


def _body_offset(content: str) -> int:
    """Where the article body starts, past any frontmatter (RA2).

    An unterminated frontmatter block counts as body, matching ``_apply_diff``'s
    own decision to leave such an article's frontmatter alone: there is no
    boundary to draw, and refusing every action on a malformed article would cost
    more than the stray match it prevents.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return sum(len(line) + 1 for line in lines[:i + 1])
    return 0


def _anchor_offsets(body: str, anchor: str) -> list[int]:
    """Offsets where ``anchor`` occurs in ``body``, skipping trail blocks (RA2, RA5).

    No normalization of any kind, per RA2: a fuzzy match is a silent edit to text
    nobody chose. Overlapping occurrences are all counted, so a self-similar
    anchor reads as ambiguous rather than as one arbitrary hit.
    """
    spans = [(m.start(), m.end()) for m in _TRAIL_RE.finditer(body)]
    offsets: list[int] = []
    start = 0
    while True:
        at = body.find(anchor, start)
        if at < 0:
            return offsets
        end = at + len(anchor)
        if not any(at < span_end and span_start < end for span_start, span_end in spans):
            offsets.append(at)
        start = at + 1


def _resolve_superseding_block(
    by: str, sources: Sequence[SourceBlock],
) -> tuple[SourceBlock | None, str | None]:
    """RA3: `by` must be in the payload, dated, and strictly newer than the rest.

    Returns the block on success so the caller reads the trail's date off the same
    lookup the guard already did -- a second search could not disagree, but it
    would be a second place that has to keep knowing `by`'s date is not None.

    The failure shapes are reported apart because they point an operator at
    different things: a payload with no strict maximum (every block undated, every
    dated block on one day, or a tie at the newest day) is WP9 saying no order
    exists, while a `by` that is dated but beaten by a single newer block is the
    writer naming the wrong document. Collapsing them into one reason would report
    the second as the first, which is false. A payload where every block is
    undated reports the more specific `by undated` rather than the absent maximum,
    because that is the one an operator can act on and FA5 breaks the counts down
    by reason.

    Vacuous on a single-block payload, which is the common case and RA3's stated
    limit: nothing here can order a block against the *article*, whose
    ``updated:`` is the compile day.
    """
    block = next((b for b in sources if b.source_path == by), None)
    if block is None:
        return None, _REFUSE_BY_ABSENT
    if block.date is None:
        return None, _REFUSE_BY_UNDATED

    others = [b.date for b in sources if b is not block and b.date is not None]
    if not any(day >= block.date for day in others):
        return block, None
    dated = [block.date] + others
    if dated.count(max(dated)) > 1:
        return None, _REFUSE_NO_NEWEST
    return None, _REFUSE_BY_NOT_NEWEST


def _line_span(body: str, start: int, end: int) -> str:
    """The whole lines that ``body[start:end]`` touches."""
    line_start = body.rfind("\n", 0, start) + 1
    line_end = body.find("\n", end)
    return body[line_start:] if line_end < 0 else body[line_start:line_end]


def _in_table_row(body: str, at: int) -> bool:
    """Whether the line holding ``at`` is a table row (TR5).

    Leading whitespace is stripped before the test: an indented row is still a
    row, and an unescaped `|` breaks its column count either way.
    """
    return _line_span(body, at, at).lstrip().startswith("|")


def _anchor_crosses_table_row(body: str, at: int, anchor: str) -> bool:
    """Whether a multi-line anchor touches a table row (TR5).

    An anchor spanning a newline deletes the boundary between the lines it
    replaces. Between prose lines that is an ordinary paragraph edit; where any of
    those lines is a table row it merges two rows into one, and the trail's single
    `was` would then stand as the record for every claim the merged rows held --
    TR5's column count and G7's record fail together. Judged on every line the
    anchor touches rather than on where it starts, because an anchor reaching from
    prose into a row corrupts the row just the same.
    """
    if "\n" not in anchor:
        return False
    region = _line_span(body, at, at + len(anchor))
    return any(line.lstrip().startswith("|") for line in region.split("\n"))


def _escape_table_cell(text: str) -> str:
    """Escape `|` so text inserted into a table row keeps the row's column count.

    Applied to both halves of what a supersession writes into a row -- the
    replacement and the trail's `was` -- because an unescaped `|` in either one
    adds a column, and D8 chose anchored replacement precisely so that the
    neighbouring cells survive.

    An already-escaped pipe is left alone. A writer copying an existing DDL cell
    hands back text that is escaped, and escaping it again gives `\\\\|`, which GFM
    reads as an escaped backslash followed by a cell delimiter -- the column break
    this exists to prevent. Known bound: a literal backslash immediately before a
    real pipe (`\\\\|` in the source) is read as an escape here and left unescaped,
    which is the same shape one level up and has no instance in the corpus.
    """
    return re.sub(r"(?<!\\)\|", r"\\|", text)


def _render_trail(day: _date, by: str, was: str, *, in_table_row: bool) -> str:
    """The trail block, per TR1 and D1's example.

    Rendered here rather than by the model, so D1's four format rules are
    mechanical: the model supplies the judgement in `was`, the format is the
    code's. ``day`` is the superseding document's own date (TR3).
    """
    if in_table_row:
        was = _escape_table_cell(was)
    return f"[Superseded {day.isoformat()} by {by}: {was}]"


# TR6's reasons, verbatim, because they are operator-facing report text.
_TRAIL_MALFORMED = "trail block is malformed"
_TRAIL_BAD_DATE = "trail date is not a date"
_TRAIL_BY_ABSENT = "trail names a source that is not in this payload"

# Where a trail block opens, and what a well-formed one looks like read back.
# Deliberately an opener plus a parse rather than one pattern: the opener finds
# every *candidate*, so a block that never closes is reported instead of skipped,
# and the parse decides whether the candidate is the shape TR1 fixes.
#
# The opener is a plain string scanned with str.find rather than a regex, and that
# is not a style choice. A regex candidate has to run to the end of the line
# (TR1 makes the block single-line, so a wrapped one is malformed rather than a
# block whose tail lives on the next line), and a greedy match then swallows every
# further block on that line -- which is exactly how TR4's chains sit, one entry
# after another on one line. finditer resumes past what it consumed, so the second
# and later entries of a chain would never be looked at.
#
# `by` is non-greedy up to the first `: ` rather than a run of non-space, because a
# source path can contain spaces: distill's _raw_rel joins the file's path parts
# verbatim, so `My Notes/design doc.md` ingests as `raw/<root>__My Notes__design
# doc.md`. A non-space `by` reported every trail _render_trail had itself written
# for such a source as malformed -- the two halves of TR6 disagreeing about the
# format while the prompt tells the writer to copy the path "exactly as it is
# listed". Taking the *first* `: ` is what lets `was` hold colons of its own.
#
# Two bounds this shares with _TRAIL_RE above, and the third declaration of the
# same format: a `was` containing `]` parses short, so the block read back here is
# a prefix of what was written, and `day` is a run of non-space, so a date with a
# space in it reads as a shape defect rather than as a date defect. Neither loses
# information -- both surface as a report either way.
_TRAIL_OPENER = "[Superseded "
_TRAIL_PARSE_RE = re.compile(
    r"^\[Superseded (?P<day>[^\s\]]+) by (?P<by>[^\]\n]+?): [^\]\n]*\]")


@dataclass(frozen=True)
class TrailDefect:
    """A trail block the rewrite path emitted that code would not have (TR6).

    Distinct from SupersedeRefusal, and the difference is the whole point of the
    asymmetry TR6 names: a refusal changed nothing, where a defect is already in
    the article and is being reported so a human can fix the prose. Rejecting it
    would lose the merge's information, which costs more than a malformed note.
    """

    reason: str
    trail: str


def _trail_defects(before: str, after: str,
                   sources: Sequence[SourceBlock]) -> list[TrailDefect]:
    """Every trail block the rewrite path added that is not well formed (TR6).

    Only blocks that are new in ``after`` are checked. TR6 read literally would
    validate every block in the output, which reports a false defect on exactly
    the case D10 designs for: v3 arriving after v2 superseded v1 leaves a
    preserved v2 entry whose ``by`` names a document the v3 payload does not
    contain. Checking what the writer *added* keeps the `by` rule meaningful
    without turning a correct chain into noise. The pre-write article is the
    second half of the comparison, and SG1 reads the same pair for its own guard.

    Three checks, in the order an operator can act on them: the bracket shape,
    then a resolvable day, then a ``by`` this payload carries. Reported apart
    because a wrong format and a wrong date point at different fixes.

    "New" is a substring test against the pre-write article, which also skips a
    *newly added duplicate* of a block already there. That is deliberate: TR6 is
    about the format of what the writer wrote, and a duplicated trail is SG1's
    question about whether the history survived intact, not this one's.

    A block whose opener is not exactly ``[Superseded `` -- ``[Superseded:``,
    ``[**Superseded**``, an opener broken across a line -- yields no candidate and
    so no report. That bound is TR1's: it fixes the block's opening as the string a
    grep over ``wiki/`` looks for, and a reader grepping for the trail would miss
    those the same way.
    """
    known = {block.source_path for block in sources}
    defects: list[TrailDefect] = []

    def defect(reason: str, text: str) -> TrailDefect:
        """Cut to 80 characters in one place, as ``_apply_supersede``'s ``refuse``
        does. No whitespace folding is needed here where SG3's anchors need it: the
        candidate is already bounded by its own line, so it holds no newline."""
        return TrailDefect(reason=reason, trail=text[:80])

    at = after.find(_TRAIL_OPENER)
    while at >= 0:
        line_end = after.find("\n", at)
        candidate = after[at:] if line_end < 0 else after[at:line_end]
        parsed = _TRAIL_PARSE_RE.match(candidate)
        # The block as it stands, cut to the parse where there is one: a candidate
        # runs to the end of its line, so an entry with a chained one or plain
        # prose after it would otherwise report that text as part of the block.
        block_text = parsed.group(0) if parsed else candidate
        if block_text not in before:
            if parsed is None:
                defects.append(defect(_TRAIL_MALFORMED, block_text))
            elif as_day(parsed.group("day")) is None:
                defects.append(defect(_TRAIL_BAD_DATE, block_text))
            elif parsed.group("by") not in known:
                defects.append(defect(_TRAIL_BY_ABSENT, block_text))
        at = after.find(_TRAIL_OPENER, at + len(_TRAIL_OPENER))
    return defects


# SG1's reason, verbatim, because it is operator-facing report text.
_TRAIL_LOST = "pre-existing trail missing from the rewrite"

# What the retry adds to the prompt the first attempt already saw. Fixed text kept
# well inside _SAFETY_MARGIN (pinned by a test), because the first send is sized to
# the budget minus that margin and anything past it raises PromptTooLargeError --
# which would lose the history to a crash rather than to the guard SG1 designed.
#
# It restates the constraint rather than relying on the prompt file's own version
# of it, and merge-rewrite.md landed that rule a step early for this reason: a
# retry is the second time the model is told, not the first.
#
# Phrased as a requirement rather than as feedback on the rejected draft, because
# the draft is not sent back: the retry appends to the first attempt's messages and
# nothing else, so text about "what you dropped" would name an artifact this
# conversation does not contain. Carrying the draft would cost a whole article of
# budget to say what the list of notes below already says.
_TRAIL_RETRY_HEAD = (
    "The article you return has to contain every [Superseded ...] note listed "
    "below, word for word, alongside everything you merged. The article's history "
    "is append-only: these are notes it already carried.\n\n"
)
_TRAIL_RETRY_TAIL = "\nReturn the complete updated article.\n"


def _lost_trails(before: str, after: str) -> list[str]:
    """Every trail block in ``before`` that ``after`` does not carry verbatim (SG1).

    Verbatim is the only grain a code guard has, and the spec says so rather than
    implying more: a rewrite that paraphrases a preserved note trips this, and the
    cost of that is one wasted retry, never a silent loss. What it cannot promise
    is the converse -- a note kept in a section the rewrite otherwise gutted still
    reads as preserved here.

    Two bounds worth naming. A pre-existing block that does not close on its own
    line is not a block by TR1's definition, so it yields no match and is not
    guarded -- the same bound a reader grepping ``wiki/`` for the trail lives with.
    And the test is substring presence, so an article carrying one block twice is
    satisfied by an output that keeps one of them: duplicates are deduplicated here
    to report a loss once, which is also why collapsing them cannot be detected.
    """
    carried = dict.fromkeys(_TRAIL_RE.findall(before))
    return [block for block in carried if block not in after]


def _trail_retry_note(missing: Sequence[str], room: int) -> str:
    """SG1's retry message: the constraint restated, and the blocks to bring back.

    ``room`` is what the budget left after the first send, and the list is cut to
    fit it: naming five long blocks costs more than _SAFETY_MARGIN reserved. The
    constraint is restated whether or not a single block fits beside it, and the
    report names every missing block regardless -- the prompt is one call's worth,
    where the report is the whole loss.
    """
    room -= len(_TRAIL_RETRY_HEAD) + len(_TRAIL_RETRY_TAIL)
    listed: list[str] = []
    for block in missing:
        room -= len(block) + 1
        if room < 0:
            break
        listed.append(block)
    return _TRAIL_RETRY_HEAD + "\n".join(listed) + _TRAIL_RETRY_TAIL


def _apply_supersede(content: str, patch: dict,
                     sources: Sequence[SourceBlock]) -> tuple[str, SupersedeRefusal | None]:
    """Apply one `supersede` patch, or refuse it and change nothing (RA1-RA5).

    Every refusal is a no-op on the whole action: the article keeps every byte it
    had (story S9). The trail goes at the anchor's position, immediately after the
    replacement in the same line and section (TR2) or alone there when the claim is
    withdrawn rather than restated. That placement is also what makes TR4 fall out
    -- an existing trail sits just past the anchor, so the new entry lands ahead of
    it and the entries read newest to oldest.

    One consequence of RA5 worth naming: a position holding only trail blocks is
    unreachable by any later ``supersede``, because anchor matching excludes trail
    text. A withdrawn claim is therefore final on this path, and a further
    supersession of it reports `anchor not found` rather than chaining.
    """
    anchor = patch.get("anchor") or ""
    replacement = patch.get("replacement") or ""
    by = patch.get("by") or ""
    was = patch.get("was") or ""

    def refuse(reason: str) -> tuple[str, SupersedeRefusal]:
        return content, SupersedeRefusal(reason=reason, anchor=" ".join(anchor[:80].split()))

    if "\n" in was:
        return refuse(_REFUSE_WAS_NEWLINE)
    # `was` is the required field, not `replacement`. An empty `replacement` is a
    # deletion the trail makes recoverable, which RA1 allows; an empty `was` is a
    # deletion of the record itself, and G7 is the whole reason D1 chose a trail
    # over a deletion. So the field that carries the old value is the one that
    # cannot be left out -- with both empty the claim would leave the article with
    # nothing saying it was ever there. Tested on .strip(), because the guard is
    # about the record and a `was` that renders as blank is not one.
    if not was.strip():
        return refuse(_REFUSE_WAS_EMPTY)
    block, violation = _resolve_superseding_block(by, sources)
    if violation is not None:
        return refuse(violation)
    # An empty anchor names no text, and str.find would report it at every offset.
    # Reported as not found rather than earning a reason of its own.
    if not anchor:
        return refuse(_REFUSE_ANCHOR_MISSING)

    offset = _body_offset(content)
    body = content[offset:]
    offsets = _anchor_offsets(body, anchor)
    if not offsets:
        return refuse(_REFUSE_ANCHOR_MISSING)
    if len(offsets) > 1:
        return refuse(_REFUSE_ANCHOR_AMBIGUOUS)

    at = offsets[0]
    if _anchor_crosses_table_row(body, at, anchor):
        return refuse(_REFUSE_ANCHOR_CROSSES_ROW)

    in_row = _in_table_row(body, at)
    if in_row:
        # TR5 covers everything this action writes into the row, not only the
        # trail: a `|` in the replacement adds a column exactly as one in `was`
        # does. A newline has no escape -- it splits the row into two -- and
        # outside a row a multi-line replacement is ordinary prose, so this is the
        # one refusal that depends on where the anchor turned out to be.
        if "\n" in replacement:
            return refuse(_REFUSE_REPLACEMENT_NEWLINE_IN_ROW)
        replacement = _escape_table_cell(replacement)

    trail = _render_trail(block.date, by, was, in_table_row=in_row)
    # An empty replacement leaves the trail alone in the claim's place: a deletion
    # with a record, which is what RA1 allows it to mean.
    inserted = f"{replacement} {trail}" if replacement else trail
    return content[:offset] + body[:at] + inserted + body[at + len(anchor):], None


def _apply_diff(article_content: str, diff: dict, sources: Sequence[SourceBlock],
                today: str) -> tuple[str, list[SupersedeRefusal]]:
    """Frontmatter refresh, then the patches, and what the patches refused.

    ``sources`` is the payload's blocks rather than their paths, because RA3's
    order guard reads their dates and two representations of one payload could
    disagree about which document is newest. A bare ``str`` passed here fails
    loudly on the first ``.source_path``, where the previous ``list[str]``
    signature would have appended one frontmatter item per character.
    """
    source_paths = [block.source_path for block in sources]
    lines = article_content.split("\n")

    if lines and lines[0].strip() == "---":
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx:
            fm_lines = lines[1:end_idx]
            # Scope note: this collects every "  - " item in the frontmatter, not
            # only the ones under sources:. A same-named item under another list
            # key would suppress the source append. create_new_article emits
            # flow-style tags, so no other key produces "  - " items today.
            existing_sources = {fl.strip() for fl in fm_lines if fl.startswith("  - ")}
            # One line per source, where the flattened payload wrote a single
            # comma-joined item ("  - raw/a.md, raw/b.md") that no YAML reader
            # resolves back to a list of paths. Compared normalized on both sides
            # -- existing_sources is stripped, so an indented line never matches
            # -- and deduplicated among themselves, since a duplicate item in an
            # article's frontmatter is written once and read forever.
            new_sources = list(dict.fromkeys(
                f"  - {p}" for p in source_paths if f"- {p}" not in existing_sources))
            new_fm = []
            found_updated = False
            found_sources = False
            for fm_idx, fl in enumerate(fm_lines):
                if fl.startswith("updated:"):
                    new_fm.append(f"updated: {today}")
                    found_updated = True
                elif fl.startswith("sources:"):
                    found_sources = True
                    new_fm.append(fl)
                elif found_sources and fl.startswith("  - "):
                    new_fm.append(fl)
                    next_is_source = (fm_idx + 1 < len(fm_lines) and fm_lines[fm_idx + 1].startswith("  - "))
                    if not next_is_source:
                        new_fm.extend(new_sources)
                        found_sources = False
                else:
                    if found_sources:
                        new_fm.extend(new_sources)
                        found_sources = False
                    new_fm.append(fl)
            if found_sources:
                new_fm.extend(new_sources)
            if not found_updated:
                new_fm.append(f"updated: {today}")
            lines = ["---"] + new_fm + lines[end_idx:]

    content = "\n".join(lines)
    patches = diff.get("patches", [])
    refusals: list[SupersedeRefusal] = []

    # RA4: every supersede runs before any additive action, against the article
    # text the anchors were chosen against. An append_to_section applied first can
    # create text an anchor then matches, or move the text an anchor was cut from.
    # Within the group, emission order -- _apply_diff's existing rule.
    for patch in patches:
        if patch.get("action") == "supersede":
            content, refusal = _apply_supersede(content, patch, sources)
            if refusal is not None:
                refusals.append(refusal)

    for patch in patches:
        action = patch.get("action")
        new_content = patch.get("content", "")
        if action == "append_to_section":
            section = patch.get("section", "")
            content = _append_to_section(content, section, new_content)
        elif action == "new_section":
            after = patch.get("after", "")
            heading = patch.get("heading", "")
            content = _insert_section_after(content, after, heading, new_content)

    return content, refusals


def _append_to_section(content: str, section_heading: str, new_content: str) -> str:
    lines = content.split("\n")
    section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == section_heading.strip():
            section_idx = i
            break

    if section_idx is None:
        return content.rstrip() + f"\n\n{section_heading}\n\n{new_content}\n"

    heading_level = len(section_heading) - len(section_heading.lstrip("#"))
    insert_before = len(lines)
    for i in range(section_idx + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= heading_level:
                insert_before = i
                break

    lines.insert(insert_before, new_content + "\n")
    return "\n".join(lines)


def _insert_section_after(content: str, after_heading: str, new_heading: str, new_content: str) -> str:
    lines = content.split("\n")
    after_idx = None
    for i, line in enumerate(lines):
        if line.strip() == after_heading.strip():
            after_idx = i
            break

    if after_idx is None:
        return content.rstrip() + f"\n\n{new_heading}\n\n{new_content}\n"

    heading_level = len(after_heading) - len(after_heading.lstrip("#"))
    insert_at = len(lines)
    for i in range(after_idx + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= heading_level:
                insert_at = i
                break

    section_block = f"\n{new_heading}\n\n{new_content}\n"
    lines.insert(insert_at, section_block)
    return "\n".join(lines)


_SECTION_TEMPLATES = {
    "concept": "Suggested sections: Overview, Details, Examples, Related Concepts",
    "project": "Suggested sections: Overview, Status, Key Decisions, Team, Related",
    "decision": "Suggested sections: Background, Decision, Rationale, Related Decisions",
    "person": "Suggested sections: Role, Key Contributions, Collaboration Context",
}


# Stands in for any article type with no template of its own, so
# write_prompt_version() hashes _section_guidance's fallback branch too. Not a
# real type: it only has to miss every key in _SECTION_TEMPLATES.
_UNTEMPLATED_TYPE = "_untemplated"


def _section_guidance(article_type: str) -> str:
    template = _SECTION_TEMPLATES.get(article_type)
    if template:
        return f'Article type: "{article_type}"\n{template}'
    return f'Article type: "{article_type}"\nChoose appropriate sections for this type of article.'


def _strip_markdown_fencing(text: str) -> str:
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return text


def _write_stage_renderings() -> list[tuple[str, str]]:
    """Every *system* prompt the write phase sends, as it now renders.

    Three sources, not two. merge-rewrite and merge-diff are prompt files; the
    article creator's system prompt is built in code and varies by article type,
    so a hash over the files alone would leave it a blind spot -- the same trap
    B11 covers on the extraction side.

    The user messages are deliberately out: create_new_article's user_header and
    _merge_user_message's <article> framing are scaffolding around per-run data,
    and extract_prompt_version draws the same line (it hashes the extract prompts,
    not extract_knowledge's own "<document>" wrapper). Editing that scaffolding
    moves no hash, which is a known limit of both versions rather than an
    oversight in this one.

    The article types are enumerated from _SECTION_TEMPLATES rather than mirrored
    in a second list, so a new type is covered the moment it is added. The
    sentinel covers _section_guidance's fallback branch, which is what the two
    DEFAULT_CATEGORIES entries with no template of their own (reference, guide)
    are actually sent.
    """
    out = [("merge-rewrite", _merge_rewrite_system()),
           ("merge-diff", _merge_diff_system())]
    for article_type in sorted(_SECTION_TEMPLATES) + [_UNTEMPLATED_TYPE]:
        out.append((f"create-new#{article_type}", _create_system(article_type)))
    return out


@functools.lru_cache(maxsize=1)
def write_prompt_version() -> str:
    """12 hex digits over the write stage's prompt set as it now renders.

    The counterpart of extract_prompt_version, and deliberately a separate value:
    a write-prompt edit must not move the extraction's version, or every document
    would re-extract at full cost over a prompt extraction never used.

    Reported, never gated (spec D5, PV1, NG12) -- and the reason for that changed
    with A2, so it is restated rather than carried. It used to be that gating bought
    nothing: both merge paths were additive, so a re-composition layered new content
    on top of the old and could not correct anything. That argument is now false.
    merge-diff.md offers `supersede` and merge-rewrite.md states the trail rule, so
    a re-composition can retract a claim, and a gate would be the thing that gets
    the 682 existing articles corrected.

    What holds it back is cost and blast radius, not futility: a prompt edit would
    re-compose the whole wiki through the full write phase, and every article it
    touched would be rewritten by a model with a new action and no measurement
    behind it yet. Which is why NG12 leaves that to path C's decision instead of
    letting a hash change trigger it. The value's own job is unchanged -- it says
    which articles are behind, and nothing acts on the answer.

    Every prompt edit in this feature moves the value for every existing KB, so the
    first report after each upgrade names every article: A1's source-order block
    (_SOURCE_ORDER, WP6) did it once and A2's two prompt files do it again (PV4).
    That is noise rather than spend, because nothing acts on it.

    Memoized for the same reason as its extraction counterpart (B12): the registry
    caches lazily per name, so a long-lived daemon could otherwise hold
    merge-rewrite from before an edit and merge-diff from after it.

    Name and content are framed with a length prefix and a NUL separator, so a
    trailing newline in one prompt cannot collide with the next name.
    """
    h = hashlib.sha256()
    for name, text in _write_stage_renderings():
        body = text.encode("utf-8")
        h.update(f"{len(name)}\0{name}\0{len(body)}\0".encode("utf-8"))
        h.update(body)
        h.update(b"\0")
    return h.hexdigest()[:12]


def _create_system(article_type: str) -> str:
    """The article creator's system prompt for one article type.

    Its own function rather than an f-string inside create_new_article so that
    write_prompt_version() can hash the text the model is actually sent. Inline,
    it was the write phase's blind spot: editing this prompt invalidated nothing
    and no hash could see it.
    """
    status_line = "\nstatus: active" if article_type == "project" else ""

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
{_GROUNDING}{_SOURCE_ORDER}

The `summary` line is the article's entry in the knowledge-base catalog, which is
the only surface a reader searches before opening anything. Write one sentence
under 150 characters naming the specific things covered here — subsystems, key
parameters, decisions — not a restatement of the title.

The `sources:` list carries every path given under `- Sources:` above,
one item per path — the template shows a single item because that is the shape of
an item, not the count. A source left out of that list is a document no derived
knowledge base will copy.

Use [[wikilinks]] for references to related concepts.
Return the complete article including frontmatter."""


@_with_write_timeout
def create_new_article(
    article_type: str,
    title: str,
    sources: Sequence[SourceBlock],
    model: str = "claude-sonnet-4-6",
) -> str:
    """Compose a new article from ``sources``.

    Same ordering expectation as ``merge_into_article``: oldest to newest, undated
    last, as ``build_source_blocks`` returns them (WP5), because the system prompt
    states that order to the model (_SOURCE_ORDER).
    """
    today = _date.today().isoformat()

    system = _create_system(article_type)

    # Rendered as a YAML list rather than the comma-joined string the flattened
    # payload sent, because the frontmatter format in the system prompt asks for
    # a list and one item holding "raw/a.md, raw/b.md" is not one. Every source is
    # named here as well as in its own block: the blocks are the knowledge, and
    # this is the frontmatter the article is required to carry.
    source_list = "\n".join(f"  - {block.source_path}" for block in sources)
    user_header = f"""Create article:
- Title: {title}
- Type: {article_type}
- Sources:
{source_list}
- Created/Updated: {today}
- Tags: {_block_topics(sources)}

Knowledge to include:
"""
    budget = MAX_PROMPT_CHARS - len(system) - len(user_header) - _SAFETY_MARGIN
    user = user_header + _render_blocks(sources, max(budget, 200))

    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=16384, cache=True).strip()
    return _strip_markdown_fencing(text)
