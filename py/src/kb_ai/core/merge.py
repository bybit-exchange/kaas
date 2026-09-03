from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from kb_ai._context import adopt_context, get_context
from kb_ai.core.extract import ExtractionResult
from kb_ai.llm import (
    MAX_PROMPT_CHARS,
    DeadlineExceededError,
    EmptyCompletionError,
    OutputTruncatedError,
    completion,
    completion_json,
    emit_alert,
    estimate_max_tokens,
    get_call_timeout,
    set_call_timeout,
)
from kb_ai.prompts import default_registry

_SAFETY_MARGIN = 500

# The framing _merge_user_message wraps the existing article in, and the tag a
# rewrite sometimes echoes back into its output. One pair of constants so the
# framing and _strip_article_wrapper cannot drift apart.
_ARTICLE_OPEN = "<article>"
_ARTICLE_CLOSE = "</article>"

# Per-call timeout for the write phase, mirroring extract's override. Without one
# a write inherits DEFAULT_CLIENT_TIMEOUT_S, and a gateway that hangs on a 6-8K
# prompt then costs 15 minutes to discover -- three derive runs each lost roughly
# that to a single stalled call (issue #26).
#
# Sized above extract's 180s because a merge prompt carries the whole existing
# article on top of the extraction, and below the client default, because that is
# the number it exists to replace: at DEFAULT_CLIENT_TIMEOUT_S a stalled write costs
# 3*900+30 = 2730s to discover, so this buys back 1800s of that.
#
# _WRITE_TIMEOUT_ENV is honoured verbatim, including past DEFAULT_CLIENT_TIMEOUT_S.
# The client timeout is a default, not a ceiling -- _completion.py applies an override
# with client.with_options(timeout=...), which replaces the value rather than clamping
# it, so an operator who needs 1200 gets 1200.
#
# Calibrated on one cloud reference run (docs/articles/kaas-bootstrap-case-study:
# 48 article groups, 16 workers) that spent 255.27s on the *entire* write phase, so
# no single call in it came close. That is the regime this default serves.
#
# A local model is a different regime, and 300 is too small for it. qwen3.8:27b-mlx
# generates at roughly 23 output tok/s against roughly 540 tok/s of prefill, and a
# merge emits the whole rewritten article, so latency tracks the article's size
# rather than the prompt's. Measured on that model, all three under one load
# condition -- which turns out to matter, see below:
#
#   9 sources into a 6101-char article -> 29024 chars   348.8s
#   4 sources into a 6101-char article -> 18245 chars   257.9s
#   5 sources into an 18245-char one   -> 34981 chars   507.7s
#
# The first of those exceeded this cap and cost a derive run nine documents'
# content. The default still does not move, for three reasons.
#
# It is not free: a timeout is retried, so at _TIMEOUT_RETRIES=2 plus backoff a hung
# gateway costs 3*300+30 = 930s to discover here, and every 300s added to the default
# adds 900s to that.
#
# No constant fixes the local case anyway. These calls are allowed 16384 output
# tokens (see the max_tokens below), which at 23 tok/s is ~712s, and a derive-merged
# article only grows. Worse, throughput is not a property of the model: the same
# 9-source call measured at 348.8s above needed more than 900s when a second model
# was sharing the GPU, a 2.4x swing on one machine. A number that fits today is
# outrun by tomorrow's article or by tomorrow's co-tenant.
#
# And the retry is doing real work, so shortening the budget to fail faster would be
# the wrong trade. The same call that exceeded a 900s budget twice succeeded on the
# third attempt with an unchanged prompt: a write timeout here is throughput-driven,
# not a deterministic function of prompt size, so an identical retry genuinely can
# land.
#
# So the local case is carried by _WRITE_TIMEOUT_ENV rather than by a number
# extrapolated from three calls under one load. README.md says how to size it.
#
# Known bound: completion() retries a truncated response with max_tokens doubled,
# and a write escalated past its 16384 default could plausibly need longer than
# this. No run has produced one -- an article that overruns 16K output tokens is
# already pathological -- so this is not scaled per attempt until one shows up.
_WRITE_CALL_TIMEOUT_S = 300.0
_WRITE_TIMEOUT_ENV = "KB_AI_WRITE_TIMEOUT_S"


@functools.lru_cache(maxsize=1)
def _warn_unusable_write_timeout(raw: str) -> None:
    """Report an ignored override once, not once per write call.

    Keyed on the raw string, matching _cost.py's handling of KB_AI_PRICING, so a
    corrected value is reported afresh rather than swallowed by the cache.
    """
    print(f"[write] ignoring {_WRITE_TIMEOUT_ENV}={raw!r}: expected a positive "
          f"number of seconds — using {_WRITE_CALL_TIMEOUT_S}", file=sys.stderr)


def _write_call_timeout() -> float:
    """The per-call write timeout, re-read on every write entry.

    Read per call rather than at import like the neighbouring MAX_PROMPT_CHARS, so
    that setting the variable does not have to happen before kb_ai is imported.
    Under the Go bridge the two are indistinguishable -- it snapshots the
    environment when it spawns the daemon -- so the difference shows up for a
    direct caller and for the tests.

    A value that cannot serve as a timeout is reported and ignored rather than
    honoured: '0' or a negative would fail every write call instantly, and a
    non-finite one would silently remove the cap this override exists to impose.
    Failing a whole compile over a typo in an env var is the worse outcome, and
    saying nothing would leave the typo looking like it took effect.
    """
    raw = os.environ.get(_WRITE_TIMEOUT_ENV, "")
    if not raw:
        return _WRITE_CALL_TIMEOUT_S
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if seconds > 0 and math.isfinite(seconds):
        return seconds
    _warn_unusable_write_timeout(raw)
    return _WRITE_CALL_TIMEOUT_S


def _with_write_timeout(fn):
    """Apply the write-phase call timeout to all LLM calls within fn.

    On the entry points rather than on their callers, so that every write path
    reaching them is covered: both compile_kb's write phase and the pipeline's
    run_write_phase, and anything added later.

    Restoring to prev (not None) keeps nested invocations safe, matching
    extract's _with_extract_timeout.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        prev = get_call_timeout()
        set_call_timeout(_write_call_timeout())
        try:
            return fn(*args, **kwargs)
        finally:
            set_call_timeout(prev)
    return wrapper


# Order is survival order under a tight budget: _fit_extraction_to_budget adds
# fields from the top and halves a list that does not fit.
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


def _estimate_full_extraction_size(extraction: ExtractionResult, source_path: str) -> int:
    """Estimate full untruncated character count of extraction text."""
    size = len(f"- Source: {source_path}\n")
    for field_name, field_type in _FIELD_PRIORITY:
        value = getattr(extraction, field_name, None)
        # Skip falsy the same way _fit_extraction_to_budget does, otherwise the
        # estimate counts lines the output never emits and every merge would
        # report a truncation that never happened.
        if not value:
            continue
        if field_type == "str":
            size += len(f"- {field_name.replace('_', ' ').title()}: {value}\n")
        else:
            size += len(f"- {field_name.replace('_', ' ').title()}: {json.dumps(value, ensure_ascii=False)}\n")
    return size


def _fit_extraction_to_budget(
    extraction: ExtractionResult, source_path: str, budget_chars: int
) -> str:
    """Build extraction text fitting within budget_chars.

    Fields are added in priority order. List fields use exponential backoff
    (halving item count) when full content exceeds remaining budget.
    """
    prefix = f"- Source: {source_path}\n"
    if budget_chars <= len(prefix):
        return prefix[:budget_chars] if budget_chars > 0 else ""

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
    full_size = _estimate_full_extraction_size(extraction, source_path)
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


# Articles at or above this many UTF-8 bytes merge via the diff path instead of
# a full rewrite. This is the *default* of the configurable threshold below --
# deployments lower it through KB_MERGE_FULL_REWRITE_LIMIT (recommended 12000
# for hot, large-article KBs; see the distillation-throughput plan), never by
# editing code. Keeping the shipped default unchanged is deliberate: a lower
# threshold shifts merges onto the diff path, a quality/latency tradeoff that
# belongs to the operator, not to a release.
#
# Scope: in auto mode the section-merge path sits AHEAD of this threshold for
# articles that fit the prompt budget (its degraded fallback is the diff leg,
# which this threshold selects). An operator who wants at-or-above-threshold
# articles on the diff path unconditionally sets KB_MERGE_SECTION_MODE=off,
# which restores exactly the pre-section dispatch.
_LARGE_ARTICLE_THRESHOLD = 30_000


def _full_rewrite_limit() -> int:
    """The UTF-8 byte threshold at or above which merge_into_article takes the
    diff path: KB_MERGE_FULL_REWRITE_LIMIT when it holds a valid positive
    integer, else the shipped default. An invalid value warns on stderr and
    falls back to the default rather than raising -- a typo in an env var must
    not take down the write phase.

    In auto mode the section-merge path runs AHEAD of this threshold for
    articles that fit the prompt budget (see _LARGE_ARTICLE_THRESHOLD); this
    threshold then selects the section path's own degraded fallback.
    KB_MERGE_SECTION_MODE=off restores its unconditional "at or above → diff"
    routing.
    """
    raw = os.environ.get("KB_MERGE_FULL_REWRITE_LIMIT")
    if not raw:
        return _LARGE_ARTICLE_THRESHOLD
    try:
        limit = int(raw)
    except ValueError:
        limit = None
    if limit is None or limit <= 0:
        print(
            f"[merge] invalid KB_MERGE_FULL_REWRITE_LIMIT={raw!r}, "
            f"using default {_LARGE_ARTICLE_THRESHOLD}",
            file=sys.stderr,
            flush=True,
        )
        return _LARGE_ARTICLE_THRESHOLD
    return limit


# Articles at or above this many UTF-8 bytes qualify for the section-level merge
# path: a tiny router call decides which sections the extraction touches, only
# those sections are rewritten, and the rest of the article is carried through
# byte-identical. Below this size a full rewrite costs less than the router call
# it would take to decide -- a code constant for the same reason as
# _LARGE_ARTICLE_THRESHOLD: it is a cost/quality tradeoff the release ships a
# default for, not an operator choice.
_SECTION_MERGE_MIN_BYTES = 12_000

# The section path's rollback knob: "off" restores the pre-section dispatch
# exactly, so a misbehaving layer can be disabled without reverting the others.
_SECTION_MERGE_MODE_ENV = "KB_MERGE_SECTION_MODE"


@functools.lru_cache(maxsize=1)
def _warn_invalid_section_merge_mode(raw: str) -> None:
    """Report an ignored _SECTION_MERGE_MODE value once, not once per read.

    Keyed on the raw string, matching _warn_unusable_write_timeout, so a
    corrected value is reported afresh rather than swallowed by the cache.
    """
    print(f"[merge] invalid {_SECTION_MERGE_MODE_ENV}={raw!r}: expected 'auto' or "
          f"'off' — using auto", file=sys.stderr, flush=True)


def _section_merge_enabled() -> bool:
    """Whether the section-merge path may run: auto (the default) or off.

    An invalid value warns once and falls back to auto rather than raising --
    the _full_rewrite_limit() rule that a typo in an env var must not take down
    the write phase, and must not silently look like it took effect either.
    """
    raw = os.environ.get(_SECTION_MERGE_MODE_ENV, "")
    if raw == "off":
        return False
    if raw and raw != "auto":
        _warn_invalid_section_merge_mode(raw)
    return True


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


def _merge_section_router_system() -> str:
    """The section router's system prompt, file plus grounding constraint.

    .content for the same brace reason as _merge_diff_system:
    merge-section-router.md holds a literal `{...}` JSON output example, which
    str.format would read as placeholders.
    """
    return default_registry().get("merge-section-router").content + "\n" + _GROUNDING


def _merge_section_system() -> str:
    """The per-section rewrite prompt, file plus grounding constraint.

    .content for the same brace reason, preemptively: the file is plain
    instructions today, and the hazard arrives the moment an output example is
    added to it.
    """
    return default_registry().get("merge-section").content + "\n" + _GROUNDING


# The section path fans one merge out into many small LLM calls (router, section
# rewrites, new-section bodies). At pipeline_batch_max_inflight=2 that is the one
# place the write phase could multiply its concurrent calls several-fold, and 429
# is not in the retryable set -- so every section-path LLM call runs under one
# process-wide semaphore. 12 keeps the process's worst case at roughly today's
# level plus one article's worth of fan-out.
_SECTION_MERGE_MAX_CONCURRENT = 12
_SECTION_CONCURRENCY_ENV = "KB_MERGE_SECTION_MAX_CONCURRENT"

# The per-merge thread-pool cap. The semaphore bounds the process; this bounds
# one article's share of it, so a 20-section article cannot monopolize all the
# permits while other articles' merges wait.
_SECTION_POOL_CAP = 4

# Lazily sized: the test suite's autouse env hygiene deletes
# _SECTION_CONCURRENCY_ENV per test, so constructing the semaphore at import
# time would freeze an ambient operator value before any of them run. The
# object is cached keyed on the parsed bound, never on first construction.
_section_call_sem: threading.Semaphore | None = None
_section_call_sem_bound = 0


@functools.lru_cache(maxsize=1)
def _warn_invalid_section_concurrency(raw: str) -> None:
    """Report an ignored concurrency override once, not once per read."""
    print(f"[merge] invalid {_SECTION_CONCURRENCY_ENV}={raw!r}: expected a positive "
          f"integer — using {_SECTION_MERGE_MAX_CONCURRENT}", file=sys.stderr, flush=True)


def _get_section_sem() -> threading.Semaphore:
    """The process-wide section-merge concurrency bound.

    Reads _SECTION_CONCURRENCY_ENV per call (the _full_rewrite_limit()
    env-read pattern), warns once per distinct invalid value -- a bound below 1
    would deadlock every section call on the semaphore, so it is invalid and the
    default is used, matching how _full_rewrite_limit treats its own typos --
    and caches the Semaphore object keyed on the parsed bound, so a changed
    value re-sizes the bound rather than being ignored.
    """
    global _section_call_sem, _section_call_sem_bound
    bound = _SECTION_MERGE_MAX_CONCURRENT
    raw = os.environ.get(_SECTION_CONCURRENCY_ENV, "")
    if raw:
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 0
        if parsed >= 1:
            bound = parsed
        else:
            _warn_invalid_section_concurrency(raw)
    if _section_call_sem is None or _section_call_sem_bound != bound:
        _section_call_sem = threading.Semaphore(bound)
        _section_call_sem_bound = bound
    return _section_call_sem


# The key each list field's items carry their name in: concepts and decisions
# use "title", entities and enumerations "name", action_items "task", claims
# "claim". Probed in this order so the router digest stays one line per field.
_DIGEST_TITLE_KEYS = ("title", "name", "task", "claim")

# Titles shown per field before the digest cuts to "+N more"; the count still
# reports the full list length, which is the routing signal.
_DIGEST_ITEMS_SHOWN = 6


def _digest_title(item: object) -> str:
    if isinstance(item, dict):
        for key in _DIGEST_TITLE_KEYS:
            value = item.get(key)
            if value:
                return str(value)
    return str(item)


def _extraction_digest(extraction: ExtractionResult, source_path: str) -> str:
    """Compact routing digest of an extraction for the router call.

    The router needs enough signal to match material to sections -- summary,
    topics, and each field's item titles and count -- not the full extraction
    text: the call is capped at max_tokens=1024, so the input has to stay small
    too. _FIELD_PRIORITY's order, for a deterministic digest.
    """
    lines = [f"Source: {source_path}"]
    if extraction.summary:
        lines.append(f"Summary: {extraction.summary}")
    if extraction.topics:
        lines.append("Topics: " + ", ".join(str(t) for t in extraction.topics))
    for field_name, _field_type in _FIELD_PRIORITY:
        if field_name in ("summary", "topics"):
            continue
        value = getattr(extraction, field_name, None)
        if not value:
            continue
        titles = ", ".join(_digest_title(item) for item in value[:_DIGEST_ITEMS_SHOWN])
        more = "" if len(value) <= _DIGEST_ITEMS_SHOWN else \
            f", +{len(value) - _DIGEST_ITEMS_SHOWN} more"
        lines.append(f"{field_name.replace('_', ' ').title()} ({len(value)}): {titles}{more}")
    return "\n".join(lines)


def _route_sections(article_content: str, extraction: ExtractionResult,
                    source_path: str, model: str) -> dict | None:
    """Tiny router call deciding which sections the extraction touches.

    Sends the numbered ## heading list plus an extraction digest and expects
    {"sections": ["## H", ...], "new_sections": [{"heading": "## N",
    "after": "## H"}]}. Headings the article does not carry are dropped with an
    alert -- a hallucinated route must not corrupt the reassembly -- and the
    returned headings are the article's own strings, so downstream matching is
    exact. Duplicate sections are collapsed; a new section's heading keeps the
    model's text, anchored to the article's own spelling of "after" -- except
    that a proposal naming a heading the article already carries is remapped
    to a route onto that section (dropping it would silently unmerge its
    material), and one duplicating another proposal drops with an alert.

    Returns None on call failure (parse error, garbage shape, exhausted
    truncation ladder, empty completion, batch deadline) or when nothing valid
    survives -- the caller treats None as degraded and falls through to the
    legacy chain rather than silently merging nothing.

    The completion_json call runs under _get_section_sem() with restart
    semantics (JSON cannot continue mid-object), max_tokens fixed at 1024: the
    payload is heading strings, and a router that needs more than that is
    garbage.
    """
    headings = [h for h, _body in _parse_sections(article_content) if h]
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headings, 1))
    digest = _extraction_digest(extraction, source_path)
    user = (f"Article sections:\n{numbered}\n\n"
            f"New material to place:\n{digest}\n\n"
            f"Which existing sections should the new material be merged into, "
            f"and which new sections are needed?")

    try:
        with _get_section_sem():
            raw = completion_json(model=model, messages=[
                {"role": "system", "content": _merge_section_router_system()},
                {"role": "user", "content": user},
            ], max_tokens=1024)
    except (json.JSONDecodeError, RuntimeError, OutputTruncatedError,
            EmptyCompletionError, DeadlineExceededError):
        return None
    if not isinstance(raw, dict):
        return None

    raw_sections = raw.get("sections")
    raw_new_sections = raw.get("new_sections")
    if not isinstance(raw_sections, list):
        raw_sections = []
    if not isinstance(raw_new_sections, list):
        raw_new_sections = []

    known = {h.strip(): h for h in headings}

    sections: list[str] = []
    for entry in raw_sections:
        if isinstance(entry, str) and entry.strip() in known:
            heading = known[entry.strip()]
            if heading not in sections:
                sections.append(heading)
        else:
            emit_alert(f"router named section {entry!r} the article does not carry, "
                       f"dropping it", model, 0, "section_route_dropped")

    new_sections: list[dict] = []
    proposed: set[str] = set()
    for entry in raw_new_sections:
        if not isinstance(entry, dict):
            emit_alert(f"router new_section {entry!r} is not a JSON object, dropping it",
                       model, 0, "section_route_dropped")
            continue
        heading = entry.get("heading")
        after = entry.get("after")
        if not isinstance(heading, str) or not heading.strip():
            emit_alert("router new_section has no heading, dropping it",
                       model, 0, "section_route_dropped")
            continue
        if not isinstance(after, str) or after.strip() not in known:
            emit_alert(f"router new_section anchors after {after!r} which the article "
                       f"does not carry, dropping it", model, 0, "section_route_dropped")
            continue
        # A proposal naming a heading the article already carries is a route
        # onto that existing section, not a new section: remap it instead of
        # dropping it -- a partial drop here would silently leave the
        # material unmerged while the task Acks "merged". A heading
        # duplicating another PROPOSAL has no unambiguous placement, so it
        # drops with an alert (and only that -- the first proposal carries
        # the placement).
        key = heading.strip()
        if key in known:
            if known[key] not in sections:
                sections.append(known[key])
            continue
        if key in proposed:
            emit_alert(f"router new_section heading {heading!r} duplicates another "
                       f"proposed section, dropping it",
                       model, 0, "section_route_dropped")
            continue
        proposed.add(key)
        new_sections.append({"heading": key, "after": known[after.strip()]})

    if not sections and not new_sections:
        return None
    return {"sections": sections, "new_sections": new_sections}


def _merge_one_section(heading: str, body: str, extraction: ExtractionResult,
                       source_path: str, model: str, budget: int, *,
                       after: str = "") -> str:
    """One bounded section rewrite -- with an empty body and an `after` anchor,
    the body for a section that does not exist yet.

    system = the merge-section prompt + _GROUNDING; user = the section's
    current body (for a new section, its heading plus the anchor it goes
    after) and the extraction fitted by _fit_extraction_to_budget within
    `budget` -- the _merge_full_rewrite convention: the caller passes
    MAX_PROMPT_CHARS minus the system prompt and the safety margin, and the
    user message fits inside what is left. The call is sized by
    estimate_max_tokens(len(body) + extraction_estimate, minimum=4096) with
    continue_on_length=True -- a truncated section body is worth keeping, not
    discarding -- and runs under _get_section_sem() like every section-path
    LLM call.
    """
    system = _merge_section_system()
    if body:
        section_block = f"Section to merge into:\n\n{heading}\n\n{body}"
    else:
        anchor = f", placed after the section {after}" if after else ""
        section_block = (f"New section to write{anchor}:\n\n{heading}\n\n"
                         f"Write this new section's body from the material below.")
    header = f"{section_block}\n\nNew information to merge:\n"
    extraction_budget = max(budget - len(header), 200)
    user = header + _fit_extraction_to_budget(extraction, source_path, extraction_budget)

    extraction_estimate = _estimate_full_extraction_size(extraction, source_path)
    with _get_section_sem():
        text = completion(model=model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=estimate_max_tokens(
            len(body) + extraction_estimate, minimum=4096),
           cache=True, continue_on_length=True)

    # The prompt says body only, but an echoed fence or heading would corrupt
    # the deterministic reassembly (which emits the heading itself), so both
    # are stripped from whatever came back. The echo match compares the first
    # line, normalized, against the whole heading: "## Notes" prefix-matching
    # a different echoed heading like "## Notes on X" must not eat the start
    # of the body, while an echo carrying trailing whitespace or a CR must
    # still be recognized -- a heading that slips through renders twice and
    # trips the duplicate-heading guard on every later merge.
    out = _strip_markdown_fencing(text).strip()
    if heading:
        split = out.split("\n", 1)
        if len(split) == 2 and split[0].strip() == heading.strip():
            out = split[1].lstrip("\n").strip()
        elif out.strip() == heading.strip():
            out = ""
    if not out:
        # An empty body would silently delete the section's content in the
        # reassembly -- bad generation, not a valid "nothing to say".
        raise RuntimeError("section rewrite came back empty")
    return out


def _merge_sections(
    article_path: str, article_content: str,
    extraction: ExtractionResult, source_path: str, model: str,
) -> tuple[str, bool]:
    """Section-level merge: router -> cost guard -> parallel section rewrites
    and new-section bodies -> deterministic reassembly -> _update_frontmatter.

    Returns (new_content, degraded). degraded is True on router failure,
    cost-guard trip, or any section still failing after its one retry; the
    content is then the article unchanged, because the caller ignores it and
    falls through to the legacy chain (over-size or prompt-overflow ->
    _merge_diff, else full rewrite). Those run at most once each, so the chain
    section -> diff -> full rewrite is acyclic by construction.
    """
    sections = _parse_sections(article_content)
    n_sections = sum(1 for heading, _body in sections if heading)

    # The reassembly keys rewritten bodies by heading text, so a duplicated ##
    # heading would have both occurrences replaced with one rewrite (based on
    # the last occurrence's body) and silently delete the other's content. The
    # legacy paths place content positionally and are duplicate-safe.
    headings = [heading for heading, _body in sections if heading]
    if len(set(headings)) != len(headings):
        print(f"[merge] section-merge fallback: {article_path}: duplicate ## "
              f"headings, the legacy paths handle them positionally",
              file=sys.stderr, flush=True)
        return article_content, True

    route = _route_sections(article_content, extraction, source_path, model)
    if route is None:
        print(f"[merge] section-merge fallback: {article_path}: router call failed",
              file=sys.stderr, flush=True)
        return article_content, True

    affected = route["sections"]
    new_sections = route["new_sections"]

    # Cost guard on the router's output. Coverage half: past 60% of the
    # sections touched, one full rewrite is cheaper than the fan-out it would
    # replace. Sized half: every section call carries the whole extraction,
    # so the expected generated tokens -- the quantity billing actually
    # meters; caps and headroom are free over-provisioning, hence
    # minimum=1/headroom=0 -- are summed per affected call and compared
    # against a single full rewrite carrying the extraction once. A trip
    # costs one 1024-token router call, bounded and counted by the log line.
    if (len(affected) + len(new_sections)) > 0.6 * n_sections:
        print(f"[merge] section-merge guard: {article_path}: {len(affected)} sections "
              f"+ {len(new_sections)} new of {n_sections} -- over 60% coverage, "
              f"a full rewrite is cheaper", file=sys.stderr, flush=True)
        return article_content, True

    extraction_estimate = _estimate_full_extraction_size(extraction, source_path)
    affected_set = set(affected)
    sized_sections = sum(
        estimate_max_tokens(len(body) + extraction_estimate, minimum=1, headroom=0)
        for heading, body in sections if heading in affected_set)
    sized_rewrite = estimate_max_tokens(
        len(article_content) + extraction_estimate, minimum=1, headroom=0)
    if sized_sections > sized_rewrite:
        print(f"[merge] section-merge guard: {article_path}: sized affected work "
              f"{sized_sections} tokens exceeds the sized full rewrite "
              f"{sized_rewrite} tokens", file=sys.stderr, flush=True)
        return article_content, True

    bodies = {heading: body for heading, body in sections if heading}
    system = _merge_section_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN
    parent_ctx = get_context()

    def _rewrite_section(heading: str, body: str, after: str) -> str | None:
        """One section task with its single retry; None means both attempts
        failed and the merge degrades. The pool worker adopts the caller's
        context (the extract.py pattern) so its LLM call keeps the write
        phase's call_timeout and phase label instead of a default context."""
        adopt_context(parent_ctx)
        for _attempt in (1, 2):
            try:
                return _merge_one_section(
                    heading, body, extraction, source_path, model, budget,
                    after=after)
            except Exception:
                continue
        return None

    # Existing-section rewrites and new-section bodies share one call shape,
    # so they share one pool; min(_SECTION_POOL_CAP, tasks) keeps one article
    # from monopolizing the process-wide semaphore's permits.
    tasks = [(heading, bodies[heading], "") for heading in affected]
    tasks += [(ns["heading"], "", ns["after"]) for ns in new_sections]

    rewritten: dict[str, str] = {}
    new_bodies: dict[str, str] = {}
    degraded = False
    with ThreadPoolExecutor(max_workers=min(_SECTION_POOL_CAP, len(tasks))) as pool:
        futures = {pool.submit(_rewrite_section, h, b, a): (h, a)
                   for h, b, a in tasks}
        for future in as_completed(futures):
            heading, after = futures[future]
            body = future.result()
            if body is None:
                degraded = True
            elif after:
                new_bodies[heading] = body
            else:
                rewritten[heading] = body

    if degraded:
        print(f"[merge] section-merge fallback: {article_path}: "
              f"a section failed twice", file=sys.stderr, flush=True)
        return article_content, True

    # Deterministic reassembly over the full article's own section list:
    # untouched sections and the preamble pass through byte-identical (the
    # line list is rebuilt, so "\n".join reproduces the original exactly),
    # routed bodies are swapped in under their headings, and new sections are
    # inserted right after their anchors -- before the frontmatter pass runs
    # on the assembled result.
    insertions: dict[str, list[tuple[str, str]]] = {}
    for ns in new_sections:
        insertions.setdefault(ns["after"], []).append(
            (ns["heading"], new_bodies[ns["heading"]]))

    out_lines: list[str] = []
    for heading, body in sections:
        if not heading:
            out_lines.extend(body.split("\n"))  # preamble, byte-identical
            continue
        if heading in rewritten:
            out_lines.extend([heading, "", *rewritten[heading].split("\n"), ""])
        else:
            out_lines.extend([heading, *body.split("\n")])
        for new_heading, new_body in insertions.get(heading, []):
            out_lines.extend([new_heading, "", *new_body.split("\n"), ""])

    from datetime import date
    today = date.today().isoformat()
    new_content = _update_frontmatter("\n".join(out_lines), source_path, today)
    print(f"[merge] section-merge: {article_path} "
          f"({len(rewritten)}/{n_sections} sections, +{len(new_bodies)} new)",
          file=sys.stderr, flush=True)
    return new_content, False


@_with_write_timeout
def merge_into_article(
    article_path: str,
    article_content: str,
    extraction: ExtractionResult,
    source_path: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    # A previously leaked <article> wrapper sits above the frontmatter and
    # silently disables _apply_diff's frontmatter pass, so heal it on entry
    # rather than carrying the pollution through another compile. Articles
    # that receive no further merges keep the tag on disk; sweeping the
    # compiled wiki once is deliberately out of scope here.
    article_content = _strip_article_wrapper(article_content)

    # Budget-aware: check if full rewrite fits.
    # Registry caches per-process, so this call here + same call inside
    # _merge_full_rewrite both hit the cache after the first lookup.
    full_rewrite_system = _merge_rewrite_system()
    budget = MAX_PROMPT_CHARS - len(full_rewrite_system) - _SAFETY_MARGIN
    min_extraction_chars = len(source_path) + 50
    fits_full_rewrite = len(article_content) + min_extraction_chars <= budget

    article_bytes = len(article_content.encode("utf-8"))
    over_size_limit = article_bytes >= _full_rewrite_limit()

    # Section path -- the deterministic pre-filter spends no LLM call deciding:
    # auto mode, at least _SECTION_MERGE_MIN_BYTES, at least three ##
    # headings, and an article that fits the prompt budget (a section merge
    # sends each section body plus the extraction, so a prompt-overflow
    # article stays on the legacy diff path). A degraded section merge --
    # router failure, guard trip, or a section failing twice -- falls through
    # to the existing chain below, whose paths each run at most once.
    if (fits_full_rewrite and _section_merge_enabled()
            and article_bytes >= _SECTION_MERGE_MIN_BYTES
            and sum(1 for h, _body in _parse_sections(article_content) if h) >= 3):
        sectioned, degraded = _merge_sections(
            article_path, article_content, extraction, source_path, model)
        if not degraded:
            return sectioned

    if over_size_limit or not fits_full_rewrite:
        new_content, degraded = _merge_diff(
            article_path, article_content, extraction, source_path, model)
        # A degraded diff means the model's response was unparsable or carried
        # malformed patches, and the article came back without the new
        # extraction merged in. When a full
        # rewrite fits the prompt budget anyway, pay it rather than silently
        # dropping the new content -- correctness over tail latency (plan risk
        # R6). The log line doubles as the fallback-rate metric for Phase 5.
        if degraded and fits_full_rewrite:
            print("[merge] diff result unparsable, falling back to full-rewrite",
                  file=sys.stderr, flush=True)
            return _merge_full_rewrite(
                article_path, article_content, extraction, source_path, model)
        if degraded:
            # No rewrite fits either (over the size limit and the prompt
            # budget): the extraction was NOT merged. Raise rather than return
            # the unchanged article -- both callers' per-article handlers
            # record the error into the task's Ack payload / the compile
            # error list, so the failure is visible instead of a task that
            # reports "merged" while a document's knowledge never landed.
            # Raising also skips the write, so the frontmatter does not
            # record a source whose content is absent.
            raise RuntimeError(
                f"diff result unparsable and no rewrite fits: {article_path} "
                f"keeps its current content (extraction from {source_path} "
                f"was not merged)")
        return new_content

    return _merge_full_rewrite(article_path, article_content, extraction, source_path, model)


def _merge_full_rewrite(
    article_path: str, article_content: str,
    extraction: ExtractionResult, source_path: str, model: str,
) -> str:
    system = _merge_rewrite_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN
    user = _merge_user_message(article_content, extraction, source_path, budget)

    # Sized first rung + continuation: the rewritten article's length is
    # knowable up front (existing article + extraction), so the first attempt
    # lands right instead of discarding a 16K-token generation on every
    # over-cap merge (the measured round-A waste this plan exists to remove).
    expected_chars = len(article_content) + _estimate_full_extraction_size(
        extraction, source_path)
    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=estimate_max_tokens(expected_chars, minimum=16384),
        continue_on_length=True, cache=True).strip()
    # Wrapper before fencing and again after: an echoed <article> can nest
    # either way -- outermost, or the whole wrapper inside a markdown fence.
    return _strip_article_wrapper(_strip_markdown_fencing(_strip_article_wrapper(text)))


def _merge_diff(
    article_path: str, article_content: str,
    extraction: ExtractionResult, source_path: str, model: str,
) -> tuple[str, bool]:
    """Merge via patches. Returns (new_content, degraded); degraded is True
    when the LLM's diff response was unparsable (JSONDecodeError, RuntimeError,
    EmptyCompletionError, DeadlineExceededError or OutputTruncatedError from
    completion_json -- the same set the section router degrades on) or when
    _validate_patches dropped a malformed patch from it -- a legitimate
    {"patches": []} is a valid "nothing to add" answer, not degradation.
    """
    from datetime import date
    today = date.today().isoformat()

    system = _merge_diff_system()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN

    # BUG 1 (fixed, was RCA optimization #6 item 1): the prompt below is built
    # from a possibly section-truncated view of the article, but the returned
    # patches are applied to the FULL on-disk article. The invariant that makes
    # that safe: patch anchors are model-visible headings, which are a subset
    # of the full article's headings -- _truncate_article_by_sections keeps
    # every heading in the normal branch, and even its extreme branch (heading
    # skeleton alone over budget) keeps a heading prefix. A patch naming a
    # model-visible heading lands correctly on the full article; a hallucinated
    # anchor degrades to append-at-end through _append_to_section /
    # _insert_section_after's existing fallbacks, exactly as it did when the
    # apply targeted the view. The pre-fix behavior rebuilt the merged article
    # from the truncated view, silently dropping the bodies of non-relevant
    # sections from disk -- and in the extreme branch, which keeps only
    # headings, the frontmatter that _apply_diff's frontmatter pass requires
    # (lines[0] == "---").
    article_budget = int(budget * 0.7)
    prompt_view = article_content
    if len(prompt_view) > article_budget:
        prompt_view = _truncate_article_by_sections(
            prompt_view, extraction.topics, article_budget)

    user = _merge_user_message(prompt_view, extraction, source_path, budget)

    degraded = False
    try:
        # The patch payload scales with the extraction, not the article, so
        # the first rung is sized from the extraction estimate (floor 4096):
        # over-provisioning is free, under-sizing costs a restart round.
        raw = completion_json(model=model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=estimate_max_tokens(
            _estimate_full_extraction_size(extraction, source_path), minimum=4096),
           cache=True)
    except (json.JSONDecodeError, RuntimeError, EmptyCompletionError,
            DeadlineExceededError, OutputTruncatedError):
        raw = {"patches": []}
        degraded = True

    # BUG 2 (fixed, was RCA optimization #6 item 2): variant-finish truncations
    # no longer leak parseable-but-partial patch sets (closed in completion()'s
    # set-based finish-reason matching, kb_ai/llm/_completion.py), so what
    # reaches here malformed is bad generation, not a cut -- any dropped patch
    # marks the response suspect and sets degraded, and the caller then pays
    # the full rewrite when the budget fits. _apply_diff keeps its defensive
    # per-patch skip for the patches that survive.
    patches, dropped = _validate_patches(raw, model)
    if dropped:
        degraded = True

    return _apply_diff(article_content, {"patches": patches}, source_path, today), degraded


def _merge_user_message(article_content: str, extraction: ExtractionResult,
                        source_path: str, budget_chars: int) -> str:
    header = f"Existing article:\n{_ARTICLE_OPEN}\n"
    footer = f"\n{_ARTICLE_CLOSE}\n\nNew information to merge:\n"
    extraction_budget = max(budget_chars - len(header) - len(article_content) - len(footer), 0)
    extraction_text = _fit_extraction_to_budget(extraction, source_path, max(extraction_budget, 200))

    user = header + article_content + footer + extraction_text
    # Final guard: hard truncate if still over budget (extreme edge case)
    if len(user) > budget_chars:
        user = user[:budget_chars]
    return user


def _update_frontmatter(article_content: str, source_path: str, today: str) -> str:
    """Refresh `updated:` and append source_path under `sources:`.

    Factored verbatim out of _apply_diff's frontmatter block (no behavior
    change) so the write phase's later merge paths can run the same pass.
    An article that does not start with a closed `---` block is returned
    unchanged.
    """
    lines = article_content.split("\n")

    if lines and lines[0].strip() == "---":
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx:
            fm_lines = lines[1:end_idx]
            source_line = f"  - {source_path}"
            # Compare normalized on both sides -- existing_sources is stripped,
            # so an indented source_line would never match.
            source_key = source_line.strip()
            # Scope note: this collects every "  - " item in the frontmatter, not
            # only the ones under sources:. A same-named item under another list
            # key would suppress the source append. create_new_article emits
            # flow-style tags, so no other key produces "  - " items today.
            existing_sources = {fl.strip() for fl in fm_lines if fl.startswith("  - ")}
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
                        if source_key not in existing_sources:
                            new_fm.append(source_line)
                        found_sources = False
                else:
                    if found_sources:
                        if source_key not in existing_sources:
                            new_fm.append(source_line)
                        found_sources = False
                    new_fm.append(fl)
            if found_sources and source_key not in existing_sources:
                new_fm.append(source_line)
            if not found_updated:
                new_fm.append(f"updated: {today}")
            lines = ["---"] + new_fm + lines[end_idx:]

    return "\n".join(lines)


def _validate_patches(raw: dict, model: str) -> tuple[list[dict], int]:
    """(valid_patches, dropped_count). A patch is valid when action is
    append_to_section (non-empty section + content) or new_section
    (after + heading + non-empty content). Each dropped patch alerts
    (kind="merge_patch_dropped").
    """
    valid: list[dict] = []
    dropped = 0
    for i, patch in enumerate(raw.get("patches", [])):
        if not isinstance(patch, dict):
            emit_alert(f"diff patch {i} is not a JSON object, dropping it",
                       model, 0, "merge_patch_dropped")
            dropped += 1
            continue
        action = patch.get("action")
        content = patch.get("content", "")
        if action == "append_to_section":
            if patch.get("section") and content:
                valid.append(patch)
                continue
            reason = "append_to_section needs a non-empty section and content"
        elif action == "new_section":
            if patch.get("after") and patch.get("heading") and content:
                valid.append(patch)
                continue
            reason = "new_section needs a non-empty after, heading and content"
        else:
            reason = f"unknown action {action!r}"
        emit_alert(f"diff patch {i} dropped: {reason}",
                   model, 0, "merge_patch_dropped")
        dropped += 1
    return valid, dropped


def _apply_diff(article_content: str, diff: dict, source_path: str, today: str) -> str:
    content = _update_frontmatter(article_content, source_path, today)

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


def _strip_article_wrapper(text: str) -> str:
    """Remove the <article>/</article> wrapper a rewrite sometimes echoes back
    from _merge_user_message's framing.

    The framing is prompt scaffolding, but the rewrite output is written to
    disk verbatim, so an echoed tag lands above the frontmatter. Once there it
    also breaks _apply_diff, whose frontmatter pass requires lines[0] == "---"
    -- so the tag is stripped here both from fresh output and from article
    content that already carries it (healing on the next merge).

    Paired-only: the closing tag is removed just when the opening tag was,
    because an article whose body legitimately ends with a literal
    </article> (an HTML example, say) must not lose its tail. A clean article
    starts with the frontmatter delimiter, never this tag, so the leading
    match is unambiguous.
    """
    if not text.startswith(_ARTICLE_OPEN):
        return text
    text = text[len(_ARTICLE_OPEN):]
    trimmed = text.rstrip()
    if trimmed.endswith(_ARTICLE_CLOSE):
        text = trimmed[: -len(_ARTICLE_CLOSE)]
    return text.strip()


def _write_stage_renderings() -> list[tuple[str, str]]:
    """Every *system* prompt the write phase sends, as it now renders.

    Four prompt files -- merge-rewrite, merge-diff, merge-section-router,
    merge-section -- plus the article creator's system prompt, which is built in
    code and varies by article type, so a hash over the files alone would leave
    it a blind spot -- the same trap B11 covers on the extraction side.

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
           ("merge-diff", _merge_diff_system()),
           ("merge-section-router", _merge_section_router_system()),
           ("merge-section", _merge_section_system())]
    for article_type in sorted(_SECTION_TEMPLATES) + [_UNTEMPLATED_TYPE]:
        out.append((f"create-new#{article_type}", _create_system(article_type)))
    return out


@functools.lru_cache(maxsize=1)
def write_prompt_version() -> str:
    """12 hex digits over the write stage's prompt set as it now renders.

    The counterpart of extract_prompt_version, and deliberately a separate value:
    a write-prompt edit must not move the extraction's version, or every document
    would re-extract at full cost over a prompt extraction never used.

    Reported, never gated. The diff and rewrite paths are additive -- merge-diff.md
    offers only append_to_section and new_section, and merge-rewrite.md says
    nothing about supersession -- so re-composing an article layers new content
    on top of the old rather than replacing it. The section path (merge-section.md)
    is the one bounded supersession that exists: it rewrites single sections and
    may replace an existing statement the new material directly contradicts,
    nothing broader. Feeding this into the composition gate would still inflate
    every article on a prompt edit and pay the full write phase to do it, so
    whether write-prompt edits should ever gate stays an open follow-up question
    (recorded in the replay-benchmark analysis doc); an operator reading the
    count remains the useful thing.

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
    extraction: ExtractionResult,
    source_path: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    from datetime import date
    today = date.today().isoformat()

    system = _create_system(article_type)

    user_header = f"""Create article:
- Title: {title}
- Type: {article_type}
- Source: {source_path}
- Created/Updated: {today}
- Tags: {extraction.topics}

Knowledge to include:
"""
    budget = MAX_PROMPT_CHARS - len(system) - len(user_header) - _SAFETY_MARGIN
    extraction_text = _fit_extraction_to_budget(extraction, source_path, max(budget, 200))
    user = user_header + extraction_text

    # Prose expansion factor 2x: the article restates the extraction's content
    # in full sentences with structure and frontmatter, roughly doubling it.
    expected_chars = 2 * _estimate_full_extraction_size(extraction, source_path)
    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=estimate_max_tokens(expected_chars, minimum=16384),
        continue_on_length=True, cache=True).strip()
    return _strip_markdown_fencing(text)
