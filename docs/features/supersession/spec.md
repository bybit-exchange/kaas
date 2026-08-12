# Supersession A1: carry ordering to the writer, report what it cannot act on

Date: 2026-08-12
Slug: `supersession`
Status: aligned for A1. D1–D5 settled (D1 and D2 in
[design-options.md](design-options.md) on 2026-08-10; the trigger condition, the
A1/A2 split, D3, D4 and D5 on 2026-08-12). A2 is sketched in
[Non-goals](#non-goals) and specified separately.

**On identifiers.** `A1` and `A2` always mean the two increments of build path A.
`D1`–`D5` always mean the design decisions carried from
[design-options.md](design-options.md). `P1`–`P10`, `N1`–`N4` and `U1`–`U4` always
mean fixture cases from [test-set.md](test-set.md). Acceptance criteria in this
spec therefore use two-letter prefixes, and non-goals use `NG`, so that no
identifier means two things across the feature's documents.

## Background

A project plan exists as v1 and v2. Compiling both should leave an article that
states v2. Today the article can state both and contradict itself.

[design-options.md](design-options.md) analyses the gap and settles two decisions:
the article body states the current claim plus a `[Superseded …]` trail (D1), and
build path A ships first — a replace primitive, the document date carried to the
writer, and per-source blocks instead of one flat bag (D2).

Reading the write path against those decisions splits path A in two, and that
split is why this spec exists. `compile.py` has three write paths, not two:

```python
# py/src/kb_ai/commands/compile.py:533   article does not exist
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
new_content = create_new_article(article_type, title, combined, ", ".join(merge_rels), ...)

# py/src/kb_ai/commands/compile.py:553   one source, article exists
new_content = merge_into_article(art_path, old_content, extraction, rel, ...)

# py/src/kb_ai/commands/compile.py:570   many sources, article exists
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
new_content = merge_into_article(art_path, old_content, combined, ", ".join(merge_rels), ...)
```

`merge→create` composes from scratch, so given the document dates and one block
per source it can simply state v2 — nothing in the article constrains it. The two
merge paths run against existing `old_content` through prompts whose only actions
are `append_to_section` and `new_section`. Better ordering information does not
help them: there is no action that retracts.

So the ordering signal and the replace primitive fix different paths, and only the
second can destroy correct content. This spec covers the first — **A1** — which is
also a strict prerequisite for the second, because the replace action has to reason
over exactly the dates and per-source blocks A1 introduces.

Three facts from the corpus shape the acceptance criteria.

**The evidence base is one ambiguous failure.** Of ten positive cases in
[test-set.md](test-set.md), two are adjudicated: P6 succeeds today and P1 fails.
P1 is a *dropped-claim* case — v2 deleted the section rather than contradicting it
— and test-set.md calls its status an open labelling rule. There is currently no
confirmed contradiction-type failure. Labelling the remaining positives costs no
LLM spend and is a precondition for scoring anything.

**The fixture as built tests the path A1 can fix.** 38 documents compiled into a
fresh KB routes each version chain into one `merge→create` call. That is very
likely why P6 succeeded, and it means an unstaged run would score A1 on the easy
path and report it as a general result.

**No date reaches the writer on any route.** `core/merge.py:95` emits
`- Source: {source_path}` and nothing else.

## Goals

- **G1.** The writer is told, for every source it composes from, when that source
  is dated — on all three ingest routes.
- **G2.** The writer receives one block per source rather than one flattened bag,
  so a claim is attributable to the document that made it.
- **G3.** Ordering information that cannot be safely acted on is reported to an
  operator instead of being acted on.
- **G4.** No write path gains the ability to remove or replace text. A1 cannot
  regress a correct article.
- **G5.** The fixture measures the merge paths, not only `merge→create`.

## Non-goals

- **NG1. The replace primitive (A2).** No new action in `merge-diff.md` or
  `merge-rewrite.md`. The comment at `compile.py:628` — "merge paths are additive
  -- merge-diff.md offers only append_to_section and new_section" — stays true
  after A1 and changes only with A2.
- **NG2. The `[Superseded …]` trail (A2).** A1 emits no markers. On `merge→create`
  its best output is correct current state with no trail, which is *latest-wins*,
  the option D1 rejected. **A1 does not satisfy D1**, and a clean A1 score must not
  be read as D1 delivered.
- **NG3. Chained supersession (A2).** With no markers there is nothing for a third
  version to nest into. Whether v3 superseding what v2 already superseded keeps or
  drops the v1 entry is A2's first open question. Fixture case P4 still runs under
  A1, scored on Staleness with Trail expected 0.
- **NG4. Marking a dropped claim as superseded.** See [Trigger and
  reports](#rp-trigger-and-reports).
- **NG5. Gating on `write_prompt_version` (D5).** It stays reported, never gated.
- **NG6. Classify instability.** The same 88 documents producing 48 or 98 articles
  is upstream of everything here.
- **NG7. Whether an article can shrink.** A1 only adds.

## User stories / scenarios

- **S1.** An operator submits a plan through the web UI, then submits its v2 a week
  later. The second compile's writer knows which is newer.
- **S2.** An operator backfills v1 *after* already submitting v2. The date they
  supply on submit, not the submission order, determines what the writer is told.
- **S3.** A document is revised in place and re-extracted. The compile already
  names the articles carrying the previous version's content; that report keeps
  working.
- **S4.** Two documents whose titles differ only by a version marker land in one
  article, and the earlier asserts something the later one does not. The compile
  says so. Nothing rewrites the article on that basis.
- **S5.** A document has no date on any route. The writer is told its ordering is
  unknown rather than being given a guess.

## Acceptance criteria

### RT. Date acquisition across routes

- **RT1.** `submitRequest` (`internal/api/submit.go:25`) gains an optional `date`
  field, `json:"date"`.
- **RT2.** The submit handler writes YAML frontmatter ahead of the content at
  `internal/api/submit.go:65`, carrying at least `date`, plus `source` and `title`
  where already known. `raw/<uuid>.md` stops being byte-verbatim on this route;
  `distill` already set that precedent by prepending `<!-- source: … -->`.
- **RT3.** When `date` is absent the handler stamps the current time. When it is
  present but unparseable it returns 400 — the caller can fix that one.
- **RT4.** `ContentHash` (`internal/store/store.go:53`) is computed over what RT2
  actually wrote, so dedup and the composition gate see one consistent document.
- **RT5.** `store.Task.CreatedAt` (`internal/store/store.go:63`) stays a task
  record field and is never read by the write phase. The durable date lives in
  `raw/`, which is what `derive` copies (`derive/_layout.py:193`).
- **RT6.** The leading-HTML-comment skip currently private to
  `_document_frontmatter` (`py/src/kb_ai/storage/index.py:147`) is promoted to a
  shared helper, and both readers use it. `design-options.md:57-60` calls for this
  the moment a second reader appears; A1 adds one.
- **RT7.** No re-ingest and no re-extraction is required for any existing KB. A1
  reads a field already on disk for the fetch and `distill` routes.

### WP. Writer payload

- **WP1.** The merge user message carries a per-source `- Date: <value>` line
  beside the existing `- Source:` line (`core/merge.py:95`).
- **WP2.** The date is read from the source's raw frontmatter at write time (D4).
  This is a deliberate exception to the extraction layer's rule that the write
  phase reads only from `extraction/`
  (`docs/features/extraction-layer/alignment-questions.md:762-771`), recorded here
  because the alternative — a new provenance field at `storage/extraction.py:83` —
  costs a `schema_version` bump, and `storage/extraction.py:199-202` refuses every
  existing file on a bump, re-extracting the whole KB at 0.0551 USD per document.
- **WP3.** `_combine_extractions` (`core/extract.py:778`) stops flattening. The
  user message emits one labelled block per source.
- **WP4.** All four call sites move to the new shape: `compile.py:533`, `:570`,
  `pipeline/_phase_write.py:66`, `:84`. The `create_new_article` and
  `merge_into_article` signatures that today take `combined, ", ".join(merge_rels)`
  change with them.
- **WP5.** Blocks render oldest to newest. Undated sources come last, in path
  order, so the rendering is deterministic across runs — `compile.py` writes
  article groups on 16 workers and raw-scan order is not stable across ingests.
- **WP6.** The system prompt states that blocks run oldest to newest and that an
  undated source's position carries no ordering claim. It goes in the system
  prompt, not the user message, because that is where an instruction is applied
  reliably.
- **WP7.** Identical-checksum duplicates contribute one block, not two. The U1–U4
  controls exist because 55 lineage groups are the same bytes ingested twice.

### BG. Budget and truncation

- **BG1.** Budget is allocated **newest block first**. The existing single-budget
  truncation (`core/merge.py:102-143`, field priority with exponential backoff on
  list fields) received one flat extraction; with per-source blocks, filling
  oldest-first would truncate or drop the newest source — precisely backwards for
  supersession.
- **BG2.** When the budget cannot fit every block, whole trailing (oldest) blocks
  are dropped rather than a block being left structurally broken.
- **BG3.** The truncation notice (`core/merge.py:145-154`) names which source's
  block was cut or dropped.
- **BG4.** A budget too small for even the newest block degrades to that block
  truncated by the existing field priority, not to an empty message.

### RP. Trigger and reports

- **RP1.** The trigger for treating a claim as superseded is **explicit
  contradiction only**. A claim absent from a later source's extraction is not
  evidence of retraction: extraction is lossy summarization, and under A1 the
  writer never sees raw text, so absence and "not extracted" are
  indistinguishable at the point of decision.
- **RP2.** Shape A dropped claims are already reported. `compile.py:329` marks a
  re-extracted document as revised and `:632-640` names the articles still
  carrying the previous version. A1 verifies this still fires; it does not rebuild
  it.
- **RP3.** Shape B dropped claims get a new report line: a lineage group whose
  members share an article, where the earlier member asserts something the later
  one does not. Report only.
- **RP4.** The lineage rule for RP3 is the one [test-set.md](test-set.md) already
  validated on the corpus — same title after stripping a trailing version marker,
  different `id` — including both exclusion rules the data forced out:
  cross-source title collisions (a document and the recording of the meeting about
  it) and person-name collisions.
- **RP5.** Nothing from RP3 or RP4 is fed to the model. It informs an operator; it
  does not enter a prompt. That is what keeps the lineage heuristic clear of D2's
  gate on build path B.

### PV. Prompt version and rollout

- **PV1.** `write_prompt_version` (`core/merge.py:504-533`) moves, because WP6
  edits a system prompt and the hash covers the system prompt renderings
  (`core/merge.py:528`). Per D5 it gates nothing, so the cost is a report saying
  every article is behind — noise, not spend.
- **PV2.** The `write_prompt_version` docstring at `core/merge.py:512-518` is
  updated. "Until a supersession path exists, an operator reading the count is the
  useful thing" describes the world before A1.
- **PV3.** Existing articles are not revisited. A1 applies to future write ops.

### FX. Fixture and scoring

- **FX1.** The `/tmp/supersession/` scripts move to `py/scripts/` with tests.
- **FX2.** The fixture runs staged, **one stage per version**. Stage N compiles
  version N into the wiki stage N−1 produced, so the merge paths are exercised at
  all, and P4's four-version chain merges repeatedly into an article that earlier
  versions already wrote.
- **FX3.** Labels for P2–P5 and P7–P10 — `superseded`, `replacement`, `control` —
  are drafted from the diffs and the migrated extractions, then human-confirmed
  before they score anything.
- **FX4.** A pre-A1 baseline is measured on the staged fixture, before any code
  changes. The existing `wiki/` in `data/kb-knowledge` was written by prompt
  versions that no longer exist and is an existence proof, not a baseline.
- **FX5.** Scoring uses test-set.md's columns. Under A1, Trail is expected 0 on
  every case; Staleness on the merge-path stages is the discriminating column.
  False positives stay at 0 on N1–N4 and no duplicate contributes twice on U1–U4.
- **FX6.** The create-path prose comparison D2 committed to runs as a second arm
  *after* WP3 lands, against FX4's baseline: the same documents through the flat
  bag and through per-source blocks, article prose compared. It cannot be part of
  FX4 itself, because one of its two arms is the change being measured.
  Per-source blocks alter every new article, not only corrections.
- **FX7.** A1 is judged on Staleness across FX4's baseline and the post-A1 run.
  Clearing the positives without tripping N1–N4 is what makes A2 optional rather
  than assumed.

### VF. Verification

- **VF1.** Unit tests for the shared frontmatter reader (RT6): leading HTML
  comments, no frontmatter at all, malformed `date`, and a `date` present but
  empty.
- **VF2.** Unit tests for block ordering (WP5, WP7): all dated, none dated, mixed,
  and identical checksums.
- **VF3.** Unit tests for newest-first budget allocation (BG1–BG4) under a budget
  too small for all blocks, asserting which block survives.
- **VF4.** Unit tests for the lineage rule (RP4), including both exclusion cases.
- **VF5.** Go tests for submit with a valid `date`, without one, and with an
  unparseable one, asserting the frontmatter written and the resulting
  `ContentHash` (RT1–RT4).
- **VF6.** A both-routes parity test — CLI and worker producing identical blocks
  for the same documents in one process — mirroring the extraction layer's T14.
- **VF7.** A real staged run on the fixture, with spend recorded.

## Resolved questions

| # | Question | Answer |
|---|---|---|
| D1 | What "override" produces in the body | Current claim plus a `[Superseded …]` trail. Decided 2026-08-10. A1 does not deliver it (NG2) |
| D2 | Which build path ships first | A, split into A1 and A2. A1 first; A2 bought only if A1 fails the positives. Decided 2026-08-12 |
| D3 | Recency signal for UI-ingested documents | Optional `date` on submit, written as frontmatter, falling back to the stamp time (RT1–RT4). Ingest time is not authorship time, which is why the field is exposed rather than inferred |
| D4 | Date in `extraction/` or read from `raw/` | Read from `raw/` at write time (WP2) |
| D5 | Does `write_prompt_version` become a gate | No. Stays report-only (NG5, PV1) |
| Q1 | What triggers a supersession marker | Explicit contradiction only. Dropped claims escalate to a report (RP1–RP3) |
| Q2 | Fallback for a dateless source | No date line, and the prompt says ordering is unknown (WP6, S5). Never file mtime: `derive` copies `raw/` (`derive/_layout.py:193`), which rewrites mtime to the copy time |

## Open questions

None blocking A1. Carried to A2: the trail format for chained supersession (NG3),
and whether A2 needs raw text at write time in order to act on dropped claims
(RP1).

## Implementation sequencing

1. **Shared reader and the submit route.** RT6, then RT1–RT5 with VF1 and VF5.
   Independently useful: it dates the UI route's documents whether or not the rest
   lands.
2. **Per-source blocks.** WP3, WP4, WP1, WP2, WP5, WP7 with VF2 and VF6. The four
   call sites move together, and the signature change means grepping for every
   caller of `create_new_article` and `merge_into_article`.
3. **Budget.** BG1–BG4 with VF3.
4. **Prompt and version.** WP6, PV1, PV2.
5. **Reports.** RP2 verified, then RP3–RP5 with VF4.
6. **Fixture.** FX1, FX2, FX3, then the FX4 baseline, then VF7 with FX5, FX6 and
   FX7.

FX3's labelling has no dependency on steps 1–5 and costs no LLM spend, so it can
run in parallel from the start. It is the precondition for A1 meaning anything.
