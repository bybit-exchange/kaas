# FX7 verdict: A1 does not clear the positives, so A2 is not optional

Written 2026-08-19, after V35–V38 were ruled. The two arms are
[scoring.md](scoring.md) (pre-A1 baseline, 24 of 40, code at `bd8252e`) and
[scoring-a1.md](scoring-a1.md) (the A1 arm, 19 of 40, code at `033517c`). The criterion is
[spec.md FX7](spec.md); the gate it enforces is
[test-set.md's](test-set.md#scoring) — "Path A is worth shipping first if and only if it
clears the positives without tripping the negatives."

**A1 improves the gating column under every reading of every ruling and clears it under
none.** The negatives hold at 0. So the condition D2 attached to A2 — bought only if A1
fails the positives — is met, and A2 moves from optional to required.

## The gate

FX7 asks one question and deliberately excludes most of the columns from it:

> A1 is judged on Staleness over `superseded-contradiction` across FX4's baseline and
> the post-A1 run. Clearing those positives without tripping N1–N4 is what makes A2
> optional rather than assumed. Staleness (drop) moving is reported as a finding about
> A2's RP1 arm and does not enter the verdict either way.

So three numbers decide it, and the rest of the record is context:

| | baseline | A1 arm | verdict input |
|---|---|---|---|
| Staleness, gating (lower is better) | 24 of 40 (60%) | **19 of 40 (47.5%)** | improved by 5 rows, **not cleared** |
| False positives, N1–N4 | 0 of 4 | **0 of 4** | negatives not tripped |
| Double counts, U1–U4 | 0 of 4 | **0 of 4** | negatives not tripped |

Nineteen labelled contradictions still state a superseded value as current in the articles
A1 produced. That is the whole verdict on the gate: an article that says the 2026 phase 3
deadline is end of September, in the present tense, in a KB whose newest source says end of
October, is the failure this feature exists to remove, and there are nineteen of them.

The other columns are reported because they are what the arm bought, and none of them is
the gate:

| Column | baseline | A1 arm | in the verdict? |
|---|---|---|---|
| Correction landed | 34 of 45 | **38 of 45** | no — D2's column, not FX7's |
| Trail (V28 directional) | 7 of 45 | **5 of 45** | no — NG2 predicted 0 and A1 emits no markers |
| Staleness (drop) | 37 of 41 | **29 of 41** | excluded by FX7 in terms; an RP1 finding |
| Collateral present | 40 of 42 | **41 of 42** | no — a regression guard, and it did not regress |
| Spend | 17.9896 USD | **14.3873 USD** | no |
| Stages | stage 2 took three passes, 2 of 18 residual | **4 of 4 first attempt, residual empty** | no |

## The verdict does not depend on any of the four rulings

V36 was carried on this branch as the ruling that decided P4's direction, P4 being the set's
strongest failure case. It decides P4's characterisation. It does not decide the verdict:

| Reading | P3 | P4 | P7 | P9 | P10 | total |
|---|---|---|---|---|---|---|
| **As ruled** (V35 no, V36 union, V37 not stale) | 5 | 9 | 0 | 5 | 0 | **19 of 40** |
| Every ruling at its most favourable to A1 (V36 newest-half) | 5 | 3 | 0 | 0 | 0 | **8 of 40** |
| Every ruling at its harshest (V35 yes, V37 stale) | 6 | 9 | 2 | 5 | 0 | **22 of 40** |
| baseline, for comparison | 8 | 7 | 5 | 4 | 0 | **24 of 40** |

The band is 8–22 of 40 against a baseline of 24. **A1 is better on every reading and clean
on none**, so the pass/fail answer is invariant and the rulings move only the size of the
improvement. The favourable end of the band is also the writer-owned rate: the next section
derives it from the rows instead of from a ruling and lands on the same 8.

*(The 8 of 40 figure corrects a counterfactual this branch carried in four documents as
13 of 40. That number applied V36's alternative to P4 and not to P9, though P9 is split by
version in exactly the same way and its newest-half article reads 0 of 6. The ruled figure,
19 of 40, was never affected.)*

## Where the nineteen rows are, and which of them A1 owns

The arm split two chains across articles by version, so a case can be stale in one article
and clean in the other. Splitting the total on that line is what the verdict needs, because
one side is the write path A1 changed and the other is classification, which
[NG6](spec.md#non-goals) puts upstream of this feature:

| | rows | baseline stale | A1 stale | owner |
|---|---|---|---|---|
| Cases whose articles saw the whole chain (P3, P7, P10) | 24 | 13 (54%) | **5 (21%)** | the writer — A1's own change |
| Cases A1 split by version (P4, P9) | 16 | 11 (69%) | **14 (88%)** | the classifier |
| **total** | **40** | **24** | **19** | |

Read at the row grain rather than the case grain the split is sharper still:

- **8 of the 19 stale rows are in an article that had both values in front of it** — P3's
  five, and P4's newest-half article's three (C6 `set_time` in nanoseconds, C7 `action` for
  `service_action`, C9 disposal for TRW).
- **11 of the 19 exist only because a second article carries the older half of a chain** —
  six in P4's v1+v2 article, five in P9's v1-only article. Neither article's sources say the
  design moved. No write prompt can fix a row whose article never saw the newer value.

So A1's write-path change took the rows it could reach from 13 of 24 to 5 of 24, and the
column then gave 3 of those 5 rows back plus 11 more through a classification behaviour A1
does not control and NG6 excludes. **The writer-owned rate is 8 of 40 (20%) against the
baseline's 24 of 40 (60%)** — the number the second row of the sensitivity table arrives at
from the other direction.

Eight rows is what A1 bought, and it is not zero. Those eight sit in articles that held both
values and stated the older one as current anyway.

## What the arm did instead of clearing the column

A1 shifted the failure mode. The baseline stated superseded values as current and unlabelled.
This arm states them **with their source attached** — 「V1 (2026-03-05)」 against
「V2 (2026-03-06)」, "In earlier design this was … in the v0.2.0 implementation …",
"As of 20260430 … As of 20260514 …". Ordering reaches the page on almost every case. What
the writer does with it is attribute each value to its version rather than assert that one
value is dead.

That behaviour has two consequences and they point opposite ways:

1. **It clears the gating column wherever it is applied** — P7 0 of 8, P10 0 of 7, P5 0 of
   5 — because a named basis makes the two figures different claims rather than one
   contradictory one. That is the column's own reasoning, ruled twice (V28, V29).
2. **It earns no Trail**, because attribution is not replacement. So A1's three best cases
   read `(Staleness 0, Trail 0)`, which is **coequal presentation** — the shape
   [D1 rejects in terms](design-options.md#d1--the-body-states-the-current-claim-plus-a-superseded-trail)
   ("replaced by the pair, not kept alongside it: an article that states both as current is
   the bug this feature exists to fix") and the shape D1's option list did not name until
   V28's ruling added it.

[NG2](spec.md#non-goals) anticipated part of this: it says A1's best output is "correct
current state with no trail, which is *latest-wins*, the option D1 rejected", and that a
clean A1 score must not be read as D1 delivered. What the arm actually produced is not
latest-wins. Latest-wins leaves the reader one value. Coequal presentation leaves them two,
each correctly sourced, with nothing saying which is in force — so against D1 it is worse
than the shape NG2 warned about, on the same rows the column scores clean.

**So the 5-row improvement is partly an artefact of what the column measures**, and how much
of it cannot be established now. If a basis-labelled parallel presentation counted as stale,
A1's total would rise to roughly 36 of 40 and the baseline's to roughly 34: the arms become
indistinguishable and the advantage disappears. That estimate is read off the two scoring
records and not off the articles — P7's eight rows are all dated snapshots, P10's seven clean
rows are all inside version-labelled sections, P5's five sit in one `Version Comparison`
table, and P3 has two named-basis rows among its four clean ones.

**It cannot be settled.** The A1 arm's articles survive in `~/kaas-arms/a1` and could be
re-read; the baseline's
[no longer exist](scoring.md#the-scored-arm-no-longer-exists-on-disk). A criterion that can
only be applied to one side of a comparison cannot be applied to the comparison, so it is
recorded as a bound on the figure rather than raised as a ruling. It is also the case for A2's
arm: that is where both sides can be read against one rubric.

## What A2 has to answer, taken from the failure map

The arm's failures concentrate. Each item below is a location A2 has to reach; none of them
prescribes a mechanism:

1. **The three places the arm stops labelling.** Every stale row in P10 is in a Key
   Decisions section or an Action Items table. Four of P3's five are Key Decisions plus a
   Related line. P4's three writer-owned survivors are DDL cells copied verbatim from a v2
   table into a table headed v3. A replace primitive that reaches prose and not these three
   surfaces leaves most of the remaining failure standing.
2. **Self-contradiction inside one article, which has no column.** P3-C1, C4, C5 and C6 each
   state the correct value in one place and the superseded one in another, both in the
   present tense, with no ordering between them. The baseline's dominant failure was stating
   the old value; this arm's is stating both. `Staleness` records it as one stale row and
   cannot see that the correct value is also there.
3. **Version-split chains, which A1 does not own and A2 does not either as specified.**
   Eleven of the nineteen rows are here, and in these two cases a trail is *impossible* —
   16 of the 45 contradiction rows sit in chains no single article sees both halves of. A2's
   replace primitive cannot retract a value its article never received. Either A2's scope
   grows to cover how a version chain is routed, or the gating column cannot reach zero
   whatever A2 ships.
4. **False differentiation, also without a column.** U1, U3 and U4 attribute shared content
   to one of two byte-identical documents, so a reader is told one copy added material both
   contain. Nothing is double counted and nothing is stale. It is the mirror image of the
   failure U1–U4 were written to catch, and it is a direct product of an arm that attributes
   claims by source date — which is the behaviour A2 builds on.
5. **RP1's baseline moved, and in the cheaper direction.** Drops went 37 → 29 of 41 without
   any drop-specific mechanism, which is what the column was carried for
   ([test-set.md](test-set.md#scoring)). Two of the eight are false progress rather than
   real: P9-D4 and P9-D6 went the other way, from clean on the baseline to lost here,
   because the v1-only article restates them and v1 is its only source.

## What this verdict cannot do

**A baseline row cannot be reopened.** `/tmp` was cleared on 2026-08-19 and took all 27
baseline articles with it, so scoring.md is the baseline side of this comparison in full and
by itself. Every published column, per-case figure and row citation is there. A disagreement
about a baseline row has no artefact to appeal to, and four of that arm's seven rulings are
closed permanently for the same reason.

**The two arms differ in article count** — 20 against 27 — so Size is an absolute record on
each and not a comparison, and any per-article rate carries that denominator difference.

**Nothing here judges D1.** A1 emits no markers by design (NG1, NG2). A1 failing to produce
trails is not evidence about whether trails are the right output; it is what the spec said
would happen.

**Nothing here judges the classifier.** Version-splitting decided 11 of the 19 rows and is
outside this feature (NG6). It is now the largest single contributor to the gating column
and it has no owner on this branch.

## Consequence

- **A2 is required, not optional.** D2's condition is met on the measurement FX7 was written
  to take.
- **A1 ships as it stands.** It is a strict prerequisite for A2 — the replace primitive has
  to reason over exactly the dates and per-source blocks A1 introduces — and it improved
  four columns while regressing none, at 3.6 USD less than the baseline, in four clean
  stages, with both FX4 write defects absent.
- **A2's rubric needs work before its arm runs, not after.** Coequal presentation with a
  named basis currently scores clean on the gating column. If A2 ships D1's trail and is
  scored on the same column against the same rubric, its result will not be distinguishable
  from A1's on the rows that matter most. The place to fix that is
  [test-set.md's Scoring table](test-set.md#scoring), before spending on a second arm.
