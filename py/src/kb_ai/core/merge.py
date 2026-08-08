from __future__ import annotations

import functools
import json
import sys

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


_FIELD_PRIORITY = [
    ("summary",      "str"),
    ("concepts",     "list"),
    ("entities",     "list"),
    ("decisions",    "list"),
    ("connections",  "list"),
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


_LARGE_ARTICLE_THRESHOLD = 30_000


@_with_write_timeout
def merge_into_article(
    article_path: str,
    article_content: str,
    extraction: ExtractionResult,
    source_path: str,
    model: str = "claude-sonnet-4-6",
) -> str:
    if len(article_content.encode("utf-8")) >= _LARGE_ARTICLE_THRESHOLD:
        return _merge_diff(article_path, article_content, extraction, source_path, model)

    # Budget-aware: check if full rewrite fits.
    # Registry caches per-process, so this call here + same call inside
    # _merge_full_rewrite both hit the cache after the first lookup.
    full_rewrite_system = default_registry().get("merge-rewrite").render()
    budget = MAX_PROMPT_CHARS - len(full_rewrite_system) - _SAFETY_MARGIN
    min_extraction_chars = len(source_path) + 50
    if len(article_content) + min_extraction_chars > budget:
        return _merge_diff(article_path, article_content, extraction, source_path, model)

    return _merge_full_rewrite(article_path, article_content, extraction, source_path, model)


def _merge_full_rewrite(
    article_path: str, article_content: str,
    extraction: ExtractionResult, source_path: str, model: str,
) -> str:
    system = default_registry().get("merge-rewrite").render()
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN
    user = _merge_user_message(article_content, extraction, source_path, budget)

    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=16384, cache=True).strip()
    return _strip_markdown_fencing(text)


def _merge_diff(
    article_path: str, article_content: str,
    extraction: ExtractionResult, source_path: str, model: str,
) -> str:
    from datetime import date
    today = date.today().isoformat()

    # merge-diff contains literal `{...}` JSON example braces, so use .content
    # rather than .render() (which would treat them as str.format placeholders).
    system = default_registry().get("merge-diff").content
    budget = MAX_PROMPT_CHARS - len(system) - _SAFETY_MARGIN

    # If article exceeds 70% of budget, apply section-based truncation
    article_budget = int(budget * 0.7)
    if len(article_content) > article_budget:
        article_content = _truncate_article_by_sections(
            article_content, extraction.topics, article_budget)

    user = _merge_user_message(article_content, extraction, source_path, budget)

    try:
        raw = completion_json(model=model, messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], max_tokens=4096, cache=True)
    except (json.JSONDecodeError, RuntimeError):
        raw = {"patches": []}

    return _apply_diff(article_content, raw, source_path, today)


def _merge_user_message(article_content: str, extraction: ExtractionResult,
                        source_path: str, budget_chars: int) -> str:
    header = "Existing article:\n<article>\n"
    footer = "\n</article>\n\nNew information to merge:\n"
    extraction_budget = max(budget_chars - len(header) - len(article_content) - len(footer), 0)
    extraction_text = _fit_extraction_to_budget(extraction, source_path, max(extraction_budget, 200))

    user = header + article_content + footer + extraction_text
    # Final guard: hard truncate if still over budget (extreme edge case)
    if len(user) > budget_chars:
        user = user[:budget_chars]
    return user


def _apply_diff(article_content: str, diff: dict, source_path: str, today: str) -> str:
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

    status_line = "\nstatus: active" if article_type == "project" else ""

    system = f"""You are a knowledge base article creator.

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

The `summary` line is the article's entry in the knowledge-base catalog, which is
the only surface a reader searches before opening anything. Write one sentence
under 150 characters naming the specific things covered here — subsystems, key
parameters, decisions — not a restatement of the title.

Use [[wikilinks]] for references to related concepts.
Return the complete article including frontmatter."""

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

    text = completion(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=16384, cache=True).strip()
    return _strip_markdown_fencing(text)
