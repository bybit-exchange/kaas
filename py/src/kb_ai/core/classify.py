from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.extract import ExtractionResult
from kb_ai.llm import MAX_PROMPT_CHARS, completion_json
from kb_ai.prompts import default_registry
from kb_ai.storage.store import ArticleMeta, KBStore

_SAFETY_MARGIN = 500

# The default article taxonomy. Measured over this repository's own docs
# (docs/classify-taxonomy-measurements.md): `person` was chosen 0 times in 240
# classifications and `decision` 0-2 times, while `reference` and `guide` -- both
# absent from the original four -- took the right documents (policy files to
# reference, how-to files to guide). Usage saturates at five categories, so six
# leaves one slot of headroom. `person` stays because core/people.py generates
# people articles from config, a path a docs-only corpus never exercises.
DEFAULT_CATEGORIES = ["concept", "decision", "project", "reference", "guide", "person"]

# One line per category, injected into the classify prompt. Without these the
# model infers what each bare word means, and `project` becomes the default
# bucket -- it took 81% of a docs corpus on the old four-item menu. Keyed by name
# so a caller passing a custom `categories` list gets no definitions rather than
# wrong ones.
CATEGORY_DEFINITIONS = {
    "concept": "a durable idea, mechanism, or how-something-works explanation that stays true over time",
    "decision": "a choice that was made, with its rationale, the alternatives considered, and its consequences",
    "project": "a specific named initiative with a lifecycle -- status, milestones, or a backlog of work items",
    "reference": "canonical rules, policies, specifications or lookup material, consulted rather than read through",
    "guide": "step-by-step instructions for accomplishing a task",
    "person": "a named individual, their role, and their responsibilities",
}


def effective_categories(categories: list[str] | None) -> list[str]:
    """The category list classify_article() will actually use.

    Callers pass None to mean "the defaults", so any cache key built from the
    caller's own argument would describe a run that never happened.
    """
    return list(categories) if categories else list(DEFAULT_CATEGORIES)


def resolve_categories(store: KBStore, categories: list[str] | None) -> list[str]:
    """The category set for this run, frozen into per-KB config on first use.

    Freezing matters because DEFAULT_CATEGORIES is a measured default that can
    change between releases. Without a frozen set, a KB compiled under one
    taxonomy would quietly start filing new articles under another, leaving a
    mixed taxonomy that re-running does not repair (see
    docs/classify-taxonomy-measurements.md). An explicit set still wins, because
    the daemon accepts one per request, but a set that disagrees with the frozen
    one is logged loudly -- that is precisely the case that mixes the taxonomy.
    """
    config = store.load_config()
    frozen = config.get("categories")

    if not isinstance(frozen, list) or not frozen:
        effective = effective_categories(categories)
        # Nothing to freeze into on a read-only store (the MCP server opens one),
        # and nothing worth creating for a KB directory that does not exist --
        # writing one there would leave a mistyped --kb path looking like a real KB.
        if not store.read_only and store.base_dir.exists():
            config["categories"] = effective
            config["categories_frozen_at"] = datetime.now(timezone.utc).isoformat()
            store.save_config(config)
        return effective

    if not categories or list(categories) == frozen:
        return frozen

    print(
        f"[config] WARNING: requested categories {list(categories)} differ from "
        f"the set frozen at KB creation {frozen}; using the requested set. New "
        f"articles will not share a taxonomy with the existing ones.",
        file=sys.stderr,
        flush=True,
    )
    return list(categories)


def classify_inputs_hash(categories: list[str] | None) -> str:
    """Hash the classify prompt as it will actually be sent, minus the articles.

    Hashing the rendered system template rather than the category list means the
    key moves when the prompt file changes, when a CATEGORY_DEFINITIONS entry
    changes, or when the category list changes. The old categories-only hash saw
    only the last of those, so a prompt-only edit silently kept serving
    classifications produced by the previous prompt. The articles are excluded
    because classify_cache_key() carries them separately.
    """
    return hashlib.sha256(
        _render_classify_system(effective_categories(categories)).encode()
    ).hexdigest()[:8]


def _render_classify_system(categories: list[str]) -> str:
    """Render the classify system template, articles placeholder still unfilled."""
    return default_registry().get("classify").render(
        categories_str=", ".join(categories),
        categories=categories,
        category_definitions=category_definitions_block(categories),
    )


def category_definitions_block(categories: list[str]) -> str:
    """Render definitions for whichever active categories have one."""
    known = [(c, CATEGORY_DEFINITIONS[c]) for c in categories if c in CATEGORY_DEFINITIONS]
    if not known:
        return ""
    lines = "\n".join(f"- {name}: {desc}" for name, desc in known)
    return f"\nCategory definitions (choose the single best fit):\n{lines}\n"


def _relevance_score(article: ArticleMeta, topics: list) -> float:
    """Score article by title word overlap with extraction topics."""
    title_words = _title_words(article.title)
    if not title_words:
        return 0.0
    topic_words: set[str] = set()
    for t in topics:
        topic_words.update(re.sub(r'[^a-zA-Z0-9\s]', '', str(t).lower()).split())
    if not topic_words:
        return 0.0
    return len(title_words & topic_words) / min(len(title_words), len(topic_words))


def _fit_articles_to_budget(articles: list[dict], budget_chars: int) -> str:
    """Fit articles JSON into budget using exponential backoff truncation."""
    full = json.dumps(articles, ensure_ascii=False, indent=2)
    if len(full) <= budget_chars:
        return full

    total = len(articles)
    n = total
    while n > 0:
        n = n // 2
        candidate = json.dumps(articles[:n], ensure_ascii=False, indent=2)
        if len(candidate) <= budget_chars:
            print(
                f"[truncation] classify articles: {total} → {n} items",
                file=sys.stderr,
                flush=True,
            )
            return candidate

    print(
        f"[truncation] classify articles: {total} → 0 items (budget too small)",
        file=sys.stderr,
        flush=True,
    )
    return "[]"


def classify_article(
    extraction: ExtractionResult,
    existing_articles: list[ArticleMeta],
    model: str = "claude-sonnet-4-6",
    categories: list[str] | None = None,
) -> ClassificationResult:
    categories = effective_categories(categories)

    # Sort articles by relevance (descending) before building prompt
    sorted_articles = sorted(
        existing_articles,
        key=lambda a: _relevance_score(a, extraction.topics),
        reverse=True,
    )

    articles_for_prompt = [
        {"title": a.title, "path": a.path, "summary": a.summary[:80]}
        for a in sorted_articles
    ]

    # Build user message with budget-aware truncation.
    # Reserve half the total budget for user content, half for system (articles).
    user_budget = MAX_PROMPT_CHARS // 2
    summary = extraction.summary[:user_budget // 4]
    topics_str = str(extraction.topics)[:user_budget // 8]
    decisions_json = json.dumps(extraction.decisions, ensure_ascii=False)

    prefix = (
        f"Extracted knowledge:\n"
        f"- Summary: {summary}\n"
        f"- Topics: {topics_str}\n"
        f"- Decisions: "
    )
    decisions_budget = user_budget - len(prefix)
    if len(decisions_json) > decisions_budget:
        decisions_json = decisions_json[:max(decisions_budget, 0)]
    user = prefix + decisions_json

    # Render the classify prompt from the registry. The stored content holds
    # the source f-string text byte-exact (with `{{ARTICLES_PLACEHOLDER}}`,
    # `{{{{`, `{categories_str}`, `{categories[0]}`), so .render() with the
    # right kwargs reproduces the original f-string output exactly.
    system_template = _render_classify_system(categories)

    skeleton_len = len(system_template.replace("{ARTICLES_PLACEHOLDER}", ""))
    articles_budget = MAX_PROMPT_CHARS - skeleton_len - len(user) - _SAFETY_MARGIN

    articles_summary = _fit_articles_to_budget(articles_for_prompt, articles_budget)

    system = system_template.replace("{ARTICLES_PLACEHOLDER}", articles_summary)

    raw = completion_json(model=model, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=2048, cache=True)

    return ClassificationResult.from_dict(raw)


def _title_words(title: str) -> set[str]:
    return set(re.sub(r'[^a-zA-Z0-9\s]', '', title.lower()).split())


def dedup_create_new(classification: ClassificationResult, existing: list[ArticleMeta]) -> ClassificationResult:
    if not classification.create_new or not existing:
        return classification

    merge_into = list(classification.merge_into)
    kept_new: list[CreateTarget] = []

    for item in classification.create_new:
        new_words = _title_words(item.title)
        if not new_words:
            kept_new.append(item)
            continue

        best_match = None
        best_overlap = 0.0
        for art in existing:
            art_words = _title_words(art.title)
            if not art_words:
                continue
            overlap = len(new_words & art_words) / min(len(new_words), len(art_words))
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = art

        if best_overlap >= 0.7 and best_match:
            merge_into.append(MergeTarget(
                path=best_match.path,
                reason=f"dedup: title overlap {best_overlap:.0%} with existing article",
            ))
        else:
            kept_new.append(item)

    return ClassificationResult(merge_into=merge_into, create_new=kept_new)


def hash_existing_articles(articles: list[ArticleMeta]) -> str:
    blob = json.dumps(
        [(a.path, a.title, a.summary[:80]) for a in articles], sort_keys=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def classify_cache_key(checksum: str, articles_hash: str, categories_hash: str) -> str:
    return f"{checksum}-{articles_hash}-{categories_hash}"
