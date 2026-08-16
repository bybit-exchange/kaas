# FX3 labels — the supersession test set's reference standard

Status: **drafted, awaiting confirmation.** Every item below is `to confirm`. The
two blocking rulings are **settled** (2026-08-15): P2 leaves the positives and is
kept as the documented wrong-date counter-case, and P7's measurement-time reading
is accepted. Neither is still a question; see [P2](#p2--infra-biweekly-review-withdrawn-counter-case)
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
because it asked an empirical question rather than for a decision. **Four are now
ruled** — V1, V2, V3 and V12, the ones that moved the totals — leaving **14 open**. See [the verification pass](#independent-verification-pass-2026-08-15). Note
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
| P3 | 8 | 5 | 6 | 6 of 8 | to confirm |
| P4 | 10 | 4 | 6 | **9 of 10** | to confirm — worst case in the set |
| P5 | 5 | 5 | 6 | **0 of 5**, reported apart from the gate | **V20 ruled 2026-08-16** — the payload stated the chain backwards off a path tie-break, which is fixed by withdrawing the ordering claim, not by correcting it; so P5 gains no basis to be scored on this column and its exclusion is now permanent, pending **V21** on v3's frontmatter date. Its 5 contradictions still count in the set totals, see [P5](#p5--bybit-trading-skill-api-inventory) |
| P7 | 8 | 0 | 6 | 6 of 8 | to confirm — reading accepted; **V4 ruled 2026-08-16**, all 8 rows stay scoreable and only the causal claim narrows to C8, see [P7](#p7--2026-h1-cost-progress-tracking) |
| P8 | 0 | 6 | 6 | — | **V1 ruled 2026-08-15** — its four contradictions were de-specifications and are struck; P8 keeps its drops and controls and no longer gates, see [P8](#p8--ai-project-portfolio-overview) |
| P9 | 6 | 5 | 6 | 3 of 6 | to confirm — **V2 ruled 2026-08-15**, C1 struck as preserved by v2, see [P9](#p9--bybit-ai-toc-project-initiation) |
| P10 | 7 | 6 | 6 | 3 of 7 | to confirm — **V3 ruled 2026-08-15**, C6 reclassified as drop D6, see [P10](#p10--2025-engineering-efficiency-report) |
| ~~P2~~ | ~~8~~ | ~~6~~ | ~~6~~ | ~~7 of 8~~ | **withdrawn from the positives** — counter-case, scores nothing, see [P2](#p2--infra-biweekly-review-withdrawn-counter-case) |

Totals across the seven scoring cases: **44 contradictions, 31 drops, 42
controls**, and 27 of the 44 contradictions are stated as current in the articles
today — a 61% pre-A1 staleness rate, measured over compiled output rather than argued
from P1 alone. Read over the cases that actually gate it is **27 of 39, 69%**: P5's five
contradictions are in the 44, but P5 is reported apart from the staleness column and V20
made that permanent, so the denominator has to say which reading it is (V21). Plus one
non-scored `chained-supersession` entry (P4) as evidence for NG3's trail format, and P2's
withdrawn label (8/6/6) retained below as counter-case evidence.

- **P5 reads 0 of 5 stale** and leaks its ordering six ways inside the body, so it
  belongs with P6 as an accidental-signal case rather than as evidence about A1. That
  reading also depends on the true version order, which the payload does not carry:
  the two versions share a frontmatter date and the tie-break states the chain
  backwards. **V20 is ruled** — the payload stops claiming an order it cannot support,
  which keeps P5 out of the gating column rather than putting it in — and the wrong
  date underneath is **V21**.
- P4 is the sharpest probe at 9 of 10 stale. **P8 now contributes no
  contradictions**: V1 ruled its four to be de-specifications of one column rename,
  so it carries drops and controls only.
- Drops are not a rounding error: 31 of them, and on P8 five of six are stated as
  current. That is the baseline A2's RP1 arm would be measured against.
- The gating set is therefore **six drafted cases plus P6**, which succeeds today.
  P1, P2 and now P8 are evidence rather than tests: P1 because it is a drop, P2
  because its date lies, P8 because what its later version changed was the grain of
  an attribution rather than its content. P8 still exercises the signal — it is the
  one case with no accidental ordering cue at all — but on the drop and control
  columns, not on the gating one.

**These totals have V1, V2, V3, V4, V5, V12 and V19 applied; 12 rulings are still open.**
Three of those would move a number further — V7, V8 and V9. The four rulings taken
since have all left the totals where they were. V19 changed what the staleness column
measures and raised **V20**: P5's two versions share a date, so the payload orders them
backwards and P5's 0-of-5 pass cannot be scored on that column until a tie-break rule
lands. V4 left P7 with all 8 rows, narrowing only the claim that its staleness
demonstrates *this pair's* ordering being lost, which C8 alone supports. V5 kept P4-C8
at **9 of 10 stale**, since the residual `系统户` prose describes a different level than
the counterparty role the row scores. V6 kept P10-C7 on the replacement it was drafted
with: v2 assigns 全量 to throughput and 剔除后 to efficiency (L377–378), and the ≤120
column the item preferred does not reconcile with v2's own total, so the row re-bases to
2,036 / 1,182 and not to 1,971 / 1,129. The details are in
[the verification pass](#independent-verification-pass-2026-08-15).

---

## Independent verification pass, 2026-08-15

Every row of the seven scoring cases was re-derived from the sources in a fresh
context, one per case, with no access to the drafting reasoning — only the row, the
named fixture versions and the article. Each was asked to open the cited lines rather
than accept a plausible row, and to flag disagreements only. P2 was excluded because
it now gates nothing; its evidence was checked separately by hand (queue item **V10**).

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

### The queue — 20 items: 8 settled, 12 still needing a ruling

Ordered by how much they move the measurement. Owner is the Captain for all of them
except **V16**, which asked whether a document was read rather than how a row should
score and is therefore settled below by evidence; none of the others is an agent's
call, because each either reclassifies a row or changes what a number means. **V1, V2,
V3, V4, V5, V12 and V19 are ruled** — the three that moved the totals, the one that
governs the same item as V3, the one that redefined the staleness column, the one that
settled P7's confound, and the one that kept P4-C8 — and each row records the decision.
**V20 was raised by ruling V19** and is the only item added after the pass. Of the 12
still open, three would move a scored number: V7 forces P3 to 8/5 or 9/4, V8 would take
P5's drops to 6, and V9 adds two measured losses to the drop arm. V20 moves no total
either, but it decides whether P5 can be scored on the gating column at all. The rest
change what a number means or correct the reasoning under it.

| # | Item | Location | Finding | Recommendation | If accepted |
|---|---|---|---|---|---|
| **V1** | P8-C1–C4 | P8 → contradictions table | **RULED 2026-08-15: accepted.** The four rows are not incompatible, they are **de-specifications**. v2 keeps `@lucas.wan` over the whole infra category (v2 L19) and glosses him as `Lucas (架构)` (v2 L271), so `团队 = 架构` generalises `Owner = Lucas Wan` rather than contradicting it. Two further findings decided it: the article itself writes both sides (「Lucas Wan / Architecture team」 at L188 and L192), so it is not asserting the superseded value under any staleness rule; and v2 keeps person names in the `团队` column (L154, L291, L311) and still names 「Victor / Lucas」 at L681, so nothing was actually re-attributed away. The draft's own call 3 excludes 「Q2 W6」→「Q2」 for exactly this shape | Struck; moved to the [re-attribution list](#re-attribution-not-contradiction--the-four-rows-v1-struck) | Applied: **P8 → 0 contradictions**, out of the gating set. 7 gating cases → 6; totals 46/30/42 with 29 stale |
| **V2** | P9-C1 | P9 → contradictions table | **RULED 2026-08-15: accepted.** v2 preserves *both* of v1's end-state parts near item-for-item (v2 L175–178 for the self-hosted-OpenClaw half, L182–184 for the in-house TradeGPT agent) — the second is already scored as control **K1**, so scoring C1 had the same material both preserved and superseded. Checked at ruling time: the article's two-component framing (L21, L23–24) is what v2 asserts too, so the row's `stale` verdict was wrong on the facts as well as on the classification. The three pillars are a capability taxonomy on a different axis, and the draft's own call 7 files that material under "additive, not superseding" | Struck; substance folded into K1's evidence rather than a new control, and the pillars added to call 7's additive list | Applied: P9 → 6 contradictions, **3 of 6 stale**; totals 45/30/42 with 28 stale |
| **V3** | P10-C6 | P10 → contradictions table | **RULED 2026-08-15: accepted.** Compares v1's **mean** development duration (L25) against v2's **median** 研发周期 (L28), which v2 L14 defines as development *plus* test — a different statistic over a different span. Checked at ruling time: v2 does carry a same-scope median development duration (the 中位开发时长 column at L49, 1–3 → 4–7 days at L67), and it is compatible with v1's mean 7.3 → 11.3, just as v2's own 「中位低、均值高」 note (L38) predicts; and **no same-basis pair exists to re-cut the row onto**, because v1 reports development duration only as a mean (L25, L73, L177). Keeping it would ask A1 to correct 9.2 days against no replacement value, so R6 was unscoreable | Reclassified as `superseded-drop` **D6**, recorded as a lost drop, with the basis change written into [measurement-basis item 4](#measurement-basis-changes--why-c1c5-c7-and-c8-are-contradictions-rather-than-new-figures) | Applied: P10 → 7 contradictions, **3 stale**; drops → 6; totals 44/31/42 with 27 stale |
| **V4** | P7 case-level | P7 → preamble and headline | **RULED 2026-08-16: the finding is accepted, the scoring restriction is rejected.** The premise is verified exactly — `raw/docs/2026-04-14-infra-双周会-2026_h1.md` (P2's v1) asserts v1's entire 0430 column, confirmed with fixed-string counts at L898 (`40.95`, `24.57`), L904 (`13.3`), L911 (`3000C`), L916 (`合同已提交`), L919 (`117.3`), L921 (`3300`, `83.1`) and L925/L928 (`7197`, `17054`). But "score only C8" rests on attributing staleness to a document *pair*, and supersession is a property of the **compile set**: the set holds 04-14 asserting the old value and v2 asserting otherwise, so a writer emitting it undated mishandled ordering whichever document it read it from — and that co-source is itself superseded inside the fixture by P2's v2. Under V19's ruled criterion all six stale rows stand, because the newest source speaking to each is v2 (2026-05-14). For FX7 the confound cancels outright, since the co-source sits in both arms | All 8 rows stay scoreable. What is restricted is the **causal** claim: only C8 supports "this pair's ordering was lost", so the headline no longer reads 6 of 8 as evidence of ordering loss. Two repairs came with the ruling — C8's test is tightened to the full phrase `识别—分析—跟踪—复盘`, since the bare token `闭环` has 7 hits in the 双周会 on a different loop (L823), and C6 gains an ambiguity note because the newest source in the set may assert its old value | Applied: no total moved. P7 stays a gating case at 6 of 8 stale |
| **V5** | P4-C8 | P4 → contradictions table | **RULED 2026-08-16: the residual is recorded, the row stands.** The five `系统户` mentions are verified (v4 L788, L798, L808, L5683, L5864, none in a 待决策 block) but they are weaker than C7's residual, not stronger, because they describe a different level: three are transType accounting directions in §3.3 engine, one is hedged with 可以考虑, and one is a worked example whose next lines say 「差额公司出」, sitting under a `light-yellow` open question. Against that, the replacement is the cleanest in the chain — v2 L5447–5453 and v3 L5697–5703 are the same table row replaced cell for cell across subject, role and detail 1. Two line-level corrections came out of ruling it: **the pair is v2→v3, not v2→v4** (`差额账户` first appears in v3; v4 shifts the two lines by one with no content change), which independently confirms what **V15** argues for X1; and **`允许透支` is not part of the change**, since it already stands in v2's cell | Row kept and scored on the table row, the same basis call 2 uses for C7. Residual written up as [call 8](#p4-open-judgement-calls); both line corrections applied to the row | Applied: no total moved. P4 stays **9 of 10 stale** |
| **V6** | P10-C7 | P10 → contradictions table | **RULED 2026-08-16: the basis mismatch is real, the repair is rejected, and the row stands exactly as drafted.** The premise holds — v1's 1,907 and 1,081 (L50, L53) are counted after 「剔除交付周期 >90 天」 (L10, L235) while v2's 2,036 and 1,182 are 全量 (L135, L138). What the item missed is that there are **three populations, not two**, so its own repair does not fix what it names: v2's 剔除后 column is filtered at >120 days (L12, L378), so 1,971 / 1,129 is no more v1's basis than 2,036 / 1,182 is. Three checks then settled which of v2's two columns the row belongs on, and all three point away from the item's preference. First, **v2 assigns its datasets by purpose**: 全量 「用于吞吐量统计和长周期分析」 and 剔除版 「用于效率指标计算」 (L377–378). C7 is a throughput claim, so v2's own designated basis for it is 全量. Second, the ≤120 column **does not reconcile with v2's own headline**: its twelve cells sum to 17,578 against a stated 17,777, and its 差异 cells sum to 867 (4.7% of 全量) against the headline's 668 (3.6%) — while the 全量 column sums to exactly 18,445, v2's stated total. The recommended target is the one column in the document that does not add up. Third, **nothing was revised, only re-based**: across all twelve months v1 ≤ v2's ≤120 ≤ v2's 全量 holds without exception (July +64 then +65, October +48 then +53, December +0 then +167), and v1's twelve cells sum to 17,294, its own stated total. Two figures cannot be incompatible as counts of nested populations, which is why this row scores as a re-basing of the same metric rather than a corrected error. **The residual the item wanted to score instead is not v1-only**, which is the reason its second half fails: v2 marks 7月 as 「全年峰值」 (L135) and 10月 as 「国庆+全年最低」 (L138, restated L176) and gives the peak its own section 4.4 (L179), and the swing is 43.3% on v1's basis, 41.9% on 全量 and 42.7% on ≤120 — so both the framing and the ~43% are preserved by v2, and scoring staleness on them would charge A1 for material v2 still asserts | Row kept unchanged, replacement stays **2,036 / 1,182**, and the basis change is recorded in [measurement-basis item 2](#measurement-basis-changes--why-c1c5-c7-and-c8-are-contradictions-rather-than-new-figures) rather than in the row. The stale verdict stands and gains the sharper evidence ruling it produced: article L60 states 1,907 and 1,081 and its next sentence gives the 2025 monthly average as 「approximately 1,537 items」 — and 1,537 is 18,445/12, v2's 全量 average, where v1's own average is 1,441 (17,294/12). The article is therefore not faithfully reporting v1; it splices v1's ≤90 extremes onto v2's 全量 average inside two sentences, and on the replacement the sentence becomes one population (2,036 / 1,182 / 1,537) | Applied: no total moved. P10 stays 7C / 6D / 6K with 3 stale, and totals stay 44/31/42 with 27 stale. **V13 is the same shape and this ruling decides it**: v1's H1 8,916 / H2 8,378 sum to 17,294 (≤90) and v2's 9,412 / 9,033 sum to 18,445 (全量), so its drafted disposition — row unaffected, reasoning corrected — is what this ruling confirms |
| **V7** | P3-D3 vs call 2 | P3 → drops table and open call 2 | Both rest on the same v1 lines (L635–638). Promoting call 2 to a 9th contradiction would score that evidence twice — once gating, once as a drop | Rule explicitly either/or, and record that promoting it strikes D3 | P3 either 8/5 or 9/4, never 9/5 |
| **V8** | P5 `universal-transfer` | P5 → open call 3 | An unlisted abridgement loses a whole distinct assertion — 「资金可转到他人控制的子账户」, 0 hits in v3 — the same shape used to promote D4 and D5, and the article carries it at L394 | Promote to a drop or decline explicitly | P5 drops 5 → 6 |
| **V9** | P5-D4/D5 | P5 → drops table | Both dropped clauses are in the article (L427, L402), so both are **lost** drops. The label does not say so | Record the article residue on both rows | P5's drop arm gains two measured losses |
| **V10** | P2 evidence | P2 → evidence table and open call 2 | Verified by hand. Row 3 of the evidence table is half wrong: in the section both files date 04-17 they **agree** on vLLM at 90% (v1 L1358, v2 L405); the 100% is exclusive to the 04-14 file's 05-04 section (L399). So judgement call 2 is wrong that C7 and C8 are the two unambiguous rows — v1 asserts both values, which is the ambiguity it attributes only to C1–C6. C8 does hold (56% at both L783 and L1781 against 20% at v2 L824) | Correct the row and the call. The inversion conclusion **stands** and is better supported: the rolling file updated its own 04-17 section in place | P2's revival recipe rests on C8 alone |
| **V11** | P10 call 5 | P10 → open call 5 | The provenance list is wrong in both directions: 1,907/1,081 **and** 45% are in the non-superseded full-data report (L95, L98, L89), so they are not v1-exclusive; but 「9.3 days」 is in **no** source, so L170 is most likely v1's 9.2 mis-transcribed and belongs on the scoreable side | Rewrite the list | Changes which article lines may be scored |
| **V12** | P10 item 4 | P10 → measurement-basis item 4 | **RULED 2026-08-15: accepted**, applied together with V3 since both govern the same item. "v2 reports no mean anywhere" is false — v2 L38 「均值 13-20 天」, L82 「均值产品准备期 13.5 天」, L271 「平均周期 172 天」 | Restricted to development duration, where `平均开发时长` returns 0 hits in v2 | Applied; item 4 rewritten, and it is what carried V3 |
| **V13** | P10 item 2 | P10 → measurement-basis item 2 | Crosses bases: v1's 8,916/8,378 are ≤90-filtered, v2's 9,412/9,033 are full-population. Throughput was re-based, not revised. **Decided in substance by V6 2026-08-16** and left open only to be recorded on its turn: the two pairs sum to v1's 17,294 and v2's 18,445, so this is C7's shape at half-year granularity, and V6's ruling already wrote the basis change into item 2 | Say so; the wording V6 added covers it, so this item is a confirmation rather than a rewrite | Row unaffected; reasoning corrected |
| **V14** | P10 call 4 | P10 → open call 4 | v2's roster is v1's same eight teams **plus** Trading Engine and Finance, not "10 different ones" | Correct | Strengthens the call |
| **V15** | P4-X1 | P4 → chained-supersession entry | The trail's third step lands at **v3**, not v4 — 差额账户/TRW first appear at v3 L5697–5705, and v3→v4 changes nothing there. And v1→v2 is a reframing, so a strict reading leaves one supersession | Rewrite as v2→v3, or record "none" | NG3's trail-format evidence weakens. **Corroborated 2026-08-16 by ruling V5**: on the same material, `差额账户` first appears at v3 L5697/L5703 and v4 changes nothing there but the line offset, so the v3 landing point is now verified from two directions |
| **V16** | P5 undeclared source | P5 → open call 3 | **RESOLVED 2026-08-15, no ruling needed** — the hardening plan carries those rationales, but so does v1, and nothing the plan asserts *alone* reaches the article. Evidence [below](#v16--resolved-by-investigation-no-ruling-needed) | Score D2–D5 as lost drops; the residues are v1's | No provenance gap. Queue drops to 18 |
| **V17** | P10-C5 | P10 → contradictions table | Verified as a contradiction, but the delta is largely a **basis artifact**, and v2 misdeclares its own basis. v2 L378 says the series is ≤120-filtered; its twelve monthly medians (L51–62) are identical in all twelve months to the full report's **unfiltered** 全量中位周期 column (L89–100), not its 剔除 column. So v1's ≤90-*filtered* 13.8/17.8 is being compared against v2's *unfiltered* 15.3/19.8. Verified independently by comparing all 24 values | Keep the row — v2 declares the same span and statistic, so it is a contradiction on its face — but record that much of "+2 days" is re-basing rather than degradation, and do not cite C5 as evidence of real slowdown | C5 survives with a caveat; strengthens the V19 case that basis must be stated |
| **V18** | P4-C3 | P4 → contradictions table | v1 asserts **both** the monthly table and its replacement, two lines apart: L1761 「资金流水记录表 按月存储… uta_liq_trans_log_202605」 and L1763 「translog_realtime 实时translog表（TiDB单表，日分区，7天滚动）」. Verified independently — `uta_liq_trans_log` 1 hit in v1 and 0 in v2–v4, `translog_realtime` already 2 hits in v1. Note L1763 is also the line control **K4** is scored on | Keep the row: the measured token is clean and v2–v4 drop it entirely. Add an open call recording that v1 is internally ambiguous here, as C7's and C9's residuals already are | Row survives; one more documented residual |
| **V19** | FX5 criterion | spec.md FX5 | **RULED 2026-08-16: accepted in a tightened form.** Staleness read "the earlier value appears in the article", which over-attributes. Two findings at ruling time reshaped the fix. First, the drafted wording *"the newest source in the compile set"* is wrong per document and had to become **the newest source that speaks to that item**, since the newest document is usually silent on any one claim and the drafted form would clear an item whenever the latest source simply did not mention it. Second, the item's own rationale does not hold: it invokes V4, but no fixture co-source is newer than its chain head except P5's — P7's is `2026-04-14` against a chain head of `2026-05-14`, P10's `2026-03-05` against `2026-03-06` — so the restatement answers **V4 in no case**, and V4 must still be ruled on its own | Applied to both staleness columns in test-set.md's Scoring table and to FX5, per claim rather than per document. FX7's gate is unaffected, since it counts corrections carried | Applied: no total moved. Ruling it surfaced **V20**, and P5 leaves the gating column — V20 is now ruled and P5 stays out, on V21's grounds rather than on an unruled tie |
| **V20** | Same-day source order | `py/src/kb_ai/core/merge.py` (WP family) | **RULED 2026-08-16: accepted, and settled on the caveat rather than a tie-breaker.** Raised by ruling V19. `build_source_blocks` sorts dated blocks `(date, source_path)` (L173–174) and `_SOURCE_ORDER` tells the model without qualification that "blocks run oldest to newest", caveating **undated** blocks only (L596–603). A same-day pair therefore gets a positive ordering claim resting on a path tie-break, which carries no recency evidence. **P5 is a live inversion**: both versions carry `date: 2026-03-13`, and since `-` sorts before `.` the payload renders `…清单-v3.md` first, so it states that v1 is the newest. Its article carries v3's figures (L32, L141–144), so scored against the stated order P5 reads **5 of 5 stale, not 0 of 5**, and its compile set contains a second such pair (`…测试报告-v100.md` before `…测试报告.md`). The larger ruling-time finding is that P5 is a same-day pair in its frontmatter only, not in fact: v1's body reads 「生成时间：2026-03-13」 (L13) and v3's reads 「生成时间：2026-03-19」 (L12), six days apart. The fact is already recorded as this case's ordering family 2, but only as a confound that leaks the order to the writer; its consequence for the ordering rule was not drawn. What v3 carries is a frontmatter date that is wrong by its own body — the WP2 rolling-date class the spec files under A2 (101 of 996 corpus documents) — and the path tie-break then renders the pair backwards on top of it. Two defects, not one, and only the second is V20's. Measured on the reference KB (`~/.knowledge`, 691 articles, 397 multi-source, `sources` with comma-packed entries split): **156 articles (39%) carry at least two same-day sources, 384 pairs**. Re-measured at ruling time, and the basis had to be restated: the figure first recorded here, 159 articles and 411 pairs, counts byte-identical duplicates as two blocks, which is what merge.py's own comment ("160 of the 395") measures too — but WP7 collapses them into one, and a WP-family fix operates on the post-dedup list. Dropping only repeated paths reproduces 160 articles and 414 pairs, so the recorded figure was the pre-WP7 basis and drifts 3 pairs from today's snapshot; under WP7 the population is 156 and 384. Neither basis changes the argument, and both are given because the item is quoted as a population size. **Neither candidate tie-breaker reaches that population.** A filename version marker appears in 9 of the 384 pairs (2%), and only 2 pair two revisions of the same title; of those 2 the `…测试报告-v100.md` marker turns out to name the tested skill's version, 1.0.0, against a sibling that reports 3.1.0, so it carries no claim about which document is newer and the usable revision signal is **1 pair in 384**. A body-stated date appears in both members of 9 pairs, is unambiguous and differing in 5, and again only 1 of the 5 is a revision pair. So the tie-break is **uninformative rather than inverted** in ~99% of cases, and no stated signal covers them. Separately `_budget_priority` (L262–265) breaks same-day ties path-ascending while claiming newest-first, so for every same-day pair one document is at once the "oldest" for the ordering claim and the "newest" for the budget claim. **Scope, checked across all eight cases**: three have a chain head that is not last within its own day — P5 (shares `2026-03-13` with two, one rendered after it), P7 (`2026-05-14`, one after) and P10 (`2026-03-06`, two after) — but only in P5 is the document rendered after the head a member of the chain. P7's later-rendered same-day source `raw/meetings/2026-05-14-成本管控小组周会.md` carries **v2's** replacements (`97.28` and `11362`, one hit each) and none of v1's six superseded figures; P10's two carry none of v1's either, its only `7.3` hits being `+17.3pp` at L180 and L183. So no stale row outside P5 is affected, and P5's payload has four tie-broken groups (03-10, 03-11, 03-12, 03-13) rather than one — ten same-day pairs inside that one payload, from groups of 2, 3, 3 and 3. **Re-checked at ruling time against the caveat form specifically**, since withdrawing an ordering claim is a different intervention from correcting one: on P7 and P10 the blocks that go unordered are the chain head and co-sources that assert the replacements or nothing, so neither case loses a signal it was scored on. One gap in V4's wording closed on the way: P7's chain head is **not** the newest document in its compile set — `raw/meetings/2026-05-20-aws成本分析.md` is — but it is silent on every token this case turns on — v1's superseded figures and v2's replacements alike (`40.95`, `24.57`, `13.3`, `3000C`, `117.3`, `3300`, `83.1`, `7197`, `17054`, `97.28`, `11362`) plus `闭环`, 0 fixed-string hits each across its 919 lines, so V19's per-claim criterion still lands on v2 and V4's score stands | **Ruled: WP6's caveat extends to same-day blocks, and the tie-breakers are rejected.** Same-day blocks keep rendering in path order for reproducibility, exactly as undated blocks do under WP5, and the system prompt stops claiming a recency relation between them: what WP6 says of an undated block's position now also holds of two blocks sharing a `- Date:` line. The tie-breakers are rejected on the measurement above — a signal that fires on 1 pair in 384 cannot be the rule for the population, and a rule stated in the system prompt applies to every payload, not to the pairs where it happens to be informative. Reading the body's own date is rejected for a second reason: it is **A2's question, already deferred pending FX7**, and the data does not support pre-empting it — of the 10 same-day sources whose body date contradicts their frontmatter, 7 point *earlier* and 2 later (1 carries two body dates), so a body-date rule would move most documents in the direction of looking older, with no way to establish from the corpus which date is the document's own. `_budget_priority` (L262–265) needs no change of direction, which the item did not notice: it already breaks the tie path-ascending (`-date`, then `source_path`) and so does the render (`date`, then `source_path`), so both serve the same document first and the conflict was never in the two orders — it was in WP6 calling that document older while BG1 called it newer. Withdrawing the recency claim dissolves it. What BG1 owes is the matching qualification in its own prose: priority is **newest known day first, ties broken on path for stability**, with no claim that the block served first is the newer of a same-day pair. Two code notes for the implementation. `py/tests/test_core_merge_blocks.py:316` (`test_sources_dated_the_same_day_claim_the_budget_in_path_order`) **pins the behaviour this ruling changes** and is rewritten by the fix, not added to. And `_budget_priority`'s own docstring quotes "160 of the 395 multi-source articles" — the pre-WP7 basis, which becomes **156 of 397** (384 pairs) once identical checksums collapse | Applied: no total moved, and the item's own consequence is reversed. P5 does *not* become scoreable by this ruling — the caveat removes a false claim ("v1 is the newest") and puts *no claim* in its place, so the payload gives A1 no basis to prefer v3's figures and P5's 0 of 5 would be luck rather than evidence of supersession being handled. P5 therefore stays out of the gating count after the fix lands, for a different reason than before: not an unruled tie, but a frontmatter date wrong by six days against its own body. That is raised as **V21**. The fix is still worth taking on its own terms — it stops 384 pairs' worth of unfounded ordering claims, and P5 is the one case in the fixture where such a claim is actively inverted. One number does move, and it is not a total: making P5's exclusion permanent puts the stale rate's denominator in question, since 27 of 44 (61%) counts P5's five contradictions in a column P5 is not judged on. Held apart it reads 27 of 39 (69%), over five gating cases rather than six. Both figures are stated wherever the headline is quoted until V21 picks one |
| **V21** | P5's frontmatter date | `data/kb-supersession-fixture/raw/docs/2026-03-13-…-v3.md`, and P5's row in test-set.md | Raised by ruling V20. v3's frontmatter says `date: 2026-03-13`, its body says 「生成时间：2026-03-19」 (L12), and v1's body says 「2026-03-13」 (L13) — so the two documents are six days apart and the payload's date tie is an artifact of the wrong metadata, not of the corpus. This is the WP2 rolling-date defect the spec files under A2 (101 of 996 corpus documents carry a body heading date later than their frontmatter date), and P5 is a fixture instance of it, which the spec does not yet record — its only named instance is P2, whose chain is inverted *by date*. P5's is not: 03-13 → 03-19 is the true order, and only the render inverts it. With V20 ruled, P5's staleness column has no basis in the payload either way, so the case cannot probe A1's ordering until this is settled | Three options, and none is free. **Re-date v3 in the fixture** makes P5 a normal two-day Shape-B chain but makes the fixture unfaithful to the source document it was staged from, which is the one property FX1–FX3 rest on. **Score P5 as an A2 body-date case** keeps the fixture honest and gives A2's deferred question its first measured instance, at the cost of P5 never gating A1. **Leave it out** costs the Shape-B probe with nothing bought. Recommend the second, and record in FX3 that the fixture holds two wrong-date cases, P2 by inversion and P5 by a tie | P5's 5C / 5D / 6K stay counted in the set totals; what changes is that its staleness sits outside the gate permanently rather than pending a fix, so the cases judged on the gating column are **five** — P3, P4, P7, P9, P10 — with P8 out on V1 and P5 out on this. The set totals do not move, but the **stale rate depends on which denominator is published**: 27 of 44 (61%) with P5's five counted, 27 of 39 (69%) with them held apart. Choosing between them is part of this item, not a separate one |

**Done means**: every V-item above reads `ruled` — or, for V16, `resolved` — with the
decision written into the row it governs, and the Progress table is recomputed from
the survivors. **V1, V2, V3, V4, V5, V12 and V19 are ruled and applied**, so the Progress
table now reads **44 contradictions, 31 drops and 42 controls, with 27 of 44 stale
(61%)** — carried by seven cases still, but only **six of them gating**, since P8
contributes no contradictions. That is a smaller and more defensible set than the
50/30/42 it started from, and its headline no longer leans on P8's rename reading.
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

Consequence: **D2–D5 can be scored as lost drops**, P5's 16 declared sources stand, and
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
| P3-D3 | The transfer system's `Transfer` interface is idempotent on `request_id` with a 3000 ms timeout, `RATE_LIMITED`/`TIMEOUT` retryable and `INSUFFICIENT_BALANCE`/`ACCOUNT_FROZEN` fatal | v1 L635–638 | to confirm |
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
2. **`manifest.json` schema — left out, strongest candidate for promotion.** v1's manifest carries per-interface contracts (`interfaces[]` with `idempotent_key`, `timeout_ms`, `retryable_errors`, `fatal_errors`, v1 L630–646); v2's carries `version`/`createdAt`/`updatedAt`/`triggers`/`documents` and no interface data (v2 L172–192). Same subject, incompatible content. Held out only to stay inside the eight-item ceiling. The article asserts v1's shape as current (L119–123) plus v2's semver (L125), so promoting it adds a 7th stale item.
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
| Shared 04-17 section's own figures | storage governance 56%, vLLM 100% | storage governance 20%, vLLM 90% |

So the file the fixture calls *earlier* is a rolling document that accumulates
meeting sections and carries reporting three weeks *newer* than the file it is
supposed to precede. Its frontmatter `date` is its creation day, not its content
day. Every `replacement` drafted below is therefore the **older** figure.

P2 is worth more as evidence of this failure mode than as a scoring case. WP2
reads the ordering signal from raw frontmatter `date`, so on this document A1
would hand the writer `- Date: 2026-04-14` for content dated 2026-05-04 and
assert an order that is confidently wrong. Q2 and D3 provisioned for a *missing*
date, not a *wrong* one.
Scope of the risk, measured over the corpus rather than assumed:

| Measurement | Result |
|---|---|
| Fixture chains whose body-content order inverts their frontmatter order | **1 of 12** (P2 only) |
| Fixture docs whose newest body heading date postdates their frontmatter date | 6 of 38 |
| Corpus docs with the same symptom | 101 of 996 (10.1%); 36 stale by more than a week |
| Corpus docs sharing the placeholder `date: 2026-01-01` | 21 |
| N3 / N4 | absolute dates stale by ~30 days, **relative order preserved** — still valid controls |

The symptom is common; the fatal form (inverted order) is rare. Meeting
transcripts are the main source — `2026-03-10-realclaw安全评估.md` is dated
2026-03-10 while its body heading reads 「Meeting transcript: realclaw安全评估
2026-04-10」.

### Contradictions and their replacements — drafted in the fixture's stated direction, i.e. reversed relative to content

| ID | What v1 (04-14 file) asserts | Evidence | Article today | Status |
|---|---|---|---|---|
| P2-C1 / R1 | Q2 cloud-cost optimization at 40.95%, 24.57W banked → 0.28%, 0.17W | v1 L898 → v2 L953 | **stale** — L615, L761 state 40.95% / 24.57W as current | to confirm |
| P2-C2 / R2 | Low-load governance over-delivered at 117.3%, 17.6W against a 10W–15W target → 0% | v1 L919 → v2 L969 | **stale** — L618, L762 | to confirm |
| P2-C3 / R3 | AI-gateway scenario convergence 90% (36/40) plus 34 extra → 87.5% (35/40) plus 32 extra | v1 L435 → v2 L448 | **stale** — L578, L759 | to confirm |
| P2-C4 / R4 | Self-developed AI gateway kicked off 4.20 at 100%, design review due 5.8 → still an evaluation due 4.20 | v1 L438–439 → v2 L451 | **stale** — L578 | to confirm |
| P2-C5 / R5 | Bgwst gray release at 50% trading QPS, 40K/s daily, 230K peak, full 5.12 → 45%, 35K/s, 61K peak, full end of April | v1 L557 → v2 L578 | **stale** — L592 | to confirm |
| P2-C6 / R6 | Bgws C++ committed to testnet 5.27 and mainnet 6.16 → no schedule, estimate due 4.24 | v1 L562–564 → v2 L585 | **stale** — L593 | to confirm |
| P2-C7 / R7 | vLLM instance monitoring 100% complete → 90% | v1 L399 → v2 L405 | **stale** — L580, L760 | to confirm |
| P2-C8 / R8 | Storage non-standard governance overall 56% → 20% | v1 L1781, L783 → v2 L824 | not stale, and the replacement is absent too — no storage-governance figure in the article | to confirm |

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
2. **Only C7 and C8 are unambiguous.** They sit inside the section both files date
   2026-04-17, so v1 asserts exactly one value. For C1–C6 the 04-14 file carries
   *both* values in different sections (87.5% at L1405 beside 90% at L435), so an
   article stating v2's figure proves nothing about ordering — it may have copied
   the older subsection. If only unambiguous items should gate, keep C7 and C8 and
   demote C1–C6.
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
| v2→v3 | `set_time` redefined from nanoseconds to milliseconds across seven log tables; `action` renamed `service_action`; counterparty renamed 交易系统户 → 交易系统内的差额账户 with disposal reassigned to TRW; fund-recovery callback API added; the 兑币流水回滚 task and two open questions deleted |
| v3→v4 | Three progress cells only: 封禁 gains 联调结束, 资产追回 60% → 开发90%，下周可以联调, MarginDB 开发中 → 联调中 |

### Contradictions and their replacements (judged v1→v4)

| ID | Earlier assertion → v4's | Evidence | Article today | Status |
|---|---|---|---|---|
| P4-C1 / R1 | Monthly translog gains `change_flow_usd`, `uta_result_topic_name`, `uta_result_offset` → monthly tables get no new fields this round, they go to the real-time table | v1 L1144, L1363, L1368 → v2 L1519 / v4 L1742 | **stale** — L454–456 list all three as current additions, plus open action L636; the correction exists but is misfiled under `uta_liq_trans_log` (L473–478), so the article asserts both | to confirm |
| P4-C2 / R2 | Coin-exchange table is monthly `uta_exchange_record_202604` → a single TiDB table, dual-written with MySQL for a transition | v1 L1433 → v4 L1751 | **stale** — L487 | to confirm |
| P4-C3 / R3 | §4.1.3 fund-flow table is `uta_liq_trans_log_202605`, monthly, past data deletable → `translog_realtime` in TiDB | v1 L1761 → v4 L2111 | **stale** — L469–471 | to confirm |
| P4-C4 / R4 | User-behaviour log tables are monthly-sharded `_{yyyyMM}` → unsharded TiDB tables | v1 L2539, L2667, L3653 → v4 L3272, L3416, L4488 | **stale** — L494, L498, L499 | to confirm |
| P4-C5 / R5 | Existing `uta_leverage_log` will be refactored into monthly shards → migrated from MySQL to TiDB | v1 L3213 → v4 L3869, L3871 | **stale** — L504–506, action L638, plus `uta_spot_leverage_log_{yyyyMM}` L508 | to confirm |
| P4-C6 / R6 | `set_time` in the user-behaviour log tables is nanoseconds → milliseconds | v1 L2626 (and L2782, L2921, L3179, L3353, L3612, L3754) → v4 L3359, L3405 | **stale** — L494 | to confirm |
| P4-C7 / R7 | `uta_auto_add_margin_log` trigger column is `action` → `service_action` | v2 L3954 → v4 L4192 | **stale** — L514, action L639 | to confirm |
| P4-C8 / R8 | Incident counterparty is the trading system account (系统户), funds settle against it → the in-trading difference account (差额账户). Overdraft is **not** part of the change: 「允许透支」 already stands in v2's cell | v2 L5447, L5453 → **v3** L5697, L5703. Corrected from v4 by V5: `差额账户` first appears in v3, and v4 only shifts these two lines by one with no content change | **stale** — L421–424 | to confirm — **V5 ruled 2026-08-16**, row stands with a residual at [call 8](#p4-open-judgement-calls) |
| P4-C9 / R9 | Post-rollback disposal is futures dumped to the order book with options and spot moved to a PM takeover account, pending TR discussion → spot and positions handed to TRW | v2 L5455 → v4 L5706 | **stale** — L425–426, plus open item L667; TRW appears nowhere | to confirm |
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

### Chained supersession (evidence for NG3's trail format, not scored)

| ID | Sequence | Status |
|---|---|---|
| P4-X1 | The system-side account absorbing incident funds: v1 「对账补齐到系统账号（账号可以提前创建好）」 (L4776) → v2 「交易系统户 … 和系统户结算，允许透支」 (L5447, L5453) → **v3** 「交易系统内的差额账户 … 和差额账户结算」 (L5697, L5703; v4's L5698/L5704 are the same two lines shifted one, per V5) | to confirm — weak, see call 4 |

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
3. **C9 is the least certain.** v4's 待决策 section still lists TWAP order-book
   selling and the PM-account transfer as options, while the module table says
   TRW. Scored on the module table because the other block is explicitly marked
   "pending decision".
4. **X1 is weak.** The v1→v2 step is a reframing rather than a contradiction of
   the identical predicate, so a strict reading makes this chain a single
   supersession (v2→v3) and X1 should read "none". Decide before using it as
   trail-format evidence. Its two ends are already scored separately as P4-D3 and
   P4-C8, so lists 1–4 are not double-counting.
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
frontmatter being wrong rather than the corpus being ambiguous — queue item **V21**.

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
| P5-D1 | The skill inventories a Leverage Token module (`/v5/spot-lever-token/*`, 5 endpoints under `spot.md`), Purchase and Redeem needing Mainnet confirmation | v1 L1241, endpoints L1273–1349; verified absent (`spot-lever-token`, `杠杆代币`: 0 hits in v3) | to confirm — see call 1 |
| P5-D2 | When cancelling all orders, take care not to cancel strategic standing orders | v1 L584; v3 L583 reduces the note to 「Mainnet 需确认」 | to confirm |
| P5-D3 | Batch order placement must display all orders before confirmation | v1 L604; v3 L603 reduced | to confirm |
| P5-D4 | The BybitPay Payout endpoint is essentially an alternative withdrawal channel | v1 L4744; v3 L4889 reduced | to confirm |
| P5-D5 | The stated *reason* for removing institutional-loan UID bind/unbind — that it affects other users' accounts — is dropped; v3 keeps the removal with no rationale | v1 L4007 「机构贷款绑定/解绑 UID，影响他人账户」 → v3 L4044 「机构贷款绑定/解绑 UID」; `影响他人账户` 0 hits in v3. **Reworded on verification** — as first drafted the row folded in the surviving removal, so a grader applying the absence test to the row as written finds it present in v3 and mis-scores it | to confirm |

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
   the payload will state at all.
2. **No status flags changed anywhere.** All **273** pairable endpoint rows match on
   name, method and 状态 — zero differences across all three fields, which is the
   strongest single piece of evidence in this case. (251 as first drafted was wrong:
   v1 has 278 REST endpoint rows and v3 299, sharing 273 paths, since 278 − 5
   leverage-token rows = 273.) The ⚠️ count rose only because of **eight** new
   copy-trading / strategy / bot write endpoints. So this revision offers no
   reversed-decision contradiction — it is additive scope plus a recount. Verified
   mechanically: 280 distinct `/v5/...` paths in v1, 301 in v3, 5 dropped (all
   `spot-lever-token`), 26 added, and 280 − 5 + 26 = 301.
3. **Left out — note abridgement below article altitude.** v3 shortens several
   备注 cells without contradicting them (fixed-term borrow, flexible borrow,
   Release Assets, Create Sub-account, Distribute Voucher, Delete Master API Key).
   Treated as restatement because the parent claim survives; the four promoted to
   drops are the ones where a whole distinct assertion disappears. **Verification
   found this inventory materially incomplete**: there are **17** abridged rows, not
   the 10 accounted for here. The seven unlisted are `universal-transfer` (v1 L2730 →
   v3 L2652), `query-universal-transfer-list` (L2732 → L2672), `agreement/pay`
   (L4826 → L4971), `move-positions` (L970 → L969), `move-history` (L990 → L989),
   `create-sub-api` (L3035 → L2978) and `update-api` (L3055 → L2998). Two
   consequences. `universal-transfer` loses a whole distinct assertion —
   「资金可转到他人控制的子账户」, 0 hits in v3 — which is the same shape used to promote
   D4 and D5, so it should be promoted or explicitly declined. And the article
   carries at least **six** abridged details, not two: L394, L396, L397, L399, L402,
   L416, L427. Two of those are D4's and D5's own dropped clauses (L427, L402), so
   **D4 and D5 are lost drops**, which this label did not state.
   The caveat this raised is now **discharged**:
   `raw/docs/2026-03-12-bybit-trading-skill-security-hardening-plan.md` does carry
   several of these rationales verbatim (L96, L116, L156, L342, L588) while **not**
   appearing in the article's `sources` frontmatter, but nothing it asserts alone
   reaches the article, and D5's own clause 「影响他人账户」 is a single corpus hit at
   v1 L4007. So the residues are v1's and D4 and D5 score as lost drops — evidence in
   [V16](#v16--resolved-by-investigation-no-ruling-needed).
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
| P10-C2 / R2 | The 2025 sample is one population of 17,294 → two datasets, 18,445 full and 17,777 filtered, with purposes split (full for throughput, filtered for efficiency) | v1 L12 → v2 L12, L377 | not stale but blended — L30 keeps 17,294 as a live dataset row and L162 says 「17,294–17,777 data points」 | to confirm |
| P10-C3 / R3 | Annual on-time rate ~36%, H1 41.8% → H2 28.5% (−13.3pp) → ~25%, 33.1% → 18.2% (−14.9pp) | v1 L26 → v2 L31 | not stale — L169 uses v2's value | to confirm |
| P10-C4 / R4 | The best month of 2025 reached only 45% on-time → January was best at 35%, falling monotonically to 14.3% in October | v1 L32 → v2 L36, L51, L204 | **stale** — L84 states the 45% claim, in the same sentence as v2's 35%→14.3%, self-inconsistently | to confirm |
| P10-C5 / R5 | Median end-to-end delivery cycle ~15 days (13.8 H1, 17.8 H2) → ~17 days (15.3, 19.8) | v1 L24 → v2 L29 | not stale, replacement also missing — neither ~15 nor ~17 appears | to confirm |
| P10-C7 / R7 | Monthly throughput peaked at 1,907 in July, bottomed at 1,081 in October, a 43% swing → 2,036 and 1,182, on v2's 全量 basis, which is the one v2 designates for throughput (L377) | v1 L50, L53, L59 → v2 L135, L138, L176 | **stale** — L60 states both extremes, and its next sentence gives the monthly average as 1,537, which is v2's 全量 figure (18,445/12) rather than v1's 1,441. The sentence pair crosses bases, so it is not a faithful report of v1 | **V6 ruled 2026-08-16** — row kept, replacement stays 全量; the swing and the peak/trough framing are *not* scored, since v2 asserts both |
| P10-C8 / R8 | UserService's on-time rate fell 44.6% (Q1) → 22.0% (Q4) → 37.2% → 12.1% | v1 L101 → v2 L233 | **stale** — L282 | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P10-D1 | The technical-requirement share of throughput fell from ~31% in Q1 to ~24% in Q4, squeezing technical improvement work | v1 L60; v2's monthly table has no business/technical split, and 技术需求占比 survives only as a 25–35% target (L317) | to confirm |
| P10-D2 | Recommends WIP limits per team to cut context switching | v1 L210 | to confirm |
| P10-D3 | Recommends an organizational-change buffer: a 2–4 week transition with lowered delivery expectations when a leader changes, plus a knowledge-transfer checklist | v1 L225 | to confirm |
| P10-D4 | Proposes a tech-lead quality tier of bug-association rate ≤0.3, rework ≤5%, and a per-capita monthly throughput baseline | v1 L163; v2's third tier is stale-requirement rate / estimation accuracy / P-1+P0 share (L322–326) | to confirm |
| P10-D5 | Mandates splitting any requirement whose delivery cycle exceeds 20 days, targeting ≤10 days | v1 L199; v2 manages size by tiering instead | to confirm |
| P10-D6 | The headline engineering-time metric is *average development duration*, ~9.2 days, +54.8% from 7.3 to 11.3 | v1 L25, restated at L73 and L177; `平均开发时长` returns 0 hits in v2, which reports development duration as a median instead. **Reclassified from contradiction C6 by V3, ruled 2026-08-15** — v2's headline 中位研发周期 (L28) is a different statistic over a different span (L14 defines 研发周期 as development *plus* test), so it cannot contradict a mean development duration | to confirm — **lost drop**: the article still carries v1's mean framing at L21, L50, L54 and L170 |

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
2. **One filtered population → a two-dataset design** with purposes split
   (v2 L377–378). Invalidates every throughput figure: annual 17,294, monthly
   average 1,441, H1 8,916 / H2 8,378 and −6.0% (v2: 9,412 / 9,033, −4.0%), and
   every monthly cell of v1's §2.1. C2 and C7 are downstream.
   **V6's ruling adds three things here**, since it decided which of v2's two columns
   those rows re-base onto. The split is by purpose and v2 states it:
   全量 「用于吞吐量统计和长周期分析」, 剔除版 「用于效率指标计算」 (L377–378).
   So a throughput row takes the 全量 figure and an efficiency row takes the 剔除后 one,
   and neither takes v1's ≤90 population, which v2 does not publish at any
   granularity. The 全量 column reconciles
   exactly (twelve cells → 18,445, and 18,445/12 = 1,537, v2's stated monthly average)
   while the **剔除后 column does not**: twelve cells → 17,578 against a stated 17,777,
   and its 差异 cells → 867, which is 4.7% rather than the headline's 3.6% / 668 items.
   And the re-basing is arithmetically clean in the direction it should be: v1 ≤ 剔除后 ≤
   全量 holds in all twelve months, so no figure was corrected and none can contradict
   another as a count — what changed is which requirements are inside the number.
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
   restated on the new basis and all move down. C8.
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
4. **Team-level contradictions are a family; one is labelled.** Every team's Q1/Q4
   on-time rate is restated downward and the roster itself changes (v1 has 8 rows,
   v2 has 10 different ones). UserService was picked because v1 calls it the worst
   deterioration and the article repeats v1's figures verbatim. Fiat Channel
   (L277) and Compliance (L283) are equally stale if a second entry is wanted.
5. **Five sources, only two of them this pair.** The article also compiles
   `2026-03-05-…-report-full.md`, `2026-03-06-2026-engineering-team-goals.md` and
   `2026-03-06-2026-q1-engineering-efficiency-report.md`. Numbers that look like
   v1 residue but are legitimately from the full-data report and must not be
   scored: 「984 | 5.3%」 (L30), 「9.3 days (annual)」 (L170), 「28% (full-data
   view)」 (L84), and the Q4 full-vs-filtered table (L260–263). The unambiguous v1
   fingerprint is the H1 7.3 / H2 11.3 / +54.8% triple.

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
every one returned 0 hits in the later version. P4's drafting used full-file
diffs, and P8's confirmed each absence by grep. So no drop list is corrupted, but
anyone extending this label set should not reuse that `sed` recipe.

## Note: within-version ambiguity

Every contradiction row is phrased "the earlier version asserts X, the later asserts
incompatible Y". Verification found five places where a single version asserts **both
X and something close to not-X**, so that phrasing is stronger than the documents
support. This is a different problem from the co-source confound: there the *article*
had a second source, here the *fixture document itself* is internally inconsistent.

| Where | The document says both |
|---|---|
| **P4-C3** (v1) | L1761 names the monthly `uta_liq_trans_log_202605`; L1763, two lines later, already introduces `translog_realtime` — its replacement. L1763 is also control K4's line |
| **P4-C8** (v4) | The §5 table names 差额账户 as counterparty (L5698), while L788, L798, L808, L5683 and L5864 still call it 系统户 — including a cell of the same table, two rows up. None is in a pending-decision block |
| **P4-C7** (v4) | DDL says `service_action` (L4192); prose at L4182 still says `action`. Already documented in open call 2 |
| **P2** (the 04-14 file) | Asserts vLLM onboarding at both 「进度100%」 (L399, in its `# 2026-05-04` section) and 「进度90%」 (L1358, in its `# 2026-04-17` section) — the artefact of a rolling document updated in place |
| **P6** (v1) | Its own version: frontmatter `title` (L5) and the H1 (L10) say 「通用网关设计方案 v1.5」 while the body marker at L13 says `> 版本: v1.6`. Governs no row — P6 is adjudicated, not drafted — but it is the only instance where the ambiguity is about the *version* rather than about a claim, and P6's success is credited to that marker ([test-set.md](test-set.md#three-adjudicated-cases)) |

Only one of these was documented when drafted (C7's). Of the rest, **V18**, **V5** and
**V10** are queued; P6's changes no scored row and is recorded rather than queued.

Two consequences for scoring. First, a row whose earlier version also asserts the
replacement is weaker evidence than the table implies, even when the *measured token*
is clean — P4-C3's is clean, and it still deserves the caveat. Second, and more
practically for FX5: **an extractor reading the later version alone can legitimately
emit the older claim**, because the later version still makes it. P4-C8 is the sharp
case — grading the article stale at L421–424 would fail a pipeline for repeating what
v4 itself still says in five places. So a stale verdict needs the later version to be
*unambiguous*, not merely to contain the correction somewhere.

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
this for one case; it generalises.

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

**For the drafted `Article today` column and the 61% headline, the confound is
severe.** Only P3 and P8 are compiled from the chain alone — and V1 struck P8's four
contradictions, so of the six cases that still gate, only P3 does. P7 is the worst case:
its co-source asserts v1's *entire* 0430 column, so 7 of its 8 staleness
observations have a second possible cause. **V4 ruled 2026-08-16 that this bounds the
causal claim, not the score** — a value the article states undated is still contradicted
by the newest source in the same compile set, whichever document supplied it, so P7's
rows stay scoreable and only "this pair's ordering was lost" narrows to C8.

P5's article merges 16 sources, which is
the strongest reason not to read its 0-of-5 pass as evidence that the pipeline
handles supersession — it may simply have been told the newer values repeatedly.

**For FX5's actual scoring the confound is bounded**, because spec.md's FX4 already
declares the existing `wiki/` an existence proof rather than a baseline and re-runs
the compile over the staged fixture. Only P5 and P7 carry a co-source into that run,
one each, and in both cases the co-source is another case's v1 — itself superseded
within the fixture, so ordering applies to it too.

So the 61% pre-A1 figure is motivation, not measurement, and should stop being
quoted as though the two were interchangeable. The criterion this note asked for is now
ruled: **V19** restates staleness against *the newest source in the compile set that
speaks to the item*, per claim rather than per document. It buys less here than this
note assumed, though. The wording only clears an observation where a co-source is
**newer** than the chain head, and of the two co-sources that reach the fixture run
neither is — P7's is dated `2026-04-14` against a chain head of `2026-05-14`, P10's
`2026-03-05` against `2026-03-06`. P5's is the only one that is newer, and P5 is the
case that already scores 0. So the confound above still has to be handled case by
case, which is what V4 is for on P7, and the 61% figure keeps its caveat rather than
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
bodies are six days apart, which is **V21**.
