# Brainstorm — derive a topic-scoped knowledge base from the catalog

Date: 2026-08-04
Slug: `derive-topic-kb-from-catalog`

## Problem statement

A KaaS knowledge base compiled from a broad corpus answers questions across
everything it ingested. There is no way to carve out the part of it that is
about one topic and hand that over as a knowledge base in its own right — to
scope an agent's `ask` tool to a subject, to give one team the slice of the
corpus that concerns them, or to compile a focused wiki without re-collecting
and re-ingesting the underlying documents by hand.

The catalog (`index/master-index.md`) already holds a one-line summary per
article, and `retrieval/retrieve.py:42` already asks an LLM which of those lines
are relevant to a query. That machinery is the cheap filter surface. What is
missing is turning a filter result into a new, compiled knowledge base.

## Users

- **KaaS operator with one large KB** who wants a topic-scoped KB to point an
  agent or a team at, without re-ingesting source material by hand.
- **AI agent over MCP** that has been asked to build a focused knowledge base
  about a subject and can already see the catalog through the `ask` tool.

## Non-goals

- Re-deriving or incrementally refreshing a derived KB when the source KB
  changes. A derived KB is a snapshot. Staleness, deletions, and conflicts with
  edits made inside the derived KB are a separate feature.
- Full multi-KB support in the Go service (registering N independent knowledge
  bases, per-KB worker/queue/session state, a KB switcher). Derived KBs are
  reachable through a selector on the existing read paths, not through a
  general multi-KB refactor.
- Changing the shared compile prompts (`core/extract.py`, `core/merge.py`) to
  make them topic-aware.
- Deriving from anything other than a KaaS KB that has already been compiled and
  has an `index/master-index.md`.

## Decisions taken (from brainstorming Q&A)

| # | Question | Decision |
|---|---|---|
| 1 | What does the derived KB ingest? | The **un-compiled source documents**. For each matching article, read its `sources:` frontmatter, resolve those `raw/*.md` files inside the source KB, dedupe the union, copy into the derived KB's `raw/`, then run `compile_kb()`. Not the compiled `wiki/*.md` articles — re-feeding a compiled article through extract → classify → write is second-generation distillation. |
| 2 | Resolve `sources:` to the KB copy or the on-disk original? | The **KB copy** (`<source-kb>/raw/*.md`). Self-contained: no dependency on the original file still existing, being unmoved, or being on this machine. |
| 3 | How is "related to a topic" decided? | **One LLM call over the whole catalog**, returning every matching path with no top-K cap. Follows the existing `_select_relevant` pattern. Handles synonyms and framing, which a substring match over tags/title/summary cannot. |
| 4 | Where does a derived KB live? | Nested: **`<source-kb>/derived/<slug>/`**, each with its own `raw/`, `wiki/`, `index/` and a `manifest.json`. Read paths (`ask`/chat/wiki) take an optional derived-KB selector; default stays the root KB. One server, one data root, no new deployment story. |
| 5 | Which surfaces? | **All three**: Python CLI (`kb-ai derive`), MCP tool, HTTP API + web UI. |
| 6 | Snapshot or live link? | **Snapshot plus a provenance manifest**: source KB path, topic, timestamp, selected article paths, resolved source documents and their checksums, and what was skipped. No re-derive logic; the record makes it auditable and makes re-derive possible later. |
| 7 | A document is broader than the topic — accept the bleed? | **Second filter pass after compiling.** Compile the derived KB from the full documents, then run the same topic filter over the *derived* catalog and move non-matching articles to `derived/<slug>/_offtopic/` (moved, not deleted), then reindex. Costs one extra LLM call. |
| 8 | A matching article has no `sources:` | **Skip it and report it.** It contributes no documents; it is named in the run report and in the manifest as unresolved. `sources:` is LLM-written from a prompt template, not a machine-enforced field, so this case is expected rather than exceptional. |

## Key assumptions to verify in tech design

1. **Nesting is inert.** `KBStore._iter_raw_paths` globs `<base>/raw/**/*.md` and
   `update_markdown_index` globs `<base>/wiki/**/*.md`; a derived KB at
   `<base>/derived/<slug>/{raw,wiki}` falls outside both, so the source KB's own
   compile and index should not see it. The Go scanner, the wiki tree API, and
   the cost-estimate path need the same check before this is relied on.
2. **Catalog fits one prompt.** The filter sends the whole catalog in one call.
   With `SUMMARY_MAX_CHARS=200` and `KEYS_MAX_CHARS=500` a line can reach ~800
   chars, so `MAX_PROMPT_CHARS` (80K) is reached somewhere around 100 articles.
   Behaviour past that point — batch, or fail loudly — is an open question.
3. **Compiling a derived KB reuses the existing pipeline unchanged.**
   `compile_kb(kb_dir, …)` is parameterised by directory, so pointing it at
   `derived/<slug>/` should need no pipeline change.
4. **`sources:` values are KB-relative `raw/…` paths.** Confirmed for the write
   template (`core/merge.py:441`) and `apply_diff` (`core/merge.py:294-325`).
   Path containment must still be enforced via `KBStore._resolve` — the values
   are LLM-written and therefore attacker-influenced.

## Open questions for the spec

- Catalog larger than one prompt budget: batch the filter, or fail with a clear
  message? (Assumption 2.)
- Where does the slug come from — user-supplied, or derived from the topic
  string? What happens when `derived/<slug>/` already exists?
- Does the second filter pass reuse the identical prompt as the first, or does
  filtering compiled-from-scratch articles need different wording?
- Cost visibility: the existing pipeline has a cost-review/approval path
  (`raw/_skipped/`). Does derive route through it, or report cost after the fact?

## Scope concern (flagged, not acted on)

Three surfaces span Python, Go and TypeScript in one feature. The Python CLI is
the only one that is complete on its own; MCP and HTTP/UI both depend on the
derived-KB selector threading through read paths. Recommendation is to keep all
three in scope as chosen, but sequence them in the plan so the CLI slice is
verifiable before the Go and web work starts. Raised again at Step 6.
