# FX5 scoring: the pre-A1 baseline arm

Scored 2026-08-18 against the finished FX4 baseline arm in `/tmp/kaas-baseline` (27
articles, 17.99 USD, code at `bd8252e`). Labels are the confirmed set in
[labels.md](labels.md); columns and their definitions are
[test-set.md's Scoring table](test-set.md#scoring); the criterion is
[spec.md FX5](spec.md).

The gating column reads **24 of 40 (60%)** on the five cases that gate, against
the 28 of 40 (70%) the label pass published for the historical corpus articles.
So the arm is better
than the artifact it replaces, and the reason is one nothing on this branch predicted: this
writer already performs supersession some of the time, unprompted, on 18 of 45 contradiction
rows.

Two findings changed the criterion before any row was scored, both in
[What FX5 assumed and what the arm did](#what-fx5-assumed-and-what-the-arm-did): a case
usually resolves to two articles rather than one, and one article that carries a whole chain
is invisible to source-based resolution.

## Results

Union rule: an item is stale if **any** article carrying the chain states it as
current, a correction lands if any article carries it, a control is present if any
article carries it. Per-article figures are kept because they differ sharply.

### The gating column — Staleness over `superseded-contradiction`

| Case | stale (union) | rows | per article | historical | band |
|---|---|---|---|---|---|
| P3 | **8** | 9 | 5 / 5 | 7 | 7–8 |
| P4 | **7** | 10 | 7 (one article) | 9 | 7 |
| P7 | **5** | 8 | 4 / 4 | 6 | 4–6 |
| P9 | **4** | 6 | 4 / 3 | 3 | 3–4 |
| P10 | **0** | 7 | 0 / 0 | 3 | 0 |
| **total** | **24** | **40** | — | 28 | **21–25** |

**24 of 40 (60%)**, quoted with its composition attached as V21 requires: five gating
cases, P8 out on V1, P5 out on V21. The band is the four items in
[the queue](#ruling-queue-seven-open-items) that move this column — V30, V31 and V32 take it
down a row each, V33 puts one back — and the point estimate is the drafted position on each.
The other three move other columns: V28 moves Trail, V34 moves Collateral and Correction
landed, and V29 moves a per-article figure without touching the union.

P5, reported apart under V21: **0 of 5**, and not by luck — see
[P5 recovered its own order](#p5-recovered-its-own-order-from-body-text).

### Every other column

| Column | Result | Basis |
|---|---|---|
| Correction landed | **34 of 45** | P3 8/9 · P4 3/10 · P5 5/5 · P7 6/8 · P9 5/6 · P10 7/7 |
| Trail | **18 of 45** | P3 4/9 · P4 1/10 · P5 4/5 · P7 6/8 · P9 1/6 · P10 2/7 |
| Staleness (drop) | **37 of 41** | P3 4/5 · P4 3/4 · P5 6/6 · P8 7/7 · P9 8/8 · P10 9/11 |
| Collateral | **40 of 42** present | P10-K2 missing in both articles; P7-K2 counted missing on a split conjunction (target survives, "still 0%" does not); everything else carried |
| False positive | **0 of 4** | N1–N4 all clean |
| Double count | **0 of 4** | U1–U4 all clean, no marker between byte-identical documents |
| Size | **not measurable** | no per-stage `wiki/` snapshot exists; see [Size](#size-is-unmeasurable-on-both-arms-as-scripted) |

P1 (drop, does not gate): **stale**, four occurrences of the ~140-user figure across
its two articles, correction landed, no trail. Confound-free — both articles declare
the chain and nothing else, so unlike the historical article's eleven sources there is
nothing to clear. Worse than the historical article in one respect: the project
article states the stale figure one line above a sentence dating the new step to April
17, the date its source dropped it.

P6 (no-regression check): **pass** in both articles, on stronger evidence than the
historical article — both reproduce v2's four-way problem split, which is unreachable
from v1, and 「重量級」 is 0 hits in a file that quotes v2's tables in verbatim Chinese.
One regression: neither names the v1.5–v1.7 range the historical article cited, so the
framing passes and the trail is gone.

P2 scores nothing (withdrawn, V10). Its article in this arm is
`wiki/project/infra-team-okr-h1-2026.md`.

## What FX5 assumed and what the arm did

### A case resolves to two articles, not one

FX5 says a case resolves "by its `sources` set" to "the article whose `sources:` holds
the whole chain". In this arm **10 of the 18 chains resolve to two articles**, both
carrying the whole chain, because the classifier split most chains across `decision/`
and `project/`. One-to-one: P2, P4, P10, N2, N3, U2–U4. Two articles: P1, P3, P5, P6,
P7, P8, P9, N1, N4, U1.

The union rule is not a formality. On P3 the two articles are stale on **almost
disjoint rows** — each reads 5 of 9 alone, the union reads 8 of 9, and only C1 and C9
fail in both. On P8 the decision article reads 5 of 7 drops and the tracker 7 of 7.
A single-article rule would have produced a number several rows off, with the offset
depending on an arbitrary pick, and the pick could differ between arms.

Two cases where the split does something the columns do not capture:

- **The corrections can land in the article FX5 excludes.** P4's
  `wiki/reference/uta-trading-rollback-database-schema.md` declares only v2/v3/v4 — no
  v1, so it does not hold the chain and is out of scope — and it is clean exactly where
  the scored article is stale, carrying C9's `TRW` replacement that the scored article
  lacks. The pattern across P4 is not "latest loses" but **the oldest source wins
  wherever it is the only one filed in that section**.
- **The two articles can disagree with each other, both in the present tense.** P9's
  pair states phases 1 and 2 completing mid-June and mid-August (v1) in one article and
  end of June and end of August (v2) in the other. P8's pair states AI Gateway coverage
  as 36 of 40 (90%) and 33 of 40 (82.5%). No FX5 column fires on a KB that holds two
  live values for one fact.

### One article carrying a whole chain is invisible to resolution

`wiki/decision/engineering-efficiency-2025-improvement-decisions.md` (517 lines, the
larger of P10's two) names both chain documents in `sources:` but opens with the
writer's own preamble prose above the delimiter, so `parse_sources` returns nothing and
it drops out of source-based resolution silently. It was resolved by hand and scored.

This is not a marginal inclusion: **it is the article carrying P10's trails.** Its
preamble announces "I'll integrate the new data as a parallel/complementary analysis
rather than replacing the existing data", and the body implements that as symmetric
version-labelled sections — `### Annual Core Metrics — Report v1 (>90-day exclusion)`
against `### Annual Core Metrics — Report v2 (>120-day exclusion)`, and nine more such
pairs. All seven of its contradiction rows are protected under V11's basis rule. Had
FX4's frontmatter defect been allowed to exclude it, P10 would have scored on the other
article alone and this behaviour would not appear in the record at all.

### The frozen article needs no by-name exclusion

spec.md excludes `wiki/decision/infra-team-h1-2026-decisions.md` "by name and by
reason". The `sources` rule already excludes it: it carries v1 of P2's chain and v1 of
N2's chain, so no full chain is contained. The by-name clause is stronger than
necessary. The asymmetry question spec.md raises (whether the A1 arm writes the article
the baseline could not) does not affect FX5 resolution either way; it still affects
FX7's article pairing.

### V9's exclusion is inert on this fixture

Every case's co-sources were swept for every residue string rather than assumed:

- **P5** — the co-sources V9 rests on (the 03-11 capability list, the 03-12
  retained-interface list, the hardening plan) **are not in the fixture at all**. Both
  articles declare exactly the two chain files. So P5's drops are unexcluded here, and
  that is most of why they read 6 of 6 against the historical 3 of 6.
- **P8, P9** — the labels record these articles as declaring only the chain; in this arm
  the decision article declares six sources and the tracker four. All five distinct
  co-sources return **zero hits** on every residue probe, so no row is excluded, but
  the confound exists where the labels said it could not. This check has to run per arm.
- **P4, P7, P10, P3, P1, P6** — swept, zero hits, or no co-source declared.

Net: the exclusion clause changed no verdict anywhere in the arm.

### Size is unmeasurable on both arms as scripted

FX5 measures Size "against the pre-run article". Neither the baseline driver nor
`/tmp/kaas-fx4-a1arm.sh` snapshots `wiki/` between stages, so no pre-run article exists
for any stage after the first. Absolute bytes are recorded (755,700 across 27 articles)
and growth is not. Two lines in the A1 script (`cp -a $KB/wiki $LOGS/stage$stage-wiki`
after each compile, about 750 KB per stage) would make the column available for that
arm; it stays unavailable for the baseline either way, so the arms would not be
comparable on it.

### The write history is clean, and it was checked rather than assumed

Rebuilt from the drivers' `[merge] <article> ← <source>` lines rather than from the
compile JSON's `revised` map, which is not a write log — `stage2-recover-attempt1`
reports `compiled: 10` and `revised: 0`. Every case's later version reached both of its
articles; most of the stage-2 merges landed in the recovery pass after the endpoint
outage, not in `stage2-compile`. So **no case's score is confounded by a lost write**,
and the only article frozen at v1 content is the excluded one.

Spend verified independently: the twelve `[LLM Cost]` lines sum to 17.9896 USD, of which
8.81 is the 65 write operations.

## What the writer actually does about supersession

FX5 was drafted expecting Trail to be 0 before A1 and the question to be whether A1
clears staleness. The arm shows the pre-A1 writer already using **four distinct
strategies**, chosen per chain and sometimes per line:

1. **Explicit supersession.** P3: "The earlier three-level model … has been superseded
   by this two-stage approach in v0.2.0", and a heading reading
   `### Decision 4: No Init Command (Superseded)`. P10: "Note: An earlier version of
   this report applied a 90-day exclusion threshold and reported 17,294 requirements."
2. **Version-labelled parallel presentation.** P5's table columns are headed
   `v3 document` and `Earlier document`; P10's second article pairs every v1 section
   with a v2 section, basis named in the heading. Both score 0 stale with the old
   values fully present.
3. **Snapshot dating.** P7 preserved the source's weekly columns as separately stamped
   blocks (`### Q2 Status as of 20260430` / `as of 20260514`) without merging them. The
   old values survive stamped, which is why 5 of 8 stale is *better* than the
   historical 6 of 8 while every superseded figure is still on the page.
4. **Coequal presentation — conflict seen, ordering refused.** P4, five instances:
   "The material records both versions without resolving the discrepancy", "the article
   retains both". This is neither latest-wins nor current-plus-trail, and the D1 option
   list has no name for it.

**The capability is unreliable rather than absent**, and P9 shows the grain at which it
fails. v2 states all three phase deadlines on one legend line,
「一期规划（6月末完成）| 二期规划（8月末完成）| 三期规划（10月末完成）」. The article performed
the v1-versus-v2 comparison for **one** of those three fields, emitted a correct
supersession note for it ("the May 11 document is the later source"), and silently kept
v1's values for the other two. A writer that notices one third of one line is the case
for making the ordering signal explicit (A1) rather than for buying a separate
reporting arm (A2).

### P5 recovered its own order from body text

The payload told the writer that v1 was the newest source — the same-day tie broke on
the path, and `…-v3.md` sorts before `…清单.md`. The articles say the opposite: the
decision article calls v1 "the earlier document" and treats v3's 301 endpoints as
primary. Anchored independently: v1's body states 「全部 8 个 modules」 and
「生成时间：2026-03-13」, v3's states 「全部 11 个 modules」 and 「生成时间：2026-03-19」.

So P5's 0 of 5 is not the luck V20 called it — the writer read the body and overrode the
payload. It remains right to keep P5 out of the gate, for a different reason than the
one recorded: the case measures whether body text can rescue a wrong frontmatter date,
which is A2's question.

The wrong-order defect still surfaced, structurally rather than verbally: that article's
spine is v1 (v1's numbering, v1's section layout, v1's `🔴` legend at 24 occurrences
against v3's 0, stopping at endpoint #280), it asserts that endpoints beyond #280 "are
not enumerated in the source material available here" — false, v3 enumerates all 301 —
and then lists v3's #278–#299 anyway, 190 lines later. Blending the two numbering
schemes produced live ordinal collisions: #278, #279 and #280 each name two different
endpoints.

## Failure modes the label set has no column for

Recorded because each was found in the arm and none of them scores:

| Mode | Instance |
|---|---|
| Range-spanning | P7's decision article resolves conflicting snapshots into ranges: "45%–50% QPS (daily QPS 35K–40K/s, peak 61K–230K/s)", "87.5%–90% (35–36 of 40 scenarios)", "164–179 applications remaining (the material records both figures)" |
| Cross-article disagreement | P9's phase dates, P8's gateway coverage — two live values for one fact in one KB |
| Synthetic merge | P9's tracker puts v2's dates on the roadmap headings and v1's deleted task lists underneath, a version existing in neither source |
| Intra-article self-contradiction | P3's decision article gives `/cht-tools:distill` at L127 and `/cht-knowledge:distill` at L289; says "each agent maps to one of the six scan dimensions" three lines after listing eight agents |
| Supersession actively denied | P4-C7: "The DDL also records a `service_action` field (**distinct from the `action` field noted elsewhere**)". A trail mechanism must overwrite this sentence, not append to it |
| Fabricated convention | P4's article shards `uta_position_mode_log_{yyyyMM}` by month; no version of the TRD shards that table and v1 does not name it |
| Placeholder read as data | `zero-trust-security-initiative.md` L28/L35 reads the source's template placeholder 「比如已过时间约70%，完成约40%」 as actual progress |
| Untranslated blocks | Large Chinese blocks survive inside otherwise-English articles (P1's and P6's pairs). Incidentally this is what makes Chinese-string probes meaningful against this arm |

## Ruling queue: seven open items

Same convention as [labels.md's queue](labels.md#the-queue--22-items-all-settled): each
item is Captain's call, and **the default if ignored is the drafted position**, which is
what the numbers above already use. "Moves" states the effect of ruling *against* the
drafted position.

| # | Location | The call | Drafted | Moves | What settles it |
|---|---|---|---|---|---|
| **V28** | test-set.md Scoring table (Trail row); spec.md FX5 | What counts as a Trail? Three behaviours observed: explicit "superseded by" wording; a version- or basis-labelled presentation; an as-of date stamp with the newer value adjacent. Trail is the column that separates the D1 options, so it needs one definition, not a per-case call | The rubric as given to the judges: an as-of stamp counts | Trail 18 of 45 → 7–11 on an explicit-wording reading (7 if version-labelled columns are excluded too, 11 if they count); P7 6 of 8 → 0 of 8. Does not move Staleness | A written criterion in test-set.md's Scoring table naming which of the three tiers satisfies the column, confirmed by re-reading P7's eight rows against it |
| **V29** | P10, `engineering-efficiency-2025-improvement-decisions.md` L29/L41/L81 | Does a basis-naming *section heading* protect prose inside the section, or does V11's protection reach only table-grain devices (column names, labelled comparisons)? | Section headings protect | P10's second article 0 → 2 of 7 stale. **The published total does not move** — the other article holds none of these figures, so the union stays 0 of 7 | A ruling on V11's grain, plus re-reading the four affected lines (C4 at L39, C3 at L49, D1, D9) |
| **V30** | P9-C3, `bybit-ai-initiatives-architecture-decisions.md` L264/L266/L294 | Does bibliographic attribution to the superseded version, with no correction offered, count as "attributed to a past plan"? The article states 一期（6月中完成）only inside "The April 23 document records a resolved roadmap" — but uses that idiom for live content too, and calls the roadmap "active" | Stale — attribution is that article's ordinary citation idiom, not a marker | P9 4 → 3 of 6; **total 24 → 23 of 40** | Ruling, then re-reading P9-C3, C4, C6 and D8 in that article, which all turn on the same idiom |
| **V31** | P3-C7, labels.md L595 (P3 replacement table) | Does C7 cover the agent count only, or the scan-dimension count with it? The two halves split in this arm: the 6-parallel-agent half is trailed, the 「6 个维度」 half is live at L148–155 | Both halves, per the label's own wording ("no 6-agent **or 6-dimension** claim") | P3 8 → 7 of 9; **total 24 → 23 of 40** | A scope ruling on C7's text in labels.md |
| **V32** | P7-C4, `cloud-cost-optimization-h1-2026-decisions.md` L442/L447/L449 | Does an undated sentence wedged between two dated blocks inherit their date? The article carries no replacement for this row at all | Stale — it carries no stamp of its own | P7 5 → 4 of 8; **total 24 → 23 of 40** | Ruling on date inheritance, applied to P7-C4 and re-checked against P7-C5's undated pending-core rows |
| **V33** | P7-C6, `cloud-cost-optimization-h1-2026.md` L928 | Does a correctly dated figure sitting in an **Open Action Items** table count as stated-as-current? The item asserts a 1w-core reduction is still open where v2 reports the gap at 7C | Not stale — the figure is stamped | P7 5 → 6 of 8; **total 24 → 25 of 40** | Ruling on whether an open-action framing overrides a date stamp |
| **V34** | P8-K1, P7-K2, P10-K3, P9-K5/K6, P5-R1, P4-C3 | Do compound claims score on every conjunct or on the main proposition? Eight rows split: P8-K1's ≥50% cost reduction survives and its "Go 原生 LLM 路由服务" descriptor does not; P7-K2's target survives and its "still 0%" half does not; P5-R1's scope landed and the numeral 11 did not | Main proposition | Collateral 40 of 42 → as low as 34; Correction landed 34 of 45 → 32 | One stated rule in test-set.md covering controls, drops and replacements alike, then a re-read of the eight rows |

Two further grain questions are recorded and **move no published total**, so they are not
queued: P3-C3 (artifact `index.json` versus mechanism "a maintained global index" — the
other article is unambiguously stale either way) and P4-C3's correction grain (whether a
live `translog_realtime` section counts as R3 landing; it would take Correction landed
from 34 to 35 of 45).

## What this measurement changed in other documents

All landed with this file, so nothing here is a pending edit:

- **spec.md** — FX4's article-shape prediction was corrected first (commit 0df60c8); FX5 now
  carries the union rule, both resolution findings, the automatic exclusion and Size's
  unavailability; and NG3 no longer says Trail is expected 0 on P4, since the baseline reads
  1 of 10 there.
- **test-set.md** — the status head reports 24 of 40 beside the published 28 of 40, the V9 note
  records that the clause is inert on this fixture, and the Scoring table's Trail and Size rows
  now say what is open and what is unmeasurable rather than implying both are settled.
- **labels.md** — its closed queue now points here, because V31 is a scope question about
  P3-C7's own wording.
- **`.superpowers/sdd/progress.md`** — the 08-18 entry described the timeout exclusion as
  symmetric; corrected to match spec.md, which says the symmetry cannot be assumed until the
  A1 arm runs.

## What this scoring cannot decide

The union rule answers what the KB tells a reader. It does not answer which article a
consumer would actually read, and this arm gives that question teeth: the same chain
produces a `decision/` article and a `project/` article that can state different values
for the same fact. If the product answer is that one article is canonical, the gating
number is not 24 of 40 — it is whichever of the two per-article columns applies, which
on P3 is 5 of 9 rather than 8 of 9. That is a product decision, not a scoring one, and
it is out of A1's scope.

FX7 compares this arm against the A1 arm on the same column. Nothing here is a verdict
on A1.
