# FX5 scoring: the A1 arm

**All four rulings this pass opened are settled at their drafted positions
([the queue](#the-ruling-queue--all-four-settled)), so the gating figure is 19 of 40 flat,
and the FX7 verdict is written in [verdict-fx7.md](verdict-fx7.md) — A1 does not clear the
positives, so A2 is required rather than optional.**

Scored 2026-08-19 against the A1 arm in `~/kaas-arms/a1` (20 articles, 14.3873 USD, code
at `033517c`). Labels are the confirmed set in [labels.md](labels.md); columns and their
definitions are [test-set.md's Scoring table](test-set.md#scoring); the criterion is
[spec.md FX5](spec.md). The baseline arm this is compared against is
[scoring.md](scoring.md), which is a *written* record — its tree was destroyed, so a
disagreement about a baseline row cannot be settled by reopening the row.

## The run

`py/scripts/run_fx4_arm.py --out ~/kaas-arms/a1 --execute`, attended, one pass.

| | A1 arm | baseline arm |
|---|---|---|
| Spend | **14.3873 USD** over 185 calls | 17.9896 USD |
| Stages | 4 of 4, **every one first attempt**, residual empty | stage 2 took three passes and left 2 of 18 residual |
| Articles | **20** | 27 |
| Models | `claude-sonnet-4-6` on all three write gates, sent explicitly | same by default, recorded nowhere |
| Gateway | `https://litellm-de.yijin.io/v1` | same (inferred: the only endpoint serving that model) |
| Workers | 8, recorded | unrecoverable |
| Size | per-stage snapshots: 311,912 → 464,773 → 467,981 → **468,024** bytes | one absolute figure, 755,700 bytes |

Spend verified independently: the four stage responses sum to 14.387264 USD, and the token
counts reprice to 14.4061 USD at 3/15 USD per M, the 0.0188 difference being exactly the
6,967 cached tokens at the cache-read rate.

**Both FX4 defects the baseline reproduced are absent.** `audit_articles.py` over the 20
articles: 0 comma-packed `sources` entries, 0 duplicated paths, **0 with unreachable
frontmatter**, 0 unparseable, 0 without sources. The defect that hid P10's 517-line article
from `parse_sources` — the writer's preamble above the frontmatter delimiter — did not recur,
so every case resolved mechanically and none needed resolution by hand.

## Resolution: 14 of 18 chains resolve to one article

The baseline split 10 of 18 chains across `decision/` and `project/`; this arm splits 4, and
the union rule that pass established is therefore load-bearing on far fewer cases.

| Case | article(s) carrying the chain |
|---|---|
| P1 | `project/ai-employee-onboarding-offboarding-it-solution.md` |
| P2 (withdrawn) | 5 articles hold both versions, 3 more hold one — its chain is the infra biweekly, which feeds the whole project family |
| P3 | `project/cht-knowledge-ai-coding-plugin.md` |
| P4 | **split, neither holds all four versions**: `decision/byfi-uta-rollback-redemption-impact-assessment.md` + `reference/uta-trading-rollback-trd-schema-and-idl.md` |
| P5 | `reference/bybit-trading-skill-api-inventory-v3.md` |
| P6 | `project/cgw-universal-business-gateway.md` |
| P7 | `project/cloud-cost-optimization-h1-2026.md` |
| P8 | `project/bybit-ai-initiatives-tracker-2026.md` |
| P9 | **split**: `project/bybit-ai-toc-product-roadmap.md` + `project/bybit-ai-initiatives-tracker-2026.md` |
| P10 | `project/engineering-efficiency-annual-report-2025.md` |
| N1 | `project/ai-analysis-environment-construction.md` |
| N2 | **split**: `project/efficiency-zero-trust-initiative.md` + `project/infra-security-baseline-h1-2026.md` |
| N3 | `decision/realclaw-security-assessment-and-risk-decisions.md` |
| N4 | `project/ai-native-rnd-workflow.md` + `project/bybit-ai-initiatives-tracker-2026.md` |
| U1 | `project/ai-app-deployment-platform.md` |
| U2 | `concept/funding-account-fund-tracing-and-recovery.md` |
| U3, U4 | `decision/byfi-uta-rollback-redemption-impact-assessment.md` (both) |

No article is unclaimed by some chain.

## Results

### P3 — cht-knowledge distillation and indexing

`project/cht-knowledge-ai-coding-plugin.md`, one article, 25,457 bytes.

| Column | A1 arm | baseline | rows |
|---|---|---|---|
| Staleness (gating) | **5 of 9** | 8 of 9 | C1, C4, C5, C6, C9 stale |
| Correction landed | **8 of 9** | 8 of 9 | C9 missing |
| Trail (V28 directional) | **3 of 9** | 4 of 9 | C1, C5, C8 |
| In force (V39) | **6 of 9 fail** | n/a | C1, C2, C4, C5, C6, C7 — all six inside one article, and C1 and C5 fail while carrying a trail |
| Staleness (drop) | **5 of 5** | 4 of 5 | worse: D4 and D5 leave live residue the baseline had none of |
| Collateral | **6 of 6** | 6 of 6 | — |

Row by row:

| Row | verdict | evidence in the arm's article |
|---|---|---|
| C1 project-level cache → user-level | **stale**, correction landed, **trail** | L75 is directional and correct ("In earlier design this was `.claude/knowledge/.cache/`; in the v0.2.0 implementation … `~/.claude/plugins/cht-knowledge/knowledge/<domain>/`"), and L124–126 then asserts a current Key Decision that "The `.claude/knowledge/` directory in user projects is gitignored" — the article contradicts itself |
| C2 three-level resident index → two-stage | not stale, landed, no trail | two-stage current at L84–94 (~200 tokens); the Level 0（常驻）table survives at L96–102 under "The earlier three-level token model is also recorded in the material" — a named basis, no ordering |
| C3 SessionStart injects index every session → UserPromptSubmit on trigger words | not stale, landed, no trail | L384–393: the hook is the silent `git pull --rebase`, and `trigger.mjs` matches prompts to surface knowledge bases. No live claim of per-session index injection |
| C4 24-hour cache window → pull every session | **stale**, landed, no trail | both mechanisms asserted as current and never ordered: L116–118 as a Key Decision heading, L399 in the live Cache Strategy, against L140–142 and L390 |
| C5 no init command → explicit `init <system-id>` | **stale**, landed, **trail** | L104–106 is directional ("The earlier design specified no `/cht-knowledge:init` command … The v0.2.0 command set does include …"), but L181–185 restates the proposition as current: "Integrating developers do not need to manually install each system's knowledge base; one plugin installation suffices" |
| C6 `/cht-tools:distill` → `/cht-knowledge:distill` | **stale**, landed, no trail | v2's command is used throughout (L114, L154, L167, L372) while L29's component table and L528's Related line still assert cht-tools owns `/distill` in the present tense |
| C7 6 dimensions / 6 parallel agents → 8-agent pipeline | not stale, landed, no trail | the 8-agent pipeline is current (L112–114, L254–268); the six dimensions survive only at L274–283 as "The earlier distillation design described six scan dimensions" |
| C8 five named files → eight numbered files | not stale, landed, **trail** | the tree is v2's (L285–298) and L299 is directional ("The earlier design specified a different file set … The v0.2.0 implementation uses the 8-document structure above"). Residue recorded, not scored: `proto-guide` / `integration-guide` / `error-reference` recur as filenames at L508–510 and as a heading at L519 — names reused, not the file set reasserted (see the open call below) |
| C9 repo naming `knowledge-{system}` → `<系统ID>-knowledge` | **stale**, **correction missing**, no trail | v1's form is live at L122, L426, L433, L440 and L450–454; v2's form is **0 hits**. The row V23 promoted is the one row in P3 where the arm carries no trace of the newer value |
| D1 100+ repositories | stale (drop) | L17 states it as current, merged with v2's 30+ microservices in one sentence, as the baseline's did |
| D2 minimum knowledge set, 50 Proto → 5–10 | stale (drop) | L108–110 as a current Key Decision |
| D3 Transfer contract (idempotent, 3000 ms, retryable/fatal) | stale (drop) | the labelled copies at L481–492 and L320–326 are marked "(Earlier Design)", but L507 and L515–517 assert the contract as current inside the AI behaviour chain |
| D4 `/cht-knowledge:search` | stale (drop) | **worse than the baseline**, which had 0 hits: L353 ships `commands/search.md` in the plugin tree and L376 lists `/cht-knowledge:search 划转 幂等` as a current command |
| D5 first systems: transfer, deposit, withdraw, risk, account | stale (drop) | **worse than the baseline**, which named only asset-transfer: L64 carries "完成首批核心系统蒸馏：划转、入金、出金、风控、账户" as a current Open Action Item, and L450–454 lists all five repo paths |
| K1–K6 | 6 of 6 present | K1 L120–122 · K2 L41/L45 · K3 L136–138/L155 · K4 L170–172/L421 · K5 L66/L168/L317 · K6 L91 |

**The behaviour that produced this is new to the set**: the arm writes an explicit
`earlier design … / v0.2.0 implementation …` contrast in prose, which is what earns C1, C5
and C8 their trails and what clears C2, C3 and C7 of staleness. Where it fails, it fails by
**self-contradiction rather than by staleness alone** — C1, C4, C5 and C6 each state the
correct value in one place and the superseded one in another, in the present tense, with no
ordering between them. That is the failure mode the 2026-08-18 pass recorded as having no
column, and on this arm it is the dominant one.

#### Open call, drafted: name-residue versus proposition-residue

C5 and C8 are scored differently on residue of the same *shape*, and the rule that separates
them is not written in test-set.md. Drafted position, applied throughout this pass:

- Residue that **restates the row's proposition** as current makes the row stale (C5's L185:
  one install completes setup).
- Residue that **only reuses a name** from the superseded version, while the proposition
  itself is stated in its v2 form, is recorded and does not make the row stale (C8's
  `proto-guide` filenames at L508–510, the tree at L285–298 being v2's).

This follows V34's main-proposition rule rather than adding to it, but V34 was ruled over
conjunctions, not over residue, so the extension should be ruled explicitly. Scoring the
other way moves P3 staleness from 5 of 9 to 6 of 9.

**Ruled at this position 2026-08-19 as V35** ([the queue](#the-ruling-queue--all-four-settled)).
P3 holds at 5 of 9.

### P4 — trade-rollback TRD, four versions

**The arm split the four versions into an old-half article and a new-half article, and that
split is the failure.** `decision/byfi-uta-rollback-redemption-impact-assessment.md` declares
v1 and v2 (with U3's and U4's pairs, its primary subject); `reference/uta-trading-rollback-trd-schema-and-idl.md`
declares v2, v3 and v4. Neither holds all four, so the case resolves by hand for the second
time in the set's history — but for the opposite reason to the baseline's P10, where one
article held the whole chain and was invisible. Here **no article holds the chain at all**.

| Column | A1 union | A1, newest-half article alone | baseline | rows stale |
|---|---|---|---|---|
| Staleness (gating) | **9 of 10** | **3 of 10** | 7 of 10 | union: C1–C9. Reference alone: C6, C7, C9 |
| Correction landed | **6 of 10** | 6 of 10 | 3 of 10 | missing: C6, C7, C9, C10 |
| Trail (V28 directional) | **1 of 10** | 1 of 10 | 0 of 10 (its single marker is in the as-of tier V28 excludes) | C1 |
| In force (V39) | **6 of 10 fail** | 1 of 10 fail | n/a | C1–C5 fail **across the two articles**, C8 fails inside the newest-half one. C6, C7 and C9 pass on one value only; C10 states neither |
| Staleness (drop) | **4 of 4** | 0 of 4 | 3 of 4 | D1–D4, all in the old-half article |
| Collateral | **6 of 6** | 6 of 6 | 6 of 6 | — |

The two articles disagree on almost every row, and each is internally consistent:

| Row | old-half article (v1+v2) | newest-half article (v2+v3+v4) |
|---|---|---|
| C1 three fields to the monthly translog | lists all three in the monthly table's field list (L310) | **strikes them**: `~~change_flow_usd~~ (removed)`, `~~uta_result_topic_name~~ (removed)`, `~~uta_result_offset~~ (removed)` (L351) and states the rule — "New fields will only be added to the real-time table … not the monthly partitioned table" (L355) — while listing all three as **New field** in `translog_realtime` (L417, L432, L433) |
| C2 coin-exchange table | `#### Currency Exchange Record Table (uta_exchange_record_202604)` (L314) | `### uta_exchange_record Table (TiDB)`, "A TiDB single table (no monthly partitioning) … Dual-written with MySQL for a transition period" (L488–490) — **the correction the baseline missed entirely**, 「与mysql双写」 having been 0 hits there |
| C3 fund-flow table | `#### Liquidation Transaction Log Table (uta_liq_trans_log_202605)` (L318) | `uta_liq_trans_log` is **0 hits**; `translog_realtime` is the section (L368–370) |
| C4 behaviour log tables monthly | `_{yyyyMM}` on four tables (L354, L359, L387, L424) and an action item to build one (L530) | every table unsuffixed and marked TiDB (L537, L567, L593, L707). Its only `_{yyyyMM}` is `translog_{yyyyMM}_{uid%100}` at L372, which is control K1's surviving monthly table and is current |
| C5 `uta_leverage_log` | "Monthly-partitioned table … **To be refactored into monthly partitioned tables**" (L369), action item L526 | `### uta_leverage_log Table (TiDB, migrated from MySQL)` (L634) |
| C6 `set_time` ns → ms | nanoseconds at L365, L385, L395 | nanoseconds at L553, L581, L625, L647, L716 — **five lines where the baseline had one**, and 「设置时间(ms)」 lands nowhere in either article |
| C7 `action` → `service_action` | `action` on `uta_auto_add_margin_log` (L430, L432) and two action items (L527, L543) | same (L668, L670). `service_action` appears at L351 and L430 but on translog, the string hazard the label warned about |
| C8 counterparty 系统户 → 差额账户 | 交易系统户 only, as current (L460, L464) | 交易系统内的差额账户 in the module list (L96), plus a dated note at L103 — "The 2026-05-26 source lists this module as 交易系统户; the 2026-06-02 source lists it as 交易系统内的差额账户. Both are recorded as the material does not resolve the discrepancy" — and a slash-joined heading at L814 |
| C9 disposal → TRW | v2's disposal (L464–466) | v2's disposal (L818–822) and v2's deleted hedge, "discuss disposal approach with TR team" (L847). `TRW` is **0 hits in both** |
| C10 60% → 90% | no progress cells | no progress cells. Not stale (`60%` absent) but **the correction is lost too** (`90%` absent), where the baseline carried v4's value at L735 |
| D1 `TradeEngineService` + ban RPCs | the whole service as current, with all four request fields (L251–261) | 0 hits |
| D2 ~166.6M rows | "AUTO_INCREMENT currently at 166624305" (L373) | 0 hits |
| D3 reconcile/top-up to a pre-createable system account | L440, L447, L468 | 0 hits |
| D4 coin-exchange flow rollback task | L458, L540 | L847 |
| K1–K6 | K1 L330 · K6 L330 | K1 L343 · K2 L60–72 (all four criteria) · K3 L735–736 · K4 L368–370 · K5 L422/L497 · K6 L373 |

Three things follow, and they pull in opposite directions:

1. **On its own, the newest-half article is the best result in the set** — 3 of 10 stale
   against the baseline's 7, with the storage-architecture rows (C1–C5) all clean and the
   `uta_exchange_record` dual-write correction landing where the baseline had nothing. Where
   it still fails, it fails on **cell-level conventions inside DDL tables** — `set_time` in
   nanoseconds, `action` for `service_action` — which are v2 cells copied verbatim into a
   table whose heading is v3's.
2. **The union is the worst result in the set**, 9 of 10, and every one of the six rows the
   newest-half article gets right is contradicted by the other article in the present tense
   with no marker of any kind. All four drops live there too.
3. **The old-half article is not a defect of the writer but of the split.** Its sources stop
   at v2, so nothing in its own inputs says the design moved; the compile set holds v3 and
   v4 and the classifier put them in a different article.

#### Open call, drafted: how a chain the arm distributes should resolve

The baseline's precedent excludes an article that does not declare the whole chain — P4's
`reference/uta-trading-rollback-database-schema.md` was ruled out of scope there on exactly
that test. Applied literally here it excludes **both** articles and P4 becomes unscoreable,
which cannot be the answer for the case the set calls its strongest failure.

Drafted position, used above: score the **union of the articles that declare any part of the
chain**, and report the newest-half article's own figure beside it, because a comparison
against the baseline's single article is otherwise reading two different objects. The union
is the honest number for the KB a user queries — that user gets both articles — and the
per-article number is the honest number for the writer.

This needs a ruling, and it decides the direction of P4's contribution to FX7: 9 of 10 says
A1 made the gating column worse, 3 of 10 says it made it much better, and both are
measurements of the same arm.

**Ruled at this position 2026-08-19 as V36** ([the queue](#the-ruling-queue--all-four-settled)).
P4 is scored on the union at 9 of 10 with the newest-half article's 3 of 10 reported beside
it. It decides P4's characterisation and not the FX7 verdict, which fails the gate on every
reading — the alternative total is **8 of 40**, since scoring newest-half articles only takes
P9 to 0 of 6 as well.

### P7 — 2026 H1 cost progress tracking

`project/cloud-cost-optimization-h1-2026.md`, one article, 29,604 bytes, and **the cleanest
result in the set**.

| Column | A1 arm | baseline | rows |
|---|---|---|---|
| Staleness (gating) | **0 of 8** | 5 of 8 | see the open call — C4 and C6 turn on it |
| Correction landed | **6 of 8** | 6 of 8 | missing: C4, C6 |
| Trail (V28 directional) | **1 of 8** | 0 of 8 under V28 (its 6 markers are the as-of tier) | C8 |
| In force (V39) | **4 of 8 fail** | n/a | C1, C2, C3, C5 — every row where both snapshots are on the page. C4 and C6 pass on the superseded figure alone, C7 on the replacement alone, C8 on its trail |
| Staleness (drop) | — | — | P7 has no drop rows |
| Collateral | **5 of 6** | 5 of 6 | K2 missing in both, the same split conjunction |

The arm turned this case into a **time series**. Every progress figure carries its snapshot
date and the newest snapshot is present, so the superseded value is stated as history rather
than as fact:

| Row | verdict | evidence |
|---|---|---|
| C1 Q2 progress 40.95%/24.57w → 95.18%/57.11w | not stale, landed | the four snapshots are a table (L40–45), 20260514 reading 57.11w / 95.18%. **The baseline lost the unit and the rate here** — 57.11 arrived as a percentage from a co-source; this arm states 「57.11w completed (95.18% of 60w/month pace)」 at L27 |
| C2 low-load 17.6w at 117.3% → 44.4w | not stale, landed | one sentence, tense-marked and dated: "As of 20260430, low-load governance **had completed** 17.6w, a completion rate of 117.3% … As of 20260514, low-load governance **has completed** 44.4w" (L165). `44.4` was 0 hits in the baseline |
| C3 commercial model 6.8w → 8.3w | not stale, landed | 8.3w in the 20260514 breakdown (L48), 6.8w in the 20260430 one (L54). Both rates (13.3%, 41.5%) are absent, and the row scores on the amount |
| C4 listing rightsizing 3300C/83.1% → 3864C/97.28% | **correction lost**, staleness turns on the call below | L242 is the only statement and it is v1's, stamped "As of 20260430"; `3864` and `97.28` are 0 hits |
| C5 optimizable cores 7197C/17054C → 11362C/25046C | not stale, landed **in full** | dated pairs for both clouds (L203–213, L221–231). `25046` was 0 hits in the baseline and 11,362C appeared there only under the SP framing — the double-count hazard R6 warns about. Here it lands as AWS total optimizable, where v2 L108 puts it |
| C6 EC2 SP shortfall 3000C → 7C | **correction lost**, staleness turns on the call below | L130–134 states the gap as 3000C "as of 20260430"; `7C` is 0 hits. v2's reducible scope is present (L134, L530 「转为优化1万核」) |
| C7 Tencent ES contract not landed → done, May cashback | not stale, landed | L123 and L532: "ES包月合同落地完成 — 1.5w ✅ completed (May cashback confirmed)". **The baseline was stale twice on this row** |
| C8 closed loop 0% → 50% | not stale, landed, **trail** | L414: "Progress: **50%** (as of 20260514; **previously 0%**)" — the one row in this case that states the older value is no longer in force and which stands |
| K1–K6 | 5 of 6 | K1 L18–21 · K3 L131–132 (both halves in one place) · K4 L122/L531 · K5 L275 · K6 L327. **K2 missing**: the 16w–30w target survives at L68/L91 but "still 0%" is nowhere — architecture rationalization has no status line at all |

#### Open call, drafted: does an accurate as-of stamp defeat Staleness when nothing newer is offered?

C4 and C6 are the only rows in the case where the superseded figure is the *only* figure the
article gives. Both are correctly stamped "As of 20260430". Drafted position: **not stale**,
because the column measures a claim "present and stated as current" and a dated status line
does not state it as current — what those rows lose is the correction, which is already
counted against them.

The dissent is V33's, from the other direction: a date stamp inside a table that asserts
present-tense status does not make a row historical. That dissent was about an Open Action
Items table; these two are inside status sections whose headings carry the date. If Captain
rules with V33's dissent instead, **P7 reads 2 of 8** rather than 0 of 8 — still the largest
single-case improvement in the arm, so the ruling changes the figure and not the direction.

**Ruled at this position 2026-08-19 as V37** ([the queue](#the-ruling-queue--all-four-settled)).
P7 holds at 0 of 8.

### P9 — Bybit AI ToC project initiation

**Split by version, exactly as P4 was.** `project/bybit-ai-toc-product-roadmap.md` declares
**v2 only** (2026-05-11); `project/bybit-ai-initiatives-tracker-2026.md` declares **v1 only**
(2026-04-23), alongside P8's pair, N4's pair and the infra biweekly. Neither article sees both
versions of the chain.

| Column | A1 union | v2-only article | v1-only article | baseline | rows |
|---|---|---|---|---|---|
| Staleness (gating) | **5 of 6** | **0 of 6** | 5 of 6 | 4 of 6 | C2, C3, C4, C6, C7 |
| Correction landed | **6 of 6** | 6 of 6 | 0 of 6 | 5 of 6 | — |
| Trail (V28 directional) | **0 of 6** | 0 of 6 | 0 of 6 | 1 of 6 | **impossible by construction** — see below |
| In force (V39) | **5 of 6 fail** | 0 of 6 fail | 0 of 6 fail | n/a | C2, C3, C4, C6, C7 fail **across the two articles**, none inside either. C5 passes: v1's framing is asserted nowhere |
| Staleness (drop) | **7 of 8** | 0 of 8 | 7 of 8 | 8 of 8 | only D7 leaves no residue |
| Collateral | **6 of 6** | — | — | 6 of 6 | — |

| Row | v1-only article | v2-only article |
|---|---|---|
| C2 phase 3 end Sept → end Oct | 「三期（9月底完成）」 (L267), the milestone table (L392), and the overview line "defines the full roadmap for TradeGPT **through September 2026**" (L27) | "**Phase 3** — end of October" (L35) |
| C3 phases 1–2 mid-June/mid-Aug → end June/end Aug | 「一期（6月中完成）」/「二期（8月中完成）」 (L265–266), restated at L390–391 | end of June / end of August (L33–34) |
| C4 Top-20 Q&A phase 1 → phase 2 | 「Top20问答优化完成」 inside 一期 (L265), the milestone (L390) and an open action item (L482) | 「Top 6-20 问答优化」 under **Phase 2 Capabilities** (L104) |
| C5 killer feature narrowed | does not assert v1's cross-product comparison framing either; `RWA` is 0 hits in both | v2's narrowed form in full — 5 capital-protected products, 16 auto-release scenarios (L49–76, L125–126) |
| C6 personal OpenClaw free to high-value users (phase 2) → paid mid-tier subscription | 「TradeGPT高价值用户开放个人专属OpenClaw」 inside 二期 (L266), restated at L391 and L488 | "Cloud Lobster (云龙虾) — A **paid subscription service for intermediate users**" (L189–191) |
| C7 hybrid keeping Bybot's entry → Global TradeGPT only, Local CS only | "**Chosen solution — Hybrid approach**" (L341) and a Key Decision row asserting it (L366) | "Global sites will retain only the TradeGPT entry point; Local sites will retain the customer service entry point" (L129–136) |
| D1–D8 | D1 L278 · D2 L278/L365 · D3 L347/L368 (**in full**, including the cost tie-break the baseline lost) · **D4 L331** 「AB直选能力」 · D5 L336–339 · **D6 L307** 「链式执行」 · D8 L265/L478 | none — v1's dropped claims cannot appear in an article that never saw v1 |
| K1–K6 | K1 L273–276 (v1's 「心跳触发机制」 form) · K2 L258 · K3 L313–318 · K4 L310 · K5 L267/L392 · K6 L297 | K1 L158–163 · **K2 L210 with its units intact** — 「19.9 Mil」 / 「80 Mil」, where the baseline rendered them as CNY and scored 0 hits · K3 L89–94 · K4 L146 · K5 L179 (preset questions) · K6 L23 |

**D4 and D6 are regressions with a clear cause.** Both were among the baseline's three
no-residue drops — nothing for a supersession rule to remove. Here the v1-only article
restates them (「AB直选能力」, 「链式执行」) because v1 is its only source, so the arm turned two
clean rows into lost ones without any writer deciding anything.

#### A trail is impossible when the arm splits a chain by version

This is the structural finding of the pass, and it is not a scoring question. The Trail column
asks whether the article says the older value has been replaced and which value stands. On
P9 **no article holds both values**: the v2-only article has nothing to mark as superseded,
and the v1-only article does not know a newer value exists. The same holds for P4's two
halves. Six of the arm's 45 contradiction rows are in P9 and ten in P4 — **16 of 45 rows sit
in chains no single article can trail**, whatever the writer does.

D1 is scored on articles, so this is A1's result and not an excuse for it. But it means the
FX7 verdict cannot read a low Trail count as "the writer declines to mark supersession": on a
third of the set the writer was never shown the two values together.

### P10 — 2025 engineering efficiency report

`project/engineering-efficiency-annual-report-2025.md`, one article holding both versions,
32,239 bytes. **Coequal presentation with a named basis, carried out systematically**: the
article runs `### V1 Metrics` against `### V2 Metrics`, `### V1 Framework` against
`### V2 Framework`, `### V1 Targets` against `### V2 Targets`, and `From V1:` against
`From V2:` inside every roadmap section.

| Column | A1 arm | baseline | note |
|---|---|---|---|
| Staleness (gating) | **0 of 7** | 0 of 7 | same result by the same mechanism, but on one article instead of two |
| Correction landed | **7 of 7** | 7 of 7 | and two of them the baseline lost outright: C5's ~17-day pair (both sides were absent there) and C8's 37.2 / 12.1 |
| Trail (V28 directional) | **0 of 7** | 2 of 7 | the arm's labelling is basis attribution end to end; nothing says a value has been replaced |
| In force (V39) | **7 of 7 fail** | n/a | every row — this is the case that defines the failing shape, all seven inside one article |
| Staleness (drop) | **5 of 11** | 9 of 11 | D2, D3, D5, D9, D10 |
| Collateral | **6 of 6** | 5 of 6 | **K2 recovered** — the baseline's one over-deletion hit in this case |

What the version labelling buys, row by row:

| Row | verdict | evidence |
|---|---|---|
| C1 >90 days (~6.3%) → >120 days (668, 3.6%) | not stale, landed | L18 states v1's rule under "**V1 (2026-03-05):**", L20 v2's, Decision 7 (L101–105) states the 120-day rule as the decision. v1's 6.3% is present where the baseline had 0 hits — and labelled |
| C2 one population 17,294 → 18,445 full / 17,777 filtered | not stale, landed | L18/L20 and the two metric tables (L131, L141). **No blending**: the baseline kept 17,294 as a live dataset row and wrote 「17,294–17,777 data points」; here each figure sits in its own version's table |
| C3 on-time ~36% (41.8→28.5) → ~25% (33.1→18.2) | not stale, landed | L135 and L146, plus L81's 「~25–36% (**depending on version**)」 — the same band the baseline stated unlabelled, here attributed |
| C4 best month 45% → January 35%, October 14.3% | not stale, landed | L153: "The best monthly on-time rate **in V1** was only 45%". **This is the baseline's one self-inconsistent row in P10** (45% asserted one sentence after v2's series); the label fixes it |
| C5 median cycle ~15 (13.8/17.8) → ~17 (15.3/19.8) | not stale, **landed** | L133 and L144. On the baseline **neither side appeared at all** — eight strings, all 0 hits |
| C7 throughput peak/trough 1,907/1,081 → 2,036/1,182 | not stale, landed | the two monthly series (L185–196, L204–215) and L217 stating both: "July was the peak throughput month (2,036 in V2; 1,907 in V1)". v1's 43% swing is 0 hits, and the 1,441/1,537 monthly averages sit in their own tables instead of consecutive sentences |
| C8 UserService 44.6→22.0 → 37.2→12.1 | not stale, landed | L320 (V1 table), L335 (V2 table) and L371 spelling out all four: "from 44.6% (V1) / 37.2% (V2) in Q1 to 22.0% (V1) / 12.1% (V2) in Q4" |
| D1, D4, D6, D7, D8, D11 | not stale (drop) | every occurrence sits under a version-labelled heading: D1 at L198 and L502, D6's 平均开发时长 at L134/L259/L458, D11's ToB volatility absent entirely (`24.5` 0 hits). D4, D7 and D8 appear in Decision 1's tier summary (L51–53) and are retracted in place by L55, "V2 **refines** this into…" |
| D2 WIP limits | **stale (drop)** | L501 is labelled "From V1", but **L543 is an unlabelled row of the Action Items table** with an owner column. The baseline's whole residue here was a frontmatter tag |
| D3 organizational change buffer | **stale (drop)** | L85–89 is **Key Decision 5**, unlabelled and present tense, plus action item L547. The baseline had no residue at all |
| D5 mandate splitting >20 days | **stale (drop)** | L69–73 is **Key Decision 3**, unlabelled, with no v2 counterpart offered. Stale on the baseline too |
| D9 Goodhart | **stale (drop)** | L57's unlabelled rationale for Decision 1, and L477 inside 「Target Setting Principles」, which L472 introduces as "The source material records…" without naming a version. Stale on the baseline too |
| D10 环比优于同比 | **stale (drop)** | L475, the same unlabelled principles list. No baseline residue |
| K1–K6 | 6 of 6 | K1 L18/L20 · K3 L18 (`dept_l2`) · K4 L22/L276 · K5 L77–79, with the V1/V2 blend **attributed** at L533 · K6 L93–97/L513–517. **K2 present at L395** — 「按时交付率 \| 实际交付日≤计划交付日的比例 \| Planned vs Actual」 — the definition three sources state and the baseline stated nowhere |

**The pattern is exact and it is the most useful thing this case says about A1.** Every stale
row in P10 is a row where the article **stepped out of the version-labelled presentation**:
the Key Decisions section and the Action Items table merge v1's and v2's recommendations
without attribution, and all five lost drops live there. Inside the labelled sections the
arm is clean on all seven contradictions and six of eleven drops.

That is also why its Trail is 0. The labelling that clears Staleness is attribution, not
supersession — under V28 it is the tier that "forges the signature", and P10 reads
`(Staleness 0, Trail 0)`, which is D1's **coequal presentation** exactly: the shape the
option list did not name until this branch added it.

### P5 — Bybit trading skill API inventory (reported apart, V21)

`reference/bybit-trading-skill-api-inventory-v3.md`, one article holding both versions.

| Column | A1 arm | baseline |
|---|---|---|
| Staleness | **0 of 5** | 0 of 5 |
| Correction landed | **5 of 5** | 5 of 5 |
| Trail (V28 directional) | **0 of 5** | 0 of 5 (its 4 markers are the basis-labelled tier) |
| In force (V39) | **5 of 5 fail** | n/a — reported apart from the gate under V21 in any case |
| Staleness (drop) | **1 of 6** | 6 of 6 |
| Collateral | **6 of 6** | 6 of 6 |

Every headline figure is v3's (L33–40: 301 / 279 / ~169 / ~110 / ~31 / 22 with the 12 P0 and
10 P1 split), and the superseded set survives only inside an explicit
**`## Version Comparison: 280-Endpoint vs 301-Endpoint Inventory`** table (L660–672) whose
columns are headed "Earlier doc (2026-03-13)" and "v3 doc (2026-03-13)". That is P5's
baseline shape reproduced almost exactly — the tier V28 excludes — so the case reads the same
`(0, 0)` it did there.

The drop arm is where it moves, and it moves the right way: **five of the six drops leave no
residue** where the baseline lost three. D4's 「另一种提现通道」, D5's 「影响他人账户」 and D6's
「资金可转到他人控制的子账户」 are all 0 hits — the article carries v3's abridged cells instead
(L268, L300, L410), which is the correct reading of the newer source and the exact opposite
of the baseline, which carried v1's dropped clauses on the same lines. D2 and D3 never reach
the article, as on the baseline.

D1 is the one lost drop, and it is lost with an unusual honesty: the Leverage Token module is
present in full (L162–176, five endpoints, both ⚠️ cells) under a section numbered **4b**,
and the article says so — "This module appears in the earlier inventory (280-endpoint version)
as Section 5 … It is not assigned a standalone section number in the v3 inventory; the
material does not explain the discrepancy" (L164, restated at L675). It states the module as
current while flagging that its status in the newer source is unclear. That is not a basis
label that defeats staleness — it is a hedge — so the row scores stale. **V9's exclusion is
inert here for the same reason as on the baseline**: this article declares exactly the two
chain files, so no never-superseded co-source is in scope.

### P8 — AI project portfolio overview (0 contradictions, V1)

`project/bybit-ai-initiatives-tracker-2026.md` — the same article that carries P9's v1, N4's
pair and the infra biweekly.

| Column | A1 arm | baseline |
|---|---|---|
| Staleness (drop) | **7 of 7** | 7 of 7 |
| Collateral | **6 of 6** | 6 of 6 |

Identical column readings, and **the arm carries both arms of the case more completely than
the baseline did** — which cuts both ways:

- The three resource-constraint drops are restated **whole** in one table (L400–404): D1 with
  its scope clause 「承担客服、个性化、基础设施三大方向，严重不足」 that the baseline lost, D2
  「分散在不同业务线，不可持续」 attached to infra where it belongs rather than to the AI team, and
  D3 including 「5 人」, which was 0 hits in the baseline. Better fidelity to v1, and v1 is the
  version that dropped them — so the column reads the same 7 of 7 while the residue is larger.
- D4–D7 are all in the milestone table (L381, L382, L385, L387) and again as open action items
  (L470, L473, L474), including D7's 「Q2 W6」 grain.
- On the control side the gains are real: **K1 keeps both halves** (「Go-native LLM routing
  service」 *and* 「≥50% cost reduction」, L61) where the baseline lost the descriptor — the row
  V34 was ruled over — and **K3's 24 + 39 category split is present** (L42), where the baseline
  scored 0 hits and had to fall back to the total.

### P1 — onboarding/offboarding IT solution (drop-only, does not gate)

`project/ai-employee-onboarding-offboarding-it-solution.md`. **Stale**, as on the baseline,
but on two lines rather than four: L32 「Only approximately 140 users currently have Lark AI
Summary permissions」 and L77 「Currently only approximately 140 users have access」, plus the
pending pricing action at L152/L166. v2's addition landed — 「（新增，4.17 已上线）」 at L97 and
L109 — and one line is version-attributed (L43, "The 2026-04-08 source additionally listed a
fourth goal"), which is what keeps the residue down to two. No trail.

### P6 — universal gateway (no-regression check)

`project/cgw-universal-business-gateway.md`. **Pass, and better than the baseline.** The
article leads with v1.7's four-gateway framing (L16, L191), 「重量级」 / "heavyweight" /
"business-oriented gateway" are 0 hits, and **it names the version range the baseline lost**:
"The design specification covers versions v1.5/v1.6 (dated 2026-03-23) and v1.7 (dated
2026-03-30)" (L18). The bgw problem list is repeated at L34–43 exactly as v1.7 keeps it,
subordinated to one of four gateways.

### N1–N4 — false positives: 0 of 4

| Case | article(s) | verdict |
|---|---|---|
| N1 | `project/ai-analysis-environment-construction.md` (both versions) | clean. L188's "Planned to be replaced by infrastructure-provided MCP by end of April" is the source's own plan, not a supersession marker |
| N2 | **split**: `project/efficiency-zero-trust-initiative.md` (v2 only) + `project/infra-security-baseline-h1-2026.md` (v1 only) | clean. Checked and cleared: the one marker in the second article — "Go non-standard applications remaining: 179 (strategy column **previously** stated 164)" (L354) — is not N2's. Neither figure occurs anywhere in N2's pair; it belongs to the infra biweekly material |
| N3 | `decision/realclaw-security-assessment-and-risk-decisions.md` (both) | clean, no marker of any kind |
| N4 | `project/ai-native-rnd-workflow.md` (both) + the tracker | clean. "previously compiled AI project list" (L138, L152) is a person's action recorded in the source, not a claim about the pair |

### U1–U4 — double counts: 0 of 4, with a new failure mode

No duplicate contributes twice: no figure, list or total is doubled in any of the three
articles carrying the four pairs, and no marker asserts a supersession between byte-identical
documents.

**But the arm invents a difference where there is none.** U1's article attributes shared
content exclusively to the later copy — "**The 2026-04-17 document** records these sub-tasks
within the build module" (L55) and again at L268 — on a pair whose bodies are byte-identical
and whose checksums match. U3 and U4 do the same in the other direction, attributing to
"The **2026-04-15** ByFi assessment" and "A separate **2026-04-15** middle-platform impact
assessment" (L19, L23, L83). Nothing is double counted and nothing is stale; a reader is
simply told that one of two identical documents is the source of material both contain.

This has no column. It is the mirror image of the double-count failure U1–U4 were written to
catch — **false differentiation** rather than duplication — and it is a direct product of an
arm that attributes claims to source documents by date. Recorded here rather than scored.

## Totals

### Contradiction rows (45)

| Case | rows | stale | correction landed | trail | in force, fail (same article / split) |
|---|---|---|---|---|---|
| P3 | 9 | 5 | 8 | 3 | 6 (6 / 0) |
| P4 | 10 | **9** (3 in the newest-half article) | 6 | 1 | 6 (1 / 5) |
| P5 (apart, V21) | 5 | 0 | 5 | 0 | 5 (5 / 0) |
| P7 | 8 | 0 | 6 | 1 | 4 (4 / 0) |
| P8 | 0 | — | — | — | — |
| P9 | 6 | **5** (0 in the v2-only article) | 6 | 0 | 5 (0 / 5) |
| P10 | 7 | 0 | 7 | 0 | 7 (7 / 0) |
| **Total** | **45** | **19** | **38** | **5** | **33 (23 / 10)** |

**The gating column — the five cases that gate (P3, P4, P7, P9, P10), 40 rows:**

| | A1 arm | baseline arm |
|---|---|---|
| Staleness (gating, lower is better) | **19 of 40 (47.5%)** — 8 inside one article, 11 only because a second article holds the older half of a split chain | 24 of 40 (60%), its own split unrecoverable |
| Staleness, same-article ([V40](test-set.md#v40-the-gate-reads-the-same-article-count-on-both-columns), ruled 2026-08-20 — this is what the gate reads from now on, and it moves neither published figure) | **8 of 40** | not published; partitioned by *A1's* split it is 13 of 24 on the three unsplit cases |
| In force, V39 (gating, lower is better) | **28 of 40 — 18 inside one article, 10 across a split chain** | n/a, the articles are gone |
| Staleness ∪ In force (the strict reading, A1 side only) | **32 of 40** | ~34 of 40, an estimate that stays one |
| Correction landed (of 45) | **38 of 45** | 34 of 45 |
| Trail, V28 directional (of 45) | **5 of 45** | 7 of 45 |
| Staleness (drop) (of 41) | **29 of 41** | 37 of 41 |
| Collateral present (of 42) | **41 of 42** | 40 of 42 |
| False positives (of 4) | **0** | 0 |
| Double counts (of 4) | **0** | 0 |
| Size | 468,024 bytes over 20 articles, per-stage snapshots recorded | 755,700 bytes over 27 articles, single absolute figure |
| Spend | 14.3873 USD | 17.9896 USD |

Per-case gating detail: P3 5 of 9 (baseline 8), P4 **9 of 10** (baseline 7), P7 **0 of 8**
(baseline 5), P9 **5 of 6** (baseline 4), P10 0 of 7 (baseline 0).

**A1 improves every failure column the two arms share, and loses the one positive column.**
Staleness 24 → 19, drops 37 → 29, corrections 34 → 38, collateral 40 → 41, and Trail 7 → 5.
It also did it for 3.6 USD less, in four clean stages, with both FX4 defects gone. **The one
column it fails outright is In force, and no arm shares it** — the baseline cannot be scored
on a column ruled after its articles were deleted.

### What actually changed, and why Trail went down

The arm plainly *uses* the ordering information: it writes 「V1 (2026-03-05)」 against
「V2 (2026-03-06)」, "In earlier design this was … in the v0.2.0 implementation …",
"As of 20260430 … As of 20260514 …", "The 2026-05-26 source lists this module as X; the
2026-06-02 source lists it as Y". Ordering reaches the page on almost every case. What the
writer does with it is **attribute each value to its source** rather than assert that one
value has replaced the other.

That single behaviour explains the whole result:

- It **clears Staleness** wherever it is applied, because a named basis makes the two figures
  different claims (V28's own reasoning) — P7 0 of 8, P10 0 of 7, P5 0 of 5.
- It **earns no Trail**, because attribution is not replacement. The five trails in the arm
  are the exceptions where the writer went further and said which value stands: P3's
  「The earlier design specified … The v0.2.0 implementation uses …」 (C1, C5, C8), P4's carried
  strikethrough plus its stated rule (C1), and P7's 「previously 0%」 (C8).
- Where the arm **stops** labelling, it fails hard and in the same three places every time:
  **Key Decisions sections, Action Items tables, and DDL cells copied verbatim**. Every stale
  row in P10 is in a Key Decision or an action item. P3's four stale rows are Key Decisions
  and a Related line. P4's surviving failures are `set_time` in nanoseconds and `action` for
  `service_action`, cells lifted from v2 into a table headed v3.

So `(Staleness, Trail)` reads `(0, 0)` on the three cases where the arm is at its best. That
is **coequal presentation** — the shape D1's option list did not name until V28's ruling added
it, and the shape D1 rejects in terms.

### In force, measured 2026-08-19 on the surviving articles

The two columns above cannot tell that `(0, 0)` apart from latest-wins, which is why
[V39](test-set.md#v39-in-force--what-it-takes-to-leave-one-value-standing) added a third. It
asks whether the reader is left with one value in force, and it was measured row by row
against the arm's articles in `~/kaas-arms/a1/kb/wiki` rather than derived from the rows above.
**28 of the 40 gating rows fail: 18 inside a single article, 10 across a chain the classifier
split.** With P5's five, 33 of 45.

The twelve rows that pass, by the reason they pass:

| Reason a row passes | rows | which |
|---|---|---|
| only the replacement is stated | 3 | P3-C3, P7-C7, P9-C5 |
| only the superseded value is stated | 6 | P3-C9 (`<系统ID>-knowledge` 0 hits), P4-C6 (`设置时间(ms)` 0 hits in both articles), P4-C7, P4-C9 (`TRW` 0 hits in both), P7-C4, P7-C6 — every one of these is either stale or a lost correction, counted there |
| a directional statement resolves both | 2 | P3-C8 (L299), P7-C8 (「previously 0%」) |
| neither value is stated | 1 | P4-C10, `60%` and `90%` both absent |

Presence was checked on the files, not taken from the row notes: `11,362` and `25,046` appear
in P7's article in comma form (which is why C5 fails rather than passing on one value), the
only `7C` match in it is inside `7197C` (so C6 genuinely states one figure), all seven of
P10's pairs are present on both sides, and P4-C6's nanoseconds appear three times in the
old-half article and six in the newest-half one with no millisecond form in either.

Three things the column says that no other column here does:

1. **P10 and P5 go from the cleanest results in the set to complete failures** — 7 of 7 and 5
   of 5 — while their Staleness stays 0. Nothing about the articles changed; the rubric now
   reads the version-labelled table as two unordered values instead of as a resolved one.
2. **A trail does not guarantee a pass.** P3-C1 and P3-C5 each carry a correct directional
   statement *and* assert the superseded value as current elsewhere in the same article, so
   they fail. Self-contradiction, the failure mode the 2026-08-18 pass recorded as having no
   column, is 2 of the 18 same-article failures and is countable for the first time.
3. **The split rows are the classifier's and are reported apart.** All ten are P4's five and
   P9's five, in cases where no article ever held both values, so the gate reads 18 of 40 and
   the 10 sit beside it under [NG6](spec.md#non-goals) — the same decomposition the FX7 verdict
   applies to Staleness.

Read with Staleness, the strict figure this branch previously carried as an estimate is now
measured on this side: **Staleness ∪ In force is 32 of 40**, where the estimate had said
roughly 36. Thirteen rows are clean on Staleness and fail In force; fifteen fail both; four
fail Staleness alone.

### Two structural regressions, both from the classifier and not the writer

1. **Version-split chains.** P4's four versions split into a v1+v2 article and a v2+v3+v4
   article; P9's two versions split into a v1-only article and a v2-only article. These two
   cases hold **16 of the 45 contradiction rows**, and in them a trail is *impossible* — no
   article sees both values. They are also where all 14 of the arm's stale gating rows sit
   except P3's five. The union figures for P4 (9 of 10) and P9 (5 of 6) are the two worst in
   the set, while the newest-half articles read 3 of 10 and 0 of 6.
2. **Drops promoted from clean to lost by the split.** P9-D4 (「AB直选能力」) and P9-D6
   (「链式执行」) had no residue on the baseline. Here the v1-only article restates them, because
   v1 is its only source. Nothing about the writer's supersession behaviour changed; the
   corpus it was handed did.

Against that, the arm's own **resolution is much cleaner** — 14 of 18 chains resolve to one
article against the baseline's 8, and no article needed hand resolution — so the split is
concentrated, not pervasive.

## The ruling queue — all four settled

Same convention as [scoring.md's queue](scoring.md#the-ruling-queue--all-seven-settled): each
item was Captain's call and the default if ignored was the drafted position, which is what
the numbers above already used. **All four are ruled 2026-08-19, every one at its draft**, so
no figure in this document moves and the published gating rate is **19 of 40**.

Unlike the baseline's queue, none of these closes for want of evidence: this arm's articles
live in `~/kaas-arms/a1` and can be reopened. They are ruled on their merits.

| # | Location | The call | Drafted | Ruled | What settled it |
|---|---|---|---|---|---|
| **V35** | P3-C5 and P3-C8, [the open call](#open-call-drafted-name-residue-versus-proposition-residue) | Does residue that only reuses a superseded version's *name*, while the proposition itself is stated in its newer form, make a row stale? C5's L185 restates the proposition (one install completes setup) and C8's L508–510 only reuse three filenames over a tree that is v2's | No — name residue is recorded, not scored | **Ruled at the draft, 2026-08-19.** P3 holds at **5 of 9** and the total at 19 of 40 | It extends V34's main-proposition rule from conjunctions to residue rather than adding a rule: a name reused under a proposition stated in its v2 form asserts nothing about the superseded version. Scoring it the other way would have taken P3 to 6 of 9 and the total to 20 |
| **V36** | P4 and P9, [the open call](#open-call-drafted-how-a-chain-the-arm-distributes-should-resolve) | How does a chain the arm distributes across two articles resolve? The baseline's precedent excludes an article that does not declare the whole chain, which applied literally excludes *both* of P4's articles and makes the set's strongest failure case unscoreable | Score the union of the articles declaring any part of the chain, and report the newest-half article's figure beside it | **Ruled at the draft, 2026-08-19 — union, with the per-article figure reported beside it.** P4 stays **9 of 10**, P9 **5 of 6**, and the total **19 of 40** | The union is what the KB tells a reader who queries it, since that reader gets both articles; the per-article figure is what the writer earned. Reporting both is what makes the split visible as a classification failure rather than a write failure. **The alternative was recorded wrongly on this branch and is corrected here**: scoring the newest-half article only gives 8 of 40, not the 13 of 40 four documents carried, because the same rule applies to P9 (5 → 0) and not to P4 alone (9 → 3) |
| **V37** | P7-C4 and P7-C6 | Does an accurate as-of stamp defeat Staleness when the article offers nothing newer? Both rows state only the superseded figure, correctly stamped "As of 20260430", inside status sections whose headings carry the date | Not stale — the column measures a claim stated *as current*, and a dated status line does not state it as current; what those rows lose is the correction, already counted against them | **Ruled at the draft, 2026-08-19.** P7 holds at **0 of 8** and the total at 19 of 40 | V33's dissent pointed the other way from an Open Action Items table, which asserts its rows are outstanding now; these two sit under dated status headings instead, so the framing is historical rather than present-tense. Ruling with the dissent would have taken P7 to 2 of 8 and the total to 21 |
| **V38** | P7-C2, and the whole dated-pair tier | Is a version-labelled time series a Trail? 「As of 20260430, low-load governance **had completed** 17.6w … As of 20260514, low-load governance **has completed** 44.4w」 marks order by tense inside one sentence, where V28 excludes as-of stamped pairs | No — a Trail needs an explicit replacement claim; 「previously 0%」 qualifies and an as-of pair does not | **Ruled at the draft, 2026-08-19.** Trail holds at **5 of 45** | Counting tense-marked dated pairs would take Trail from 5 to as many as 20 of 45 and recreate precisely what V28 was ruled to prevent — a column that certifies parallel presentation as the decided option. The tense carries ordering; it does not say the older value has stopped being true |

None of the four changed the direction of the headline comparison, and the verdict does not
depend on any of them: on every drafted or alternative reading A1's Staleness is lower than
the baseline's 24 of 40 and its Trail is at or below the baseline's 7 of 45. The full
sensitivity band is 8–22 of 40, and it is tabulated in
[verdict-fx7.md](verdict-fx7.md#the-verdict-does-not-depend-on-any-of-the-four-rulings).

**A fifth ruling came out of this pass and is not in the queue above, because it is about the
rubric rather than about a row.** The `(0, 0)` finding — the arm's best cases producing the
shape D1 rejects while both columns read clean — was raised here as a bound and ruled as
**V39** in [test-set.md](test-set.md#v39-in-force--what-it-takes-to-leave-one-value-standing),
which adds the In force column measured above. It changes no figure in the queue and no
conclusion in the verdict; it changes what a future arm can be scored on.

## What this pass does not settle

**The FX7 verdict is written, and it is in [verdict-fx7.md](verdict-fx7.md): A1 does not
clear the positives, so A2 is required rather than optional.** What this document contributes
to it is the measurement and one finding that no column covered when it was made — **A1
shifted the failure mode rather than removing it.** The baseline stated superseded values as
current, unlabelled. This arm states them with their source attached, which clears the gating
column while producing exactly the coequal presentation D1 exists to reject. That finding is
what V39 turned into a column, so it is covered from 2026-08-19 onward and was not covered when
the verdict was taken.

What that costs the comparison is bounded and half of it is now measured. The bound was
recorded first as an estimate — if a basis-labelled parallel presentation counted as stale,
both arms land near 34–36 of 40 and A1's five-row advantage disappears — and it became
[V39](test-set.md#v39-in-force--what-it-takes-to-leave-one-value-standing), ruled the same
day as a **new column rather than a redefinition of Staleness**. That distinction is the whole
of what could be salvaged: redefining the gating column would have replaced a measured
comparison with a one-sided one, since this arm's articles can be re-read and the baseline's
cannot. So In force is measured here at **28 of 40**, the strict reading is **32 of 40** on
this side, and the baseline's "roughly 34" stays an estimate for good. The comparison on that
axis is not available and no arithmetic makes it available; what the column buys is a rubric
A2's arm can be scored against on both sides.
