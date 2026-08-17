# FX3 labels — the supersession test set's reference standard

Status: **drafted, awaiting confirmation.** All 118 scoring rows still read
`to confirm` — the confirm pass has not started. The verification queue below is
**closed**: 22 of 22 settled, the last two on 2026-08-17, and a ruling settles what
a row means rather than whether it scores. The two blocking rulings were the first
of them (2026-08-15): P2 leaves the positives and is kept as the documented
wrong-date counter-case, and P7's measurement-time reading is accepted. Neither is
still a question; see [P2](#p2--infra-biweekly-review-withdrawn-counter-case)
and [P7](#p7--2026-h1-cost-progress-tracking).

These labels are what [test-set.md](test-set.md)'s scoring columns are measured
against. A wrong entry does not fail loudly; it silently mis-scores A1 and feeds
the decision about whether A2 gets bought. They are drafted from the documents
and human-confirmed before they score anything ([spec.md](spec.md) FX3), and the
labels themselves stay human-owned.

Cases P1 and P6 are not here: both were adjudicated in test-set.md when the set
was built. The eight below are the ones its Label column had marked `to draft`,
and that column now links to the drafts here.

## How to confirm

Set each item's Status to one of:

| Status | Meaning |
|---|---|
| `to confirm` | not yet reviewed (the state everything ships in) |
| `confirmed` | the item is right as written and scores as-is |
| `amended` | kept, with the correction written into the row |
| `rejected` | struck, with the reason written into the row |

**Done means**: no item still reads `to confirm`; the two blocking rulings (P2's
direction, P7's same-period reading) are recorded here as decisions rather than as
questions — **done, 2026-08-15**; and test-set.md's Status block stops calling the
labels awaiting-confirmation. Until then FX5's scoring cannot run, because there is
nothing settled to score against.

Confirming does not require reopening the fixture. Every row carries the file and
line of both sides, plus the decisive quote, because aligning them is the
drafter's job rather than the reviewer's.

Since 2026-08-15 the rows have also been through an independent verification pass,
so the confirm pass starts from **18 queued rulings** rather than from 122 unchecked
rows — 19 were raised and one, V16, was
[resolved by investigation](#v16--resolved-by-investigation-no-ruling-needed)
because it asked an empirical question rather than for a decision. Three more were raised
by rulings since — V19's ruling raised V20, V20's raised V21 and V15's raised V22 — so the
queue stands at **22 rulings** of which **twenty-one are taken** and V16 needed none, leaving
**none open**. See [the verification pass](#independent-verification-pass-2026-08-15). Note
that `verified` there is **not** `confirmed`: verification re-derives a row from the
sources, and confirmation is a human decision about whether the row should score.
Only the second one clears `to confirm`.

## The rule these labels apply

Four lists, defined in [test-set.md](test-set.md#the-cases). The split that
matters: `superseded-contradiction` (the later version asserts something
incompatible about the same subject) gates A1 under FX7, while
`superseded-drop` (the later version is simply silent) is measured and does not
gate. `replacement` pairs one-to-one with `superseded-contradiction`.
`control` is what both versions assert, and it catches over-deletion.

Item IDs are stable and citable: `<case>-C<n>` contradiction, `<case>-R<n>` its
paired replacement, `<case>-D<n>` drop, `<case>-K<n>` control (kept).

Quotes are verbatim Chinese, as the source documents are. `v1`/`v2` line numbers
are into the fixture files named at the head of each case.

## Progress

| Case | Contradictions | Drops | Controls | Stale in article today | Status |
|---|---|---|---|---|---|
| P3 | 8 | 5 | 6 | 6 of 8 | to confirm — **V7 ruled 2026-08-16**: D3 stays a drop and call 2's promotion is declined, so P3 holds at 8C / 5D and has no queue item left, see [P3](#p3--cht-knowledge-distillation-and-indexing) |
| P4 | 10 | 4 | 6 | **9 of 10** | to confirm — worst case in the set; **V5 ruled 2026-08-16** keeps C8 with a recorded residual, **V15 ruled 2026-08-17** relabels X1 as a drop followed by a supersession over one entity and finds the fixture unable to carry a nested supersession at all, **V22 ruled 2026-08-17** keeps C9 stale on L667 alone, the other two residues tracing to a passage v2, v3 and v4 assert identically, and **V18 ruled 2026-08-17** keeps C3 stale on four v1-exclusive strings while withdrawing R3's, which is v1's own and control K4's, see [P4](#p4--trade-rollback-trd-four-versions) |
| P5 | 5 | **6** | 6 | **0 of 5**, reported apart from the gate | **V20 ruled 2026-08-16** — the payload stated the chain backwards off a path tie-break, which is fixed by withdrawing the ordering claim, not by correcting it; so P5 gains no basis to be scored on this column and its exclusion is now permanent. **V21 ruled 2026-08-16** gives that exclusion its disposition: v3's frontmatter date is wrong by six days against its own body, the fixture keeps the document verbatim, and P5 is recorded as an **A2 body-date case** rather than a pending fix. Its 5 contradictions still count in the set totals. **V8 ruled 2026-08-16** adds **D6**, the one abridgement of seventeen that loses a proposition v3 nowhere restates, so the drop arm reads 6 — and **V9 ruled 2026-08-16** measures that arm at **3 of 6 stated as current** (D4, D5, D6), excluding D1's co-sourced residue, without moving a total, see [P5](#p5--bybit-trading-skill-api-inventory) |
| P7 | 8 | 0 | 6 | 6 of 8 | to confirm — reading accepted; **V4 ruled 2026-08-16**, all 8 rows stay scoreable and only the causal claim narrows to C8, see [P7](#p7--2026-h1-cost-progress-tracking) |
| P8 | 0 | 6 | 6 | — | **V1 ruled 2026-08-15** — its four contradictions were de-specifications and are struck; P8 keeps its drops and controls and no longer gates, see [P8](#p8--ai-project-portfolio-overview) |
| P9 | 6 | 5 | 6 | 3 of 6 | to confirm — **V2 ruled 2026-08-15**, C1 struck as preserved by v2, see [P9](#p9--bybit-ai-toc-project-initiation) |
| P10 | 7 | 6 | 6 | 3 of 7 | to confirm — **V3 ruled 2026-08-15**, C6 reclassified as drop D6; **V6 ruled 2026-08-16** keeps C7 on v2's 全量 basis; **V11 ruled 2026-08-16** re-cuts call 5's provenance list onto basis labelling and finds 2 of the 3 stale rows co-sourced, leaving C8 as the only evidence no other source carries; **V13 ruled 2026-08-16** confirms the half-year pair on the wording V6 added and finds the article stating its −6.0% → −4.0% change as a 「−4 to −6%」 band across both bases; **V14 ruled 2026-08-16** makes the roster change additive, caps the team family at one further scoreable row (Compliance, not Fiat Channel) and finds C8's replacement co-asserted where its superseded pair is not; **V17 ruled 2026-08-17** holds C5 as a level-only contradiction, finds v2's efficiency cycle series to be the co-source's unfiltered column and the >120 population v2 declares for efficiency to be unused, and leaves the stale count at 3, see [P10](#p10--2025-engineering-efficiency-report) |
| ~~P2~~ | ~~8~~ | ~~6~~ | ~~6~~ | ~~7 of 8~~ | **withdrawn from the positives** — counter-case, scores nothing; **V10 ruled 2026-08-16** makes that permanent, the pair agreeing verbatim on seven of the eight rows in the section both files date 04-17 and the eighth leaving no article residue, see [P2](#p2--infra-biweekly-review-withdrawn-counter-case) |

Totals across the seven scoring cases: **44 contradictions, 32 drops, 42
controls**. The published pre-A1 staleness rate is **27 of 39, 69%** — measured over
compiled output rather than argued from P1 alone, and over the five cases actually judged
on the column (P3, P4, P7, P9, P10). P5's five contradictions are in the 44 but P5 is
reported apart from the staleness column, permanently under V20 and as an A2 body-date
case under **V21**, so the 44-denominator reading is retired as a headline: it shares the
numerator only because P5 is scored 0 of 5, which is the reading V20 ruled the payload
cannot support. Plus one non-scored trail entry (P4-X1) as evidence for NG3's trail
format — **a drop followed by a supersession over one entity rather than a chained
supersession, ruled by V15 on 2026-08-17**, and the strongest thing this set can offer
NG3, since P4 is the only staged chain longer than a pair and a nested supersession
therefore cannot be cut from the fixture at all. And P2's withdrawn label (8/6/6)
retained below as counter-case evidence.

- **P5 reads 0 of 5 stale** and leaks its ordering six ways inside the body, so it
  belongs with P6 as an accidental-signal case rather than as evidence about A1. That
  reading also depends on the true version order, which the payload does not carry:
  the two versions share a frontmatter date and the tie-break states the chain
  backwards. **V20 is ruled** — the payload stops claiming an order it cannot support,
  which keeps P5 out of the gating column rather than putting it in — and **V21 is ruled**
  on the wrong date underneath: the fixture keeps v3 byte-for-byte as the corpus holds it,
  and P5 is reported as an A2 body-date case.
- P4 is the sharpest probe at 9 of 10 stale. **P8 now contributes no
  contradictions**: V1 ruled its four to be de-specifications of one column rename,
  so it carries drops and controls only.
- Drops are not a rounding error: 32 of them, and on P8 five of six are stated as
  current, on P5 three of six. That is the baseline A2's RP1 arm would be measured
  against. P5's fourth residue is excluded rather than uncounted: a never-superseded
  declared source asserts the same material, so no supersession rule could have removed
  it (V9).
- The gating set is therefore **five drafted cases plus P6**, which succeeds today.
  P1, P2, P8 and now P5 are evidence rather than tests: P1 because it is a drop, P2
  because its date lies, P8 because what its later version changed was the grain of
  an attribution rather than its content, P5 because its date is wrong by six days and
  the payload can state no order for it (V20, V21). P8 still exercises the signal — it is the
  one case with no accidental ordering cue at all — but on the drop and control
  columns, not on the gating one.

**These totals have V1–V14, V19, V20 and V21 applied; 3 rulings are
still open, and none of them moves a number.** The
seven rulings between V3 and V8 all left the totals where they were; **V8 is the last one
to move any**, taking the drop total from 31 to 32. It promotes P5's unlisted
`universal-transfer` abridgement to drop **D6**, and re-reading all seventeen of that
case's abridged rows against the test the promotion implies leaves D6 the only one that
qualifies: every other dropped clause is either restated by v3 on a sibling row or
entailed by what its own cell keeps. **V9 then closed the number-moving group without
moving one**: D4 and D5 were already drops, so recording their article residues measures
P5's drop arm at **3 of 6 stated as current** rather than adding a row, and D1's residue
is excluded because a never-superseded declared source asserts the same content.
V19 changed what the staleness column
measures and raised **V20**, which is now ruled: same-day blocks get WP6's undated caveat
instead of a tie-breaker, since no stated signal reaches more than 1 of 412 same-day pairs
on the reference KB. That settles the payload's claim but not P5 — ruling it found v3's
frontmatter date wrong by six days against its own body, so P5's staleness stays out of
the gating count and the reason became **V21**, now **ruled 2026-08-16**: the fixture keeps
v3 verbatim, because both its files are byte-identical to their corpus copies, and P5 is
recorded as an A2 body-date case instead. With P5 out for good, the published rate is
**27 of 39 (69%)** over the five gating cases. The 44-denominator reading is retired:
27 of 44 (61%) and the payload's own 32 of 44 (73%) are the two ends of one band, and
which end you land on depends on a measurement of P5 that V20 ruled unsupported. V4 left P7 with all 8 rows, narrowing only the claim that its staleness
demonstrates *this pair's* ordering being lost, which C8 alone supports. V5 kept P4-C8
at **9 of 10 stale**, since the residual `系统户` prose describes a different level than
the counterparty role the row scores. V6 kept P10-C7 on the replacement it was drafted
with: v2 assigns 全量 to throughput and 剔除后 to efficiency (L377–378), and the ≤120
column the item preferred does not reconcile with v2's own total, so the row re-bases to
2,036 / 1,182 and not to 1,971 / 1,129. V10 touches no total, since P2 already scores
nothing, and closes the one door still open on it: in the section both files date 04-17
the pair agrees verbatim on seven of its eight rows, so C8 is its only cross-document
disagreement — and C8 has no article residue, which leaves option (b) with nothing to
score and makes P2's withdrawal permanent. V11 touches no total either and re-cuts P10's
provenance list: the figures its two stale headline rows are scored on all occur verbatim
in a declared `2026-03-05` co-source that is v1's own companion volume, so the test is the
article's unlabelled presentation, and — as on P7 — the causal claim narrows to C8. V13
moves nothing either and confirms P10's half-year pair on the wording V6 had already
added: v1's 8,916 / 8,378 (L22) and v2's 9,412 / 9,033 (L26) are each that document's own
monthly table summed, no third population is published at this granularity to re-base
onto, and the −6.0% → −4.0% gap measures H2-weighted exclusions rather than a revision.
Its one new fact is article-facing — the change is stated as a 「−4 to −6%」 band whose
endpoints are the two bases, which records on C2 beside L162's blend. The details are in
[the verification pass](#independent-verification-pass-2026-08-15).

---

## Independent verification pass, 2026-08-15

Every row of the seven scoring cases was re-derived from the sources in a fresh
context, one per case, with no access to the drafting reasoning — only the row, the
named fixture versions and the article. Each was asked to open the cited lines rather
than accept a plausible row, and to flag disagreements only. P2 was excluded because
it now gates nothing; its evidence was checked separately by hand (queue item **V10**,
ruled 2026-08-16).

| Case | Items checked | verified | line corrected | disputed |
|---|---|---|---|---|
| P3 | 19 | 16 | 2 | 1 |
| P4 | 20 + X1 | 19 | 0 | 1 |
| P5 | 16 | 15 | 0 | 1 |
| P7 | 14 | 11 | 0 | 3 + 1 case-level |
| P8 | 16 + 6 relocated | 17 | 1 | 4 |
| P9 | 18 | 16 | 1 | 1 |
| P10 | 19 | 17 | 0 | 2 |
| **Total** | **128** | **111** | **4** | **13 + 1 case-level** |

Nothing came back `unverifiable`. The quoting is in good shape: of 128 items only
four had a line number that had drifted, and no row was found to have invented a
quote. What verification did find is concentrated in **classification** — whether a
row is a contradiction at all — and in the **`Article today`** column, which is the
one that scores.

Three whole-set findings came out of it, recorded as notes below rather than as rows,
because they change what the numbers mean:
[co-source assertion](#note-co-source-assertion-confounds-the-staleness-column)
confounds the staleness column; P5's pass is confounded six ways over; and
[several documents contradict themselves](#note-within-version-ambiguity), which the
label's "the earlier version asserts X" phrasing does not allow for.

### Already applied — objective corrections, no ruling needed

These were wrong in a way the sources settle, so they are fixed in place and each
row says so. Listed for audit, not for decision.

| # | Where | Correction |
|---|---|---|
| A1 | P3-D5 | Quote is at v1 L1113; L1114 is `</lark-td>` |
| A2 | P3-K3 | v2 cite moves to L97/L109 — L28 lacks the AI-authorship half the control is about |
| A3 | P3-D1 | Narrowed to the repository count; v2 L20 restates the multi-team half |
| A4 | P5-D5 | Reworded to the dropped rationale only; v3 keeps the removal itself |
| A5 | P5 preamble | "three ways" → six in-body ordering families, plus one in frontmatter |
| A6 | P5 call 2 | 251 → **273** pairable rows; nine → **eight** new ⚠️ endpoints |
| A7 | P5 call 3 | 10 → **17** abridged rows; two → **six** article details carried |
| A8 | P7 headline | 6 of 8 stale *in text*, and 5 of 8 corrections lost, not 8 of 8 |
| A9 | P7-C2/C3/C6 | `Article today` cells rewritten — L57 and L192 carry explicit as-of labels, and v1's 13.3% is absent (recomputed as ~27–34%) |
| A10 | P8 preamble | Four rows replace named individuals with team names; two do not become plain `架构` |
| A11 | P8 drops | Five of six stated as current, not all six — D3's headcount is absent |
| A12 | P8 relocated | v2 L291/L311, not L283/L303 |
| A13 | P9-K2 | v2 range is L53–62; L54–63 omits the 「Fee Conversion」 label cell |
| A14 | P9-C5 | Reworded — the 5 products span Earn, Margin Staked SOL and Spot X, not Earn alone |
| A15 | Totals | Drop total is 30, not 31 |
| A16 | P10-C4 | v1's 45% sits in the sentence *after* the cited one at L84, not the same sentence — the cite is right, the quote boundary was not |

### The queue — 22 items, all settled

Ordered by how much they move the measurement. Owner is the Captain for all of them
except **V16**, which asked whether a document was read rather than how a row should
score and is therefore settled below by evidence; none of the others is an agent's
call, because each either reclassifies a row or changes what a number means. **V1–V15 and
V17–V22 are ruled** — the three that moved the totals, the one
that governs the same item as V3, the one that redefined the staleness column, the one
that settled P7's confound, the one that kept P4-C8, the one that gave same-day sources a
rule, the one that held P10-C7 on v2's throughput basis, the one that kept P3's
manifest material on the drop arm, the one that took P5's drop arm to 6, the one that
then measured what that arm has lost, the one that settled how P5 is reported, the
one that closed P2's revival recipe, the one that re-cut P10's provenance list onto
basis labelling, the one that confirmed P10's half-year pair and found the article
blending its two bases into one band, the one that made P10's roster change additive,
the one that took P4's chained-supersession entry down to a drop followed by a single
supersession, the one that held P4-C9 on its one v2-exclusive residue, the one that
decomposed P10-C5's two days into re-basing, and the one that held P4-C3 on four v1-exclusive
strings while withdrawing its replacement's only one — and each row
records the decision. **Three items were added after the pass
rather than found by it**: V19's ruling raised **V20**, V20's raised **V21** and V15's
raised **V22**, each because settling the item exposed the defect under it. Rulings V21,
V22, V17 and V18 raised nothing further, so the queue closes at 22 and stays closed. **All three items expected to move
a number are ruled**, and so is V22, the last item that could have moved one: V7 left P3 at 8/5, V8 took
the drop total to 32, and V9 moved nothing at all, since D4 and D5 were already on the
drop arm — what it settled is that arm's measurement, 3 of 6 stated as current, with D1's
co-sourced residue excluded. The rest change what a number means or correct
the reasoning under it — V21 included, which moved no total and instead decided which
staleness figure is published, 27 of 39 over the five gating cases, and V10, which moved
no total because P2 scores nothing but retired the recipe that would have brought it
back. **V11 is the same kind**: it moves nothing and changes which of P10's article lines
may be scored, having found call 5's protected list wrong in three places and P10's
co-source confound to be P7's shape. **V13 is the same kind and the smallest of them**:
it confirms an item V6 had already decided in substance, and its one new fact is that the
article states the H1→H2 throughput change as a band spanning both bases rather than as
either document's figure. **V14 is the same kind and reaches further than a wording fix**:
v2's roster is v1's eight teams plus two, so the roster change is additive and the team
family rests on the restated rates alone — and the article turns out to carry v2's rates
for two of the eight and v1's for three, which caps the family at one further scoreable
row and makes it the one place in P10 where a co-source asserts the *replacement* rather
than the superseded value. **V15 is the same kind and its cost is structural**: X1 holds
one supersession rather than two, so it is relabelled as a drop followed by a supersession
over one entity and kept — because P4 is the only staged chain with more than two versions,
which makes the fixture unable to carry a nested supersession at all, and deleting the
entry would have left NG3 with nothing rather than with less. **V22 was the last item that
could have moved a total, and it did not**: P4-C9 keeps its stale verdict on L667's
「(discuss with TR)」 alone, because the passage its other two residues trace to is
byte-identical in v2, v3 and v4 — a whole-tail diff, not a line comparison — while v3
deleted that hedge in the same edit that named TRW, so what the article repeats is a
question v3 answered rather than one v4 stopped asking. P4 stays 9 of 10 and the published
rate 27 of 39. **V17 is the same kind, and its caveat turned out to be an accounting rather
than a hedge**: P10-C5's 13.8 → 15.3 and 17.8 → 19.8 set v1's ≤90 population against an
unfiltered one, because v2's twelve monthly cycle cells are the 03-05 co-source's 全量
column in all twelve months while the ≤120 population v2 declares for efficiency produces
no figure anywhere in it — so all of the H2 gap and 0.92 of H1's 1.5 days is re-basing, the
row keeps its not-stale reading, and the artifact stops before the on-time rows, which
match neither of the co-source's columns in any month. **V18 closed the queue and is the
same kind again**: P4-C3 keeps its stale verdict on four v1-exclusive strings instead of
one, because v1's ambiguity there is a heading against its own 774-line section body and
therefore the earlier version's, which V22's test does not reach — what it costs is R3,
whose only string is v1's own and is also control K4's. **So the queue is settled at 22 of
22**, 21 by ruling and V16 by evidence, with no total moved since V8. That settles the
verification pass and not the confirm pass: 118 rows still read `to confirm`, and a ruling
fixes what a row means where confirmation decides whether it scores.

| # | Item | Location | Finding | Recommendation | If accepted |
|---|---|---|---|---|---|
| **V1** | P8-C1–C4 | P8 → contradictions table | **RULED 2026-08-15: accepted.** The four rows are not incompatible, they are **de-specifications**. v2 keeps `@lucas.wan` over the whole infra category (v2 L19) and glosses him as `Lucas (架构)` (v2 L271), so `团队 = 架构` generalises `Owner = Lucas Wan` rather than contradicting it. Two further findings decided it: the article itself writes both sides (「Lucas Wan / Architecture team」 at L188 and L192), so it is not asserting the superseded value under any staleness rule; and v2 keeps person names in the `团队` column (L154, L291, L311) and still names 「Victor / Lucas」 at L681, so nothing was actually re-attributed away. The draft's own call 3 excludes 「Q2 W6」→「Q2」 for exactly this shape | Struck; moved to the [re-attribution list](#re-attribution-not-contradiction--the-four-rows-v1-struck) | Applied: **P8 → 0 contradictions**, out of the gating set. 7 gating cases → 6; totals 46/30/42 with 29 stale |
| **V2** | P9-C1 | P9 → contradictions table | **RULED 2026-08-15: accepted.** v2 preserves *both* of v1's end-state parts near item-for-item (v2 L175–178 for the self-hosted-OpenClaw half, L182–184 for the in-house TradeGPT agent) — the second is already scored as control **K1**, so scoring C1 had the same material both preserved and superseded. Checked at ruling time: the article's two-component framing (L21, L23–24) is what v2 asserts too, so the row's `stale` verdict was wrong on the facts as well as on the classification. The three pillars are a capability taxonomy on a different axis, and the draft's own call 7 files that material under "additive, not superseding" | Struck; substance folded into K1's evidence rather than a new control, and the pillars added to call 7's additive list | Applied: P9 → 6 contradictions, **3 of 6 stale**; totals 45/30/42 with 28 stale |
| **V3** | P10-C6 | P10 → contradictions table | **RULED 2026-08-15: accepted.** Compares v1's **mean** development duration (L25) against v2's **median** 研发周期 (L28), which v2 L14 defines as development *plus* test — a different statistic over a different span. Checked at ruling time: v2 does carry a same-scope median development duration (the 中位开发时长 column at L49, 1–3 → 4–7 days at L67), and it is compatible with v1's mean 7.3 → 11.3, just as v2's own 「中位低、均值高」 note (L38) predicts; and **no same-basis pair exists to re-cut the row onto**, because v1 reports development duration only as a mean (L25, L73, L177). Keeping it would ask A1 to correct 9.2 days against no replacement value, so R6 was unscoreable | Reclassified as `superseded-drop` **D6**, recorded as a lost drop, with the basis change written into [measurement-basis item 4](#measurement-basis-changes--why-c1c5-c7-and-c8-are-contradictions-rather-than-new-figures) | Applied: P10 → 7 contradictions, **3 stale**; drops → 6; totals 44/31/42 with 27 stale |
| **V4** | P7 case-level | P7 → preamble and headline | **RULED 2026-08-16: the finding is accepted, the scoring restriction is rejected.** The premise is verified exactly — `raw/docs/2026-04-14-infra-双周会-2026_h1.md` (P2's v1) asserts v1's entire 0430 column, confirmed with fixed-string counts at L898 (`40.95`, `24.57`), L904 (`13.3`), L911 (`3000C`), L916 (`合同已提交`), L919 (`117.3`), L921 (`3300`, `83.1`) and L925/L928 (`7197`, `17054`). But "score only C8" rests on attributing staleness to a document *pair*, and supersession is a property of the **compile set**: the set holds 04-14 asserting the old value and v2 asserting otherwise, so a writer emitting it undated mishandled ordering whichever document it read it from — and that co-source is itself superseded inside the fixture by P2's v2. Under V19's ruled criterion all six stale rows stand, because the newest source speaking to each is v2 (2026-05-14). For FX7 the confound cancels outright, since the co-source sits in both arms | All 8 rows stay scoreable. What is restricted is the **causal** claim: only C8 supports "this pair's ordering was lost", so the headline no longer reads 6 of 8 as evidence of ordering loss. Two repairs came with the ruling — C8's test is tightened to the full phrase `识别—分析—跟踪—复盘`, since the bare token `闭环` has 7 hits in the 双周会 on a different loop (L823), and C6 gains an ambiguity note because the newest source in the set may assert its old value | Applied: no total moved. P7 stays a gating case at 6 of 8 stale |
| **V5** | P4-C8 | P4 → contradictions table | **RULED 2026-08-16: the residual is recorded, the row stands.** The five `系统户` mentions are verified (v4 L788, L798, L808, L5683, L5864, none in a 待决策 block) but they are weaker than C7's residual, not stronger, because they describe a different level: three are transType accounting directions in §3.3 engine, one is hedged with 可以考虑, and one is a worked example whose next lines say 「差额公司出」, sitting under a `light-yellow` open question. Against that, the replacement is the cleanest in the chain — v2 L5447–5453 and v3 L5697–5703 are the same table row replaced cell for cell across subject, role and detail 1. Two line-level corrections came out of ruling it: **the pair is v2→v3, not v2→v4** (`差额账户` first appears in v3; v4 shifts the two lines by one with no content change), which independently confirms what **V15** argues for X1; and **`允许透支` is not part of the change**, since it already stands in v2's cell | Row kept and scored on the table row, the same basis call 2 uses for C7. Residual written up as [call 8](#p4-open-judgement-calls); both line corrections applied to the row | Applied: no total moved. P4 stays **9 of 10 stale** |
| **V6** | P10-C7 | P10 → contradictions table | **RULED 2026-08-16: the basis mismatch is real, the repair is rejected, and the row stands exactly as drafted.** The premise holds — v1's 1,907 and 1,081 (L50, L53) are counted after 「剔除交付周期 >90 天」 (L10, L235) while v2's 2,036 and 1,182 are 全量 (L135, L138). What the item missed is that there are **three populations, not two**, so its own repair does not fix what it names: v2's 剔除后 column is filtered at >120 days (L12, L378), so 1,971 / 1,129 is no more v1's basis than 2,036 / 1,182 is. Three checks then settled which of v2's two columns the row belongs on, and all three point away from the item's preference. First, **v2 assigns its datasets by purpose**: 全量 「用于吞吐量统计和长周期分析」 and 剔除版 「用于效率指标计算」 (L377–378). C7 is a throughput claim, so v2's own designated basis for it is 全量. Second, the ≤120 column **does not reconcile with v2's own headline**: its twelve cells sum to 17,578 against a stated 17,777, and its 差异 cells sum to 867 (4.7% of 全量) against the headline's 668 (3.6%) — while the 全量 column sums to exactly 18,445, v2's stated total. The recommended target is the one column in the document that does not add up. Third, **nothing was revised, only re-based**: across all twelve months v1 ≤ v2's ≤120 ≤ v2's 全量 holds without exception (July +64 then +65, October +48 then +53, December +0 then +167), and v1's twelve cells sum to 17,294, its own stated total. Two figures cannot be incompatible as counts of nested populations, which is why this row scores as a re-basing of the same metric rather than a corrected error. **The residual the item wanted to score instead is not v1-only**, which is the reason its second half fails: v2 marks 7月 as 「全年峰值」 (L135) and 10月 as 「国庆+全年最低」 (L138, restated L176) and gives the peak its own section 4.4 (L179), and the swing is 43.3% on v1's basis, 41.9% on 全量 and 42.7% on ≤120 — so both the framing and the ~43% are preserved by v2, and scoring staleness on them would charge A1 for material v2 still asserts | Row kept unchanged, replacement stays **2,036 / 1,182**, and the basis change is recorded in [measurement-basis item 2](#measurement-basis-changes--why-c1c5-c7-and-c8-are-contradictions-rather-than-new-figures) rather than in the row. The stale verdict stands and gains the sharper evidence ruling it produced: article L60 states 1,907 and 1,081 and its next sentence gives the 2025 monthly average as 「approximately 1,537 items」 — and 1,537 is 18,445/12, v2's 全量 average, where v1's own average is 1,441 (17,294/12). The article is therefore not faithfully reporting v1; it splices v1's ≤90 extremes onto v2's 全量 average inside two sentences, and on the replacement the sentence becomes one population (2,036 / 1,182 / 1,537) | Applied: no total moved. P10 stays 7C / 6D / 6K with 3 stale, and totals stay 44/31/42 with 27 stale. **V13 is the same shape and this ruling decides it**: v1's H1 8,916 / H2 8,378 sum to 17,294 (≤90) and v2's 9,412 / 9,033 sum to 18,445 (全量), so its drafted disposition — row unaffected, reasoning corrected — is what this ruling confirms |
| **V7** | P3-D3 vs call 2 | P3 → drops table and open call 2 | **RULED 2026-08-16: the either/or is real, and it resolves to the drop. D3 stands, call 2's promotion is declined.** The overlap is exact, not approximate: D3's cited L635–638 are four lines *inside* the `interfaces[]` array of v1's 「manifest.json 标准格式」 at L630–646, which is call 2's subject, and both cash out in the same four article lines — L119–123, written under the heading 「Example `manifest.json` for the transfer system」. What decided the direction is that **promotion would add a gating row carrying no stale evidence of its own**. The manifest pair has exactly one directly asserted clash, the `version` field (v1 L626 `"2024-04-20"` against v2 L176 `"0.1.0"`), and the article is *current* on it: L125 states v2's semantics in detail — patch bump 「`0.1.0 → 0.1.1`」, `createdAt` preserved, document lists merged. Everything the article is stale on in that section is D3's content. So C9 would gate on the *absence* of `interfaces[]` from v2's 规范, and reading an absence as an assertion is precisely the inference **calls 4 and 6 decline** — call 4 keeps three removed commands as absences rather than contradictions, call 6 leaves the 80K/22K clash unlabelled as inferred. Promoting call 2 while declining those would apply two standards inside one case. Three checks came with the ruling. **v2 carries none of the contract vocabulary**: `idempotent`, `idempotent_key`, `timeout_ms`, `retryable_errors`, `fatal_errors`, `RATE_LIMITED`, `TIMEOUT`, `INSUFFICIENT_BALANCE`, `ACCOUNT_FROZEN`, `幂等`, `超时`, and `QueryTransfer`, `proto_repo`, `tags` — 0 hits each, so the material is absent rather than restated, and no replacement value exists for A1 to write. **The drop is larger than the row states**: v1's array holds two interfaces, and QueryTransfer's contract (L640–645, `idempotent: false`, `timeout_ms: 2000`) is dropped as well, with no article residue. **And the article does carry both schemas**, six lines apart — v1's interface block at L119–123 and v2's versioning semantics at L125 — which is the self-contradiction the feature exists to catch, but it is one article defect, so it may be counted once | Declined. D3 stays a `superseded-drop` and is recorded as a **lost** drop, since the article states it at L119–123; call 2 is rewritten below as a declined promotion rather than a pending one, keeping the manifest-schema clash on record as evidence. Q1's split is what makes this the right side to land on: A1 can only append and v2 supplies no replacement text, so the only thing that can be done with this material is report it, which is RP1–RP3's arm | Applied: **P3 stays 8C / 5D with 6 of 8 stale**, so the totals stay 44/31/42 with 27 stale and the 9/4 branch is closed. This was the first of the three items expected to move a number and it does not — **V8 and V9 were the remaining two, and V8 has since taken the drop total to 32** |
| **V8** | P5 `universal-transfer` | P5 → open call 3 and drops table | **RULED 2026-08-16: promoted, and it is the only one of the seventeen abridgements that qualifies.** The premise is verified exactly: v1 L2730 reads 「跨 UID 转账，资金可转到他人控制的子账户」 and v3 L2652 keeps 「跨 UID 转账」 alone, with 「他人控制」 at 0 hits in v3. What decided it is that promoting one abridgement forces a test on the other sixteen, so all seventeen were re-read side by side, and the test the drafter's four promotions actually embody has **two prongs**: the dropped text must state a proposition its own surviving cell does not entail, **and** v3 must not assert that proposition anywhere else, including on a sibling row of the same family. `universal-transfer` passes both. 跨 UID 转账 does not entail that the destination may be an account under a third party's control — that is the reason the endpoint was removed at all, and the hardening plan glosses the same clause as 「主账户↔任意子账户」 (L116), i.e. arbitrary sub-accounts rather than one's own. It is the shape already promoted as **D4** (「向任意 UID 打款，本质是另一种提现通道」 → 「向任意 UID 打款」, v1 L4744 → v3 L4889) and **D5** (「机构贷款绑定/解绑 UID，影响他人账户」 → 「机构贷款绑定/解绑 UID」, v1 L4007 → v3 L4044). **The second prong is what holds the count at one**, and it is the finding the item did not have: the two borrow rows are not silent losses but a **de-duplication**. v1 states 有清算风险 twice (L3659 fixed-term, L3815 flexible) and 产生利息负债 twice; v3 splits them one apiece, keeping 有清算风险 on fixed-term (L3696) and 产生利息负债 on flexible (L3852), so both propositions still stand in the document and neither row loses one. The same prong declines `create-sub-api`, whose dropped 可能赋予更高权限 survives as the sibling API-key row's 「AI 可给自己加 Withdraw 权限」 (v3 L2998). The remaining seven decline on the first prong: 等于转移持仓价值 is an equivalence gloss of the surviving 跨 UID 移动仓位 — which is itself already scored as control **K2** — 无需用户交互 glosses 静默扣款, 涉及资产分配 glosses 分发优惠券给用户, `update-api`'s 「（权限提升）」 is a label for the clause it follows, `create-sub-member`'s parenthetical expands a 组合攻击链入口 label v3 keeps (1 hit), `delete-api`'s dropped 删除主 API Key duplicates its own Endpoint column, Release Assets merges its two clauses rather than dropping either (v3 L5589 「释放 crypto 给买家，AI 无法判断法币到账」), and the two 配套查询 rows drop only the antecedent's name | Promoted to **P5-D6**, recorded as a **lost** drop on arrival, since article L394 states it as 「Funds can reach accounts controlled by others」 — so V9's finding lands on this row too and it needs no second pass. Three repairs came with the ruling. **The absence test is pinned to the full clause** 「资金可转到他人控制的子账户」 or 「他人控制」, because 「他人」 alone has a hit in v3 — L2958 「冻结子账户影响他人使用」, a row byte-identical to v1 L3015 — which is the string-matching hazard recorded on P7-C2 and tightened on C8 by V4. **The residue is not v1-exclusive**, unlike D5's: the undeclared hardening plan carries the same clause at L116. V16's method still lands it on v1, because the plan's own 「主账户↔任意子账户」 gloss is absent from the article and the plan is neither among the article's 16 declared sources nor staged in the fixture, so it cannot reach the FX4 run at all. And **call 3's count of article residues is seven, not the six A7 recorded** — L394, L396, L397, L399, L402, L416, L427, which is what its own list already enumerates | Applied: **P5 → 5C / 6D / 6K**, and the set totals become **44 contradictions, 32 drops, 42 controls**, with 27 stale unmoved because drops do not gate. D6 is the 129th drafted item and the only one not in the 128-item pass; its absence was verified by negative grep when it was ruled. Of the two open items expected to move a number **V9 is now the last**, and it is on this same arm |
| **V9** | P5-D4/D5 | P5 → drops table | **RULED 2026-08-16: accepted, and the arm was measured whole rather than row by row.** The premise verifies exactly — v1 L4744 「向任意 UID 打款，本质是另一种提现通道」 against v3 L4889 「向任意 UID 打款」, and v1 L4007 「机构贷款绑定/解绑 UID，影响他人账户」 against v3 L4044 「机构贷款绑定/解绑 UID」, with article L427 "alternative withdrawal channel (sends funds to any UID)" and L402 "institutional loan UID binding (affects other accounts)" carrying both dropped clauses. Three findings came with ruling it. **The two rows are not on the same evidential footing**: 「影响他人账户」 has exactly one corpus hit, v1 L4007 — the hardening plan's own line for that endpoint drops the clause (plan L502 「机构贷款绑定/解绑 UID」) — so D5 is a v1 fingerprint, while 「另一种提现通道」 has two, v1 L4744 and plan L96 「商户向任意 UID 打款，本质是另一种提现通道」, which puts **D4 on D6's footing rather than D5's**. It still lands on v1 under V16's method: the article carries no 商户, and the plan is neither declared among the article's 16 sources nor staged in the fixture. **Each row's absence test has to be pinned to the dropped half**, the hazard V8 recorded on D6. For D4 the test is 「另一种提现通道」 (v1 1, v3 0) and *not* 「向任意 UID 打款」, which is v3 L4889's own surviving cell and is asserted in that same abridged form by a declared, never-superseded source (`…保留接口清单按场景.md` L3550); for D5 it is the full 「影响他人账户」 (0 in v3) and not 「影响他人」, which hits v3 L2958 「冻结子账户影响他人使用」. **And V16's recommendation over-reached**: it reads "score D2–D5 as lost drops", but D2 and D3 have no article residue at all — 「注意不要误取消策略性挂单」 (v1 L584) and 「展示全部订单再确认」 (v1 L604) are absent; the article's only cancel-all content is the DCP note at L423, whose row both versions carry with an identical 「断线保护设置」 备注 (v1 L725–728, v3 L724–727), and its batch-order line (L406) states only the confirmation requirement v3 L603 keeps. What V16 settled is *whose* the residues are, not that there are four of them | D4 and D5 each record the article line and the pinned test, and the drops table gains the arm's measurement: **3 of 6 stated as current** (D4, D5, D6). **D1 is a fourth article residue and is deliberately not counted**, which is call 1's reasoning applied to the measurement — the leverage-token content at article L413 and L567 is over-determined by two declared, never-superseded sources, one of which lists Purchase and Redeem as *retained* with 「执行前需确认」 (`…保留接口清单按场景.md` L514–537; `…能力清单.md` L260 supplies L567), so counting it would charge the chain for material no supersession rule could have removed. One near-miss is recorded with it: the article's generic confirmation card (L320, L580) is not D3's batch-specific 「展示全部订单再确认」, and a grader matching on "review before confirming" will read it as one | Applied: **no total moves** — 44/32/42 with 27 stale, since D4 and D5 were already on the drop arm. What lands is the arm's measured figure, **P5 3 of 6**, alongside P8's 5 of 6. This was the last of the three items expected to move a number and it moves none; **no item still open moves a total** |
| **V10** | P2 evidence | P2 → evidence table and open call 2 | **RULED 2026-08-16: accepted, and in a stronger form than raised.** The premise verifies exactly — in the section both files date 04-17 they **agree** on vLLM at 90% (v1 L1358, v2 L405) and the 100% is exclusive to the 04-14 file's 05-04 section (L399), so row 3 offers as proof of disagreement the one exhibit that shows agreement. Generalising the check settled the call outright: **each of C1–C7's cited v2 lines is present verbatim in v1's 04-17 section** (v2 L953 → v1 L1910, L969 → L1926, L448 → L1405, L451 → L1408, L578 → L1535, L585 → L1542, L405 → L1358), while all eight `v1` cites point into the 05-04 section, which starts at L81 against the 04-17 section's L1025. So the rows are not a mix of ambiguous and unambiguous ones; C1–C7 uniformly set v1's 05-04 reporting against v2's 04-17 reporting, and **C8 is the only row where the two documents disagree about the same date** — v1 L1776–1786 and v2 L819–829 are byte-identical apart from two dashboard image tokens and the 进度总览 figure, 56% against 20%. Three findings came with ruling it. **C7 is weaker than an ambiguity**: all three vLLM lines carry identical counts 「sitnet 8/10，testnet 1/1， mainnet 11/12」, so 100% re-grades an unchanged measurement, and v1's parent line L398 still reads 【80%进行中】 over its own 进度100% child. **Two string hazards**, the P7-C2 class: v1's 56% is split across three `<text color="green">` spans, so `grep -F "56%"` misses the cited L1781 and finds only L783, and the article's four `56` hits are all alert-RCA coverage. **And the revival recipe does not survive its own arithmetic** — C8 has no article residue, while C7 and C3, the two rows with residues, have the article asserting both figures (90% at L445 against 100% at L580/L760; 87.5% at L733 against 90% at L759), which is what V1 struck P8's rows for | Row 3 restated as the verbatim-agreement finding, call 2 rewritten from "C7 and C8 are unambiguous" to "C8 alone is a cross-document disagreement", and both hazards recorded on their rows. New [call 6](#p2-open-judgement-calls) records that option (b) yields one contradiction and zero staleness observations, so **(c) is permanent rather than a triage choice**. The inversion conclusion **stands and is better supported**: an in-place amendment of one figure inside an otherwise byte-identical section is stronger evidence that the 04-14 file is the later document than differing figures would be | Applied: no total moved — P2 scores nothing either way. What changes is that P2 is now documented as unrevivable as a scoring case, rather than as a case with a recipe waiting |
| **V11** | P10 call 5 | P10 → open call 5 | **RULED 2026-08-16: both halves verify, the first is larger than stated, and a third error sits in the same direction as it.** The full-data report (`raw/local/2026-03-05-2025-engineering-efficiency-report-full.md`, declared by the article, staged nowhere) carries **1,907** at L95, **1,081** at L98 and January's **45.0%** at L89 — but as the 剔除后 half of a two-column comparison whose header says what that column is: 「对比版本：[剔除版](2025-engineering-efficiency-report.md)（剔除交付周期 >90 天的需求后 17,294 件）」 (L14, restated L208). **Those cells are v1's series by declaration rather than by coincidence**: the 剔除后 column sums to 8,916 / 8,378 / 17,294 (L89–100) and its quarterly row to 4,073 + 4,843 and 4,651 + 3,727 (L112), v1's own halves and total, while the 全量 column sums to 9,412 / 9,033 / 18,445, v2's. The document is also v2's *input* and not its rival: its 4.3 recommends 「剔除阈值建议调整为 120 天」 (L193–195), the change C1 scores. So "not v1-exclusive" is true as a string fact and buys nothing — **the co-source is v1's companion, quoting v1's population and naming the file.** Three measurements bound it. Under V19's per-claim criterion the newest source speaking to either item is still v2, 03-05 against a chain head of 03-06 — the gap V19's row and test-set.md already recorded without measuring what it covers — so **V4's ruling applies unchanged and both rows keep their stale verdicts**. What it covers is **2 of P10's 3 stale rows**: C4 and C7 have a second possible cause, C8 has none, since 「44.6」 and 「22.0」 are v1-exclusive across all five sources and are what article L282 states. And it **does not reach the fixture run**, since `data/kb-supersession-fixture/raw/local/` holds the two chain files only, so it qualifies the drafted reading of today's article rather than FX5. Two notes come with it: v1 and the full report share `2026-03-05`, so WP9 leaves the payload no ordering claim between them either, which is a second reason no *document*-level attribution of L60 is available; and the full report's 984 is its long-cycle count (its L66–77 table sums to exactly 984) where 18,445 − 17,294 = 1,151, v1's own 「约占 6.3%」 (L235) — so the article's L30 row inherits a mismatch the co-source made, 17,294 + 984 = 18,278. **The second half verifies and lands more firmly than "mis-transcribed": 「9.3 days」 is in no source.** Every `9.3` across the five is something else — v2's section heading 9.3, the full report's 2月 39.3%, the Q1 report's 19.3% — while v1 states 「~9.2 天」 twice (L25, L177). Two routes reach 9.3 and both start at v1: 9.2 mis-keyed, or the unweighted mean of v1's own 7.3 / 11.3, which article L50 carries verbatim (weighted by 8,916 and 8,378 it is 9.24, which is why v1 writes 9.2). Either way L170 is D6's material and **D6's row already claims it**, so call 5 and the drops table contradicted each other and the drops table was right. **The third error is in the item's own first direction**: 「28% (full-data view)」 (L84) is not the full-data view. The full report's 全量 Q4 on-time rate is 26.7% (L119); 28.0% is its 剔除后 Q4 (L120) and v1's own (L75, restated 「按时率仅 28%」 at L80), i.e. the ≤90 figure under a full-data label — and v2 restates Q4 at 15% (L211), so the article is stale on it and the entry was protecting nothing | **The list is re-cut on basis labelling rather than provenance**, the axis A9 already used on P7's L57 and L192: a figure is protected where the article states the basis it belongs to, and scoreable where it is stated bare as a fact about 2025, whichever document also contains it. Protected: the dataset table (L27–31) and the Q4 full-vs-filtered table (L260–263), both of which name their columns and neither of which offers a figure as current — 37.0 and 24.9 are full-report-only (L114–115, restated L123) while its two Q4 medians are shared, 21.5 with v2 L60 and 18.5 with v1 L74, so even here it is the labelling and not the string that protects the lines. Struck from the list: L84's 28%, and L170's 9.3, which moves to the scoreable side as D6's fourth residue. Recorded rather than protected: L60's extremes and L84's 45%, which the co-source **contains but never claims** — it nowhere calls 1,907 a peak, 1,081 a trough or 45.0% the year's best month, and those framings are v1's sentences (L59, L32). **So this case's staleness tests are presentation-level, not string-level**, the opposite of P5's, where V8 and V9 pinned each row to a clause: every figure C4 and C7 score occurs verbatim in a declared, never-superseded source, so no fixed string can carry the test. D6 gains the hazard that follows from the same finding — the article writes 9.3 where v1 writes 9.2, so a grader testing 「9.2」 reads the residue as absent. And the Q4 on-time pair (v1 28.0% → v2 15%) joins [call 3](#p10-open-judgement-calls) as a derivative of C3 with the article stale on it, phrased the way call 2 already phrases that shape | Applied: **no total moves** — 44/32/42 with 27 of 39 stale, and P10 stays 7C / 6D / 6K with 3 stale. The Q4 pair is recorded as derivative on call 3's standard and call 4's precedent rather than promoted; taking it would read 4 of 9. What changes is which article lines may be scored, and what P10's stale column means: like P7's, **its causal claim narrows to C8**, the one row whose evidence no co-source shares. One finding is handed to **V13** rather than pre-empted — the full report publishes both of V13's pairs, 8,916 / 8,378 as its 剔除后 sums and 9,412 / 9,033 as its 全量 sums, so the two populations sit side by side in one 03-05 document: string-exclusive to v1 and v2 respectively, but both arithmetically co-asserted by that single co-source |
| **V12** | P10 item 4 | P10 → measurement-basis item 4 | **RULED 2026-08-15: accepted**, applied together with V3 since both govern the same item. "v2 reports no mean anywhere" is false — v2 L38 「均值 13-20 天」, L82 「均值产品准备期 13.5 天」, L271 「平均周期 172 天」 | Restricted to development duration, where `平均开发时长` returns 0 hits in v2 | Applied; item 4 rewritten, and it is what carried V3 |
| **V13** | P10 item 2 | P10 → measurement-basis item 2 | **RULED 2026-08-16: confirmed on V6's wording, the confirmation is firmer than the item claims, and the one thing it missed is that this material reaches the article.** The premise verifies with the cites it was drafted without: v1 L22 「需求吞吐量 \| 17,294 件 \| 8,916 件 \| 8,378 件 \| -6.0%」 against v2 L26 「18,445 件 \| 9,412 件 \| 9,033 件 \| -4.0%」, and each pair is that document's own monthly table summed — v1's twelve 总交付 cells (L44–55) give 8,916 / 8,378 and v2's twelve 全量 cells (L129–140) give 9,412 / 9,033 — so both documents reconcile at half-year granularity and this is C7's shape one level up, exactly as drafted. Three findings come with confirming it. **There is no third population at this granularity**, so V6's rejected repair has no counterpart here: v2 publishes half-year throughput on 全量 alone, and its 剔除后 halves — 9,035 / 8,543, which it never prints — could not be published consistently anyway, since they total 17,578 against its own stated 17,777. 「Three populations, not two」 is a fact about v2's monthly cells; at half-year granularity the item's two pairs are the only two published, which is why the confirmation is stronger than a restatement of V6. **The −6.0% → −4.0% gap is a measurable basis artifact rather than a revision**: both filters cut more from H2 than from H1 — ≤90 removes 496 items and 655 (9,412−8,916, 9,033−8,378, together v1's own 1,151), ≤120 removes 377 and 490 (v2's 差异 cells, together 867 against its stated 668) — so the decline flattens monotonically as the population widens, −6.03% on v1's basis, −5.45% on the unpublished ≤120 series, −4.03% on 全量, and V6's v1 ≤ 剔除后 ≤ 全量 ordering holds here too (8,916 ≤ 9,035 ≤ 9,412, 8,378 ≤ 8,543 ≤ 9,033). **V11's handed finding verifies and lands harder than 「arithmetically co-asserted」**: the co-source's 剔除后 column is not merely summable to v1's halves, it *is* v1's monthly table cell for cell in all twelve months (full L89–100 against v1 L44–55), its quarterly 剔除后 row giving 4,073 + 4,843 and 4,651 + 3,727 (L112), while its 全量 column reproduces v2's halves at both granularities (L89–100, L111). It prints no half-year row, though, so 「8,916」 and 「9,412」 stay string-exclusive to v1 and v2 across all five sources — the one place in P10 where a fixed string still tests what it appears to, and it is unscored. **What the item did not have is that the article carries this pair's derived figure three times, as a blend**: L56 「Throughput decline \| Only −4 to −6%」, L58 「(−4–6%)」 and L301 「throughput declined only 4–6% H1」, a band whose endpoints are v2's −4.0% and v1's −6.0% | **Say so, as drafted — the wording V6 added covers it**, and item 2 gains the two cites, the half-year monotonicity and the absence of a third pair. **The blend records on C2 rather than as staleness**, which is where the same defect already sits: L162's 「17,294–17,777 data points」 is this shape at the population level and L56 / L58 / L301 are it at the rate level. It is not a stale assertion under V1's precedent — an article writing both sides is not asserting the superseded one — and the band is not even false, since the ≤120 series' −5.4% falls inside it; what it loses is which population each endpoint belongs to, the presentation-level defect V11 named for this whole case. Call 3 already lists 「H1→H2 change −6.0% → −4.0%」 among the derivatives left out and is corrected to say the article carries it blended rather than not at all. Two notes for a grader come with it. **Nothing else in that sentence is v1's**: v2 L37 asserts 「吞吐量基本稳定：H1/H2 仅差 4%，团队产出能力没有显著变化」 and v2 L217 「需求复杂度上升」, so the stability framing, the capacity claim and the complexity gloss the article gives at L58 are all preserved and only the −6% endpoint is v1's — the shape V6 found for C7's peak/trough framing. And **L301 is the article's unterminated final line**, ending mid-sentence after 「H1」 with no trailing newline, so a check on that occurrence cannot expect a complete clause | Applied: **no total moves** — 44/32/42 with 27 of 39 stale, and P10 stays 7C / 6D / 6K with 3 stale, so the drafted disposition (row unaffected, reasoning corrected) is what this ruling confirms. Item 2 carries the cites and the two arithmetic findings, C2's `Article today` cell gains the third blended line, and the co-source note's 「tests cannot be strings at all」 is bounded to the scored rows. The queue read **17 settled, 4 open** at this ruling — V14, V15, V17 and V18, none of which moves a number — and **V14 has since taken it to 18 and 3, V15 to 19 settled of 22 items** with 3 still open, since ruling it raised **V22** |
| **V14** | P10 call 4 | P10 → open call 4 | **RULED 2026-08-16: accepted, and the correction reaches the classification rather than only the wording.** The premise verifies exactly — v1's eight rows are Fiat Channel, BigData, Asset, UserService, ToB, Compliance, SBU Business and Salesforce (L98–105), and v2's ten are the same eight in the same order with **Trading Engine** and **Finance** inserted before Salesforce (L230–239), both names 0 hits in v1. So the roster change is **purely additive**, which is NG1 material rather than supersession, and what makes the team rows a contradiction family is the restated rates alone. The call's other half verifies cell by cell: **16 of 16 on-time rates are restated downward** (Fiat 54.8→45.3 and 31.5→23.7, BigData 41.0→37.2 and 37.5→14.5, Asset 23.7→11.2 and 18.0→7.9, UserService 44.6→37.2 and 22.0→12.1, ToB 50.3→42.0 and 24.6→18.1, Compliance 36.4→17.2 and 15.7→9.0, SBU Business 50.8→46.7 and 23.6→18.0, Salesforce 39.1→19.6 and 29.1→4.8), which is the direction C1's basis change predicts — widening ≤90 to ≤120 admits late items — and v1 L115 does call UserService 「恶化幅度全公司最大」. Four findings came with ruling it. **The article is not uniformly stale on the family**: of the eight shared teams only five carry an on-time rate at all, three of them v1's (Fiat 「55% → 32%」 at L277, UserService 44.6 → 22.0 at L282, Compliance 36% → 15.7% at L283) and **two of them v2's** (Asset 11.2–7.9 at L281, Salesforce 4.8% at L284), while BigData, SBU Business and ToB carry none — and v2's two additions both reach the article with v2's own figures, Trading Engine's 28 days at L286 credited to 「the 2025 v2 analysis」 and Finance at L285. So the family's ceiling is two further rows, not seven. **Compliance is the cleaner second entry, not Fiat Channel.** The article gives Fiat v1's *prose rounding* (v1 L114 「按时率从 55% 降至 32%」) rather than its table cells, so an absence test on 54.8 / 31.5 reads the residue as gone — and both strings are ambiguous besides. `54.8` names two metrics inside v1, the `+54.8%` development-duration increase (L25) and Fiat's Q1 rate (L98), and the article's only two hits are the former (L21, L50), so the test reads a false positive on D6's material. `31.5` names three: Fiat's Q4 rate (v1 L98), February's 技术需求占比 (v1 L45, D1's own metric) and a 121–180-day bucket share in the full-data co-source (L28). Compliance's L283 carries v1's table value 15.7% itself — 1 hit in v1, 0 in v2, 0 in all three co-sources — with its hazard on the replacement side instead: 17.2% (v2 L235) collides with v1's Compliance Q1 交付周期 17.2天 (v1 L103), one number naming a rate in one version and a cycle in the other. **C8's own replacement is not unique**: v2 states 37.2% for both BigData Q1 (L231) and UserService Q1 (L233), and the 2026 Q1 co-source states it twice more (L174, L176), so the test stays on the superseded side, where V11 established 「44.6」 / 「22.0」 as v1-exclusive across all five sources. **And the co-source confound runs the opposite way here from C4 and C7**: the 2026 Q1 report (03-06) reproduces v2's 2025 team Q1 rates as its year-ago baseline column (L173 45.3, L174 37.2, L176 37.2, L178 17.2, L180 9.0), so the *replacement* side is co-asserted by a same-day source while the *superseded* side is the oldest document's alone — which makes the team rows the cleanest stale rows in the case under V19's criterion. Two apparent co-source hits on the superseded side are coincidences of different metrics: the full report's `31.5%` (L28) and its `12.1` (L116, L123, a mean-vs-median gap in days) | Corrected as recommended, and the four findings land where they are testable. Call 4 now reads 「v1's same eight teams plus Trading Engine and Finance」, records the roster change as **additive** rather than as part of the family, and carries the per-row split — 3 stale, 2 current, 3 unquoted, both additions absorbed — with the ceiling that follows from it. The second-entry sentence keeps both candidates and names **Compliance** as the cleaner one with both hazards attached. C8's row gains the 37.2 collision and the reverse-direction confound; the [co-source note](#note-co-source-assertion-confounds-the-staleness-column) gains a paragraph for the same finding. Two observations are recorded with the split. Every team bullet **pairs a 2025 clause from the chain with a Q1-2026 clause from a co-source** (L282's 33.5 days / 19.1%, L283's 7.8%), so what is stale is the 2025 half of a sentence whose 2026 half is current — V11's presentation-level defect one level finer. And the article's roster is **11**, not 8 or 10: Group Risk Control (L280) comes from the Q1 co-source (its L145, L165), so the article's roster is the union of the compile set, which is further evidence the additions were absorbed rather than mishandled | Applied: **no total moves** — 44/32/42 with 27 of 39 stale, and P10 stays 7C / 6D / 6K with 3 stale. The second entry stays unpromoted, so the family still contributes one labelled row; promoting Compliance would read 45 contradictions and 28 of 40 stale, and it is recorded as available on that arithmetic rather than taken |
| **V15** | P4-X1 | P4 → chained-supersession entry | **RULED 2026-08-17: both halves of the premise verify, and the entry is relabelled rather than deleted — on a fixture-level measurement neither drafted option had.** The landing point is now confirmed three ways rather than two. Fixed-string counts across v1–v4 give `差额账户` 0/0/2/2, `TRW` 0/0/1/1 and `交易系统户` 0/1/0/0; v3 carries the row at L5697 「交易系统内的差额账户」, L5703 「…和差额账户结算 ， 允许透支」 and L5705 「…现货和持仓处置(给到TRW处置)」; and the **whole-file** v3→v4 diff is four changes only — `date`, `checksum`, and three 进展 cells (L5659 gains 「联调结束」, L5675 「60%」→「开发90%，下周可以联调」, L5775 「开发中」→「联调中」) — so v4 shifts this material by one line and touches nothing in it. That re-derives V5's grep result from the diff rather than from a hit count. The second half verifies harder than 「reframing」: **v1 asserts no counterparty at all.** Its only two 对手方 hits are the `opponent_user_id` field descriptions (L845, L1858); its one 系统账号 mention is an engine task line in §5 分工与排期 (L4776); and v2's §5 is a table v1 does not have (`rows="11" cols="3"`), so v2's row is new material and v1's line is separately scored as **D3**. One same-predicate replacement remains — v2→v3, already scored as **C8** (settlement) and **C9** (disposal). Three findings came with ruling it. **P4 contains no nested supersession anywhere**: projecting the v1→v2 and v2→v3 diffs onto v2's line numbers and intersecting them leaves 34 lines, every one either v2-introduced (§5's row at L5447/L5453/L5455, `uta_delayed_fee_record`'s DDL, `uta_auto_add_margin_log`'s `action` at L3954, 兑币流水回滚 at L5442) or identical in v1 and v2 and changed once at v3 (`set_time`: v1's cell 「设置时间（纳秒）」 = v2's cell and DDL 「(纳秒)」 → v3 「(ms)」) — and v3→v4's three cells sit in the 进展 column v3 itself added (v2 `cols="3"` → v3 `cols="4"`), so they are first assertions rather than nestings. **Neither does the fixture**: of the 38 staged files P4 is the only chain with more than two versions, and its one co-source is not staged, so no nested supersession can be cut from this test set by relabelling any case — which is what decides the disposition. **The article is why the entry is worth keeping**: it asserts v1's dropped state (L396 pre-created reconciliation accounts) and v2's superseded one (L421's 「System Account (交易系统户)」 heading, L423–424's counterparty and overdraft sentences, L667's row ending 「(discuss with TR)」) as one current section, while 差额 and TRW are 0 hits — three states, the two oldest merged and asserted, the newest absent | **Ruled: relabel, do not delete.** Both drafted options are rejected. 「Rewrite as v2→v3」 keeps the chained-supersession category for material that holds one link and turns X1 into a non-scoring duplicate of C8 / C9; 「record none」 removes the only multi-step trail evidence in the set, and the measurement above shows it cannot be replaced from elsewhere. The entry and its section become **[one entity, three states — a drop then a supersession](#one-entity-three-states--a-drop-then-a-supersession-evidence-for-ng3-not-scored)**, with the article evidence and the no-nesting measurement written into it, and call 4 is marked ruled. Ruling it also raises **V22** on C9 | Applied: **no total moves** — 44/32/42 with 27 of 39 stale, and P4 stays 10C / 4D / 6K at 9 of 10. X1 stays unscored and its two ends stay D3 and C8 / C9, so nothing is double-counted. Three things change: the section and row are rewritten, the fixture-level fact is recorded where NG3 is quoted (the totals note above and spec.md's NG3), and the queue reads **22 items, 19 settled and 3 open** — V17, V18 and the new V22, of which only V22 could move a number. **V22 has since been ruled and moved none**, taking the queue to 20 settled and 2 open: P4-C9 stands on L667 alone, because the 待决策 passage its other two residues trace to is byte-identical in v2, v3 and v4 |
| **V16** | P5 undeclared source | P5 → open call 3 | **RESOLVED 2026-08-15, no ruling needed** — the hardening plan carries those rationales, but so does v1, and nothing the plan asserts *alone* reaches the article. Evidence [below](#v16--resolved-by-investigation-no-ruling-needed) | Score D2–D5 as lost drops; the residues are v1's — **the D2–D3 half is wrong and ruling V9 corrected it**: neither clause reaches the article, so only D4 and D5 are lost | No provenance gap. Queue drops to 18 |
| **V17** | P10-C5 | P10 → contradictions table | **RULED 2026-08-17: the row stands, and the caveat is larger than it was drafted — v2's efficiency series is not the population v2 declares, it is the co-source's unfiltered column.** The premise verifies exactly and then hardens three times. v2's twelve monthly 中位整体周期 cells (L51–62) equal the `2026-03-05` full report's 全量中位周期 column (full L89–100) in **12 of 12** months and its 剔除后 column in 2 — April and June, the only months where those two columns agree anyway — so C5 sets v1's ≤90 series against an **unfiltered** one, v1's side being the co-source's 剔除后 column by declaration (V11) and by identity with v1's own quarterly medians 13.5 / 14.5 / 15.5 / 18.5 (v1 L74, full L118). **The declared basis is not merely mislabelled, it is unused**: v2 L378 assigns the 17,777-item >120 population 「用于效率指标计算」, and `17,777` occurs twice in v2, at L12 and L378, both of them declarations — no figure in the document is computed on it. **December decides it deductively, with no assumption about density**: v2's own §4.1 puts December's filtered count at 1,300 (L140, 全量 1,467 less 167) and the co-source puts its >90-filtered count at the same 1,300 (full L100), so the >120 set is the >90 set and the two filtered Decembers are the same 167-item removal — a >120-filtered December median would then be the co-source's **18.5**, not the **22.5** v2 publishes, which is the unfiltered cell. **The same lift shows in a second column**: v2's §4.1 长周期占比 (L129–140) is the co-source's 占当月总数比 column (full L66–77) verbatim in all twelve months, a rate built on the >90 counts (36 / 1,184 = 3.0%) sitting beside v2's own >120 差异 cells, from which the same rates read 3.8% / 4.9% / 5.1% and so on — so the cycle medians are one instance of a habit rather than a one-off. **Where the artifact stops is measurable too, and it stops before the on-time rows**: filtering moves an on-time rate by +0.4 to +1.6pp, the co-source's own 「按时率差异全年在 1-2 个百分点以内」 (full L105), while v2's monthly 按时率 column sits **7.4 to 13.9pp below** the 全量 column in all twelve months and matches neither column in any month, so C3, C4 and C8 rest on a measurement v2 made rather than on a column it re-based, and nothing here reaches them. Verified independently by comparing all 24 cycle cells, all 24 on-time cells, both count columns and both rate columns | **Ruled: C5 stands as a superseded-contradiction, and the delta is decomposed rather than the row deprecated.** It stands because both versions assert the same statistic over the same span — v1 L144 defines 中位交付周期 as 「从需求创建到交付的中位天数」, and v2 L14–15 make 整体交付周期 the sum of 产品准备期 and 研发周期 with 产品准备期 starting at 需求创建 — which is what separates C5 from C6, the row V3 reclassified for pairing a mean against a median. **The caveat is now arithmetic**: on the same twelve cells the basis change alone moves the half-year mean by +0.92 days in H1 and +2.00 in H2, against published deltas of +1.5 and +2.0, so **the whole of the H2 gap is re-basing and 0.58 of H1's 1.5 days survives it**. Stated with its limit: a mean of twelve monthly medians is not a population median, and it reproduces both published H2 figures to the decimal (17.83 → 17.8, 19.83 → 19.8) but neither H1 figure (14.25 against 13.8, 15.17 against 15.3), so this is a reconstruction from the cells rather than the publishers' arithmetic recovered. **The two versions agree on the shape**: +29.0% against +29.6%, a 0.6pp spread on the H1→H2 change under a 1.5–2.0 day spread on the levels, so C5 contradicts on level and not on trend — and v2's +29.6% does not reproduce from its own 15.3 / 19.8, which give +29.4%. **So the drafted restriction is accepted in a sharper form**: on H2 C5 is not evidence of degradation at all, and the article never asked it to be, since its H2-decline paragraph runs on 研发周期 5.0 → 8.5 (article L21, L51) and on the on-time series, neither of which this finding touches. Basis item 1 gains the correction that C5 re-bases ≤90 → **unfiltered** rather than ≤90 → ≤120, item 2 that v2's purpose split holds for throughput and fails for the efficiency cycle series, and item 5 that the on-time restatement cannot be attributed to filtering either | Applied: **no total moves** — 44/32/42 with 27 of 39 stale (69%), and P10 stays 7C / 6D / 6K at 3 of 7. C5 keeps 「not stale, replacement also missing」, re-verified: `13.8`, `17.8`, `15.3`, `19.8`, 「~15」 and 「~17」 are 0 hits in the article, whose only company-level 2025 delivery-cycle medians are the labelled Q4 pair at L262–263 that V11 protected. **Nothing becomes newly scoreable**: article L17 does describe the v2 analysis as covering 17,777 after excluding the 668 items over 120 days, which this ruling shows is not the population v2's efficiency figures come from, but that label is v2's own (L12, L378), so the article inherits the misdeclaration rather than introducing it. Two findings are recorded outside C5 and neither raises an item. The co-source's 984 headline is the sum of its §1.3 distribution table (full L66–77) while its own §2.1 removals sum to 1,151 (full L89–100), the two series differing in 11 of 12 months — that is where the 984-against-1,151 gap **V11** recorded comes from, and 984 is also the second series' Jan–Nov subtotal, a coincidence rather than the cause. And the article's 「A further 167 requirements fall in a boundary zone (91–120 days)」 (L34) states a December long-cycle cell, v2 L140's 差异, where both documents give the 91–120 count as 483 (full L27, restated L194, and 1,151 − 668 independently) — a defect on C1's subject that leaves C1 not stale, since C1 is tested on the rule, which the article carries at L17 and L116. The queue closes at **22 items, 21 settled and 1 open** — V18, which cannot move a number either |
| **V18** | P4-C3 | P4 → contradictions table | **RULED 2026-08-17: the row stands on four clean strings instead of one, and the ambiguity is a heading against its own section body rather than two adjacent lines.** The premise verifies exactly — `uta_liq_trans_log` is 1 hit in v1 and 0 in v2, v3 and v4, `translog_realtime` is already 2 in v1, and L1763 is control **K4**'s line — and then the shape of it changes. **L1761 is a heading and its section runs to L2534**: across those 774 lines the monthly name never occurs again, while the body specifies the replacement in its first line and the three after it — 「translog_realtime 实时translog表（TiDB单表，日分区，7天滚动）」 (L1763), the shared data source (L1765), the single-table daily-partition strategy with a 7-day window (L1767), and a 53-row schema table headed 「translog_realtime 表结构」 (L1771, L1775). So v1 does not assert two designs two lines apart; it carries a heading its own section has outgrown, and the monthly table has a name and four clauses and no specification anywhere. **v2 finishes that job rather than starting it**: it rewrites the heading to 「资金流水记录表 translog_realtime (TiDB)」 (L1888) and adds the two things v1 lacked, `CREATE TABLE translog_realtime` (v2 L2681, v4 L2904) and a 常用查询SQL section of six `FROM translog_realtime` blocks (v2 L2754, v4 L2977) — which is what takes the token from 2 hits to 11 and holds there through v4. **The superseded side is four v1-exclusive strings rather than one**: 「按月存储」, 「过往数据可以删除」, 「表结构和translog保持一致」 and the table name are each 1/0/0/0 across the chain, all four deleted in the same v2 edit. **The replacement side has none**, which is the finding that matters here: `translog_realtime` is v1's own string and is precisely K4's, so a presence test on it reads the control rather than the replacement and only a count discriminates — V22's precedent, this time on an R-side row. What does discriminate is an **attachment**: 「用于快速过滤出受影响的用户和资金损失」 is 1/1/1/1, sitting inside v1's heading beside the monthly name and on its own line under v2–v4's translog_realtime heading (v2 L1890, v4 L2113). **And P4's one co-source is silent here, as V22 found it silent on C9**: `uta_liq_trans_log`, `translog_realtime`, 「资金流水」 and `202605` are 0 hits in `raw/docs/2026-04-20-a23-异常交易回滚-仓位字段回滚分析.md`, whose eight `translog` hits are seven lines of engine rollback pseudocode and field notes plus one 资金流(translog) wiki mention, so this row's verdict needs no narrowing the way P7's and P10's did. Verified independently across all four versions, the co-source and the article, with the section bounded on v1's own heading list | **Ruled: C3 stands, and the caveat points at R3 instead of at the staleness.** Two things keep the ambiguity away from the stale verdict. It is the **earlier** version's, so the test V19 and V22 established — the newest source speaking to the item has to be unambiguous — is satisfied outright: v2, v3 and v4 name translog_realtime in the heading, the body, the DDL and six queries, with no monthly residue at all. And the article states the superseded claim in a form no later version offers, as its own table section: **`#### uta_liq_trans_log (Monthly Partitioned)`** (L469), 「Structure is **identical to the translog table**」 and 「Partitioned by month (e.g., `uta_liq_trans_log_202605`)」 (L471) — three of v1's four heading clauses, the deletability being the one it drops. What the ambiguity does reach is R3. The article carries a **`#### translog_realtime`** section nine lines above (L460–467) with K4's content intact, never says the two are the same table, and leaves the purpose clause at L471 under the monthly heading, which is v1's attachment — so the article reproduces v1's heading-versus-body split rather than resolving it, and **R3 is recorded as not carried and scoreable only as an attachment**, never as a string. The transition is corrected the way V5 corrected C8's and V22 corrected C9's, the third time this column has cited v4 for an edit v2 made: the pair is v1 L1761 → **v2** L1888, and v4 L2111 is that heading shifted 223 lines. The within-version note's row is rewritten onto heading-against-body, and the judgement inside it — whether a heading-only claim that 774 lines of its own section contradict should score as a supersession — becomes **P4 open call 9** instead of staying implicit | Applied: **no total moves** — 44/32/42 with 27 of 39 stale (69%), and P4 stays 10C / 4D / 6K at **9 of 10**. C3 keeps its stale verdict and gains three more clean strings; R3 loses the only one it had. **The queue is closed**: 22 items, 21 ruled and V16 settled by evidence, none open, and no total has moved since V8. That closes the verification pass and not the confirm pass — **118 rows still read `to confirm`** — because a ruling settles what a row means while confirmation is the separate human decision about whether it scores |
| **V19** | FX5 criterion | spec.md FX5 | **RULED 2026-08-16: accepted in a tightened form.** Staleness read "the earlier value appears in the article", which over-attributes. Two findings at ruling time reshaped the fix. First, the drafted wording *"the newest source in the compile set"* is wrong per document and had to become **the newest source that speaks to that item**, since the newest document is usually silent on any one claim and the drafted form would clear an item whenever the latest source simply did not mention it. Second, the item's own rationale does not hold: it invokes V4, but no fixture co-source is newer than its chain head except P5's — P7's is `2026-04-14` against a chain head of `2026-05-14`, P10's `2026-03-05` against `2026-03-06` — so the restatement answers **V4 in no case**, and V4 must still be ruled on its own | Applied to both staleness columns in test-set.md's Scoring table and to FX5, per claim rather than per document. FX7's gate is unaffected, since it counts corrections carried | Applied: no total moved. Ruling it surfaced **V20**, and P5 leaves the gating column — V20 is now ruled and P5 stays out, on V21's grounds rather than on an unruled tie |
| **V20** | Same-day source order | `py/src/kb_ai/core/merge.py` (WP family) | **RULED 2026-08-16: accepted, and settled on the caveat rather than a tie-breaker.** Raised by ruling V19. `build_source_blocks` sorts dated blocks `(date, source_path)` (L173–174) and `_SOURCE_ORDER` tells the model without qualification that "blocks run oldest to newest", caveating **undated** blocks only (L596–603). A same-day pair therefore gets a positive ordering claim resting on a path tie-break, which carries no recency evidence. **P5 is a live inversion**: both versions carry `date: 2026-03-13`, and since `-` sorts before `.` the payload renders `…清单-v3.md` first, so it states that v1 is the newest. Its article carries v3's figures (L32, L141–144), so scored against the stated order P5 reads **5 of 5 stale, not 0 of 5**, and its compile set contains a second such pair (`…测试报告-v100.md` before `…测试报告.md`). The larger ruling-time finding is that P5 is a same-day pair in its frontmatter only, not in fact: v1's body reads 「生成时间：2026-03-13」 (L13) and v3's reads 「生成时间：2026-03-19」 (L12), six days apart. The fact is already recorded as this case's ordering family 2, but only as a confound that leaks the order to the writer; its consequence for the ordering rule was not drawn. What v3 carries is a frontmatter date that is wrong by its own body — the WP2 rolling-date class the spec files under A2 (101 of 996 corpus documents) — and the path tie-break then renders the pair backwards on top of it. Two defects, not one, and only the second is V20's. Measured on the reference KB (`~/.knowledge`, 691 articles, 397 multi-source, `sources` with comma-packed entries split): **156 articles (39%) carry at least two same-day sources, 384 pairs**. Re-measured at ruling time, and the basis had to be restated: the figure first recorded here, 159 articles and 411 pairs, counts byte-identical duplicates as two blocks, which is what merge.py's own comment ("160 of the 395") measures too — but WP7 collapses them into one, and a WP-family fix operates on the post-dedup list. Dropping only repeated paths reproduces 160 articles and 414 pairs, so the recorded figure was the pre-WP7 basis and drifts 3 pairs from today's snapshot; under WP7 the population is 156 and 384. Neither basis changes the argument, and both are given because the item is quoted as a population size. **Neither candidate tie-breaker reaches that population.** A filename version marker appears in 9 of the 384 pairs (2%), and only 2 pair two revisions of the same title; of those 2 the `…测试报告-v100.md` marker turns out to name the tested skill's version, 1.0.0, against a sibling that reports 3.1.0, so it carries no claim about which document is newer and the usable revision signal is **1 pair in 384**. A body-stated date appears in both members of 9 pairs, is unambiguous and differing in 5, and again only 1 of the 5 is a revision pair. So the tie-break is **uninformative rather than inverted** in ~99% of cases, and no stated signal covers them. Separately `_budget_priority` (L262–265) breaks same-day ties path-ascending while claiming newest-first, so for every same-day pair one document is at once the "oldest" for the ordering claim and the "newest" for the budget claim. **Scope, checked across all eight cases**: three have a chain head that is not last within its own day — P5 (shares `2026-03-13` with two, one rendered after it), P7 (`2026-05-14`, one after) and P10 (`2026-03-06`, two after) — but only in P5 is the document rendered after the head a member of the chain. P7's later-rendered same-day source `raw/meetings/2026-05-14-成本管控小组周会.md` carries **v2's** replacements (`97.28` and `11362`, one hit each) and none of v1's six superseded figures; P10's two carry none of v1's either, its only `7.3` hits being `+17.3pp` at L180 and L183. So no stale row outside P5 is affected, and P5's payload has four tie-broken groups (03-10, 03-11, 03-12, 03-13) rather than one — ten same-day pairs inside that one payload, from groups of 2, 3, 3 and 3. **Re-checked at ruling time against the caveat form specifically**, since withdrawing an ordering claim is a different intervention from correcting one: on P7 and P10 the blocks that go unordered are the chain head and co-sources that assert the replacements or nothing, so neither case loses a signal it was scored on. One gap in V4's wording closed on the way: P7's chain head is **not** the newest document in its compile set — `raw/meetings/2026-05-20-aws成本分析.md` is — but it is silent on every token this case turns on — v1's superseded figures and v2's replacements alike (`40.95`, `24.57`, `13.3`, `3000C`, `117.3`, `3300`, `83.1`, `7197`, `17054`, `97.28`, `11362`) plus `闭环`, 0 fixed-string hits each across its 919 lines, so V19's per-claim criterion still lands on v2 and V4's score stands | **Ruled: WP6's caveat extends to same-day blocks, and the tie-breakers are rejected.** Same-day blocks keep rendering in path order for reproducibility, exactly as undated blocks do under WP5, and the system prompt stops claiming a recency relation between them: what WP6 says of an undated block's position now also holds of two blocks sharing a `- Date:` line. The tie-breakers are rejected on the measurement above — a signal that fires on 1 pair in 384 cannot be the rule for the population, and a rule stated in the system prompt applies to every payload, not to the pairs where it happens to be informative. Reading the body's own date is rejected for a second reason: it is **A2's question, already deferred pending FX7**, and the data does not support pre-empting it — of the 10 same-day sources whose body date contradicts their frontmatter, 7 point *earlier* and 2 later (1 carries two body dates), so a body-date rule would move most documents in the direction of looking older, with no way to establish from the corpus which date is the document's own. `_budget_priority` (L262–265) needs no change of direction, which the item did not notice: it already breaks the tie path-ascending (`-date`, then `source_path`) and so does the render (`date`, then `source_path`), so both serve the same document first and the conflict was never in the two orders — it was in WP6 calling that document older while BG1 called it newer. Withdrawing the recency claim dissolves it. What BG1 owes is the matching qualification in its own prose: priority is **newest known day first, ties broken on path for stability**, with no claim that the block served first is the newer of a same-day pair. Two code notes for the implementation. `py/tests/test_core_merge_blocks.py:316` (`test_sources_dated_the_same_day_claim_the_budget_in_path_order`) **pins the behaviour this ruling changes** and is rewritten by the fix, not added to. And `_budget_priority`'s own docstring quotes "160 of the 395 multi-source articles" — the pre-WP7 basis, which becomes **156 of 397** (384 pairs) once identical checksums collapse | Applied: no total moved, and the item's own consequence is reversed. P5 does *not* become scoreable by this ruling — the caveat removes a false claim ("v1 is the newest") and puts *no claim* in its place, so the payload gives A1 no basis to prefer v3's figures and P5's 0 of 5 would be luck rather than evidence of supersession being handled. P5 therefore stays out of the gating count after the fix lands, for a different reason than before: not an unruled tie, but a frontmatter date wrong by six days against its own body. That is raised as **V21**. The fix is still worth taking on its own terms — it stops 384 pairs' worth of unfounded ordering claims, and P5 is the one case in the fixture where such a claim is actively inverted. One number does move, and it is not a total: making P5's exclusion permanent puts the stale rate's denominator in question, since 27 of 44 (61%) counts P5's five contradictions in a column P5 is not judged on. Held apart it reads 27 of 39 (69%), over five gating cases rather than six. **V21 ruled 2026-08-16 publishes 27 of 39**, on the ground that the 44-denominator reading embeds P5 at the 0 of 5 this ruling declared unsupported. **Implemented 2026-08-16 as WP9, and the population figure did not survive implementation**: this row's post-WP7 reading of **156 articles / 384 pairs is retired in favour of 160 / 412**. WP7's key is `_compute_checksum`, sha256 over the whole file (`storage/store.py:56`, applied at `:172`), so it collapses byte-identical duplicates only — on the reference KB that is **one** article and 2 pairs, taking 414 to 412 rather than to 384. The 156 / 384 pair reproduces exactly when the dedup runs on the *body* with frontmatter stripped, which collapses 84 within-article groups of which **83 hold documents whose frontmatter dates differ** — the distinction this whole population is about, so it is the wrong basis rather than a stricter one. Every leg of the argument holds on the corrected basis and one is unchanged: the filename version marker still appears on 9 pairs and still survives inspection on exactly 1, P5's own. Denominator note, since 397 is quoted here as a population size: 397 counts articles with two or more `sources` entries as listed, 391 counting only `raw/` entries and 385 counting only entries whose file resolves; the numerator 160 is over resolvable sources either way |
| **V21** | P5's frontmatter date | `data/kb-supersession-fixture/raw/docs/2026-03-13-…-v3.md`, and P5's row in test-set.md | **RULED 2026-08-16: the second option is taken — the fixture keeps v3 verbatim, P5 is recorded as an A2 body-date case, and the published stale rate becomes 27 of 39 (69%).** Raised by ruling V20. The premise verifies exactly: v3's frontmatter reads `date: 2026-03-13` (L4) while its body reads 「生成时间：2026-03-19」 (L12), against v1's 「生成时间：2026-03-13」 (L13) — six days apart, so the payload's date tie is an artifact of v3's metadata rather than a property of the corpus, and the true order 03-13 → 03-19 is not inverted by the dates the way P2's is. Only WP5's path tie-break inverts it. Five findings came with ruling it. **Fixture fidelity is measured rather than assumed, and it is what decides the first option**: both P5 files are byte-identical to their corpus copies under `data/kb-knowledge/raw/docs/`, so re-dating v3 would make P5 the one place in the fixture where a staged document departs from the document it was staged from — the property FX1–FX3 rest on. **P5 was already inside the A2 population, counted but not named**: of the 101 corpus documents whose newest body-stated date postdates their frontmatter date, 99 state it in a heading and **2 in a 生成时间 line**, and v3 is one of those two; the fixture's recorded 6 of 38 is 5 on headings alone, so the sixth was always P5. What was wrong is the descriptor rather than the count — "body heading date" has to read **body-stated date**, since the heading form alone measures 99 of 996 and not 101. **The count is a floor, and P5 is the third named fixture instance rather than the second**: N2's 04-17 file heads a section 「周例会 0428」 (L12) and its 05-06 file 「周例会 0512」 (L37), an `MMDD` form no date scan catches, which takes the fixture to at least 8 of 38 — test-set.md already names N2 as the second instance. One recorded figure does not reproduce: **36 stale by more than a week** measures 35 at more than seven days and 40 at seven or more, while 101 and 99 reproduce exactly (the original script is gone per FX1, so these are a reconstruction's numbers, stated with their thresholds). **The rate is conditional on a body date existing, and the corpus does not favour reading one**: only **505 of the 996** documents state a body date at all, so the conditional rate is 101 of 505 (20%) rather than 10.1% — and among those 505 the newest body date points **earlier** than the frontmatter date in **109** and later in 101, with 295 agreeing — so at corpus scale the two directions are near-even rather than lopsided, which is V20's finding (7 earlier of 10) reproduced at n=505 and weakened by it: earlier still leads, and no basis in the corpus says which of a document's two dates is its own. **A body-date rule would de-order two pairs to order one**: both members of N3 carry the heading 「Meeting transcript: realclaw安全评估 2026-04-10」 (L9) and both members of N4 「文字记录：…2026年4月9日」 (L9), because a transcript's heading date names the meeting rather than the document — so reading body dates collapses two pairs that frontmatter dates order correctly (03-10 → 03-11) into same-day ties, which under WP9 carry no ordering claim at all. Corpus-wide that shape dominates the population: **78 of the 101 sit under `raw/meetings`**, and 24 of them fall in 10 clusters sharing both a title and a body date | **Ruled: score P5 as an A2 body-date case, and publish 27 of 39 (69%).** The first option is rejected on the byte-identity above, the third because it loses the same Shape-B probe the second one loses while buying nothing in return. What the second option buys is exact and small: P5 is the one fixture pair a body-date rule would order, against the two it would de-order, so it gives A2's deferred question its first measured instance **and** its first measured counter-evidence. That is a reason to keep the question in A2 pending FX7 rather than to pre-empt it here, which is where V20 left it. FX3 records three wrong-date cases rather than two — P2 inverted by date, N2 dated before its own sections with its order intact, P5 tied by a date wrong by six days — and the descriptor corrections land wherever the population is quoted. **On the denominator**: the two readings share the numerator 27 only because P5 is scored 0 of 5, and that 0 is precisely the reading V20 ruled the payload cannot support. Scored against the order the payload states today P5 is 5 of 5, which makes the all-cases figure **32 of 44 (73%)**. So 27 of 44 is not the conservative reading of the pair; it is the low end of a 27–32 of 44 band (61–73%) whose position turns entirely on an unruled measurement of a case that is not judged on the column. **27 of 39 is the only figure that does not depend on P5**, and it sits inside that band, so publishing it is not taking the flattering end of it — but it is the larger number and therefore the one that argues harder for buying A1, so it is published with its composition attached rather than bare: 27 of 39 over five gating cases, with P5 and P8 named as excluded and why. 61% is retired as a headline and kept only as the set-total statement — 44 contradictions across seven cases, 39 of them judged on staleness | Applied: **no total moves** — 44/32/42 with 27 stale, and P5's 5C / 6D / 6K stay counted. Two things change. The published rate is **27 of 39 (69%)** across five gating cases (P3, P4, P7, P9, P10), and P5's exclusion now has a recorded disposition rather than a pending one: an A2 body-date case, reported apart from the gate for good. Its drop arm is unaffected — V9's 3 of 6 is measured against the labels, which take the true order from the two 生成时间 lines, and drops do not gate. The queue closes at **21 items, 14 settled and 7 open** at this ruling, none of the 7 moving a total — **V10 and V11 have since taken it to 16 settled and 5 open, and V13 to 17 and 4** |
| **V22** | P4-C9 | P4 → contradictions table | **RULED 2026-08-17: the row stands on one residue instead of three, and a whole-tail diff is what decides it.** Raised by ruling V15. The premise verifies and then hardens past what it claimed. L425 「a **TWAP market-selling mechanism** similar to the insurance pool」 traces to L5832 「采用类似保险池twap甩卖机制进行盘口甩卖」 and L426 「either held to expiry or transferred to a PM takeover account」 to L5833 「期权仓位如何处置： 1.等交割 2.通过移仓给到PM接管户」 — pairings v2's superseded cell does not carry, since it puts 现货 with 期权 and offers no 等交割. What the item asserted line by line holds for **the whole block**: diffing v2 from its 待决策和讨论项 marker to end of file (L5531–5598) against v4's (L5804–5867) leaves exactly two differences, both v2-exclusive deletions — 「仓位强增操作，经过撮合？…」 and 「现货兑币： TR还回来？」 — and v3's tail is byte-identical to v4's, so item 5's two bullets, the junk-coin question, the worked example and its `TR:` ledger line all stand unchanged in all three versions. Those lines are control-shaped: under V19's ruled criterion the newest source speaking to them is v4, and they discriminate nothing in either direction. Four findings came with ruling it. **v3 answers the TR question rather than falling silent on it**, which is what keeps the row a contradiction rather than a drop: the edit that first writes 「给到TRW处置」 (`TRW` 0/0/1/1) deletes both of v2's TR markers — the cell's own 「这里还需要和TR讨论下」 and 「现货兑币： TR还回来？」, 1 hit each in v2 and 0 in v1, v3 and v4 — and folds 现货 into the disposal item (v2's 期权和现货 → PM against v3's 现货和持仓 → TRW). An article calling the disposal pending TR discussion is not repeating something v4 merely stopped mentioning; it is repeating what v3 recorded as settled. **The article's action-item section exhibits the append**: it is partitioned by source — one unlabelled table, then 「Additional action items from 2026-05-26 TRD」 (L654) and 「…from 2026-06-04 TRD」 (L679) — and the later block picks up the line v3 *added* to §5 (「财务资金处置」, v3 L5671 / v4 L5672, reaching article L688 with the same owner `ou_436ac3…`) while missing the line v3 *changed* in it. Additions carried, replacement missed, inside one table of one article. **That also bounds the dated-label defence** L667 might otherwise have: the labels name which document a block was read from, not when its content entered — 「财务资金处置」 is v3's and is filed under 06-04 — so 「from 2026-05-26 TRD」 makes no claim that anything in that table was later replaced, and the section it sits in is titled 「Open Action Items」. **The pair is v2 → v3, not v2 → v4**, the same line-level correction V5 made for C8, since `TRW` first appears at v3 L5705 and v4 only shifts it one line. **And P4's one co-source is silent on this row**: `处置`, `甩卖`, `保险池`, `TRW`, `系统户`, `差额` and `TR讨论` are 0 hits in `raw/docs/2026-04-20-a23-异常交易回滚-仓位字段回滚分析.md`, whose single 接管户 hit is the hedging-engine 接管价格 field (article L266's `hedging_take_over_price_x`) — so unlike P7's seven rows and P10's C4 / C7, C9 carries no co-source confound and its causal claim needs no narrowing | **Ruled: C9 stands, scored on L667 alone, with C5's kind of caveat attached.** L425–426 leave the `Article today` cell and are recorded instead as this case's presentation defect, P10-C2's shape: the article states v4's 待决策 options as settled characteristics under 「Key characteristics」, and it demonstrably knows the other form, since the junk-coin question from the same source block is filed as an open item at L685. So the article keeps the hedge v3 deleted and drops the hedge v4 still carries — wrong in both directions, and only the first is staleness. Two tests are pinned, the P7-C2 hazard: C9's is 「这里还需要和TR讨论下」 against the article's 「discuss with TR」, and **not** `PM接管户`, `等交割`, `twap`, `保险池`, `盘口`, `甩卖` or `移仓`, every one of which survives into v4 — a *count* discriminates where a presence test does not (`盘口`, `PM接管户` and `移仓` are 2 in v2 against 1 in v3 and v4). R9's test is `TRW`, and it is the cleanest string in the case: 0/0/1/1 across the chain, 0 in the co-source, 0 in the article. The source-side ambiguity stays where it was documented, [call 3](#p4-open-judgement-calls), rewritten around the diff | Applied: **no total moves** — 44/32/42 with 27 of 39 stale (69%), and P4 stays 10C / 4D / 6K at **9 of 10**. The row keeps its verdict and loses two of its three residues, its transition is corrected to v2 → v3, the v2→v3 summary gains the third deleted marker, and the hedge-dropping is recorded as a finding rather than raised as a new item. The queue closes at **22 items, 20 settled and 2 open** — V17 and V18, **neither of which can move a number**, so every item that could is now ruled. **V17 has since been ruled and moved none**, taking the queue to 21 settled and 1 open: P10-C5 stands as a level-only contradiction, and v2's efficiency cycle series turns out to be the 03-05 co-source's unfiltered column. **V18 has since closed the queue, also moving none** |

**Done means**: every V-item above reads `ruled` — or, for V16, `resolved` — with the
decision written into the row it governs, and the Progress table is recomputed from
the survivors. **V1–V15 and V19–V22 are ruled and applied**, so the
Progress table now reads **44 contradictions, 32 drops and 42 controls, with 27 of 39
stale (69%)** — carried by seven cases still, but only **five of them gating**, since P8
contributes no contradictions and P5 is not judged on the column. The drop total is 32 rather than 31 because V8 promoted
P5's `universal-transfer` abridgement to D6, the one row of that case's seventeen where
the dropped clause is neither entailed by what survives in its cell nor restated by v3
elsewhere. V9 leaves it at 32 and puts a figure on what that arm has lost: **3 of P5's 6
drops are stated as current** (D4, D5, D6), with D1's residue excluded because a
never-superseded declared source asserts the same material. V20 leaves those totals where they are and adds one
qualification to the headline: P5's five contradictions are counted in the 44 but P5 is
not judged on the staleness column. **V21 publishes the figure that follows from it** —
**27 of 39 (69%)** across five cases — and disposes of P5 as an A2 body-date case, the
fixture keeping v3's wrong frontmatter date because the staged file is byte-identical to
the corpus copy it came from. **V10 leaves every number alone** — P2 has scored nothing
since 2026-08-15 — and settles the last question about the case that was still open:
its two files agree verbatim in the section they both date 04-17 on seven of the eight
drafted rows, so C8 is the only place they disagree, and C8 leaves no residue in the
article. P2's withdrawal is therefore permanent rather than reversible by option (b).
**V11 leaves every number alone as well** and settles what P10's stale column is measured
on: not the figures, which its `2026-03-05` co-source prints verbatim, but the article
stating them with no basis attached — so P10 joins P7 as a case whose causal claim
narrows to its C8. **V13 leaves them alone too** and closes P10's basis reasoning: the
half-year pair is C7's shape one level up, there is no third population published to
re-base it onto, and the article's 「−4 to −6%」 band is recorded on C2 as a blend of the
two bases rather than as an assertion of v1's figure. **V14 leaves them alone too** and
closes P10's team family: the roster change is additive, so the family rests on 16 rates
restated downward, and the article carries v2's rates for two of the eight shared teams
against v1's for three — which caps the family at one further scoreable row, names
Compliance rather than Fiat Channel as that row, and finds the case's one co-source that
asserts a replacement instead of a superseded value. **V15 leaves them alone as well** and
settles what P4's unscored entry is: one entity in three states, a drop then a
supersession, kept under that name because the fixture cannot carry a nested supersession
at all — P4 is its only chain longer than a pair. Ruling it raised **V22**, which is where
the next number could have moved, and **V22 leaves them alone too**: P4-C9 keeps its stale
verdict on one residue rather than three, since the 待决策 passage the article's other two
lines come from stands byte-identical in v2, v3 and v4, while v3 deleted the
「(discuss with TR)」 hedge in the edit that assigned disposal to TRW. **So no open item
moves a total, and none is left that could.**
That is a smaller and more defensible set than the 50/30/42 it started from, and its headline no longer leans on P8's rename reading.
P7's confounded column stays in it: V19 established that the confound cannot be
dissolved by redefining the column, because P7's co-source is older than its chain
head, and V4 then established that it does not need to be — the rows score, and only
the causal claim narrows.

#### V16 — resolved by investigation, no ruling needed

The item asked whether the compile read `raw/docs/2026-03-12-bybit-trading-skill-security-hardening-plan.md`
without declaring it, or whether the article's `sources:` list is simply incomplete.
**Neither, as far as the article's content can show**: every rationale it carries is
also asserted by v1, which is declared and is the chain under test, and two of them
are v1-exclusive across the whole corpus.

No artifact settles the routing question directly, so it cannot be answered that way.
`.compile-state.json` records a checksum and a timestamp per source and no target
article, and no `.classify-cache/` survives in `data/kb-knowledge`, so which article
each document was classified into is unrecoverable. Nor is the frontmatter itself
authoritative: on the rewrite path the *model* writes the `sources:` entry
(`py/src/kb_ai/core/merge.py:703-714`), which is why 91 entries corpus-wide are
comma-packed — including this document's own entry in the article that does declare it
(`wiki/decision/ai-trading-agent-architecture-decisions.md` L16 packs three paths into
one item, and repeats a path already listed at L6).

So it was resolved on content, in both directions.

- **Nothing plan-exclusive reaches the article.** Of the plan's 982 lines, 68 survive
  as text no other raw document contains. None of the 68 appears in the article. The
  sharpest is 「打乱策略性挂单」 (plan L588), the plan's cancel-all framing and a
  corpus-exclusive string: the article instead carries v1's DCP note (article L423) and
  v1's own 「注意不要误取消策略性挂单」 wording is what the abridged v3 row reduces. Also
  absent are the plan's supply-chain threat items (L908 repo/CDN injection, L942 CDN
  poisoning) and its entire P0/P1/P2 execution checklist (L954–L980).
- **Two residues are v1-exclusive, so they can only be v1's.** 「影响他人账户」 occurs
  once in the corpus, v1 L4007 — absent from v3, from the plan (its L502 drops the
  clause) and from the retained-interface list — and it is what article L402 carries as
  "affects other accounts". That is **D5's** dropped clause. And v1 L2975's parenthetical
  「组合攻击链入口（创建子账户→转资金→子账户提现）」 is likewise a single corpus hit,
  reproduced at article L399; v3 L2918 keeps the label without the expansion, and the
  plan phrases it the other way round (L382 「创建子账户 → 转资金 → 子账户提现（组合攻击链）」).
- **Where both assert a rationale, the article follows v1's wording.** Article L427
  "sends funds to any UID" matches v1 L4744 「向任意 UID 打款，本质是另一种提现通道」 without
  the plan's 商户 (plan L96) — that is **D4**. Article L394 matches v1 L2730 without the
  plan's 「主账户↔任意子账户」 gloss (plan L116).
- **The neighbouring material is declared too.** The article's risk tiering (L143, L388:
  12 P0 high-risk, 10 P1 medium-high) is v1 L5486/L5494, and its jsDelivr and SHA256
  content comes from three declared sources — `2026-03-10-bybit-ai-trading-agent-设计方案.md`
  and both testnet reports — not from the plan.

Consequence: **D4 and D5 can be scored as lost drops** — as first written this read
"D2–D5", which **ruling V9 corrected**: D2's and D3's clauses never reach the article,
so there is nothing of theirs to lose, and what this investigation settles is whose the
residues are rather than how many there are. P5's 16 declared sources stand, and
the [co-source table](#note-co-source-assertion-confounds-the-staleness-column) is
unaffected. The general risk the item raised is real but is not this case's: an
unreliable `sources:` list is what FX4's added check exists for, and where it does bite
is co-source analysis on the *existing* articles, which must split comma-packed entries
first.

---

## P3 — cht-knowledge distillation and indexing

- `v1` = `data/kb-supersession-fixture/raw/docs/2026-04-20-cht-knowledge-跨系统知识蒸馏与索引方案.md`
- `v2` = `data/kb-supersession-fixture/raw/docs/2026-04-30-cht-knowledge-跨系统知识蒸馏与索引方案.md`
- `article` = `data/kb-knowledge/wiki/concept/cht-knowledge-plugin-system.md`

The revision is an architecture change, not a polish pass: project-level cache
becomes user-level, a resident index becomes trigger-based injection, the
distillation command changes owner and shape. Six of the eight contradictions are
still stated as current in the article today, which makes P3 the strongest pre-A1
failure in the set after P1. Unlike P1, its items are contradictions, so they
gate.

### Contradictions and their replacements

| ID | What v1 asserts | Evidence | Article today | Status |
|---|---|---|---|---|
| P3-C1 / R1 | Knowledge caches live in the project, in a gitignored `.claude/knowledge/` → they live at a user-level path shared across projects | v1 L265 「.claude/knowledge/ ← 整个目录 gitignored」 → v2 L152 「**本地克隆路径**：`~/.claude/plugins/cht-knowledge/knowledge/<domain>/`」, L64 | not stale — article states the v2 path (L66) | to confirm |
| P3-C2 / R2 | Three-level loading with `index.json` permanently resident, ~50 tokens per system and ~1500 for 30 → two-stage loading with nothing resident, ~200 tokens for the summary | v1 L746 「Level 0（常驻）：index.json ~50 tokens/系统」, total at L325 → v2 L951 「两阶段加载在大多数情况下仅消耗 ~200 tokens（Stage 1 摘要）」, L212 | **stale** — L30 heading, L36 table row, L40 「1,500 tokens」 | to confirm |
| P3-C3 / R3 | The SessionStart hook generates `index.json` and injects it every session → injection moves to a `UserPromptSubmit` hook on trigger words, and SessionStart only pulls silently | v1 L294 「index.json 从 registry.mjs 自动生成，在每次会话启动时通过 hook 注入 AI 提示词。」 → v2 L214 「**时机**：UserPromptSubmit Hook 检测到触发词时自动注入」, L115 | **stale** — L63 asserts the resident global index; L67 also describes v2's pull, so the article carries both mechanisms side by side | to confirm |
| P3-C4 / R4 | Cached knowledge has a 24-hour validity window and is not re-fetched inside it → freshness comes from a `git pull --rebase` on every session start, failing silently offline | v1 L289 「缓存有效期：24 小时内不重复拉取」 → v2 L251 「对每个知识库执行后台 `git pull --rebase`」, L253 | **stale** — L68 states the 24-hour window as current | to confirm |
| P3-C5 / R5 | There is no `init` command; installing the plugin completes setup → each knowledge base is installed explicitly with `/cht-knowledge:init <system-id>`, which git-clones it | v1 L399 「**注意：没有 init 命令。** 安装插件即完成所有设置」 → v2 L112, L481/484 | **stale** — L71 「**No init command:**」 | to confirm |
| P3-C6 / R6 | Distillation is a `cht-tools` command, `/cht-tools:distill` → it is `/cht-knowledge:distill --source <path>`, run inside the knowledge-base repo | v1 L448 「## 四、蒸馏工具设计（/cht-tools:distill）」 → v2 L513, L516 | **stale** — L75, and L21/L181/L232/L262; `/cht-knowledge:distill` appears nowhere | to confirm |
| P3-C7 / R7 | Distillation scans 6 dimensions with 6 parallel sub-agents → an 8-agent pipeline, 5 parallel then 3 serial | v1 L464 「蒸馏工具自动扫描 6 个维度，使用并行子 Agent 提高效率：」, agents at L468–473 → v2 L109, L393, L400 | not stale — article states 5 parallel + 3 serial (L75) | to confirm |
| P3-C8 / R8 | A knowledge base is `manifest.json` plus five named files (`system-overview.md`, `proto-guide.md`, `integration-guide.md`, `data-model.md`, `error-reference.md`) → `manifest.json` plus eight numbered files `00-overview.md` … `07-usage-guide.md` | v1 L609–615 → v2 L159–167 | **stale** — article's tree is v1's names plus two extras (L108–117) | to confirm |

### Drops (measured, not gating)

| ID | What v1 asserts and v2 drops | Evidence | Status |
|---|---|---|---|
| P3-D1 | The platform has 100+ repositories | v1 L14 「在中台大团队（100+ 仓库、多个子团队）中」; `100+` and 「子团队」 both 0 hits in v2. **Narrowed on verification** — the original row also claimed "and multiple sub-teams", which v2 restates at L20 「中台有 30+ 微服务，跨团队协作时…」, so that half was not a drop | to confirm — see note 1, this may belong in C |
| P3-D2 | Distillation extracts a minimum knowledge set rather than copying code: 50 Proto methods reduce to 5–10 selected external core interfaces | v1 L561 「**蒸馏不是照搬代码，而是提取 AI 对接时需要的最小知识。**」, L575/578 | to confirm |
| P3-D3 | The transfer system's `Transfer` interface is idempotent on `request_id` with a 3000 ms timeout, `RATE_LIMITED`/`TIMEOUT` retryable and `INSUFFICIENT_BALANCE`/`ACCOUNT_FROZEN` fatal — and, widened by V7, `QueryTransfer` with it (`idempotent: false`, `timeout_ms: 2000`) | v1 L635–638, inside the `interfaces[]` array at L630–646; QueryTransfer at L640–645. Absent from v2 across the whole contract vocabulary — `idempotent`, `idempotent_key`, `timeout_ms`, `retryable_errors`, `fatal_errors`, `RATE_LIMITED`, `TIMEOUT`, `INSUFFICIENT_BALANCE`, `ACCOUNT_FROZEN`, `幂等`, `超时`, `QueryTransfer` all return 0 hits | to confirm — **V7 ruled 2026-08-16** — stays a drop, and a **lost** one: the article states the Transfer contract at L119–123 under 「Example `manifest.json` for the transfer system」. QueryTransfer's half has no article residue. Call 2's promotion to C9 declined |
| P3-D4 | The plugin offers `/cht-knowledge:search`, a keyword search over already-cached knowledge | v1 L355/361; v2's command reference (L461–543) has no analogue — `:match` debugs trigger words, it does not search content | to confirm |
| P3-D5 | The first systems to distill are transfer, deposit, withdraw, risk and account | v1 L1113/1116 (L1114 as first drafted is `</lark-td>`) | to confirm |

### Controls (present in both; missing from the article means over-deletion)

| ID | Asserted by both versions | Evidence | Status |
|---|---|---|---|
| P3-K1 | Each system's knowledge lives in its own independent Git repository | v1 L1140 → v2 L151 | to confirm |
| P3-K2 | `cht-context` is a Git submodule bound to a project, unlike `cht-knowledge` which is git-cloned | v1 L160 → v2 L72 | to confirm |
| P3-K3 | Distillation is AI-driven: an agent scans source and generates structured documents | v1 L964 → v2 L97/L109 (L28 as first drafted asserts source→structured docs but not AI authorship) | to confirm |
| P3-K4 | A knowledge base becomes platform-wide by registering in `registry.mjs` and merging an MR | v1 L994/997 → v2 L756 | to confirm |
| P3-K5 | Distilled output must be human-reviewed before publication | v1 L972 → v2 L785 | to confirm |
| P3-K6 | On-demand deep loading of full documents costs ~2000–4000 tokens | v1 L796 → v2 L237 | to confirm |

### P3 open judgement calls

Each needs a yes/no from Captain; the default if ignored is the drafted position.

1. **P3-D1, drop or contradiction?** v2 replaces the framing with 「中台有 30+ 微服务」 (v2 L20). Drafted as a drop, because repo count and microservice count are different measures that can both hold. The article merges them into one sentence (L16). Ruling it a replacement promotes it to C9.
2. **`manifest.json` schema — promotion declined, V7 ruled 2026-08-16.** v1's manifest carries per-interface contracts (`interfaces[]` with `idempotent_key`, `timeout_ms`, `retryable_errors`, `fatal_errors`, v1 L630–646); v2's carries `version`/`createdAt`/`updatedAt`/`triggers`/`documents` and no interface data (v2 L172–192). Same subject, field sets nearly disjoint, and it was drafted as the strongest candidate for promotion. It stays out because its only asserted clash is `version` (v1 L626 `"2024-04-20"` → v2 L176 `"0.1.0"`) and the article is current on that one at L125, so C9 would gate on `interfaces[]` being *absent* from v2 — the inference calls 4 and 6 decline — while striking D3 over the same four article lines. What stands recorded is that the article carries both schemas six lines apart (L119–123, L125): one defect, counted once.
3. **Knowledge-repo naming — left out as low consequence.** v1 `cht/ai-coding/knowledge-{system}` (L890, L986) against v2 `<系统ID>-knowledge` under `cht/ai-coding/knowledge/` (L583, L586). A real contradiction; the article uses v1's form throughout (L105, L190, L262).
4. **Do exhaustive command tables contradict removed commands?** v2's 命令参考 (L461–543) reads as a complete set and omits `search`, `clean` and `update` (v1 L379/384, L388/394). Drafted as absences, and only `search` is listed, as the one with no v2 analogue. Ruling that an exhaustive table contradicts moves all three up to C.
5. **Roadmap table — left out.** v1's 实施路径 (L1088–1107) is fully replaced by v2's Roadmap (L806–826). Held out because v1's phases are plan items, not assertions about current state, and the article already uses v2's table (L252–257), so it would score as non-stale either way.
6. **The 80K-token figure — left out, but the article is internally inconsistent here.** v1 asserts full preload costs 80K+ tokens (L843); v2 asserts full injection is ~22,000 tokens *per system* (L951). Over 30+ systems those are arithmetically incompatible, but the incompatibility is inferred rather than asserted, so it was not labelled. The article states both (L40 「80K+ tokens」, L212 table 「660K+」). Note the trap: the article also reuses 80,000 as v2's distillation *input* size (L96), a separate and correct claim that shares the number.
7. **C2 and C3 are two facets of one architectural shift** (resident index → trigger-based injection), so one article fix would likely satisfy both and that single defect carries double weight. Kept separate because each is independently checkable in prose. Merging them is defensible if the score should weight defects rather than sentences.

Extraction cross-check: every v1 claim the pipeline itself considered salient is
accounted for, and so is every v2 counterpart. One artifact to keep out of the
label: the v2 extraction records 「Each session costs approximately 1-2 USD」 and
「10-15 minutes」 per *session*, where v2 states them per distillation run
(v2 L887–897).

---

## P2 — Infra biweekly review (WITHDRAWN, counter-case)

- `v1` = `.../raw/docs/2026-04-14-infra-双周会-2026_h1.md` (fixture calls this earlier)
- `v2` = `.../raw/docs/2026-04-17-infra-双周会-2026_h1.md` (fixture calls this later)
- `article` = `data/kb-knowledge/wiki/decision/infra-ai-devops-roadmap-decisions.md`

**Ruled 2026-08-15: P2 is withdrawn from the positives and kept as the documented
wrong-date counter-case** — option (c) of the direction call below. It scores
nothing under FX5 and gates nothing under FX7. Its drafted label is retained
verbatim, in the fixture's stated direction, because P2 is the corpus's only
instance of an inverted chain and deleting the label deletes the evidence. What it
is evidence *for* is a limitation of A1's design, not a defect in A1's
implementation: WP2 takes ordering from raw frontmatter `date`, and on this
document that date is wrong rather than missing.

The chain runs backwards relative to its content, verified three independent ways:

| Evidence | v1 (dated 04-14) | v2 (dated 04-17) |
|---|---|---|
| Dated section headings in body | `# 2026-05-04` (L81) **and** `# 2026-04-17` (L1025) | `# 2026-04-17` (L81) only |
| Extraction `extracted_at` | `2026-05-04T04:32:44+00:00` | `2026-04-17T13:24:00+00:00` |
| The section both files date 04-17 | verbatim identical to v2 apart from **storage governance 56%** (L1781) and two dashboard images | **storage governance 20%** (L824) |

So the file the fixture calls *earlier* is a rolling document that accumulates
meeting sections and carries reporting three weeks *newer* than the file it is
supposed to precede. Its frontmatter `date` is its creation day, not its content
day. Every `replacement` drafted below is therefore the **older** figure.

**Ruling V10 sharpened row 3, 2026-08-16**, and it changes what the pair's rows mean.
The newer reporting is in v1's 05-04 section, not in the section both files date 04-17:
there the two documents agree *word for word* on every one of C1–C7, each v2 line the
tables cite being present verbatim in v1's 04-17 section (v2 L953 → v1 L1910, L969 →
L1926, L448 → L1405, L451 → L1408, L578 → L1535, L585 → L1542, L405 → L1358). Every
`v1` cite below, by contrast, points into the **05-04** section, which runs from L81
where the 04-17 one begins at L1025. So C1–C7 set v1's 05-04 reporting against v2's
04-17 reporting — the inversion itself — rather than two documents disagreeing about
one date. **C8 is the single exception**: v1 L1776–1786 and v2 L819–829 are
byte-identical apart from three lines, two dashboard image tokens and the 进度总览
figure, 56% against 20%. The rolling file amended its own 04-17 section in exactly one
place, which is stronger evidence that it is the later document than differing figures
would have been.

P2 is worth more as evidence of this failure mode than as a scoring case. WP2
reads the ordering signal from raw frontmatter `date`, so on this document A1
would hand the writer `- Date: 2026-04-14` for content dated 2026-05-04 and
assert an order that is confidently wrong. Q2 and D3 provisioned for a *missing*
date, not a *wrong* one.
Scope of the risk, measured over the corpus rather than assumed:

| Measurement | Result |
|---|---|
| Fixture chains whose body-content order inverts their frontmatter order | **1 of 12** (P2 only) |
| Fixture docs whose newest body-stated date postdates their frontmatter date | 6 of 38 — 5 in a heading, plus P5's v3 in a 生成时间 line; **8 of 38** counting N2's pair, whose later sections are titled `周例会 0428` and `0512` |
| Corpus docs with the same symptom | **101 of 996** (10.1%) — 99 in a heading, 2 in a 生成时间 line; 35 stale by more than a week (40 at a week or more) |
| Corpus docs stating a body date at all — a `YYYY-MM-DD`-style date in a heading or on a 生成时间/更新时间 line | **505 of 996**, so the conditional rate is 101 of 505 (20%) — and the newest body date points **earlier** than the frontmatter date in 109 of them, later in 101, equal in 295 |
| Corpus docs sharing the placeholder `date: 2026-01-01` | 21 |
| N3 / N4 | absolute dates stale by ~30 days, **relative order preserved** — still valid controls |

The symptom is common; the fatal form (inverted order) is rare. Meeting
transcripts are the main source — `2026-03-10-realclaw安全评估.md` is dated
2026-03-10 while its body heading reads 「Meeting transcript: realclaw安全评估
2026-04-10」 — and 78 of the 101 sit under `raw/meetings`.
Three qualifications, measured while ruling **V21** and recorded because this table is
quoted as a population size. The descriptor is **body-stated date**, not body *heading*
date: the heading form alone measures 99, and the two documents that take it to 101 state
their date in a 生成时间 line, one of them being P5's v3. Both figures are **floors**,
because a body date written as `MMDD` inside a section title is invisible to any date
scan — which is exactly N2's shape. And the direction matters as much as the rate: over the
505 documents that state a body date, the disagreements split 109 *earlier* against 101
later, so reading the body's date moves about as many documents towards looking older as
newer. That is V20's finding at n=505 rather than n=10, and weaker than its sample
suggested — 7 earlier against 2 later there reads as lopsided, this reads as near-even —
but it points the same way, and neither basis tells you which date is the document's own.
Which is why the fix for this class stays A2's question rather than being pre-empted.

### Contradictions and their replacements — drafted in the fixture's stated direction, i.e. reversed relative to content

| ID | What v1 (04-14 file) asserts | Evidence | Article today | Status |
|---|---|---|---|---|
| P2-C1 / R1 | Q2 cloud-cost optimization at 40.95%, 24.57W banked → 0.28%, 0.17W | v1 L898 → v2 L953 | **stale** — L615, L761 state 40.95% / 24.57W as current | to confirm |
| P2-C2 / R2 | Low-load governance over-delivered at 117.3%, 17.6W against a 10W–15W target → 0% | v1 L919 → v2 L969 | **stale** — L618, L762 | to confirm |
| P2-C3 / R3 | AI-gateway scenario convergence 90% (36/40) plus 34 extra → 87.5% (35/40) plus 32 extra | v1 L435 → v2 L448 | **stale** — L578, L759 | to confirm |
| P2-C4 / R4 | Self-developed AI gateway kicked off 4.20 at 100%, design review due 5.8 → still an evaluation due 4.20 | v1 L438–439 → v2 L451 | **stale** — L578 | to confirm |
| P2-C5 / R5 | Bgwst gray release at 50% trading QPS, 40K/s daily, 230K peak, full 5.12 → 45%, 35K/s, 61K peak, full end of April | v1 L557 → v2 L578 | **stale** — L592 | to confirm |
| P2-C6 / R6 | Bgws C++ committed to testnet 5.27 and mainnet 6.16 → no schedule, estimate due 4.24 | v1 L562–564 → v2 L585 | **stale** — L593 | to confirm |
| P2-C7 / R7 | vLLM instance monitoring 100% complete → 90% | v1 L399 (**05-04 section**) → v2 L405; v1's own 04-17 section reads 90% at L1358, verbatim with v2 | **not a clean observation** — the article states both, 90% at L445 against 100% at L580 and L760 | **V10 ruled 2026-08-16** — ambiguous rather than unambiguous. All three lines carry the same counts 「sitnet 8/10，testnet 1/1， mainnet 11/12」 and only the grade differs, so the 100% re-grades an unchanged measurement; v1's own parent line L398 still reads 【80%进行中】 above it |
| P2-C8 / R8 | Storage non-standard governance overall 56% → 20% | v1 L1781 (04-17 section, 「[56%] 进度总览」) and L783 (05-04 section, 「P-1治理率 56%」) → v2 L824 | not stale, and the replacement is absent too — no storage-governance figure in the article | **V10 ruled 2026-08-16** — the pair's only cross-document disagreement. Two string hazards recorded with it: v1's 56% is split across three `<text color="green">` spans (`**[**`, `**56**`, `**%]**`), so `grep -F "56%"` finds only L783 and misses the cited L1781; and the article's four `56` hits (L82, L342, L643, L707) are all alert-RCA coverage, not this metric |

### Drops (measured, not gating)

| ID | Asserted by the 04-14 file, absent from the 04-17 file | Evidence | Status |
|---|---|---|---|
| P2-D1 | ABF security-compliance conversion 100% complete by 4.30 across testnet/prod — 6 accounts, 585 hosts, 922 disks | v1 L315 | to confirm |
| P2-D2 | The Fiat model-call anomaly was fixed, cutting spend from a 1750/day peak to under 50/day, catching about 4w per month | v1 L940 | to confirm |
| P2-D3 | Private-model stability progress was slow because staff were absorbed by ABF disk encryption, finishing 4.30 | v1 L395 | to confirm |
| P2-D4 | Agreed plan for third-party gateway metadata: align with the efficiency platform by Q2, add vendor and purpose fields to the Blueking egress ticket, Blueking loads it into the efficiency database | v1 L225–227 | to confirm |
| P2-D5 | Three pending improvements for the AI deployment platform: one-click deploy for Claude Code and OpenClaw, externally reachable generated domains pending security review, database creation | v1 L1397–1400 | to confirm |
| P2-D6 | EBS storage-encryption data migration is complete | v1 L1271 | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P2-K1 | Third-party gateway totals: 338 channels (+21), 197 not onboarded (−17), 141 onboarded (+38) | v1 L720 → v2 L750 | to confirm |
| P2-K2 | Third-party gateway scope: 6 departments, 206 applications, 57 scheduled for April, rest evaluated in batches before 4.20 | v1 L709 → v2 L739 | to confirm |
| P2-K3 | Unified-framework backlog: 198 Java and 179 Go applications remaining | v1 L1789, L1791 → v2 L832, L834 | to confirm |
| P2-K4 | AI adoption: 67.35% AI developers (33/49), 40.13% AI-generated code | v1 L991–992 → v2 L1037–1038 | to confirm |
| P2-K5 | Cost baseline: Q1 stock baseline 3330W excluding 90W of compliance sites, Q1 3330W → Q2 3090W/3030W | v1 L890 → v2 L945 | to confirm |
| P2-K6 | Image zero-trust is live, all base images converging onto the efficiency platform by 4.30 | v1 L626 → v2 L647 | to confirm |

### P2 open judgement calls

1. **Direction — RULED (c), 2026-08-15.** The three options were (a) accept the
   fixture's direction, in which case A1 is being asked to prefer an older figure
   and P2 measures the wrong thing; (b) invert the label, swapping contradiction
   and replacement and turning the six drops into v2-only additions; or (c)
   withdraw P2 from the positives and keep it as a **documented counter-case** for
   the wrong-date failure mode, which is what its evidentiary value actually is.
   (c) was taken. Under it the rows above keep the fixture's direction — so read
   every `replacement` as the older figure and do not score any of it — and (b)'s
   inversion is the reading to apply if the case is ever revived: swap each C with
   its R, and reclassify D1–D6 as v2-only additions rather than drops. The reason
   (a) was rejected is that it would have A1 graded as correct for asserting an
   order that is wrong, which corrupts FX7 in the direction that flatters the
   work.
2. **C8 alone is a disagreement between the two documents — RULED (V10), 2026-08-16.**
   The draft had it that C7 and C8 both sit inside the section both files date
   2026-04-17, so v1 asserts exactly one value for each. That holds for C8 and fails
   for C7: v1's 04-17 section reads 90% at L1358, verbatim with v2 L405, and the 100%
   is exclusive to its 05-04 section (L399). The same check clears C1–C6 the same way,
   every v2 line they cite being verbatim in v1's 04-17 section, so the line this call
   drew is not between ambiguous and unambiguous rows but between the one row where the
   rolling file **amended** its own 04-17 section (C8) and the seven where it **copied**
   it. The consequence the draft reached for C1–C6 therefore covers C7 as well: an
   article stating v2's figure proves nothing about ordering, because v1 states it too.
3. **The article asserts the inversion in prose**, which is worth reading before
   ruling: L574 「It provides updated metrics and decisions that supersede or
   complement the April 17 data」 and L615 「a significant improvement from the
   0.17W (0.28%) reported at the April 17 meeting」. The pipeline already inferred
   the true direction from content.
4. **Left out — the EC2 Savings Plan reversal**, the largest decision difference
   in the pair. The 04-14 file strikes 「目标覆盖率90%…」 (L907) and substitutes
   「预期不新增购买sp,需优化1w核」 with a 3000C gap, while the 04-17 file states the
   90% target unstruck (L962). It hinges on reading `~~…~~` as cancellation, and
   the pipeline's own extraction did not read it that way. Add it if the
   strikethrough reading is accepted.
5. **Also left out**: ABF percentages where the 04-14 file asserts both values in
   one file (unscoreable); two monitoring rows too deep in a table to reach article
   prose; a decision softening neither version's article states; and eight smaller
   numeric pairs, capped rather than padded.
6. **Revival is not available on the numbers — recorded while ruling V10.** Option (b)
   of call 1 leaves exactly one scoreable contradiction, C8, and C8 has **no article
   residue at all**: the article carries neither 56% nor 20%, so it yields no staleness
   observation. The two rows whose residues were checked go the other way — the article
   asserts *both* figures, vLLM 90% at L445 against 100% at L580 and L760, and gateway
   convergence 87.5% at L733 against 90% at L759 — which is the shape ruling **V1**
   struck P8's four rows on. So P2 cannot be revived as a *scoring* case in either
   direction, and (c) is not a triage decision but the only reading its content
   supports. The inverted label stays on record because what it is evidence for is a
   limitation of A1's design, which is what it was kept for.

---

## P4 — trade-rollback TRD, four versions

- `v1`…`v4` = `.../raw/docs/{2026-05-19,2026-05-26,2026-06-02,2026-06-04}-交易回滚trd.md`
- `article` = `data/kb-knowledge/wiki/concept/derivatives-position-field-schema.md`

**The strongest failure case in the set: 9 of 10 contradictions are still stated
as current.** The chain is a design document converging over three weeks, and
what changed is mostly storage architecture.

| Transition | What actually changed |
|---|---|
| v1→v2 | Storage flips from MySQL monthly sharding to single TiDB tables (nine tables lose `_{yyyyMM}`, gain DDL); three new fields are struck from the monthly translog and re-scoped to the real-time table; the engine `RollbackUserRequest` is rewritten (ban/unban RPCs deleted, `user_snap` / `cash_balance_info_list` / `repayment_info_list` added); §5 becomes an 11-row module table |
| v2→v3 | `set_time` redefined from nanoseconds to milliseconds across seven log tables; `action` renamed `service_action`; counterparty renamed 交易系统户 → 交易系统内的差额账户 with disposal reassigned to TRW; fund-recovery callback API added; the 兑币流水回滚 task, two standalone open questions and — measured by V22 — the disposal cell's own 「这里还需要和TR讨论下」 hedge deleted |
| v3→v4 | Three progress cells only: 封禁 gains 联调结束, 资产追回 60% → 开发90%，下周可以联调, MarginDB 开发中 → 联调中 |

### Contradictions and their replacements (judged v1→v4)

| ID | Earlier assertion → v4's | Evidence | Article today | Status |
|---|---|---|---|---|
| P4-C1 / R1 | Monthly translog gains `change_flow_usd`, `uta_result_topic_name`, `uta_result_offset` → monthly tables get no new fields this round, they go to the real-time table | v1 L1144, L1363, L1368 → v2 L1519 / v4 L1742 | **stale** — L454–456 list all three as current additions, plus open action L636; the correction exists but is misfiled under `uta_liq_trans_log` (L473–478), so the article asserts both | to confirm |
| P4-C2 / R2 | Coin-exchange table is monthly `uta_exchange_record_202604` → a single TiDB table, dual-written with MySQL for a transition | v1 L1433 → v4 L1751 | **stale** — L487 | to confirm |
| P4-C3 / R3 | §4.1.3 fund-flow table is `uta_liq_trans_log_202605`, monthly, past data deletable → `translog_realtime` in TiDB. Corrected from v4 by V18, as V5 corrected C8 and V22 corrected C9: the heading changes at **v2** | v1 L1761 → **v2** L1888 (v4 L2111 is that heading shifted 223) | **stale** — L469–471, which is its own table section, `#### uta_liq_trans_log (Monthly Partitioned)`, carrying three of v1's four heading clauses | to confirm — **V18 ruled 2026-08-17** — row stands, on four v1-exclusive strings rather than one (「按月存储」, 「过往数据可以删除」, 「表结构和translog保持一致」 and the table name, each 1/0/0/0). v1's ambiguity is a heading against its own 774-line section body, which is the earlier version's and so cannot trigger V22's test; what it costs is **R3**, whose only string is v1's own and is control K4's, leaving it scoreable as an attachment and reading not carried — see [call 9](#p4-open-judgement-calls) |
| P4-C4 / R4 | User-behaviour log tables are monthly-sharded `_{yyyyMM}` → unsharded TiDB tables | v1 L2539, L2667, L3653 → v4 L3272, L3416, L4488 | **stale** — L494, L498, L499 | to confirm |
| P4-C5 / R5 | Existing `uta_leverage_log` will be refactored into monthly shards → migrated from MySQL to TiDB | v1 L3213 → v4 L3869, L3871 | **stale** — L504–506, action L638, plus `uta_spot_leverage_log_{yyyyMM}` L508 | to confirm |
| P4-C6 / R6 | `set_time` in the user-behaviour log tables is nanoseconds → milliseconds | v1 L2626 (and L2782, L2921, L3179, L3353, L3612, L3754) → v4 L3359, L3405 | **stale** — L494 | to confirm |
| P4-C7 / R7 | `uta_auto_add_margin_log` trigger column is `action` → `service_action` | v2 L3954 → v4 L4192 | **stale** — L514, action L639 | to confirm |
| P4-C8 / R8 | Incident counterparty is the trading system account (系统户), funds settle against it → the in-trading difference account (差额账户). Overdraft is **not** part of the change: 「允许透支」 already stands in v2's cell | v2 L5447, L5453 → **v3** L5697, L5703. Corrected from v4 by V5: `差额账户` first appears in v3, and v4 only shifts these two lines by one with no content change | **stale** — L421–424 | to confirm — **V5 ruled 2026-08-16**, row stands with a residual at [call 8](#p4-open-judgement-calls) |
| P4-C9 / R9 | Post-rollback disposal is futures dumped to the order book with options and spot moved to a PM takeover account, pending TR discussion → spot and positions handed to TRW. Corrected from v4 by V22, as V5 corrected C8: `TRW` first appears in v3 | v2 L5455 → **v3** L5705 (v4 L5706 is that line shifted one) | **stale** — on **L667 alone**, the 05-26 action-item row ending 「(discuss with TR)」, a hedge v3 deleted in the same edit that named TRW; TRW appears nowhere. **L425–426 are not evidence**: the passage they trace to stands byte-identical in v2, v3 and v4 | to confirm — **V22 ruled 2026-08-17**, row stands on one residue, with the two withdrawn lines recorded as a presentation defect at [call 3](#p4-open-judgement-calls) |
| P4-C10 / R10 | Asset recovery is 60% done → 90% developed, integration testing next week | v3 L5674 → v4 L5675 | not stale — L735 carries v4's value | to confirm |

### Drops (measured, not gating)

| ID | Asserted earlier, absent from v4 | Evidence | Status |
|---|---|---|---|
| P4-D1 | The engine exposes `TradeEngineService` with batch ban/unban RPCs (`BatchBanTrading` / `BatchUnbanTrading`, carrying `user_ids`, `operator`, `reason`, `expire_at`) | v1 L705–737; v4 §3.3 (L705–743) defines no service, and `TradeEngineService` does not occur in v4 | to confirm |
| P4-D2 | `uta_leverage_log` already holds ~166.6M rows (`AUTO_INCREMENT = 166624305`) | v1 L3236; the number does not occur in v4 | to confirm |
| P4-D3 | The engine reconciles/tops up to a system account, which can be created in advance | v1 L4776; neither 对账补齐 nor 提前创建 occurs in v4 | to confirm |
| P4-D4 | Coin-exchange flows roll back through the normal coin-exchange path | v2 L5442; v4's 回滚 row ends at item 2 (L5684–5691) | to confirm |

### Controls

| ID | Asserted by v1 and v4 | Evidence | Status |
|---|---|---|---|
| P4-K1 | The transaction log table is sharded by month and UID trailing digit | v1 L760 → v4 L1074 | to confirm |
| P4-K2 | Users who changed account mode, toggled collateral, changed single/dual position mode, or are institutional borrowers are not auto-rolled-back | v1 L172 → v4 L174 | to confirm |
| P4-K3 | `per_user_max_subsidy_usd_amount` defaults to 10000 and `user_rollback_watermark` to 90 | v1 L4001, L4018 → v4 L4854, L4871 | to confirm |
| P4-K4 | `translog_realtime` is a single TiDB table, daily partitions, 7-day rolling window | v1 L1763 → v4 L2115 | to confirm |
| P4-K5 | `mark_price` applies only to USDC perpetuals | v1 L1279 → v4 L1593 | to confirm |
| P4-K6 | Volume estimate ~91 million rows / 55GB over 7 days | v1 L2529 → v4 L2896 | to confirm |

### One entity, three states — a drop then a supersession (evidence for NG3, not scored)

| ID | Sequence | Status |
|---|---|---|
| P4-X1 | The system-side account absorbing incident funds, in three states over three versions, of which **only the second step is a supersession**: v1 「对账补齐到系统账号（账号可以提前创建好）」 (L4776, an engine task line in §5 分工与排期) → **dropped rather than contradicted** when v2 rebuilt §5 as an 11-row table, where 「交易系统户」 is asserted for the first time as 「作为事故用户的对手方」 with 「事故期间的资金都和系统户结算 ， 允许透支」 (L5447, L5450, L5453) → **superseded at v3** by 「交易系统内的差额账户 … 和差额账户结算 ， 允许透支」 (L5697, L5703; v4's L5698/L5704 are the same two lines shifted one, per V5) | **V15 ruled 2026-08-17** — recorded as drop → supersession over one entity, not as chained supersession; its two ends stay scored as **D3** and **C8** / **C9** |

**Why it is kept, and what it is evidence for — V15 ruled 2026-08-17.** It is not a
chained supersession: v1 asserts no counterparty at all (its only two 对手方 hits are the
`opponent_user_id` field descriptions at L845 and L1858), so v1→v2 replaces no predicate
of v2's, and the chain holds exactly one same-predicate replacement, v2→v3. What the
entry does show is what the compile set does to an entity with three states, and the
article settles it: **it asserts the two oldest states side by side as current and
carries the newest nowhere.** L396 「System accounts for reconciliation can be pre-created
in advance to streamline the top-up process」 is v1's dropped claim (对账补齐 and 提前创建
are 0 hits in v2–v4); L421's heading 「System Account (交易系统户)」 and L423–424's
counterparty and overdraft sentences are v2's superseded ones (交易系统户 is 1 hit in v2 and
0 in v1, v3 and v4; the overdraft bullet is L424 rather than L423, corrected while ruling
V22, and C8's own cite L421–424 was right); L667 「System account: incident-period fund settlement, derivatives position
counterparty, post-rollback position disposal (discuss with TR)」 reproduces v2's whole
table row including the 「这里还需要和TR讨论下」 hedge (TR讨论 is likewise v2-exclusive in the
chain). **V22 adds where that line sits**: under the article's 「Additional action items
from 2026-05-26 TRD」 heading (L654), which names the block's source without claiming
anything about supersession, in a section titled 「Open Action Items」 — and the
「…from 2026-06-04 TRD」 block below it (L679) carries the line v3 *added* to §5
(「财务资金处置」, article L688) while carrying no replacement for the row v3 *changed*.
Against that, 差额 and TRW are **0 hits in the article**. So the trail A2 has to
emit here is one where the oldest entry was dropped, the middle one superseded, and
latest-wins would still be an improvement on what A1 produces.

**P4 contains no nested supersession at all, and neither does the fixture — measured.**
Projecting the v1→v2 and v2→v3 diffs onto v2's line numbers and intersecting them leaves
34 lines, and every one is either material v2 introduced (the §5 row at L5447/L5453/L5455,
`uta_delayed_fee_record`'s DDL, `uta_auto_add_margin_log`'s `action` column at L3954, the
兑币流水回滚 item at L5442) or material whose value v1 and v2 state identically and only v3
changes (`set_time`: v1's cell 「设置时间（纳秒）」 = v2's cell and DDL 「(纳秒)」 → v3
「(ms)」). v3→v4's only content changes are three cells of the 进展 column, which v3 itself
added (v2's table is `cols="3"`, v3's `cols="4"`), so those are first assertions rather
than nestings. And **P4 is the only staged chain with more than two versions** — all 38
fixture files were checked, every other chain is a pair, and P4's one co-source is not
staged — so no nested supersession can be cut from this test set at all. That is a fact
about the fixture rather than about X1, and it is why deleting the entry was rejected:
it would remove the only multi-step trail evidence in the set without putting anything
in its place.

**Restored (contradicted mid-chain, then reverted by v4): none.** v3→v4 touches
three progress cells and reverts nothing.

### P4 open judgement calls

1. **C6 is deliberately scoped to `set_time` in the user-behaviour log tables
   only.** v4 still has `exec_time_e9` in nanoseconds (L1976) and unstruck prose
   bullets about the three new fields (L1746–1747). Do not widen C6 to "all
   timestamps are milliseconds" — that would be wrong.
2. **C7 has residual contrary prose.** v4 L4182 still says 「增加action字段…」 while
   the DDL at L4192 says `service_action`. Scored on the DDL, which is what v4's
   own extraction did. Drop it if zero ambiguity is required.
3. **C9 is the least certain row in the case — V22 ruled it 2026-08-17, and it stands
   on one residue.** v4's 待决策和讨论项 block (marker L5804) still lists TWAP order-book
   selling and the PM-account transfer as options for the system account's positions
   (L5832 「采用类似保险池twap甩卖机制进行盘口甩卖」, L5833 「期权仓位如何处置： 1.等交割
   2.通过移仓给到PM接管户」), while the module table says TRW. Scored on the module table
   because the other block is explicitly marked "pending decision". **The article's
   wording sides with that block rather than with v2's superseded cell**: L425 「a **TWAP
   market-selling mechanism** similar to the insurance pool」 matches L5832's 保险池 /
   twap pairing, which v2's cell does not carry, and L426 「either held to expiry or
   transferred to a PM takeover account」 matches L5833's 等交割 option, which v2's cell
   also lacks — v2 instead puts 现货 with 期权 and offers no 等交割. **What V22 measured is
   that the block is not v4's own residual**: from v2's marker (L5531) to end of file,
   v2 and v4 differ by two deletions only, both v2-exclusive open questions, and v3's tail
   is identical to v4's, so item 5 stands unchanged in all three versions (v2 L5561–5562 =
   v4 L5832–5833) and discriminates nothing in either direction. L425–426 therefore score nothing, and C9's
   stale verdict rests on L667's 「(discuss with TR)」, which v3 deleted in the same edit
   that named TRW. Two things stay recorded here. **The article states v4's pending
   options as settled characteristics** — both lines sit under 「Key characteristics」 —
   while filing the junk-coin question from the same block as an open item at L685: a
   presentation defect in P10-C2's shape, not staleness, and one the article contradicts
   itself on within a single source block. **And 期货 is over-determined**: v2's cell
   states 「期货走盘口甩卖」 outright, where v4 leaves it to be inferred from item 5's two
   bullets — positions dumped on the order book, options carved out — so a grader reading
   L425's "futures" as v2's wording is right about where the word came from and wrong
   about whether v4 denies it.
4. **X1 is not a chained supersession — V15 ruled 2026-08-17.**
   The v1→v2 step is a reframing rather than a contradiction of the identical
   predicate, and v1 asserts no counterparty at all, so the chain holds one
   supersession (v2→v3). The entry is kept and relabelled as one entity in three
   states, a drop followed by a supersession, with the evidence written up
   [above](#one-entity-three-states--a-drop-then-a-supersession-evidence-for-ng3-not-scored).
   Its two ends are already scored separately as P4-D3 and P4-C8, so lists 1–4 are
   not double-counting.
5. **Left out — the engine `RollbackUserRequest` retyping**, the largest IDL
   change in the chain (v1 L739–748 → v4 L728–742). An identically-named
   `RollbackUserRequest` with the *old* field set still sits in §3.2 risk_eval
   (v4 L645–654), so the question is answerable both ways from v4 alone. Add it
   only phrased strictly as "the *engine* rollback request".
6. **Left out**: the §1.2 heading widening (§1.6 was not renamed, so v4 is
   internally inconsistent about ban scope); the `liq_type` value set (the DDL
   comment still lists only the original five); `uta_delayed_fee_record` fee-comment
   refinements; two v2 open questions dropped in v3, both arguably answered
   elsewhere in v4 rather than dropped.
7. **Only C10 comes from v3→v4.** Add the MarginDB cell (v3 L5774 → v4 L5775) if
   the v3-vs-v4 discrimination should rest on more than one item. The 封禁 cell was
   empty in v3, so that is an addition, not a supersession.
8. **C8 has residual `系统户` prose, weaker than C7's — recorded by V5, ruled
   2026-08-16.** The replacement itself is as clean as this fixture gets: v2 L5447–5453
   and v3 L5697–5703 are the *same table row* replaced cell for cell, subject
   (交易系统户 → 交易系统内的差额账户), role (both 作为事故用户的对手方) and detail 1
   (…资金都和系统户结算，允许透支 → …资金都和差额账户结算，允许透支). But v3 and v4 each
   keep five `系统户` mentions, and none is in a 待决策 block. They sit at a different level of
   description, which is why the row survives: three are transType accounting directions
   in §3.3 engine (v4 L788, L798, L808 — 「给用户加钱 / 系统户扣钱」, i.e. which ledger
   account moves per transType, not who the counterparty is); one is hedged with 可以考虑
   (L5683, 「系统户分片被动形成持仓」); and one is a worked example (L5864,
   「系统户UID： +1个BTC, -80000个USDT」) that three lines later says 「现货交易/期货交易：
   差额公司出」, which is complementary rather than contrary, and which sits under
   「系统账户拿到一批垃圾币，如何处置掉？」 highlighted `light-yellow` — this document's
   open-question marker, as at L5688. Scored on the table row, the same basis call 2 makes
   for C7. Drop it only if zero ambiguity is required, and note that doing so would
   discard the chain's cleanest cell-for-cell replacement.
9. **C3 is a heading-only claim, and R3 has no string of its own — V18 ruled 2026-08-17.**
   The judgement is whether a table name that appears once in v1, in the heading of a
   774-line section whose body specifies its replacement (L1761 against L1763–2534), asserts
   a design position at all, or is a heading left behind by an edit. Scored as a supersession
   because v1 states it and v2 deletes it — four strings at once, 「按月存储」,
   「过往数据可以删除」, 「表结构和translog保持一致」 and `uta_liq_trans_log_202605`, each 1 hit
   in v1 and 0 in v2–v4 — and because the article rebuilds it into a table section of its own
   (L469–471) carrying three of those four. Decline it only if a heading is held not to
   assert, and note that the article's own structure argues the other way: it read the
   heading as a table. **The caveat lands on R3 instead.** `translog_realtime` is v1's own
   string, 2 hits before v2 takes it to 11, and it is control **K4**'s line (v1 L1763 → v4
   L2115), so it cannot distinguish a carried replacement from a kept control; the count can,
   and so can one attachment — 「用于快速过滤出受影响的用户和资金损失」 is in all four versions,
   inside v1's heading beside the monthly name and on its own line under v2–v4's
   translog_realtime heading (v2 L1890, v4 L2113), and the article puts it at L471 under the
   monthly heading. On that test R3 is **not carried**, and it is the second replacement in
   the set whose string cannot carry its own test — P10-R8's, co-asserted by the `2026-03-06`
   Q1 report as V14 measured, is the other.

Also carried as current in the article but not gating: **all four** drops —
P4-D1 `TradeEngineService` as the ban/unban service (L333, L357, L396, L563),
P4-D2 `AUTO_INCREMENT ~166,624,305` (L506), P4-D3 pre-created reconciliation
accounts (L396), and P4-D4 the coin-conversion rollback path (L666). Each was
re-checked in the article rather than taken from the draft, which is how the
count was corrected from three. All six controls are present.

---

## P5 — Bybit trading skill API inventory

- `v1` = `.../raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单.md`
- `v3` = `.../raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单-v3.md`
- `article` = `data/kb-knowledge/wiki/project/bybit-ai-trading-skill.md`

**This case reads 0 of 5 contradictions stale — but only against the true version
order, which is not the order the compile set states.** Both versions carry
`date: 2026-03-13`, so the payload's oldest-to-newest claim falls to a path tie-break
that renders `…-v3.md` first and therefore asserts that **v1** is the newest source;
read that way the case is 5 of 5 stale. The tie is already recorded as ordering family
2 below, but its consequence was not drawn. That was queue item **V20**, **ruled
2026-08-16**: the payload stops asserting an order for same-day blocks instead of
asserting a better one, because no signal in the corpus reaches more than 1 same-day
pair in 384. So P5's Staleness stays reported apart from the gating count after the
fix rather than joining it. Ruling V20 also read family 2 the other way round: the two
`生成时间` lines mean these documents are **six days apart**, so the tie is v3's
frontmatter being wrong rather than the corpus being ambiguous. That was queue item
**V21**, **ruled 2026-08-16**: the fixture keeps v3 exactly as staged — both files are
byte-identical to their copies under `data/kb-knowledge/raw/docs/`, so re-dating one
would break the only fidelity property FX1–FX3 rest on — and P5 is reported as an **A2
body-date case**, which is what its 5C now testify to instead of gating A1. It is also
the instance A2 will be argued from in both directions: a body-date rule would order
this pair, and would collapse N3's and N4's into same-day ties, both members of each
carrying one heading date for the meeting they transcribe.

The 0-of-5 reading is still a result rather than a gap in the label. Like P6, it comes
with a confound — a far larger one than first drafted. Verification found **six
independent in-body ordering families**, not three:

1. The H1 carries 「(v3)」 (v3 L10) — and so does the frontmatter `title` (v3 L5), so
   this one reaches a pipeline as metadata too, not only as body text.
2. The `生成时间` lines differ (v1 L13 「2026-03-13」 vs v3 L12 「2026-03-19」). This is
   the only differing date; frontmatter `date` is `2026-03-13` in both.
3. The module count on that same line: 「全部 8 个 modules」 against 「全部 11 个」.
4. The summary-statistics table moves monotonically on five rows at once: 280→301,
   258→279, ~165→~169, ~93→~110, ~25→~31 (v1 L5441–5473 → v3 L6344–6376).
5. Section inventory and numbering: 17 numbered `##` sections against 19, with v1's
   §5 Leverage Token gone and everything after §4 shifted down by one.
6. The endpoint index ceiling equals each file's own 总 API 数 (280 against 301), so
   the index column is itself a version stamp.

A pipeline can order this pair six ways with no dated metadata at all, so P5 cannot
testify that A1's explicit signal did the work. It belongs with P6 as an
accidental-signal case, and is the more extreme of the two.

There is a second, independent reason this pass is weak evidence: **the revision is
structurally incapable of producing a hard contradiction.** Across all 273 shared
endpoint rows there are zero changes to name, method or 状态, and all 17 body
differences are pure trailing-clause deletions. It is additive scope plus a recount —
the easiest supersession shape there is. Report P5 as a confounded, low-difficulty
pass and do not aggregate its 0-of-5 with a case like P7 without that caveat.

Note also that the same-day filenames make this the one pair where `date`
frontmatter alone cannot order the versions — the tie is broken by path, per WP5.

### Contradictions and their replacements

| ID | v1 → v3 | Evidence | Article today | Status |
|---|---|---|---|---|
| P5-C1 / R1 | The inventory covers 8 skill modules → 11, the new three being Copy Trading, Strategy Orders and Trading Bot | v1 L13 → v3 L12, sections L5649, L5753, L5856 | not stale — L32 states 11 modules | to confirm |
| P5-C2 / R2 | Total audited API count 280 → 301 | v1 L5438, L5441 → v3 L6341, L6344 | not stale — L141; `280` occurs nowhere | to confirm |
| P5-C3 / R3 | Retained endpoints 258 → 279 | v1 L5446, L5449 → v3 L6349, L6352 | not stale — L142; no `258` | to confirm |
| P5-C4 / R4 | Retained split ~165 GET / ~93 POST → ~169 GET / ~110 POST | v1 L5454–5465 → v3 L6357–6368 | not stale — L142 | to confirm |
| P5-C5 / R5 | Endpoints needing Mainnet confirmation ~25 → ~31 | v1 L5470, L5473 → v3 L6373, L6376 | not stale — L144, L404 | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v3 | Evidence | Status |
|---|---|---|---|
| P5-D1 | The skill inventories a Leverage Token module (`/v5/spot-lever-token/*`, 5 endpoints under `spot.md`), Purchase and Redeem needing Mainnet confirmation | v1 L1241, endpoints L1273–1349; verified absent (`spot-lever-token`, `杠杆代币`: 0 hits in v3) | to confirm — see call 1, and **V9 ruled 2026-08-16**: the article does state this material (L413, L567) but it is **not counted as a lost drop**, two declared never-superseded sources asserting it independently |
| P5-D2 | When cancelling all orders, take care not to cancel strategic standing orders | v1 L584; v3 L583 reduces the note to 「Mainnet 需确认」 | to confirm — **V9 ruled 2026-08-16**: **not** a lost drop, 「注意不要误取消策略性挂单」 having no residue in the article |
| P5-D3 | Batch order placement must display all orders before confirmation | v1 L604; v3 L603 reduced | to confirm — **V9 ruled 2026-08-16**: **not** a lost drop, and the near-miss is the article's generic confirmation card (L320, L580), which is not 「展示全部订单再确认」 |
| P5-D4 | The BybitPay Payout endpoint is essentially an alternative withdrawal channel | v1 L4744 「向任意 UID 打款，本质是另一种提现通道」 → v3 L4889 「向任意 UID 打款」. Test on 「另一种提现通道」, 0 hits in v3 — **not** on 「向任意 UID 打款」, which is v3 L4889's own surviving cell and is asserted in the same abridged form by the declared, never-superseded `…保留接口清单按场景.md` L3550 | to confirm — **V9 ruled 2026-08-16**, a **lost** drop: article L427 states it as "alternative withdrawal channel (sends funds to any UID)". The residue is not v1-exclusive corpus-wide — the undeclared, unstaged hardening plan carries the clause at L96, with a 商户 the article does not have — so this row sits on D6's footing rather than D5's, see [V16](#v16--resolved-by-investigation-no-ruling-needed) |
| P5-D5 | The stated *reason* for removing institutional-loan UID bind/unbind — that it affects other users' accounts — is dropped; v3 keeps the removal with no rationale | v1 L4007 「机构贷款绑定/解绑 UID，影响他人账户」 → v3 L4044 「机构贷款绑定/解绑 UID」; `影响他人账户` 0 hits in v3 — **not** `影响他人`, which hits v3 L2958 「冻结子账户影响他人使用」. **Reworded on verification** — as first drafted the row folded in the surviving removal, so a grader applying the absence test to the row as written finds it present in v3 and mis-scores it | to confirm — **V9 ruled 2026-08-16**, a **lost** drop: article L402 states it as "institutional loan UID binding (affects other accounts)". The residue is a v1 fingerprint, 「影响他人账户」 being a single corpus hit, and the hardening plan drops the clause on its own line for this endpoint (plan L502) |
| P5-D6 | Universal Transfer's stated risk — that funds can be moved to a sub-account under someone else's control — is dropped; v3 keeps the endpoint, its 移除 status and the bare 跨 UID 转账 classification | v1 L2730 「跨 UID 转账，资金可转到他人控制的子账户」 → v3 L2652 「跨 UID 转账」. Test on the full clause 「资金可转到他人控制的子账户」 or on 「他人控制」, both 0 hits in v3 — **not** on 「他人」, which hits v3 L2958 「冻结子账户影响他人使用」, a row identical in both versions | to confirm — **V8 ruled 2026-08-16**, promoted from [call 3](#p5-open-judgement-calls), and a **lost** drop: article L394 states it as 「Funds can reach accounts controlled by others」. Note the residue is not v1-exclusive corpus-wide (the undeclared hardening plan carries the clause at L116), but that document reaches neither the article nor the fixture — see [V16](#v16--resolved-by-investigation-no-ruling-needed) |

**Three of the six are stated as current in the article today** — D4 (L427), D5 (L402)
and D6 (L394) — which is the baseline A2's RP1 arm would be measured against for this
case, and **V9 ruled 2026-08-16** stops the count there. D1's material is in the article
too (L413, L567) and is deliberately excluded: two of the article's declared,
never-superseded sources assert it independently, and one lists the two endpoints as
retained with 「执行前需确认」 (`raw/docs/2026-03-12-bybit-trading-skill-保留接口清单按场景.md`
L514–537), so no supersession rule could have removed it — call 1's reasoning, applied to
the measurement rather than to the classification. D2 and D3 never reached the article at
all: its only cancel-all content is the DCP note at L423, whose row both versions carry
with an identical 「断线保护设置」 备注 (v1 L725–728, v3 L724–727), and its batch-order line
(L406) states the confirmation requirement v3 L603 keeps. The
near-miss to avoid there is reading the article's generic confirmation card (L320, L580)
as D3's 「展示全部订单再确认」 — the batch-specific proposition is absent.

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P5-K1 | 22 endpoints removed on security grounds, split 12 P0 and 10 P1 | v1 L5481, L5489, L5497 → v3 L6384, L6392, L6400 | to confirm |
| P5-K2 | Move Position and its history endpoint are removed because they move positions across UIDs | v1 L970 → v3 L969 | to confirm |
| P5-K3 | Withdraw is removed because it sends funds to external addresses | v1 L2723 → v3 L2612 | to confirm |
| P5-K4 | Modify Master API Key is removed because the AI could grant itself Withdraw permission | v1 L3055 → v3 L2998 | to confirm |
| P5-K5 | Upgrade to UTA is removed as irreversible | v1 L2039 → v3 L1930 | to confirm |
| P5-K6 | Leverage above 20x triggers an extra warning beyond Mainnet confirmation | v1 L802 → v3 L801 | to confirm |

### P5 open judgement calls

1. **P5-D1: drop or contradiction?** v3 never says leverage tokens are out of
   scope — the module is simply gone. Under the stated rule that is a drop. But
   「全部 11 个 modules」 plus the absence arguably asserts it is no longer in
   scope. Under the stated rule it stays a drop, and verification removed the
   reason for overruling it. As first drafted this entry claimed the article's
   leverage-token content is v1-only and that promoting D1 would make P5 1 of 6
   stale. **That premise is false.** The two article lines are real (L413 「Earn Place
   Order, Leverage Token Purchase/Redeem」, L567 「22 endpoints including leverage
   tokens」) but the content is over-determined: two of the article's own declared,
   never-superseded sources assert it independently —
   `raw/docs/2026-03-11-bybit-ai-trading-skill-能力清单.md` L260 supplies L567's
   「22 个 endpoint」 with leverage tokens and spot margin together, and
   `raw/docs/2026-03-12-bybit-trading-skill-保留接口清单按场景.md` L494–538 supplies
   L413. Promoting D1 would credit the pipeline's failure for content unsuperseded
   sources legitimately provide. D1 stays a drop and P5 stays 0 of 5 on the true
   version order — see [the co-source
   confound](#note-co-source-assertion-confounds-the-staleness-column), and **V20** for
   why that order is not the one the payload states — and, after V20's ruling, not one
   the payload will state at all. **V9, ruled 2026-08-16, extends this to the drop
   measurement**: D1's article residue is not counted among P5's lost drops either,
   because `…保留接口清单按场景.md` L514–537 lists Purchase and Redeem as retained with
   「执行前需确认」 and is never superseded, so the article is not carrying that content
   in error.
2. **No status flags changed anywhere.** All **273** pairable endpoint rows match on
   name, method and 状态 — zero differences across all three fields, which is the
   strongest single piece of evidence in this case. (251 as first drafted was wrong:
   v1 has 278 REST endpoint rows and v3 299, sharing 273 paths, since 278 − 5
   leverage-token rows = 273.) The ⚠️ count rose only because of **eight** new
   copy-trading / strategy / bot write endpoints. So this revision offers no
   reversed-decision contradiction — it is additive scope plus a recount. Verified
   mechanically: 280 distinct `/v5/...` paths in v1, 301 in v3, 5 dropped (all
   `spot-lever-token`), 26 added, and 280 − 5 + 26 = 301.
3. **Note abridgement below article altitude — settled by V8, ruled 2026-08-16.**
   v3 shortens 17 备注 cells, not the 10 this call first accounted for. The seven the
   draft missed are `universal-transfer` (v1 L2730 → v3 L2652),
   `query-universal-transfer-list` (L2732 → L2672), `agreement/pay` (L4826 → L4971),
   `move-positions` (L970 → L969), `move-history` (L990 → L989), `create-sub-api`
   (L3035 → L2978) and `update-api` (L3055 → L2998).
   **The disposition is 5 drops and 12 restatements**, on a two-pronged test that V8
   read out of the promotions already made: the dropped text has to state a
   proposition its own surviving cell does not entail, *and* v3 must not assert that
   proposition elsewhere, sibling rows of the same family included.
   Only `universal-transfer` passes both, and it is now **D6** — 跨 UID 转账 does not
   entail a destination under a third party's control, and no other v3 row says
   otherwise. The other six unlisted rows fail one prong or the other, as do the six
   the draft already declined (fixed-term borrow, flexible borrow, Release Assets,
   Create Sub-account, Distribute Voucher, Delete Master API Key).
   **Two of those declines are worth reading before extending this label.** The borrow
   pair is a *de-duplication*, not a loss: v1 says 有清算风险 and 产生利息负债 on both
   rows, v3 keeps one each (fixed-term L3696, flexible L3852), so both propositions
   survive. And `create-sub-api`'s 可能赋予更高权限 survives on the sibling API-key row
   as 「AI 可给自己加 Withdraw 权限」 (v3 L2998).
   **The article carries seven abridged details, not the two first drafted** — L394,
   L396, L397, L399, L402, L416, L427; A7's "six" undercounts its own list. Three are
   drop clauses, so **D4, D5 and D6 are lost drops** (L427, L402, L394) — D6 recorded
   as such by V8, D4 and D5 by **V9, ruled 2026-08-16**, which also measured the whole
   arm at 3 of 6 and declined to count D1's residue. The other four (L396, L397, L399, L416) belong
   to *declined* rows, and that is a hazard rather than a gap: their v1 wording is
   genuinely gone from v3, so a grader testing strings finds a loss where the label
   says there is none. The proposition is what survives, not the phrasing.
   The caveat this raised is now **discharged**:
   `raw/docs/2026-03-12-bybit-trading-skill-security-hardening-plan.md` does carry
   several of these rationales verbatim (L96, L116, L156, L342, L588) while **not**
   appearing in the article's `sources` frontmatter, but nothing it asserts alone
   reaches the article, and D5's own clause 「影响他人账户」 is a single corpus hit at
   v1 L4007. So the residues are v1's and D4 and D5 score as lost drops — evidence in
   [V16](#v16--resolved-by-investigation-no-ruling-needed). **D6 is the one row where
   the plan is a genuine co-source**: 「资金可转到他人控制的子账户」 has two corpus hits,
   v1 L2730 and plan L116, so it is not the v1 fingerprint D5's clause is. It still
   lands on v1 under V16's method — the plan's own 「主账户↔任意子账户」 gloss never
   reaches the article — and the plan is not staged in the fixture, so nothing about
   this reaches the FX4 run.
4. **Left out**: the 🔴 glyph on removal rows (presentation), and endpoint index
   renumbering caused by the Leverage Token removal (positional artifact — a
   grader must not match on endpoint numbers).
5. **Unrelated stale content, not this chain's**: L189 「274+ API endpoints across
   7 functional modules」 and L198 「plus 7 functional modules」 come from a
   different source document. A naive whole-article number match would
   false-positive on them.

---

## P7 — 2026 H1 cost progress tracking

- `v1` = `.../raw/docs/2026-04-09-2026-h1成本进展跟进.md`
- `v2` = `.../raw/docs/2026-05-14-2026-h1成本进展跟进.md`
- `article` = `data/kb-knowledge/wiki/project/cloud-infrastructure-cost-optimization-2026h1.md`

**One framing decision governs this whole label. Ruled 2026-08-15: the
measurement-time reading is accepted, so the label below stands and P7 scores its
8 contradictions.** v2 contains v1 verbatim plus two new weekly columns, so no
*dated* claim is ever textually contradicted — v2 asserts both 「as of 4/30:
24.57w」 and 「as of 5/14: 57.11w」, which are compatible. The accepted reading
takes the measure to be "cumulative Q2 progress / current status of item X", with
the as-of date being a measurement time rather than a different period.

The stricter reading (as-of date is part of the period) was rejected: under it this
case has **zero** contradictions and measures nothing. What decided it is the
article's own behaviour rather than a preference between two defensible readings —
it flattens the table into undated current-state prose (「significant remaining
opportunity」, an open action to close a 3,000-core gap), which is exactly where
v1's figures become wrong. An article that had preserved the as-of qualifiers
would have made the strict reading the right one; this one did not.

`superseded-drop` is **empty by construction**: a body diff returns additions
only. See call 2 for the three candidates under a different absence test.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P7-C1 / R1 | Q2 progress 40.95%, 24.57w banked → 95.18%, 57.11w | v1 L69 → v2 L75 | present but dated 「as of 2026-04-30」 (L43–49); v2's 95.18% absent, and 57.11 appears mis-rendered as a *rate* at L39 | to confirm |
| P7-C2 / R2 | Low-utilization governance 17.6w at 117.3% of a 10w–15w target → 44.4w, with 117.3 struck and no new rate given | v1 L90 → v2 L102–103. Hazard: 117.3% also appears **un-struck** in v2's own 0507 column (L220), so a string-matching scorer will find it "present in v2" and wrongly clear the row | **stale, undated at L480**; also present at L57, but there under a 「Completed (Apr 30)」 column header (L55), so L57 is not undated evidence; `44.4` and `41.13` absent | to confirm |
| P7-C3 / R3 | Commercial-model optimization 13.3%, 6.8w → 41.5%, 8.3w | v1 L75 → v2 L82 | amount 6.8w present under a 「Completed (Apr 30)」 column (L58); v1's 13.3% **absent** — the article recomputes it as 「~27–34%」; v2's 41.5% and 8.3w absent | to confirm |
| P7-C4 / R4 | Listing low-utilization rightsizing 3300C at 83.1% → 3864C at 97.28% | v1 L92 → v2 L222 | **stale and undated** — L480; the article *also* carries v2's value at L70 and L481, contradicting itself | to confirm |
| P7-C5 / R5 | Optimizable cores 7197C on AWS (13.8w) and 17054C on Tencent Cloud (3.8w) → 11362C and 25046C | v1 L96, L99 → v2 L108, L115, L107 | **stale, framed as a live opportunity** — L490 | to confirm |
| P7-C6 / R6 | EC2 SP shortfall 3000C → 7C, with confirmed reducible scope 11362C | v1 L82 → v2 L207, L88. Note R6's 11362C is the *same figure* as R5's AWS replacement (v2 L88 against L108), so a scorer matching on figures will double-count the two rows | **stale and live as an open action at L571**; L192 states the same gap but explicitly 「as of April 30」 and in the same sentence carries the replacement scope 11,362核 (also L74, L482); only the `7C` value is lost. **Residual recorded by V4**: the newest source in the set restates 3000C at 05-20 L374 — see below | to confirm |
| P7-C7 / R7 | Tencent Cloud ES monthly contract submitted but not landed → done, normal May cashback | v1 L86–87 → v2 L98 | **stale** — L201, open action L572 | to confirm |
| P7-C8 / R8 | The identify–analyze–track–review closed loop is at 0% → 50% | v1 L319 → v2 L549 | **stale** — L91; sibling rows *were* patched (L114, L115) | to confirm |

**6 of 8 stale in the article's text**, and **5 of 8 corrections lost** — C4's
3,864C/97.28% and C5/C6's 11,362核 did land. C1 and C3 keep v1's value under an
explicit as-of label, which is defensible on its own, but their replacements are
absent from the article entirely.

**V4 ruled 2026-08-16: all 8 rows stay scoreable; only the causal claim is
restricted.** The confound below is real and verified, but it does not invalidate the
observations. Supersession is a property of the compile set, not of a document pair:
the set holds the 04-14 source asserting the old value and v2 asserting otherwise, so
a writer that emits it undated has mishandled ordering whichever document it read it
from — and the 04-14 source is itself superseded inside the fixture by P2's v2, so A1
orders it too. Under [V19's ruled
criterion](#independent-verification-pass-2026-08-15) every stale row
holds, because the newest source speaking to each is v2. What the confound does kill is
the *causal* reading: only **C8** supports "this pair's ordering was lost", so 6 of 8
may not be quoted as evidence of ordering loss. For FX7 it cancels outright, the
co-source being present in both arms.

The attribution caveat is not a quibble. The article merges five sources, and one of
them —
`raw/docs/2026-04-14-infra-双周会-2026_h1.md`, which is P2's v1 — asserts v1's
**entire** 0430 column verbatim: 40.95%/24.57w at L898 (C1), 13.3%/6.8w at L904
(C3), 3000C at L911 (C6), 合同已提交 at L916 (C7), 117.3%/17.6w at L919 (C2),
3300C/83.1% at L921 (C4), and 7197C/17054C at L925/L928 (C5). All nine tokens were
re-counted as fixed strings when V4 was ruled, one hit each except `7197` with two. So
for C1–C7 an article that states the superseded figure may be faithfully reporting
*that* source rather than mishandling this pair.

**Only C8 is clean on both sides**, and the test has to be the full phrase: v1 L319
「**[0%]**建立“识别—分析—跟踪—复盘”闭环机制」 → v2 L549 「**[50%]**」, and
`识别—分析—跟踪—复盘` returns **0 hits** in all three non-chain sources. The bare token
「闭环」 does not work as the test — it has 7 hits in the 双周会 alone, all of them a
different loop (L823 「三盘闭环：异常 → 工单 → 治理 → 验证」, L876 「自动识别与治理闭环机制」).
That is the same string-matching hazard already recorded on C2's 117.3%.

The corrections that did land are confounded the same way — 57.11w, 11362C and
3,864C/97.28% are all also in `raw/meetings/2026-05-14-成本管控小组周会.md` (fixed-string,
one hit each; note `3,864` carries a comma there, so a scorer searching `3864` misses
it). Two corrections are in **no** source but v2: C1's 95.18%, C2's 44.4w/41.13, C3's
41.5%/8.3w and C5's 25046C all return 0 hits across the three non-chain sources, as do
C7's ES-contract outcome and C6's 7C. What is *not* confounded is that v2's newest
column reached the pipeline at all: article L517 and L682 carry content existing only
in v2 (L97, L190–191), so the absences are genuine losses.

**C6 carries an extra ambiguity, found when V4 was ruled.** The newest source in the
compile set is `raw/meetings/2026-05-20-aws成本分析.md`, and at L374 a speaker says
「这是Q2，还计划内的还剩3000 C 没有优化」 — C6's own figure, six days *after* v2 reported
that gap closed (v2 L207 「目前缺口7C」, against 「预估完成9993C」 on a 「需优化1w核」 target,
v1 L82 having been 「预估完成7197C」 with 「目前缺口3000C」). Whether the transcript means the
EC2 SP shortfall or the broader Q2 plan is not stated. So C6 is the one row where the
newest source that speaks to the item may be asserting the superseded value, which is
exactly the case V19's criterion turns on. The row stands, with this residual recorded
as C7's and C9's are in P4. It does not reach the fixture run: the 05-20 meeting is not
staged.

This is a general threat to FX5 and not a P7 quirk — see
[the co-source confound](#note-co-source-assertion-confounds-the-staleness-column).

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P7-K1 | H1 target is 420w committed / 540w stretch against a Q1 baseline | v1 L37 → v2 L43 | to confirm |
| P7-K2 | Architecture rationalization is still 0% against its 16w–30w Q2 target | v1 L70 → v2 L76 | to confirm |
| P7-K3 | EC2 SP coverage 83%, daily on-demand spend 3.5w | v1 L77 → v2 L84 | to confirm |
| P7-K4 | Tencent Cloud Doris monthly contract landed, saving 4w | v1 L85 → v2 L97 | to confirm |
| P7-K5 | Fiat's model-call anomaly was throttled from a 1750/day peak to under 50/day, about 4w per month of identified anomaly | v1 L111 → v2 L162 | to confirm |
| P7-K6 | AI capability building overall stands at 60% | v1 L294 → v2 L526 | to confirm |

### P7 open judgement calls

1. **The same-measure/same-period reading — RULED accepted, 2026-08-15**, on the
   article-behaviour evidence above. The label stands and P7 keeps its 8
   contradictions. Had it been rejected, P7 would have had zero contradictions and
   left the positives. One consequence to carry into scoring: because the reading
   is a judgement about what the measure *is*, C1 and C3 — where the article keeps
   v1's value under an explicit as-of label — are scored on their lost
   replacement rather than on staleness. Their `Article today` column says so.
2. **Drops, if a non-empty list is wanted**, need the test "asserted in v1's
   newest column, not carried into v2's newest column, not contradicted". The
   three candidates are v1 L93 「新增可缩容68C」, v1 L94 (the architect-weekly
   follow-up, replaced in v2's 0514 column by a per-BU confirmation table), and
   v1 L110 「20260506评审方案」. All three were left out because a scorer testing
   "absent from v2" finds them present at v2 L325, L326 and L342 — the exact shape
   that silently corrupts a score.
3. **C2 is the messiest entry.** v2 struck 「117.3」 without supplying a new rate,
   so the replacement is the amount only. 44.4w against a 10w–15w target is
   296–444%, so the article's 「117.3% ✅」 is arithmetically stale too — but do not
   score for a specific new percentage. v2's own extraction misread this, recording
   the struck figure as live.
4. **C4's v2 quote is from the 0507 column**, because in the 0514 column the same
   sentence is struck (v2 L104). The document uses strikethrough for both "done"
   and "cancelled". Read as "item closed", because the 0514 column's 41.13w and
   36408C are built on that rightsizing. If it is a retraction, C4 becomes a drop.
5. **C6 mixes columns deliberately** (v1's gap is in the 0430 column, v2's 7C in
   0507, and 0514 carries no gap line because the confirmed scope exceeds the
   need). Kept because the article turns it into a live open action. Drop it if
   every contradiction must be anchored in the newest column.
6. **C5 bundles two numbers** because the article states them as one pair (L490).
   Split if the scorer needs one number per entry.
7. **Money markers.** Neither version contains `¥`, `CNY`, `RMB` or 人民币 — zero
   hits. Amounts are bare (`420w`) or USD-marked. The *article* introduces `RMB`
   and 「万 CNY」 at L18, L128, L137, L170–173, L516; those are downstream
   transcription artifacts and must not be converted.
8. **No internal version marker in either body** — identical title, no revision
   line. The only body-internal ordering signal is the set of weekly column
   headers. Note that v1's filename date (2026-04-09) is *older* than its newest
   column (20260430), so the filename date is not an as-of date for v1.
9. **Left out but valid under the same reading**, trimmed to the eight-item cap:
   database low-load 0.5w → 3.27w; HDFS 200TB → 600TB (article L491 stale); Kafka
   S3 deep archive planned-by-4.30 → done (L494 stale); Q3 其他 0% → 88.5% (L497
   stale); four AI-cost scenarios 0% → 30%; source governance 0% → 20% (corrected
   in the article at L115); other-data onboarding 0% → 10%; MySQL and Redis
   low-load counts.
10. **Out of scope**: the article merges five sources, so `~3,000 cores` at L169,
    L524 and L702, `~68万/month`, and the Gen5→Gen6 cancellation come from two
    meeting notes rather than this chain. Also unverified: several progress figures
    live only inside `<image>` payloads in both versions, so a claim marked absent
    could in principle sit inside an image.

---

## P8 — AI project portfolio overview

- `v1` = `.../raw/docs/2026-04-12-ai-项目全景-分类总览.md`
- `v2` = `.../raw/docs/2026-04-13-ai-项目全景-分类总览.md`
- `article` = `data/kb-knowledge/wiki/decision/ai-project-portfolio-status-q2-2026.md`

Revised the next day, and **not** the wholesale reorganisation the recorded
similarity of 0.079 suggests: 71 of 88 table rows are byte-identical and 212 of
~1,700 body lines differ. (That similarity figure is an artifact — see
[the similarity note](#note-the-recorded-similarity-figures-are-distorted).) The
real edit is a **re-attribution of infrastructure projects from named individuals
to teams**: the infra tables' `Owner` column becomes `团队`, four rows replace named
individuals with team names, and Lucas's attribution relocates to the section heading as
`@lucas.wan`. Secondarily, v2 deletes the whole `### 关键资源约束` headcount table
and three milestone rows.

Both bodies carry the same internal date marker `2026-04-12` (v1 L15, v2 L14) and
neither has a version number, so only the frontmatter `date` distinguishes them.
This is the case where A1's signal does all the work with no accidental help — which
is why it is worth keeping after V1 struck its contradictions. It exercises the signal
on the drop and control columns instead.

### Contradictions and their replacements

**None. P8 contributes no contradictions** — the four it was drafted with are struck by
V1, ruled 2026-08-15, and kept below as a re-attribution list. P8 stays in the set as a
case A1 must not break, carrying 6 drops and 6 controls; it does not gate under FX7.

### Re-attribution, not contradiction — the four rows V1 struck

Kept with their evidence because they are the set's clearest instance of a change that
*reads* like supersession and is not one. Anyone tempted to score an owner change should
read this list first. The IDs are retired: nothing may cite `P8-C1`–`C4` or `R1`–`R4` as
gating items.

| Was | v1 → v2 | Evidence | Article today |
|---|---|---|---|
| C1 / R1 | The AI unified governance (three-review) process is owned by Lucas Wan → by 架构 | v1 L233, L236 → v2 L228, L231 | states **both** — L188 「Lucas Wan / Architecture team」, and L27 names Lucas |
| C2 / R2 | AI Gateway integration is owned by Lucas Wan → by 架构 | v1 L253, L256 → v2 L248, L251 | states **both** — L192 「Lucas Wan / Architecture team」 |
| C3 / R3 | The AI Coding standards project is owned by Lucas Wan → by 架构 | v1 L122, L125 → v2 L66, L69 | states no owner for it |
| C4 / R4 | AI Trading Skills is owned by Lucas Wan and Victor → by 架构 / api 团队 | v1 L88, L91 → v2 L49, L52 | L144 names no owner; 「Victor」 occurs nowhere |

Three facts in v2 itself settled it:

- v2 asserts the mapping these rows read as a substitution: L271 writes
  「Lucas (架构) / Roger (知识库) / …」, and L19 hangs `@lucas.wan` on the whole
  infrastructure category heading, which v1's L24 does not. `团队 = 架构` therefore names
  Lucas at a coarser grain rather than replacing him.
- The article writes both sides anyway (L188, L192), so under FX5's staleness rule — in
  either the drafted or the V19 form — it is not asserting a superseded value.
- v2 re-attributed nothing away: person names survive in its own `团队` column (L154
  Smart Router, L291, L311) and 「Victor / Lucas」 still stands at L681. Selective enough
  to be an unfinished editorial pass, which is the reading the draft could not exclude
  and now does not have to.

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P8-D1 | The AI team has 6 people and is severely insufficient across CS, personalization and infrastructure | v1 L1563–1569 | to confirm |
| P8-D2 | Infra support for AI is 3 people, spread across business lines, unsustainable | v1 L1574–1580 | to confirm |
| P8-D3 | The security team has 5 people with 25% of capacity consumed by AI projects for two months or more | v1 L1585–1591 | to confirm |
| P8-D4 | An AI asset convergence roadmap and freeze strategy is due in the week of 4/13–4/19 | v1 L1618, L1621 | to confirm |
| P8-D5 | Rockman formally joins as CTO on 4/14 | v1 L1629, L1632 | to confirm |
| P8-D6 | Locking the AI Coding 20% metric definition is a Q2 milestone | v1 L1662, L1665 | to confirm |

Five of the six are stated as current in the article today (L16, L94, L161, L49–52,
L185, L40, L194) — recorded because it sizes A2's RP1 arm, not because it gates A1.
D3 holds only in part: the article carries its 25%/≥2-month clause at L16 but never
states the security team's headcount, and `5 people` returns no hits.

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P8-K1 | Smart Router is a Go-native LLM routing service validated at ≥50% cost reduction | v1 L199 → v2 L160 | to confirm |
| P8-K2 | AI Gateway covers 82.5% of 40 target scenarios (33/40) | v1 L262 → v2 L257 | to confirm |
| P8-K3 | The portfolio totals 63 projects (24 infrastructure + 39 business) | v1 L1541 → v2 L1534 | to confirm |
| P8-K4 | 88 AI scenarios collected company-wide, 41 pending for lack of AI team resources, cross-BU common needs recommended for central build | v1 L1598 → v2 L1541 | to confirm |
| P8-K5 | Q1 2026 AI coding actuals: 74.89% adoption, 34.17% AI code ratio | v1 L322 → v2 L317 | to confirm |
| P8-K6 | Bybot automatically handles 83.85% of online CS volume at an 84%+ resolution rate | v1 L654 → v2 L647 | to confirm |

### Relocated, not dropped — the list that proves reorganisation was not read as deletion

- Lucas Wan's ownership of the infrastructure category is not deleted; it moves to
  the section heading (v2 L19 「## 一、基建类全局 AI 项目 @lucas.wan」, absent from
  v1 L24). Drafted as the reason C1–C4 were scoped to specific rows; under V1 it is
  the reason they score nothing.
- Completed-infra rows 1 and 2 move from the top of the table (v1 L49, L66) to the
  bottom (v2 L163, L180), byte-identical; v2's row order is 3, 5, 6, 4, 7, 8, 9, 1, 2.
- Smart Router row 9 relocates (v1 L185 → v2 L146), content identical, still
  `Lucas Wan` — v2 did *not* teamify it.
- MCP 能力建设 and AI Coding 采纳率提升 also keep `Lucas Wan` in v2's `团队` column
  (v2 L291, L311; L283/L303 as first drafted were off by eight lines).
- The 88-scenario / 41-pending callout moves out from under the deleted
  `### 关键资源约束` (v1 L1598) to sit under `## 三、数据汇总` (v2 L1541), so the
  resource-shortage *framing* survives; only the headcounts drop.
- `AI Code Review CI 集成` is *expanded*, not contradicted: v1 「中台架构组」 (L108)
  → v2 「效能 / app / 中台架构组」 (L103).

### P8 open judgement calls

1. **Is `Owner` → `团队` a real re-attribution or a column relabel? — RULED, neither
   scores.** The change is *selective*: rows 9, 12, 13 and 14 keep person names inside
   v2's `团队` column while rows 3, 5, 10 and 11 change to `架构`, and the header change
   is confined to the two infra tables (the 未开始 infra table and all four business
   tables still say `Owner`, v2 L497, L561, L707, L1150). The draft read that as
   deliberate re-attribution; a mechanical relabel would have converted all of them.
   But the competing reading — an editor who started and stopped halfway — cannot be
   excluded from the text, and v2 names Lucas at both the category heading (L19) and in
   `Lucas (架构)` (L271), so even the deliberate reading does not make the two grains
   incompatible. V1 accepted that, and all four contradictions collapsed: P8 has none.
2. **The column-header change itself is deliberately not an entry.** It is the
   umbrella cause of C1–C4, but "the infra tables use an Owner column" is not
   scoreable in article prose.
3. **Left out, wants a decision — the JIRA/GitLab MCP schedule.** v1 「Q2 W6」
   (L1684) → v2 「Q2」 (L1594). Q2 W6 is inside Q2, so v2 de-specifies rather than
   contradicts; but the week-level commitment was removed. The article says "Q2
   Week 6" in three places (L102, L157, L191), so promoting this adds a third
   stale hit.
4. **Left out**: v1 「新多站点架构测试完成 (100% AI 编写)」 (L1709) → v2 adds an
   「App」 scope qualifier (L1619); the underlying project row is identical in both.
   Restatement, not change.
5. **Do not trust the stored extractions on ownership.** v2's extraction invents
   `owner: Frontend Team` for the multi-site item where the raw text says `Arkin`,
   same as v1, and renders v1's 「中台 / AI Infra」 as "Middle platform team" — a
   translation, not a change. The extractions did independently corroborate C1 and
   C2, but every entry above is grounded in raw text.
6. **Drops are at the cap of 6**, and they are two editorial acts: D1–D3 delete
   `### 关键资源约束` (v1 L1546–1594) and D4–D6 delete three milestone rows.
   Collapse to 2 entries if scoring should count acts rather than claims.

---

## P9 — Bybit AI ToC project initiation

- `v1` = `.../raw/docs/2026-04-23-bybit-ai-toc-整体立项.md`
- `v2` = `.../raw/docs/2026-05-11-bybit-ai-toc-整体立项.md`
- `article` = `data/kb-knowledge/wiki/project/tradegpt-toc-product-roadmap.md`

A genuine positive rather than an append-only revision, but most of the
281→685-line growth is additive and the contradictions concentrate in schedule,
scope-limit and decision-reversal claims. v2's body carries two internal date
markers — the heading 「# 会议纪要 20260513」 (L656), which postdates v2's own
frontmatter date of 2026-05-11, and 「ABF（6月末启动，目标7.30主网）」 (L234) — so v2
is distinguishable from v1 by body content, not only by the date prefix.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| ~~P9-C1 / R1~~ | ~~The end state is two parts (Skills for self-hosted OpenClaw users, plus an "online lobster" via the TradeGPT entry) → three pillars (问答交互 / 智能投顾 / Agent能力)~~ | ~~v1 L20 → v2 L122, L130, L133, L136~~ | **struck by V2, ruled 2026-08-15** — v2 keeps *both* parts (L175–178 and L184, the latter already scored as control **K1**), so the article's two-component framing at L21, L23–24 matches the newest source and was never stale. The pillars are a capability taxonomy on another axis; the substance now sits in control K1 below and in call 7's additive list. ID retired | — |
| P9-C2 / R2 | Phase 3 completes end of September → end of October | v1 L140–141 → v2 L124 | not stale — L339, and L341 explicitly records the move | to confirm |
| P9-C3 / R3 | Phases 1 and 2 complete mid-June and mid-August → end of June and end of August | v1 L108–109, L126–127 → v2 L124 | not stale — L339, L422, L461 | to confirm |
| P9-C4 / R4 | Top-20 Q&A optimization is a phase-1 deliverable → reassigned to phase 2 | v1 L121 → v2 L156 with the legend at L124 | **stale** — L434 lists it under Phase 1 | to confirm |
| P9-C5 / R5 | The phase-1 killer feature is a cross-product yield comparison spanning Earn, spot and RWA → yield routing limited to 5 capital-protected products across Earn, Margin Staked SOL and Spot X, over 16 auto-release scenarios | v1 L205 → v2 L161–162, L316–317, L673; the 5 products are tabulated at v2 L333–384. **Reworded on verification** — "5 capital-protected Earn products" as first drafted overstated the narrowing, since v1's 现货 leg is partly retained; only RWA and the horizontal-comparison framing are genuinely gone | not stale — no RWA or horizontal-comparison killer feature in the article | to confirm |
| P9-C6 / R6 | Personal dedicated OpenClaw instances open to high-value TradeGPT users in phase 2 → per-user hosted OpenClaw is a paid mid-tier subscription (phase 3) | v1 L134 → v2 L185–186, L650–653 | **stale** — L236 states the phase-2 exception, L465, L339; the article carries v2's Cloud OpenClaw (L68, L234, L477) alongside without resolving | to confirm |
| P9-C7 / R7 | The adopted Bybot/TradeGPT resolution is the hybrid keeping Bybot's own entry alive → Global keeps only the TradeGPT entry, Local keeps the CS entry | v1 L287, L281 → v2 L678, L662 | **stale** — L258, decision heading L297; v2's routing decision is appended at L260 without retracting the hybrid | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P9-D1 | One OpenClaw per user costs 20 USD/month to run plus 20 USD/month in tokens, reaching 4M USD/month at 100K DAU | v1 L24 | to confirm |
| P9-D2 | OpenClaw cannot be shared across users — the design is single-user and sharing risks data contamination, forcing one instance per user | v1 L25 | to confirm |
| P9-D3 | Model selection is decided by parallel A/B testing of next-day retention, breaking ties on cost and response time | v1 L225, L227; 留存 occurs nowhere in v2 | to confirm — see call 5 |
| P9-D4 | TradeGPT will offer an A/B answer picker returning two answers in parallel, doubling as a way to test answer logic and compare models | v1 L233 | to confirm |
| P9-D5 | Regulators prohibit trading recommendations inside a CS bot, so a merged entry would fail licensing review on Local Sites and on a future licensed Global site | v1 L278, L280; neither 合规 nor 监管 occurs in v2 | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P9-K1 | The only four OpenClaw capabilities TradeGPT lacks — heartbeat trigger, workflow orchestration, long memory, multi-chat-app adaptation — will be built in-house, and with it v1's whole two-part end state: 对自有龙虾用户 Skills at v2 L175–178 and the in-house TradeGPT agent at L184 | v1 L20, L27 → v2 L175–178, L184, L625–632 (the two-part half added by V2, which struck C1) | to confirm |
| P9-K2 | The 26H1 Fee Conversion target is 80 Mil, 300% growth on 25H2's 19.9 Mil actual | v1 L63–72 → v2 L53–62 (L54–63 as first drafted omits the 「Fee Conversion」 label cell at L53) | to confirm |
| P9-K3 | Agent sub-account phase 1 covers account balance cap, fund transfer, max borrow leverage and max contract leverage | v1 L186 → v2 L620 | to confirm |
| P9-K4 | TradeGPT's private Skills may recommend on 180 days of Copy Trading leader performance while the product shows users only 90 | v1 L194 → v2 L639 | to confirm |
| P9-K5 | The TradeGPT entry end state is a hideable persistent floating button on the right offering page-specific preset questions | v1 L266 → v2 L287 | to confirm |
| P9-K6 | Phase-1 Skills and MCP are live, Skills covering basic query and execution across all product lines, MCP basic queries for most products | v1 L159 → v2 L593 | to confirm |

### P9 open judgement calls

1. **C3 bundles the phase-1 and phase-2 date moves** because v2 states all three
   deadlines on one line (L124) and two-week slips are individually low
   consequence. Split for strict one-assertion-per-entry (8 contradictions);
   collapsing C2 and C3 into one instead makes an article that gets phase 1 right
   and phase 3 wrong score ambiguously.
2. **C4 rests on colour markup, not prose.** 「Top 6-20 问答优化」 is phase 2 only
   via the `light-green` span plus the legend at L124; the 输出端 prose (L307) gives
   no phase. Drop C4 if colour-encoded phase assignment is too weak to score. The
   same mechanism carries C6's phase (absence of a highlight = phase 3).
3. **C6 is the least certain.** v2 never says high-value users will *not* get a
   personal OpenClaw; the contradiction rests on reading v2's user-tier table as an
   exhaustive segmentation. If the tiers are non-exhaustive this becomes a drop —
   and the article's current "Phase 2 exception" wording (L236) is exactly the
   reconciliation someone would write under that reading.
4. **C5's subject match is a judgement call**: v1's killer feature is a
   *comparison* across 理财+现货+RWA, v2's is *routing* into 5 capital-protected
   products. Treated as the same subject because both fill the phase-1 slot and v2
   uses the exclusive 「限于」. Alternatively re-cut as a drop (RWA comparison) plus
   a purely additive yield-routing entry.
5. **D3 could be a contradiction** against v2's 「底层模型定期更新（GPT -> Sonnet ->
   Haiku）」 — a predetermined migration path instead of retention-driven selection.
   Called a drop because v2 says nothing about selection criteria. The article
   fuses both (L307, L443), which is what a failed contradiction resolution looks
   like; reclassifying makes the stale count 5 of 8.
6. **Left out**: the OKR section retitle 「TradeGPT 业务目标」 → 「Bybit AI 业务目标」
   (a real scope reframing, but all three carried numbers are byte-identical);
   TradFi, where v2 splits the capability across phases rather than contradicting
   the phase-2 completion; AI Marketplace timing (v2's 「5.30 AI Marketplace」 reads
   as a note under 收益路由, too ambiguous); 「Skills编辑后台（视业务需要而定）」, already
   conditional in v1; and the token-quota statistic, which v2's 「交易量提升Token额度」
   presupposes.
7. **Additive, not superseding** (the list that proves P9 belongs with the
   positives rather than the negative controls) — and V2 moved the three-pillar
   restructure (问答交互 / 智能投顾 / Agent能力, v2 L130/L133/L136) into this list, because
   it is a capability taxonomy on a different axis from v1's two-audience split rather
   than a replacement for it: a whole new 智能投顾 pillar with
   two detail tables plus 大模型交易员 and 资产配置助手 (L320–585); two new OKR rows
   (Question Count per User 2.6 → 6.5, per Day 96.5K → 241K, L89–117); an
   Agent-capability resourcing table (L197–243); ABF独立部署; a new 运营支持 section
   (L245–263); new knowledge-base sources (L151–154, L293); A2UI generative layout
   (L157, L308–310); periodic base-model updates (L182, L644); and the entire
   「# 会议纪要 20260513」 section (L656–691). New is not corrected.
8. **Out of scope**: the article also compiles
   `raw/meetings/2026-05-20-bybit-ai-toc--weekly.md` and
   `raw/docs/2026-05-29-客服top5场景对比.md`; the BabyAI merger phases,
   internal-controls workstream and top-5 CS scenarios come from those.

---

## P10 — 2025 engineering efficiency report

- `v1` = `.../raw/local/2026-03-05-2025-engineering-efficiency-report.md`
- `v2` = `.../raw/local/2026-03-06-2025-engineering-efficiency-report-v2.md`
- `article` = `data/kb-knowledge/wiki/decision/2025-engineering-efficiency-report-full-data-decisions.md`

The revision changes the **measurement basis**, and every headline figure moves
with it. Neither body carries an internal version or date marker — the only "v2"
strings are in the frontmatter `id` and `title` — so ordering here genuinely
depends on frontmatter date and filename, which makes P10 a clean test of A1's
signal.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P10-C1 / R1 | Excludes delivery cycles over 90 days (~6.3% of the population) → over 120 days, removing 668 items (3.6%) | v1 L235, L10 → v2 L378, L12, L263 | not stale — L17 carries v2's rule, and Decision 1 recommends 90 → 120 (L116) | to confirm |
| P10-C2 / R2 | The 2025 sample is one population of 17,294 → two datasets, 18,445 full and 17,777 filtered, with purposes split (full for throughput, filtered for efficiency) | v1 L12 → v2 L12, L377 | not stale but blended — L30 keeps 17,294 as a live dataset row and L162 says 「17,294–17,777 data points」 | to confirm — **V13 ruled 2026-08-16** — a third blended line belongs here, the same defect at the rate level: the H1→H2 throughput change is stated as 「−4 to −6%」 (L56, L58, restated at L301), a band whose endpoints are v2's −4.0% and v1's −6.0%. Not stale under V1's precedent, and not false either — the unpublished ≤120 series' −5.4% falls inside it — what it loses is which population each endpoint names |
| P10-C3 / R3 | Annual on-time rate ~36%, H1 41.8% → H2 28.5% (−13.3pp) → ~25%, 33.1% → 18.2% (−14.9pp) | v1 L26 → v2 L31 | not stale — L169 uses v2's value | to confirm |
| P10-C4 / R4 | The best month of 2025 reached only 45% on-time → January was best at 35%, falling monotonically to 14.3% in October | v1 L32 → v2 L36, L51, L204 | **stale** — L84 states the 45% claim in the sentence after v2's 35%→14.3%, self-inconsistently inside one paragraph (A16) | to confirm — **V11 ruled 2026-08-16** — row kept and scored on the article's unlabelled presentation, not on the string: the full-data co-source carries 45.0% as January's ≤90 rate (L89) but never as the year's best month, and it is dated 03-05 against v2's 03-06, so V19's criterion still lands on v2 |
| P10-C5 / R5 | Median end-to-end delivery cycle ~15 days (13.8 H1, 17.8 H2) → ~17 days (15.3, 19.8) — the pair sets v1's ≤90 population against the **unfiltered** one rather than against the ≤120 one v2 declares (V17) | v1 L24 → v2 L29; basis measured on v2 L51–62 against full L89–100 | not stale, replacement also missing — neither ~15 nor ~17 appears | to confirm — **V17 ruled 2026-08-17** — row stands, as a contradiction on level and not on trend: both versions state the same statistic over the same span (v1 L144, v2 L14–15) and their H1→H2 changes agree at +29.0% against +29.6%, while the level gap is re-basing — on the same twelve monthly cells the basis change alone accounts for all +2.0 days of H2 and +0.92 of H1's +1.5. Not to be cited as evidence of real slowdown, and the article does not cite it, running its H2 decline on 研发周期 5.0 → 8.5 instead |
| P10-C7 / R7 | Monthly throughput peaked at 1,907 in July, bottomed at 1,081 in October, a 43% swing → 2,036 and 1,182, on v2's 全量 basis, which is the one v2 designates for throughput (L377) | v1 L50, L53, L59 → v2 L135, L138, L176 | **stale** — L60 states both extremes, and its next sentence gives the monthly average as 1,537, which is v2's 全量 figure (18,445/12) rather than v1's 1,441. The sentence pair crosses bases, so it is not a faithful report of v1 | to confirm — **V6 ruled 2026-08-16** — row kept, replacement stays 全量; the swing and the peak/trough framing are *not* scored, since v2 asserts both. **V11 ruled 2026-08-16** — both figures also occur verbatim in the full-data co-source (L95, L98), as the 剔除后 column it declares to be v1's population (L14), so the test is the article's unlabelled presentation rather than either string; the co-source is dated 03-05 against v2's 03-06 and the row scores under V4 and V19 |
| P10-C8 / R8 | UserService's on-time rate fell 44.6% (Q1) → 22.0% (Q4) → 37.2% → 12.1% | v1 L101 → v2 L233 | **stale** — L282 | to confirm — **V14 ruled 2026-08-16** — cites confirmed, and the test belongs on the superseded side only: `37.2` is not unique to this row, since v2 states it for BigData's Q1 as well (L231) and the 2026 Q1 co-source states it twice more (L174, L176), while 「44.6」 / 「22.0」 stay v1-exclusive across all five sources per V11. The confound is the reverse of C4's and C7's — the same-day co-source reproduces **v2's** team rates as its year-ago baseline, not v1's — so this is the case's cleanest stale row under V19. Its `12.1` also has two hits in the full-data co-source (L116, L123) as a mean-vs-median gap in days, which is a different metric |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P10-D1 | The technical-requirement share of throughput fell from ~31% in Q1 to ~24% in Q4, squeezing technical improvement work | v1 L60; v2's monthly table has no business/technical split, and 技术需求占比 survives only as a 25–35% target (L317) | to confirm |
| P10-D2 | Recommends WIP limits per team to cut context switching | v1 L210 | to confirm |
| P10-D3 | Recommends an organizational-change buffer: a 2–4 week transition with lowered delivery expectations when a leader changes, plus a knowledge-transfer checklist | v1 L225 | to confirm |
| P10-D4 | Proposes a tech-lead quality tier of bug-association rate ≤0.3, rework ≤5%, and a per-capita monthly throughput baseline | v1 L163; v2's third tier is stale-requirement rate / estimation accuracy / P-1+P0 share (L322–326) | to confirm |
| P10-D5 | Mandates splitting any requirement whose delivery cycle exceeds 20 days, targeting ≤10 days | v1 L199; v2 manages size by tiering instead | to confirm |
| P10-D6 | The headline engineering-time metric is *average development duration*, ~9.2 days, +54.8% from 7.3 to 11.3 | v1 L25, restated at L73 and L177; `平均开发时长` returns 0 hits in v2, which reports development duration as a median instead. **Reclassified from contradiction C6 by V3, ruled 2026-08-15** — v2's headline 中位研发周期 (L28) is a different statistic over a different span (L14 defines 研发周期 as development *plus* test), so it cannot contradict a mean development duration | to confirm — **lost drop**: the article still carries v1's mean framing at L21, L50, L54 and L170. **V11 ruled 2026-08-16** confirms L170 as this row's residue against call 5, which had it protected, and records the string hazard: the article writes 「9.3 days (annual)」 where v1 writes 「~9.2 天」, a figure in no source, so an absence test on 「9.2」 reads the residue as gone. Test 「+54.8%」 (article L21, L50) instead, the one token of this family no other source carries — 「7.3 天」 and 「11.3 天」 both hit v2 (L210, L101) |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P10-K1 | The population is JIRA requirements with Actual End Date in 2025.01–2025.12 and status MainNet | v1 L10 (source/window/status part only — the >90-day clause in the same line is C1) → v2 L11 | to confirm |
| P10-K2 | On-time means Actual End Date ≤ Planned MainNet Date, with requirements lacking a planned date excluded | v1 L236 → v2 L381 | to confirm |
| P10-K3 | Team attribution uses the JIRA `dept_l2` field | v1 L237 → v2 L382 | to confirm |
| P10-K4 | August 2025 is the inflection point after which efficiency deteriorated without recovering | v1 L30 → v2 L194 | to confirm |
| P10-K5 | Three-point estimation should replace single-point estimation, with calibration workshops for the lowest on-time teams | v1 L194 → v2 L342 | to confirm |
| P10-K6 | DORA metrics (deployment frequency, change lead time, MTTR, change failure rate) should be added long-term | v1 L221 → v2 L363 | to confirm |

### Measurement-basis changes — why C1–C5, C7 and C8 are contradictions rather than new figures

1. **Exclusion rule >90 → >120 days** (v1 L10, L235 → v2 L12, L378). The root
   change; it invalidates every efficiency figure in v1. C1, C3, C5 and C8 are
   downstream, and so is drop D6. Note the exclusion rate also moves from 「约占 6.3%」 to 3.6% —
   roughly 1,151 items excluded against 668.
   **Ruling V17 corrects which re-basing C5 is downstream of.** v2's efficiency cycle series
   is not >120-filtered at all: its twelve monthly 中位整体周期 cells (L51–62) are the
   co-source's **全量** column (full L89–100) in all twelve months, and the 17,777 population
   v2 declares for efficiency (L12, L378) produces no figure in the document — so C5 compares
   ≤90 against **unfiltered**, and the threshold this item names is not what moved that row's
   figure. Two of the numbers around the threshold gain sources at the same time: the 91–120
   count is **483** (full L27, restated L194, and 1,151 − 668 independently), and the
   article's 「a further 167 requirements」 in that band (L34) is a December long-cycle cell
   (v2 L140) rather than a boundary count. C1 itself is unaffected, since it is tested on the
   rule, which the article carries at L17 and L116.
2. **One filtered population → a two-dataset design** with purposes split
   (v2 L377–378). Invalidates every throughput figure: annual 17,294, monthly
   average 1,441, H1 8,916 / H2 8,378 and −6.0% (v2: 9,412 / 9,033, −4.0%), and
   every monthly cell of v1's §2.1. C2 and C7 are downstream.
   **V6's ruling adds three things here**, since it decided which of v2's two columns
   those rows re-base onto. The split is by purpose and v2 states it:
   全量 「用于吞吐量统计和长周期分析」, 剔除版 「用于效率指标计算」 (L377–378).
   So a throughput row takes the 全量 figure and an efficiency row takes the 剔除后 one,
   and neither takes v1's ≤90 population, which v2 does not publish at any
   granularity. **Ruling V11 adds where it is published**: the declared co-source
   `raw/local/2026-03-05-…-report-full.md` prints v1's ≤90 series and the 全量 series as
   adjacent columns, monthly (L89–100) and quarterly (L111–120), and states that the
   first of them is v1's (L14). Its 剔除后 cells sum to 8,916 / 8,378 / 17,294 and its
   全量 cells to 9,412 / 9,033 / 18,445, so both of the pairs **V13** is about stand in
   one document — which is where a reader could reconcile the two bases, and is also why
   this case's staleness cannot be tested on the figures alone. The 全量 column reconciles
   exactly (twelve cells → 18,445, and 18,445/12 = 1,537, v2's stated monthly average)
   while the **剔除后 column does not**: twelve cells → 17,578 against a stated 17,777,
   and its 差异 cells → 867, which is 4.7% rather than the headline's 3.6% / 668 items.
   And the re-basing is arithmetically clean in the direction it should be: v1 ≤ 剔除后 ≤
   全量 holds in all twelve months, so no figure was corrected and none can contradict
   another as a count — what changed is which requirements are inside the number.
   **Ruling V13 confirms this item and supplies the half-year arithmetic** it was drafted
   without. The two rows are v1 L22 and v2 L26, and each reconciles with its own monthly
   table: v1's twelve 总交付 cells (L44–55) sum to 8,916 / 8,378 and v2's twelve 全量 cells
   to 9,412 / 9,033. It also sharpens the paragraph above — the co-source's 剔除后 column is
   v1's monthly table cell for cell in all twelve months (full L89–100 against v1 L44–55),
   so it carries v1's halves by identity rather than by arithmetic coincidence, while
   printing no half-year row of its own. Two things follow that C7's granularity does not
   show. **No third pair
   exists here** — v2 gives half-year throughput on 全量 only, and its 剔除后 halves,
   9,035 / 8,543, are both unpublished and unpublishable against its stated 17,777 — so the
   ≤120 repair V6 rejected has no counterpart at this level. And **the two change rates
   differ because the exclusions are H2-weighted**: ≤90 removes 496 items from H1 and 655
   from H2, ≤120 removes 377 and 490, so the decline flattens as the population widens,
   −6.03% (v1) → −5.45% (≤120) → −4.03% (全量). The 6% and the 4% are the same twelve
   months counted three ways, which is the shortest statement of what this item exists to
   say. The article states the derived rate as a band across both bases — 「−4 to −6%」 at
   L56 and L58, restated at L301 — which is recorded on C2's row beside L162's
   「17,294–17,777」 rather than as staleness.
   **Ruling V17 holds the split for throughput and breaks it for efficiency**, which
   corrects the sentence above that sends an efficiency row to the 剔除后 figure. v2 honours
   the purpose split where V6 tested it — C7's throughput extremes are 全量 — and abandons it
   in §2.1: the twelve 中位整体周期 cells (L51–62) are the co-source's 全量 column (full
   L89–100) in 12 of 12 months and its 剔除后 column in 2, the two months where those columns
   agree anyway. December proves the cells cannot be ≤120-filtered without any assumption
   about density, since v2's own §4.1 (L140) and the co-source (full L100) both put
   December's filtered count at 1,300, so the two filters remove the same 167 requirements
   and a ≤120 December median would have to be 18.5 rather than the 22.5 v2 prints. The lift
   is visible in a second column as well: v2's §4.1 长周期占比 (L129–140) is the co-source's
   占当月总数比 column (full L66–77) verbatim, a rate built on ≤90 counts standing beside v2's
   own ≤120 差异 cells, from which the same rates would read 3.8% / 4.9% / 5.1% and so on.
   This sits beside the reconciliation failure recorded above rather than explaining it, and
   it is what makes v2's filtered dataset declared-and-never-used: `17,777` occurs at L12 and
   L378 only, both times as a declaration.
3. **Overall cycle decomposed into 产品准备期 + 研发周期** (v2 L14–15, L379–380).
   The most consequential change, because it re-attributes the H2 decline: v1 says
   delivery cycle and development duration both worsened; v2 says the R&D cycle
   nearly doubled while product preparation stayed flat (5.3 → 5.5 days), making
   the bottleneck engineering execution and the product queue a separate
   long-tailed problem (mean 13.5 vs median 5.5, P90 43.5).
4. **Statistic and scope changed: mean 平均开发时长 → median 中位研发周期** (dev+test,
   from dev start). This is why **V3 reclassified C6 as drop D6** rather than a
   contradiction: two different statistics over two different spans cannot be
   incompatible. Three corrections belong here, the first of them V12's.
   *v2 does report means* — 均值产品准备期 13.5 天 (L82), 均值 13-20 天 (L38), 平均周期
   172 天 (L271) — so the claim only holds for development duration, where
   `平均开发时长` returns 0 hits.
   *v2 does report a same-scope development duration*, as a median: the monthly table
   carries a 中位开发时长 column (L49) and L67 states it rose from 1–3 days in H1 to 4–7
   in H2. That is compatible with v1's mean 7.3 → 11.3, exactly as v2's own
   「中位低、均值高」 note about the long tail (L38) would predict.
   *And no same-basis pair exists to re-cut the row onto*: v1 reports development
   duration only as a mean (L25, L73, L177) and never as a median, so there is nothing
   in v1 to compare against v2's median series. Reclassification was the only coherent
   option, not the lenient one. The consequence for FX7 is the practical argument:
   keeping C6 would ask A1 to correct 9.2 days when v2 offers no replacement value for
   it, so R6 was unscoreable.
5. **Team-level measure changed from delivery cycle to R&D cycle**, so v1's
   team-level cycle values have no counterpart while team-level on-time rates are
   restated and all move down. C8.
   **Ruling V17 removes 「on the new basis」 from that sentence**, because no declared basis
   change accounts for the on-time move in either direction. Filtering lifts an on-time rate
   by +0.4 to +1.6pp — the co-source measures it at 「按时率差异全年在 1-2 个百分点以内」 (full
   L105) and its 剔除后 column is v1's own series, 41.9% and 28.0% at Q1 and Q4 (full L120,
   v1 L75) — while v2's monthly rates sit 7.4 to 13.9pp **below** the 全量 column in all
   twelve months and match neither column in any of them, under an on-time definition K2
   records as unchanged (v1 L236 → v2 L381). So C3, C4 and C8 are the rows this case's basis story does *not*
   reach: whatever produced v2's on-time series, neither document declares it, and the drop
   cannot be read as an artifact of the population change the way C5's can.
6. **Target basis moved with the metric basis**: the 2026 on-time target drops from
   ≥55% (H2) to ≥40%, and the cycle target changes measure from median delivery
   cycle ≤12 days to median R&D cycle ≤5.0 days plus median product preparation
   ≤5.0 days.
7. **Unchanged basis elements**, hence K1–K3: data source, time window, status
   filter, on-time definition, team attribution.

### P10 open judgement calls

1. **C6 is the softest entry.** A mean of 9.2 days and a median R&D cycle of 6.0
   days are different statistics over different spans and could coexist without
   logical conflict. Scored as a contradiction because the rule counts "a metric
   redefined" and because v2 deliberately retires the mean. Demoting it to a drop
   removes the gate on the single most consequential change in the revision.
2. **Left out — the causal attribution of the Aug–Oct dip.** v1 attributes it to
   organizational restructuring and leader transitions (L82, L126–131); v2
   explains the same months with summer absence, July overdraft and the holiday
   calendar (L191–194) and asserts 「春节/国庆…并非 H2 效率下滑的主因」 (L39). Because
   v1 words it as 可能原因, this was judged neither contradiction nor drop and left
   out. The article states v1's framing as current (L44, L299–301), so ruling it a
   contradiction raises the stale count to 5 of 9.
3. **Left out as derivative**: monthly average throughput 1,441 → 1,537; H1→H2
   change −6.0% → −4.0%; the 2026 targets (article already carries v2's ≥40%);
   dashboard alert thresholds; and the large-requirement metric redefinition.
   **Ruling V11 adds one, and unlike the others the article is stale on it**: the Q4
   on-time rate, v1 28.0% (L75, L80) → v2 15% (L211), which article L84 states as v1's
   under a 「full-data view」 label that belongs to neither figure — the full report's
   全量 Q4 rate is 26.7% (L119) and its 剔除后 is v1's 28.0% (L120). It is left out as
   C3's own metric at a finer granularity — the ground the monthly-average throughput
   entry above is left out on; ruling it a contradiction raises the stale count to 4 of 9.
   **Ruling V13 corrects a second entry without moving it**: the article does carry the
   H1→H2 change, as the band 「−4 to −6%」 (L56, L58, L301) whose endpoints are v1's −6.0%
   and v2's −4.0%, so that derivative is left out as *blended* rather than as absent, and
   the line is recorded on C2 with L162's population blend.
4. **Team-level contradictions are a family; one is labelled.** **Rewritten by ruling
   V14, 2026-08-16.** Every team's Q1/Q4 on-time rate is restated downward — 16 of 16
   cells, the direction C1's widened filter predicts — while the roster change is
   **additive**: v2 has 10 rows to v1's 8, but they are v1's same eight teams in the same
   order (v1 L98–105) with **Trading Engine** and **Finance** inserted before Salesforce
   (v2 L230–239), both names absent from v1. As first written this read 「10 different
   ones」, which would have made the roster a re-attribution; being additive puts it under
   NG1, so what makes this a contradiction family is the restated rates alone.
   UserService was picked because v1 calls it 「恶化幅度全公司最大」 (L115) and the article
   repeats v1's figures verbatim (L282).
   - **The article is not uniformly stale on the family**, which is why one labelled row
     is the right treatment rather than a token for a uniform pattern. Of the eight
     shared teams only five carry an on-time rate: three are v1's — Fiat Channel
     「55% → 32%」 (L277), UserService 44.6 → 22.0 (L282), Compliance 36% → 15.7% (L283) —
     and **two are v2's**, Asset 11.2–7.9 (L281) and Salesforce 4.8% (L284). BigData, SBU
     Business and ToB carry none, and v2's two additions both arrive with v2's own
     figures (Trading Engine's 28 days at L286, credited to 「the 2025 v2 analysis」;
     Finance at L285). So a second entry is available but a third is not: the ceiling is
     **two** further rows, and taking Compliance would read 45 contradictions with 28 of
     40 stale.
   - **Compliance is the cleaner second entry, not Fiat Channel.** The article gives Fiat
     v1's *prose rounding* (v1 L114 「按时率从 55% 降至 32%」) rather than its table cells,
     so an absence test on the table strings reads the residue as gone — and both are
     ambiguous besides. `54.8` names two metrics inside v1, the `+54.8%` development-duration
     increase (L25) and Fiat's Q1 rate (L98), and the article's only two hits are the
     former (L21, L50), so the test reads a false positive on **D6's** material. `31.5`
     names three: Fiat's Q4 rate (v1 L98), February's 技术需求占比 (v1 L45, **D1's**
     metric) and a 121–180-day bucket share in the full-data co-source (L28). Compliance's L283 carries v1's table value 15.7% itself, 1 hit in v1 and 0 in
     v2 and in all three co-sources. Its hazard is on the replacement side instead:
     17.2% (v2 L235) collides with v1's own Compliance Q1 交付周期 17.2天 (v1 L103).
   - **The confound runs the other way here than on C4 and C7.** The 2026 Q1 co-source
     reproduces v2's 2025 team Q1 rates as its year-ago baseline column (L173 45.3,
     L174 37.2, L176 37.2, L178 17.2, L180 9.0), so the *replacement* side is co-asserted
     by a same-day source while the *superseded* side is v1's alone — the reverse of what
     call 5 found for the throughput rows, and it makes these the case's cleanest stale
     rows under V19's criterion. The two apparent co-source hits on the superseded side
     are different metrics: the full report's `31.5%` (L28) and its `12.1` (L116, L123, a
     mean-vs-median gap in days, not UserService's replacement rate).
   - **Each bullet blends 2025 with Q1 2026.** L282 pairs v1's 2025 rates with the Q1
     report's 33.5 days / 19.1%, L283 pairs them with its 7.8% — so the stale material is
     the 2025 clause of a sentence whose 2026 clause is current, V11's presentation-level
     defect one level finer. The article's roster is **11**, since Group Risk Control
     (L280) comes from that co-source (its L145, L165): the roster is the union of the
     compile set, so the additions were absorbed rather than mishandled.
5. **Five sources, only two of them this pair — and provenance is the wrong test.**
   **Rewritten by ruling V11, 2026-08-16.** The article also compiles
   `2026-03-05-…-report-full.md`, `2026-03-06-2026-engineering-team-goals.md` and
   `2026-03-06-2026-q1-engineering-efficiency-report.md`. The list first written here
   sorted article figures by which document contains them, and it was wrong in both
   directions: 1,907 (full L95), 1,081 (L98) and 45.0% (L89) are all in the full-data
   report, so "v1-exclusive" excludes almost nothing, while 「9.3 days」 is in no source
   at all. What replaces it is **basis labelling**, the test A9 applied to P7's L57 and
   L192 — a figure is protected where the article states the basis it belongs to, and
   scoreable where it is stated bare as a fact about 2025.
   - **Protected**: the dataset table (L27–31) and the Q4 full-vs-filtered comparison
     (L260–263), both of which name their columns. 37.0 and 24.9 occur only in the full
     report (L114–115, restated L123), but its two Q4 medians do not — 21.5 also stands in
     v2 L60 and 18.5 in v1 L74 — so even here the labelling and not the figure is what
     protects the lines. 「984 | 5.3%」 is full-report-only, and it sits in a row that does
     not add up — a defect inherited rather than made here:
     18,445 − 17,294 = 1,151, which is v1's own 「约占 6.3%」
     (L235), where 984 is the full report's long-cycle count (its L66–77 table sums to
     exactly 984) and 5.3% is 984/18,445.
   - **Scoreable**: 「9.3 days (annual)」 (L170), v1's retired mean and D6's fourth
     residue — either 9.2 mis-keyed or the unweighted mean of v1's own 7.3 / 11.3 — and
     「28% (full-data view)」 (L84), whose label is wrong (the full-data Q4 rate is 26.7%,
     full L119; 28.0% is the ≤90 figure, full L120 and v1 L75/L80) and which v2 restates
     as 15% (L211).
   - **Not decidable by provenance, so scored on presentation**: L60's 1,907 / 1,081 and
     L84's 45%. The full report holds all three values and claims none of them — it never
     calls 1,907 a peak, 1,081 a trough or 45.0% the year's best month. Those framings are
     v1's sentences (L59, L32) and the article states them unlabelled. All three readings
     also hold only on the ≤90 column, which is the sharper reason they are v1's: 1,907 and
     1,081 are that column's extremes and 45.0% its maximum, while the 全量 column's best
     month is 43.4% (L89) — so 「best single month reached only 45%」 is not a statement the
     full-data view supports at all. C4 and C7 therefore
     score, per V4 and V19: the co-source is dated 03-05 against v2's 03-06, so the newest
     source speaking to either claim is still v2.

   The fingerprint claim needed correcting too. **+54.8%** is the one token no other source
   carries (v1 L25, article L21 and L50; 0 hits in the other four, though within v1 the `+`
   and `%` are needed to separate it from Fiat Channel's 54.8% at L98), and on the team rows
   C8's 「44.6」 / 「22.0」 (v1 L101, article L282). The H1 7.3 / H2 11.3 pair is not
   exclusive: v2 L210 states a Q3 研发周期 of 「7.3 天」 and v2 L101 a Compliance figure of
   「11.3 天」, so both halves collide inside the chain's own newer version — and `grep -F
   "7.3"` additionally catches 「27.3天」 at v1 L104–105 and 27.3% at v2 L56. This is the
   P7-C2 string hazard, on the one item drafted as this case's clean test.

---

## Note: the recorded similarity figures are distorted

test-set.md's `sim` column is computed by `py/scripts/select_cases.py`'s
`diffstat`, which calls `difflib.SequenceMatcher(None, earlier, later)` over body
lines and leaves **`autojunk` at its default of `True`**. For sequences of 200
elements or more that heuristic discards any line occurring in more than 1% of
the second sequence. In markup-heavy documents that means blank lines, table
delimiters and Lark attribute lines. The recorded values reproduce exactly with
`autojunk=True`, so this is the metric the corpus was stratified with, inherited
from the original throwaway script rather than introduced by FX1's rebuild.

| Case | Recorded | `autojunk=False` | Identical body lines |
|---|---|---|---|
| P8 | 0.079 | **0.928** | 1544 of 1709 |
| P5 | 0.217 | 0.645 | 3833 of 6397 |
| P2 | 0.448 | 0.485 | 759 of 2042 |
| P9 | 0.168 | 0.333 | 161 of 685 |
| P3 | 0.096 | 0.253 | 270 of 1155 |

`stratum()` calls anything below `_REWRITE_SIMILARITY = 0.55` a rewrite.
Corrected, P8 (0.928) and P5 (0.645) are not rewrites, so the strata table and the
"123 of 682 articles at 18%" figure rest on a distorted metric. No label here is
invalidated, because labels are drafted from the documents, not from the
similarity, and the 18 chains already selected do not change. Captain's call,
recorded as an open item rather than fixed silently.

## Note: a verification hazard in the drafting method

The recipe `diff <(sed -n '/^---$/,/^---$/!p' A) …` silently suppresses body
content between the third and fourth standalone `---`, so on a document with
horizontal rules it hides whole sections — in P4's case the entire §5 module
table, which makes the v3→v4 body diff look empty. 20 of the 38 fixture documents
have more than two standalone `---`, affecting P3, P4, P5, P8 and P10 (P2, P7 and
P9 are clean).

Checked rather than assumed: all 17 `superseded-drop` claims for P3, P5 and P10
were re-verified by direct negative grep on their distinguishing phrases, and
every one returned 0 hits in the later version. That 17 is the current count
(5 + 6 + 6) rather than the count at the pass, which was 15: two of the rows arrived
afterwards — P10-D6 reclassified from C6 by V3, P5-D6 promoted by V8 — and each was
grepped when it was ruled, so the guarantee still covers every drop.
P4's drafting used full-file
diffs, and P8's confirmed each absence by grep. So no drop list is corrupted, but
anyone extending this label set should not reuse that `sed` recipe.

## Note: within-version ambiguity

Every contradiction row is phrased "the earlier version asserts X, the later asserts
incompatible Y". Verification found five places where a single version asserts **both
X and something close to not-X**, and ruling V22 measured a sixth, so that phrasing is
stronger than the documents support. This is a different problem from the co-source
confound: there the *article* had a second source, here the *fixture document itself* is
internally inconsistent.

| Where | The document says both |
|---|---|
| **P4-C3** (v1) | **Measured by V18 as a heading against its own section body, not two adjacent lines**: L1761's heading names the monthly `uta_liq_trans_log_202605`, and across the 774 lines of the section it opens (L1761–2534) that name never occurs again, while the body specifies `translog_realtime` from its first line (L1763, with the data source at L1765, the storage strategy at L1767 and a 53-row schema at L1771). L1763 is also control K4's line, which is why R3 has no string of its own |
| **P4-C8** (v4) | The §5 table names 差额账户 as counterparty (L5698), while L788, L798, L808, L5683 and L5864 still call it 系统户 — including a cell of the same table, two rows up. None is in a pending-decision block |
| **P4-C7** (v4) | DDL says `service_action` (L4192); prose at L4182 still says `action`. Already documented in open call 2 |
| **P4-C9** (v2, v3 and v4 alike) | The §5 cell assigns post-rollback disposal — v2 to the order book and a PM takeover account (L5455), v3 and v4 to TRW (L5705 / L5706) — while all three carry the same 待决策 item 5: 「采用类似保险池twap甩卖机制进行盘口甩卖」 and 「期权仓位如何处置： 1.等交割 2.通过移仓给到PM接管户」 (v2 L5561–5562 = v4 L5832–5833). Documented in open call 3 when drafted; **V22 measured that the block is identical across the three versions**, which is the one entry here that both versions of the pair share, and why the article's L425–426 score nothing |
| **P2** (the 04-14 file) | Asserts vLLM onboarding at both 「进度100%」 (L399, in its `# 2026-05-04` section) and 「进度90%」 (L1358, in its `# 2026-04-17` section) — the artefact of a rolling document updated in place |
| **P6** (v1) | Its own version: frontmatter `title` (L5) and the H1 (L10) say 「通用网关设计方案 v1.5」 while the body marker at L13 says `> 版本: v1.6`. Governs no row — P6 is adjudicated, not drafted — but it is the only instance where the ambiguity is about the *version* rather than about a claim, and P6's success is credited to that marker ([test-set.md](test-set.md#three-adjudicated-cases)) |

Two of these were documented when drafted (C7's and C9's). The rest are all ruled: **V5** kept
P4-C8 with its residual recorded, **V10** corrected P2's evidence table
and call 2, whose vLLM reading this row had right all along, **V22** kept P4-C9 on the one
residue the ambiguity does not touch, and **V18** kept P4-C3 and moved its caveat onto the
replacement; P6's changes no scored row and is recorded rather than queued.

Two consequences for scoring. First, a row whose earlier version also asserts the
replacement is weaker evidence than the table implies, even when the *measured token*
is clean — P4-C3's is clean four times over, and **V18 located the weakness precisely**: it
is not the stale verdict that suffers but the replacement test, because the string that would
prove the replacement was carried is one the earlier version already publishes. Second, and more
practically for FX5: **an extractor reading the later version alone can legitimately
emit the older claim**, because the later version still makes it. P4-C8 is the sharp
case — grading the article stale at L421–424 would fail a pipeline for repeating what
v4 itself still says in five places. So a stale verdict needs the later version to be
*unambiguous*, not merely to contain the correction somewhere.

**P4-C9 is where V22 applied that test at claim level**, and it cuts a row's evidence
rather than the row: v4 is ambiguous about the disposal *mechanism* — its 待决策 block
lists the order book and the PM account as options — and unambiguous about who owns the
disposal, so the row scores on the second and its two mechanism residues are withdrawn.
The block being byte-identical to v2's is what makes that safe: it is not the later
version conceding the earlier one, it is material neither version's cell speaks for.

That is a stricter test than "the earlier value appears", and it points the same way
as V19, which is why V19's ruled form reads against **the newest source that speaks to
the item** — what that source actually asserts, in full, rather than the one line the
label happened to cite.

## Note: co-source assertion confounds the staleness column

The `Article today` column asks whether a superseded claim survives in the article.
It answers a weaker question than it appears to, because these articles merge more
sources than the chain under test. Where a **co-source** independently asserts the
same claim and was never superseded, an article stating it may be reporting that
source faithfully rather than mishandling this pair. P10's judgement call 5 caught
this for one case; it generalises — and **ruling V11 found call 5's own version of it
back to front**, since the numbers it protected were mostly not the co-sourced ones.

| Case | Article sources | This chain | Co-sources | Co-sources also staged in the fixture |
|---|---|---|---|---|
| P3 | 2 | 2 | 0 | 0 |
| P4 | 5 | 4 | 1 | 0 |
| P5 | 16 | 2 | 14 | 1 — `raw/docs/2026-04-23-bybit-ai-toc-整体立项.md`, which is P9's v1 |
| P7 | 5 | 2 | 3 | 1 — `raw/docs/2026-04-14-infra-双周会-2026_h1.md`, which is P2's v1 |
| P8 | 2 | 2 | 0 | 0 |
| P9 | 4 | 2 | 2 | 0 |
| P10 | 5 | 2 | 3 | 0 |

Two consequences, and they are not the same size.

**For the drafted `Article today` column and the published 69% headline, the confound is
severe.** Only P3 and P8 are compiled from the chain alone — and V1 struck P8's four
contradictions, so of the five cases that still gate after V21, only P3 does. P7 is the worst case:
its co-source asserts v1's *entire* 0430 column, so 7 of its 8 staleness
observations have a second possible cause. **V4 ruled 2026-08-16 that this bounds the
causal claim, not the score** — a value the article states undated is still contradicted
by the newest source in the same compile set, whichever document supplied it, so P7's
rows stay scoreable and only "this pair's ordering was lost" narrows to C8.

**P10 turns out to be the same shape, measured by ruling V11**: its `2026-03-05`
co-source is v1's own companion volume, printing v1's ≤90 series beside the 全量 series
and declaring the first to be v1's (L14), so 2 of P10's 3 staleness observations — C4 and
C7 — have a second possible cause, and C8's 「44.6」 / 「22.0」 is the only evidence in the
case that no other source carries. The disposition is V4's, since the co-source is a day
older than the chain head: the rows score and the causal claim narrows to C8. The
consequence peculiar to P10 is that its tests cannot be strings at all — every figure C4
and C7 score appears verbatim in that co-source, so what is scored is the article stating
them with no basis attached. **V13 bounds that claim to the scored rows rather than
weakening it**: the co-source prints no half-year figures, so v1's 8,916 / 8,378 and v2's
9,412 / 9,033 stay string-exclusive to their own documents — but they belong to
measurement-basis item 2, which gates nothing, so no *scored* test in P10 can be a string.

**Ruling V17 found the co-source standing on the other side of the pair as well**, which is
the sharpest form this confound takes anywhere in the set. v2's twelve monthly cycle
medians are that companion volume's 全量 column verbatim (v2 L51–62 against full L89–100),
so the 03-05 document supplies **both** sides of C5 — v1's ≤90 series in one column and v2's
published efficiency series in the next — and prints their difference as a filtering effect,
0–2 days in H1 widening to 3–4 in Q4 (full L102–104). It changes no count here, because C5
is not stale and nothing in the article states either side of it. What it costs is the
premise that a chain's two versions are two independent measurements: on this row they are
one document's two columns, and the fixture cannot tell A1 otherwise.

**Ruling V14 found the confound running the other way on P10's third stale row**, which is
worth stating because it is the only place in the set where a co-source helps. C8's
superseded pair 「44.6」 / 「22.0」 is v1's alone, while its *replacement* is co-asserted: the
`2026-03-06` Q1 report reproduces v2's 2025 team Q1 rates as its year-ago baseline column
(L173 45.3, L174 37.2, L176 37.2, L178 17.2, L180 9.0), the same relation the `2026-03-05`
full report has to v1's monthly table. So on the team family two of five sources assert the
new value and only the oldest asserts the old one, which is the shape the column was
supposed to measure. Two hits that look like exceptions are different metrics: the full
report's `31.5%` is a 121–180-day bucket share (L28), not Fiat Channel's Q4 rate, and its
`12.1` is a mean-vs-median gap in days (L116, L123), not UserService's replacement.

**Ruling V22 measured P4's co-source and found it silent on the row it was ruling**, which
is the first entry in this table cleared at row level rather than case level: `处置`,
`甩卖`, `保险池`, `TRW`, `系统户`, `差额` and `TR讨论` are 0 fixed-string hits in
`raw/docs/2026-04-20-a23-异常交易回滚-仓位字段回滚分析.md`, and its one 接管户 hit is the
hedging engine's 接管价格 field, which the article carries as a schema row (L266) rather
than as disposal content. So P4-C9's surviving residue is chain-exclusive and its causal
claim needs no narrowing — the confound reaches P4 as a case, not this row.

P5's article merges 16 sources, which is
the strongest reason not to read its 0-of-5 pass as evidence that the pipeline
handles supersession — it may simply have been told the newer values repeatedly.

**For FX5's actual scoring the confound is bounded**, because spec.md's FX4 already
declares the existing `wiki/` an existence proof rather than a baseline and re-runs
the compile over the staged fixture. Only P5 and P7 carry a co-source into that run,
one each, and in both cases the co-source is another case's v1 — itself superseded
within the fixture, so ordering applies to it too.

So the published pre-A1 figure is motivation, not measurement, and should stop being
quoted as though the two were interchangeable. The criterion this note asked for is now
ruled: **V19** restates staleness against *the newest source in the compile set that
speaks to the item*, per claim rather than per document. It buys less here than this
note assumed, though. The wording only clears an observation where a co-source is
**newer** than the chain head, and of the two co-sources that reach the fixture run
neither is — P7's is dated `2026-04-14` against a chain head of `2026-05-14`, P10's
`2026-03-05` against `2026-03-06`. P5's is the only one that is newer, and P5 is the
case that already scores 0. So the confound above still has to be handled case by
case, which is what V4 is for on P7, and the published figure keeps its caveat rather than
being repaired by a definition. FX7's gate is unaffected, since it counts corrections
carried, not staleness.

P5's 0-of-5 has a second and larger problem that this note missed, filed as **V20** and
**ruled 2026-08-16**: its two versions share a frontmatter date, so the payload's
oldest-to-newest claim rests on a path tie-break that renders `…清单-v3.md` first and
thereby states that **v1** is the newest source. Read against the order the compile set
actually presents, P5 is 5 of 5 stale. The 16-source confound above is the weaker of the
two reasons not to read that pass as evidence. V20's ruling withdraws the claim rather
than correcting it, so neither reading gates: P5's staleness is reported apart for good.
And the shared date turns out to be an error rather than a fact about the corpus — the
bodies are six days apart, which is **V21**, **ruled 2026-08-16** as an A2 body-date case
with the fixture left verbatim. One consequence for this note: the published rate is now
27 of 39 over five cases, four of which carry a co-source — so the confound described
here reaches every case behind the headline figure but P3, and, measured row by row, not
P4-C9 either.
