# Tech design — derive a topic-scoped knowledge base from the catalog

Date: 2026-08-04
Slug: `derive-topic-kb-from-catalog`
Spec: [spec.md](spec.md) · Brainstorm: [brainstorm.md](brainstorm.md)

## Overview

Derive is a Python-side orchestration over machinery that already exists: read
the source catalog with `KBStore.existing_articles()`, ask an LLM which lines
match the topic, follow each match's `sources:` frontmatter to the un-compiled
documents, copy those into a nested KB at `<source-kb>/derived/<slug>/`, and run
the unchanged `compile_kb()` on it. A second filter pass over the resulting
catalog moves off-topic articles aside. No pipeline, prompt, or storage change is
needed for the core — `compile_kb(data_dir, …)` is already parameterised by
directory (`commands/compile.py:62`).

The Go and TypeScript work is read-path plumbing plus one new job type. Nothing
in the existing service can see a derived KB today, which is the property that
makes nesting safe and also the reason each read path needs a selector.

## Architecture

```
                    ┌─────────────────── Stage 1: Python core ───────────────────┐
                    │                                                            │
 kb-ai derive ──────▶ derive/__init__.derive_kb()                                │
   (CLI, F1–F6)     │      │                                                     │
                    │      │ 1. KBStore(source, read_only=True)                  │
                    │      │      .existing_articles()          ── catalog       │
                    │      ▼                                                     │
                    │  _filter.select_by_topic(catalog, topic, mode=RECALL)      │
                    │      │   batches by prompt budget, unions results (A6–A8)  │
                    │      ▼                                                     │
                    │  _sources.resolve_documents(source_store, selected)        │
                    │      │   frontmatter sources: ──▶ raw/*.md, deduped (B1–B5)│
                    │      ▼                                                     │
                    │  _layout.create(source_kb, slug, force)  ── derived dir    │
                    │      │   + write manifest.json (E1, E2)                    │
                    │      ▼                                                     │
                    │  ◀── volume gate (F5): documents, bytes, --yes ──          │
                    │      ▼                                                     │
                    │  compile_kb(derived_dir, …)   ── UNCHANGED (D1)            │
                    │      ▼                                                     │
                    │  _offtopic.prune(derived_store, topic, mode=PRECISION)     │
                    │      │   move wiki/x.md ──▶ _offtopic/x.md (D2, D7)        │
                    │      │   update_markdown_index() (D3)                      │
                    │      ▼                                                     │
                    │  DeriveReport ──▶ manifest update (E3)                     │
                    └────────────────────────────────────────────────────────────┘

 Stage 2:  MCP ask{kb} ──▶ resolve_kb_dir(root, slug) ──▶ iterative_retrieve(derived)
 Stage 3:  POST /api/derive ──▶ derived_jobs table ──▶ runner ──▶ bridge cmd "derive"
           GET /api/wiki?kb=  GET /api/derived   web KB selector
```

## Stage 1 — Python core and CLI

### Module layout

```
py/src/kb_ai/derive/
├── __init__.py     # derive_kb() orchestrator, DeriveReport, error types
├── _filter.py      # select_by_topic() + budget batching
├── _sources.py     # sources: parsing, document resolution
├── _layout.py      # slug normalisation, derived-dir creation, manifest I/O
└── _offtopic.py    # second pass, move, reindex
py/src/kb_ai/commands/derive.py   # argparse, volume gate, respond()
```

Five files rather than one because the concerns are independently testable and a
single module lands near 400 lines. This follows the `commands/pipeline/`
precedent (a package per multi-phase command) rather than inventing a shape. The
CLI stays in `commands/` like every other entry point, so `derive/` holds no
argparse and no `respond()` — it is importable from the daemon (Stage 3) without
dragging CLI concerns along.

### Key interfaces

```python
# derive/__init__.py
Selector = Callable[[list[ArticleMeta], str], SelectionResult]

@dataclass(frozen=True)
class Skipped:
    ref: str
    reason: str   # see reason vocabulary below

@dataclass(frozen=True)
class SelectionResult:
    paths: list[str]
    batches: int
    dropped_invented: int
    skipped: list[Skipped]     # oversized catalog lines (A8)

@dataclass
class DeriveReport:
    derived_kb: str
    slug: str
    topic: str
    selected_articles: list[str]
    skipped_articles: list[Skipped]
    skipped_documents: list[Skipped]
    documents: list[DocumentRef]        # rel_path + checksum
    dropped_invented_paths: int
    filter_batches: int
    offtopic_articles: list[str]
    compiled: bool
    compile: dict | None
    warnings: list[str]

def derive_kb(
    source_kb: str,
    topic: str,
    *,
    slug: str | None = None,
    force: bool = False,
    model: str,
    select: Selector | None = None,       # None → _filter.select_by_topic
    compile_fn: Callable | None = None,   # None → commands.compile.compile_kb
    approve: Callable[[DeriveReport], bool] | None = None,  # None → auto-approve
) -> DeriveReport
```

`select`, `compile_fn` and `approve` are injected and default late (`None`),
matching the `summary_max_chars=None` idiom in `storage/index.py:110`. This is
what makes I1 achievable: every test drives the orchestrator with a stub selector
and a stub compile, and no test needs a real LLM. `approve` is how the CLI's
volume gate (F5) reaches into the middle of the orchestration without the core
knowing about TTYs or `--yes`.

Reason vocabulary, fixed so the manifest is machine-readable:

| Reason | Meaning | Criterion |
|---|---|---|
| `no_sources_key` | frontmatter has no `sources:` | B2 |
| `empty_sources` | `sources:` present but empty | B2 |
| `unparseable_frontmatter` | YAML error or no frontmatter block | B2 |
| `article_unreadable` | article path in catalog but unreadable | B2 |
| `escapes_kb` | `sources:` entry rejected by `_resolve` | B3 |
| `document_missing` | `sources:` entry names a nonexistent file | B4 |
| `document_unreadable` | present but `OSError` on read | B4 |
| `line_over_budget` | one catalog line exceeds a whole batch | A8 |

### Errors

New subclasses of the existing `KBError` (`_errors.py`), which already carries a
machine-readable `code` that `respond_error` surfaces:

```python
class DeriveError(KBError):            code = "DERIVE_FAILED"
class NoCatalogError(DeriveError):     code = "NO_CATALOG"
class InvalidSlugError(DeriveError):   code = "INVALID_SLUG"
class SlugExistsError(DeriveError):    code = "SLUG_EXISTS"
class NestedDeriveError(DeriveError):  code = "NESTED_DERIVE"
class NoDocumentsError(DeriveError):   code = "NO_DOCUMENTS"
```

A5's filter failure surfaces as `DeriveError` wrapping the LLM exception —
derive fails loudly where `retrieval._select_relevant` deliberately degrades to
`[]`, because an empty selection would silently build an empty KB.

### Catalog rendering, shared with retrieval

A5 requires the same `| keys:` column retrieval uses. Rather than copy the
f-string from `retrieve.py:53`, extract it:

```python
# storage/store.py — next to KEYS_MARKER, which it consumes
def render_catalog_line(a: ArticleMeta) -> str:
    return f"- {a.path} — {a.title}: {a.summary}" + (f"{KEYS_MARKER}{a.keys}" if a.keys else "")
```

`retrieve._select_relevant` is changed to call it. That is a two-line change to
existing code, justified by the alternative being two renderers that drift — a
keys-column change would otherwise silently stop reaching derive.

### Batching (A6–A8)

Budget follows the `core/classify.py:109` pattern — measure the skeleton, not a
magic number:

```
budget = MAX_PROMPT_CHARS - len(prompt_skeleton(topic, mode)) - _SAFETY_MARGIN
```

Greedy pack rendered lines into batches under `budget`; a single line longer than
`budget` is dropped as `line_over_budget` rather than making the run
unschedulable. Each batch is one `completion_json` call; results are unioned
preserving first-seen order, then filtered to catalog membership and
de-duplicated. One batch and ten batches return the same `SelectionResult`
shape (A7), and `batches` is reported so a run's cost is explainable.

Batches run sequentially in v1. Parallelising them is a later change: the
existing pipeline has its own worker-count plumbing and borrowing it here would
be scope creep for a call count that is single-digit on realistic catalogs.

### Filter prompt and the two modes — resolving O4

One prompt template, two modes, because the two passes have opposite failure
costs:

- **`RECALL`** (first pass, over the source catalog). A missed article loses its
  documents permanently — they never enter the derived KB. Instruction: *include
  an article if it could contribute to understanding the topic, even
  peripherally.*
- **`PRECISION`** (second pass, over the derived catalog). Every article here was
  compiled from documents already judged topical, so a permissive prompt selects
  everything and the pass does nothing. Instruction: *include an article only if
  it is substantially about the topic; peripheral mentions do not qualify.*

Both use the same model, the same renderer and the same batching. D6 is the
backstop: if `PRECISION` selects nothing, everything stays put and the report
carries `second_pass_selected_nothing`. The smoke run (I3) measures the actual
move ratio, which is the only honest way to know whether the two modes are
separated enough.

### `--force` safety

C4 lets `--force` replace an existing `derived/<slug>/`, which is a recursive
delete driven by a user-supplied string. Two guards, both required:

1. Lexical validation first (C3): single path segment, not `.` or `..`, matching
   `^[a-z0-9][a-z0-9-]{0,39}$`. Checked before the path is built, so a hostile
   slug never reaches the filesystem.
2. The target must contain a `manifest.json` whose `slug` matches. `--force`
   replaces a directory *derive created*; it refuses to delete anything else.
   Without this, a mistyped `--kb` pointing at a real KB plus `--force` is a data
   loss bug.

### Extract-cache reuse (decided: included)

`load_extract_cache(checksum)` keys on the document's content checksum
(`store.py:202`, `_compute_checksum` at `store.py:41`). The documents copied into
a derived KB are byte-identical to their source-KB originals, so their checksums
match — meaning copying the corresponding
`<source>/.extract-cache/<checksum>.json` files into the derived KB makes the
derived compile skip **every extract call**, which is the per-document bulk of
compile cost. Classify and write still run.

Roughly 15 lines: while copying each document, copy
`<source>/.extract-cache/<checksum>.json` when it exists. A missing entry is not
an error — the derived compile simply extracts that document itself.

Documented caveat: the cache key contains no model or prompt version, so a
derived KB compiled with a different model than the source reuses the other
model's extractions. This is already true within a single KB today, so reuse
across KBs is no worse; it is stated here rather than left to be discovered.
Copying (not symlinking) keeps the derived KB self-contained, so deleting the
source KB cannot invalidate it.

## Stage 2 — MCP `ask` kb selector (G3, G4)

One shared resolver, used by every read path in Stages 2 and 3:

```python
# derive/_layout.py
def resolve_kb_dir(root_kb: str, slug: str | None) -> str:
    """Root KB when slug is None; else <root>/derived/<slug> if it exists.

    Raises InvalidSlugError on a slug failing lexical validation and
    UnknownDerivedKBError when no such derived KB exists -- never falls back to
    the root KB, because answering from the wrong corpus silently is worse than
    an error (G3).
    """
```

Python side (`server_mcp.py:58`): `ask()` gains `kb: str | None`, passes
`resolve_kb_dir(...)` to `iterative_retrieve`. Go side: `askInputSchema`
(`internal/mcp/schema.go:6`) gains a `kb` property, and the handler forwards it
through the existing chat/ask bridge payload. Both need it — the Go MCP server is
the remote transport and the Python one is stdio.

Validation happens in Go *and* Python. The Go layer's containment check is
lexical (matching `internal/api/wiki.go`'s `safeJoin` convention) and the Python
layer's resolves symlinks (matching `KBStore._resolve`, which deliberately
rejects a symlinked subtree). Duplicating the check is intentional: neither layer
should trust the other's input.

## Stage 3 — HTTP API and web UI

### The queue problem (a finding, not a detail)

H1 says "enqueues through the existing queue/worker path". Inspecting it, that
path does not fit:

- `Task` is document-shaped: `RawPath` (a file under `<kb_dir>/raw`),
  `ContentHash` with a **unique index** (`store.go:50`, `ErrDuplicate`).
- `Worker.Process` reads `os.ReadFile(task.RawPath)` and runs extract → pipeline
  for that one document (`worker.go:84-125`).
- `Stage*` values (`extract`, `pipeline`, `index`) describe one document's
  progress, not filter → resolve → compile → prune.

Forcing derive into `Task` means a synthetic `ContentHash` (where re-deriving the
same topic collides with `ErrDuplicate`), a meaningless `RawPath`, and a branch
at the top of `Process`. Two honest options; **Option A is the decided one.**

**Option A (decided) — a separate `derived_jobs` table and runner.**
Columns: `slug` (unique), `topic`, `status`, `stage`, `error`, `result` JSON,
timestamps. A single-flight runner goroutine started next to the dispatcher
claims pending jobs and calls a new bridge command. The compile queue is
untouched, so a derive cannot starve or break document ingestion, and `slug`
being unique gives the "one derive per slug at a time" guard for free. Costs a
migration, a small store, and a runner (~200 lines Go + tests).

**Option B — a `kind` column on `Task`.** Add `kind` (`"compile" | "derive"`) and
a `payload` JSON column, make `ContentHash` nullable-unique, branch `Process`.
Fewer moving parts conceptually, but it changes the hot path every document
ingestion goes through, and the unique-index semantics get subtler. I would not
put a KB-level job in a per-document queue to save a table.

The rest of Stage 3 assumes Option A.

### Endpoints

| Endpoint | Behaviour |
|---|---|
| `POST /api/derive` | `{topic, slug?, model?}` → insert `derived_jobs` row, return `{job_id, slug}` (202). No volume gate — async, nobody to prompt (H5). |
| `GET /api/derive/{id}` | Job status, stage, error, result (cost, counts). |
| `GET /api/derived` | List from manifests: `[{slug, topic, created_at, article_count}]` (H2). |
| `GET /api/wiki?kb=` | Existing tree handler, rooted at the resolved KB (H3). |
| `GET /api/wiki/file?kb=` | Existing file handler, same resolution (H3). |
| chat path `?kb=` | Forwards `kb` into the bridge chat payload (H3). |

`handleListWiki` caches one tree in `s.wikiC` keyed on a single directory's
modtime (`internal/api/wiki.go:167-185`). With a selector that becomes a
`map[string]*wikiCacheEntry` keyed by slug (`""` for root), each entry keeping
its own modtime and TTL. Leaving it single-entry would thrash the cache the
moment a user switches KBs.

### Bridge command

New `derive` command following the established shape: `DeriveRequest` /
`DeriveResponse` in `internal/bridge/api.go`, a `Derive()` method on the daemon
client (`daemon_client.go`, mirroring `Index()` at line 209), and an
`elif cmd == "derive"` branch in `server_daemon.py:343`'s dispatch. Non-streaming
`call`, since progress granularity per derive stage is not worth a stream in v1 —
the job row's `stage` column carries it.

### Web

- `web/src/api/derived.ts` — `listDerived()`, `startDerive()`, `getDeriveJob()`,
  following `api/wiki.ts` conventions.
- KB selector in the wiki view using the existing `@radix-ui/react-select`, with
  the selected slug in a Zustand store (matching `web/src/store/`) so the wiki
  tree and chat read the same value.
- Every `api/wiki.ts` and chat call threads the slug as `?kb=`.
- i18n: `en` and `zh` entries for every new string in
  `web/src/i18n/strings.ts` (H6). The `zh` map is one of CLAUDE.md's two
  explicit exceptions to the English-only rule.

## Dependencies

- **Internal, unchanged**: `compile_kb`, `update_markdown_index`, `KBStore`,
  `completion_json`, `CostTracker`, the queue/dispatcher (untouched under
  Option A).
- **Internal, changed**: `retrieve._select_relevant` (extracted renderer),
  `storage/store.py` (+`render_catalog_line`), `server_mcp.ask` (+`kb`),
  `internal/mcp/schema.go` (+`kb`), `internal/api/wiki.go` (cache keyed by slug,
  `?kb=`), `internal/store` (+`derived_jobs`), `internal/bridge` (+`derive`).
- **External**: none. No new Python, Go or npm dependency.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Off-topic bleed is larger than expected.** One broad document behind one matching article drags its whole subject in; the derived KB is compiled from mostly-irrelevant text and the second pass moves most of it aside — real money spent on articles that end up in `_offtopic/`. | The volume gate (F5) shows document count and bytes before spending. The smoke run (I3) records the move ratio, which is the number that says whether this design works. If the ratio is bad, the honest fix is filtering at the article level, i.e. revisiting brainstorm decision 1 — not tuning prompts. |
| **Second pass empties the wiki.** A `PRECISION` prompt that is too strict moves nearly everything. | D6: selecting nothing leaves everything in place and warns. Moves, never deletes (D2). |
| **`--force` deletes the wrong directory.** | Lexical slug validation before path construction, plus requiring a matching `manifest.json` in the target. |
| **`sources:` is LLM-written, so path values are attacker-influenced.** | All reads go through `KBStore.read_raw` → `_resolve`, which resolves symlinks and rejects escapes; rejection is recorded, never fatal (B3). |
| **`kb=` selector reaches the server from MCP and HTTP clients.** | Lexical validation in Go, symlink-resolving validation in Python, existence checked against `derived/` before use. No fallback to the root KB on an unknown slug. |
| **Concurrent derives of the same slug corrupt a directory.** | `derived_jobs.slug` unique under Option A; the CLI's `SLUG_EXISTS` covers the CLI path. Two concurrent CLI runs on a fresh slug remain a known gap, documented rather than locked. |
| **Nesting turns out not to be inert** (e.g. a future feature globs `<kb>/**/*.md`). | C6 is a test, not a comment: it compiles a source KB after deriving and asserts the derived documents are neither re-compiled nor indexed. |
| **Rollback.** | Everything the feature writes lives under `derived/<slug>/`. Deleting that directory removes all trace; no source-KB state is mutated, and `.compile-state.json` for the source is untouched. |

## Alternatives considered

- **Copy compiled articles instead of documents** (brainstorm option A). Cheapest
  by far — one LLM call and a file copy, no compile. Rejected because a derived
  KB would be a filtered view of the source's articles rather than a KB compiled
  around the topic, and because re-feeding compiled articles through the pipeline
  is second-generation distillation. Worth revisiting if the smoke run shows the
  bleed ratio is bad enough to make the compile mostly waste.
- **Deterministic tag/substring filtering.** Free and reproducible, and it would
  have removed the LLM from the critical path entirely. Rejected in brainstorming:
  it cannot match a topic phrased differently from the article's own vocabulary,
  which is most of the value.
- **Sibling derived KBs outside the source KB.** Simpler for the Go service (no
  selector), but the web UI could then never show a derived KB, making Stage 3
  pointless.
- **`kind` column on `Task`** — see Stage 3 Option B.
- **Topic-aware compile prompts.** Would produce the best derived KB by threading
  the topic into extract and write. Rejected as a non-goal: it changes prompts
  shared by every existing caller for one new use case.

## Test strategy

| Layer | Approach |
|---|---|
| `_filter` | Stub `completion_json`; assert union across batches, budget packing, oversized-line skip, invented-path drop, uncapped result, raise-on-error. |
| `_sources` | Fixture articles covering all eight skip reasons; assert dedup, stable order, and that no single bad entry aborts. |
| `_layout` | Pure: slug normalisation table-driven, `INVALID_SLUG` cases, `SLUG_EXISTS`, `--force` refusing a directory with no matching manifest, `NESTED_DERIVE`. |
| `_offtopic` | Stub selector; assert move-not-delete, path preservation, reindex, D5 (no dir created) and D6 (nothing moved + warning). |
| `derive_kb` | End-to-end with stub selector and stub compile (I2): fixture KB in `tmp_path`, assert layout, manifest contents, report counts, and the `approve` callback declining leaves `compiled:false`. |
| C6 | Real `update_markdown_index` on the source after deriving; assert derived articles absent from the source catalog and derived documents absent from the source's raw scan. |
| CLI | `respond` payload shape per F2/F3, `--yes` bypassing the gate, TTY-less non-`--yes` behaviour. |
| Go | `derived_jobs` store CRUD and unique-slug conflict; `?kb=` resolution accept/reject table; wiki cache keyed by slug (switching KBs does not serve a stale tree); bridge `derive` marshalling. Table-driven, stdlib `testing`, hand-written mocks — matching the existing packages. |
| Web | Vitest + `@testing-library/react`: KB selector drives the tree query, i18n keys present in both `en` and `zh`. |
| Smoke (I3) | Real derive against a KB compiled from this repository. Record in `notes.md`: topic, articles matched, documents resolved and bytes, articles moved off-topic, filter batches, and total cost with model. |
