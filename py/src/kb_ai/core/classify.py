from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone

from kb_ai._text import bigram_tokens, overlap, tokens
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
    """Score an article's title against the extraction's topics.

    Tokenised by the shared lexical tokeniser rather than a local ASCII-only
    regexp: that regexp scored every Chinese title 0.0, which left the sort below
    stable and therefore a no-op, so the budget cut kept whichever articles came
    first. Topics arrive from LLM output and are not guaranteed to be strings.
    """
    return overlap(tokens(article.title), tokens(" ".join(str(t) for t in topics)))


# json.dumps(list, indent=2) wraps the entries in "[\n" ... "\n]" and joins them
# with ",\n", each entry indented one level. The fit below needs each entry's
# exact cost, so it renders them one at a time and reassembles the array;
# test_fit_articles_renders_exactly_what_json_dumps_would pins the equivalence.
_ARRAY_OVERHEAD = len("[\n") + len("\n]")
_ENTRY_SEPARATOR = ",\n"


def _entry_block(entry: dict) -> str:
    # Indented by hand rather than with textwrap.indent, which breaks lines on
    # everything str.splitlines() accepts: a title carrying U+0085, U+2028 or
    # U+2029 (ensure_ascii=False emits all three raw) came back with two spaces
    # injected into it, so the model read a title the article does not have.
    return "  " + json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n  ")


def _fit_articles_to_budget(articles: list[dict], budget_chars: int) -> str:
    """Keep the highest-ranked entries whose rendered JSON fits the budget.

    The previous version halved the list until it fit, so a budget with room for
    30 of 32 entries kept 16 -- and at 500 articles, where the catalog is cut for
    real, the classifier saw a quarter of the KB and created a duplicate article
    whenever the merge target was in the discarded half. Every entry the budget
    holds is one more article a merge can land in.
    """
    kept: list[str] = []
    used = 0
    for entry in articles:
        block = _entry_block(entry)
        cost = len(block) + (len(_ENTRY_SEPARATOR) if kept else _ARRAY_OVERHEAD)
        if used + cost > budget_chars:
            # Skip rather than stop: the list is ranked, so one entry whose block
            # does not fit must not discard every shorter one below it (same rule
            # as retrieve._fit_catalog).
            continue
        kept.append(block)
        used += cost

    if len(kept) < len(articles):
        print(
            f"[truncation] classify articles: {len(articles)} → {len(kept)} items "
            f"({budget_chars:,}-char budget)",
            file=sys.stderr,
            flush=True,
        )
    if not kept:
        return "[]"
    return "[\n" + _ENTRY_SEPARATOR.join(kept) + "\n]"


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


# Measured over the 675 titles of data/kb-knowledge: this rule merges 22 pairs
# against the pre-branch ASCII rule's 46. All 22 were read: 15 are one article
# titled twice (capitalisation, "&" against "And", or a trailing date), 1 is this
# corpus's near-duplicate "AI-Native workflow" cluster, and 6 are a rolling 发言复盘
# article beside its dated instalments (see the docstring below). The number gate
# changes none of those 22 -- on this corpus it is inert, and it is kept for the
# series shape the docstring names, which this corpus happens not to contain.
_DUPLICATE_THRESHOLD = 0.7

# A one-token difference is enough to invert a claim, and these are the tokens that
# do it. Deliberately small, and every entry is exercised by a test: an unpaired
# marker refuses a merge, so a missing entry leaves the pre-branch behaviour rather
# than creating a new failure, while a spurious match costs a real duplicate. That
# last cost is measured, which is why `rollback`, `revert` and `non` are NOT here --
# they appear in 28 of this corpus's 675 titles as ordinary domain nouns ("Abnormal
# Trade Rollback Methodology", "Non-Middleware Integration Scope").
_POLARITY_MARKERS = frozenset({
    "不", "非", "无", "未", "停", "禁", "取消",
    "not", "no", "without", "disable", "disabled",
})

# Any token carrying a digit is a number: `2026`, `01`, but also `q1`, `v2`, `h1`.
# Restricting this to all-digit tokens let `2026 Q1 Planning Review` merge into
# `2026 Q2 Planning Review`.
_DIGIT = re.compile(r"\d")


def _numbers(title: str) -> set[str]:
    # Read off tokens rather than off the raw string, so `(2026-01)` and `2026 01`
    # carry the same numbers -- the corpus writes trailing dates both ways.
    return {t for t in tokens(title) if _DIGIT.search(t)}


def _polarity(title: str) -> set[str]:
    # tokens() emits one token per CJK character, so a single-character marker is
    # found there. The substring arm is for the multi-character ones (取消), which
    # are neither a token nor guaranteed to survive bigramming.
    words = tokens(title)
    return {m for m in _POLARITY_MARKERS
            if m in words or (not m.isascii() and m in title)}


def _duplicate_score(new_title: str, existing_title: str) -> float:
    """How strongly two titles claim to name the same article.

    In one sentence: a duplicate is the same title with words ADDED, and nothing
    replaced -- no substituted word, no disagreeing number, no unpaired negation.

    This is not the ranking's score, and the difference is the cost of being wrong.
    Ranking divides by the smaller token set because it wants recall and a loose
    match only reorders a list. Here a merge writes a document's knowledge into an
    article that never named the subject, and nothing later undoes it. One
    substituted token is all it takes to change the subject, and on a Dice score it
    is also nearly free: for two titles of n tokens differing in one, the score is
    exactly 1 - 1/n, so 内部用户数据访问审计方案 against 外部用户数据访问审计方案
    reaches 0.91 and `允许跨境数据传输…` against `拒绝跨境数据传输…` 0.86. A
    threshold cannot separate those from a genuine rewording, because the corpus's
    one real reworded pair (`Bi-Weekly` against `Biweekly`) sits BELOW them at 0.88.
    So substitution is refused outright and only addition can merge, which is also
    the collision the cross-group dedup phase exists for: "Vector Search Basics"
    beside "Vector Search", 向量检索基础 beside 向量检索.

    Numbers gate the addition, because a number in a title is a period, a version
    or a date: two titles whose numbers DISAGREE are consecutive instances of a
    series (`发言复盘 2026` is not the January instalment). A title that merely ADDS
    a date still matches its undated twin, which is 9 of the duplicate pairs in
    data/kb-knowledge -- and the price of that, accepted deliberately, is that a
    dated instalment also matches a rolling archive of the same name
    (`发言复盘 2026-07` into `发言复盘`). The two shapes are lexically identical, so
    nothing here separates them.

    Polarity markers gate it too, because an addition can invert a claim as easily
    as a substitution can: `不支持向量检索` contains every token of `支持向量检索`
    and scores 0.91.

    Three limitations, all measured and none closable by another threshold:
    - An addition can change the subject without carrying a marker, so
      `Gateway Migration Plan Deprecation` still merges into `Gateway Migration
      Plan` (0.86), as does 全球数据安全规范 into 数据安全规范 (0.83). Separating
      those needs meaning, not tokens.
    - A re-spelling that splits a token is a substitution and is refused:
      `May 6` against `May6`, `Bi-Weekly` against `Biweekly`. That costs a
      duplicate, which is the cheap direction.
    - The relation is not transitive, and _phase_dedup walks it pairwise, so a
      short generic title acts as a hub: `Big Data Team OKR Decisions` and
      `DBA Team OKR Decisions` score 0.0 against each other yet both merge into
      `Team OKR Decisions`. 15 such triples exist in data/kb-knowledge, 6 of them
      the 发言复盘 archive named above.
    """
    new_numbers, existing_numbers = _numbers(new_title), _numbers(existing_title)
    if new_numbers and existing_numbers and new_numbers != existing_numbers:
        return 0.0
    if _polarity(new_title) != _polarity(existing_title):
        return 0.0
    a, b = bigram_tokens(new_title), bigram_tokens(existing_title)
    if not a or not b:
        return 0.0
    if not (a <= b or b <= a):
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def dedup_create_new(classification: ClassificationResult, existing: list[ArticleMeta]) -> ClassificationResult:
    """Turn a create that duplicates an existing title into a merge.

    This is the backstop for a classification that missed its merge target, and
    it read titles through an ASCII-only tokeniser -- so on a Chinese KB it scored
    every pair 0.0 and never fired. It now scores through _duplicate_score, which
    shares kb_ai._text with the ranking but is deliberately stricter: this
    function writes a document's knowledge into an article it did not name, and
    nothing later undoes that, while a missed duplicate leaves an article a later
    compile can still merge.
    """
    if not classification.create_new or not existing:
        return classification

    merge_into = list(classification.merge_into)
    kept_new: list[CreateTarget] = []

    for item in classification.create_new:
        best_match = None
        best_overlap = 0.0
        for art in existing:
            # _duplicate_score returns 0.0 when either title tokenises to nothing,
            # which never beats the 0.0 seed -- so an untitled article, and an
            # untitled create, need no guard of their own.
            score = _duplicate_score(item.title, art.title)
            if score > best_overlap:
                best_overlap = score
                best_match = art

        if best_overlap >= _DUPLICATE_THRESHOLD and best_match:
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
