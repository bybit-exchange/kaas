# Supersession A2: a replace primitive, and one value left standing

Date: 2026-08-20
Slug: `supersession`
Status: specified; **sequencing steps 1, 2 and 5 landed** — the supersede primitive and its
trail (`17aa09b`), V40 in test-set.md (`3d9597a`), and the two prompts plus PV4/PV5
(2026-08-21, the step that changes what the writer does). Steps 3, 4 and 6 are open: the
rewrite-path guard, the reports, then the arm. **Required rather than optional** — A1 was measured
and [verdict-fx7.md](verdict-fx7.md) decided D2's condition against it. The rubric this
increment is judged on was fixed before any spend on its arm: `In force` became a third
gating column as V39 on 2026-08-19 ([test-set.md](test-set.md#scoring)). D1 fixes what the
body must say; D6–D10 below fix the five things D1 left open, taken 2026-08-20.

**On identifiers.** This document continues A1's numbering rather than restarting it, so
that no identifier means two things across the feature's documents. `G6`–`G10`, `NG8`–`NG13`,
`S6`–`S9` and `PV4`–`PV6` extend the lists in [spec.md](spec.md). `D6`–`D10` extend the
design decisions carried from [design-options.md](design-options.md). `RA`, `TR`, `SG`, `GT`,
`FA` and `VA` are new families and appear nowhere in A1. `P1`–`P10`, `N1`–`N4` and `U1`–`U4`
are still the fixture cases from [test-set.md](test-set.md), and `V1`–`V39` are the rulings
already taken; this spec opens `V40`, which is ruled here as GT1 and landed in test-set.md.

## Background

A1 carried ordering to the writer and measured what that alone buys. The answer is in
[verdict-fx7.md](verdict-fx7.md): the gating column went from 24 of 40 to **19 of 40** and
cleared under no reading, the negatives held at 0 of 4 and 0 of 4, and the arm cost
14.3873 USD over 185 calls in four clean stages. So A2 is bought.

What A1 leaves for A2 is not a uniform 19-row deficit. It concentrates, and the concentration
is what this spec is shaped around.

**The arm shifted the failure mode rather than removing it.** The baseline stated superseded
values as current and unlabelled. A1 states them *with their source attached* — 「V1
(2026-03-05)」 against 「V2 (2026-03-06)」, "In earlier design this was … in the v0.2.0
implementation …". Ordering reaches the page on almost every case; what the writer does with
it is attribute each value to its version rather than assert that one value is dead. That is
**coequal presentation**, the shape D1 rejects in terms, and it is the load-bearing shape of
the A1 arm rather than an incidental one. It scores clean on Staleness (P7 0 of 8, P10 0 of 7,
P5 0 of 5) and earns no Trail, so A1's three best cases read `(Staleness 0, Trail 0)` —
which under the two-column rubric was indistinguishable from latest-wins. V39's `In force`
column is what can see it: measured on A1's surviving articles it reads **28 of 40**, 18
inside a single article and 10 across a chain the classifier split, and the strict
`Staleness ∪ In force` reading is 32 of 40.

**Eleven of the nineteen stale rows are in articles that never saw the newer value.** A1's
run split two chains across articles by version, so P4's v1+v2 article and P9's v1-only
article state values their own sources never contradict. Sixteen of the 45 contradiction rows
sit in chains no single article sees both halves of. No write prompt reaches them. Splitting
the total on that line gives the two figures this spec's gate is defined against:

| | rows | baseline stale | A1 stale | owner |
|---|---|---|---|---|
| Cases whose articles saw the whole chain (P3, P7, P10) | 24 | 13 (54%) | **5 (21%)** | the writer |
| Cases A1 split by version (P4, P9) | 16 | 11 (69%) | **14 (88%)** | the classifier ([NG6](spec.md#non-goals)) |
| **total** | **40** | **24** | **19** | |

**The residue sits on three surfaces, and none of them is prose.** Every stale row in P10 is
in a Key Decisions section or an Action Items table. Four of P3's five are Key Decisions plus
a Related line. P4's three writer-owned survivors are DDL cells copied verbatim from a v2
table into a table headed v3. A replace primitive that reaches paragraphs and not list items
or table cells leaves most of the remaining failure standing — which is why the grain of the
primitive is D8 below rather than an implementation detail.

**What A1 built that this increment stands on.** All seven write call sites compose their
payload through `build_source_blocks` (`core/merge.py:132`), which returns one
`SourceBlock` per source (`:83`) carrying the document's own date, oldest to newest with the
undated last. `_SOURCE_ORDER` (`:623`) tells all three system prompts that the blocks run in
that order, that a same-day pair carries no ordering claim (WP9) and that an undated block's
position carries none either. `_block_header` (`:182`) renders the `- Date:` line. None of
that changes here; A2 adds the action that reasons over it.

**What the write paths can do today.** `merge_into_article` (`:660`) routes to
`_merge_full_rewrite` (`:687`) for an article under `_LARGE_ARTICLE_THRESHOLD` (30,000 bytes,
`:542`) whose content plus blocks fit the budget, and to `_merge_diff` (`:702`) otherwise. The
diff path's actions are `append_to_section` and `new_section`
(`prompts/defaults/merge-diff.md:8-17`), applied by `_apply_diff` (`:756`, loop at `:813-822`).
The rewrite path re-emits the whole article. The A1 arm produced 20 articles totalling 468,024
bytes — a mean of 23 KB — so both routes are live and both are in scope.

## Goals

- **G6.** A merge can state that a value has been replaced: what stands now, what stood
  before, which document replaced it, and when — on both merge routes.
- **G7.** The superseded value stays readable in the article. A wrong supersession is
  recoverable without going back to `raw/`, which is D1's deciding argument and becomes a
  code guarantee here rather than a preference.
- **G8.** Supersession is asserted only where the payload establishes an order. An
  unordered pair produces a report, not a guess.
- **G9.** No write silently removes an existing trail, and every article that shrinks is
  visible to an operator.
- **G10.** A2's arm can be read against A1's arm on one rubric, both sides surviving on
  disk. This is the comparison [verdict-fx7.md](verdict-fx7.md) says only A2's arm can buy.

## Non-goals

- **NG8. Version-split chain routing.** When a lineage group's members classify into
  different articles, A2 does not reroute them. Eleven of A1's nineteen stale rows and 10 of
  its 28 In force rows are here and A2 reaches none of them: the article asserting the older
  value never received the newer one. This is D6, and it is why the gate is restated as GT1
  rather than left to fail by construction. The rows are still measured and still reported —
  attributed to classification, which [NG6](spec.md#non-goals) puts upstream of this feature.
- **NG9. Dropped claims (the RP1 arm).** A2's trigger stays explicit contradiction, as
  Q1 fixed it for A1: extraction is lossy summarization, the writer never sees raw text, so
  absence and "not extracted" are indistinguishable at the point of decision. The drop column
  is recorded on A2's arm exactly as on A1's (29 of 41 there, 37 of 41 on the baseline) and
  gates nothing. This is D7.
- **NG10. A body-date consistency check.** A1's open question stays open and stays out of
  A2. V21 measured why: among the 505 of 996 corpus documents that state a body date, the
  newest points *earlier* than the frontmatter date in 109 and later in 101, so a rule has no
  established direction; on the fixture it would order P5's pair and de-order N3's and N4's.
  P5 stays reported as an A2 body-date case and is not scored on either gating column.
- **NG11. Explicit lineage fed to the model (path B), and recomposition (path C).** RP5
  holds: `storage/lineage.py` informs an operator and does not enter a prompt. `core/merge.py`
  still imports nothing from it, and A2's arm is not evidence for or against path B.
- **NG12. Revisiting existing articles.** PV3 stands: `write_prompt_version` stays
  report-only (D5), so the 682 articles in `data/kb-knowledge` keep their contradictions.
  A2 applies to future write ops. Making a prompt edit rewrite the wiki is path C's decision.
- **NG13. The create path.** `create_new_article` (`core/merge.py:1019`) gains no action.
  A fresh article composes from scratch over ordered blocks and can simply state the newest
  value; there is nothing in it to retract. This is A1's Background reasoning unchanged, and
  it bounds A2's blast radius to `merge_into_article`.

## User stories

- **S6.** An operator submits a plan, then its v2 a week later. The article states v2's
  target and carries a bracketed note of what v1 said and when it stopped being true.
- **S7.** v3 arrives after v2 already superseded v1. The statement carries two notes,
  newest first, and the v1 note is not rewritten by the v3 merge.
- **S8.** Two sources of one article share a date. The compile reports that it could not
  order them and changes nothing — no supersession is asserted on a pair the payload itself
  says carries no ordering claim.
- **S9.** The writer proposes a replacement whose anchor no longer matches the article
  text. The compile reports the miss, naming the article and the action, and the article
  keeps every byte it had.

## Decisions taken

Five decisions, taken 2026-08-20, each with the option it beat.

### D6 — A2 is writer-side only, and the gate is restated to match

A2 ships the replace primitive and the trail. It does not touch how a version chain is
routed to articles. The alternative — growing A2 to force a lineage group's members into one
article group — was rejected for this increment because it makes A2 two independent
subsystems, redraws NG6's boundary, and raises both the arm's cost and its attribution
problem: a run that changes routing *and* the write prompts cannot say which change moved a
row.

The cost is accepted and it is not small: the KB really does keep 11 stale rows that nobody
on this branch owns. What the decision forbids is hiding that. GT1 restates the gate to read
the same-article count, the split rows are published beside it, and the third option — a
separate A2b spec bought only if A2's arm clears the same-article rows — stays available on
exactly the evidence A2's arm produces.

### D7 — the trigger stays explicit contradiction

Dropped claims keep escalating to the RP1–RP3 report. Giving the writer raw text at write
time so it could tell "retracted" from "not extracted" was rejected here: it inflates the
payload, reopens the budget model BG1–BG4 settled, and rests on a premise (that raw text
makes the distinction decidable) that nothing has measured. A1's arm moved the drop column
from 37 to 29 of 41 with no drop-specific mechanism at all, which is the observation the
column was carried for and is not yet an argument for building the arm.

### D8 — the primitive replaces anchored text, not a section

The action names the exact existing text it replaces. A section-level replace was rejected on
the failure map: the residue is in Key Decisions bullets, Action Items rows and DDL table
cells, and reaching a table cell by rewriting its whole section puts every neighbouring cell
at risk on a column that already reads 41 of 42 (Collateral). Anchored replacement is also
the only grain at which a code-level guarantee is available — an exact match either exists
or it does not, where "did the rewritten section keep everything else" is not checkable.

### D9 — the delete guard is code-level, and it is asymmetric on purpose

A2 is the first increment where a write path may remove text, so A1's G4 is lifted and
something has to take its place. Two guarantees, and they are different in kind:

- **A trail, once written, is append-only.** On the diff path this is structural and free:
  no action can delete a trail block, and RA5 excludes trail blocks from anchor matching. On
  the rewrite path the model re-emits everything, so the output is checked against the
  article's pre-existing trail blocks. A missing one buys one retry; if it is still missing,
  the merge is abandoned and the article keeps every byte it had. Losing a merge is expensive
  and it is the right price here: this is the one loss that cannot be recovered from the
  article itself.
  **One exception to "structural", measured 2026-08-21 while step 3 landed.** The claim holds
  for what the actions do and not for what the diff path hands them. `_merge_diff`
  section-truncates an article over 70% of the prompt budget — about 52 700 characters — and
  then patches *the truncated text*, which is also what is written back (`merge.py:749-751`,
  `:763`, `:772`), so whole section bodies are dropped before any action runs. On a synthetic
  86 731-character article with a trail in a large low-relevance section: 51 966 characters
  written back, the trail gone, its heading kept. This predates A2 and contradicts A1's G4 as
  squarely as it does D9, so it is recorded rather than fixed inside a step scoped to SG1 —
  patching the untruncated article, or refusing the write when truncation would drop a trail,
  is its own change with its own tests. Until then the guarantee reads: structural on the diff
  path *for articles that fit the prompt budget whole*, checked against the output on the
  rewrite path, and unenforced in the truncation range. SG2's shrink report will surface the
  range as large deltas, which is why the exception is named before step 4 rather than
  discovered from it.
- **Shrinkage is reported, never blocked.** Every write op records the byte delta and any
  article that got smaller is named in the report with its delta. A hard threshold was
  rejected outright: there is no measured distribution of legitimate shrinkage to set one
  from, A1's NG7 means shrinking has never been possible before, and a guessed threshold
  would kill correct large rewrites while inventing a number the spec cannot defend.

### D10 — chained trails accumulate, newest first

v3 superseding what v2 already superseded appends a second entry rather than replacing the
first. This is D1's own reasoning applied one level down — a wrong trail entry is recoverable
where a wrong deletion is not, and retrieval reads article bodies, so collapsing to the most
recent supersession makes "what did we decide before, and when did it change" answerable only
from `raw/`. A cap of N entries was rejected because it teaches the prompt a counting rule,
which is the class of constraint writers follow least reliably, and the fixture has no
instance to verify it against.

The cost is real: P4 is a four-version chain, so one statement there can carry three entries,
and Size grows monotonically in the trail. NG3's question is answered by this decision and
**not** by evidence — V15 measured that the fixture holds no nested supersession to label, so
A2's arm will report whether any instance arose rather than confirming the format was right.

## Acceptance criteria

### RA. The replace action

- **RA1.** `merge-diff.md` gains a third action, `supersede`, with four fields: `anchor`
  (the exact existing article text to replace), `replacement` (what stands now), `by` (the
  raw path of the document that replaced it), `was` (the superseded claim, as the trail
  should state it), and nothing else. The trail's *text* is rendered by code from `by`,
  `was` and the date on `by`'s block — not written by the model — so D1's four format rules
  are mechanical rather than hoped for. The model supplies the judgement; the format is the
  code's.
  **`replacement` may be empty; `was` may not.** An empty or absent `replacement` withdraws
  the claim instead of restating it, and the trail left in its place is what makes that
  deletion recoverable — this is D1's argument applied to the case where nothing stands now,
  not an exception to it. An empty or absent `was` is refused, because it deletes the *record*
  rather than the claim: with both empty the value leaves the article with nothing saying it
  was ever there, and G7 is the whole reason D1 chose a trail over a deletion. So the field
  carrying the old value is the one the action cannot omit. "Empty" is tested after stripping
  whitespace, because the guard is about the record and a `was` that renders as blank is not
  one.
  **A withdrawn claim is final on this path.** RA5 excludes trail text from anchor matching, so
  a position left holding only trail blocks cannot be reached by any later `supersede` — a
  further supersession of it reports `anchor not found` rather than chaining under TR4. This is
  RA5 working as written rather than a defect, and it is recorded here so that a reader meeting
  it does not file it as one.
- **RA2.** `anchor` must occur **exactly once** in the article body. Zero occurrences is a
  no-op and a report; two or more is a no-op and a report, because the action cannot say
  which one it meant. No normalization of any kind — not whitespace, not case, not
  punctuation — because a fuzzy match is a silent edit to text nobody chose. The prompt's
  side of this is RA7: one action per occurrence, each with an anchor long enough to be
  unique.
- **RA3.** `by` must name a source path in this payload, that block must carry a date, and
  its date must be **strictly newer than every other dated block in the payload**. If no
  block is strictly newest — every block undated, or every dated block sharing one day — the
  action is refused and reported. This is WP9 and G8 in code: the system prompt already
  states that a same-day pair carries no ordering claim, and an action that supersedes across
  one would contradict the prompt that carried it.
  **The guard's limit is stated rather than implied.** It orders blocks against each other
  and cannot order a block against the *article*, which carries no document date of its own —
  `updated:` is the compile day. A single-block payload therefore passes RA3 vacuously, and
  that is the common case: v2 merging into the article v1 wrote. So a writer that supersedes
  a value the article states *because it is the newer one* is not caught by code. It is
  caught by G7 — the old value survives in the trail — and it is measured by the arm's
  Collateral column. This is the concrete reason D1 chose a trail over a deletion.
- **RA4.** `supersede` actions apply **before** the additive ones, against the article text
  as it entered the prompt. Anchors were chosen against exactly those bytes, so applying an
  `append_to_section` first can create text an anchor then matches, or move the text an anchor
  was cut from. Within the supersede group, actions apply in emission order, which is
  `_apply_diff`'s existing rule.
- **RA5.** Trail blocks are excluded from anchor matching — both the ones the article already
  carried and the ones an earlier action in this same patch set rendered. A later supersession
  edits the article's claims, never its history, and two actions in one merge cannot chain onto
  each other's bookkeeping.
- **RA6.** `merge-rewrite.md` gains the same rule in prose, since the rewrite path returns a
  whole article and has no action vocabulary. It states the trail format by example — D1's
  example verbatim — and states the same order precondition RA3 enforces.
  **One deviation, taken 2026-08-21 when the prompt landed: the example is unwrapped onto one
  line.** D1 writes it wrapped across two, which is that document's line width and not part of
  the format; TR1 makes the block single-line and TR6's validator reads it back that way, so a
  verbatim copy of the wrapped form would teach a shape this feature's own code reports as
  malformed on every use. Pinned by a test that runs the prompt's example line through
  `_trail_defects` and asserts it is clean — the disagreement is only visible across the two
  artifacts, so it is asserted there rather than inside either one.
- **RA7.** Both prompts state four things the action needs and one it forbids: make the
  anchor unique by including surrounding text; emit one action per occurrence when the same
  claim is stated in two places; name in `by` the source whose block is newest; leave the
  claim alone when no block is newest. The forbidden one: do not supersede a value the
  incoming block is *older* than. **A1's S2 story — an operator backfilling v1 after v2 — has
  no fixture instance**, because FX2 stages version N into the wiki version N−1 produced, so
  the newest document always arrives last. The rule is stated and left unmeasured, recorded
  here rather than discovered later.
  **One of the four is diff-only, 2026-08-21.** "Make the anchor unique by including surrounding
  text" is vacuous on the rewrite path, which returns a whole article and has no anchor;
  `merge-rewrite.md` states the other three and the prohibition. Recorded because RA7 says
  *both* prompts state four, and a reader checking would otherwise find a rule missing.

### TR. The trail

- **TR1.** One bracketed block per supersession, rendered as D1 fixes it by example:
  `[Superseded 2026-06-14 by raw/plan-v2.md: the earlier target was 1 200 requests per
  second]`. One block, opening `[Superseded `, closing `]`, so a grep over `wiki/` finds
  every entry and a reader can tell prose from bookkeeping.
- **TR2.** The block sits immediately after the text that replaced it, in the same section
  (D1's fourth rule). Retrieval reads article bodies, so a trail anywhere else is a second
  lookup page selection has no reason to make.
- **TR3.** The date is the `- Date:` value on `by`'s block — the superseding *document's*
  date, from its raw frontmatter — never the compile date, which moves on every recompile and
  would rewrite the history it records. A `by` whose block is undated cannot reach here: RA3
  refuses it first.
- **TR4.** Chained trails accumulate newest first (D10). Where the insertion point is
  already followed by one or more trail blocks, the new block is inserted **before** them, so
  the entries read newest to oldest. No cap.
- **TR5.** The rendered block is single-line. Where the insertion point is inside a table row
  — the containing line begins with `|`, leading whitespace ignored, since an indented row is
  still a row — the guard covers **everything the action writes into that row**, not only the
  trail: any `|` in `was` *and* any `|` in `replacement` is escaped as `\|` so the row's column
  count survives. Escaping only `was` would leave the same corruption reachable through the
  other half of the same edit, and D8 chose anchored replacement precisely so that the
  neighbouring cells survive on a column already reading 41 of 42 (Collateral).
  A newline is refused rather than escaped, because it has no escape — it splits the row in
  two — and a multi-line value in a table cell has no correct rendering, so the caller can
  restate it. This covers all three of the action's text fields, at the scope each one needs:
  a `was` containing a newline is refused **everywhere**, since TR1 makes the trail single-line
  on every surface; a `replacement` containing one is refused **only inside a row**, since in
  prose a multi-line replacement is ordinary content; and an `anchor` containing one is refused
  **when any line it touches is a table row**, judged on the whole span rather than on where it
  starts, since an anchor reaching from prose into a row corrupts the row just the same. The
  `anchor` case is the one that fails two criteria at once and so cannot be left to the report:
  a multi-line anchor across two rows merges them, and the trail's single `was` would then
  stand as the record for every claim the merged rows held, so TR5's column count and G7's
  record fail together. These two are the refusals that depend on where the anchor turned out
  to be, and so the ones reported after anchor resolution rather than before it.
- **TR6.** On the rewrite path the model writes the trail text itself, and this asymmetry is
  stated rather than papered over. Code validates every trail block in the output — the
  bracket shape, a resolvable date, and a `by` path that is one of this payload's sources —
  and **reports** malformed ones without rejecting the write. A malformed trail is prose a
  human can fix; a rejected merge loses information. Only D9's append-only guarantee rejects.
  **Narrowed to the blocks new in the output, 2026-08-21.** "Every trail block in the output"
  read literally reports a false defect on the case D10 exists for: S7's v3 merge preserves
  the v2 entry, whose `by` names a document the v3 payload does not carry, so the `by` rule
  would fire on every correct chain. The validator therefore compares the output against the
  pre-write article — the same pair SG1 reads — and checks only what the writer added.
  Two bounds worth naming rather than discovering. The date test is `as_day`, the KB's one
  narrowing, so a *resolvable* day that is not D1's `YYYY-MM-DD` (an ISO stamp, or the basic
  form `20260514`) passes; the alternative is a second date reader that could disagree with
  the one ordering the blocks. And the blocks of a chain sit adjacent on one line, so the
  scan runs per opener rather than per line — a line-wide match consumes the whole chain and
  leaves every entry after the first unchecked, which is how the first implementation of this
  read and what a mutation run caught.
  **One open bound, and it is a decision rather than an oversight: an empty `was` passes.**
  The three checks are shape, date and `by`, so `[Superseded 2026-05-14 by raw/v2.md: ]` — a
  trail recording nothing — is reported by neither, where the diff path refuses it outright
  (RA1, `was is empty`) because G7 is the whole reason D1 chose a trail over a deletion. The
  asymmetry is the one G7 argues hardest against, so it is not left implicit: current behaviour
  is pinned by a test, and adding a fourth check is a change to TR6 rather than a fix to its
  implementation. Note the paths would still differ in *response* — the diff path refuses, TR6
  reports — which is the asymmetry TR6 chose on purpose and would not be touched.

### SG. Guards and reports

- **SG1.** Trail preservation, per D9. The diff path holds it structurally, with the one
  truncation-range exception D9 now records. On the rewrite path, every trail block present in
  the pre-write article must be present verbatim in the output; if one is missing, the call is
  retried once with the constraint restated, and if it is still missing the article is left
  unchanged and the failure is reported with the article path and the missing block, cut to 80
  characters as SG3 cuts an anchor — a trail block is as long as the claim it records, and the
  article still holds the block a prefix locates.
- **SG2.** Shrinkage, per D9. Every merge op records pre- and post-write article bytes, and
  the compile report names every article that shrank, with its delta. No threshold, no block.
  This is also what makes the Size column readable in both directions for the first time —
  A1's NG7 ("whether an article can shrink") is answered here by *yes*, so the column stops
  being a growth meter.
- **SG3.** Every refused or no-op `supersede` is reported: the article, the reason (anchor
  not found, anchor ambiguous, anchor spans a table row boundary, `replacement` contains a
  newline in a table row, `by` not in payload, `by` undated, no strictly-newest block, `by` is
  not the newest dated block, `was` is empty, `was` contains a newline), and the anchor's first
  80 characters folded onto one line so that one refusal cannot print as two.

  RA3's **ordering** pair is reported apart because the two point an operator at different
  things: a payload with no strict maximum is WP9 saying no order exists, where a `by` that is
  dated but beaten by a single newer block is the writer naming the wrong document, and one
  reason covering both would report the second as the first. Where a payload is both — every
  block undated — the specific reason wins, since that is the one an operator can act on.
  This is G3's shape — an
  ordering judgement that cannot be safely acted on is reported to an operator instead of
  being acted on — and it is the report that says whether the prompt is producing actions the
  code then throws away.
- **SG4.** The reports are operator-facing and never re-enter a prompt, on RP5's reasoning
  and asserted the same way: the write phase's entry points take source blocks and nothing
  else, and every report is built after the last write op.

### PV. Prompt version and the additive claim

- **PV4.** `write_prompt_version` (`core/merge.py:936`) moves again, because the hash covers
  all three write-stage system prompt renderings (`_write_stage_renderings`, `:907`) and two
  of them change: the diff path's and the rewrite path's. `_create_system` (`:975`) is
  untouched, per NG13 — it keeps `_GROUNDING` and `_SOURCE_ORDER` and gains no action, and two
  changed renderings move the hash exactly as three would. Per D5 it gates nothing (NG12), so
  the cost is a report saying every article is behind — noise, not spend.
  **Landed 2026-08-21: `5a66a8ed04ea` → `3c88b88358d8`**, measured across the two prompt edits
  rather than asserted. The docstring's *reason* for staying report-only changed with it and
  was rewritten rather than carried: it used to be that gating bought nothing because a
  re-composition could only append, and now a re-composition can correct a claim, so what
  holds the gate back is cost and blast radius — which is where NG12 already put the decision.
- **PV5.** **Six sites assert that the merge paths cannot retract, and A2 falsifies all
  six.** They are enumerated here because a stale claim in a docstring is what a future
  reader will believe: `core/merge.py:609` (the `_SOURCE_ORDER` comment, which says A1 adds
  no action), `core/merge.py:943-955` (`write_prompt_version`'s docstring), `storage/lag.py:13-20`
  (the module docstring), `storage/extraction.py:315`, `commands/compile.py:190` (the lineage
  report's own text) and `commands/compile.py:722-732` (the revised-documents report). The two
  report strings are user-visible and change what an operator is told, so they change with the
  code and not after it.
  **All six cleared 2026-08-21, and the guard is a grep rather than six line numbers**, since
  line numbers move and what a future reader believes is the sentence. Two things the drafting
  got wrong and the test caught: the `_SOURCE_ORDER` comment says "the merge paths cannot
  retract", which the pattern written for `write_prompt_version`'s "merge cannot retract" does
  not match — so the site PV5 names first would have been missed — and a pattern set proves
  nothing when it is empty by accident, so the test asserts a positive control before it
  asserts a clean tree.
- **PV6.** RP2's guarantee is re-verified rather than rebuilt: a revised document still
  names the articles carrying its previous version. What A2 changes is the *reason* the report
  exists — the articles may now have been corrected — so the text says "may still carry" and
  names the trail as the thing to look for.

### GT. The gate

- **GT1. Ruling V40, ruled 2026-08-20 with D6 and now landed in
  [test-set.md](test-set.md#v40-the-gate-reads-the-same-article-count-on-both-columns) with
  GT2–GT4, which was step 5 of the sequencing.** The Staleness half of
  [test-set.md's](test-set.md#scoring) gate reads
  the **same-article count**, exactly as V39 already scoped `In force`. A row that is stale
  only because a second article holds the older half of a chain is reported apart and
  attributed to classification.
  **Grounds:** 11 of A1's 19 stale rows and 10 of its 28 In force rows exist only in an
  article whose sources never contradict the value it states. No write prompt can retract a
  value its article never received, so a gate that counts them is not a measurement of a
  writer-side increment — it is a measurement of the classifier with a writer-side increment
  in the denominator.
  **What V40 does not do:** it moves no published figure. The baseline's 24 of 40 and A1's
  19 of 40 stand as published, and the same-article decomposition is stated beside them
  rather than replacing them — A1's writer-owned Staleness is **8 of 40** and its
  same-article In force is **18 of 40**. This is V39's shape deliberately: a column or a
  scope is added, and no measured comparison is re-read after the fact.
- **GT2.** A2's arm clears the positives if and only if: same-article Staleness over
  `superseded-contradiction` is **0**, same-article `In force` is **0**, false positives on
  N1–N4 are **0 of 4**, and double counts on U1–U4 are **0 of 4**. Trail does not gate on its
  own, per test-set.md.
- **GT3.** A **D1 conformance reading** is published beside the gate, because the gate alone
  cannot tell D1 from the option D1 rejected. V39 gives a row three ways to pass `In force`:
  a directional statement resolves both values (current-plus-trail, D1), only one value is
  stated (latest-wins), or neither is (the item is absent — P4-C10 is A1's only instance). So
  the arm reports, of the rows that pass, how many pass each way. **A2 that clears both
  columns with Trail near 0 has shipped latest-wins**, which is a result worth knowing and is
  not D1 delivered.
- **GT4.** The same-article denominator is **measured on A2's own arm, not inherited**.
  Classification may split differently than it did at `033517c`, so the arm publishes its own
  same-article and split counts over the 40 gating rows before either column is read. A
  denominator carried over from A1 would quietly re-score A2's rows against A1's routing.

### FA. Fixture, arm and scoring

- **FA1.** The arm runs on the staged fixture unchanged — FX2's four stages, one per version
  — through `py/scripts/run_fx4_arm.py`, which is versioned and tested for exactly this
  reason (FX1) and refuses a gateway that does not serve the arm's write model. Same
  documents, same stages, same driver as A1's arm; the only difference is the code under it.
- **FA2.** **A1's arm is the comparison side, and both sides survive.** Its 20 articles are
  in `~/kaas-arms/a1/kb/wiki`, beside its logs and its four per-stage `wiki/` snapshots, and
  its record is [scoring-a1.md](scoring-a1.md). This is the first
  comparison in the feature where one rubric can be applied to both arms — the baseline's
  articles were lost when `/tmp` was cleared on 2026-08-19, which is what made `In force`
  permanently `n/a` there. So A2's arm reports `In force` on both sides of its own comparison,
  and it survives by construction rather than by remembering to copy it: `run_fx4_arm.py`
  refuses an `--out` that resolves into a volatile directory (`_volatile`, `py/scripts/run_fx4_arm.py:464`),
  which is the lesson the baseline's loss paid for.
- **FA3.** Scored on every column test-set.md defines: Staleness (same-article and split),
  `In force` (same-article and split), Trail under V28's directional criterion, Correction
  landed, Collateral, Staleness (drop), Size, false positives, double counts. A1's figures to
  beat: Staleness 19 of 40 with 8 writer-owned, `In force` 28 of 40 with 18 same-article,
  Trail 5 of 45, Correction landed 38 of 45, Collateral 41 of 42, drops 29 of 41.
- **FA4.** **Reported per surface, not only per case.** The three surfaces the residue sits
  on — Key Decisions sections, Action Items tables, and table cells copied under a newer
  heading — are counted separately, because a primitive that reaches prose and not tables
  would show up as a partial improvement in the totals and as a complete failure per surface.
- **FA5.** Two counts that exist only because A2 can now fail in new ways: how many
  `supersede` actions the writer emitted, and how many the code refused, broken down by
  SG3's reasons. A column that is clean because the writer never tried is not the same result
  as a column that is clean because it tried and succeeded.
- **FA6.** `py/scripts/audit_articles.py` runs on the arm, as it did on both previous ones.
  Both FX4 write defects are live in the writer and absent from A1's arm, so absence is not
  yet a property of the code.
- **FA7.** Spend is recorded. A1's arm was 14.3873 USD over 185 calls; A2 adds prompt text
  to the two merge system prompts, plus at most one retry per rewrite-path trail failure, so
  15–20 USD is the band to budget and the actual figure is what gets published.
- **FA8.** The verdict is written as `verdict-a2.md`, on verdict-fx7.md's shape: the gate,
  the columns that are not the gate, the sensitivity of the answer to any ruling the scoring
  opens, and what the verdict cannot decide.

### VA. Verification

- **VA1.** `_apply_diff` with a `supersede` action: exact single match; zero matches is a
  no-op and reports; two matches is a no-op and reports; an empty and an absent `replacement`
  each leave the trail alone in the claim's place (RA1); the anchor inside a table row escapes
  `|` in both `was` and `replacement` without double-escaping one already escaped, a
  `replacement` containing a newline is refused there but allowed in prose, and an `anchor`
  spanning a row boundary is refused whether it starts in the row or reaches into it (TR5); an
  anchor that would match text inside an existing trail block does not match (RA5); supersede
  applies before an `append_to_section` whose content would have created a second match (RA4).
- **VA2.** Trail rendering: the exact D1 format; the date taken from `by`'s block and not
  from today; a `by` absent from the payload refused; chained insertion putting the new block
  before existing ones (TR4); a `was` containing a newline refused (TR5); an empty, absent or
  whitespace-only `was` refused with and without a replacement beside it (RA1).
- **VA3.** The order guard (RA3), one case each: all blocks undated, all dated blocks
  sharing one day, a strictly-newest block present, `by` naming a dated but not-newest block,
  and the single-block payload that passes vacuously — asserted as passing, so the limit
  stated in RA3 is pinned rather than described.
- **VA4.** Rewrite-path trail preservation (SG1): an output missing a pre-existing trail
  retries once; an output missing it twice leaves the article byte-identical and reports.
  Both assertions are on the article, not on the log.
- **VA5.** The shrink report (SG2) fires with the correct delta and does not block the
  write. A write that grows the article produces no shrink line.
- **VA6.** TR6's rewrite-path validation: a malformed trail block in the output is reported
  and the write still lands.
- **VA7.** `write_prompt_version` moves when either prompt changes (PV4), and the six PV5
  sites are asserted not to claim the merge paths are additive — a grep-shaped test, because
  the claim is what a future reader will believe.
- **VA8.** A both-routes parity test — CLI and worker producing identical output for the
  same article and blocks in one process — extending VF6 to cover the new action.
- **VA9.** A real staged run with spend recorded, which is FA1.

## Resolved questions

| # | Question | Answer |
|---|---|---|
| D6 | Does A2 cover version-split chains | No. Writer-side only; GT1 restates the gate to the same-article count and publishes the split rows apart |
| D7 | Does A2 act on dropped claims | No. Explicit contradiction only, as Q1 fixed for A1; the drop column is recorded and gates nothing |
| D8 | What grain does the replace primitive work at | Anchored exact text, one occurrence per action. Not section-level — the residue is in bullets and table cells |
| D9 | What replaces A1's G4 once a path can delete | A trail is append-only, enforced by rejection on the rewrite path and structurally on the diff path except in its truncation range; shrinkage is reported with no threshold |
| D10 | Chained supersession: keep or drop the earlier entry (A1's NG3) | Accumulate, newest first, no cap. Answered by reasoning, not by evidence — the fixture holds no instance (V15) |

## Open questions

- **Does the writer emit actions the code then refuses, and at what rate?** FA5 is written
  to answer it, and the answer decides whether the next increment is a better prompt or a
  looser guard. Nothing predicts it: A1's writer produced directional trails unprompted on 7
  of 45 baseline rows, so it is capable of the judgement, but it has never been offered an
  action.
- **Does a trail survive the next merge intact?** SG1 guarantees it against deletion and
  says nothing about a rewrite that paraphrases one. A paraphrased trail passes SG1's
  verbatim check only if the original text is still present, so paraphrase-plus-original is a
  duplicate and paraphrase-instead-of-original is a rejected merge. Whether that costs merges
  in practice is what FA7's spend and FA5's counts show.
- **Carried from A1 unchanged:** whether the body-date defect needs a consistency check
  (NG10), and whether the RP1 arm is worth building (NG9, and A2's drop column is the next
  datum).
- **Opened by D6:** whether A2b — routing a lineage group's members into one article group
  — is bought. The condition is the same shape D2 attached to A2: buy it only if A2's arm
  clears the same-article rows, since a routing change on top of a writer that still leaves
  values standing would not be measurable.

## Implementation sequencing

1. **Trail rendering and the supersede application.** RA1's field handling, RA2–RA5, TR1–TR5
   in `_apply_diff`, with VA1–VA3 and VA5. **No prompt changes, so behaviour does not move**:
   the model cannot emit an action it has not been told about, and the code lands under test
   before it can be exercised.
2. **The prompts — landed 2026-08-21.** RA6, RA7 and TR6 in `merge-diff.md` and
   `merge-rewrite.md`, plus PV4 and PV5's six sites, with VA6 and VA7. This is the step that
   changes what the writer does. One thing arrived a step early on purpose: `merge-rewrite.md`
   also states D9's append-only rule, because SG1 retries "with the constraint restated" and a
   prompt that never carried the constraint would make that retry the normal path rather than
   the exception. Step 3 adds the code that enforces it.
3. **The rewrite-path guard — landed 2026-08-21.** SG1 with VA4. The retry restates the
   constraint as a requirement rather than as feedback on the rejected draft, because the draft
   is not sent back: carrying it would spend a whole article of budget to say what the list of
   missing blocks says. The retry's own text is bounded by what the first send left of the
   budget, since overrunning it would raise `PromptTooLargeError` and lose the history to a
   crash rather than to the guard; the report names every missing block whether or not the
   prompt could name it.
4. **Reports — landed 2026-08-21.** SG2, SG3, SG4 and PV6, surfaced through the compile report
   beside the revised and lineage reports (`compile.py:190`, `:722-739`), with VA8.
   Three decisions the rule text left open, recorded because each could have gone another way.
   **The findings travel in a caller-passed sink** (`merge_into_article(..., events=...)`) and
   are *collected instead of printed*: the sink's owner logs the report, so emitting at both
   layers would tell an operator the same refusal twice and make a count of report lines wrong.
   A caller that passes none keeps the stderr behaviour it had, which is the only report a
   direct caller gets. **SG2's delta is measured inside the merge op**, not by its two callers,
   though both hold the pre- and post-write text: one number must not depend on which route
   wrote the article. It has a one-byte floor worth knowing about — the rewrite route strips
   what the model returns, so an article stored with a trailing newline really does lose a byte,
   and SG2 reports it rather than inventing the threshold D9 rejected. **An abandoned merge is
   its own status** on both routes (`merge-abandoned` in the compile log, `abandoned` in the
   worker route's item result) rather than a `merged` that changed nothing, because `merged`
   tells a client the sources reached the article and SG1 dropped the write so that they did
   not. The ops still count as completed: D9 accepts losing the merge, and a deterministic trail
   failure retried on every compile would re-spend forever while reporting the same finding.
5. **The ruling — landed 2026-08-20.** GT1 written into test-set.md as V40, with GT2–GT4.
   Cost no spend and is the precondition for the arm meaning anything, which is why it ran
   first rather than in parallel.
6. **The arm.** FA1–FA7, then `verdict-a2.md` (FA8).

Steps 1 and 5 are independent of everything else. Step 2 is the point of no return for
`write_prompt_version`, and step 3 must land before the arm, since the arm is the first place
a rewrite-path merge meets an article that already carries a trail.
