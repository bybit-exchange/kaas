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
split is why this spec exists. `compile.py` wrote through four call shapes, not
two — three off the merge ops and one more off the create ops. The code below is
the write path **as it stood before A1**, quoted because that is the inventory the
split was reasoned from; steps 2–4 have since moved all seven call sites onto
`build_source_blocks` (WP4) and retired `_combine_extractions`, so the line
anchors resolve in this spec's history rather than in the file today:

```python
# py/src/kb_ai/commands/compile.py:533   article does not exist
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
new_content = create_new_article(article_type, title, combined, ", ".join(merge_rels), ...)

# py/src/kb_ai/commands/compile.py:558   one source, article exists
new_content = merge_into_article(art_path, old_content, extraction, rel, ...)

# py/src/kb_ai/commands/compile.py:570   many sources, article exists
combined, merge_rels = _combine_extractions([(rel, ext) for rel, _cs, ext, _det in merges])
new_content = merge_into_article(art_path, old_content, combined, ", ".join(merge_rels), ...)

# py/src/kb_ai/commands/compile.py:492   the create ops, one source per call,
# flipping to a merge once the file is on disk
new_content = merge_into_article(details["path"], old_content, extraction, rel, ...)
new_content = create_new_article(details["type"], details["title"], extraction, rel, ...)
```

`merge→create` composes from scratch, so given the document dates and one block
per source it can simply state v2 — nothing in the article constrains it. The
merge paths run against existing `old_content` through prompts whose only actions
are `append_to_section` and `new_section`. Better ordering information does not
help them: there is no action that retracts. The create-op pair at `:492`
straddles the two — a single-source create while the file is absent, an additive
merge once an earlier version has written it — which is what a version chain hits
when its members arrive as separate create ops.

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
LLM spend and is a precondition for scoring anything. **Superseded by FX3's
drafting**, which is quoted here as the reasoning A1's criteria were written from:
the labels now carry 44 drafted contradictions with 27 stated as current (50 and 31
as drafted, before V1, V2 and V3 removed six), so the evidence base is no longer one
case — but it is drafted evidence awaiting item-by-item confirmation, not adjudicated
evidence. **That last clause expired on 2026-08-17**: all 118 scoring rows are now
confirmed, 64 as written and 54 amended on evidence, with no verdict and no total moved,
so 44 contradictions with 27 stated as current stands as confirmed rather than drafted.
Five judgement calls remain open with Captain, each a promotion that would move one of
those numbers up.

**The fixture as built tests the path A1 can fix.** 38 documents compiled into a
fresh KB routes each version chain into one `merge→create` call. That is very
likely why P6 succeeded, and it means an unstaged run would score A1 on the easy
path and report it as a general result. The other candidate explanation — an
ordering signal inside the payload — survives verification but comes out weaker
than stated: P6's v1 carries `> 版本: v1.6` in its body while its own title and H1
say v1.5, so the accidental signal can contradict its own document about its own
version ([test-set.md](test-set.md#three-adjudicated-cases)). It still orders
correctly here, and it is one more reason to read blocker 2 as an argument for
path A.

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
  `merge-rewrite.md`. The comment at `compile.py:722` — "merge paths are additive
  -- merge-diff.md offers only append_to_section and new_section" — stays true
  after A1 and changes only with A2.
- **NG2. The `[Superseded …]` trail (A2).** A1 emits no markers. On `merge→create`
  its best output is correct current state with no trail, which is *latest-wins*,
  the option D1 rejected. **A1 does not satisfy D1**, and a clean A1 score must not
  be read as D1 delivered.
- **NG3. Chained supersession (A2).** With no markers there is nothing for a third
  version to nest into. Whether v3 superseding what v2 already superseded keeps or
  drops the v1 entry is A2's first open question. Fixture case P4 still runs under
  A1, scored on Staleness with Trail expected 0. **The question has no instance in
  this fixture, measured rather than assumed (labels.md V15, ruled 2026-08-17):** P4
  is the only staged chain longer than a pair, and inside it every predicate v3
  changes was either introduced by v2 or left untouched by it, so no nested
  supersession exists to label. P4-X1 carries the nearest shape instead — one entity
  in three states where the first step is a *drop* and the second a supersession, and
  the compiled article asserts both stale states while carrying neither replacement
  term. Answering NG3 on evidence needs a chain selected and staged for it — FX1's
  `select_cases.py` plus an FX2 stage — not a relabelling of what FX3 already holds.
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

- **RT1.** `submitRequest` (`internal/api/submit.go:30`) gains an optional `date`
  field, `json:"date"`. The UI does not send one yet (`web/src/api/submit.ts`
  carries no `date`), so until it does the field serves API callers and RT3's stamp
  serves the UI. S2 — backfilling v1 after v2 — is the story that needs the input,
  and it is not reachable from the browser until one exists.
- **RT2.** The submit handler writes YAML frontmatter ahead of the content at
  `internal/api/submit.go:70`, carrying at least `date`. `source` and `title` ride
  along **only in a block the route creates itself**, which is either a document
  that had no frontmatter or one whose frontmatter the writer could not edit (RT10)
  and so sits below a stacked block. A document whose own block *is* edited receives
  `date` and nothing else, because the alternative is writing keys over ones the
  document chose. The cost is real and accepted — the catalog's context line reads
  `date` and `source` (`storage/index.py:24`), so such a document contributes a date
  without a source. `raw/<uuid>.md` stops being
  byte-verbatim on this route; `distill` already set that precedent by prepending
  `<!-- source: … -->`. One visible consequence to expect rather than discover:
  `GET /api/tasks/{id}/content` (`internal/api/tasks.go:140`) streams the raw file,
  so the UI's preview of a pasted document now opens with the block.
- **RT3.** When `date` is absent the handler stamps the current time, *unless* the
  document may already carry one of its own — see RT9's four-way precedence, of
  which this is the last branch. When `date` is present but unparseable it returns
  400 — the caller can fix that one.
- **RT4.** `ContentHash` (`internal/store/store.go:53`) stays computed over the
  resolved content *as submitted*, before RT2 prepends anything. Hashing the
  written bytes would break deduplication outright: `tasks.content_hash` carries a
  unique index (`internal/store/sqlite/sqlite.go:83`), that index is what produces
  the 409 at `internal/api/submit.go:109`, and RT3's stamp time would make every
  resubmission of identical content unique — leaving the duplicate path
  unreachable. The compile gate is unaffected, because it checksums the file it
  reads (`storage/store.py:56`) rather than the task record.
- **RT8.** `task.FileTitle` (`internal/api/submit.go:103`) is computed from the
  original content, before RT2 prepends anything. `ExtractTitle` reads a leading
  `title:` (`internal/frontmatter/frontmatter.go:56-64`), so computing it after the
  prepend would return the title RT2 just wrote instead of the document's own.
- **RT9.** Precedence when the document already dates itself, in four branches:
  an explicit request `date` wins; otherwise the document's own leading-frontmatter
  `date` stands and the file is stored verbatim; otherwise — and this is the branch
  the textual scan forces — frontmatter the writer *cannot read* also stands, and
  the file is stored verbatim and undated, because it may be hiding a date the
  reader can see (RT10); otherwise RT3's stamp. Forced by implementing RT2 —
  a markdown file uploaded through the UI arrives on this route as `content`, so
  prepending unconditionally would overwrite an authored date with the ingest
  clock, which is the corpus defect A1 exists to fix. Two consequences of the same
  reasoning: the date is written *into* an existing block rather than as a second
  block above it, because a stacked block leaves the document's own keys in the
  body where the catalog reads them as prose; and where the document has a `date`
  the caller overrides, the *last* such key's value is replaced rather than a
  second key inserted, because PyYAML resolves duplicate keys to the last one —
  so rewriting the first leaves the document's date standing and drops the
  caller's, which is the same silent loss by a different route.
- **RT10.** The Go writer decides "does this document have a date" textually, with
  no YAML parser. Not for want of a dependency — `gopkg.in/yaml.v2` is already in
  `go.mod` indirectly — but because neither available parser answers the question
  asked: `yaml.v2` does not reproduce PyYAML's resolver, so it would disagree with
  the reader about what counts as a date, and editing one key while preserving the
  document's own comments, key order and quoting needs node-level round-tripping
  rather than unmarshal-and-remarshal. A textual scan that is honest about its
  limits is the smaller risk. So the criterion is: a `date` key at the block's own
  indentation, its key unquoted before comparison, its colon followed by a space
  as YAML requires, behind the same leading-comment skip RT6 shares on the Python
  side, and taking the last such key rather than the first.
  Because the scan is an approximation, it is asymmetric on purpose: the question
  it answers is not "is this dated" but "may this be dated", and it errs towards
  yes so the clock is never stamped over something unread. Seven boundaries, each
  measured against the real reader rather than assumed:
  - A `date` nested under another key, or one appearing inside a literal scalar,
    is not the document's date and is left untouched. The block gets its own
    `date` at the top level instead.
  - A `date` value that YAML resolves to something other than a date — a quoted
    `"2020-01-01"`, or prose — counts as *dated* here, so it is preserved rather
    than overwritten. Making sense of it is the write phase's job (WP8).
  - The block's indentation is the level its **keys** sit at, not its first
    non-blank line's. A YAML comment carries indentation of its own and none of
    the block's, and taking the level from one put the inserted `date` two columns
    in above a key at column 0 — which PyYAML rejects outright, so a document that
    arrived dated and titled came back with neither.
  - A complete block whose first meaningful line is not a plain `key: value` —
    flow syntax (`{date: …}`), a sequence, a tab for indentation, a colon without
    the following space — is *unreadable*, not absent, and the two are handled
    differently. PyYAML may well read a date out of it, so it counts as possibly
    dated: with no explicit caller date the document is stored verbatim and reaches
    the writer undated (the S5 path). Only an explicit caller date, which outranks
    the document's own, is written — and then as a block stacked above, because
    inserting a block key above a flow mapping is invalid YAML and would cost the
    document every label it had, while a stacked block keeps all of its bytes and
    still parses.
  - A leading BOM is stepped over on both sides rather than shadowing the block.
    It is an encoding artefact, not content, so it stays at the head of the file
    while `date` is written into the block behind it, and the shared reader strips
    it before splitting. Left alone it made a BOM'd document read as having no
    frontmatter at all, which on this route is not merely unlabelled: the clock
    would have been stamped over the date such a document declared.
  - A top-level entry whose **value the reader cannot parse** makes the whole block
    unreadable, and the one shape checked is a plain scalar holding `": "` or ending
    in `":"` — `title: Q3: the plan`, which PyYAML refuses outright. Quoted and flow
    values are exempt because both parse, and only the block's own level is examined,
    because the prose inside a literal scalar is indented deeper and its colons are
    not YAML's. This is the one place the scan *gains* something rather than merely
    avoiding harm: such a document never had readable frontmatter, so stacking a
    block above it makes it datable for the first time. It is not a YAML validator
    and does not try to be; what it misses leaves a document undated, which is what
    it already was.
  - A `date` key whose **value is on the lines below it** — a nested mapping, a
    sequence, a literal scalar — is not replaceable, because rewriting the key
    orphans the value: the block stops parsing and the document loses every label
    it had, or the caller's date is folded together with the document's into one
    string. Such a block is unreadable, handled as above. This is the same class as
    the comment-indent case: a line-at-a-time scan believing it has seen the whole
    of a value.
  The delimiter cutset is the other place the two ends have to agree exactly, and
  it is two sets rather than one. The reader closes a block with `str.rstrip()`,
  which removes all 29 characters `str.isspace()` accepts, so the writer spells
  that set out rather than using `unicode.IsSpace` — which omits `U+001C`–`U+001F`
  and tracks a table that can shift under a Go release. But 10 of those 29 are also
  characters `str.splitlines()` breaks on, so the reader's *line* ends at one where
  this scan's does not: trimming them would make a line look like a delimiter while
  the reader was looking at something else entirely. A block containing one is
  therefore reported unreadable rather than guessed at — the answer that is safe in
  both directions, since reporting "no block" would have the clock stamped on top of
  a date the document does declare.
- **RT11.** A `date` the caller supplies must name a year of 1 or later. Go's
  `time.Parse` accepts year zero and PyYAML's timestamp constructor then raises
  `ValueError`, which is not a `yaml.YAMLError`: one such file under `raw/` aborted
  `build_document_catalog` for every document beside it, with nothing in the
  product able to remove it. Rejected on submit (400), and the shared reader also
  widens its own guard, because a hand-authored file can still carry one. The
  reader's guard takes `OverflowError` with it: PyYAML 6.0 subtracted a timestamp's
  UTC offset instead of attaching it as `tzinfo`, so `0001-01-01T00:00:00+02:00` —
  a date the year guard accepts — overflowed `datetime.min`. `uv.lock` pins 6.0.3,
  where it does not, but `pyproject.toml` allows `>=6.0`.
- **RT12.** `POST /api/submit/files` (`internal/api/submit_files.go:153-186`,
  `:362`) is a fourth ingest route — the multipart and ZIP upload behind the UI's
  drag-and-drop — and A1 leaves it undated. It is out of step 1 deliberately:
  those documents degrade to S5 rather than being wrong, and the route already
  computes its hash and `FileTitle` before writing, so it is a small change when
  taken. Recorded because G1 says "all three ingest routes" and this is the
  likeliest way an operator ingests a folder of plans, so the gap has to be
  visible rather than implied by RT7's silence.
- **RT5.** `store.Task.CreatedAt` (`internal/store/store.go:63`) stays a task
  record field and is never read by the write phase. The durable date lives in
  `raw/`, which is what `derive` copies (`derive/_layout.py:193`).
- **RT6.** The leading-HTML-comment skip currently private to
  `_document_frontmatter` (`py/src/kb_ai/storage/index.py:147`) is promoted to a
  shared helper, `read_document_frontmatter` in `py/src/kb_ai/_frontmatter.py`, and
  both readers use it. `design-options.md:60-63` calls for this the moment a second
  reader appears; A1 adds one. Promoting it is also what makes the Go writer's
  agreement checkable: the skip rules, the delimiter cutset and the BOM are now
  stated once per language instead of once per call site.
- **RT7.** No re-ingest and no re-extraction is required for any existing KB. A1
  reads a field already on disk for the fetch and `distill` routes.

### WP. Writer payload

- **WP1.** The merge user message carries a per-source `- Date: <value>` line
  beside the existing `- Source:` line (`core/merge.py:95`). One renderer serves
  both writers (`core/merge.py:320`, `:596`), so no path is missed — but
  `_estimate_full_extraction_size` (`core/merge.py:72`) spells the same prefix out
  a second time to size the untruncated text, and BG3's notice fires on those two
  disagreeing. Both sites gain the line together.
- **WP2.** The date is read from the source's raw frontmatter at write time (D4).
  This is a deliberate exception to the extraction layer's rule that the write
  phase reads only from `extraction/`
  (`docs/features/extraction-layer/alignment-questions.md:762-771`), recorded here
  because the alternative — a new provenance field at `storage/extraction.py:83` —
  costs a `schema_version` bump, and `storage/extraction.py:199-202` refuses every
  existing file on a bump, re-extracting the whole KB at 0.0551 USD per document.
- **WP3.** `_combine_extractions` (`core/extract.py:778`) stops flattening. The
  user message emits one labelled block per source.
- **WP4.** Seven call sites move to the new shape, not four. Anchors here are
  pre-A1, like the Background inventory they came from. `create_new_article` and
  `merge_into_article` took `extraction: ExtractionResult, source_path: str`
  (`core/merge.py:247-252`, `:574-579`), so changing that signature reaches the
  single-source callers as well: `compile.py:492`, `:495` and `:558` each pass one
  block. The four combined callers — `compile.py:533`, `:570`,
  `pipeline/_phase_write.py:66`, `:84` — stop flattening into
  `combined, ", ".join(merge_rels)`.
- **WP5.** Blocks render oldest to newest. Undated sources come last, in path
  order, so the rendering is deterministic across runs — `compile.py` writes
  article groups on 16 workers and raw-scan order is not stable across ingests.
- **WP6.** The system prompt states that blocks run oldest to newest and that an
  undated source's position carries no ordering claim. It goes in the system
  prompt, not the user message, because that is where an instruction is applied
  reliably.
- **WP7.** Identical-checksum duplicates contribute one block, not two. The U1–U4
  controls exist because 55 lineage groups are the same bytes ingested twice.
- **WP8.** A `date` the reader hands back as something other than a date object —
  a quoted `"2020-01-01"`, `last Tuesday`, anything YAML resolved to a string — is
  parsed here if it parses, and otherwise treated as absent: no date line, and the
  block sorts with the undated ones under WP5. RT10 explains why the submit route
  cannot make this call instead: it has no YAML parser, so it cannot tell a date
  from a string that looks like one, and preserving the value is the only safe
  thing it can do.
- **WP9.** Two blocks that share a `- Date:` line carry **no ordering claim relative to
  each other**, and the system prompt says so — what WP6 states about an undated block's
  position holds equally of a same-day pair. They still render in path order, for
  reproducibility rather than recency, exactly as undated blocks do under WP5. Raised as
  queue item V20 by ruling V19 and **ruled 2026-08-16** in this form, against the
  alternative of breaking the tie on a stated signal. The alternative loses on
  measurement: on the reference KB 160 of 397 multi-source articles carry a same-day pair
  (**412 pairs** counting one block per checksum as WP7 requires, 414 before that dedup —
  re-measured at implementation time, since the 156 and 384 first recorded here deduped on
  the body with frontmatter stripped, which collapses 83 groups whose members are dated
  differently and is the one distinction this population is about), and of those a filename
  version marker appears in 9, names a
  document revision in 2, and survives inspection in **1** — the other of the two,
  `…测试报告-v100.md`, marks the *tested skill's* version 1.0.0 against a sibling
  reporting 3.1.0. A body-stated date fares no better: present in both members of 9
  pairs, unambiguous and differing in 5, a revision pair in 1. A rule in the system
  prompt applies to every payload, so a signal worth 1 pair in 412 cannot be it. Reading
  body dates is also A2's question and is left there (see the closing note): of the 10
  same-day sources whose body date contradicts their frontmatter, 7 point earlier and 2
  later, so the corpus does not establish which date is the document's own. **BG1 needs
  no change of direction** — it already breaks the tie path-ascending and so does the
  render, so both serve the same block first; the conflict was WP6 calling that block
  older while BG1 called it newer, and withdrawing the claim ends it. What BG1 restates
  is its own basis: newest known *day* first, ties broken on path for stability, with no
  claim that the block served first is the newer. Scope across the eight cases: three
  render a source after their own chain head — P5, P7 and P10 — but only P5's is a chain
  member, and the same-day co-sources P7 and P10 render last assert the replacements or
  nothing, so no stale row outside P5 turns on this either way. P5 does not become
  gate-scoreable: withdrawing the claim leaves its chain unordered in the payload, and
  the six-day gap its two bodies actually state makes the shared `date: 2026-03-13` an
  error in v3's frontmatter rather than a property of the corpus. That was queue item
  V21, **ruled 2026-08-16**: the fixture keeps v3 as staged and P5 is reported as an A2
  body-date case (FX3, FX5). The ruling also corroborated this one's basis on the whole
  corpus rather than on 10 same-day sources — of the 505 documents stating a body date,
  109 state one *earlier* than their frontmatter date against 101 later, near-even rather
  than the 7-to-2 the sample showed — so a body-date tie-breaker has no established
  direction to move documents in, and reading body dates stays A2's question.

### BG. Budget and truncation

- **BG1.** Budget is allocated **newest block first**. The existing single-budget
  truncation (`core/merge.py:102-143`, field priority with exponential backoff on
  list fields) received one flat extraction; with per-source blocks, filling
  oldest-first would truncate or drop the newest source — precisely backwards for
  supersession. Precisely: dated blocks newest **day** to oldest, ties broken on path
  for stability, then undated blocks in path order. This is *not* the render order
  reversed, because WP5 sorts undated blocks last: reversing would rank the blocks that
  make no recency claim above the one source known to be newest, and WP6 says their
  position carries no such claim to read. An undated source is the first to give way,
  including to a dated source older than it may turn out to be — the guarantee BG1 buys
  is about the newest *known* source. Same-day blocks are peers here in the same sense
  WP9 gives them in the prompt: one of them is served first because the order has to be
  stable, not because it is the newer, and nothing downstream may read priority as
  recency within a day.
- **BG2.** When the budget cannot fit every block, whole blocks are dropped from
  the bottom of BG1's priority order rather than a block being left structurally
  broken. Not "trailing", which is the same thing only while every block is dated;
  once one is not, the order that governs is BG1's and not WP5's.
- **BG3.** The truncation notice (`core/merge.py:145-154`) names which source's
  block was cut or dropped.
- **BG4.** A budget too small for even the first block in BG1's order — the newest
  dated source, or the first undated one when nothing is dated — degrades to that
  block truncated by the existing field priority, not to an empty message.

### RP. Trigger and reports

- **RP1.** The trigger for treating a claim as superseded is **explicit
  contradiction only**. A claim absent from a later source's extraction is not
  evidence of retraction: extraction is lossy summarization, and under A1 the
  writer never sees raw text, so absence and "not extracted" are
  indistinguishable at the point of decision.
- **RP2.** Shape A dropped claims are already reported. `compile.py:415` marks a
  re-extracted document as revised and `:721-734` names the articles still
  carrying the previous version. A1 verifies this still fires; it does not rebuild
  it. The one place A1 could have broken it is WP7: two paths holding identical
  bytes now contribute one block, and a revised document on the collapsed path must
  still name its article. It does — the ops bookkeeping reads the merge list rather
  than the surviving blocks — and that is pinned by a test rather than left to the
  comment that says so.
- **RP3.** Shape B gets a new report line: a lineage group whose members share an
  article. Report only. **The "where the earlier member asserts something the later
  one does not" condition is dropped**, because it selects nothing: measured over
  the corpus's stored extractions, a claim-text comparison fires on 35 of the 35
  checkable (article, group) pairs at every threshold from 0.55 up (331 claims
  flagged at 0.55, 385 at 0.80), and the best-match similarity distributions do not
  separate — median 0.47 on real version pairs against 0.36 on recurring series.
  Claims are restated in new words between versions, so "not present in the later
  member" is the normal case rather than the exceptional one. The cheap proxy fails
  in the other direction: "the later member asserts fewer claims" holds for 14 of
  those 35 pairs and *excludes* P6, the one adjudicated shape-B success, whose claim
  count grows 26 → 33. An LLM judge would decide it, and RP5 forbids one. So the
  report names the group and leaves the reading to the operator, which is what G3
  asks for.
- **RP4.** The lineage rule for RP3 is the one [test-set.md](test-set.md) validated
  on the corpus — same title after stripping a trailing version marker, different
  `id` — including both exclusion rules the data forced out: cross-source title
  collisions (a document and the recording of the meeting about it) and person-name
  collisions. Three details the reconstruction had to settle, because the script
  that produced test-set.md's counts was thrown away and only its output survived:
  - The marker requires a `v`. A bare trailing number would collapse `Cost Report
    2025` and `Cost Report 2026` into one chain, and an operator cannot tell that
    error from a real group. Both bracket forms and any number of dotted components
    count: the corpus holds `(v3)`, which the original script matched, and `v1.0.0`,
    which it did not — so it reported one group fewer than the data has. Titles are
    compared case-insensitively for the same reason, which the original was not.
  - The cross-source exclusion is implemented as `source` being part of the grouping
    key, so it excludes the *pairing* rather than the title: two recordings of one
    meeting share a source and stay a group, while the design document under the
    same title is not joined to them.
  - Person names come from the KB's person pages *and* from the configured people
    allowlist, since the pages are stubs a later phase generates and a one-to-one
    ingested on a first compile would otherwise read as a version chain.

  What the rule cannot do, recorded because RP3's usefulness rests on it: a
  recurring meeting series has one fixed title and a new `id` per occurrence, so it
  is a lineage group by any title rule. Of the 41 (article, group) pairs on the
  reference corpus, 4 are real version chains and 37 are recurring series — one
  daily standup series contributes 11 members to a single article. The version
  marker is reported as a triage key and marked groups are listed first, but it is
  not a filter: P7, P8 and P9 are shape-B positives whose two versions share a title
  verbatim, so filtering on the marker would silence two of the five cases
  judged on the gating column, plus P8, the one case carrying no accidental ordering cue
  at all.
- **RP5.** Nothing from RP3 or RP4 is fed to the model. It informs an operator; it
  does not enter a prompt. That is what keeps the lineage heuristic clear of D2's
  gate on build path B. Held structurally rather than by inspection: the rule lives
  in `storage/lineage.py`, `core/merge.py` does not import it (asserted over the
  module's imports), the writer's entry points take source blocks and nothing else,
  and the report is built after the last write op.

### PV. Prompt version and rollout

- **PV1.** `write_prompt_version` (`core/merge.py:937-966`) moves, because WP6
  edits all three system prompts and the hash covers the system prompt renderings
  (`_write_stage_renderings`). Per D5 it gates nothing, so the cost is a report
  saying every article is behind — noise, not spend.
- **PV2.** The `write_prompt_version` docstring (`core/merge.py:939-966`) is
  updated. "Until a supersession path exists, an operator reading the count is the
  useful thing" describes the world before A1. The same sentence is duplicated in
  `storage/lag.py`'s module docstring, which is updated with it; `commands/check.py`
  and `compile.py:721-725` carry the additive-merge claim only, which A1 leaves
  true (NG1).
- **PV3.** Existing articles are not revisited. A1 applies to future write ops.

### FX. Fixture and scoring

- **FX1.** The `/tmp/supersession/` scripts move to `py/scripts/` with tests — but
  only the two that will run again. What landed is `select_cases.py`, which finds the
  chains and stratifies them, and `stage_fixture.py`, which builds FX2's stages.
  The corpus conversion and the conformance pass are not ported: both ran once
  against a gitignored KB with absolute paths, their output is on disk and verified
  by `kb-ai check`, and the scripts themselves are gone. test-set.md's Regenerating
  section records that instead of pretending they are reproducible.
  The selector had to be rebuilt rather than moved, because the script that produced
  test-set.md's counts was deleted and only its output survived. Reconstructed
  against that output it reproduces every diffstat and every stratum on the corpus,
  and it corrects three defects in the original: `sources:` entries holding a
  comma-joined batch are split apart (which is what the shared-article column
  undercounted), the append-only test runs before the similarity test, and shape B
  carries RP4's exclusions rather than having them applied by hand afterwards.
- **FX2.** The fixture runs staged, **one stage per version**. Stage N compiles
  version N into the wiki stage N−1 produced, so the merge paths are exercised at
  all, and P4's four-version chain merges repeatedly into an article that earlier
  versions already wrote.
- **FX3.** Labels for P2–P5 and P7–P10 — `superseded-contradiction`,
  `superseded-drop`, `replacement`, `control` — are drafted from the diffs and the
  migrated extractions, then human-confirmed before they score anything. Drafted
  2026-08-14 in [labels.md](labels.md); the two rulings the drafts surfaced were
  taken 2026-08-15. **Confirmed 2026-08-17**, which closes this criterion's gate: eight
  case passes settled all 118 scoring rows plus P2's 18 — 64 confirmed, 54 amended, none
  rejected — and **no pass moved a total**, so the figures below are the confirmed ones.
  Five judgement calls stay open with Captain, each a promotion whose other branch would
  move one of those totals; they are named at the top of [labels.md](labels.md). **P2 is withdrawn from the positives** and kept as a
  counter-case, because its frontmatter date inverts its content order and scoring
  it would credit A1 for asserting a wrong order — and **ruling V10 2026-08-16 makes
  that permanent**: in the section both files date 04-17 the pair agrees verbatim on
  seven of the eight drafted rows, the eighth is an in-place amendment of one figure,
  and it leaves no residue in the article, so the inverted reading has nothing to score
  either; **P7's measurement-time reading
  is accepted**, so it keeps its 8 contradictions. The scoring set is therefore
  seven drafted cases plus P6, carrying — after V1, V2, V3 and V8, below — 44
  contradictions, 32 drops and 42 controls, of which 27 are stated as current today.
  Those 128 items
  were then **independently verified** in fresh contexts (111 verified, 4
  line-corrected, 13 disputed, 0 unverifiable), leaving a queue of
  [22 rulings](labels.md#independent-verification-pass-2026-08-15) for the confirm
  pass, of which **all 22 are now settled**, 21 by ruling and one by evidence, and none of the
  last four moved a total. Nineteen were raised; the one that
  asked an empirical question rather than for a decision is resolved, ruling V19
  added a twentieth, ruling V20 a twenty-first and ruling V15 a twenty-second, which
  closed the queue — V22, ruled 2026-08-17 on P4-C9, the last item that could have moved
  a number, then V17 on P10-C5 and V18 on P4-C3, which kept both rows and moved nothing. The resolved one: P5's article
  carries nothing that the undeclared hardening plan
  asserts alone, and two of the residues at issue are v1-exclusive corpus-wide, so the
  dropped rationales its article carries score as lost drops — D4 and D5, ruling V9
  having found that this investigation's "D2–D5" over-counted by two — and the fixture
  has no provenance gap.
  Three would move the totals, and two are **ruled 2026-08-15**. **V1 accepted**: P8's
  four contradictions are struck as de-specifications of one column rename — v2 names
  Lucas both on the category heading and as `Lucas (架构)`, and the article writes both
  sides — so **P8 leaves the gating set, six cases plus P6** at that point and five once
  V21 settles P5, staying in on its drops
  and controls, which matters because it is the one case with no accidental ordering
  cue. **V2 accepted**: P9-C1 is struck because v2 preserves both halves of v1's end
  state (L175–178 and L184), the second already scored as control K1, so the article's
  two-component framing was never stale. **V3 accepted**: P10-C6 becomes drop D6,
  because it paired v1's *mean* development duration against v2's *median* 研发周期,
  which v2 defines as development plus test — and v1 reports that duration only as a
  mean, so no same-basis pair exists to re-cut it onto. Together the three left **44
  contradictions, 31 drops and 42 controls with 27 stale**, and one later ruling moves the
  drop arm again: **V8 is ruled 2026-08-16** and promotes P5's unlisted
  `universal-transfer` abridgement to drop D6, since 跨 UID 转账 does not entail a
  destination under a third party's control and v3 asserts that nowhere else. Re-reading
  all seventeen of that case's abridged 备注 cells leaves D6 the only promotion, so the
  current totals are **44 contradictions, 32 drops and 42 controls with 27 stale** — 27
  unmoved, because drops do not gate. **V9 is ruled 2026-08-16** and moves no total, since
  D4 and D5 were already drops; what it settles is the drop arm's own measurement, the
  baseline RP1 would be judged against — **3 of P5's 6 drops are stated as current in the
  article**, and D1's residue is excluded because a declared, never-superseded source
  lists the same endpoints as retained, so no supersession rule could have removed it.
  **V19 is ruled 2026-08-16**, in a tightened form: staleness is now defined against the
  newest source in the compile set *that speaks to the item*, per claim rather than per
  document, since the newest document is usually silent on any one claim. Ruling it
  established two things the item did not claim. Its own rationale does not hold — no
  fixture co-source is newer than its chain head except P5's, so the wording answers V4
  in no case. **V4 is then ruled 2026-08-16 on its own**: the confound is verified but
  bounds only the causal claim, since a value the article states undated is still
  contradicted by the newest source in the same compile set whichever document supplied
  it. P7 keeps all 8 rows; only "this pair's ordering was lost" narrows to C8.
  And P5 cannot be scored on this column at all: both of its versions
  carry `date: 2026-03-13`, the payload breaks that tie on the path and so states the
  chain backwards, which would read as 5 of 5 stale rather than 0 of 5. That defect was
  raised as **V20**, a WP-family code fix rather than a scoring definition, and is
  **ruled 2026-08-16** as WP9: the payload withdraws the ordering claim instead of
  correcting it, since no signal in the corpus reaches more than 1 same-day pair in 384.
  So P5's exclusion becomes permanent rather than pending, and ruling it found the reason
  underneath — v3's body dates itself six days after its frontmatter, so the tie is an
  error in the metadata, filed as **V21** and **ruled 2026-08-16**. FX7's gate is
  unaffected either way, because it counts corrections carried; what the exclusion changes
  is which stale rate is published, and V21 publishes **27 of 39 (69%)** over the five
  gating cases. The 27-of-44 reading is retired as a headline: both readings share the
  numerator only because P5 is scored 0 of 5, which is the reading WP9's ruling found the
  payload cannot support, and against the order the payload states today P5 is 5 of 5 —
  making the all-cases figure 32 of 44 (73%) instead. 27 of 39 is the one figure that does
  not depend on P5. **V21 also settles the fixture's side of it**: v3 keeps its wrong date,
  because both P5 files are byte-identical to their corpus copies and re-dating one would
  be the only place a staged document departs from what it was staged from (FX1). P5 is
  reported as an A2 body-date case instead, which makes the fixture's wrong-date record
  three cases rather than two — P2 inverted by date, N2 dated before its own sections with
  its order intact, P5 tied by a date wrong by six days.
  **Verification coverage is now complete**: the eight controls, P1 and P6
  were checked separately from the 128-item pass, since none of them is a drafted row.
  All hold. P6 adds no queue item but does add a finding about the accidental ordering
  signal, recorded above.
  `superseded` is split because Q1 scopes A1's trigger to explicit contradiction
  and sends dropped claims to RP1–RP3's report: only the contradiction list gates
  A1 (FX7), and the drop list is measured so A2's RP1 arm has a baseline. The cost
  of the split is stated in test-set.md rather than buried: P1, the one adjudicated
  failure, is a drop case and therefore no longer gates the work it motivated.
  Needs no re-serialization of the fixture's `schema_version: 1` extractions,
  contrary to an earlier note in test-set.md: the version check lives inside
  `parse` (`storage/extraction.py:209`), which only `extraction.load` calls, and
  drafting reads the files as text.
- **FX4.** A pre-A1 baseline is measured on the staged fixture, before any code
  changes. The existing `wiki/` in `data/kb-knowledge` was written by prompt
  versions that no longer exist and is an existence proof, not a baseline.
  **"Before any code changes" no longer describes the checkout**: steps 1–5 landed
  first, because the fixture could not have scored them and the report in step 5 is
  what says where to look. So the baseline arm runs from a worktree at `bd8252e`, the
  last commit before A1, against its own copy of the staged fixture — the comparison
  FX7 makes is between two runs of the same documents, and which working tree each
  ran from does not enter it.
  **Add two checks to both arms**, found while verifying the controls and then
  re-measured while resolving V16: the existing articles' `sources` frontmatter is
  unreliable as a list of paths, and in seven articles it is not reachable at all.
  Across all 682 articles, **91 entries pack two or more comma-separated paths into a
  single YAML list item** (46 articles), and a source path is **listed twice or more in
  21 articles** as a literally repeated list item — **30 articles** once the comma-packed
  items are split, which is how the paths have to be read. The definition matters more
  than the number, so it is now attached: an earlier note here said 22 articles, which
  does not reproduce under any of four readings tried (exact item 21, basename 25,
  comma-split 30, both 32) and is withdrawn. `91` reproduces exactly.
  Both are old-writer output, so a fresh run should not reproduce them — but G2 is
  exactly the claim that a source is an attributable unit, so the baseline and the A1 arm
  should each be checked for comma-packed and duplicated `sources` entries. A duplicated
  entry is also the double-count failure the U1–U4 controls exist to catch, already
  present 47 times across those 30 articles. Anyone doing co-source analysis on the
  *existing* articles must split these entries on commas first; the seven scoring cases
  were checked and contain none, so labels.md's co-source table is unaffected.
  The second check is the sharper one, because it is a defect nothing catches today.
  **Seven of the 682 articles do not begin with a frontmatter delimiter**: the writer's
  own preamble prose stands above it — `wiki/decision/web3-cluster-decision.md` opens
  「Looking at the new information, it's largely already captured in the existing
  article…」 — and `wiki/project/ddq-auto-fill-tool.md` additionally wraps the article in
  a ` ```markdown ` fence. `split_frontmatter` returns `None` for content that does not
  open with a delimiter line (`py/src/kb_ai/_frontmatter.py`), so for these seven every
  key is invisible to every reader: no `title` for the catalog, no `date` for WP2's
  ordering signal, and **no `sources` for `derive` to copy**, which fails G2 outright
  rather than mis-shaping it. `kb-ai check` does not surface them — its extraction line
  counts documents against extractions (982 match, 14 missing of 996) and its grounding
  line skipped all 682 on the `schema_version: 1` gate. So both arms should assert that
  every article written opens at byte 0 with `---`. None of the seven is a scoring case,
  so labels.md is again unaffected.
- **FX5.** Scoring uses test-set.md's columns. Under A1, Trail is expected 0 on
  every case; Staleness over `superseded-contradiction`, on the merge-path stages,
  is the discriminating column. Both staleness columns are read per claim, against
  the newest source in the compile set that speaks to that item (V19), and a case
  whose source order rests on a same-day tie-break is reported apart from the gate —
  P5 is the only one, and WP9 keeps it there rather than letting it in, because the
  fix withdraws the ordering claim instead of correcting it (V20, ruled 2026-08-16).
  The cases judged on this column are therefore five: P3, P4, P7, P9 and P10.
  P5's five contradictions stay in the set totals, and **V21 (ruled 2026-08-16) publishes
  the rate over the cases that gate — 27 of 39 (69%)**, quoted with that composition
  attached rather than bare, since a reader has to be able to see that P5 and P8 are out
  and why. P5's own row is reported under the A2 body-date heading V21 gives it, not as a
  pending fix. Staleness (drop) is recorded on the same
  runs and gates nothing. False positives stay at 0 on N1–N4 and no duplicate contributes
  twice on U1–U4.
- **FX6.** The create-path prose comparison D2 committed to runs as a second arm
  *after* WP3 lands, against FX4's baseline: the same documents through the flat
  bag and through per-source blocks, article prose compared. It cannot be part of
  FX4 itself, because one of its two arms is the change being measured.
  Per-source blocks alter every new article, not only corrections.
- **FX7.** A1 is judged on Staleness over `superseded-contradiction` across FX4's
  baseline and the post-A1 run. Clearing those positives without tripping N1–N4 is
  what makes A2 optional rather than assumed. Staleness (drop) moving is reported
  as a finding about A2's RP1 arm and does not enter the verdict either way, so a
  run that clears the contradictions and leaves every drop stale still passes.

### VF. Verification

- **VF1.** Unit tests for the shared frontmatter reader (RT6): leading HTML
  comments, no frontmatter at all, malformed `date`, a `date` present but empty,
  and a `date` no calendar accepts (RT11). Each shape the submit route writes is
  also pinned as a fixture the reader parses, from both sides: the two ends share
  no definition of the format, so each holds the same bytes.
- **VF2.** Unit tests for block ordering (WP5, WP7): all dated, none dated, mixed,
  and identical checksums.
- **VF3.** Unit tests for newest-first budget allocation (BG1–BG4) under a budget
  too small for all blocks, asserting which block survives.
- **VF4.** Unit tests for the lineage rule (RP4), including both exclusion cases —
  the cross-source one in both its forms, dropped and split — every version-marker
  shape the corpus holds and the bare trailing number that must not count as one,
  and member ordering matching WP5's. Plus RP5 held structurally: the write phase's
  imports are asserted to name nothing from the rule, and a compile that fires the
  report is asserted to hand the writer source blocks carrying no judgement.
- **VF5.** Go tests for submit with a valid `date`, without one, and with an
  unparseable one, asserting the frontmatter written and the resulting
  `ContentHash` (RT1–RT4), plus each RT9 branch: a document that dates itself
  stored verbatim, a caller date overriding one, and a date inserted into an
  existing block. Two are regressions rather than new behaviour: identical content
  submitted twice still hashes the same, so the 409 path still fires, and
  `FileTitle` still comes from the document's own title rather than the one RT2
  wrote (RT8). RT10's boundaries get one case each — an indented block, a nested
  `date`, a `date` inside a literal scalar, a quoted `date` key, a block behind a
  provenance comment, a block whose keys sit behind a YAML comment, a duplicate
  `date`, a colon without its following space, a delimiter closed with `U+00A0`, a
  character the reader breaks a line on, a BOM on both the insert and the prepend
  path, an empty key, a `date` whose value is a mapping, a sequence or a literal
  block, an unquoted value holding a colon (with its quoted, flow and
  literal-scalar counterparts, so the rule cannot over-reach), and each unreadable
  shape (flow mapping, sequence, sequence of mappings,
  tab indentation) in both its verbatim and its stacked form — because every one of them was a live defect
  before it was a test. The clock itself is asserted exactly by calling
  `rawDocument` with a fixed time rather than through the handler, which can only
  check that the stamp is close to now.
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

Opened by FX3's drafting, and not blocking because A1 is no worse than the
pipeline it replaces: **a frontmatter `date` can be wrong rather than merely
missing.** Q2 and D3 both provisioned for absence — a dateless source gets no date
line and the prompt says its ordering is unknown — but a rolling document whose
`date` records its creation day while its body accumulates later sections gives
WP2 a date that is confidently wrong, and A1 then asserts an order to the writer
with no hedge. P2 is the corpus's only chain inverted *by its dates*, which is why it is
withdrawn from the positives rather than scored (FX3); the weaker symptom is common, at
101 of 996 corpus documents carrying a body-stated date later than their frontmatter
date — 99 of them in a heading and 2 in a 生成时间 line, one of those two being P5's v3.
**P5 is a third fixture instance, found by ruling V20 and disposed of by V21**: its v3 is
dated `2026-03-13` in frontmatter and 「生成时间：2026-03-19」 in its body, which is what
makes it share a date with its own predecessor. Its chain is not inverted by date — 03-13
→ 03-19 is the true order — so the damage arrives through WP5's tie-break rendering it
backwards instead. N2 is the second, dated before two sections it already carries with its
order intact (test-set.md). What A1 does not
have is any way to notice: the writer is told a date and never the text the date came
from. Whether the answer is a body-date consistency
check, an RP-style report, or nothing at all is A2's question, and it needs the
FX7 run first — if A1 clears the positives with this defect present, the defect is
not what is costing accuracy.

Ruling V21 measured what a body-date rule would be worth, and the answer is why the
question stays here rather than being answered early. The rate is conditional on a body
date existing: only **505 of the 996** documents state one, so the symptom runs at 101 of
505 (20%) among documents a rule could read at all — but among those same 505 the newest
body date points **earlier** than the frontmatter date in 109 and later in 101 — near-even,
so the rule has no established direction and nothing in the corpus says which of a
document's two dates is its own. On the fixture it is sharper still: it
would order P5's pair, and it would **de-order N3's and N4's**, whose two members each
carry one heading date for the meeting they transcribe (「…realclaw安全评估 2026-04-10」 on
both, 「…2026年4月9日」 on both), turning two pairs that frontmatter dates order correctly
into same-day ties that WP9 leaves unordered. That costs those controls nothing scoreable —
they are append-only false-positive checks — but a rule that buys one ordered pair and
withdraws two is not obviously worth its own risk, and 78 of the 101 corpus instances are
the transcript shape that produced it.

## Implementation sequencing

1. **Shared reader and the submit route.** RT6, then RT1–RT5 and RT8–RT11 with VF1
   and VF5. Independently useful: it dates the UI route's documents whether or not
   the rest lands. RT12's route is deliberately not part of it.
2. **Per-source blocks.** WP3, WP4, WP1, WP2, WP5, WP7 with VF2 and VF6. All seven
   call sites move together; WP4 enumerates the ones that exist today, and the grep
   for callers of `create_new_article` and `merge_into_article` is worth re-running
   at implementation time in case another has landed.
3. **Budget.** BG1–BG4 with VF3.
4. **Prompt and version.** WP6, PV1, PV2, and **WP9** with them — it is the same prompt
   paragraph plus BG1's restated basis, and it lands as a fix on code already shipped
   (`build_source_blocks`, `_SOURCE_ORDER`, `_budget_priority`) rather than as new
   surface. It rewrites `test_sources_dated_the_same_day_claim_the_budget_in_path_order`
   (`py/tests/test_core_merge_blocks.py:316`), which pins the claim WP9 withdraws.
5. **Reports.** RP2 verified, then RP3–RP5 with VF4.
6. **Fixture.** FX1, FX2, FX3, then the FX4 baseline, then VF7 with FX5, FX6 and
   FX7.

FX3's labelling has no dependency on steps 1–5 and costs no LLM spend, so it can
run in parallel from the start. It is the precondition for A1 meaning anything.
