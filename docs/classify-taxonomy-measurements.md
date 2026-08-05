# Classify-phase taxonomy: what the numbers say

Measurements taken on 2026-08-05 against the classify phase, to answer three
questions: how many article categories should the default menu hold, what causes
the run-to-run article-count variance, and does the menu size affect it.

## Setup

Corpus: this repository's own documentation distilled into a fresh KB — `docs/`
plus the root markdown, 16 source documents, 8 articles. Model
`us.claude-sonnet-4-6` through a LiteLLM gateway, `temperature=0` (the client
default in `llm/_completion.py`).

Extractions were read straight from the KB's `.extract-cache`, so no extract
calls were made. `core/classify.classify_article()` applies no result caching —
callers do — so every call below was a real LLM call. 240 classifications in
total, 0 errors.

Menus tested:

```
4  concept, project, decision, person                                   (the current default)
6  + reference, process
8  + guide, incident
```

## Result 1: classification is deterministic; menu size does not destabilise it

Each document was classified three times per menu against an identical empty
existing-articles context.

| Menu size | Documents | Unanimous across 3 repeats | Stability |
|---|---|---|---|
| 4 | 16 | 16 | 100% |
| 6 | 16 | 16 | 100% |
| 8 | 16 | 16 | 100% |

At `temperature=0`, given a fixed (document, menu, context), the answer never
varied. A larger menu did not add variance.

## Result 2: the variance comes from context, i.e. from ordering

Because classification is deterministic given its inputs, the only way one
document gets two different types across runs is that its *context* differed —
which articles already existed when it was classified.

That context is built per run by `_cluster_by_topic_overlap()` grouping plus
parallel worker scheduling, neither of which is order-stable. Early decisions
change later contexts, so the effect compounds. This is the mechanism behind the
recorded 48-vs-98 article variance on identical input, and behind a case
observed directly: `CONTRIBUTING.md` classified as `decision` in one KB and
`project` in another, from the same single source document and the same 4-item
menu.

The fix implied is deterministic ordering, not temperature or retries.

## Result 3: usage saturates at five categories, and growing the menu re-partitions

| Menu size | Categories used | Dead | Distribution |
|---|---|---|---|
| 4 | 3 of 4 | `person` | project 13, decision 2, concept 1 |
| 6 | 5 of 6 | `person` | project 10, concept 2, process 2, decision 1, reference 1 |
| 8 | 5 of 8 | `person`, `process`, `incident` | project 9, concept 2, guide 2, reference 2, decision 1 |

Going from 6 to 8 added no new distinctions — five used either way — and left
three categories dead.

Adding categories does not extend the taxonomy, it re-partitions it. Only 10 of
16 documents (62%) kept the same type across all three menus:

```
agent-quickstart.md    decision  -> process   -> guide
CLAUDE.md              decision  -> reference -> reference
CONTRIBUTING.md        project   -> process   -> guide
SECURITY.md            project   -> project   -> reference
```

Consequence for operators: changing a KB's category set is a migration, not a
configuration change, because roughly a third of articles change directory and
`wiki/<type>/<name>.md` is an article's identity. Choose the set when the KB is
created and freeze it. The set is already a parameter (`categories`, threaded
through `compile_kb` and accepted per daemon request); it is simply not exposed
on `kb-ai distill`, so the default always applies there.

## Result 4: category definitions help, modestly

`prompts/defaults/classify.md` passes the categories as bare words —
`type must be one of: concept, project, decision, person` — with no definitions,
so the model infers what each one means. Adding a one-line definition per
category, changing nothing else:

| | Distribution | Top bucket | Categories used |
|---|---|---|---|
| Bare names | project 10, guide 2, concept 2, reference 2 | 62% | 4 of 6 |
| With definitions | project 8, concept 4, guide 2, reference 2 | 50% | 4 of 6 |

Two documents of 16 moved, both correctly (technical overviews `project` →
`concept`), and determinism held (16/16 across two passes). Worth doing, but it
is not the lever that fixes skew.

The `project` concentration is probably substantially the corpus rather than the
prompt: these 16 documents are a software project's own paperwork — plan,
backlog, spec, notes, README. Deciding whether 50% is wrong needs a
human-labelled gold set, which does not exist yet. That is the missing
instrument, and the honest prerequisite for further prompt tuning.

## Recommendation

Six categories: `concept`, `decision`, `project`, `reference`, `guide`, `person`.

The count matters less than the membership. The default menu's real problem is
which four it holds:

```
default:        concept, project, decision, person
measured usage: concept, project, reference, guide
```

`person` fired zero times in 240 classifications and `decision` fired 0-2 times,
while `reference` and `guide` — both absent from the default — took four
documents between them and took the right ones (`CLAUDE.md` and `SECURITY.md` →
reference, `agent-quickstart` and `CONTRIBUTING` → guide). Keep `person`
regardless: `core/people.py:update_people_stubs` generates people articles from
config, a feature a docs-only corpus never exercises. Keep `decision` for
corpora that carry ADRs or meeting notes.

Priority order for acting on this:

1. Deterministic ordering in the classify phase. This is the demonstrated defect
   and the only one that changes output correctness run to run.
2. Definitions in `classify.md`, and a narrower definition of `project` so it
   stops working as the default bucket.
3. Category set as per-KB configuration, frozen at KB creation, and exposed on
   `kb-ai distill`.

## Caveats

One corpus, 16 documents, one model. The 100% repeat stability and the 62%
cross-menu agreement are strong signals. The category *distribution* is
corpus-specific: a code-heavy or meeting-notes corpus would saturate at a
different number, so re-run the measurement rather than porting these
percentages.

Also note a gap found while running this: the classify cache key is
`checksum + articles_hash + categories_hash` (`core/classify.py:classify_cache_key`)
and does not include the prompt text. Editing `classify.md` therefore leaves
cached classifications in place, so a prompt change appears to do nothing on a
KB that has already been compiled.

## Reproducing

Both harnesses were throwaway scripts outside the repository. To rebuild them:
read extractions from `<kb>/.extract-cache/*.json` via
`core.extract.parse_extraction_result`, call
`core.classify.classify_article(ext, [], model=..., categories=[...])` per
(document, menu, repeat), and record `create_new[0].type`. For the definitions
arm, render the `classify` prompt with bare category names and append a
definitions block, keeping the user message construction byte-identical to
`classify_article`.

Cost: the 192-call sweep and the 48-call definitions arm were roughly 1.5 and
0.4 USD, scaled from a measured `0.108 USD / 14 calls` classify rate rather than
metered directly.
