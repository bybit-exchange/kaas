from __future__ import annotations

import functools
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from typing import Callable, Sequence

from kb_ai._frontmatter import read_document_frontmatter
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


def _as_day(value: object) -> _date | None:
    """Narrow whatever YAML resolved a ``date`` key to into a day, or None.

    Three shapes arrive from real documents, because the submit route has no YAML
    parser and cannot tell a date from a string that looks like one (spec RT10),
    so it preserves what it was given and this is where it is resolved (WP8):
    ``datetime.date`` for a plain ISO day, ``datetime.datetime`` for a stamp, and
    ``str`` for a quoted one.

    Stamps are narrowed to their day rather than kept, because ``datetime`` is a
    subclass of ``date`` that refuses to be compared with one: a corpus holding
    both kinds -- which the reference KB does -- raises TypeError the moment the
    two end up in one sort key. Sub-day ordering is the cost, and version chains
    are days or weeks apart.

    Anything else is None, which sorts the block with the undated ones instead of
    inventing a day the document never claimed: ``date: 2020`` is an int to YAML,
    and reading it as January 1st is a fabricated ordering signal.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            return None
    return None


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
    return _as_day(frontmatter.get("date"))


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
    ordering that varied per run would make the payload unreproducible.
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
    system prompt states that blocks run oldest to newest and that an undated
    source's position carries no ordering claim (WP6), and a rendered "unknown"
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

    Per block, because the question is whether every source can contribute
    something, not whether one of them can.
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


def _render_blocks(blocks: Sequence[SourceBlock], budget_chars: int) -> str:
    """Render blocks in order, sharing budget_chars between them.

    When every block fits whole, each one is simply rendered whole: there is no
    allocation to make, and splitting an adequate budget evenly is loss for
    nothing -- a block over its share would be truncated against a remainder the
    carry can never flow backwards to reach, and the first field truncation drops
    is enumerations, the one field it cannot degrade gracefully (issue #41).

    Only when they do not all fit is the budget divided: each block gets an equal
    share of what is left, and whatever it does not use rolls on to the next -- so
    one block cannot starve the others, and a single block still gets the whole
    budget, which is what every single-source call site sends.

    An interim policy, and known to be the wrong one for supersession: BG1
    allocates newest block first, because filling in render order truncates the
    *newest* source when the budget runs out, which is precisely backwards. BG1's
    priority, whole-block drops (BG2) and a notice naming the dropped source
    (BG3) land together in the budget step.

    Empty renderings contribute no separator, so a budget too small for any block
    yields "" rather than a run of blank lines over budget.
    """
    # The separators are part of what the caller's budget has to cover: three
    # blocks that each fit exactly would otherwise overrun it by two.
    remaining = budget_chars - (len(blocks) - 1)
    fits_whole = sum(_estimate_block_size(block) for block in blocks) <= remaining
    parts: list[str] = []
    left = len(blocks)
    for block in blocks:
        share = remaining if (fits_whole or left == 1) else max(remaining // left, 0)
        text = _fit_block_to_budget(block, share)
        parts.append(text)
        remaining -= len(text)
        left -= 1
    return "\n".join(part for part in parts if part)


def _fit_block_to_budget(block: SourceBlock, budget_chars: int) -> str:
    """Build one block's text fitting within budget_chars.

    Fields are added in priority order. List fields use exponential backoff
    (halving item count) when full content exceeds remaining budget.
    """
    extraction = block.extraction
    source_path = block.source_path
    prefix = _block_header(block)
    if budget_chars <= len(prefix):
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


def _merge_rewrite_system() -> str:
    """The rewrite path's system prompt, file plus grounding constraint.

    One function for the three callers that need it -- the budget calculation in
    merge_into_article, the send in _merge_full_rewrite, and the hash in
    _write_stage_renderings. Composed rather than sent verbatim, so a budget
    computed from the file alone would under-reserve by the grounding block and a
    hash over the file alone would not move when that block is edited.
    """
    return default_registry().get("merge-rewrite").render() + "\n" + _GROUNDING


def _merge_diff_system() -> str:
    """The diff path's system prompt, file plus grounding constraint.

    .content, not .render(): merge-diff.md holds literal `{...}` JSON example
    braces, which str.format would read as placeholders.
    """
    return default_registry().get("merge-diff").content + "\n" + _GROUNDING


@_with_write_timeout
def merge_into_article(
    article_path: str,
    article_content: str,
    sources: Sequence[SourceBlock],
    model: str = "claude-sonnet-4-6",
) -> str:
    if len(article_content.encode("utf-8")) >= _LARGE_ARTICLE_THRESHOLD:
        return _merge_diff(article_path, article_content, sources, model)

    # Budget-aware: check if full rewrite fits.
    # Registry caches per-process, so this call here + same call inside
    # _merge_full_rewrite both hit the cache after the first lookup.
    full_rewrite_system = _merge_rewrite_system()
    budget = MAX_PROMPT_CHARS - len(full_rewrite_system) - _SAFETY_MARGIN
    if len(article_content) + _min_blocks_chars(sources) > budget:
        return _merge_diff(article_path, article_content, sources, model)

    return _merge_full_rewrite(article_path, article_content, sources, model)


def _merge_full_rewrite(
    article_path: str, article_content: str,
    sources: Sequence[SourceBlock], model: str,
) -> str:
    system = _merge_rewrite_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN
    user = _merge_user_message(article_content, sources, budget)

    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=16384, cache=True).strip()
    return _strip_markdown_fencing(text)


def _merge_diff(
    article_path: str, article_content: str,
    sources: Sequence[SourceBlock], model: str,
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

    return _apply_diff(article_content, raw, [b.source_path for b in sources], today)


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


def _apply_diff(article_content: str, diff: dict, source_paths: list[str],
                today: str) -> str:
    # list[str] rather than Sequence[str]: a bare `str` satisfies the wider type
    # and would append one frontmatter item per character, to a file that is then
    # written to disk and read back by derive as one source path per character.
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

    for patch in diff.get("patches", []):
        action = patch.get("action")
        new_content = patch.get("content", "")
        if action == "append_to_section":
            section = patch.get("section", "")
            content = _append_to_section(content, section, new_content)
        elif action == "new_section":
            after = patch.get("after", "")
            heading = patch.get("heading", "")
            content = _insert_section_after(content, after, heading, new_content)

    return content


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

    Reported, never gated. Both merge paths are additive -- merge-diff.md offers
    only append_to_section and new_section, and merge-rewrite.md says nothing
    about supersession -- so re-composing an article layers new content on top of
    the old rather than replacing it. Feeding this into the composition gate would
    inflate every article on a prompt edit and pay the full write phase to do it.
    Until a supersession path exists, an operator reading the count is the useful
    thing.

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
{_GROUNDING}

The `summary` line is the article's entry in the knowledge-base catalog, which is
the only surface a reader searches before opening anything. Write one sentence
under 150 characters naming the specific things covered here — subsystems, key
parameters, decisions — not a restatement of the title.

Use [[wikilinks]] for references to related concepts.
Return the complete article including frontmatter."""


@_with_write_timeout
def create_new_article(
    article_type: str,
    title: str,
    sources: Sequence[SourceBlock],
    model: str = "claude-sonnet-4-6",
) -> str:
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
