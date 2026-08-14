# Supersession: letting a later document override what an earlier one said

Status: all of D1–D5 decided — D1 and D2 here on 2026-08-10 (see
[Decisions taken](#decisions-taken)), D3, D4 and D5 on 2026-08-12. The decision
record has moved to [spec.md](spec.md), which also splits path A into A1 and A2 and
fixes the trigger condition this document left implicit. What stands here is the
option analysis behind those choices. Written 2026-08-10.

The case that prompted this: a project plan exists as v1 and v2. Compiling both
should leave an article that states v2, not an article that states both and
contradicts itself. Today it states both.

This is already a named gap rather than a discovery. `spec.md` of the extraction
layer records it as O4a (`docs/features/extraction-layer/spec.md:830-837`), the
published four-layers article records it twice
(`docs/articles/kaas-four-layers.md:195`, `:307`), and the code says it in a
docstring: "Until a supersession path exists, an operator reading the count is
the useful thing" (`py/src/kb_ai/core/merge.py:512-521`). None of them says what
the fix should look like, which is the gap this fills.

## Two shapes, and only one of them is even detected

**Shape A — the same document is revised in place.** `raw/plan.md` changes, its
checksum moves, extraction re-runs, and the write phase merges the new extraction
into the article that the old text already contributed to. Detected: the compile
records these as revised documents and names the articles a human should re-read
(`py/src/kb_ai/commands/compile.py:415`, `:721-734`). Not fixed: the merge that
follows can only add.

**Shape B — v1 and v2 are two separate documents.** `raw/plan-v1.md` and
`raw/plan-v2.md` are unrelated as far as the system is concerned. Each is
classified on its own against the article catalog, both land on the same article,
and nothing anywhere holds the claim that one replaces the other. Not detected at
all.

The prompting case is Shape B. It is also the more common one: a plan doc that
gets a v2 is usually a new file or a new Lark doc, not an edit to the old one.

## Five things that block it today

**1. Both merge routes are additive.** `merge-diff.md` offers exactly two patch
actions, `append_to_section` and `new_section`. `merge-rewrite.md` says "integrate
new information naturally" and "do not duplicate information already in the
article" — nothing about a statement that is now wrong. There is no primitive that
removes or replaces a sentence.

**2. No recency signal reaches the writer.** Raw documents from the Lark import
path carry a frontmatter `date` (see any file under
`data/kb-smoke-newpipeline/raw/`), and the document catalog asks for it
(`py/src/kb_ai/storage/index.py:24`, read off the raw frontmatter at `:262-263`).
It now gets it on every route. `distill` still prepends `<!-- source: ... -->` to
every file it ingests (`py/src/kb_ai/distill.py:82`), which used to push the
document's own frontmatter off line 0 and degrade `_document_frontmatter` to `{}`
— no date, no source, and the filename as the title. Issue #37 fixed that in the
raw-document reader, which skips leading HTML comments before parsing. Measured
on `data/kb-2026-06` after the fix: 108 of 108 document-index lines carry a date
and a source and none is titled by its filename stem, against 0 of 108 before,
and no re-ingest was needed.

That fix lives in one private function, `_document_frontmatter`. D4 below adds a
second reader of raw frontmatter in the write phase, and D3 a third writer of raw
content, so whichever lands first should promote the skip to a shared helper rather
than call `split_frontmatter` directly and reopen this.

Past the catalog it still stops for every route. The extraction layer's
provenance record has no document date
(`py/src/kb_ai/storage/extraction.py:71-89`), and the merge user message emits
only `- Source: <path>` plus the payload fields
(`py/src/kb_ai/core/merge.py:95-154`). The model deciding what to write is not
told which source is newer.

One thing flatters the current behaviour and is worth naming: in the reference KB
the date is inside the filename (`window-2026-06__docs__2026-06-01-...`), so the model
can sometimes infer ordering from the source path by accident. That is not a
signal anything guarantees.

**3. Attribution is destroyed when several sources hit one article in one run.**
`_combine_extractions` concatenates every source's claims, decisions and action
items into one flat bag and joins the paths into a comma-separated string
(`py/src/kb_ai/core/extract.py:778-794`). When v1 and v2 are compiled together,
the writer receives one undifferentiated list in which v1's superseded claim and
v2's replacement are indistinguishable. Both merge and create go through this.

**4. Write order is not stable.** Article groups are written in parallel — 16
workers by default on both routes (`py/src/kb_ai/commands/compile.py:595-597`,
`py/src/kb_ai/commands/pipeline/_phase_write.py:215-231`). Within one group the
ops are in raw-scan order, which is sorted path order. Across runs, ordering
depends on what was ingested when. So "last writer wins" is not available as a
cheap fallback: there is no defined last writer.

**5. Classify cannot see the contradiction.** The classifier is given catalog
lines — path, title, summary — and never an article body
(`py/src/kb_ai/prompts/defaults/classify.md`). It can route v2 into the article v1
built, which is right, but it has no way to say "and this replaces what is
already in there".

## What "override" should mean — decide this before anything else

The word hides three different products.

**Latest-wins.** The article body states v2 only. The frontmatter `sources:` list
keeps both files, so provenance survives and `raw/` still holds v1 verbatim.
Cheapest to specify. A reader asking "what did we decide before, and when did it
change" gets nothing from the wiki.

**Current plus a superseded trail.** The body states v2 and carries an explicit
note of what v1 said and when it stopped being true. This repo's own documents
already use exactly this convention — `[Superseded 2026-08-08: ...]` markers run
through `docs/features/extraction-layer/spec.md`. Costs prose length in every
article that ever gets a correction. Degrades safely: a mislabelled supersession
leaves both statements readable rather than deleting the right one.

**An article family.** v1 and v2 stay separate articles and a canonical article
points at the current one. Cleanest history, and the worst fit for retrieval:
catalog lines double, and page selection has to learn that two of the candidates
it just retrieved are the same thing at different times.

Recommendation: current-plus-trail, for two reasons beyond taste. Retrieval
reads article bodies, so a silent deletion makes "what changed" unanswerable
without going back to `raw/`. And it is the failure mode that matters: the model
will sometimes be wrong about what supersedes what, and a wrong trail entry is
recoverable where a wrong deletion is not.

## Three ways to build it

**A — replace primitive plus recency, no new detection.** Add a replace action to
`merge-diff.md` and a supersession rule to `merge-rewrite.md`. Carry the document
date into what the writer sees. Stop flattening multiple sources into one bag, so
the writer gets per-source blocks it can order.

Smallest change that can work, and it covers both shapes: Shape A because the
revised extraction merges against an article it can now correct, Shape B because
v2 merges into the article v1 wrote and can correct it there. It does not need any
new artifact or any new LLM pass.

Two costs that are not obvious. Editing both merge prompts moves
`write_prompt_version` (`py/src/kb_ai/core/merge.py:504-533`), which is recorded
and reported but gates nothing, so existing articles are not revisited — the fix
applies to future merges only. And per-source blocks change what the *create* path
sees too, which is a prose-quality change to every new article, not just to
corrections. That needs measuring, not assuming.

**B — A plus explicit lineage.** Add a step that records the claim "document X
supersedes document Y" as its own artifact, reports it, and feeds it to merge as an
instruction rather than leaving the model to infer it. Signal candidates: the raw
frontmatter `date` plus title similarity plus a shared `source`/`url`, or an LLM
pass over the document catalog.

Buys reliability where the text is ambiguous, and an auditable claim a human can
correct. Costs a new artifact, and the LLM variant costs money per document on a
path that currently costs none. This should be justified by a measured failure of
A, not bought upfront.

**C — recompose instead of patching.** When any source of an article is revised,
rewrite the article from all of its sources' extractions rather than patching the
existing text. Supersession then becomes ordering inside a single write call and
needs no replace primitive at all.

The only option that converges: nothing accumulates, because nothing is carried
forward. It is also the expensive one, and it discards hand edits to articles. The
cost basis already exists — a full recompile of the 108-document reference KB is
30.2 USD against 17.5 USD for an extraction pass
(`docs/articles/kaas-four-layers.md:185-191`), and a separate measurement over 88
documents compiled twice produced 48 articles once and 98 the other time
(`:308-313`), so recomposition inherits the classify instability too.

Recommendation: A as the shipping increment, because it is the one that unblocks
the others and needs no new artifact. C is the eventual answer for revised
documents and deserves its own feature once article-level reproducibility is worth
paying for. B only on evidence.

## Decisions taken

D1 and D2 were decided on 2026-08-10. D3, D4 and D5 stay open, and the
implementation spec still has to answer them.

### D1 — the body states the current claim plus a superseded trail

The article states what is true now, and carries an explicit note of what the
previous claim was and when it stopped being true. The old sentence is replaced by
the pair, not kept alongside it: an article that states both as current is the bug
this feature exists to fix.

Format, fixed by example — the convention this repository's own documents already
use:

```markdown
The gateway targets 2 000 requests per second.

[Superseded 2026-06-14 by raw/plan-v2.md: the earlier target was 1 200 requests
per second.]
```

Four rules the format carries:

- One bracketed block, opening with `[Superseded ` and closing with `]`, so a
  grep finds every trail entry in the wiki and a reader can tell prose from
  bookkeeping.
- The date is the *superseding document's* `date`, from its raw frontmatter — not
  the compile date, which moves on every recompile and would rewrite the history
  it is supposed to record.
- `by <raw path>` names the document that did it, so a reader lands in `raw/`
  rather than guessing which source to reopen.
- The block sits immediately after the statement it corrects, in the same section.
  Retrieval reads article bodies, so anything further away is a second lookup that
  page selection has no reason to make.

Chosen over latest-wins because a silent deletion makes "what did we decide
before, and when did it change" unanswerable without going back to `raw/`, and
over an article family because catalog lines would double while page selection has
no way to know two candidates are the same thing at two times. The deciding
argument is the failure mode: the model will sometimes be wrong about what
supersedes what, and a wrong trail entry is recoverable where a wrong deletion is
not.

### D2 — path A ships first, with both of its costs accepted

A replace primitive in both merge prompts, the document date carried to the
writer, and per-source blocks instead of one flat bag. B stays gated on a measured
failure of A; C stays a later feature of its own.

Both costs named under A are accepted rather than scoped out:

- **No gate on existing articles.** Editing the merge prompts moves
  `write_prompt_version`, which is recorded and reported but gates nothing, so
  articles already written keep their contradictions until something else rewrites
  them. Accepted because making it a gate is D5, and D5's recommendation is that
  it stays report-only — a prompt edit that rewrites the whole wiki is C's
  decision, not A's.
- **The create path sees per-source blocks too.** That is a prose-quality change
  to every new article, not only to corrections. Accepted with a measurement
  attached rather than on faith: the change ships only after the same documents are
  compiled through both shapes and the article prose is compared, on the corpus
  [test-set.md](test-set.md) already builds for this feature.

## Decisions needed

Each row needs an answer before implementation starts. "Done when" is the
condition that closes it.

| # | Decision | Where it lands | Options | Recommendation | Done when |
|---|---|---|---|---|---|
| D1 | What "override" produces in the article body | `prompts/defaults/merge-rewrite.md`, `merge-diff.md` | latest-wins / current-plus-trail / article family | current-plus-trail — **decided 2026-08-10** | ✅ Closed: [Decisions taken](#decisions-taken) fixes the marker format by example |
| D2 | Which build path ships first | `core/merge.py`, `core/extract.py:778-794` | A / B / C | A — **decided 2026-08-10** | ✅ Closed: [Decisions taken](#decisions-taken) accepts both of A's costs, neither scoped out |
| D3 | Where the recency signal comes from for UI-ingested documents | `internal/api/submit.go:60-65` writes raw content verbatim, with no frontmatter | write frontmatter at submit time / read the task record / accept no date for this route | write frontmatter at submit time — it is the only route that makes the date durable, and `derive` copies `raw/` so it travels (`py/src/kb_ai/derive/_layout.py:193-199`) | A decision recorded, and if "accept no date", the fallback merge behaviour for a dateless source is specified |
| D4 | Whether the date lives in `extraction/` or is read from `raw/` at write time | `storage/extraction.py:71-89` provenance, vs a read of raw frontmatter | new provenance field / read raw at write time | read raw at write time — it costs no LLM call and no `schema_version` bump, and a bump refuses every existing file (`storage/extraction.py:199-203`), which re-extracts the whole KB at 17.5 USD. No longer blocked: issue #37 is fixed, so a read of raw frontmatter returns the date on a `distill`-built KB too | Decided, and either way the tension with the extraction layer's own D1 is recorded: the write phase reading `raw/` again is a deliberate exception to "the write phase reads only from `extraction/`" (`docs/features/extraction-layer/alignment-questions.md:762-771`) |
| D5 | Whether `write_prompt_version` becomes a gate once a replace primitive exists | `core/merge.py:504-533`, `storage/lag.py` | stays report-only / becomes a gate | stays report-only for this feature — gating is what makes a prompt edit rewrite the wiki, and that is C's decision, not A's | Decided and recorded in the spec's non-goals if unchanged |

## What this document does not decide

- Whether an article can shrink. Every option above except C leaves the article
  monotonically growing in bytes even when it stops growing in claims.
- Classify's instability. The same 88 documents producing 48 or 98 articles
  (`docs/articles/kaas-four-layers.md:308-313`) is upstream of everything here and
  is untouched by any option.
- Orphaned extractions, which remain a stated non-goal of the extraction layer.
