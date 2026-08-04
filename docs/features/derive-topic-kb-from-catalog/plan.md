# Derive a topic-scoped knowledge base — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Date: 2026-08-04
Slug: `derive-topic-kb-from-catalog`
Spec: [spec.md](spec.md) · Tech design: [tech-design.md](tech-design.md) · Brainstorm: [brainstorm.md](brainstorm.md)

**Goal:** Given a compiled KaaS knowledge base and a topic string, produce a new
compiled knowledge base at `<source-kb>/derived/<slug>/` holding only the
documents behind the articles that match the topic, reachable from the CLI, MCP
`ask`, and the HTTP API + web UI.

**Architecture:** A Python orchestration package (`kb_ai/derive/`) filters the
source catalog with an LLM, follows each matching article's `sources:`
frontmatter to the un-compiled `raw/*.md` documents, copies them (plus their
extract-cache entries) into a nested KB, runs the unchanged `compile_kb()` on it,
then runs a second, stricter filter pass over the derived catalog and moves
off-topic articles to `_offtopic/`. Go and TypeScript work is read-path plumbing
(`?kb=<slug>` / `kb` MCP argument) plus one new job table and runner.

**Tech Stack:** Python 3.13 (uv, pytest), Go 1.26 (stdlib `testing`,
`modernc.org/sqlite`), React 19 + Vite + Zustand + Vitest.

## Global Constraints

- **English only.** Every artifact — replies, docs, code comments, TODO notes,
  commit messages, branch names, PR text, log messages, error strings, LLM
  prompts — is English. The only exception is the `zh` map in
  `web/src/i18n/strings.ts`. When dispatching any subagent, the prompt MUST
  include: "Write everything in English — your replies, documentation, code
  comments, commit messages and PR text. The only exception is a file explicitly
  named as a translation, such as README.zh-CN.md."
- **No new dependency** in Python, Go or npm.
- **No change to the compile pipeline or its prompts** (`core/extract.py`,
  `core/merge.py`, `commands/pipeline/`). `compile_kb` is called as-is.
- **No test may call a real LLM.** Every filter is injected or monkeypatched
  (spec I1). The only real-LLM run is the manual smoke run in Task 10.
- **Python style:** `from __future__ import annotations` at the top of every new
  module, builtin generics (`list[str]`, `str | None`), frozen `@dataclass` for
  value objects, `snake_case`, module docstring naming the spec criteria the
  module implements.
- **Go style:** `cmd/` + `internal/`, errors wrapped with `fmt.Errorf("...: %w")`,
  exported sentinels prefixed with the package name, table-driven stdlib tests,
  hand-written fakes.
- **TypeScript style:** `strict`, zero `any`, `import type`, module-level
  exported functions (no classes), `@/` alias, Vitest co-located as `x.test.ts`.
- **Commits:** Conventional Commits with a fine scope, e.g.
  `feat(derive): add topic filter with prompt-budget batching`. One commit per
  task, English subject and body.
- **Test commands:** `cd py && uv run pytest tests/ -v` · `go test ./... -count=1`
  · `cd web && pnpm test`.

## Decisions this plan makes that the tech design left open or stated loosely

Recorded here so no implementer has to re-derive them:

1. **Error classes live in `py/src/kb_ai/_errors.py`**, not in
   `derive/__init__.py`. `_layout`, `_filter` and `_sources` all raise them, and
   `derive/__init__.py` imports those modules — defining the errors in the
   package `__init__` would create an import cycle. `_errors.py` is already the
   single home of every `KBError` subclass.
2. **Shared dataclasses live in `derive/_types.py`** for the same reason,
   mirroring the existing `kb_ai/_types.py` ("defines domain types used across
   multiple layers to avoid circular dependencies").
3. **Slug availability is checked before the first LLM call**, and the derived
   directory is created after documents resolve. The tech design's diagram
   places `_layout.create` after the filter; checking availability up front
   means a `SLUG_EXISTS` failure costs nothing, while B5 ("zero documents creates
   no derived directory") still holds.
4. **`DocumentRef` carries `size_bytes`** and the manifest records it. Spec E2
   lists the fields the manifest *contains*; this is a superset. The volume gate
   (F5) needs bytes, and re-reading every document to sum sizes would double the
   I/O.
5. **Document content is not held in memory.** `resolve_documents` returns refs
   only; the copy step re-reads each file through `store.read_raw`. Holding
   content would mirror `compile_kb`'s `list_raw_files()`, which the codebase
   already flags as a memory TODO.
6. **A malformed filter response raises `DeriveError`** (not "return `[]`"),
   matching A3's reasoning: silently empty selection builds an empty KB.
7. **`sources:` entries are comma-split.** A batch merge writes several
   documents into one entry: `commands/compile.py` passes
   `", ".join(merge_rels)` as `source_path`, and `core/merge.py:_apply_diff`
   appends it as a single `  - raw/a.md, raw/b.md` line. Treating that as one
   path would lose every document in a batch-merged article.
8. **Whole-run cost is read from `kb_ai.llm.tracker` after the second pass.**
   `compile_kb`'s returned `cost` is a snapshot taken before the `PRECISION`
   pass runs, so it cannot be the run total. The manifest gets both: `compile`
   (the `compile_kb` result verbatim, E3) and `cost` (the final tracker summary).
9. **Chat takes `kb` as a query parameter**, matching spec H3's `?kb=` wording
   for all three read paths and leaving `decodeJSON`'s `DisallowUnknownFields`
   body contract untouched.
10. **The Go containment check lives in a new `internal/kbpath` package**,
    because both `internal/mcp` and `internal/api` need it and `api` already
    imports `mcp` (so it cannot live in `api`).

## File structure

### Stage 1 — Python core and CLI

| File | Responsibility |
|---|---|
| `py/src/kb_ai/_errors.py` (modify) | `DeriveError` + six subclasses |
| `py/src/kb_ai/storage/store.py` (modify) | `render_catalog_line()` — the one catalog-line renderer |
| `py/src/kb_ai/retrieval/retrieve.py` (modify) | calls the shared renderer |
| `py/src/kb_ai/derive/_types.py` (new) | `Skipped`, `SelectionResult`, `DocumentRef`, `DeriveReport`, mode constants |
| `py/src/kb_ai/derive/_layout.py` (new) | slug rules, derived-dir creation, document + cache copy, manifest I/O, `resolve_kb_dir` |
| `py/src/kb_ai/derive/_filter.py` (new) | `select_by_topic()` with two modes and prompt-budget batching |
| `py/src/kb_ai/derive/_sources.py` (new) | `sources:` parsing and document resolution |
| `py/src/kb_ai/derive/_offtopic.py` (new) | second pass, move, reindex |
| `py/src/kb_ai/derive/__init__.py` (new) | `derive_kb()` orchestrator |
| `py/src/kb_ai/commands/derive.py` (new) | argparse, volume gate, `respond()` |
| `py/src/kb_ai/__main__.py` (modify) | register the `derive` command |

Tests: `py/tests/test_derive_layout.py`, `test_derive_filter.py`,
`test_derive_sources.py`, `test_derive_offtopic.py`, `test_derive_kb.py`,
`test_commands_derive.py`, `test_derive_nesting.py`.

### Stage 2 — MCP read selector

| File | Responsibility |
|---|---|
| `py/src/kb_ai/server_mcp.py` (modify) | `ask(kb=...)` resolving through `resolve_kb_dir` |
| `internal/kbpath/kbpath.go` (new) | lexical slug validation + `Resolve(root, slug)` |
| `internal/mcp/schema.go` (modify) | `kb` property on `askInputSchema` |
| `internal/mcp/ask.go` (modify) | `askArguments.KB`, resolve, forward as `KBDir` |

### Stage 3 — HTTP API and web UI

| File | Responsibility |
|---|---|
| `internal/store/store.go` (modify) | `DerivedJob` entity, status constants, `DerivedJobStore` interface |
| `internal/store/sqlite/derived.go` (new) | `derived_jobs` schema + CRUD + claim |
| `internal/store/sqlite/sqlite.go` (modify) | run the new migration |
| `internal/bridge/api.go` (modify) | `DeriveRequest` / `DeriveResponse` |
| `internal/bridge/daemon_client.go` (modify) | `Derive()` |
| `py/src/kb_ai/server_daemon.py` (modify) | `derive` command handler |
| `internal/derive/runner.go` (new) | single-flight job runner |
| `internal/api/derive.go` (new) | `POST /api/derive`, `GET /api/derive/{id}`, `GET /api/derived` |
| `internal/api/wiki.go` (modify) | `?kb=` on tree + file, cache keyed by slug |
| `internal/api/chat.go` (modify) | `?kb=` forwarded as `KBDir` |
| `internal/api/server.go` (modify) | routes, `DerivedJobStore` dependency, cache type |
| `cmd/kaas/main.go` (modify) | wire the runner alongside the dispatcher |
| `web/src/api/derived.ts` (new) | `listDerived`, `startDerive`, `getDeriveJob` |
| `web/src/store/kb.ts` (new) | selected-KB Zustand store |
| `web/src/api/wiki.ts`, `web/src/api/chat.ts` (modify) | thread `kb` |
| `web/src/features/wiki/KBSelector.tsx` (new) | root + derived KB picker |
| `web/src/features/wiki/DeriveDialog.tsx` (new) | start a derive, poll the job |
| `web/src/pages/Wiki.tsx` (modify) | mount selector + dialog, refetch on switch |
| `web/src/i18n/strings.ts` (modify) | `en` + `zh` for every new string |

---

# Stage 1 — Python core and CLI

Covers spec A–F and I1–I3. Complete and useful on its own; ends with a real
smoke run.

## Task 1: One catalog-line renderer shared with retrieval

Spec: A5. Tech design: "Catalog rendering, shared with retrieval".

**Files:**
- Modify: `py/src/kb_ai/storage/store.py` (add after `KEYS_MARKER`, line 13)
- Modify: `py/src/kb_ai/retrieval/retrieve.py:53-55`
- Test: `py/tests/test_storage.py` (append)

**Interfaces:**
- Consumes: `ArticleMeta`, `KEYS_MARKER` (both already in `storage/store.py`).
- Produces: `kb_ai.storage.store.render_catalog_line(a: ArticleMeta) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `py/tests/test_storage.py`:

```python
def test_render_catalog_line_without_keys():
    from kb_ai.storage.store import ArticleMeta, render_catalog_line

    a = ArticleMeta(title="Pricing Model", path="wiki/pricing.md",
                    summary="How fees are computed.")
    assert render_catalog_line(a) == "- wiki/pricing.md — Pricing Model: How fees are computed."


def test_render_catalog_line_appends_keys_column():
    from kb_ai.storage.store import KEYS_MARKER, ArticleMeta, render_catalog_line

    a = ArticleMeta(title="Limits", path="wiki/limits.md",
                    summary="Configured ceilings.", keys="max_zip_entries, max_body")
    line = render_catalog_line(a)
    assert line.endswith(f"{KEYS_MARKER}max_zip_entries, max_body")
    assert line.startswith("- wiki/limits.md — Limits: Configured ceilings.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py && uv run pytest tests/test_storage.py -k render_catalog_line -v`
Expected: FAIL with `ImportError: cannot import name 'render_catalog_line'`

- [ ] **Step 3: Add the renderer**

In `py/src/kb_ai/storage/store.py`, directly after the `KEYS_MARKER` constant:

```python
def render_catalog_line(a: ArticleMeta) -> str:
    """Render one catalog line the way the master index writes it.

    Shared by retrieval's page selection and derive's topic filter: two copies of
    this f-string would drift, and a change to the keys column would silently
    stop reaching one of them.
    """
    return (f"- {a.path} — {a.title}: {a.summary}"
            + (f"{KEYS_MARKER}{a.keys}" if a.keys else ""))
```

Note: it must be defined *below* the `ArticleMeta` dataclass, so place it after
`ArticleMeta` (line 25) rather than immediately after `KEYS_MARKER` if the module
is read top-to-bottom — the annotation is a string under
`from __future__ import annotations`, so either position runs, but keep it next to
`ArticleMeta` for legibility.

- [ ] **Step 4: Use it in retrieval**

In `py/src/kb_ai/retrieval/retrieve.py`, change the import on line 28:

```python
from kb_ai.storage.store import ArticleMeta, KBStore, render_catalog_line
```

and replace lines 53-55:

```python
    listing = "\n".join(render_catalog_line(a) for a in catalog)
```

`KEYS_MARKER` is no longer referenced in this module; drop it from the import.

- [ ] **Step 5: Run the storage and retrieval tests**

Run: `cd py && uv run pytest tests/test_storage.py tests/test_retrieve.py tests/test_retrieval_paths.py -v`
Expected: PASS, no test touched other than the two added

- [ ] **Step 6: Commit**

```bash
git add py/src/kb_ai/storage/store.py py/src/kb_ai/retrieval/retrieve.py py/tests/test_storage.py
git commit -m "refactor(storage): extract the shared catalog-line renderer"
```

---

## Task 2: Derive error types and shared dataclasses

Spec: A3, C3, C4, C5, B5, E2, G3. Tech design: "Errors", "Key interfaces".

**Files:**
- Modify: `py/src/kb_ai/_errors.py` (append)
- Create: `py/src/kb_ai/derive/__init__.py` (placeholder docstring only — filled in Task 7)
- Create: `py/src/kb_ai/derive/_types.py`
- Test: `py/tests/test_errors.py` (append)

**Interfaces:**
- Produces, in `kb_ai._errors`: `DeriveError` (`DERIVE_FAILED`), `NoCatalogError`
  (`NO_CATALOG`), `InvalidSlugError` (`INVALID_SLUG`), `SlugExistsError`
  (`SLUG_EXISTS`), `NestedDeriveError` (`NESTED_DERIVE`), `NoDocumentsError`
  (`NO_DOCUMENTS`), `UnknownDerivedKBError` (`UNKNOWN_DERIVED_KB`).
- Produces, in `kb_ai.derive._types`: `MODE_RECALL = "recall"`,
  `MODE_PRECISION = "precision"`, `Skipped(ref, reason)`,
  `SelectionResult(paths, batches, dropped_invented, skipped)`,
  `DocumentRef(rel_path, checksum, size_bytes)`, `DeriveReport(...)`,
  `Selector = Callable[[list[ArticleMeta], str, str], SelectionResult]`.

- [ ] **Step 1: Write the failing test**

Append to `py/tests/test_errors.py`:

```python
def test_derive_error_codes():
    from kb_ai._errors import (
        DeriveError, InvalidSlugError, KBError, NestedDeriveError, NoCatalogError,
        NoDocumentsError, SlugExistsError, UnknownDerivedKBError,
    )

    expected = {
        DeriveError: "DERIVE_FAILED",
        NoCatalogError: "NO_CATALOG",
        InvalidSlugError: "INVALID_SLUG",
        SlugExistsError: "SLUG_EXISTS",
        NestedDeriveError: "NESTED_DERIVE",
        NoDocumentsError: "NO_DOCUMENTS",
        UnknownDerivedKBError: "UNKNOWN_DERIVED_KB",
    }
    for cls, code in expected.items():
        assert cls.code == code
        assert issubclass(cls, KBError)
    for cls in expected:
        if cls is not DeriveError:
            assert issubclass(cls, DeriveError)


def test_derive_report_defaults():
    from kb_ai.derive._types import DeriveReport

    r = DeriveReport(derived_kb="/kb/derived/x", slug="x", topic="pricing")
    assert r.compiled is False
    assert r.compile is None
    assert r.selected_articles == []
    assert r.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd py && uv run pytest tests/test_errors.py -k derive -v`
Expected: FAIL with `ImportError: cannot import name 'DeriveError'`

- [ ] **Step 3: Append the error classes**

At the end of `py/src/kb_ai/_errors.py`:

```python
class DeriveError(KBError):
    """A topic-scoped derive run failed.

    Derive fails loudly where retrieval degrades: an empty selection or a
    swallowed LLM error would silently produce an empty knowledge base.
    """

    code = "DERIVE_FAILED"


class NoCatalogError(DeriveError):
    """The source knowledge base has no index/master-index.md to filter."""

    code = "NO_CATALOG"


class InvalidSlugError(DeriveError):
    """The derived-KB slug is empty or is not a single safe path segment."""

    code = "INVALID_SLUG"


class SlugExistsError(DeriveError):
    """derived/<slug>/ already exists and --force was not given."""

    code = "SLUG_EXISTS"


class NestedDeriveError(DeriveError):
    """The source knowledge base is itself a derived one; nesting stops at one level."""

    code = "NESTED_DERIVE"


class NoDocumentsError(DeriveError):
    """No selected article resolved to a readable source document."""

    code = "NO_DOCUMENTS"


class UnknownDerivedKBError(DeriveError):
    """The requested derived-KB slug does not exist.

    Never a fallback to the root KB: answering from the wrong corpus silently is
    worse than an error (spec G3).
    """

    code = "UNKNOWN_DERIVED_KB"
```

- [ ] **Step 4: Create the package and the shared types**

`py/src/kb_ai/derive/__init__.py` (placeholder for now — Task 7 replaces it):

```python
"""Derive a topic-scoped knowledge base from a compiled KaaS knowledge base.

See docs/features/derive-topic-kb-from-catalog/spec.md. The orchestrator
(derive_kb) lands in this module; the phases live in the private submodules.
"""
from __future__ import annotations
```

`py/src/kb_ai/derive/_types.py`:

```python
"""Value objects shared by the derive phases (spec A–E).

Kept out of the package __init__ so _filter, _sources, _layout and _offtopic can
import them without a cycle through the orchestrator -- the same reason
kb_ai/_types.py exists.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from kb_ai.storage.store import ArticleMeta

# Filter modes. The two passes have opposite failure costs, so they share one
# prompt template with different inclusion instructions (spec O4).
#   RECALL    -- first pass over the source catalog. A missed article loses its
#                documents permanently, so include anything that could help.
#   PRECISION -- second pass over the derived catalog. Every article here came
#                from documents already judged topical, so a permissive prompt
#                would select everything and the pass would do nothing.
MODE_RECALL = "recall"
MODE_PRECISION = "precision"


@dataclass(frozen=True)
class Skipped:
    """One thing the run could not use, and why.

    reason is drawn from a fixed vocabulary so the manifest stays
    machine-readable: no_sources_key, empty_sources, unparseable_frontmatter,
    article_unreadable, escapes_kb, document_missing, document_unreadable,
    line_over_budget.
    """

    ref: str
    reason: str


@dataclass(frozen=True)
class SelectionResult:
    """What one topic-filter pass decided. Identical shape for 1 or N batches (A7)."""

    paths: list[str]
    batches: int
    dropped_invented: int
    skipped: list[Skipped]


@dataclass(frozen=True)
class DocumentRef:
    """A source document to copy into the derived KB.

    size_bytes feeds the CLI volume gate (F5); checksum is the 16-hex-char
    SHA-256 prefix storage.store._compute_checksum produces, so it also keys the
    extract-cache entry copied alongside the document (C7, E4).
    """

    rel_path: str
    checksum: str
    size_bytes: int


@dataclass
class DeriveReport:
    """Everything one derive run decided and did. Serialised into manifest.json."""

    derived_kb: str
    slug: str
    topic: str
    selected_articles: list[str] = field(default_factory=list)
    skipped_articles: list[Skipped] = field(default_factory=list)
    skipped_documents: list[Skipped] = field(default_factory=list)
    documents: list[DocumentRef] = field(default_factory=list)
    dropped_invented_paths: int = 0
    filter_batches: int = 0
    offtopic_articles: list[str] = field(default_factory=list)
    compiled: bool = False
    compile: dict | None = None
    # Whole-run LLM spend, read from the process-wide tracker after the second
    # pass -- compile's own summary predates that pass, so it is not the total.
    cost: dict | None = None
    warnings: list[str] = field(default_factory=list)


# (catalog, topic, mode) -> SelectionResult. The model is bound by the caller, so
# tests inject a three-argument stub and no test needs a real LLM (spec I1).
Selector = Callable[[list[ArticleMeta], str, str], SelectionResult]
```

- [ ] **Step 5: Run the tests**

Run: `cd py && uv run pytest tests/test_errors.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add py/src/kb_ai/_errors.py py/src/kb_ai/derive/ py/tests/test_errors.py
git commit -m "feat(derive): add derive error codes and shared value objects"
```

---

## Task 3: Layout — slug rules, derived directory, document copy, manifest

Spec: C1–C5, C7, E1, E2, E4, G4. Tech design: "`--force` safety",
"Extract-cache reuse", "Stage 2 — one shared resolver".

**Files:**
- Create: `py/src/kb_ai/derive/_layout.py`
- Test: `py/tests/test_derive_layout.py`

**Interfaces:**
- Consumes: `kb_ai._errors` (Task 2), `kb_ai.derive._types.DocumentRef` (Task 2),
  `KBStore`, `storage.store._compute_checksum`.
- Produces:
  - `SLUG_RE: re.Pattern`
  - `normalise_slug(topic: str) -> str`
  - `validate_slug(slug: str) -> None`
  - `assert_not_nested(source_kb: Path) -> None`
  - `check_slug_available(source_kb: Path, slug: str, force: bool) -> None`
  - `create(source_kb: Path, slug: str, force: bool) -> Path`
  - `copy_documents(source_store: KBStore, derived_dir: Path, docs: list[DocumentRef]) -> int`
  - `write_manifest(derived_dir: Path, payload: dict) -> None`
  - `read_manifest(derived_dir: Path) -> dict`
  - `resolve_kb_dir(root_kb: str, slug: str | None) -> str`

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_derive_layout.py`:

```python
"""Tests for derive/_layout.py -- slug rules, directory creation, manifest I/O."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import (
    InvalidSlugError, NestedDeriveError, SlugExistsError, UnknownDerivedKBError,
)
from kb_ai.derive import _layout
from kb_ai.derive._types import DocumentRef
from kb_ai.storage.store import KBStore


@pytest.mark.parametrize("topic,expected", [
    ("pricing and fee structure", "pricing-and-fee-structure"),
    ("Pricing / Fees!", "pricing-fees"),
    ("  spaced  out  ", "spaced-out"),
    ("CJK 定价", "cjk"),
    ("a" * 60, "a" * 40),
    ("x" * 39 + "-tail", "x" * 39),  # truncation must not leave a trailing dash
])
def test_normalise_slug(topic, expected):
    assert _layout.normalise_slug(topic) == expected


@pytest.mark.parametrize("slug", ["", "-", "..", ".", "a/b", "A", "-lead", "x" * 41, "定价"])
def test_validate_slug_rejects(slug):
    with pytest.raises(InvalidSlugError):
        _layout.validate_slug(slug)


def test_validate_slug_accepts():
    _layout.validate_slug("pricing-and-fees")
    _layout.validate_slug("a")
    _layout.validate_slug("x" * 40)


def test_assert_not_nested_rejects_a_derived_kb(tmp_path: Path):
    nested = tmp_path / "derived" / "pricing"
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text("{}")
    with pytest.raises(NestedDeriveError):
        _layout.assert_not_nested(nested)


def test_assert_not_nested_allows_a_dir_named_derived_without_a_manifest(tmp_path: Path):
    plain = tmp_path / "derived" / "kb"
    plain.mkdir(parents=True)
    _layout.assert_not_nested(plain)  # no manifest -> not a derived KB


def test_create_makes_the_derived_dir(tmp_path: Path):
    out = _layout.create(tmp_path, "pricing", force=False)
    assert out == tmp_path / "derived" / "pricing"
    assert out.is_dir()


def test_create_refuses_an_existing_slug(tmp_path: Path):
    (tmp_path / "derived" / "pricing").mkdir(parents=True)
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=False)


def test_force_replaces_only_a_directory_derive_created(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    (target / "stale.txt").write_text("old")

    out = _layout.create(tmp_path, "pricing", force=True)
    assert out.is_dir()
    assert not (out / "stale.txt").exists()


def test_force_refuses_a_directory_with_no_matching_manifest(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "precious.md").write_text("not ours")
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=True)
    assert (target / "precious.md").exists()


def test_force_refuses_a_manifest_naming_another_slug(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"slug": "compliance"}))
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=True)


def test_copy_documents_copies_content_and_extract_cache(tmp_path: Path):
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    from kb_ai.storage.store import _compute_checksum
    checksum = _compute_checksum("body")
    cache_dir = src / ".extract-cache"
    cache_dir.mkdir()
    (cache_dir / f"{checksum}.json").write_text('{"summary": "cached"}')

    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)
    copied = _layout.copy_documents(store, derived, [
        DocumentRef(rel_path="raw/notes.md", checksum=checksum, size_bytes=4),
    ])

    assert copied == 1
    assert (derived / "raw" / "notes.md").read_text() == "body"
    assert (derived / ".extract-cache" / f"{checksum}.json").read_text() == '{"summary": "cached"}'


def test_copy_documents_tolerates_a_missing_cache_entry(tmp_path: Path):
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    copied = _layout.copy_documents(store, derived, [
        DocumentRef(rel_path="raw/notes.md", checksum="deadbeefdeadbeef", size_bytes=4),
    ])
    assert copied == 1
    assert not (derived / ".extract-cache").exists()


def test_manifest_round_trip(tmp_path: Path):
    _layout.write_manifest(tmp_path, {"slug": "pricing", "topic": "pricing"})
    assert _layout.read_manifest(tmp_path)["slug"] == "pricing"


def test_read_manifest_of_a_dir_without_one(tmp_path: Path):
    assert _layout.read_manifest(tmp_path) == {}


def test_resolve_kb_dir_root(tmp_path: Path):
    assert _layout.resolve_kb_dir(str(tmp_path), None) == str(tmp_path.resolve())
    assert _layout.resolve_kb_dir(str(tmp_path), "") == str(tmp_path.resolve())


def test_resolve_kb_dir_derived(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}")
    assert _layout.resolve_kb_dir(str(tmp_path), "pricing") == str(target.resolve())


def test_resolve_kb_dir_unknown_slug(tmp_path: Path):
    with pytest.raises(UnknownDerivedKBError):
        _layout.resolve_kb_dir(str(tmp_path), "nope")


def test_resolve_kb_dir_rejects_a_traversal_slug(tmp_path: Path):
    with pytest.raises(InvalidSlugError):
        _layout.resolve_kb_dir(str(tmp_path), "../..")


def test_resolve_kb_dir_rejects_a_symlinked_derived_kb(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}")
    derived_root = tmp_path / "kb" / "derived"
    derived_root.mkdir(parents=True)
    (derived_root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnknownDerivedKBError):
        _layout.resolve_kb_dir(str(tmp_path / "kb"), "escape")


def test_list_derived_reads_manifests(tmp_path: Path):
    for slug, topic in (("pricing", "pricing"), ("compliance", "compliance rules")):
        d = tmp_path / "derived" / slug
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"slug": slug, "topic": topic}))
    (tmp_path / "derived" / "junk").mkdir()  # no manifest -> not listed

    got = _layout.list_derived(str(tmp_path))
    assert [m["slug"] for m in got] == ["compliance", "pricing"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_derive_layout.py -v`
Expected: FAIL — `AttributeError: module 'kb_ai.derive._layout' has no attribute 'normalise_slug'` (or ImportError)

- [ ] **Step 3: Write `derive/_layout.py`**

```python
"""Filesystem layout of a derived knowledge base (spec C1-C7, E1-E4, G4).

Owns every path decision: what a slug may be, where derived/<slug>/ lives, how
documents and their extract-cache entries are copied in, and how the provenance
manifest is read back. resolve_kb_dir() is the one read-path resolver shared by
MCP ask and the HTTP read handlers.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from kb_ai._errors import (
    InvalidSlugError,
    NestedDeriveError,
    SlugExistsError,
    UnknownDerivedKBError,
)
from kb_ai.derive._types import DocumentRef
from kb_ai.storage.store import KBStore

# One lower-case path segment, dash-separated, at most 40 chars. Validated
# lexically BEFORE any path is built, so a hostile slug never reaches the
# filesystem -- --force is a recursive delete driven by this string (C3, C4).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

MANIFEST_NAME = "manifest.json"
DERIVED_DIRNAME = "derived"
OFFTOPIC_DIRNAME = "_offtopic"

_SLUG_MAX = 40


def normalise_slug(topic: str) -> str:
    """Derive a slug from a topic string (C2).

    Lower-cased, non-alphanumeric runs collapsed to '-', trimmed, truncated to 40
    characters, then trimmed again -- truncation can land on a dash, which
    validate_slug rejects.
    """
    flat = re.sub(r"[^a-z0-9]+", "-", topic.lower())
    return flat.strip("-")[:_SLUG_MAX].strip("-")


def validate_slug(slug: str) -> None:
    """Raise InvalidSlugError unless slug is a single safe path segment (C3)."""
    if not slug or not SLUG_RE.match(slug):
        raise InvalidSlugError(
            f"invalid slug {slug!r}: expected 1-40 chars matching {SLUG_RE.pattern}"
        )


def assert_not_nested(source_kb: Path) -> None:
    """Refuse to derive from a derived knowledge base (C5).

    A derived KB is exactly '<parent>/derived/<slug>/' holding a manifest.json.
    Requiring the manifest keeps a real KB that merely happens to sit in a
    directory called 'derived' usable.
    """
    src = Path(source_kb).expanduser().resolve()
    if src.parent.name == DERIVED_DIRNAME and (src / MANIFEST_NAME).exists():
        raise NestedDeriveError(
            f"{src} is a derived knowledge base; nesting stops at one level"
        )


def derived_dir(source_kb: Path, slug: str) -> Path:
    """Path of derived/<slug>/ under source_kb. Assumes slug is already valid."""
    return Path(source_kb).expanduser().resolve() / DERIVED_DIRNAME / slug


def check_slug_available(source_kb: Path, slug: str, force: bool) -> None:
    """Raise SlugExistsError now if create() would later refuse (C4).

    Called before the first LLM call so a name clash costs nothing.
    """
    target = derived_dir(source_kb, slug)
    if not target.exists():
        return
    if not force:
        raise SlugExistsError(
            f"{target} already exists; pass --force to replace it"
        )
    manifest = read_manifest(target)
    if manifest.get("slug") != slug:
        # --force replaces a directory derive created. Refusing anything else is
        # what stops a mistyped --kb plus --force from being a data-loss bug.
        raise SlugExistsError(
            f"{target} exists but holds no {MANIFEST_NAME} naming slug {slug!r}; "
            "refusing to replace a directory this command did not create"
        )


def create(source_kb: Path, slug: str, force: bool) -> Path:
    """Create derived/<slug>/, replacing it when force is given (C1, C4)."""
    validate_slug(slug)
    check_slug_available(source_kb, slug, force)
    target = derived_dir(source_kb, slug)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def copy_documents(source_store: KBStore, dest_dir: Path,
                   docs: list[DocumentRef]) -> int:
    """Copy each document into dest_dir keeping its source-relative name (C1).

    The matching .extract-cache/<checksum>.json entry is copied too when it
    exists (C7): the copies are byte-identical, so the content checksum the cache
    keys on matches and the derived compile skips the extract call already paid
    for. A missing entry is not an error. Copied, not symlinked, so deleting the
    source KB cannot invalidate the derived one.

    Caveat: the cache key carries no model or prompt version, so compiling a
    derived KB with a different model than the source reuses the other model's
    extractions. That is already true within one KB today.
    """
    copied = 0
    for doc in docs:
        content = source_store.read_raw(doc.rel_path)
        dest = dest_dir / doc.rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        copied += 1

        cache_src = source_store.base_dir / ".extract-cache" / f"{doc.checksum}.json"
        if cache_src.exists():
            cache_dst = dest_dir / ".extract-cache" / f"{doc.checksum}.json"
            cache_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache_src, cache_dst)
    return copied


def write_manifest(dest_dir: Path, payload: dict) -> None:
    """Write manifest.json (E1: before compiling, so a dead run still records intent)."""
    (Path(dest_dir) / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )


def read_manifest(dest_dir: Path) -> dict:
    """Read manifest.json, or {} when absent or unparseable."""
    path = Path(dest_dir) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_derived(root_kb: str) -> list[dict]:
    """Every derived KB's manifest under root_kb, sorted by slug (H2).

    A directory without a readable manifest is not a derived KB and is skipped.
    """
    root = Path(root_kb).expanduser().resolve() / DERIVED_DIRNAME
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest = read_manifest(child)
        if manifest:
            out.append(manifest)
    return out


def resolve_kb_dir(root_kb: str, slug: str | None) -> str:
    """Root KB when slug is empty, else <root>/derived/<slug> (G3, G4, H3).

    Raises InvalidSlugError on a slug failing lexical validation and
    UnknownDerivedKBError when no such derived KB exists. Never falls back to the
    root KB: answering from the wrong corpus silently is worse than an error.

    Containment is checked after resolve(), so a symlink planted under derived/
    that points outside the KB is rejected -- matching KBStore._resolve rather
    than the Go layer's lexical check, on purpose.
    """
    root = Path(root_kb).expanduser().resolve()
    if not slug:
        return str(root)
    validate_slug(slug)
    base = root / DERIVED_DIRNAME
    target = (base / slug).resolve()
    if not target.is_relative_to(base) or not (target / MANIFEST_NAME).exists():
        raise UnknownDerivedKBError(f"no derived knowledge base named {slug!r}")
    return str(target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_derive_layout.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
git add py/src/kb_ai/derive/_layout.py py/tests/test_derive_layout.py
git commit -m "feat(derive): add derived-KB layout, slug rules and manifest I/O"
```

---

## Task 4: Topic filter with two modes and prompt-budget batching

Spec: A1–A8. Tech design: "Batching", "Filter prompt and the two modes".

**Files:**
- Create: `py/src/kb_ai/derive/_filter.py`
- Test: `py/tests/test_derive_filter.py`

**Interfaces:**
- Consumes: `render_catalog_line` (Task 1), `MODE_RECALL` / `MODE_PRECISION` /
  `SelectionResult` / `Skipped` (Task 2), `DeriveError` (Task 2),
  `kb_ai.llm.completion_json`, `kb_ai.llm.MAX_PROMPT_CHARS`.
- Produces:
  - `build_prompt(topic: str, mode: str, listing: str) -> str`
  - `pack_batches(catalog: list[ArticleMeta], budget: int) -> tuple[list[list[ArticleMeta]], list[Skipped]]`
  - `select_by_topic(catalog: list[ArticleMeta], topic: str, mode: str, *, model: str) -> SelectionResult`

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_derive_filter.py`:

```python
"""Tests for derive/_filter.py -- topic selection, batching, failure modes."""
from __future__ import annotations

import pytest

from kb_ai._errors import DeriveError
from kb_ai.derive import _filter
from kb_ai.derive._types import MODE_PRECISION, MODE_RECALL
from kb_ai.storage.store import ArticleMeta


def _catalog(n: int, *, summary: str = "s") -> list[ArticleMeta]:
    return [ArticleMeta(title=f"T{i}", path=f"wiki/a{i}.md", summary=summary)
            for i in range(n)]


def test_empty_catalog_makes_no_llm_call(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("completion_json must not be called")

    monkeypatch.setattr(_filter, "completion_json", boom)
    result = _filter.select_by_topic([], "pricing", MODE_RECALL, model="m")
    assert result == _filter.SelectionResult(paths=[], batches=0, dropped_invented=0, skipped=[])


def test_returns_every_selected_path_with_no_cap(monkeypatch):
    catalog = _catalog(30)
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": [a.path for a in catalog]})
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == [a.path for a in catalog]
    assert result.batches == 1


def test_drops_invented_paths_and_counts_them(monkeypatch):
    catalog = _catalog(2)
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {
        "paths": ["wiki/a0.md", "wiki/invented.md", 42, "wiki/a1.md"],
    })
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == ["wiki/a0.md", "wiki/a1.md"]
    assert result.dropped_invented == 2


def test_dedupes_preserving_first_seen_order(monkeypatch):
    catalog = _catalog(2)
    monkeypatch.setattr(_filter, "completion_json",
                        lambda **kw: {"paths": ["wiki/a1.md", "wiki/a0.md", "wiki/a1.md"]})
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")
    assert result.paths == ["wiki/a1.md", "wiki/a0.md"]
    assert result.dropped_invented == 0


def test_keys_column_reaches_the_prompt(monkeypatch):
    catalog = [ArticleMeta(title="Limits", path="wiki/limits.md", summary="Ceilings.",
                           keys="max_zip_entries")]
    seen: list[str] = []

    def capture(**kwargs):
        seen.append(kwargs["messages"][0]["content"])
        return {"paths": []}

    monkeypatch.setattr(_filter, "completion_json", capture)
    _filter.select_by_topic(catalog, "zip limits", MODE_RECALL, model="m")
    assert "max_zip_entries" in seen[0]


def test_llm_error_raises_derive_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(_filter, "completion_json", boom)
    with pytest.raises(DeriveError, match="topic filter failed"):
        _filter.select_by_topic(_catalog(1), "pricing", MODE_RECALL, model="m")


@pytest.mark.parametrize("payload", [{"paths": "wiki/a0.md"}, {}, [], None])
def test_malformed_response_raises_derive_error(monkeypatch, payload):
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: payload)
    with pytest.raises(DeriveError):
        _filter.select_by_topic(_catalog(1), "pricing", MODE_RECALL, model="m")


def test_batches_when_the_listing_exceeds_the_budget(monkeypatch):
    # 40 articles with 3K-char summaries: ~120K chars of listing against an 80K
    # prompt budget, so the pack must split.
    catalog = _catalog(40, summary="x" * 3000)
    calls: list[str] = []

    def capture(**kwargs):
        content = kwargs["messages"][0]["content"]
        calls.append(content)
        # Select only the articles this batch actually listed.
        return {"paths": [a.path for a in catalog if f"- {a.path} " in content]}

    monkeypatch.setattr(_filter, "completion_json", capture)
    result = _filter.select_by_topic(catalog, "pricing", MODE_RECALL, model="m")

    assert result.batches > 1
    assert result.batches == len(calls)
    assert sorted(result.paths) == sorted(a.path for a in catalog)  # union, not a ranking
    from kb_ai.llm import MAX_PROMPT_CHARS
    assert all(len(c) <= MAX_PROMPT_CHARS for c in calls)


def test_single_and_multi_batch_return_the_same_shape(monkeypatch):
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {"paths": []})
    one = _filter.select_by_topic(_catalog(2), "t", MODE_RECALL, model="m")
    many = _filter.select_by_topic(_catalog(40, summary="x" * 3000), "t", MODE_RECALL, model="m")
    assert type(one) is type(many)
    assert one.batches == 1 and many.batches > 1


def test_a_line_over_a_whole_batch_is_skipped_not_fatal(monkeypatch):
    huge = ArticleMeta(title="Huge", path="wiki/huge.md", summary="x" * 200_000)
    catalog = [huge, ArticleMeta(title="Ok", path="wiki/ok.md", summary="s")]
    monkeypatch.setattr(_filter, "completion_json", lambda **kw: {"paths": ["wiki/ok.md"]})

    result = _filter.select_by_topic(catalog, "t", MODE_RECALL, model="m")
    assert result.paths == ["wiki/ok.md"]
    assert [(s.ref, s.reason) for s in result.skipped] == [("wiki/huge.md", "line_over_budget")]


def test_the_two_modes_give_different_inclusion_instructions():
    recall = _filter.build_prompt("pricing", MODE_RECALL, "- wiki/a.md — A: s")
    precision = _filter.build_prompt("pricing", MODE_PRECISION, "- wiki/a.md — A: s")
    assert recall != precision
    assert "peripherally" in recall
    assert "substantially" in precision
    assert "pricing" in recall and "pricing" in precision


def test_unknown_mode_is_a_programmer_error():
    with pytest.raises(ValueError):
        _filter.build_prompt("t", "sideways", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_derive_filter.py -v`
Expected: FAIL with `ImportError`/`AttributeError` on `_filter.select_by_topic`

- [ ] **Step 3: Write `derive/_filter.py`**

```python
"""LLM topic filter over a catalog listing (spec A1-A8).

Two passes use this module with opposite inclusion instructions (spec O4):
RECALL over the source catalog, where a miss loses documents permanently, and
PRECISION over the derived catalog, where every article already came from
topical documents so a permissive prompt would select everything.

There is no top-K cap, which is what makes batching cheap: the batches only need
unioning, never a global ranking.
"""
from __future__ import annotations

from kb_ai._errors import DeriveError
from kb_ai.derive._types import (
    MODE_PRECISION,
    MODE_RECALL,
    SelectionResult,
    Skipped,
)
from kb_ai.llm import MAX_PROMPT_CHARS, completion_json
from kb_ai.storage.store import ArticleMeta, render_catalog_line

# Headroom over the measured skeleton, mirroring core/merge.py's _SAFETY_MARGIN
# habit: the skeleton is measured, not guessed, and this absorbs the difference
# between characters and whatever the gateway counts.
_SAFETY_MARGIN = 2_000

_INSTRUCTION = {
    MODE_RECALL: (
        "Include an article if it could contribute to understanding the topic, "
        "even peripherally. Missing a relevant article permanently loses the "
        "documents behind it, so prefer including a borderline article."
    ),
    MODE_PRECISION: (
        "Include an article only if it is substantially about the topic. A "
        "peripheral mention does not qualify. Every article listed here was "
        "already judged related to the topic once, so judging by that standard "
        "again would select everything and decide nothing."
    ),
}


def build_prompt(topic: str, mode: str, listing: str) -> str:
    """Render the filter prompt. listing="" gives the skeleton, for budgeting."""
    try:
        instruction = _INSTRUCTION[mode]
    except KeyError:
        raise ValueError(f"unknown filter mode: {mode!r}") from None
    return (
        "You are selecting which knowledge-base articles belong to a topic. "
        "Below is the article catalog (path — title: summary). An article that "
        "documents a table of settings, fields or endpoints also lists their "
        "names after `| keys:`, so a topic naming one specific named value "
        "belongs to the article whose keys contain it.\n\n"
        f"{listing}\n\n"
        f"Topic: {topic}\n\n"
        f"{instruction}\n\n"
        "Return JSON {\"paths\": [...]} listing every matching article path, "
        "verbatim from the catalog. There is no limit on how many you may "
        "return. Return an empty list if none match."
    )


def pack_batches(catalog: list[ArticleMeta],
                 budget: int) -> tuple[list[list[ArticleMeta]], list[Skipped]]:
    """Greedily pack catalog entries into batches whose listing fits budget (A6).

    A single line longer than a whole batch is dropped as line_over_budget rather
    than making the run unschedulable (A8).
    """
    batches: list[list[ArticleMeta]] = []
    skipped: list[Skipped] = []
    current: list[ArticleMeta] = []
    size = 0

    for article in catalog:
        cost = len(render_catalog_line(article)) + 1  # + the joining newline
        if cost > budget:
            skipped.append(Skipped(ref=article.path, reason="line_over_budget"))
            continue
        if current and size + cost > budget:
            batches.append(current)
            current, size = [], 0
        current.append(article)
        size += cost

    if current:
        batches.append(current)
    return batches, skipped


def select_by_topic(catalog: list[ArticleMeta], topic: str, mode: str,
                    *, model: str) -> SelectionResult:
    """Every catalog path the model judged part of the topic (A1-A8).

    Uncapped, filtered to catalog membership, de-duplicated preserving first-seen
    order. An empty catalog returns early without an LLM call (A2). Any LLM or
    response-shape failure raises DeriveError (A3): unlike retrieval, this cannot
    degrade to [] -- an empty selection would silently build an empty KB.
    """
    if not catalog:
        return SelectionResult(paths=[], batches=0, dropped_invented=0, skipped=[])

    valid = {a.path for a in catalog}
    budget = MAX_PROMPT_CHARS - len(build_prompt(topic, mode, "")) - _SAFETY_MARGIN
    batches, skipped = pack_batches(catalog, budget)

    paths: list[str] = []
    seen: set[str] = set()
    dropped = 0

    for batch in batches:
        listing = "\n".join(render_catalog_line(a) for a in batch)
        prompt = build_prompt(topic, mode, listing)
        try:
            result = completion_json(model=model,
                                     messages=[{"role": "user", "content": prompt}])
        except Exception as e:  # noqa: BLE001 -- re-raised as a typed domain error
            raise DeriveError(f"topic filter failed: {e}") from e

        raw = result.get("paths") if isinstance(result, dict) else None
        if not isinstance(raw, list):
            raise DeriveError(
                "topic filter returned no paths list; refusing to treat that as "
                "'nothing matches'"
            )
        for p in raw:
            if not isinstance(p, str) or p not in valid:
                dropped += 1
                continue
            if p in seen:
                continue
            seen.add(p)
            paths.append(p)

    return SelectionResult(paths=paths, batches=len(batches),
                           dropped_invented=dropped, skipped=skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_derive_filter.py -v`
Expected: PASS (15 tests, counting parametrised cases)

- [ ] **Step 5: Commit**

```bash
git add py/src/kb_ai/derive/_filter.py py/tests/test_derive_filter.py
git commit -m "feat(derive): add the topic filter with prompt-budget batching"
```

---

## Task 5: Resolve selected articles to source documents

Spec: B1–B5. Tech design: "Reason vocabulary".

**Files:**
- Create: `py/src/kb_ai/derive/_sources.py`
- Test: `py/tests/test_derive_sources.py`

**Interfaces:**
- Consumes: `DocumentRef` / `Skipped` (Task 2), `KBStore`,
  `storage.store._compute_checksum`.
- Produces:
  - `parse_sources(store: KBStore, article_path: str) -> tuple[list[str] | None, str]`
  - `resolve_documents(store: KBStore, article_paths: list[str]) -> tuple[list[DocumentRef], list[Skipped], list[Skipped]]`
    returning `(documents, skipped_articles, skipped_documents)`.

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_derive_sources.py`:

```python
"""Tests for derive/_sources.py -- sources: parsing and document resolution."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import _sources
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(tmp_path: Path) -> KBStore:
    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    return KBStore(str(tmp_path), read_only=True)


def _article(tmp_path: Path, name: str, frontmatter: str) -> str:
    path = f"wiki/{name}"
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(f"---\n{frontmatter}\n---\n\n# Body\n")
    return path


def _raw(tmp_path: Path, name: str, content: str) -> None:
    p = tmp_path / "raw" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_resolves_and_dedupes_across_articles(tmp_path: Path):
    _raw(tmp_path, "a.md", "alpha")
    _raw(tmp_path, "b.md", "beta")
    p1 = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md\n  - raw/b.md')
    p2 = _article(tmp_path, "two.md", 'title: Two\nsources:\n  - raw/b.md')

    docs, skipped_articles, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p1, p2])

    assert [d.rel_path for d in docs] == ["raw/a.md", "raw/b.md"]  # sorted, deduped
    assert skipped_articles == [] and skipped_docs == []
    assert docs[0].checksum == _compute_checksum("alpha")
    assert docs[0].size_bytes == len("alpha".encode())


def test_comma_joined_entry_yields_every_document(tmp_path: Path):
    # A batch merge writes several rels into one sources entry:
    # commands/compile.py passes ", ".join(merge_rels) as source_path.
    _raw(tmp_path, "a.md", "alpha")
    _raw(tmp_path, "b.md", "beta")
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md, raw/b.md')

    docs, _, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/a.md", "raw/b.md"]


def test_scalar_sources_value_is_accepted(tmp_path: Path):
    _raw(tmp_path, "a.md", "alpha")
    p = _article(tmp_path, "one.md", 'title: One\nsources: raw/a.md')
    docs, _, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/a.md"]


def test_no_sources_key(tmp_path: Path):
    p = _article(tmp_path, "one.md", "title: One")
    docs, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert [(s.ref, s.reason) for s in skipped_articles] == [(p, "no_sources_key")]


def test_empty_sources_list(tmp_path: Path):
    p = _article(tmp_path, "one.md", "title: One\nsources: []")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "empty_sources"


def test_unparseable_frontmatter(tmp_path: Path):
    p = "wiki/bad.md"
    (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / p).write_text("no frontmatter here\n")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "unparseable_frontmatter"


def test_invalid_yaml_frontmatter(tmp_path: Path):
    p = _article(tmp_path, "bad.md", "title: [unclosed")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "unparseable_frontmatter"


def test_article_unreadable(tmp_path: Path):
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), ["wiki/ghost.md"])
    assert skipped_articles[0].reason == "article_unreadable"


def test_escaping_source_entry_is_recorded_not_fatal(tmp_path: Path):
    outside = tmp_path.parent / "secret.md"
    outside.write_text("secret")
    _raw(tmp_path, "ok.md", "fine")
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - ../secret.md\n  - raw/ok.md')

    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/ok.md"]
    assert [(s.ref, s.reason) for s in skipped_docs] == [("../secret.md", "escapes_kb")]


def test_absolute_source_entry_is_rejected(tmp_path: Path):
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - /etc/passwd')
    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert skipped_docs[0].reason == "escapes_kb"


def test_missing_document_is_recorded_not_fatal(tmp_path: Path):
    _raw(tmp_path, "ok.md", "fine")
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - raw/gone.md\n  - raw/ok.md')
    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/ok.md"]
    assert [(s.ref, s.reason) for s in skipped_docs] == [("raw/gone.md", "document_missing")]


def test_unreadable_document_is_recorded(tmp_path: Path, monkeypatch):
    _raw(tmp_path, "a.md", "alpha")
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md')
    store = _kb(tmp_path)

    def boom(rel_path: str) -> str:
        raise OSError("EIO")

    monkeypatch.setattr(store, "read_raw", boom)
    docs, _, skipped_docs = _sources.resolve_documents(store, [p])
    assert docs == []
    assert skipped_docs[0].reason == "document_unreadable"


def test_a_document_skipped_once_is_not_reported_twice(tmp_path: Path):
    p1 = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/gone.md')
    p2 = _article(tmp_path, "two.md", 'title: Two\nsources:\n  - raw/gone.md')
    _, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p1, p2])
    assert len(skipped_docs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_derive_sources.py -v`
Expected: FAIL with `AttributeError: module 'kb_ai.derive._sources' has no attribute 'resolve_documents'`

- [ ] **Step 3: Write `derive/_sources.py`**

```python
"""Follow selected articles' sources: frontmatter to source documents (B1-B5).

sources: is written by the compile pipeline (core/merge.py) from LLM output, so
every value here is attacker-influenced: reads go through KBStore.read_raw ->
_resolve, which resolves symlinks and rejects escapes. A rejected or missing
entry is recorded and the run continues -- one bad path must not discard the
documents that did resolve.
"""
from __future__ import annotations

import yaml

from kb_ai.derive._types import DocumentRef, Skipped
from kb_ai.storage.store import KBStore, _compute_checksum


def parse_sources(store: KBStore, article_path: str) -> tuple[list[str] | None, str]:
    """Read an article's sources: entries.

    Returns (entries, "") on success, or (None, reason) with reason one of
    article_unreadable, unparseable_frontmatter, no_sources_key, empty_sources.
    """
    try:
        content = store.read_article(article_path)
    except (OSError, ValueError):
        return None, "article_unreadable"

    if not content.startswith("---"):
        return None, "unparseable_frontmatter"
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, "unparseable_frontmatter"
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, "unparseable_frontmatter"
    if not isinstance(fm, dict):
        return None, "unparseable_frontmatter"
    if "sources" not in fm:
        return None, "no_sources_key"

    raw = fm["sources"]
    if isinstance(raw, str):
        entries = [raw]
    elif isinstance(raw, list):
        entries = [e for e in raw if isinstance(e, str)]
    else:
        return None, "unparseable_frontmatter"

    # A batch merge records several documents in ONE entry: commands/compile.py
    # passes ", ".join(merge_rels) as source_path and core.merge appends it as a
    # single "  - raw/a.md, raw/b.md" line. Treating that as one path would lose
    # every document behind a batch-merged article.
    out: list[str] = []
    for entry in entries:
        out.extend(piece.strip() for piece in entry.split(",") if piece.strip())
    if not out:
        return None, "empty_sources"
    return out, ""


def resolve_documents(
    store: KBStore, article_paths: list[str],
) -> tuple[list[DocumentRef], list[Skipped], list[Skipped]]:
    """De-duplicated union of the documents behind article_paths (B1-B4).

    Returns (documents, skipped_articles, skipped_documents). Documents come back
    in stable sorted order by rel_path; each is reported at most once even when
    several articles name it. Content is read to compute the checksum and size
    and then dropped -- the copy step re-reads it, which keeps peak memory off
    the size of the whole selection.
    """
    skipped_articles: list[Skipped] = []
    skipped_documents: list[Skipped] = []
    found: dict[str, DocumentRef] = {}
    seen_bad: set[str] = set()

    for article_path in article_paths:
        entries, reason = parse_sources(store, article_path)
        if entries is None:
            skipped_articles.append(Skipped(ref=article_path, reason=reason))
            continue
        for rel in entries:
            if rel in found or rel in seen_bad:
                continue
            try:
                content = store.read_raw(rel)
            except ValueError:
                # _resolve rejected it: absolute path, "../" climb, or a symlink
                # leading out of the KB.
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="escapes_kb"))
                continue
            except FileNotFoundError:
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="document_missing"))
                continue
            except OSError:
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="document_unreadable"))
                continue
            found[rel] = DocumentRef(
                rel_path=rel,
                checksum=_compute_checksum(content),
                size_bytes=len(content.encode()),
            )

    documents = [found[k] for k in sorted(found)]
    return documents, skipped_articles, skipped_documents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_derive_sources.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add py/src/kb_ai/derive/_sources.py py/tests/test_derive_sources.py
git commit -m "feat(derive): resolve selected articles to their source documents"
```

---

## Task 6: Second pass — move off-topic articles aside and reindex

Spec: D2–D7. Tech design: "Filter prompt and the two modes".

**Files:**
- Create: `py/src/kb_ai/derive/_offtopic.py`
- Test: `py/tests/test_derive_offtopic.py`

**Interfaces:**
- Consumes: `MODE_PRECISION` / `Selector` / `SelectionResult` (Task 2),
  `OFFTOPIC_DIRNAME` (Task 3), `KBStore`, `update_markdown_index`.
- Produces: `prune(derived_dir: Path, topic: str, select: Selector) -> tuple[list[str], list[str]]`
  returning `(moved_article_paths, warnings)`.

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_derive_offtopic.py`:

```python
"""Tests for derive/_offtopic.py -- the second (PRECISION) filter pass."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import _offtopic
from kb_ai.derive._types import MODE_PRECISION, SelectionResult


def _derived(tmp_path: Path, articles: dict[str, str]) -> Path:
    """Build a compiled-looking derived KB: wiki/*.md plus a master index."""
    (tmp_path / "index").mkdir(parents=True, exist_ok=True)
    lines = ["# Knowledge Base Index", ""]
    for rel, title in articles.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ntitle: {title}\ntags: [t]\n---\n\n# {title}\n\nProse.\n")
        lines.append(f"- [{title}]({rel}) — Prose.")
    (tmp_path / "index" / "master-index.md").write_text("\n".join(lines) + "\n")
    return tmp_path


def _selector(keep: list[str]):
    calls: list[str] = []

    def select(catalog, topic, mode):
        calls.append(mode)
        return SelectionResult(paths=list(keep), batches=1, dropped_invented=0, skipped=[])

    return select, calls


def test_moves_unselected_articles_preserving_their_path(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/concepts/a.md": "A", "wiki/projects/b.md": "B"})
    select, calls = _selector(["wiki/concepts/a.md"])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == ["wiki/projects/b.md"]
    assert warnings == []
    assert calls == [MODE_PRECISION]
    assert (d / "_offtopic" / "projects" / "b.md").exists()
    assert not (d / "wiki" / "projects" / "b.md").exists()
    assert (d / "wiki" / "concepts" / "a.md").exists()


def test_moved_article_leaves_the_derived_catalog(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector(["wiki/a.md"])

    _offtopic.prune(d, "pricing", select)

    catalog = (d / "index" / "master-index.md").read_text()
    assert "wiki/a.md" in catalog
    assert "wiki/b.md" not in catalog


def test_no_offtopic_dir_when_everything_is_selected(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector(["wiki/a.md", "wiki/b.md"])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == [] and warnings == []
    assert not (d / "_offtopic").exists()


def test_selecting_nothing_leaves_everything_in_place_and_warns(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector([])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == []
    assert warnings == ["second_pass_selected_nothing"]
    assert (d / "wiki" / "a.md").exists() and (d / "wiki" / "b.md").exists()
    assert not (d / "_offtopic").exists()


def test_empty_derived_catalog_warns_without_calling_the_selector(tmp_path: Path):
    (tmp_path / "index").mkdir(parents=True)
    called: list[str] = []

    def select(catalog, topic, mode):
        called.append(mode)
        raise AssertionError("selector must not be called on an empty catalog")

    moved, warnings = _offtopic.prune(tmp_path, "pricing", select)
    assert moved == []
    assert warnings == ["second_pass_empty_catalog"]
    assert called == []


def test_documents_behind_moved_articles_stay_in_raw(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "raw" / "src.md").write_text("body")
    select, _ = _selector(["wiki/a.md"])

    _offtopic.prune(d, "pricing", select)

    assert (d / "raw" / "src.md").read_text() == "body"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_derive_offtopic.py -v`
Expected: FAIL with `AttributeError: module 'kb_ai.derive._offtopic' has no attribute 'prune'`

- [ ] **Step 3: Write `derive/_offtopic.py`**

```python
"""Second filter pass over the freshly compiled derived catalog (spec D2-D7).

A selected document can be broader than the topic, so its compiled articles can
be off-topic even though the document was on-topic. This pass re-filters the
derived catalog in PRECISION mode and moves what it does not select into
_offtopic/, outside wiki/ -- which is what takes it out of indexing and
retrieval, by the same mechanism that makes a nested derived KB invisible to its
parent.

Moved, never deleted (D2). The documents behind moved articles stay in the
derived raw/ (D7): they are what the articles were compiled from, and removing
them would make the derived KB's own re-compile lossy.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from kb_ai.derive._layout import OFFTOPIC_DIRNAME
from kb_ai.derive._types import MODE_PRECISION, Selector
from kb_ai.storage.index import update_markdown_index
from kb_ai.storage.store import KBStore

_WIKI_PREFIX = "wiki/"


def prune(derived_dir: Path, topic: str,
          select: Selector) -> tuple[list[str], list[str]]:
    """Move off-topic articles to _offtopic/ and reindex. Returns (moved, warnings).

    Two backstops keep a mis-tuned PRECISION prompt from emptying the wiki:
    an empty catalog and an empty selection both leave every article in place and
    return a warning instead (D6).
    """
    derived_dir = Path(derived_dir)
    store = KBStore(str(derived_dir))
    catalog = store.existing_articles()
    if not catalog:
        return [], ["second_pass_empty_catalog"]

    result = select(catalog, topic, MODE_PRECISION)
    keep = set(result.paths)
    if not keep:
        # An empty derived wiki is worse than an unfiltered one.
        return [], ["second_pass_selected_nothing"]

    moved: list[str] = []
    for article in catalog:
        if article.path in keep:
            continue
        # Catalog paths are written by update_markdown_index as base-relative
        # wiki/... paths; anything else is not ours to move.
        if not article.path.startswith(_WIKI_PREFIX):
            continue
        src = derived_dir / article.path
        if not src.is_file():
            continue
        dest = derived_dir / OFFTOPIC_DIRNAME / article.path[len(_WIKI_PREFIX):]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(article.path)

    if moved:
        update_markdown_index(store)
    return moved, []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_derive_offtopic.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add py/src/kb_ai/derive/_offtopic.py py/tests/test_derive_offtopic.py
git commit -m "feat(derive): move off-topic articles aside after the derived compile"
```

---

## Task 7: The `derive_kb` orchestrator

Spec: A–E end to end, I2. Tech design: "Key interfaces".

**Files:**
- Modify: `py/src/kb_ai/derive/__init__.py` (replace the Task 2 placeholder)
- Test: `py/tests/test_derive_kb.py`

**Interfaces:**
- Consumes: everything from Tasks 2–6.
- Produces:
  - `derive_kb(source_kb, topic, *, slug=None, force=False, model, select=None, compile_fn=None, approve=None) -> DeriveReport`
  - Re-exports for callers: `DeriveReport`, `DocumentRef`, `Skipped`,
    `SelectionResult`, `MODE_RECALL`, `MODE_PRECISION`, `resolve_kb_dir`,
    `list_derived`, `normalise_slug`, `select_by_topic`, `MANIFEST_SCHEMA_VERSION`.

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_derive_kb.py`:

```python
"""End-to-end tests for derive.derive_kb with a stub filter and stub compile (I2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import (
    NestedDeriveError, NoCatalogError, NoDocumentsError, SlugExistsError,
)
from kb_ai.derive import derive_kb
from kb_ai.derive._types import MODE_PRECISION, MODE_RECALL, SelectionResult


def _fixture_kb(tmp_path: Path) -> Path:
    """A compiled-looking source KB: two articles with sources:, one without."""
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "wiki").mkdir(parents=True)
    (kb / "index").mkdir(parents=True)

    (kb / "raw" / "pricing-notes.md").write_text("Fee schedule and tiers.")
    (kb / "raw" / "infra-notes.md").write_text("Cluster topology.")

    (kb / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\nsources:\n  - raw/pricing-notes.md\n---\n\n# Pricing\n")
    (kb / "wiki" / "fees.md").write_text(
        "---\ntitle: Fees\nsources:\n  - raw/pricing-notes.md\n---\n\n# Fees\n")
    (kb / "wiki" / "orphan.md").write_text(
        "---\ntitle: Orphan\n---\n\n# Orphan\n")
    (kb / "wiki" / "infra.md").write_text(
        "---\ntitle: Infra\nsources:\n  - raw/infra-notes.md\n---\n\n# Infra\n")

    (kb / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Fees](wiki/fees.md) — What we charge.\n"
        "- [Infra](wiki/infra.md) — Cluster topology.\n"
        "- [Orphan](wiki/orphan.md) — No sources.\n"
        "- [Pricing](wiki/pricing.md) — Fee schedule.\n"
    )
    return kb


def _select(first: list[str], second: list[str] | None = None):
    """Stub selector: RECALL returns `first`, PRECISION returns `second`."""
    seen: list[str] = []

    def select(catalog, topic, mode):
        seen.append(mode)
        wanted = first if mode == MODE_RECALL else (second if second is not None else [])
        present = {a.path for a in catalog}
        return SelectionResult(paths=[p for p in wanted if p in present],
                               batches=1, dropped_invented=1, skipped=[])

    return select, seen


def _fake_compile(derived_dir: str, **kwargs) -> dict:
    """Stand in for compile_kb: write one article and a catalog naming it."""
    base = Path(derived_dir)
    (base / "wiki").mkdir(parents=True, exist_ok=True)
    (base / "index").mkdir(parents=True, exist_ok=True)
    (base / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\ntags: [fees]\n---\n\n# Pricing\n\nProse.\n")
    (base / "wiki" / "stray.md").write_text(
        "---\ntitle: Stray\ntags: [misc]\n---\n\n# Stray\n\nProse.\n")
    (base / "index" / "master-index.md").write_text(
        "# Knowledge Base Index\n\n"
        "- [Pricing](wiki/pricing.md) — Fees.\n"
        "- [Stray](wiki/stray.md) — Unrelated.\n"
    )
    return {"compiled": 2, "errors": [], "cost": {"total_cost_usd": 1.25}}


def test_happy_path_layout_and_report(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md", "wiki/fees.md", "wiki/orphan.md"],
                            ["wiki/pricing.md"])

    report = derive_kb(str(kb), "pricing and fees", model="m",
                       select=select, compile_fn=_fake_compile)

    derived = kb / "derived" / "pricing-and-fees"
    assert report.derived_kb == str(derived)
    assert report.slug == "pricing-and-fees"
    assert modes == [MODE_RECALL, MODE_PRECISION]

    # Only the document behind the selected articles was copied.
    assert (derived / "raw" / "pricing-notes.md").read_text() == "Fee schedule and tiers."
    assert not (derived / "raw" / "infra-notes.md").exists()

    assert report.selected_articles == ["wiki/pricing.md", "wiki/fees.md", "wiki/orphan.md"]
    assert [(s.ref, s.reason) for s in report.skipped_articles] == [
        ("wiki/orphan.md", "no_sources_key")]
    assert [d.rel_path for d in report.documents] == ["raw/pricing-notes.md"]
    assert report.dropped_invented_paths == 1
    assert report.filter_batches == 1
    assert report.compiled is True
    assert report.compile == {"compiled": 2, "errors": [], "cost": {"total_cost_usd": 1.25}}
    assert report.offtopic_articles == ["wiki/stray.md"]
    assert (derived / "_offtopic" / "stray.md").exists()


def test_manifest_contents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md", "wiki/orphan.md"], ["wiki/pricing.md"])

    derive_kb(str(kb), "pricing", model="gpt-test", slug="p",
              select=select, compile_fn=_fake_compile)

    manifest = json.loads((kb / "derived" / "p" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["source_kb"] == str(kb.resolve())
    assert manifest["topic"] == "pricing"
    assert manifest["slug"] == "p"
    assert manifest["filter_model"] == "gpt-test"
    assert manifest["created_at"]
    assert manifest["selected_articles"] == [
        {"path": "wiki/pricing.md", "title": "Pricing", "sources": ["raw/pricing-notes.md"]},
        {"path": "wiki/orphan.md", "title": "Orphan", "sources": []},
    ]
    assert manifest["skipped_articles"] == [
        {"path": "wiki/orphan.md", "reason": "no_sources_key"}]
    assert len(manifest["documents"]) == 1
    assert set(manifest["documents"][0]) == {"rel_path", "checksum", "size_bytes"}
    assert manifest["documents"][0]["checksum"] and len(manifest["documents"][0]["checksum"]) == 16
    assert manifest["dropped_invented_paths"] == 1
    assert manifest["offtopic_articles"] == ["wiki/stray.md"]
    assert manifest["compile"]["compiled"] == 2
    assert "cost" in manifest


def test_manifest_is_written_before_compiling(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    seen: dict = {}

    def dying_compile(derived_dir: str, **kwargs):
        seen["manifest"] = json.loads(
            (Path(derived_dir) / "manifest.json").read_text())
        raise RuntimeError("compile died")

    with pytest.raises(RuntimeError, match="compile died"):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=dying_compile)

    assert seen["manifest"]["slug"] == "pricing"
    assert seen["manifest"]["documents"]


def test_declining_the_gate_leaves_raw_and_manifest_uncompiled(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, modes = _select(["wiki/pricing.md"], ["wiki/pricing.md"])

    def compile_fn(*a, **kw):
        raise AssertionError("compile must not run when the gate declines")

    report = derive_kb(str(kb), "pricing", model="m", select=select,
                       compile_fn=compile_fn, approve=lambda r: False)

    derived = kb / "derived" / "pricing"
    assert report.compiled is False
    assert report.compile is None
    assert (derived / "raw" / "pricing-notes.md").exists()
    assert (derived / "manifest.json").exists()
    assert modes == [MODE_RECALL]  # the second pass never ran


def test_the_gate_sees_the_resolved_documents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    seen: dict = {}

    def approve(report):
        seen["docs"] = [(d.rel_path, d.size_bytes) for d in report.documents]
        return True

    derive_kb(str(kb), "pricing", model="m", select=select,
              compile_fn=_fake_compile, approve=approve)

    assert seen["docs"] == [("raw/pricing-notes.md", len("Fee schedule and tiers.".encode()))]


def test_no_catalog(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(NoCatalogError):
        derive_kb(str(bare), "pricing", model="m",
                  select=lambda *a: SelectionResult([], 0, 0, []),
                  compile_fn=_fake_compile)


def test_no_documents_creates_no_derived_dir(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/orphan.md"])
    with pytest.raises(NoDocumentsError):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)
    assert not (kb / "derived").exists()


def test_slug_exists_is_raised_before_any_llm_call(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    (kb / "derived" / "pricing").mkdir(parents=True)

    def select(*args):
        raise AssertionError("the filter must not run when the slug is taken")

    with pytest.raises(SlugExistsError):
        derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)


def test_force_replaces_a_previous_run(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)
    stale = kb / "derived" / "pricing" / "stale.txt"
    stale.write_text("old")

    derive_kb(str(kb), "pricing", model="m", force=True,
              select=select, compile_fn=_fake_compile)
    assert not stale.exists()


def test_nested_derive_is_refused(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)

    with pytest.raises(NestedDeriveError):
        derive_kb(str(kb / "derived" / "pricing"), "fees", model="m",
                  select=select, compile_fn=_fake_compile)


def test_extract_cache_entries_travel_with_their_documents(tmp_path: Path):
    kb = _fixture_kb(tmp_path)
    from kb_ai.storage.store import _compute_checksum
    checksum = _compute_checksum("Fee schedule and tiers.")
    (kb / ".extract-cache").mkdir()
    (kb / ".extract-cache" / f"{checksum}.json").write_text('{"summary": "cached"}')

    select, _ = _select(["wiki/pricing.md"], ["wiki/pricing.md"])
    derive_kb(str(kb), "pricing", model="m", select=select, compile_fn=_fake_compile)

    copied = kb / "derived" / "pricing" / ".extract-cache" / f"{checksum}.json"
    assert copied.read_text() == '{"summary": "cached"}'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_derive_kb.py -v`
Expected: FAIL with `ImportError: cannot import name 'derive_kb' from 'kb_ai.derive'`

- [ ] **Step 3: Replace `derive/__init__.py`**

```python
"""Derive a topic-scoped knowledge base from a compiled KaaS knowledge base.

Orchestration only -- every phase lives in a private submodule:

    catalog  -> _filter.select_by_topic   (RECALL)
    articles -> _sources.resolve_documents
    disk     -> _layout.create / copy_documents / write_manifest
    compile  -> commands.compile.compile_kb  (UNCHANGED)
    catalog' -> _offtopic.prune            (PRECISION)

select, compile_fn and approve are injected and default late (None), so every
test drives this function with stubs and no test needs a real LLM (spec I1).
approve is how the CLI's volume gate (F5) reaches into the middle of the run
without this module knowing about TTYs or --yes.

See docs/features/derive-topic-kb-from-catalog/spec.md.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from kb_ai._errors import (  # noqa: F401 -- re-exported for callers
    DeriveError,
    InvalidSlugError,
    NestedDeriveError,
    NoCatalogError,
    NoDocumentsError,
    SlugExistsError,
    UnknownDerivedKBError,
)
from kb_ai.derive._filter import select_by_topic
from kb_ai.derive._layout import (  # noqa: F401 -- re-exported for callers
    check_slug_available,
    copy_documents,
    create,
    list_derived,
    normalise_slug,
    read_manifest,
    resolve_kb_dir,
    validate_slug,
    write_manifest,
)
from kb_ai.derive._offtopic import prune
from kb_ai.derive._sources import resolve_documents
from kb_ai.derive._types import (  # noqa: F401 -- re-exported for callers
    MODE_PRECISION,
    MODE_RECALL,
    DeriveReport,
    DocumentRef,
    SelectionResult,
    Selector,
    Skipped,
)
from kb_ai.llm import tracker
from kb_ai.storage.store import KBStore

# Bumped when the manifest's shape changes incompatibly, so a future re-derive
# feature can refuse a manifest it does not understand.
MANIFEST_SCHEMA_VERSION = 1


def _manifest_payload(report: DeriveReport, *, source_kb: Path, model: str,
                      created_at: str, sources_by_article: dict[str, list[str]],
                      titles_by_path: dict[str, str]) -> dict:
    """Serialise a report into the manifest shape (spec E2, E3)."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_kb": str(source_kb),
        "topic": report.topic,
        "slug": report.slug,
        "created_at": created_at,
        "filter_model": model,
        "selected_articles": [
            {"path": p, "title": titles_by_path.get(p, ""),
             "sources": sources_by_article.get(p, [])}
            for p in report.selected_articles
        ],
        "skipped_articles": [{"path": s.ref, "reason": s.reason}
                             for s in report.skipped_articles],
        "skipped_documents": [{"ref": s.ref, "reason": s.reason}
                              for s in report.skipped_documents],
        "documents": [{"rel_path": d.rel_path, "checksum": d.checksum,
                       "size_bytes": d.size_bytes} for d in report.documents],
        "dropped_invented_paths": report.dropped_invented_paths,
        "filter_batches": report.filter_batches,
        "offtopic_articles": report.offtopic_articles,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
    }


def derive_kb(
    source_kb: str,
    topic: str,
    *,
    slug: str | None = None,
    force: bool = False,
    model: str,
    select: Selector | None = None,
    compile_fn: Callable[..., dict] | None = None,
    approve: Callable[[DeriveReport], bool] | None = None,
) -> DeriveReport:
    """Build <source_kb>/derived/<slug>/ from the articles matching topic.

    Order matters and is not the same as the tech design's diagram: the slug is
    validated and checked for availability BEFORE the first LLM call, so a name
    clash costs nothing, while the derived directory is created only after at
    least one document resolves (B5).

    Raises DeriveError or a subclass on every failure named in the spec.
    """
    if not topic.strip():
        raise DeriveError("topic must not be empty")

    source = Path(source_kb).expanduser().resolve()
    from kb_ai.derive._layout import assert_not_nested
    assert_not_nested(source)

    slug = slug or normalise_slug(topic)
    validate_slug(slug)
    check_slug_available(source, slug, force)

    if select is None:
        def select(catalog, topic_, mode):  # noqa: F811 -- late default
            return select_by_topic(catalog, topic_, mode, model=model)
    if compile_fn is None:
        from kb_ai.commands.compile import compile_kb as compile_fn  # noqa: F811

    source_store = KBStore(str(source), read_only=True)
    catalog = source_store.existing_articles()
    if not catalog:
        raise NoCatalogError(
            f"{source} has no index/master-index.md; derive needs a compiled "
            "knowledge base"
        )
    titles_by_path = {a.path: a.title for a in catalog}

    selection = select(catalog, topic, MODE_RECALL)
    documents, skipped_articles, skipped_documents = resolve_documents(
        source_store, selection.paths)
    skipped_articles = list(selection.skipped) + skipped_articles

    if not documents:
        raise NoDocumentsError(
            f"none of the {len(selection.paths)} matching articles resolved to a "
            "readable source document; nothing to derive"
        )

    derived_dir = create(source, slug, force)
    copy_documents(source_store, derived_dir, documents)

    report = DeriveReport(
        derived_kb=str(derived_dir),
        slug=slug,
        topic=topic,
        selected_articles=list(selection.paths),
        skipped_articles=skipped_articles,
        skipped_documents=skipped_documents,
        documents=documents,
        dropped_invented_paths=selection.dropped_invented,
        filter_batches=selection.batches,
    )

    # sources: per selected article, for the manifest's provenance record.
    from kb_ai.derive._sources import parse_sources
    sources_by_article = {}
    for path in selection.paths:
        entries, _reason = parse_sources(source_store, path)
        sources_by_article[path] = entries or []

    created_at = datetime.now().isoformat(timespec="seconds")

    def flush() -> None:
        write_manifest(derived_dir, _manifest_payload(
            report, source_kb=source, model=model, created_at=created_at,
            sources_by_article=sources_by_article, titles_by_path=titles_by_path))

    flush()  # E1: written before compiling, so a run that dies still records intent

    if approve is not None and not approve(report):
        return report

    report.compile = compile_fn(str(derived_dir), extract_model=model,
                                compile_model=model, write_model=model)
    report.compiled = True

    moved, warnings = prune(derived_dir, topic, select)
    report.offtopic_articles = moved
    report.warnings.extend(warnings)

    # The process-wide tracker is the only place holding the WHOLE run: the
    # compile result's own cost snapshot predates the PRECISION pass.
    report.cost = tracker.summary()
    flush()
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_derive_kb.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Run the whole Python suite for regressions**

Run: `cd py && uv run pytest tests/ -q`
Expected: PASS, no pre-existing test broken

- [ ] **Step 6: Commit**

```bash
git add py/src/kb_ai/derive/__init__.py py/tests/test_derive_kb.py
git commit -m "feat(derive): add the derive_kb orchestrator and provenance manifest"
```

---

## Task 8: `kb-ai derive` CLI with the volume gate

Spec: F1–F6, C2. Tech design: "Module layout".

**Files:**
- Create: `py/src/kb_ai/commands/derive.py`
- Modify: `py/src/kb_ai/__main__.py:41-56`
- Test: `py/tests/test_commands_derive.py`
- Test: `py/tests/test_main_registry.py` (append)

**Interfaces:**
- Consumes: `derive_kb`, `DeriveReport` (Task 7), `KBError`,
  `kb_ai.__main__.respond`.
- Produces: `kb_ai.commands.derive.run_derive(argv: list[str]) -> None`,
  `build_parser() -> argparse.ArgumentParser`, and the `"derive"` key in
  `__main__.COMMANDS`.

- [ ] **Step 1: Write the failing tests**

Create `py/tests/test_commands_derive.py`:

```python
"""Tests for the kb-ai derive CLI: payload shape, error codes, volume gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import SlugExistsError
from kb_ai.commands import derive as derive_cmd
from kb_ai.derive._types import DeriveReport, DocumentRef, Skipped


def _report(**over) -> DeriveReport:
    base = DeriveReport(
        derived_kb="/kb/derived/pricing", slug="pricing", topic="pricing",
        selected_articles=["wiki/a.md"],
        skipped_articles=[Skipped(ref="wiki/b.md", reason="no_sources_key")],
        documents=[DocumentRef(rel_path="raw/a.md", checksum="a" * 16, size_bytes=2048)],
        filter_batches=2, offtopic_articles=["wiki/c.md"], compiled=True,
        compile={"compiled": 1, "cost": {"total_cost_usd": 0.5}},
        cost={"total_cost_usd": 0.75},
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def _run(monkeypatch, argv, *, derive=None):
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: out.append(str(a[0])) if a else None)
    if derive is not None:
        monkeypatch.setattr(derive_cmd, "derive_kb", derive)
    derive_cmd.run_derive(argv)
    return json.loads(out[-1])


def test_defaults_kb_to_dot_kaas():
    args = derive_cmd.build_parser().parse_args(["pricing"])
    assert args.kb == "./.kaas"
    assert args.slug is None and args.force is False and args.yes is False


def test_success_payload(monkeypatch):
    seen: dict = {}

    def fake_derive(source_kb, topic, **kw):
        seen.update({"source_kb": source_kb, "topic": topic, **kw})
        return _report()

    resp = _run(monkeypatch, ["pricing", "--kb", "/kb", "--yes"], derive=fake_derive)

    assert resp["ok"] is True
    data = resp["data"]
    assert data["derived_kb"] == "/kb/derived/pricing"
    assert data["slug"] == "pricing"
    assert data["topic"] == "pricing"
    assert data["selected"] == 1
    assert data["skipped"] == [{"ref": "wiki/b.md", "reason": "no_sources_key"}]
    assert data["documents"] == 1
    assert data["bytes"] == 2048
    assert data["offtopic"] == 1
    assert data["filter_batches"] == 2
    assert data["compiled"] is True
    assert data["compile"] == {"compiled": 1, "cost": {"total_cost_usd": 0.5}}
    assert data["cost"] == {"total_cost_usd": 0.75}
    assert "KAAS_KB_DIR=/kb/derived/pricing" in data["next"]
    assert seen["source_kb"] == "/kb"
    assert seen["approve"] is None  # --yes auto-approves


def test_failure_payload_carries_the_error_code(monkeypatch):
    def boom(*a, **kw):
        raise SlugExistsError("/kb/derived/pricing already exists; pass --force")

    resp = _run(monkeypatch, ["pricing", "--yes"], derive=boom)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "SLUG_EXISTS"
    assert "--force" in resp["error"]["message"]


def test_unexpected_error_is_not_swallowed(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")

    with pytest.raises(RuntimeError):
        _run(monkeypatch, ["pricing", "--yes"], derive=boom)


def test_gate_declines_without_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: False, raising=False)
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve is not None
    assert approve(_report(compiled=False)) is False


def test_gate_accepts_a_yes_on_a_tty(monkeypatch):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve(_report(compiled=False)) is True


def test_gate_rejects_anything_else_on_a_tty(monkeypatch):
    monkeypatch.setattr(derive_cmd.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    approve = derive_cmd._make_approve(derive_cmd.build_parser().parse_args(["pricing"]))
    assert approve(_report(compiled=False)) is False


def test_declined_run_reports_ok_with_compiled_false(monkeypatch):
    resp = _run(monkeypatch, ["pricing", "--yes"],
                derive=lambda *a, **kw: _report(compiled=False, compile=None,
                                                offtopic_articles=[], cost=None))
    assert resp["ok"] is True
    assert resp["data"]["compiled"] is False
    assert "--force" in resp["data"]["next"]
```

Append to `py/tests/test_main_registry.py`:

```python
def test_derive_command_is_registered():
    from kb_ai.__main__ import COMMANDS

    assert "derive" in COMMANDS
    assert callable(COMMANDS["derive"]())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_commands_derive.py tests/test_main_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kb_ai.commands.derive'`

- [ ] **Step 3: Write `commands/derive.py`**

```python
"""kb-ai derive -- build a topic-scoped knowledge base (spec F1-F6).

Holds every CLI concern the core deliberately does not know about: argparse, the
volume gate's TTY prompt, and the bridge-protocol response. The gate is passed
into derive_kb as the `approve` callback.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from kb_ai._errors import KBError
from kb_ai.derive import DeriveReport, derive_kb

_DEFAULT_MODEL = "claude-sonnet-4-6"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb-ai derive")
    parser.add_argument("topic", help="topic to scope the derived knowledge base to")
    parser.add_argument("--kb", default="./.kaas",
                        help="source knowledge-base directory (default: ./.kaas)")
    parser.add_argument("--slug", default=None,
                        help="directory name under derived/ (default: from the topic)")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing derived/<slug>/ from a previous run")
    parser.add_argument("--model", default=None,
                        help="model for the topic filter and the derived compile")
    parser.add_argument("--yes", action="store_true",
                        help="skip the volume gate and compile without confirming")
    return parser


def _make_approve(args: argparse.Namespace) -> Callable[[DeriveReport], bool] | None:
    """The volume gate (F5), or None to auto-approve when --yes was given.

    Reports articles matched, documents resolved and total bytes -- deliberately
    no cost figure: there is no pre-compile estimator in this repository, and a
    guessed one would be worse than none.
    """
    if args.yes:
        return None

    def approve(report: DeriveReport) -> bool:
        total_bytes = sum(d.size_bytes for d in report.documents)
        print(f"[derive] topic: {report.topic}", file=sys.stderr)
        print(f"[derive] {len(report.selected_articles)} articles matched, "
              f"{len(report.documents)} documents resolved, "
              f"{total_bytes:,} bytes to compile", file=sys.stderr)
        if not sys.stdin.isatty():
            print("[derive] no TTY to confirm on and --yes not given; stopping "
                  "before the compile. Re-run with --yes --force to proceed.",
                  file=sys.stderr)
            return False
        answer = input("Compile the derived knowledge base? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    return approve


def run_derive(argv: list[str]) -> None:
    from kb_ai.__main__ import respond

    args = build_parser().parse_args(argv)
    model = args.model or os.environ.get("LLM_MODEL") or _DEFAULT_MODEL

    try:
        report = derive_kb(
            args.kb, args.topic,
            slug=args.slug, force=args.force, model=model,
            approve=_make_approve(args),
        )
    except KBError as e:
        respond(False, error={"code": e.code, "message": str(e)})
        return

    if report.compiled:
        next_step = f"Register MCP: KAAS_KB_DIR={report.derived_kb} kb-ai mcp"
    else:
        next_step = (f"Declined before compiling. Re-run with --force --yes to "
                     f"compile {report.derived_kb} without re-resolving documents.")

    respond(True, data={
        "derived_kb": report.derived_kb,
        "slug": report.slug,
        "topic": report.topic,
        "selected": len(report.selected_articles),
        "skipped": [{"ref": s.ref, "reason": s.reason}
                    for s in report.skipped_articles + report.skipped_documents],
        "documents": len(report.documents),
        "bytes": sum(d.size_bytes for d in report.documents),
        "offtopic": len(report.offtopic_articles),
        "filter_batches": report.filter_batches,
        "dropped_invented_paths": report.dropped_invented_paths,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
        "next": next_step,
    })
```

- [ ] **Step 4: Register the command**

In `py/src/kb_ai/__main__.py`, add inside `_lazy_commands()` after the `distill`
closure (line 43):

```python
    def derive():
        from kb_ai.commands.derive import run_derive
        return lambda: run_derive(sys.argv[2:])
```

and add `"derive": derive,` to the returned dict, after `"distill": distill,`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_commands_derive.py tests/test_main_registry.py tests/test_command_entrypoints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add py/src/kb_ai/commands/derive.py py/src/kb_ai/__main__.py py/tests/test_commands_derive.py py/tests/test_main_registry.py
git commit -m "feat(derive): add the kb-ai derive command with a volume gate"
```

---

## Task 9: Prove nesting is inert

Spec: C6, D4. Tech design: risk table ("Nesting turns out not to be inert").

This is the assumption the whole design rests on, and it is a test, not a
comment.

**Files:**
- Test: `py/tests/test_derive_nesting.py`

**Interfaces:**
- Consumes: `derive_kb` (Task 7), the real `update_markdown_index` and the real
  `KBStore.list_raw_files`.

- [ ] **Step 1: Write the failing test**

Create `py/tests/test_derive_nesting.py`:

```python
"""A derived KB must be invisible to its source KB's compile and index (C6, D4)."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import derive_kb
from kb_ai.derive._types import MODE_RECALL, SelectionResult
from kb_ai.storage.index import update_markdown_index
from kb_ai.storage.store import KBStore


def _source_kb(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    (kb / "wiki").mkdir(parents=True)
    (kb / "index").mkdir(parents=True)
    (kb / "raw" / "notes.md").write_text("Fee schedule.")
    (kb / "wiki" / "pricing.md").write_text(
        "---\ntitle: Pricing\ntags: [fees]\nsources:\n  - raw/notes.md\n---\n\n# Pricing\n\nProse.\n")
    update_markdown_index(KBStore(str(kb)))
    return kb


def _select(catalog, topic, mode):
    if mode == MODE_RECALL:
        return SelectionResult(paths=[a.path for a in catalog], batches=1,
                               dropped_invented=0, skipped=[])
    return SelectionResult(paths=["wiki/derived-only.md"], batches=1,
                           dropped_invented=0, skipped=[])


def _fake_compile(derived_dir: str, **kwargs) -> dict:
    base = Path(derived_dir)
    (base / "wiki").mkdir(parents=True, exist_ok=True)
    (base / "index").mkdir(parents=True, exist_ok=True)
    (base / "wiki" / "derived-only.md").write_text(
        "---\ntitle: Derived Only\ntags: [fees]\n---\n\n# Derived Only\n\nProse.\n")
    (base / "wiki" / "moved-aside.md").write_text(
        "---\ntitle: Moved Aside\ntags: [misc]\n---\n\n# Moved Aside\n\nProse.\n")
    update_markdown_index(KBStore(str(base)))
    return {"compiled": 2}


def test_source_compile_and_index_do_not_see_the_derived_kb(tmp_path: Path):
    kb = _source_kb(tmp_path)
    report = derive_kb(str(kb), "pricing", model="m", slug="pricing",
                       select=_select, compile_fn=_fake_compile)
    assert report.offtopic_articles == ["wiki/moved-aside.md"]

    store = KBStore(str(kb))

    # The source's raw scan must not pick up the copied documents.
    rel_paths = [rf.rel_path for rf in store.list_raw_files()]
    assert rel_paths == ["raw/notes.md"]

    # The source's index rebuild must not list derived or _offtopic articles.
    update_markdown_index(store)
    catalog = (kb / "index" / "master-index.md").read_text()
    assert "wiki/pricing.md" in catalog
    assert "derived" not in catalog
    assert "derived-only" not in catalog
    assert "moved-aside" not in catalog

    # The source catalog parses back to exactly its own article.
    assert [a.path for a in store.existing_articles()] == ["wiki/pricing.md"]


def test_offtopic_is_outside_the_derived_kbs_own_index(tmp_path: Path):
    kb = _source_kb(tmp_path)
    derive_kb(str(kb), "pricing", model="m", slug="pricing",
              select=_select, compile_fn=_fake_compile)

    derived = kb / "derived" / "pricing"
    derived_catalog = (derived / "index" / "master-index.md").read_text()
    assert "wiki/derived-only.md" in derived_catalog
    assert "moved-aside" not in derived_catalog
    assert (derived / "_offtopic" / "moved-aside.md").exists()
```

- [ ] **Step 2: Run the test**

Run: `cd py && uv run pytest tests/test_derive_nesting.py -v`
Expected: PASS (Tasks 3–7 already make nesting inert; this test locks it in). If
it FAILS, that is the design assumption breaking — stop and report, do not patch
the test.

- [ ] **Step 3: Also check the Go-side scan assumptions**

Run: `grep -rn 'filepath.Join(.*"raw"' internal/ && grep -rn '"wiki"' internal/api/wiki.go`
Expected: every raw write is `filepath.Join(KBDir, "raw", …)` and the wiki walker
is rooted at `filepath.Join(s.cfg.KBDir, "wiki")` — neither reaches
`<kb>/derived/`. Record the grep output in `notes.md` under a
"C6 verification" heading.

- [ ] **Step 4: Commit**

```bash
git add py/tests/test_derive_nesting.py docs/features/derive-topic-kb-from-catalog/notes.md
git commit -m "test(derive): lock in that a derived KB is invisible to its source"
```

---

## Task 10: Real smoke run and Stage 1 sign-off

Spec: I3, and the "off-topic bleed" risk in the tech design. This is the task
that says whether the design works.

**Files:**
- Create/modify: `docs/features/derive-topic-kb-from-catalog/notes.md`

- [ ] **Step 1: Compile a knowledge base from this repository**

```bash
cd /Users/hk00691ml/develop/ai/github/kaas
rm -rf /tmp/kaas-derive-smoke && mkdir -p /tmp/kaas-derive-smoke
uv --directory py run kb-ai distill . --kb /tmp/kaas-derive-smoke 2>&1 | tail -20
```

Expected: `{"ok": true, ...}` with a non-zero `compiled` count and
`/tmp/kaas-derive-smoke/index/master-index.md` present. Record the article count:

```bash
grep -c '^- \[' /tmp/kaas-derive-smoke/index/master-index.md
```

- [ ] **Step 2: Derive a topic, answering the gate**

```bash
uv --directory py run kb-ai derive "retrieval and the chat answer path" \
  --kb /tmp/kaas-derive-smoke --yes 2>&1 | tail -40
```

Expected: `"ok": true`, `compiled: true`, and a non-empty
`/tmp/kaas-derive-smoke/derived/retrieval-and-the-chat-answer-path/wiki/`.

- [ ] **Step 3: Run the gate interactively once, to prove F5 works**

```bash
uv --directory py run kb-ai derive "cost accounting" --kb /tmp/kaas-derive-smoke
```

Answer `n` at the prompt. Expected: `"compiled": false`, and
`derived/cost-accounting/{raw,manifest.json}` present with no `wiki/`.

- [ ] **Step 4: Ask the derived KB a question over MCP-less chat**

```bash
KAAS_KB_DIR=/tmp/kaas-derive-smoke/derived/retrieval-and-the-chat-answer-path \
  uv --directory py run kb-ai mcp --help
```

(The full MCP `kb` selector lands in Stage 2; this only confirms the derived
directory is a loadable KB root. A grounded answer is checked in Task 12.)

- [ ] **Step 5: Write the numbers into `notes.md`**

Append a section with every figure below, each labelled with where it came from
so a reader can reproduce it:

```markdown
## Smoke run (spec I3)

Date: <YYYY-MM-DD> · Model: <exact model id> · Source: a KB compiled from this
repository with `kb-ai distill . --kb /tmp/kaas-derive-smoke`

| Figure | Value | Where it came from |
|---|---|---|
| Source articles | <n> | `grep -c '^- \[' .../index/master-index.md` |
| Topic | `retrieval and the chat answer path` | CLI argument |
| Filter batches | <n> | `data.filter_batches` |
| Articles matched | <n> | `data.selected` |
| Articles skipped (no sources etc.) | <n> | `data.skipped` |
| Documents resolved | <n> | `data.documents` |
| Bytes to compile | <n> | `data.bytes` |
| Articles compiled | <n> | `data.compile.compiled` |
| Articles moved off-topic | <n> | `data.offtopic` |
| **Move ratio** | <offtopic / compiled> | derived from the two rows above |
| Extract-cache hits | <n> | `[cached]` lines in `derived/<slug>/.compile.log` |
| Total cost | <n> USD | `data.cost.total_cost_usd` |

### Reading of the move ratio

<One paragraph. A ratio near 0 means the PRECISION pass is too permissive and
does nothing; near 1 means it is too strict, or the bleed is so bad that the
compile was mostly wasted. The tech design's stated answer if the ratio is bad
is to revisit brainstorm decision 1 (filter at the article level) rather than to
tune prompts — say which way the evidence points.>
```

- [ ] **Step 6: Run the gate on the whole Python suite once more, then commit**

```bash
cd py && uv run pytest tests/ -q
cd .. && git add docs/features/derive-topic-kb-from-catalog/notes.md
git commit -m "docs(derive): record the Stage 1 smoke run and move ratio"
```

**Stage 1 checkpoint.** Report the smoke-run table before starting Stage 2. If
the move ratio says the design does not work, stop: Stages 2 and 3 are plumbing
for a feature whose core would then need rethinking.

---

# Stage 2 — MCP `ask` reads a derived KB

Covers spec G3, G4. Read-only: agents query derived KBs, they do not build them
(decision O2). Both MCP servers need the parameter — the Python one is the stdio
transport, the Go one is the remote transport.

## Task 11: `ask(kb=…)` in the Python MCP server

Spec: G3, G4.

**Files:**
- Modify: `py/src/kb_ai/server_mcp.py:57-97`
- Test: `py/tests/test_server_mcp.py` (append)

**Interfaces:**
- Consumes: `kb_ai.derive.resolve_kb_dir` (Task 3), `kb_ai._errors.DeriveError`.
- Produces: `ask(query, paths=None, model=None, kb=None) -> dict` — unchanged
  return shape.

- [ ] **Step 1: Write the failing tests**

Append to `py/tests/test_server_mcp.py`:

```python
def test_ask_without_kb_uses_the_root(tmp_path, monkeypatch):
    from kb_ai import server_mcp

    seen: dict = {}

    def fake_chat(input_data, emit):
        seen.update(input_data)
        emit({"type": "delta", "content": "answer"})
        emit({"type": "done", "cited_sources": [], "cost_usd": 0.0})

    monkeypatch.setattr(server_mcp, "run_server_chat_http", fake_chat)
    monkeypatch.setenv("KAAS_KB_DIR", str(tmp_path))

    out = server_mcp.ask("q")
    assert out["answer"] == "answer"
    assert seen["kb_dir"] == str(tmp_path.resolve())


def test_ask_with_a_known_kb_slug(tmp_path, monkeypatch):
    from kb_ai import server_mcp

    derived = tmp_path / "derived" / "pricing"
    derived.mkdir(parents=True)
    (derived / "manifest.json").write_text("{}")

    seen: dict = {}

    def fake_chat(input_data, emit):
        seen.update(input_data)
        emit({"type": "done", "cited_sources": [], "cost_usd": 0.0})

    monkeypatch.setattr(server_mcp, "run_server_chat_http", fake_chat)
    monkeypatch.setenv("KAAS_KB_DIR", str(tmp_path))

    server_mcp.ask("q", kb="pricing")
    assert seen["kb_dir"] == str(derived.resolve())


def test_ask_with_an_unknown_kb_slug_raises(tmp_path, monkeypatch):
    import pytest

    from kb_ai import server_mcp
    from kb_ai._errors import UnknownDerivedKBError

    def fake_chat(input_data, emit):
        raise AssertionError("chat must not run for an unknown kb")

    monkeypatch.setattr(server_mcp, "run_server_chat_http", fake_chat)
    monkeypatch.setenv("KAAS_KB_DIR", str(tmp_path))

    with pytest.raises(UnknownDerivedKBError):
        server_mcp.ask("q", kb="nope")


def test_ask_with_a_traversal_kb_slug_raises(tmp_path, monkeypatch):
    import pytest

    from kb_ai import server_mcp
    from kb_ai._errors import InvalidSlugError

    monkeypatch.setattr(server_mcp, "run_server_chat_http",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no chat")))
    monkeypatch.setenv("KAAS_KB_DIR", str(tmp_path))

    with pytest.raises(InvalidSlugError):
        server_mcp.ask("q", kb="../../etc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd py && uv run pytest tests/test_server_mcp.py -k kb -v`
Expected: FAIL — `TypeError: ask() got an unexpected keyword argument 'kb'`

- [ ] **Step 3: Add the parameter**

In `py/src/kb_ai/server_mcp.py`, replace the `ask` signature and the `input_data`
assembly (lines 58 and 83):

```python
@mcp.tool()
def ask(query: str, paths: list[str] | None = None, model: str | None = None,
        kb: str | None = None) -> dict:
    """Ask the compiled KaaS wiki a question; returns a cited answer.

    Args:
        query: Natural-language question.
        paths: Optional wiki article paths to ground the answer in (skips
            master-index navigation and reads those pages in full).
        model: Optional chat model override.
        kb: Optional derived knowledge-base slug (a directory under
            <kb_dir>/derived/). Omit for the root knowledge base. An unknown slug
            is an error, never a silent fallback to the root: answering from the
            wrong corpus is worse than failing.

    Returns a dict: {answer (markdown, inline citations + Sources footer),
    sources [{title, path}], cost_usd}.
    """
```

and, in the body, replace the `input_data` line:

```python
    from kb_ai.derive import resolve_kb_dir

    input_data: dict = {"query": query, "kb_dir": resolve_kb_dir(_kb_dir(), kb),
                        "include_sources": True}
```

The import is function-local on purpose: `server_mcp` is imported by
`__main__` on the `mcp` command path, and `kb_ai.derive` pulls in `storage` and
`llm`, which the module-level import list deliberately keeps out.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd py && uv run pytest tests/test_server_mcp.py tests/test_server_mcp_paths.py -v`
Expected: PASS, including the pre-existing tests

- [ ] **Step 5: Commit**

```bash
git add py/src/kb_ai/server_mcp.py py/tests/test_server_mcp.py
git commit -m "feat(mcp): let ask target a derived knowledge base by slug"
```

---

## Task 12: `kb` on the Go MCP `ask` tool

Spec: G3, G4. Tech design: "Validation happens in Go *and* Python".

**Files:**
- Create: `internal/kbpath/kbpath.go`
- Create: `internal/kbpath/kbpath_test.go`
- Modify: `internal/mcp/schema.go:6-24`
- Modify: `internal/mcp/ask.go:14-48`
- Test: `internal/mcp/schema_test.go` (append), `internal/mcp/handler_test.go` (append)

**Interfaces:**
- Produces: `kbpath.Resolve(root, slug string) (string, error)`,
  `kbpath.ErrInvalidSlug`, `kbpath.ErrUnknownKB`, `kbpath.ValidSlug(string) bool`.
- Consumed by: Task 12 (mcp) and Tasks 16–17 (api).

- [ ] **Step 1: Write the failing tests**

Create `internal/kbpath/kbpath_test.go`:

```go
package kbpath

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestValidSlug(t *testing.T) {
	tests := []struct {
		slug string
		want bool
	}{
		{"pricing", true},
		{"pricing-and-fees", true},
		{"a", true},
		{"0abc", true},
		{"", false},
		{"-lead", false},
		{"Upper", false},
		{"a/b", false},
		{".", false},
		{"..", false},
		{"with space", false},
		{"under_score", false},
		{"定价", false},
	}
	for _, tc := range tests {
		if got := ValidSlug(tc.slug); got != tc.want {
			t.Errorf("ValidSlug(%q) = %v, want %v", tc.slug, got, tc.want)
		}
	}
}

func TestResolve(t *testing.T) {
	root := t.TempDir()
	derived := filepath.Join(root, "derived", "pricing")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(derived, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	// A directory under derived/ with no manifest is not a derived KB.
	if err := os.MkdirAll(filepath.Join(root, "derived", "junk"), 0o755); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name    string
		slug    string
		want    string
		wantErr error
	}{
		{"empty slug is the root", "", root, nil},
		{"known slug", "pricing", derived, nil},
		{"no manifest", "junk", "", ErrUnknownKB},
		{"absent", "nope", "", ErrUnknownKB},
		{"traversal", "../..", "", ErrInvalidSlug},
		{"absolute", "/etc", "", ErrInvalidSlug},
		{"uppercase", "Pricing", "", ErrInvalidSlug},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := Resolve(root, tc.slug)
			if tc.wantErr != nil {
				if !errors.Is(err, tc.wantErr) {
					t.Fatalf("Resolve(%q) err = %v, want %v", tc.slug, err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("Resolve(%q) unexpected err: %v", tc.slug, err)
			}
			if got != tc.want {
				t.Errorf("Resolve(%q) = %q, want %q", tc.slug, got, tc.want)
			}
		})
	}
}

func TestListSlugs(t *testing.T) {
	root := t.TempDir()
	for _, slug := range []string{"compliance", "pricing"} {
		d := filepath.Join(root, "derived", slug)
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(d, "manifest.json"), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(filepath.Join(root, "derived", "junk"), 0o755); err != nil {
		t.Fatal(err)
	}

	got, err := ListSlugs(root)
	if err != nil {
		t.Fatalf("ListSlugs: %v", err)
	}
	want := []string{"compliance", "pricing"}
	if len(got) != len(want) {
		t.Fatalf("ListSlugs = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("ListSlugs[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestListSlugsNoDerivedDir(t *testing.T) {
	got, err := ListSlugs(t.TempDir())
	if err != nil {
		t.Fatalf("ListSlugs: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("ListSlugs = %v, want empty", got)
	}
}
```

Append to `internal/mcp/schema_test.go`:

```go
func TestAskInputSchemaHasKB(t *testing.T) {
	var schema struct {
		Properties map[string]struct {
			Type        string `json:"type"`
			Description string `json:"description"`
		} `json:"properties"`
		Required []string `json:"required"`
	}
	if err := json.Unmarshal(askInputSchema, &schema); err != nil {
		t.Fatalf("unmarshal askInputSchema: %v", err)
	}
	kb, ok := schema.Properties["kb"]
	if !ok {
		t.Fatal("askInputSchema has no kb property")
	}
	if kb.Type != "string" {
		t.Errorf("kb type = %q, want string", kb.Type)
	}
	if kb.Description == "" {
		t.Error("kb property has no description")
	}
	for _, r := range schema.Required {
		if r == "kb" {
			t.Error("kb must not be required")
		}
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/kbpath/... ./internal/mcp/... -run 'Slug|Resolve|KB' -count=1`
Expected: FAIL — `no required module provides package .../internal/kbpath` and
`askInputSchema has no kb property`

- [ ] **Step 3: Write `internal/kbpath/kbpath.go`**

```go
// Package kbpath resolves a derived knowledge base's directory from a
// client-supplied slug.
//
// The slug arrives from MCP tool calls and HTTP query strings, so it is
// untrusted input to a path join. Validation is lexical here, matching the
// convention in internal/api/wiki.go; the Python layer runs its own
// symlink-resolving check (KBStore._resolve). Duplicating the check is
// deliberate: neither layer should trust the other's input.
package kbpath

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
)

// Sentinel errors callers map to their own status codes.
var (
	// ErrInvalidSlug is returned when a slug is not a single safe path segment.
	ErrInvalidSlug = errors.New("kbpath: invalid derived-kb slug")
	// ErrUnknownKB is returned when no derived knowledge base has that slug.
	// Never a fallback to the root KB: answering from the wrong corpus silently
	// is worse than an error.
	ErrUnknownKB = errors.New("kbpath: unknown derived knowledge base")
)

// DerivedDirName is the subdirectory of a KB holding its derived knowledge bases.
const DerivedDirName = "derived"

// manifestName marks a directory as one derive created. A directory under
// derived/ without it is not a derived KB.
const manifestName = "manifest.json"

// slugRe must stay in step with SLUG_RE in py/src/kb_ai/derive/_layout.py.
var slugRe = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,39}$`)

// ValidSlug reports whether slug is a single safe path segment.
func ValidSlug(slug string) bool {
	return slugRe.MatchString(slug)
}

// Resolve returns root for an empty slug, else <root>/derived/<slug>.
//
// Returns ErrInvalidSlug for a slug failing lexical validation and ErrUnknownKB
// when the directory does not exist or holds no manifest.json.
func Resolve(root, slug string) (string, error) {
	if slug == "" {
		return root, nil
	}
	if !ValidSlug(slug) {
		return "", fmt.Errorf("%w: %q", ErrInvalidSlug, slug)
	}
	dir := filepath.Join(root, DerivedDirName, slug)
	if _, err := os.Stat(filepath.Join(dir, manifestName)); err != nil {
		return "", fmt.Errorf("%w: %q", ErrUnknownKB, slug)
	}
	return dir, nil
}

// ListSlugs returns the slugs of every derived knowledge base under root,
// sorted. An absent derived/ directory yields an empty slice, not an error.
func ListSlugs(root string) ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(root, DerivedDirName))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("kbpath: read derived dir: %w", err)
	}
	var slugs []string
	for _, e := range entries {
		if !e.IsDir() || !ValidSlug(e.Name()) {
			continue
		}
		if _, err := os.Stat(filepath.Join(root, DerivedDirName, e.Name(), manifestName)); err != nil {
			continue
		}
		slugs = append(slugs, e.Name())
	}
	sort.Strings(slugs)
	return slugs, nil
}
```

- [ ] **Step 4: Add `kb` to the MCP schema and handler**

In `internal/mcp/schema.go`, add the property after `model`:

```go
		"model": {
			"type": "string",
			"description": "Optional chat model override."
		},
		"kb": {
			"type": "string",
			"description": "Optional derived knowledge-base slug (a directory under the KB's derived/). Omit to query the root knowledge base."
		}
```

In `internal/mcp/ask.go`, add the field and the resolution. Extend
`askArguments`:

```go
type askArguments struct {
	Query string   `json:"query"`
	Paths []string `json:"paths"`
	Model string   `json:"model"`
	KB    string   `json:"kb"`
}
```

and, after the `args.Query == ""` guard, resolve the KB directory before building
the chat request:

```go
	// kb reaches us from an MCP client, so it is untrusted input to a path join.
	kbDir, err := kbpath.Resolve(h.kbDir, args.KB)
	if err != nil {
		writeJSONRPCError(w, req.ID, -32602, "Invalid arguments: "+err.Error())
		return
	}
```

then change the `ChatRequest` literal's `KBDir` field:

```go
		KBDir:          kbDir,
```

Rename the existing `err :=` on the `h.chat(...)` call to `err =` since `err` is
now declared above, and add the import
`"github.com/bybit-exchange/kaas/internal/kbpath"`.

- [ ] **Step 5: Add the handler test**

Append to `internal/mcp/handler_test.go` (following the file's existing fake-chat
pattern — read it first and mirror the helper it already provides for building a
Handler and posting a `tools/call` request):

```go
func TestHandleAskResolvesDerivedKB(t *testing.T) {
	root := t.TempDir()
	derived := filepath.Join(root, "derived", "pricing")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(derived, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}

	var gotKBDir string
	chat := func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
		gotKBDir = req.KBDir
		return onEvent(json.RawMessage(`{"type":"done","cost_usd":0}`))
	}
	h := NewHandler(chat, root, "model", "", time.Minute, slog.Default())

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask","arguments":{"query":"q","kb":"pricing"}}}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body)))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if gotKBDir != derived {
		t.Errorf("KBDir = %q, want %q", gotKBDir, derived)
	}
}

func TestHandleAskRejectsUnknownDerivedKB(t *testing.T) {
	chat := func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
		t.Fatal("chat must not run for an unknown kb")
		return nil
	}
	h := NewHandler(chat, t.TempDir(), "model", "", time.Minute, slog.Default())

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask","arguments":{"query":"q","kb":"nope"}}}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body)))

	if !strings.Contains(rec.Body.String(), "unknown derived knowledge base") {
		t.Errorf("body = %s, want an unknown-kb error", rec.Body.String())
	}
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `go test ./internal/kbpath/... ./internal/mcp/... -count=1`
Expected: PASS

- [ ] **Step 7: Confirm the derived KB actually answers**

With the smoke-run KB from Task 10 still on disk:

```bash
cd /Users/hk00691ml/develop/ai/github/kaas/py
KAAS_KB_DIR=/tmp/kaas-derive-smoke uv run python -c "
from kb_ai.server_mcp import ask
out = ask('how does retrieval pick which articles to read?', kb='retrieval-and-the-chat-answer-path')
print(out['answer'][:600])
print('SOURCES:', [s['path'] for s in out['sources']])
"
```

Expected: a grounded answer whose source paths all come from the derived KB.
Record the source paths in `notes.md` under "Stage 2 verification".

- [ ] **Step 8: Commit**

```bash
git add internal/kbpath internal/mcp docs/features/derive-topic-kb-from-catalog/notes.md
git commit -m "feat(mcp): add the kb selector to the Go ask tool"
```

---

# Stage 3 — HTTP API and web UI

Covers spec H1–H6. The largest stage and the only one spanning Go and
TypeScript. Depends on both stages above.

## Task 13: `derived_jobs` table and store

Spec: H1, H1b. Tech design: "The queue problem" — Option A (decided).

A derive is KB-level work: filter → resolve → compile → prune. The existing
`Task` is document-shaped (`RawPath`, uniquely indexed `ContentHash`, and a
`Worker.Process` that runs one document through extract → pipeline), so
re-deriving a topic would collide with `ErrDuplicate`. A separate table keeps the
compile queue's hot path untouched and gives "one derive per slug at a time" for
free through a unique index.

**Files:**
- Modify: `internal/store/store.go`
- Create: `internal/store/sqlite/derived.go`
- Modify: `internal/store/sqlite/sqlite.go:88-104` (`Migrate`)
- Create: `internal/store/sqlite/derived_test.go`

**Interfaces:**
- Produces, in `store`:
  - `DerivedJob{ID, Slug, Topic, Model, Status, Stage, Error, Result, CreatedAt, UpdatedAt}`
  - `DerivedStatus{Pending,Running,Succeeded,Failed}` constants
  - `DerivedStage{Queued,Filter,Copy,Compile,Prune,Done}` constants
  - `ErrDerivedJobExists`
  - `DerivedJobStore` interface: `CreateDerivedJob`, `GetDerivedJob`,
    `ListDerivedJobs`, `ClaimNextDerivedJob`, `SetDerivedJobStage`,
    `FinishDerivedJob`
- Consumed by: Tasks 15, 16.

- [ ] **Step 1: Write the failing tests**

Create `internal/store/sqlite/derived_test.go`:

```go
package sqlite

import (
	"context"
	"errors"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

func newDerivedStore(t *testing.T) *Store {
	t.Helper()
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return s
}

func TestCreateAndGetDerivedJob(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	job := &store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "pricing and fees", Model: "m",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
		CreatedAt: 100, UpdatedAt: 100,
	}
	if err := s.CreateDerivedJob(ctx, job); err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := s.GetDerivedJob(ctx, "j1")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Slug != "pricing" || got.Topic != "pricing and fees" || got.Model != "m" {
		t.Errorf("round trip mismatch: %+v", got)
	}
	if got.Status != store.DerivedStatusPending || got.Stage != store.DerivedStageQueued {
		t.Errorf("status/stage = %q/%q", got.Status, got.Stage)
	}
}

func TestGetDerivedJobNotFound(t *testing.T) {
	s := newDerivedStore(t)
	if _, err := s.GetDerivedJob(context.Background(), "nope"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

func TestCreateDerivedJobRejectsAnActiveDuplicateSlug(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	first := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, first); err != nil {
		t.Fatalf("create first: %v", err)
	}
	second := &store.DerivedJob{ID: "j2", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 2, UpdatedAt: 2}
	if err := s.CreateDerivedJob(ctx, second); !errors.Is(err, store.ErrDerivedJobExists) {
		t.Errorf("err = %v, want ErrDerivedJobExists", err)
	}
}

func TestCreateDerivedJobAllowsTheSameSlugAfterATerminalRun(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	first := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, first); err != nil {
		t.Fatalf("create first: %v", err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatalf("claim: %v", err)
	}
	if err := s.FinishDerivedJob(ctx, "j1", store.DerivedStatusFailed, "boom", "", 3); err != nil {
		t.Fatalf("finish: %v", err)
	}
	second := &store.DerivedJob{ID: "j2", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 4, UpdatedAt: 4}
	if err := s.CreateDerivedJob(ctx, second); err != nil {
		t.Errorf("create after a terminal run: %v", err)
	}
}

func TestClaimNextDerivedJobIsSingleFlight(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for _, id := range []string{"j1", "j2"} {
		j := &store.DerivedJob{ID: id, Slug: id, Topic: "t", Status: store.DerivedStatusPending,
			Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", id, err)
		}
	}
	first, err := s.ClaimNextDerivedJob(ctx, 2)
	if err != nil || first == nil {
		t.Fatalf("first claim = %v, %v", first, err)
	}
	if first.ID != "j1" {
		t.Errorf("claimed %q, want the oldest (j1)", first.ID)
	}
	// A second claim must not hand out a job while one is running.
	second, err := s.ClaimNextDerivedJob(ctx, 3)
	if err != nil {
		t.Fatalf("second claim: %v", err)
	}
	if second != nil {
		t.Errorf("claimed %q while %q was running", second.ID, first.ID)
	}
}

func TestClaimNextDerivedJobEmptyQueue(t *testing.T) {
	s := newDerivedStore(t)
	got, err := s.ClaimNextDerivedJob(context.Background(), 1)
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	if got != nil {
		t.Errorf("claim = %+v, want nil", got)
	}
}

func TestSetDerivedJobStage(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	if err := s.SetDerivedJobStage(ctx, "j1", store.DerivedStageCompile, 3); err != nil {
		t.Fatalf("set stage: %v", err)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Stage != store.DerivedStageCompile || got.UpdatedAt != 3 {
		t.Errorf("job = %+v", got)
	}
}

func TestFinishDerivedJobRecordsTheResult(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	if err := s.FinishDerivedJob(ctx, "j1", store.DerivedStatusSucceeded, "", `{"documents":3}`, 4); err != nil {
		t.Fatalf("finish: %v", err)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Status != store.DerivedStatusSucceeded || got.Stage != store.DerivedStageDone {
		t.Errorf("status/stage = %q/%q", got.Status, got.Stage)
	}
	if got.Result != `{"documents":3}` || got.Error != "" {
		t.Errorf("result = %q, error = %q", got.Result, got.Error)
	}
}

func TestRecoverRunningDerivedJobs(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	// A restart leaves a job stuck in running with nobody driving it.
	n, err := s.RecoverRunningDerivedJobs(ctx, 3)
	if err != nil {
		t.Fatalf("recover: %v", err)
	}
	if n != 1 {
		t.Fatalf("recovered %d, want 1", n)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Status != store.DerivedStatusFailed {
		t.Errorf("status = %q, want failed", got.Status)
	}
	if got.Error == "" {
		t.Error("recovered job carries no error message")
	}
}

func TestListDerivedJobs(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for i, id := range []string{"j1", "j2"} {
		j := &store.DerivedJob{ID: id, Slug: id, Topic: "t", Status: store.DerivedStatusPending,
			Stage: store.DerivedStageQueued, CreatedAt: int64(i + 1), UpdatedAt: int64(i + 1)}
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatal(err)
		}
	}
	got, err := s.ListDerivedJobs(ctx, 10)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(got) != 2 || got[0].ID != "j2" {
		t.Errorf("list = %+v, want newest first", got)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/store/... -run Derived -count=1`
Expected: FAIL — `undefined: store.DerivedJob`

- [ ] **Step 3: Add the entity and interface to `internal/store/store.go`**

Append to the sentinel errors block:

```go
	// ErrDerivedJobExists is returned when a derive job for the same slug is
	// already pending or running. Terminal jobs do not block a re-derive.
	ErrDerivedJobExists = errors.New("store: derive job already active for slug")
```

and append to the file:

```go
// Derive job status values.
const (
	DerivedStatusPending   = "pending"
	DerivedStatusRunning   = "running"
	DerivedStatusSucceeded = "succeeded"
	DerivedStatusFailed    = "failed"
)

// Derive job stage values, reported on the job status endpoint. These describe
// one KB-level derive, which is why derive does not reuse Task's per-document
// Stage* values.
const (
	DerivedStageQueued  = "queued"
	DerivedStageFilter  = "filter"
	DerivedStageCopy    = "copy"
	DerivedStageCompile = "compile"
	DerivedStagePrune   = "prune"
	DerivedStageDone    = "done"
)

// DerivedJob is one request to build a topic-scoped knowledge base.
//
// Deliberately not a Task: Task is document-shaped (RawPath, uniquely indexed
// ContentHash) and Worker.Process runs one document through extract → pipeline,
// so re-deriving a topic would collide with ErrDuplicate and every document
// ingestion would pay for a branch it never takes.
type DerivedJob struct {
	ID        string // UUID
	Slug      string // derived/<slug>; unique among pending and running jobs
	Topic     string // the topic string handed to the filter
	Model     string // optional model override ("" = server default)
	Status    string // see DerivedStatus* constants
	Stage     string // see DerivedStage* constants
	Error     string // failure message, empty while healthy
	Result    string // JSON blob: counts and cost, written on success
	CreatedAt int64  // unix ms
	UpdatedAt int64  // unix ms
}

// DerivedJobStore persists derive jobs. Kept separate from Store so the compile
// queue's interface is unchanged; sqlite.Store implements both.
type DerivedJobStore interface {
	// CreateDerivedJob inserts a pending job. Returns ErrDerivedJobExists when a
	// pending or running job already holds that slug.
	CreateDerivedJob(ctx context.Context, j *DerivedJob) error
	// GetDerivedJob returns the job by id, or ErrNotFound.
	GetDerivedJob(ctx context.Context, id string) (*DerivedJob, error)
	// ListDerivedJobs returns the newest jobs first, capped at limit (0 = all).
	ListDerivedJobs(ctx context.Context, limit int) ([]*DerivedJob, error)
	// ClaimNextDerivedJob marks the oldest pending job running and returns it.
	// Returns (nil, nil) when nothing is pending OR when a job is already
	// running: a derive spends real money and rewrites a directory, so the
	// runner is single-flight by construction.
	ClaimNextDerivedJob(ctx context.Context, now int64) (*DerivedJob, error)
	// SetDerivedJobStage records progress on a running job.
	SetDerivedJobStage(ctx context.Context, id, stage string, now int64) error
	// FinishDerivedJob writes a terminal status with its error or result JSON.
	FinishDerivedJob(ctx context.Context, id, status, errMsg, result string, now int64) error
	// RecoverRunningDerivedJobs fails every job left running by a previous
	// process and returns the count. A derive is not resumable: it may have died
	// mid-compile, and the runner has no lease to pick back up.
	RecoverRunningDerivedJobs(ctx context.Context, now int64) (int, error)
}
```

- [ ] **Step 4: Write `internal/store/sqlite/derived.go`**

```go
package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/bybit-exchange/kaas/internal/store"
)

// derivedJobColumns is the canonical column order for SELECT + scanDerivedJob.
const derivedJobColumns = `id, slug, topic, model, status, stage, error, result,
	created_at, updated_at`

// derivedSchema holds KB-level derive jobs. The partial unique index is the
// whole point of the table: it enforces "one active derive per slug" in the
// database rather than in the runner, while leaving terminal rows as history a
// re-derive can sit alongside.
const derivedSchema = `
CREATE TABLE IF NOT EXISTS derived_jobs (
	id         TEXT PRIMARY KEY,
	slug       TEXT NOT NULL,
	topic      TEXT NOT NULL,
	model      TEXT NOT NULL DEFAULT '',
	status     TEXT NOT NULL,
	stage      TEXT NOT NULL,
	error      TEXT NOT NULL DEFAULT '',
	result     TEXT NOT NULL DEFAULT '',
	created_at INTEGER NOT NULL,
	updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_derived_jobs_active_slug
	ON derived_jobs(slug) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_derived_jobs_status_created
	ON derived_jobs(status, created_at);
`

func scanDerivedJob(row interface{ Scan(...any) error }) (*store.DerivedJob, error) {
	var j store.DerivedJob
	err := row.Scan(&j.ID, &j.Slug, &j.Topic, &j.Model, &j.Status, &j.Stage,
		&j.Error, &j.Result, &j.CreatedAt, &j.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &j, nil
}

// CreateDerivedJob inserts a pending job, mapping the partial unique index
// violation onto ErrDerivedJobExists.
func (s *Store) CreateDerivedJob(ctx context.Context, j *store.DerivedJob) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO derived_jobs (`+derivedJobColumns+`)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		j.ID, j.Slug, j.Topic, j.Model, j.Status, j.Stage, j.Error, j.Result,
		j.CreatedAt, j.UpdatedAt)
	if err != nil {
		if isUniqueViolation(err) {
			return fmt.Errorf("%w: %q", store.ErrDerivedJobExists, j.Slug)
		}
		return fmt.Errorf("create derived job: %w", err)
	}
	return nil
}

// GetDerivedJob returns the job by id, or store.ErrNotFound.
func (s *Store) GetDerivedJob(ctx context.Context, id string) (*store.DerivedJob, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT `+derivedJobColumns+` FROM derived_jobs WHERE id = ?`, id)
	j, err := scanDerivedJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, store.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get derived job: %w", err)
	}
	return j, nil
}

// ListDerivedJobs returns the newest jobs first.
func (s *Store) ListDerivedJobs(ctx context.Context, limit int) ([]*store.DerivedJob, error) {
	q := `SELECT ` + derivedJobColumns + ` FROM derived_jobs ORDER BY created_at DESC`
	args := []any{}
	if limit > 0 {
		q += ` LIMIT ?`
		args = append(args, limit)
	}
	rows, err := s.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("list derived jobs: %w", err)
	}
	defer rows.Close()

	var out []*store.DerivedJob
	for rows.Next() {
		j, err := scanDerivedJob(rows)
		if err != nil {
			return nil, fmt.Errorf("list derived jobs: scan: %w", err)
		}
		out = append(out, j)
	}
	return out, rows.Err()
}

// ClaimNextDerivedJob marks the oldest pending job running, but only when no job
// is already running: a derive rewrites a directory and spends money, so
// single-flight is enforced here rather than trusted to the caller.
func (s *Store) ClaimNextDerivedJob(ctx context.Context, now int64) (*store.DerivedJob, error) {
	row := s.db.QueryRowContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, updated_at = ?
		WHERE id = (
			SELECT id FROM derived_jobs WHERE status = ?
			ORDER BY created_at ASC LIMIT 1
		)
		AND NOT EXISTS (SELECT 1 FROM derived_jobs WHERE status = ?)
		RETURNING `+derivedJobColumns,
		store.DerivedStatusRunning, store.DerivedStageFilter, now,
		store.DerivedStatusPending, store.DerivedStatusRunning)
	j, err := scanDerivedJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("claim derived job: %w", err)
	}
	return j, nil
}

// SetDerivedJobStage records progress on a running job.
func (s *Store) SetDerivedJobStage(ctx context.Context, id, stage string, now int64) error {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET stage = ?, updated_at = ?
		WHERE id = ? AND status = ?`,
		stage, now, id, store.DerivedStatusRunning)
	if err != nil {
		return fmt.Errorf("set derived job stage: %w", err)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return store.ErrNotFound
	}
	return nil
}

// FinishDerivedJob writes a terminal status. Stage always lands on done, so a
// failed job's last stage is readable from its error rather than from stage.
func (s *Store) FinishDerivedJob(ctx context.Context, id, status, errMsg, result string, now int64) error {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, error = ?, result = ?, updated_at = ?
		WHERE id = ? AND status = ?`,
		status, store.DerivedStageDone, errMsg, result, now, id, store.DerivedStatusRunning)
	if err != nil {
		return fmt.Errorf("finish derived job: %w", err)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return store.ErrNotFound
	}
	return nil
}

// RecoverRunningDerivedJobs fails every job a previous process left running.
//
// Not requeued: a derive is not resumable. It may have died anywhere between the
// filter and the prune, and re-running it from the start would need --force to
// get past the directory it already created. Failing loudly puts that decision
// back with the operator.
func (s *Store) RecoverRunningDerivedJobs(ctx context.Context, now int64) (int, error) {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, error = ?, updated_at = ?
		WHERE status = ?`,
		store.DerivedStatusFailed, store.DerivedStageDone,
		"interrupted by a backend restart; re-run the derive with force enabled",
		now, store.DerivedStatusRunning)
	if err != nil {
		return 0, fmt.Errorf("recover derived jobs: %w", err)
	}
	n, _ := res.RowsAffected()
	return int(n), nil
}
```

If `isUniqueViolation` does not already exist in the package, check
`internal/store/sqlite/errors_test.go` and the `CreateTask` implementation for
how the content-hash clash is detected today (it uses `sqlitedrv`/`sqlitelib`
constants) and reuse that helper; extract it into a shared function if
`CreateTask` inlines it.

- [ ] **Step 5: Run the migration**

In `internal/store/sqlite/sqlite.go`, inside `Migrate`, after the session schema
exec:

```go
	if _, err := s.db.ExecContext(ctx, derivedSchema); err != nil {
		return fmt.Errorf("migrate derived schema: %w", err)
	}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `go test ./internal/store/... -count=1`
Expected: PASS, including the pre-existing task and session tests

- [ ] **Step 7: Commit**

```bash
git add internal/store
git commit -m "feat(store): add the derived_jobs table and its single-flight claim"
```

---

## Task 14: `derive` bridge command

Spec: H1. Tech design: "Bridge command".

**Files:**
- Modify: `internal/bridge/api.go` (append a Derive section)
- Modify: `internal/bridge/daemon_client.go` (after `Index`, line 218)
- Modify: `py/src/kb_ai/server_daemon.py` (a `_handle_derive` plus the dispatch arm)
- Test: `internal/bridge/daemon_client_test.go` (append)
- Test: `py/tests/test_server_daemon.py` (append)

**Interfaces:**
- Produces: `bridge.DeriveRequest{KBDir, Topic, Slug, Force, Model}`,
  `bridge.DeriveResponse` (mirrors the CLI's success payload),
  `(*DaemonClient).Derive(ctx, DeriveRequest) (*DeriveResponse, error)`, and the
  daemon's `derive` command.
- Consumed by: Task 15.

- [ ] **Step 1: Write the failing tests**

Append to `internal/bridge/daemon_client_test.go` (mirror the file's existing
fake-daemon harness — read how `TestIndex`-style tests stub `daemon.call` and
reuse it):

```go
func TestDeriveMarshalsTheRequestAndDecodesTheResponse(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: true, Data: json.RawMessage(`{
		"derived_kb": "/kb/derived/pricing",
		"slug": "pricing",
		"topic": "pricing",
		"selected": 4,
		"documents": 3,
		"bytes": 2048,
		"offtopic": 1,
		"filter_batches": 2,
		"compiled": true,
		"cost": {"total_cost_usd": 1.5}
	}`)}

	got, err := c.Derive(context.Background(), DeriveRequest{
		KBDir: "/kb", Topic: "pricing", Slug: "pricing", Force: true, Model: "m",
	})
	if err != nil {
		t.Fatalf("Derive: %v", err)
	}
	if fake.lastCmd != "derive" {
		t.Errorf("cmd = %q, want derive", fake.lastCmd)
	}
	var sent DeriveRequest
	if err := json.Unmarshal(fake.lastPayload, &sent); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if sent.KBDir != "/kb" || sent.Topic != "pricing" || !sent.Force || sent.Model != "m" {
		t.Errorf("sent = %+v", sent)
	}
	if got.Slug != "pricing" || got.Documents != 3 || !got.Compiled {
		t.Errorf("got = %+v", got)
	}
}

func TestDeriveSurfacesAnEngineError(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: false,
		Error: &APIError{Code: "SLUG_EXISTS", Message: "already exists"}}

	_, err := c.Derive(context.Background(), DeriveRequest{KBDir: "/kb", Topic: "t"})
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Code != "SLUG_EXISTS" {
		t.Fatalf("err = %v, want an APIError with SLUG_EXISTS", err)
	}
}
```

Append to `py/tests/test_server_daemon.py`:

```python
def test_derive_command_dispatches_to_derive_kb(monkeypatch):
    from kb_ai import server_daemon

    seen: dict = {}
    responses: list[dict] = []

    class _Report:
        derived_kb = "/kb/derived/pricing"
        slug = "pricing"
        topic = "pricing"
        selected_articles = ["wiki/a.md"]
        skipped_articles: list = []
        skipped_documents: list = []
        documents: list = []
        dropped_invented_paths = 0
        filter_batches = 1
        offtopic_articles: list = []
        compiled = True
        compile = {"compiled": 1}
        cost = {"total_cost_usd": 0.25}
        warnings: list = []

    def fake_derive_kb(source_kb, topic, **kw):
        seen.update({"source_kb": source_kb, "topic": topic, **kw})
        return _Report()

    monkeypatch.setattr("kb_ai.derive.derive_kb", fake_derive_kb)
    monkeypatch.setattr(server_daemon, "_respond_ok",
                        lambda rid, data: responses.append(data))

    server_daemon._handle_derive("req-1", {"payload": {
        "kb_dir": "/kb", "topic": "pricing", "slug": "pricing", "force": True, "model": "m",
    }})

    assert seen["source_kb"] == "/kb"
    assert seen["topic"] == "pricing"
    assert seen["slug"] == "pricing"
    assert seen["force"] is True
    assert seen["model"] == "m"
    assert seen["approve"] is None  # H5: no volume gate on the async path
    assert responses[0]["slug"] == "pricing"
    assert responses[0]["compiled"] is True
    assert responses[0]["cost"] == {"total_cost_usd": 0.25}


def test_derive_command_reports_a_domain_error_code(monkeypatch):
    from kb_ai import server_daemon
    from kb_ai._errors import SlugExistsError

    errors_seen: list = []

    def boom(*a, **kw):
        raise SlugExistsError("already exists")

    monkeypatch.setattr("kb_ai.derive.derive_kb", boom)
    monkeypatch.setattr(server_daemon, "_respond_error",
                        lambda rid, code, msg: errors_seen.append((code, msg)))

    server_daemon._handle_derive("req-1", {"payload": {"kb_dir": "/kb", "topic": "t"}})
    assert errors_seen[0][0] == "SLUG_EXISTS"


def test_derive_requires_a_topic(monkeypatch):
    from kb_ai import server_daemon

    errors_seen: list = []
    monkeypatch.setattr(server_daemon, "_respond_error",
                        lambda rid, code, msg: errors_seen.append((code, msg)))

    server_daemon._handle_derive("req-1", {"payload": {"kb_dir": "/kb"}})
    assert errors_seen[0][0] == "EMPTY_TOPIC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/bridge/... -run Derive -count=1 && cd py && uv run pytest tests/test_server_daemon.py -k derive -v`
Expected: FAIL — `undefined: DeriveRequest`, and
`AttributeError: module 'kb_ai.server_daemon' has no attribute '_handle_derive'`

- [ ] **Step 3: Add the bridge types**

Append to `internal/bridge/api.go`:

```go
// --- Derive (topic-scoped knowledge base) ---

// DeriveRequest mirrors the derive command. Non-streaming: progress granularity
// per derive stage is carried by the job row's stage column, not by a stream.
type DeriveRequest struct {
	KBDir string `json:"kb_dir"`
	Topic string `json:"topic"`
	Slug  string `json:"slug,omitempty"`
	Force bool   `json:"force,omitempty"`
	Model string `json:"model,omitempty"`
}

// DeriveResponse mirrors the derive command's success payload. Stored verbatim
// as a derive job's result, so the UI can report counts and cost.
type DeriveResponse struct {
	DerivedKB     string          `json:"derived_kb"`
	Slug          string          `json:"slug"`
	Topic         string          `json:"topic"`
	Selected      int             `json:"selected"`
	Documents     int             `json:"documents"`
	Bytes         int64           `json:"bytes"`
	Offtopic      int             `json:"offtopic"`
	FilterBatches int             `json:"filter_batches"`
	Compiled      bool            `json:"compiled"`
	Compile       json.RawMessage `json:"compile,omitempty"`
	Cost          json.RawMessage `json:"cost,omitempty"`
	Warnings      []string        `json:"warnings,omitempty"`
}
```

Append to `internal/bridge/daemon_client.go`, after `Index`:

```go
// Derive builds a topic-scoped knowledge base via the daemon.
//
// One call covering filter → copy → compile → prune, so it can run long: the
// caller sets the context deadline. There is no volume gate on this path — it is
// async and there is nobody to prompt (spec H5).
func (c *DaemonClient) Derive(ctx context.Context, req DeriveRequest) (*DeriveResponse, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "derive", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	var out DeriveResponse
	if err := json.Unmarshal(resp.Data, &out); err != nil {
		return nil, fmt.Errorf("daemon derive: decode response: %w", err)
	}
	return &out, nil
}
```

- [ ] **Step 4: Add the daemon handler**

In `py/src/kb_ai/server_daemon.py`, add after `_handle_index` (line 228):

```python
def _handle_derive(request_id: str, payload: dict) -> None:
    """Handle the derive command -- build a topic-scoped knowledge base.

    No volume gate: this path is asynchronous, so there is nobody to prompt (spec
    H5). The HTTP layer's job row is the operator-facing control.
    """
    from kb_ai._errors import KBError
    from kb_ai.derive import derive_kb

    inner = payload.get("payload", {})
    kb_dir = inner.get("kb_dir", "")
    topic = inner.get("topic", "")
    if not topic.strip():
        _respond_error(request_id, "EMPTY_TOPIC", "topic must not be empty")
        return

    try:
        report = derive_kb(
            kb_dir, topic,
            slug=inner.get("slug") or None,
            force=bool(inner.get("force")),
            model=inner.get("model") or "claude-sonnet-4-6",
            approve=None,
        )
    except KBError as e:
        _respond_error(request_id, e.code, str(e))
        return

    _respond_ok(request_id, {
        "derived_kb": report.derived_kb,
        "slug": report.slug,
        "topic": report.topic,
        "selected": len(report.selected_articles),
        "documents": len(report.documents),
        "bytes": sum(d.size_bytes for d in report.documents),
        "offtopic": len(report.offtopic_articles),
        "filter_batches": report.filter_batches,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
    })
```

and add the dispatch arm in `_dispatch`, after the `index` arm (line 359):

```python
        elif cmd == "derive":
            _handle_derive(request_id, payload)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `go test ./internal/bridge/... -count=1 && cd py && uv run pytest tests/test_server_daemon.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internal/bridge py/src/kb_ai/server_daemon.py py/tests/test_server_daemon.py
git commit -m "feat(bridge): add the derive command to the daemon protocol"
```

---

## Task 15: The derive job runner

Spec: H1, H1b, H5. Tech design: Stage 3 Option A.

**Files:**
- Create: `internal/derive/runner.go`
- Create: `internal/derive/runner_test.go`
- Modify: `cmd/kaas/main.go:261-275` (run the runner alongside the dispatcher)

**Interfaces:**
- Consumes: `store.DerivedJobStore` (Task 13), `bridge.DeriveRequest/Response`
  (Task 14).
- Produces: `derive.NewRunner(js store.DerivedJobStore, br Bridge, cfg Config, logger *slog.Logger) *Runner`
  with `(*Runner).Run(ctx context.Context) error`, and the `derive.Bridge`
  interface (`Derive(ctx, bridge.DeriveRequest) (*bridge.DeriveResponse, error)`).

- [ ] **Step 1: Write the failing tests**

Create `internal/derive/runner_test.go`:

```go
package derive

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// fakeJobStore is a minimal in-memory store.DerivedJobStore.
type fakeJobStore struct {
	mu      sync.Mutex
	pending []*store.DerivedJob
	jobs    map[string]*store.DerivedJob
	stages  []string
}

func newFakeJobStore(jobs ...*store.DerivedJob) *fakeJobStore {
	f := &fakeJobStore{jobs: map[string]*store.DerivedJob{}}
	for _, j := range jobs {
		f.pending = append(f.pending, j)
		f.jobs[j.ID] = j
	}
	return f
}

func (f *fakeJobStore) CreateDerivedJob(context.Context, *store.DerivedJob) error { return nil }

func (f *fakeJobStore) GetDerivedJob(_ context.Context, id string) (*store.DerivedJob, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	j, ok := f.jobs[id]
	if !ok {
		return nil, store.ErrNotFound
	}
	return j, nil
}

func (f *fakeJobStore) ListDerivedJobs(context.Context, int) ([]*store.DerivedJob, error) {
	return nil, nil
}

func (f *fakeJobStore) ClaimNextDerivedJob(_ context.Context, _ int64) (*store.DerivedJob, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.pending) == 0 {
		return nil, nil
	}
	j := f.pending[0]
	f.pending = f.pending[1:]
	j.Status = store.DerivedStatusRunning
	return j, nil
}

func (f *fakeJobStore) SetDerivedJobStage(_ context.Context, id, stage string, _ int64) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stages = append(f.stages, stage)
	f.jobs[id].Stage = stage
	return nil
}

func (f *fakeJobStore) FinishDerivedJob(_ context.Context, id, status, errMsg, result string, _ int64) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	j := f.jobs[id]
	j.Status, j.Error, j.Result, j.Stage = status, errMsg, result, store.DerivedStageDone
	return nil
}

func (f *fakeJobStore) RecoverRunningDerivedJobs(context.Context, int64) (int, error) {
	return 0, nil
}

func (f *fakeJobStore) job(id string) store.DerivedJob {
	f.mu.Lock()
	defer f.mu.Unlock()
	return *f.jobs[id]
}

type fakeBridge struct {
	req  bridge.DeriveRequest
	resp *bridge.DeriveResponse
	err  error
}

func (f *fakeBridge) Derive(_ context.Context, req bridge.DeriveRequest) (*bridge.DeriveResponse, error) {
	f.req = req
	return f.resp, f.err
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func runOnce(t *testing.T, js *fakeJobStore, br *fakeBridge) *Runner {
	t.Helper()
	r := NewRunner(js, br, Config{KBDir: "/kb", Model: "default-model",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	_ = r.Run(ctx)
	return r
}

func TestRunnerRunsAPendingJobToSuccess(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "pricing and fees", Model: "",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{
		Slug: "pricing", Documents: 3, Compiled: true,
		Cost: json.RawMessage(`{"total_cost_usd":1.5}`),
	}}
	runOnce(t, js, br)

	if br.req.KBDir != "/kb" || br.req.Topic != "pricing and fees" || br.req.Slug != "pricing" {
		t.Errorf("request = %+v", br.req)
	}
	if br.req.Model != "default-model" {
		t.Errorf("model = %q, want the server default when the job omits one", br.req.Model)
	}
	got := js.job("j1")
	if got.Status != store.DerivedStatusSucceeded {
		t.Errorf("status = %q, want succeeded (error: %q)", got.Status, got.Error)
	}
	var result bridge.DeriveResponse
	if err := json.Unmarshal([]byte(got.Result), &result); err != nil {
		t.Fatalf("result is not the derive response: %v (%q)", err, got.Result)
	}
	if result.Documents != 3 || !result.Compiled {
		t.Errorf("result = %+v", result)
	}
}

func TestRunnerUsesTheJobsModelOverride(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t", Model: "job-model",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{Slug: "pricing", Compiled: true}}
	runOnce(t, js, br)

	if br.req.Model != "job-model" {
		t.Errorf("model = %q, want job-model", br.req.Model)
	}
}

func TestRunnerRecordsAFailure(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{err: &bridge.APIError{Code: "NO_DOCUMENTS", Message: "nothing to derive"}}
	runOnce(t, js, br)

	got := js.job("j1")
	if got.Status != store.DerivedStatusFailed {
		t.Errorf("status = %q, want failed", got.Status)
	}
	if got.Error == "" || got.Result != "" {
		t.Errorf("error = %q, result = %q", got.Error, got.Result)
	}
}

func TestRunnerMarksStagesAsItGoes(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{Slug: "pricing", Compiled: true}}
	runOnce(t, js, br)

	js.mu.Lock()
	stages := append([]string(nil), js.stages...)
	js.mu.Unlock()
	if len(stages) == 0 || stages[0] != store.DerivedStageCompile {
		t.Errorf("stages = %v, want the compile stage recorded", stages)
	}
}

func TestRunnerRecoversRunningJobsOnStart(t *testing.T) {
	js := &recordingRecoverStore{fakeJobStore: newFakeJobStore()}
	br := &fakeBridge{}
	r := NewRunner(js, br, Config{KBDir: "/kb", PollInterval: time.Millisecond,
		Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	_ = r.Run(ctx)

	if !js.recovered {
		t.Error("Run did not recover jobs left running by a previous process")
	}
}

type recordingRecoverStore struct {
	*fakeJobStore
	recovered bool
}

func (r *recordingRecoverStore) RecoverRunningDerivedJobs(context.Context, int64) (int, error) {
	r.recovered = true
	return 1, nil
}

func TestRunnerStopsOnContextCancel(t *testing.T) {
	js := newFakeJobStore()
	r := NewRunner(js, &fakeBridge{}, Config{KBDir: "/kb",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := r.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		t.Errorf("Run = %v, want nil or context.Canceled", err)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/derive/... -count=1`
Expected: FAIL — `undefined: NewRunner`

- [ ] **Step 3: Write `internal/derive/runner.go`**

```go
// Package derive runs knowledge-base-level derive jobs.
//
// Deliberately separate from internal/worker: that package's Task is
// document-shaped and its Process runs one document through extract → pipeline.
// Keeping derive out of it means a derive can neither starve document ingestion
// nor break it, and the derived_jobs unique index gives "one derive per slug"
// without touching the compile queue's hot path.
package derive

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// Bridge is the subset of *bridge.DaemonClient the runner needs.
type Bridge interface {
	Derive(ctx context.Context, req bridge.DeriveRequest) (*bridge.DeriveResponse, error)
}

// Config holds the runner's settings.
type Config struct {
	KBDir        string        // knowledge-base root every derive is relative to
	Model        string        // default model when a job names none
	PollInterval time.Duration // how often to look for a pending job
	Timeout      time.Duration // ceiling for one derive call
}

// Runner claims pending derive jobs one at a time and drives them through the
// bridge. Single-flight: the store's claim refuses to hand out a job while one
// is running, so a slow derive queues rather than overlapping.
type Runner struct {
	js     store.DerivedJobStore
	br     Bridge
	cfg    Config
	logger *slog.Logger
}

// NewRunner builds a Runner. A nil logger falls back to slog.Default().
func NewRunner(js store.DerivedJobStore, br Bridge, cfg Config, logger *slog.Logger) *Runner {
	if logger == nil {
		logger = slog.Default()
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = 2 * time.Second
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 2 * time.Hour
	}
	return &Runner{js: js, br: br, cfg: cfg, logger: logger}
}

// Run polls for pending jobs until ctx is cancelled. Returns nil on cancellation.
//
// It first fails any job a previous process left running: a derive is not
// resumable, so leaving one "running" forever would block its slug behind the
// unique index with no way to clear it from the UI.
func (r *Runner) Run(ctx context.Context) error {
	if n, err := r.js.RecoverRunningDerivedJobs(ctx, now()); err != nil {
		r.logger.Error("derive: recover interrupted jobs", "err", err)
	} else if n > 0 {
		r.logger.Warn("derive: failed jobs interrupted by a restart", "count", n)
	}

	ticker := time.NewTicker(r.cfg.PollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			job, err := r.js.ClaimNextDerivedJob(ctx, now())
			if err != nil {
				r.logger.Error("derive: claim job", "err", err)
				continue
			}
			if job == nil {
				continue
			}
			r.process(ctx, job)
		}
	}
}

// process runs one job to a terminal status. Every exit path writes a terminal
// row: a job left running blocks its slug behind the unique index.
func (r *Runner) process(ctx context.Context, job *store.DerivedJob) {
	r.logger.Info("derive: starting", "id", job.ID, "slug", job.Slug, "topic", job.Topic)

	// The bridge call covers filter → copy → compile → prune in one round trip,
	// so this is the only stage the runner can honestly report mid-flight.
	if err := r.js.SetDerivedJobStage(ctx, job.ID, store.DerivedStageCompile, now()); err != nil {
		r.logger.Warn("derive: set stage", "id", job.ID, "err", err)
	}

	model := job.Model
	if model == "" {
		model = r.cfg.Model
	}

	callCtx, cancel := context.WithTimeout(ctx, r.cfg.Timeout)
	defer cancel()

	resp, err := r.br.Derive(callCtx, bridge.DeriveRequest{
		KBDir: r.cfg.KBDir,
		Topic: job.Topic,
		Slug:  job.Slug,
		// The API layer already refused a slug whose directory exists, so a
		// force here would only mask a race with a CLI run.
		Model: model,
	})
	if err != nil {
		r.logger.Error("derive: failed", "id", job.ID, "slug", job.Slug, "err", err)
		r.finish(job.ID, store.DerivedStatusFailed, err.Error(), "")
		return
	}

	result, mErr := json.Marshal(resp)
	if mErr != nil {
		// The derive itself succeeded; losing the result JSON must not report it
		// as a failure, or the operator re-runs work already paid for.
		r.logger.Error("derive: encode result", "id", job.ID, "err", mErr)
		result = []byte("{}")
	}
	r.logger.Info("derive: done", "id", job.ID, "slug", job.Slug,
		"documents", resp.Documents, "offtopic", resp.Offtopic)
	r.finish(job.ID, store.DerivedStatusSucceeded, "", string(result))
}

// finish writes a terminal row on a fresh context: the run may have ended
// because ctx was cancelled, and the row still has to be recorded.
func (r *Runner) finish(id, status, errMsg, result string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := r.js.FinishDerivedJob(ctx, id, status, errMsg, result, now()); err != nil {
		r.logger.Error("derive: finish job", "id", id, "status", status, "err", err)
	}
}

func now() int64 { return time.Now().UnixMilli() }
```

- [ ] **Step 4: Wire it into `cmd/kaas/main.go`**

Add the import `"github.com/bybit-exchange/kaas/internal/derive"`, build the
runner after the dispatcher (`d := worker.NewDispatcher(...)`):

```go
	// Derive jobs are KB-level, so they run beside the per-document dispatcher
	// rather than inside it (see internal/derive's package comment).
	var deriveRunner *derive.Runner
	if js, ok := st.(store.DerivedJobStore); ok {
		deriveRunner = derive.NewRunner(js, chatBr.(*bridge.DaemonClient), derive.Config{
			KBDir:        cfg.Storage.KBDir,
			Model:        cfg.LLM.Model,
			PollInterval: time.Duration(cfg.Worker.PollIntervalMS) * time.Millisecond,
		}, logger)
	}
```

and add it to the run map:

```go
	runnables := map[string]func(context.Context) error{
		"server":     srv.Run,
		"dispatcher": d.Run,
	}
	if deriveRunner != nil {
		runnables["derive-runner"] = deriveRunner.Run
	}
	errc := make(chan error, len(runnables))
	for name, fn := range runnables {
```

Adjust the existing `errc := make(chan error, 2)` and the `for name, fn := range
map[...]` header to use `runnables` as shown. Note `logger` is declared *after*
the dispatcher today — move the `deriveRunner` construction below
`logger := newLogger(cfg.Log)`, or move that line up; do not use `slog.Default()`
here. If `chatBr` is not a `*bridge.DaemonClient` in some configuration, guard
the type assertion with `if dc, ok := chatBr.(*bridge.DaemonClient); ok` and skip
the runner otherwise (logging a warning that HTTP derive is unavailable).

- [ ] **Step 5: Run tests and build**

Run: `go build ./... && go test ./internal/derive/... ./cmd/... -count=1`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internal/derive cmd/kaas/main.go
git commit -m "feat(derive): add the single-flight derive job runner"
```

---

## Task 16: Derive HTTP endpoints

Spec: H1, H1b, H2, H5.

**Files:**
- Create: `internal/api/derive.go`
- Create: `internal/api/derive_test.go`
- Modify: `internal/api/server.go:41-149` (dependency + routes)

**Interfaces:**
- Consumes: `store.DerivedJobStore` (Task 13), `kbpath` (Task 12).
- Produces: `POST /api/derive` → 202 `{job_id, slug}`;
  `GET /api/derive/{id}` → `{id, slug, topic, status, stage, error, result, created_at, updated_at}`;
  `GET /api/derived` → `{kbs: [{slug, topic, created_at, article_count}]}`.
- The `Server` gains a `js store.DerivedJobStore` field, nil when the backing
  store does not implement it (the routes then answer 501).

- [ ] **Step 1: Write the failing tests**

Create `internal/api/derive_test.go`. Read `internal/api/api_test.go` first and
reuse its `newTestServer`-style helper; the sketch below names what each test must
assert:

```go
package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPostDeriveEnqueuesAJob(t *testing.T) {
	// POST {"topic":"pricing"} -> 202, body has job_id and slug "pricing";
	// the job landed in the fake DerivedJobStore with status pending.
}

func TestPostDeriveUsesAnExplicitSlug(t *testing.T) {
	// POST {"topic":"pricing and fees","slug":"pf"} -> slug "pf".
}

func TestPostDeriveDerivesTheSlugFromTheTopic(t *testing.T) {
	// POST {"topic":"Pricing & Fees!"} -> slug "pricing-fees" (same rule as
	// py normalise_slug: lower-cased, non-alphanumeric runs collapsed, trimmed,
	// 40 chars).
}

func TestPostDeriveRejectsAnEmptyTopic(t *testing.T) {
	// POST {"topic":"  "} -> 400.
}

func TestPostDeriveRejectsAnInvalidSlug(t *testing.T) {
	// POST {"topic":"t","slug":"../etc"} -> 400.
}

func TestPostDeriveRejectsATopicThatNormalisesToNothing(t *testing.T) {
	// POST {"topic":"定价"} -> 400 naming the slug problem, since the derived
	// slug would be empty.
}

func TestPostDeriveRejectsAnExistingDerivedKB(t *testing.T) {
	// derived/pricing/manifest.json exists on disk -> POST {"topic":"pricing"}
	// answers 409, and no job is created. The HTTP path has no --force.
}

func TestPostDeriveRejectsADuplicateActiveSlug(t *testing.T) {
	// the fake store returns store.ErrDerivedJobExists -> 409.
}

func TestGetDeriveJob(t *testing.T) {
	// GET /api/derive/{id} -> 200 with status, stage, error and result decoded
	// from the stored JSON (result is an object, not a string).
}

func TestGetDeriveJobNotFound(t *testing.T) {
	// unknown id -> 404.
}

func TestListDerivedReadsManifests(t *testing.T) {
	// two derived KBs on disk with manifests; GET /api/derived -> both, sorted by
	// slug, each with topic, created_at and article_count taken from the KB's
	// index/master-index.md line count.
}

func TestListDerivedWithNoDerivedDir(t *testing.T) {
	// GET /api/derived -> 200 {"kbs":[]}, never 500.
}

func TestDeriveRoutesWithoutAJobStore(t *testing.T) {
	// a Server built with a nil DerivedJobStore answers 501 on POST /api/derive
	// and GET /api/derive/{id}, while GET /api/derived still works (it only reads
	// the filesystem).
}
```

Write each body out in full following `api_test.go`'s conventions before moving
on — a sketched test is not a test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/api/... -run Derive -count=1`
Expected: FAIL (routes 404, `undefined` symbols)

- [ ] **Step 3: Write `internal/api/derive.go`**

```go
package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/bybit-exchange/kaas/internal/kbpath"
	"github.com/bybit-exchange/kaas/internal/store"
)

// deriveRequest is the POST /api/derive body. KBDir is server-side config, so a
// client cannot point a derive at another directory.
type deriveRequest struct {
	Topic string `json:"topic"`
	Slug  string `json:"slug,omitempty"`
	Model string `json:"model,omitempty"`
}

// derivedKBSummary is one entry of GET /api/derived, read from the KB's manifest.
type derivedKBSummary struct {
	Slug         string `json:"slug"`
	Topic        string `json:"topic"`
	CreatedAt    string `json:"created_at"`
	ArticleCount int    `json:"article_count"`
}

// deriveJobResponse is the GET /api/derive/{id} body. Result is the raw JSON the
// engine returned, forwarded as an object rather than a quoted string.
type deriveJobResponse struct {
	ID        string          `json:"id"`
	Slug      string          `json:"slug"`
	Topic     string          `json:"topic"`
	Status    string          `json:"status"`
	Stage     string          `json:"stage"`
	Error     string          `json:"error,omitempty"`
	Result    json.RawMessage `json:"result,omitempty"`
	CreatedAt int64           `json:"created_at"`
	UpdatedAt int64           `json:"updated_at"`
}

// slugFillerRe collapses runs of non-slug characters, mirroring normalise_slug in
// py/src/kb_ai/derive/_layout.py. Both sides must agree, or a slug the UI shows
// differs from the directory the engine creates.
var slugFillerRe = regexp.MustCompile(`[^a-z0-9]+`)

const slugMaxLen = 40

// slugFromTopic derives a slug from a topic string (spec C2).
func slugFromTopic(topic string) string {
	flat := slugFillerRe.ReplaceAllString(strings.ToLower(topic), "-")
	flat = strings.Trim(flat, "-")
	if len(flat) > slugMaxLen {
		flat = flat[:slugMaxLen]
	}
	return strings.Trim(flat, "-")
}

// handleDerive serves POST /api/derive: it records the job and returns
// immediately. The compile happens in the derive runner, so this never blocks --
// and consequently has no volume gate, since there is nobody to prompt (H5).
func (s *Server) handleDerive(w http.ResponseWriter, r *http.Request) {
	if s.js == nil {
		writeErr(w, http.StatusNotImplemented, "derive is not available on this backend")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req deriveRequest
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}
	if strings.TrimSpace(req.Topic) == "" {
		writeErr(w, http.StatusBadRequest, "topic is required")
		return
	}

	slug := req.Slug
	if slug == "" {
		slug = slugFromTopic(req.Topic)
	}
	if !kbpath.ValidSlug(slug) {
		writeErr(w, http.StatusBadRequest,
			"invalid slug: expected 1-40 lower-case alphanumeric characters or dashes; "+
				"pass an explicit slug for a topic that does not produce one")
		return
	}

	// Refuse a slug whose directory already exists. The HTTP path has no --force:
	// replacing a compiled KB from a web form, with no prompt, is not something
	// to make easy.
	if _, err := kbpath.Resolve(s.cfg.KBDir, slug); err == nil {
		writeErr(w, http.StatusConflict,
			"a derived knowledge base named "+slug+" already exists")
		return
	} else if !errors.Is(err, kbpath.ErrUnknownKB) {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}

	now := time.Now().UnixMilli()
	job := &store.DerivedJob{
		ID:        uuid.NewString(),
		Slug:      slug,
		Topic:     req.Topic,
		Model:     req.Model,
		Status:    store.DerivedStatusPending,
		Stage:     store.DerivedStageQueued,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := s.js.CreateDerivedJob(r.Context(), job); err != nil {
		if errors.Is(err, store.ErrDerivedJobExists) {
			writeErr(w, http.StatusConflict,
				"a derive for "+slug+" is already queued or running")
			return
		}
		writeErr(w, http.StatusInternalServerError, "create derive job: "+err.Error())
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]string{"job_id": job.ID, "slug": slug})
}

// handleGetDeriveJob serves GET /api/derive/{id}.
func (s *Server) handleGetDeriveJob(w http.ResponseWriter, r *http.Request) {
	if s.js == nil {
		writeErr(w, http.StatusNotImplemented, "derive is not available on this backend")
		return
	}
	job, err := s.js.GetDerivedJob(r.Context(), r.PathValue("id"))
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "derive job not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get derive job: "+err.Error())
		return
	}
	resp := deriveJobResponse{
		ID: job.ID, Slug: job.Slug, Topic: job.Topic, Status: job.Status,
		Stage: job.Stage, Error: job.Error,
		CreatedAt: job.CreatedAt, UpdatedAt: job.UpdatedAt,
	}
	// The stored blob is the engine's own JSON; forward it as an object. A blob
	// that is not valid JSON is dropped rather than breaking the response.
	if json.Valid([]byte(job.Result)) && job.Result != "" {
		resp.Result = json.RawMessage(job.Result)
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleListDerived serves GET /api/derived, reading each derived KB's manifest.
// Filesystem-only, so it works even without a job store.
func (s *Server) handleListDerived(w http.ResponseWriter, r *http.Request) {
	slugs, err := kbpath.ListSlugs(s.cfg.KBDir)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list derived: "+err.Error())
		return
	}
	out := make([]derivedKBSummary, 0, len(slugs))
	for _, slug := range slugs {
		dir := filepath.Join(s.cfg.KBDir, kbpath.DerivedDirName, slug)
		var manifest struct {
			Slug      string `json:"slug"`
			Topic     string `json:"topic"`
			CreatedAt string `json:"created_at"`
		}
		raw, readErr := os.ReadFile(filepath.Join(dir, "manifest.json"))
		if readErr == nil {
			_ = json.Unmarshal(raw, &manifest)
		}
		out = append(out, derivedKBSummary{
			Slug:         slug,
			Topic:        manifest.Topic,
			CreatedAt:    manifest.CreatedAt,
			ArticleCount: countWikiArticles(dir),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"kbs": out})
}

// countWikiArticles counts *.md files under dir/wiki. _offtopic/ lives outside
// wiki/, so it is excluded by construction (D4).
func countWikiArticles(kbDir string) int {
	count := 0
	_ = filepath.WalkDir(filepath.Join(kbDir, "wiki"), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil // an unreadable subtree costs its count, not the response
		}
		if d.Type().IsRegular() && strings.HasSuffix(strings.ToLower(d.Name()), ".md") {
			count++
		}
		return nil
	})
	return count
}

var _ = context.Background // keep the import list stable if context drops out
```

Remove the trailing `var _ = context.Background` line if `context` is not
otherwise used — it is a placeholder to make the import list explicit, not
something to ship.

- [ ] **Step 4: Wire the routes and the dependency**

In `internal/api/server.go`:

- Add the field to `Server`: `js store.DerivedJobStore // derive jobs; nil when the backing store has none`
- Change `NewServer`'s body to accept it. Rather than widen the signature (five
  call sites in tests), type-assert the existing store:

```go
	s := &Server{q: q, st: st, ss: ss, br: br, cfg: cfg, logger: logger}
	// The sqlite store implements DerivedJobStore too; a backend that does not
	// simply leaves the derive routes answering 501.
	if js, ok := st.(store.DerivedJobStore); ok {
		s.js = js
	}
```

- Add the routes next to the wiki routes:

```go
	mux.HandleFunc("POST /api/derive", s.handleDerive)
	mux.HandleFunc("GET /api/derive/{id}", s.handleGetDeriveJob)
	mux.HandleFunc("GET /api/derived", s.handleListDerived)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `go test ./internal/api/... -count=1`
Expected: PASS, including the pre-existing API tests

- [ ] **Step 6: Commit**

```bash
git add internal/api/derive.go internal/api/derive_test.go internal/api/server.go
git commit -m "feat(api): add derive job endpoints and the derived-KB listing"
```

---

## Task 17: `?kb=` on the wiki and chat read paths

Spec: H3, and the cache note in the tech design ("Endpoints").

**Files:**
- Modify: `internal/api/wiki.go:18-30` (cache type), `:161-252`
  (`handleListWiki`), `:254-315` (`handleWikiFile`)
- Modify: `internal/api/chat.go:85-90`
- Modify: `internal/api/server.go:87` (the `wikiC` field type)
- Test: `internal/api/wiki_test.go`, `wiki_tree_test.go`, `wiki_file_test.go` (append)

**Interfaces:**
- Consumes: `kbpath.Resolve` (Task 12).
- Produces: a `(*Server).resolveKB(r *http.Request) (string, bool)` helper that
  writes the 400 itself, and a per-slug wiki tree cache.

- [ ] **Step 1: Write the failing tests**

Append to `internal/api/wiki_test.go`:

```go
func TestListWikiScopedToADerivedKB(t *testing.T) {
	// A root KB with wiki/root.md and derived/pricing/wiki/derived.md.
	// GET /api/wiki       -> tree contains root.md only
	// GET /api/wiki?kb=pricing -> tree contains derived.md only
}

func TestListWikiCacheIsKeyedBySlug(t *testing.T) {
	// Request ?kb= then ?kb=pricing then ?kb= again within the TTL; each response
	// must match its own KB. A single-entry cache would serve the derived tree
	// for the root request.
}

func TestListWikiRejectsAnUnknownKB(t *testing.T) {
	// GET /api/wiki?kb=nope -> 400
}

func TestWikiFileScopedToADerivedKB(t *testing.T) {
	// GET /api/wiki/file?kb=pricing&path=derived.md -> the derived article;
	// the same path without ?kb= -> 404
}

func TestWikiFileRejectsAnInvalidKBSlug(t *testing.T) {
	// GET /api/wiki/file?kb=../..&path=a.md -> 400
}

func TestChatForwardsTheKBDir(t *testing.T) {
	// POST /api/chat?kb=pricing with a fake ChatBridge -> the captured
	// bridge.ChatRequest.KBDir is <kbdir>/derived/pricing
}

func TestChatRejectsAnUnknownKB(t *testing.T) {
	// POST /api/chat?kb=nope -> 400 before any SSE header is written
}
```

Fill each body in following the existing wiki tests' helpers.

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/api/... -run 'KB|kb' -count=1`
Expected: FAIL — the `?kb=` parameter is ignored, so scoped requests return the
root tree

- [ ] **Step 3: Replace the single-entry wiki cache with a per-slug one**

In `internal/api/wiki.go`, replace the `wikiCache` type:

```go
// wikiCacheEntry holds one KB's cached wiki tree with dual invalidation:
// directory modtime change triggers an immediate rebuild; TTL expiry guarantees
// eventual consistency even when modtime does not reflect nested changes.
type wikiCacheEntry struct {
	tree    []wikiTreeNode
	builtAt time.Time
	dirMod  time.Time
}

// wikiCache holds one entry per knowledge base, keyed by derived-KB slug ("" for
// the root). A single shared entry would thrash the moment a user switches KBs in
// the selector, and could serve one KB's tree for another's request.
type wikiCache struct {
	mu      sync.RWMutex
	entries map[string]*wikiCacheEntry
}

func (c *wikiCache) get(slug string, dirMod time.Time) ([]wikiTreeNode, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.entries[slug]
	if !ok || e.tree == nil {
		return nil, false
	}
	if !e.dirMod.Equal(dirMod) || time.Since(e.builtAt) >= wikiCacheTTL {
		return nil, false
	}
	return e.tree, true
}

func (c *wikiCache) put(slug string, tree []wikiTreeNode, dirMod time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil {
		c.entries = map[string]*wikiCacheEntry{}
	}
	c.entries[slug] = &wikiCacheEntry{tree: tree, builtAt: time.Now(), dirMod: dirMod}
}
```

- [ ] **Step 4: Add the resolver and use it in the three handlers**

Add to `internal/api/wiki.go`:

```go
// resolveKB maps the request's optional ?kb=<slug> to a knowledge-base root.
//
// The slug reaches us from a browser query string, so it is untrusted input to a
// path join: kbpath validates it lexically and requires the target to hold a
// manifest. An unknown slug answers 400 rather than falling back to the root KB
// (spec H3) -- silently answering from the wrong corpus is the failure worth
// avoiding. Returns (dir, true) on success, or writes the error and returns
// ("", false).
func (s *Server) resolveKB(w http.ResponseWriter, r *http.Request) (string, bool) {
	slug := r.URL.Query().Get("kb")
	dir, err := kbpath.Resolve(s.cfg.KBDir, slug)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return "", false
	}
	return dir, true
}
```

In `handleListWiki`, replace the opening and the cache interactions:

```go
func (s *Server) handleListWiki(w http.ResponseWriter, r *http.Request) {
	kbDir, ok := s.resolveKB(w, r)
	if !ok {
		return
	}
	slug := r.URL.Query().Get("kb")
	wikiDir := filepath.Join(kbDir, "wiki")

	dirInfo, statErr := os.Stat(wikiDir)
	if statErr == nil {
		if tree, hit := s.wikiC.get(slug, dirInfo.ModTime()); hit {
			writeJSON(w, http.StatusOK, map[string]any{"tree": tree})
			return
		}
	}
	// ... unchanged walk ...
```

and the cache update near the end:

```go
	if di, e := os.Stat(wikiDir); e == nil {
		s.wikiC.put(slug, tree, di.ModTime())
	}
```

In `handleWikiFile`, replace the `wikiDir` line:

```go
	kbDir, ok := s.resolveKB(w, r)
	if !ok {
		return
	}
	wikiDir := filepath.Join(kbDir, "wiki")
```

placing the `resolveKB` call after the existing `path` validation so a malformed
`path` still answers 400 for the same reason it does today.

In `internal/api/chat.go`, resolve before committing to the SSE response (i.e.
above the `flusher, ok := w.(http.Flusher)` block, so a bad slug can still answer
HTTP 400) and use it in the bridge request:

```go
	kbDir, ok := s.resolveKB(w, r)
	if !ok {
		return
	}
```

then change the `bridge.ChatRequest` literal's `KBDir: s.cfg.KBDir` to
`KBDir: kbDir`. Rename the later `flusher, ok := ...` to avoid shadowing
confusion — Go allows the reuse, but two `ok`s in one function reads badly.

Add `"github.com/bybit-exchange/kaas/internal/kbpath"` to `wiki.go`'s imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `go test ./internal/api/... -count=1`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internal/api
git commit -m "feat(api): scope the wiki and chat read paths to a derived KB"
```

---

## Task 18: Web API client, KB store, and threading the slug

Spec: H2, H3.

**Files:**
- Create: `web/src/api/derived.ts`, `web/src/api/derived.test.ts`
- Create: `web/src/store/kb.ts`, `web/src/store/kb.test.ts`
- Modify: `web/src/api/wiki.ts`, `web/src/api/wiki.test.ts`
- Modify: `web/src/api/chat.ts`, `web/src/api/chat.test.ts`

**Interfaces:**
- Produces:
  - `listDerived(): Promise<{ kbs: DerivedKB[] }>` where
    `DerivedKB = { slug: string; topic: string; created_at: string; article_count: number }`
  - `startDerive(req: { topic: string; slug?: string; model?: string }): Promise<{ job_id: string; slug: string }>`
  - `getDeriveJob(id: string): Promise<DeriveJob>` where
    `DeriveJob = { id, slug, topic, status, stage, error?, result?, created_at, updated_at }`
    and `result?: DeriveResult` with
    `DeriveResult = { selected: number; documents: number; bytes: number; offtopic: number; compiled: boolean; cost?: { total_cost_usd: number } }`
  - `useKB()` Zustand store: `{ kb: string | null; setKB: (slug: string | null) => void }`
  - `listWiki(kb?: string | null)`, `fetchWikiArticle(path: string, kb?: string | null)`
  - `StreamChatRequest` unchanged; `streamChat(req, signal, kb?)` appends `?kb=`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/api/derived.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { getDeriveJob, listDerived, startDerive } from './derived'

describe('derived api', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mockOk(body: unknown): void {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(body), { status: 200 }),
    )
  }

  it('lists derived knowledge bases', async () => {
    mockOk({ kbs: [{ slug: 'pricing', topic: 'pricing', created_at: '2026-08-04', article_count: 7 }] })
    const { kbs } = await listDerived()
    expect(kbs[0]).toEqual({ slug: 'pricing', topic: 'pricing', created_at: '2026-08-04', article_count: 7 })
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/derived')
  })

  it('starts a derive', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ job_id: 'j1', slug: 'pricing' }), { status: 202 }),
    )
    const res = await startDerive({ topic: 'pricing' })
    expect(res).toEqual({ job_id: 'j1', slug: 'pricing' })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/derive')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ topic: 'pricing' })
  })

  it('fetches a job', async () => {
    mockOk({ id: 'j1', slug: 'pricing', topic: 'pricing', status: 'running', stage: 'compile', created_at: 1, updated_at: 2 })
    const job = await getDeriveJob('j1')
    expect(job.status).toBe('running')
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/derive/j1')
  })

  it('encodes the job id', async () => {
    mockOk({ id: 'a/b', slug: 's', topic: 't', status: 'failed', stage: 'done', created_at: 1, updated_at: 1 })
    await getDeriveJob('a/b')
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/derive/a%2Fb')
  })
})
```

Create `web/src/store/kb.test.ts`:

```ts
import { describe, expect, it, beforeEach } from 'vitest'
import { useKB } from './kb'

describe('useKB', () => {
  beforeEach(() => {
    useKB.setState({ kb: null })
  })

  it('defaults to the root knowledge base', () => {
    expect(useKB.getState().kb).toBeNull()
  })

  it('selects a derived knowledge base', () => {
    useKB.getState().setKB('pricing')
    expect(useKB.getState().kb).toBe('pricing')
  })

  it('goes back to the root', () => {
    useKB.getState().setKB('pricing')
    useKB.getState().setKB(null)
    expect(useKB.getState().kb).toBeNull()
  })
})
```

Append to `web/src/api/wiki.test.ts`:

```ts
it('scopes the tree request to a derived kb', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tree: [] }), { status: 200 }))
  await listWiki('pricing')
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/wiki?kb=pricing')
})

it('omits kb for the root', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ tree: [] }), { status: 200 }))
  await listWiki(null)
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/wiki')
})

it('scopes the article request to a derived kb', async () => {
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ path: 'a.md', title: 'A', content: '' }), { status: 200 }),
  )
  await fetchWikiArticle('concepts/a.md', 'pricing')
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/wiki/file?path=concepts%2Fa.md&kb=pricing')
})
```

Append to `web/src/api/chat.test.ts`:

```ts
it('scopes the chat stream to a derived kb', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response('', { status: 200 }))
  await streamChat({ query: 'q' }, undefined, 'pricing')
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/chat?kb=pricing')
})
```

Match the mocking style each existing test file already uses rather than the
sketch above if they differ.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && pnpm test -- --run derived kb wiki chat`
Expected: FAIL — `Cannot find module './derived'`, and the wiki/chat calls ignore
the new argument

- [ ] **Step 3: Write `web/src/api/derived.ts`**

```ts
import { apiFetch } from './client'

export interface DerivedKB {
  slug: string
  topic: string
  created_at: string
  article_count: number
}

/** Counts and cost the engine reported for a finished derive. */
export interface DeriveResult {
  selected: number
  documents: number
  bytes: number
  offtopic: number
  filter_batches: number
  compiled: boolean
  cost?: { total_cost_usd: number }
  warnings?: string[]
}

export type DeriveStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface DeriveJob {
  id: string
  slug: string
  topic: string
  status: DeriveStatus
  stage: string
  error?: string
  result?: DeriveResult
  created_at: number
  updated_at: number
}

export interface StartDeriveRequest {
  topic: string
  slug?: string
  model?: string
}

export async function listDerived(): Promise<{ kbs: DerivedKB[] }> {
  const res = await apiFetch('/derived')
  return res.json() as Promise<{ kbs: DerivedKB[] }>
}

export async function startDerive(
  req: StartDeriveRequest,
): Promise<{ job_id: string; slug: string }> {
  const res = await apiFetch('/derive', { method: 'POST', body: JSON.stringify(req) })
  return res.json() as Promise<{ job_id: string; slug: string }>
}

export async function getDeriveJob(id: string): Promise<DeriveJob> {
  const res = await apiFetch(`/derive/${encodeURIComponent(id)}`)
  return res.json() as Promise<DeriveJob>
}
```

- [ ] **Step 4: Write `web/src/store/kb.ts`**

```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface KBState {
  /** Selected derived-KB slug, or null for the root knowledge base. */
  kb: string | null
  setKB: (slug: string | null) => void
}

/**
 * Which knowledge base the wiki tree and chat read from.
 *
 * A store rather than component state because the wiki tree and the chat panel
 * both need the same value and are not in a parent/child relationship. Persisted
 * so a reload does not silently move the user back to the root corpus.
 */
export const useKB = create<KBState>()(
  persist(
    (set) => ({
      kb: null,
      setKB: (slug: string | null) => set({ kb: slug }),
    }),
    { name: 'kaas-kb' },
  ),
)
```

- [ ] **Step 5: Thread the slug through the wiki and chat clients**

Replace the two functions in `web/src/api/wiki.ts`:

```ts
export async function listWiki(kb?: string | null): Promise<{ tree: WikiTreeNode[] }> {
  const res = await apiFetch(kb ? `/wiki?kb=${encodeURIComponent(kb)}` : '/wiki')
  return res.json() as Promise<{ tree: WikiTreeNode[] }>
}

export async function fetchWikiArticle(path: string, kb?: string | null): Promise<WikiArticle> {
  const query = `path=${encodeURIComponent(path)}${kb ? `&kb=${encodeURIComponent(kb)}` : ''}`
  const res = await apiFetch(`/wiki/file?${query}`)
  return res.json() as Promise<WikiArticle>
}
```

and in `web/src/api/chat.ts`:

```ts
export async function streamChat(
  req: StreamChatRequest,
  signal?: AbortSignal,
  kb?: string | null,
): Promise<Response> {
  return apiFetch(kb ? `/chat?kb=${encodeURIComponent(kb)}` : '/chat', {
    method: 'POST',
    body: JSON.stringify(req),
    headers: { Accept: 'text/event-stream' },
    ...(signal ? { signal } : {}),
  })
}
```

- [ ] **Step 6: Run tests and the type gate**

Run: `cd web && pnpm test -- --run && pnpm exec tsc --noEmit`
Expected: PASS. Existing `streamChat` callers still compile — the new parameter is
optional and last.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/derived.ts web/src/api/derived.test.ts web/src/store/kb.ts web/src/store/kb.test.ts web/src/api/wiki.ts web/src/api/wiki.test.ts web/src/api/chat.ts web/src/api/chat.test.ts
git commit -m "feat(web): add the derived-KB API client and selected-KB store"
```

---

## Task 19: KB selector in the wiki view

Spec: H4, H6.

**Files:**
- Create: `web/src/features/wiki/KBSelector.tsx`, `KBSelector.test.tsx`
- Modify: `web/src/pages/Wiki.tsx:16-63,71-75`
- Modify: `web/src/pages/Wiki.test.tsx` (append)
- Modify: `web/src/i18n/strings.ts` (both maps)

**Interfaces:**
- Consumes: `listDerived` / `DerivedKB` (Task 18), `useKB` (Task 18),
  `@/components/ui/select`.
- Produces: `<KBSelector />` — self-contained: it loads the list itself and
  writes the selection into `useKB`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/wiki/KBSelector.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KBSelector } from './KBSelector'
import { useKB } from '@/store/kb'
import * as derivedApi from '@/api/derived'

vi.mock('@/api/derived')

describe('KBSelector', () => {
  beforeEach(() => {
    useKB.setState({ kb: null })
    vi.mocked(derivedApi.listDerived).mockResolvedValue({
      kbs: [
        { slug: 'pricing', topic: 'pricing and fees', created_at: '2026-08-04', article_count: 7 },
        { slug: 'compliance', topic: 'compliance', created_at: '2026-08-04', article_count: 3 },
      ],
    })
  })

  it('lists the root knowledge base plus each derived one', async () => {
    render(<KBSelector />)
    await userEvent.click(await screen.findByRole('combobox'))
    expect(await screen.findByText('All articles')).toBeInTheDocument()
    expect(screen.getByText('pricing and fees')).toBeInTheDocument()
    expect(screen.getByText('compliance')).toBeInTheDocument()
  })

  it('writes the selection into the store', async () => {
    render(<KBSelector />)
    await userEvent.click(await screen.findByRole('combobox'))
    await userEvent.click(await screen.findByText('pricing and fees'))
    await waitFor(() => expect(useKB.getState().kb).toBe('pricing'))
  })

  it('shows only the root option when nothing has been derived', async () => {
    vi.mocked(derivedApi.listDerived).mockResolvedValue({ kbs: [] })
    render(<KBSelector />)
    await userEvent.click(await screen.findByRole('combobox'))
    expect(await screen.findByText('All articles')).toBeInTheDocument()
    expect(screen.queryByText('pricing and fees')).not.toBeInTheDocument()
  })

  it('falls back to the root when the list cannot be loaded', async () => {
    vi.mocked(derivedApi.listDerived).mockRejectedValue(new Error('offline'))
    render(<KBSelector />)
    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument())
    expect(useKB.getState().kb).toBeNull()
  })

  it('resets a selection whose knowledge base no longer exists', async () => {
    useKB.setState({ kb: 'gone' })
    render(<KBSelector />)
    await waitFor(() => expect(useKB.getState().kb).toBeNull())
  })
})
```

Append to `web/src/pages/Wiki.test.tsx` (mock `@/api/wiki` as that file already
does):

```tsx
it('refetches the tree when the knowledge base changes', async () => {
  // render <Wiki />, wait for the initial listWiki(null) call, then
  // useKB.getState().setKB('pricing') and assert listWiki was called with
  // 'pricing'.
})

it('scopes the article fetch to the selected knowledge base', async () => {
  // with a path in the route and kb 'pricing', fetchWikiArticle must be called
  // with (path, 'pricing').
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && pnpm test -- --run KBSelector Wiki`
Expected: FAIL — `Cannot find module './KBSelector'`

- [ ] **Step 3: Add the i18n strings**

In `web/src/i18n/strings.ts`, add to the `en` map next to the other `wiki.*` keys:

```ts
    'wiki.kbLabel': 'Knowledge base',
    'wiki.kbRoot': 'All articles',
    'wiki.kbArticleCount': '{{count}} articles',
```

and the matching `zh` entries in the `zh` map:

```ts
    'wiki.kbLabel': '知识库',
    'wiki.kbRoot': '全部文章',
    'wiki.kbArticleCount': '{{count}} 篇文章',
```

`web/src/i18n/i18n.parity.test.ts` already asserts both maps hold the same keys,
so a missing `zh` entry fails the suite (H6).

- [ ] **Step 4: Write `web/src/features/wiki/KBSelector.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useT } from '@/i18n'
import { listDerived, type DerivedKB } from '@/api/derived'
import { useKB } from '@/store/kb'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const ROOT_VALUE = '__root__'

/**
 * Picks which knowledge base the wiki tree and chat read from: the root KB or
 * one of its derived, topic-scoped KBs.
 *
 * Loads its own list so the page does not have to thread it down. A failed load
 * leaves the root selected — the wiki still works without the list.
 */
export function KBSelector() {
  const t = useT()
  const { kb, setKB } = useKB()
  const [kbs, setKBs] = useState<DerivedKB[]>([])

  useEffect(() => {
    let cancelled = false
    listDerived()
      .then(({ kbs }) => {
        if (cancelled) return
        setKBs(kbs)
        // A persisted selection can outlive its knowledge base (deleted on
        // disk). Silently reading the root corpus under a stale label would be
        // worse than dropping the selection.
        if (kb && !kbs.some((k) => k.slug === kb)) setKB(null)
      })
      .catch(() => {
        if (!cancelled) setKBs([])
      })
    return () => {
      cancelled = true
    }
  }, [kb, setKB])

  return (
    <Select
      value={kb ?? ROOT_VALUE}
      onValueChange={(value) => setKB(value === ROOT_VALUE ? null : value)}
    >
      <SelectTrigger className="h-8 w-full text-xs" aria-label={t('wiki.kbLabel')}>
        <SelectValue placeholder={t('wiki.kbRoot')} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ROOT_VALUE}>{t('wiki.kbRoot')}</SelectItem>
        {kbs.map((k) => (
          <SelectItem key={k.slug} value={k.slug}>
            {k.topic || k.slug}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
```

Check `web/src/components/ui/select.tsx` for the exact exported names before
writing the imports; use whatever that file exports.

- [ ] **Step 5: Mount it and scope the fetches in `Wiki.tsx`**

Add the imports:

```tsx
import { KBSelector } from '@/features/wiki/KBSelector'
import { useKB } from '@/store/kb'
```

read the selection in the component:

```tsx
  const kb = useKB((s) => s.kb)
```

thread it into both effects and their dependency arrays:

```tsx
  // Load index list
  useEffect(() => {
    setIndexLoading(true)
    listWiki(kb)
      .then(({ tree }) => setTree(tree))
      .catch(() => setTree([]))
      .finally(() => setIndexLoading(false))
  }, [kb])
```

```tsx
    fetchWikiArticle(path, kb)
      .then(setArticle)
```

with `kb` added to that effect's dependency array (`[path, t, kb]`).

Mount the selector in the sidebar header, replacing the `<h2>`-only row:

```tsx
        <div className="flex h-14 items-center gap-2 px-4">
          <h2 className="shrink-0 text-sm font-semibold">{t('wiki.indexTitle')}</h2>
          <div className="min-w-0 flex-1">
            <KBSelector />
          </div>
        </div>
```

- [ ] **Step 6: Run tests, types and build**

Run: `cd web && pnpm test -- --run && pnpm exec tsc --noEmit`
Expected: PASS, including `i18n.parity.test.ts`

- [ ] **Step 7: Commit**

```bash
git add web/src/features/wiki/KBSelector.tsx web/src/features/wiki/KBSelector.test.tsx web/src/pages/Wiki.tsx web/src/pages/Wiki.test.tsx web/src/i18n/strings.ts
git commit -m "feat(web): add a knowledge-base selector to the wiki view"
```

---

## Task 20: Derive dialog with job progress and cost

Spec: H5, H6, and the chat side of H4.

**Files:**
- Create: `web/src/features/wiki/DeriveDialog.tsx`, `DeriveDialog.test.tsx`
- Modify: `web/src/pages/Wiki.tsx` (mount the trigger)
- Modify: `web/src/i18n/strings.ts` (both maps)
- Modify: `web/src/pages/Chat.tsx` (pass `kb` to `streamChat`) or
  `web/src/features/chat/StreamHandler.ts`, whichever owns the call — grep for
  `streamChat(` and thread the selected slug from `useKB` at that call site
- Modify: the corresponding chat test file

**Interfaces:**
- Consumes: `startDerive`, `getDeriveJob`, `DeriveJob` (Task 18), `useKB`.
- Produces: `<DeriveDialog />` — a button plus dialog that starts a derive and
  polls its job until terminal.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/wiki/DeriveDialog.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DeriveDialog } from './DeriveDialog'
import * as derivedApi from '@/api/derived'
import type { DeriveJob } from '@/api/derived'

vi.mock('@/api/derived')

function job(over: Partial<DeriveJob>): DeriveJob {
  return {
    id: 'j1', slug: 'pricing', topic: 'pricing', status: 'running',
    stage: 'compile', created_at: 1, updated_at: 2, ...over,
  }
}

describe('DeriveDialog', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(derivedApi.startDerive).mockResolvedValue({ job_id: 'j1', slug: 'pricing' })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.resetAllMocks()
  })

  it('starts a derive with the typed topic', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({}))
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(screen.getByLabelText(/topic/i), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    await waitFor(() =>
      expect(derivedApi.startDerive).toHaveBeenCalledWith({ topic: 'pricing' }),
    )
  })

  it('will not start with an empty topic', async () => {
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(derivedApi.startDerive).not.toHaveBeenCalled()
  })

  it('shows the stage while the job runs', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({ stage: 'compile' }))
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(screen.getByLabelText(/topic/i), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(await screen.findByText(/compile/i)).toBeInTheDocument()
  })

  it('reports counts and cost on success', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({
      status: 'succeeded', stage: 'done',
      result: {
        selected: 9, documents: 6, bytes: 4096, offtopic: 2, filter_batches: 1,
        compiled: true, cost: { total_cost_usd: 1.2345 },
      },
    }))
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(screen.getByLabelText(/topic/i), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(await screen.findByText(/1.2345 USD/)).toBeInTheDocument()
    expect(screen.getByText(/6/)).toBeInTheDocument()
  })

  it('shows the error on failure and stops polling', async () => {
    vi.mocked(derivedApi.getDeriveJob).mockResolvedValue(job({
      status: 'failed', stage: 'done', error: 'no documents resolved',
    }))
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(screen.getByLabelText(/topic/i), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(await screen.findByText(/no documents resolved/)).toBeInTheDocument()

    const callsAfterTerminal = vi.mocked(derivedApi.getDeriveJob).mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(vi.mocked(derivedApi.getDeriveJob).mock.calls.length).toBe(callsAfterTerminal)
  })

  it('surfaces a rejected start', async () => {
    vi.mocked(derivedApi.startDerive).mockRejectedValue(new Error('already exists'))
    render(<DeriveDialog />)
    await userEvent.click(screen.getByRole('button', { name: /derive/i }))
    await userEvent.type(screen.getByLabelText(/topic/i), 'pricing')
    await userEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(await screen.findByText(/already exists/)).toBeInTheDocument()
  })
})
```

Append to the chat page/handler test file:

```tsx
it('scopes the chat stream to the selected knowledge base', async () => {
  // set useKB to 'pricing', send a message, and assert streamChat was called
  // with 'pricing' as its kb argument.
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && pnpm test -- --run DeriveDialog`
Expected: FAIL — `Cannot find module './DeriveDialog'`

- [ ] **Step 3: Add the i18n strings**

`en`:

```ts
    'derive.action': 'Derive a topic KB',
    'derive.dialogTitle': 'Derive a topic knowledge base',
    'derive.dialogDesc': 'Compiles a new knowledge base from the documents behind the articles matching a topic. This spends money on LLM calls.',
    'derive.topicLabel': 'Topic',
    'derive.topicPlaceholder': 'pricing and fee structure',
    'derive.start': 'Start',
    'derive.close': 'Close',
    'derive.stage': 'Stage: {{stage}}',
    'derive.queued': 'Queued',
    'derive.doneTitle': 'Derived knowledge base ready',
    'derive.summary': '{{documents}} documents compiled, {{offtopic}} articles moved off-topic',
    'derive.cost': 'Cost: {{cost}} USD',
    'derive.failed': 'Derive failed',
```

`zh`:

```ts
    'derive.action': '按主题派生知识库',
    'derive.dialogTitle': '派生主题知识库',
    'derive.dialogDesc': '从匹配该主题的文章背后的源文档编译出一个新的知识库。此操作会产生 LLM 调用费用。',
    'derive.topicLabel': '主题',
    'derive.topicPlaceholder': '定价与费率结构',
    'derive.start': '开始',
    'derive.close': '关闭',
    'derive.stage': '阶段：{{stage}}',
    'derive.queued': '排队中',
    'derive.doneTitle': '主题知识库已就绪',
    'derive.summary': '已编译 {{documents}} 篇源文档，{{offtopic}} 篇文章移出主题',
    'derive.cost': '费用：{{cost}} USD',
    'derive.failed': '派生失败',
```

Cost is written as a `USD` suffix, never a `$` prefix: a bare `$` pair on one
line is parsed as inline maths by markdown renderers.

- [ ] **Step 4: Write `web/src/features/wiki/DeriveDialog.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { useT } from '@/i18n'
import { getDeriveJob, startDerive, type DeriveJob } from '@/api/derived'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

const POLL_MS = 2000

/**
 * Starts a derive and follows its job to a terminal status.
 *
 * No volume gate here: the HTTP path is asynchronous, so there is nothing to
 * prompt for mid-run (spec H5). The dialog's own copy is where the operator is
 * told this costs money, and the actual cost is reported when the job finishes.
 */
export function DeriveDialog() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [topic, setTopic] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<DeriveJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const terminal = job?.status === 'succeeded' || job?.status === 'failed'

  useEffect(() => {
    if (!jobId || terminal) return
    let cancelled = false

    const poll = async () => {
      try {
        const next = await getDeriveJob(jobId)
        if (cancelled) return
        setJob(next)
        if (next.status !== 'succeeded' && next.status !== 'failed') {
          timer.current = setTimeout(poll, POLL_MS)
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message)
      }
    }
    void poll()

    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [jobId, terminal])

  async function onStart() {
    if (!topic.trim()) return
    setStarting(true)
    setError(null)
    setJob(null)
    try {
      const { job_id } = await startDerive({ topic: topic.trim() })
      setJobId(job_id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <Sparkles className="h-3.5 w-3.5" />
          {t('derive.action')}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('derive.dialogTitle')}</DialogTitle>
          <DialogDescription>{t('derive.dialogDesc')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block text-sm font-medium" htmlFor="derive-topic">
            {t('derive.topicLabel')}
          </label>
          <Input
            id="derive-topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={t('derive.topicPlaceholder')}
            disabled={Boolean(jobId) && !terminal}
          />
          <Button onClick={() => void onStart()} disabled={starting || (Boolean(jobId) && !terminal)}>
            {starting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('derive.start')}
          </Button>

          {error && <p className="text-sm text-destructive">{error}</p>}

          {job && !terminal && (
            <p className="text-sm text-muted-foreground">
              {t('derive.stage', { stage: job.stage })}
            </p>
          )}

          {job?.status === 'failed' && (
            <div className="space-y-1">
              <p className="text-sm font-medium">{t('derive.failed')}</p>
              <p className="text-sm text-destructive">{job.error}</p>
            </div>
          )}

          {job?.status === 'succeeded' && job.result && (
            <div className="space-y-1">
              <p className="text-sm font-medium">{t('derive.doneTitle')}</p>
              <p className="text-sm text-muted-foreground">
                {t('derive.summary', {
                  documents: String(job.result.documents),
                  offtopic: String(job.result.offtopic),
                })}
              </p>
              <p className="text-sm text-muted-foreground">
                {t('derive.cost', {
                  cost: (job.result.cost?.total_cost_usd ?? 0).toFixed(4),
                })}
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

Check how `useT` handles interpolation (`web/src/i18n/index.tsx` — the existing
`chat.thinkingShowAll` key uses `{{count}}`) and match its call signature; if it
takes a second parameter of a different shape, adapt the `t(...)` calls above.

- [ ] **Step 5: Mount it and scope the chat stream**

In `web/src/pages/Wiki.tsx`, add `import { DeriveDialog } from '@/features/wiki/DeriveDialog'`
and render it under the search box:

```tsx
        <div className="px-3 pb-2">
          <DeriveDialog />
        </div>
```

Find the `streamChat(` call site:

```bash
grep -rn 'streamChat(' web/src
```

and thread the selected slug there: read `const kb = useKB((s) => s.kb)` in the
component owning the call and pass it as the third argument. If the call lives in
`StreamHandler.ts` (not a component), add a `kb` field to whatever options object
it already receives and pass it through from the calling component — do not read
the store from a non-React module.

- [ ] **Step 6: Run the full web suite, the type gate, and a build**

Run: `cd web && pnpm test -- --run && pnpm exec tsc --noEmit && pnpm build`
Expected: PASS

- [ ] **Step 7: End-to-end check against a running backend**

```bash
cd /Users/hk00691ml/develop/ai/github/kaas
make build
KAAS_STORAGE_KB_DIR=/tmp/kaas-derive-smoke ./bin/kaas &   # or the project's run target
curl -s -X POST localhost:8080/api/derive \
  -H 'Content-Type: application/json' \
  -d '{"topic":"cost accounting and pricing"}'
# -> {"job_id":"...","slug":"cost-accounting-and-pricing"}
curl -s localhost:8080/api/derive/<job_id>
# poll until status is succeeded, then:
curl -s localhost:8080/api/derived
curl -s 'localhost:8080/api/wiki?kb=cost-accounting-and-pricing' | head -c 400
curl -s 'localhost:8080/api/wiki?kb=nope'     # -> 400
```

Check the real config key for the KB dir in `internal/config/config.go` before
running; the env var name above is a guess and must be corrected to the real one.
Record the outputs in `notes.md` under "Stage 3 verification", including the
derive job's reported cost.

- [ ] **Step 8: Full suite and commit**

```bash
make test
git add web docs/features/derive-topic-kb-from-catalog/notes.md
git commit -m "feat(web): add the derive dialog and scope chat to the selected KB"
```

---

# Self-review

Run through this before handing the plan to an implementer.

## Spec coverage

| Spec | Task |
|---|---|
| A1 uncapped, filtered, deduped | 4 |
| A2 empty catalog, no LLM call | 4 |
| A3 LLM error → `DeriveError` | 2, 4 |
| A4 invented paths dropped and counted | 4 |
| A5 `\| keys:` in the prompt | 1, 4 |
| A6 budget batching, union | 4 |
| A7 batching transparent, count reported | 4 |
| A8 oversized line skipped | 4 |
| B1 deduped union, sorted | 5 |
| B2 three no-sources cases distinguished | 5 |
| B3 escaping entry rejected, not fatal | 5 |
| B4 missing file recorded, not fatal | 5 |
| B5 zero documents → `NO_DOCUMENTS`, no dir | 5, 7 |
| C1 `derived/<slug>/raw/` populated | 3, 7 |
| C2 slug from `--slug` or the topic | 3 |
| C3 `INVALID_SLUG` | 3 |
| C4 `SLUG_EXISTS` / `--force` | 3, 7 |
| C5 `NESTED_DERIVE` | 3, 7 |
| C6 source compile/index unaffected | 9 |
| C7 extract-cache copied | 3, 7 |
| D1 unchanged `compile_kb` | 7 |
| D2 second pass moves, not deletes | 6 |
| D3 reindex after the move | 6 |
| D4 `_offtopic/` outside indexing | 6, 9 |
| D5 no `_offtopic/` when nothing moves | 6 |
| D6 selecting nothing warns, moves nothing | 6 |
| D7 documents stay in derived `raw/` | 6 |
| E1 manifest before compiling | 7 |
| E2 manifest fields | 7 |
| E3 manifest updated after the second pass | 7 |
| E4 16-hex checksums | 3, 5 |
| F1 command registered | 8 |
| F2 success payload | 8 |
| F3 failure payload with the code | 8 |
| F4 `--kb` defaults to `./.kaas` | 8 |
| F5 volume gate | 8 |
| F6 cost reported after the run | 7, 8 |
| G3 `ask(kb=…)`, unknown slug errors | 11, 12 |
| G4 slug validated against `derived/` | 3, 12 |
| H1 `POST /api/derive`, `derived_jobs` | 13, 16 |
| H1b `GET /api/derive/{id}` | 16 |
| H2 `GET /api/derived` | 16 |
| H3 `?kb=` on wiki tree, file and chat | 17 |
| H4 KB selector scopes tree and chat | 19, 20 |
| H5 progress + cost, no HTTP gate | 14, 16, 20 |
| H6 `en` + `zh` for every string | 19, 20 |
| I1 no test calls a real LLM | all — enforced by the injected selector |
| I2 end-to-end with stubs | 7 |
| I3 real smoke run in `notes.md` | 10 |

No spec criterion is unassigned. Spec G1/G2 were dropped by decision O2, and
`_offtopic` review affordances by O5 — neither has a task, correctly.

## Type consistency

Names used across tasks, checked to match their definitions:
`render_catalog_line`, `Skipped(ref, reason)`, `SelectionResult(paths, batches,
dropped_invented, skipped)`, `DocumentRef(rel_path, checksum, size_bytes)`,
`DeriveReport`, `Selector = (catalog, topic, mode) -> SelectionResult`,
`select_by_topic(catalog, topic, mode, *, model)`,
`resolve_documents(store, article_paths) -> (documents, skipped_articles,
skipped_documents)`, `prune(derived_dir, topic, select) -> (moved, warnings)`,
`resolve_kb_dir(root_kb, slug)`, `list_derived(root_kb)`,
`kbpath.Resolve(root, slug)`, `kbpath.ValidSlug`, `kbpath.ListSlugs`,
`store.DerivedJob`, `store.DerivedJobStore`, `bridge.DeriveRequest/DeriveResponse`,
`derive.NewRunner(js, br, Config, logger)`, `listDerived`, `startDerive`,
`getDeriveJob`, `useKB`, `listWiki(kb?)`, `fetchWikiArticle(path, kb?)`,
`streamChat(req, signal?, kb?)`.

Two cross-language pairs must stay in step, and each is commented at both ends:
the slug regexp (`SLUG_RE` in `_layout.py` ↔ `slugRe` in `kbpath.go` ↔
`slugFillerRe` in `api/derive.go`) and the reason vocabulary (`_types.py`'s
docstring ↔ the manifest readers).

## Known gaps, stated rather than hidden

- **Two concurrent CLI derives on a fresh slug** can race between
  `check_slug_available` and `create`. The tech design already documents this as
  an accepted gap; the HTTP path is covered by the `derived_jobs` unique index.
- **Task 16's tests are sketched, not written.** Every other task carries full
  test bodies. That task's Step 1 says to write them out in full against
  `api_test.go`'s helpers, which cannot be transcribed here without copying that
  file's fixtures — the implementer must read it. Same for the two appended chat
  and Wiki page tests in Tasks 19 and 20.
- **`make test` runs `pnpm test`** but the repository's web tests are invoked
  through pnpm while the rest of this plan assumes it is installed. If it is not,
  substitute `npm test` and say so in `notes.md`.
- **The derive runner reports only one stage** (`compile`) because the bridge call
  is a single non-streaming round trip. Finer progress would need a streaming
  derive command, which the tech design deferred.
