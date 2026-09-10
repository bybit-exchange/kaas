# Derive Job Detail Drawer: Article-Level Task List

## 1. Background and Goals

### Why
The "Normal" (Build Jobs) tab's detail drawer shows a list of article-level build tasks when you click a job row. The "Derived Topics" tab's detail drawer shows only job metadata and a raw result JSON blob — no per-article breakdown. Users expect the same level of detail when inspecting a derive job.

### What We Want to Achieve
When a user clicks a derive job row in the Derived Topics tab, the detail drawer should display a list of articles produced by the derive — showing each article's title, path, tags, and sources — in a table similar to the build job's task table. For succeeded jobs, clicking an article should open the existing wiki article preview sheet.

### Scope
- **In scope**: Show article list from the derived KB's wiki for **succeeded** jobs; reuse the existing `GET /api/wiki?kb=<slug>` endpoint for the article tree; add a flattened article table in the derive detail sheet; allow clicking an article to preview it via the existing `FilePreviewSheet` / wiki file endpoint.
- **Out of scope**: Creating new database tables or FK relationships between derive jobs and tasks; modifying the Python engine or bridge protocol; showing per-article progress for in-progress derive jobs; nested `TaskDetailSheet` (derive articles are not tasks).

## 2. Current State Analysis

### How the System Works Now

**Build Job Detail Drawer (reference)**:
- `GET /api/build-jobs/{id}` returns `BuildJobDetailDTO` with a `tasks: TaskDTO[]` field — article-level task rows from the `tasks` table.
- `BuildJobDetailSheet` renders an embedded `<table>` of tasks with columns: file title, status badge, attempts, updated_at.
- Clicking a task row opens `TaskDetailSheet`; clicking the file name opens `FilePreviewSheet`.

**Derive Job Detail Drawer (current)**:
- `GET /api/derive/{id}` returns `deriveJobResponse` — job-level data only, no article list.
- `DeriveJobDetailSheet` shows: topic, slug, status/stage, model, select_from, timestamps, error, raw result JSON.
- No article table, no nested preview sheets.

**Key Constraint**: Derive jobs create **no Task rows**. The entire derive is a single Python bridge call. Per-article data exists only:
1. On disk as `<kb_dir>/derived/<slug>/wiki/*.md` files (compiled articles with frontmatter)
2. In the `manifest.json` file (`selected_articles`, `skipped_articles`)
3. In the result JSON's `compile` field (aggregate counts, errors)

**Existing Endpoints That Already Work**:
- `GET /api/wiki?kb=<slug>` — returns a tree of wiki articles for a derived KB, with title, path, tags. Already supports derived KBs. Frontend client `listWiki(kb)` exists.
- `GET /api/wiki/file?path=<rel>&kb=<slug>` — returns a single article's content, title, tags, sources. Frontend client `fetchWikiArticle(path, kb)` exists.

### Chosen Approach

**Use the existing wiki endpoint** (`GET /api/wiki?kb=<slug>`) to populate the article list for succeeded derive jobs. This requires **zero backend changes** — the endpoint and frontend client already exist. The derive detail sheet will:
1. Detect a succeeded job with a known slug.
2. Fetch the wiki tree via `listWiki(slug)`.
3. Flatten the tree into a list of articles.
4. Render them in an embedded table.
5. Allow clicking an article name to open a wiki article preview (reusing `fetchWikiArticle`).

For non-succeeded jobs (pending, running, failed), the article table section will show an appropriate empty/unavailable state.

## 3. Technical Design

### Architecture Decisions

1. **No new backend endpoint** — `GET /api/wiki?kb=<slug>` already returns what we need.
2. **No new detail DTO** — The derive detail type stays `DeriveJob`. The article list is fetched separately (not bundled into the detail response) because it's filesystem-derived data that only exists for succeeded jobs.
3. **Separate fetch in the detail sheet** — `DeriveJobDetailSheet` will call `listWiki(slug)` when a succeeded job is displayed, flattening the tree into rows.
4. **Reuse `FilePreviewSheet` pattern** — for article preview, but adapted: instead of fetching by task ID, we fetch by wiki path + kb slug using `fetchWikiArticle`.

### Component Changes

**`DeriveJobDetailSheet.tsx`** — major update:
- Add state for article list (fetched from wiki endpoint).
- Add `useEffect` that calls `listWiki(job.slug)` when `job.status === 'succeeded'`.
- Flatten the wiki tree into a sorted article list.
- Render an embedded article table with columns: title, path (category), tags.
- Add a wiki article preview sheet (inline sheet showing article content).

**`DeriveJobsTab.tsx`** — minor update:
- Change generic type params: `TDetail` becomes `DeriveJobDetail` (a new type extending `DeriveJob` with an optional `articles` field).
- Update `toPreviewDetail` to include `articles: []`.
- Update `getJob` to return the new `DeriveJobDetail` type.

Actually, the simpler approach: **keep `TDetail = DeriveJob`** and have the detail sheet itself manage the wiki fetch. This avoids changing the PagedJobTable generic type and keeps the article fetching logic local to the sheet. The sheet already receives the full `DeriveJob` with the `slug` field, which is all it needs.

### Data Flow

```
User clicks derive job row
  → PagedJobTable calls getDeriveJob(id) → DeriveJob
  → DeriveJobDetailSheet opens with job data
  → If job.status === 'succeeded':
      → useEffect calls listWiki(job.slug)
      → Flatten tree → article list
      → Render article table
      → Click article name → open WikiArticlePreviewSheet
          → fetchWikiArticle(path, slug) → render content
```

### Tree Flattening Algorithm

```typescript
function flattenWikiTree(nodes: WikiTreeNode[]): WikiArticleRow[] {
  const result: WikiArticleRow[] = []
  function walk(nodes: WikiTreeNode[]) {
    for (const node of nodes) {
      if (node.isDir && node.children) {
        walk(node.children)
      } else if (!node.isDir) {
        result.push({
          path: node.path,
          title: node.title || node.name,
          tags: node.tags || [],
        })
      }
    }
  }
  walk(nodes)
  return result
}
```

## 4. Interface Contracts

### Endpoint: GET /api/wiki?kb=\<slug\> (EXISTING — no changes)

This is the existing endpoint used to fetch the article tree for a derived KB. No backend modifications needed.

**Request**: `GET /api/wiki?kb=pricing-fees`

**Response (200)**:
```json
{
  "tree": [
    {
      "name": "concept",
      "path": "concept",
      "isDir": true,
      "fileCount": 3,
      "children": [
        {
          "name": "trading-fees.md",
          "path": "concept/trading-fees.md",
          "title": "Trading Fees Overview",
          "isDir": false,
          "tags": ["fees", "trading"]
        }
      ]
    },
    {
      "name": "standalone-article.md",
      "path": "standalone-article.md",
      "title": "Some Article",
      "isDir": false,
      "tags": ["general"]
    }
  ]
}
```

**Error Responses**:
- **400 Bad Request** — unknown KB slug (the derived KB directory does not exist or has no manifest). This is returned by `resolveKB()` which calls `kbpath.Resolve()` and maps any error to 400. **Not 404.**
- **200 with `{"tree": []}`** — the wiki directory is absent or empty (treated as empty, not an error).

**Frontend model** (`web/src/api/wiki.ts` — existing, no changes):
```typescript
interface WikiTreeNode {
  name: string
  path: string
  title?: string
  isDir: boolean
  fileCount?: number
  tags?: string[]
  children?: WikiTreeNode[]
}
```

**Notes**:
- `listWiki(kb)` does NOT accept an `AbortSignal` parameter. If the sheet is closed/reopened rapidly, the old fetch will complete and its result will be ignored via a stale-check in the `useEffect` cleanup (see Implementation Steps).
- The `title` field is optional — files without frontmatter will have `title` undefined. The UI falls back to `name` in that case.
- `tags` is optional — may be undefined or an empty array.

---

### Endpoint: GET /api/wiki/file?path=\<rel\>&kb=\<slug\> (EXISTING — no changes)

Used for the article preview when clicking an article title in the derived articles table.

**Request**: `GET /api/wiki/file?path=concept/trading-fees.md&kb=pricing-fees`

**Response (200)**:
```json
{
  "path": "concept/trading-fees.md",
  "title": "Trading Fees Overview",
  "tags": ["fees", "trading"],
  "sources": ["raw/doc1.pdf", "raw/doc2.pdf"],
  "created": "2025-01-15",
  "content": "# Trading Fees Overview\n\nBybit charges..."
}
```

**Error Responses**:
- **400 Bad Request** — unknown KB slug
- **400 Bad Request** — path traversal or invalid path
- **404 Not Found** — article file does not exist

**Frontend model** (`web/src/api/wiki.ts` — existing, no changes):
```typescript
interface WikiArticle {
  path: string
  title: string
  tags?: string[]
  sources?: string[]
  created?: string
  content: string
}
```

**Notes**:
- `sources` is optional — may be undefined or an empty array.
- `created` is optional — may be undefined if the article frontmatter has no `created` field.

---

### Endpoint: GET /api/derive/{id} (EXISTING — no changes)

The detail endpoint stays the same. No `articles` field is added — the articles come from a separate wiki endpoint call.

**Response (200)**:
```json
{
  "id": "uuid-string",
  "slug": "pricing-fees",
  "topic": "pricing and fees",
  "model": "gpt-4o",
  "select_from": "articles",
  "status": "succeeded",
  "stage": "done",
  "error": "",
  "result": {
    "derived_kb": "/path/to/kb",
    "slug": "pricing-fees",
    "topic": "pricing and fees",
    "selected": 5,
    "documents": 12,
    "bytes": 1024,
    "filter_batches": 2,
    "compiled": true,
    "compile": { "compiled": 5, "extracted": 12 },
    "cost": { "total_cost_usd": 0.15 },
    "warnings": []
  },
  "created_at": 1704103200000,
  "updated_at": 1704103500000
}
```

**Notes**:
- `error` is omitted (via `omitempty`) when empty string.
- `result` is omitted (via `omitempty`) when the job has no result yet (pending/running) or when the stored result is invalid JSON.
- For non-succeeded jobs, `result` will be absent — the frontend type has `result?: DeriveResult` to handle this.

---

### New Frontend Type: `WikiArticleRow` (local to DeriveJobDetailSheet)

```typescript
/** Flattened article row for the derive detail sheet's article table. */
interface WikiArticleRow {
  path: string    // relative path within wiki/, e.g. "concept/trading-fees.md"
  title: string   // from frontmatter title, fallback to filename
  tags: string[]  // from frontmatter, may be empty array
}
```

This is a UI-only projection — not an API type. It is derived by flattening `WikiTreeNode[]`.

## 5. Implementation Steps

### Phase 1: Add Article Table to DeriveJobDetailSheet

**Step 1.1** — Add wiki article preview component

**File**: `web/src/features/builds/DeriveWikiPreviewSheet.tsx` (new file)

Create a small sheet component that fetches and displays a single wiki article. This is analogous to `FilePreviewSheet` but uses `fetchWikiArticle(path, kb)` instead of a task-based fetch.

```typescript
interface DeriveWikiPreviewSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  articlePath: string | null  // relative wiki path
  kb: string                   // derived KB slug
  displayTitle: string
}
```

- On open, call `fetchWikiArticle(articlePath, kb)`.
- Render: title, tags, sources list, markdown content in a `<pre>` or monospace block (same style as `FilePreviewSheet`).
- Show loading skeleton while fetching.
- Show error state on failure.

**Step 1.2** — Add article list fetch + table to `DeriveJobDetailSheet`

**File**: `web/src/features/builds/DeriveJobDetailSheet.tsx` (modify)

Changes:
1. Import `listWiki` from `@/api/wiki` and `WikiTreeNode` type.
2. Import the new `DeriveWikiPreviewSheet`.
3. Add state: `articles: WikiArticleRow[]`, `articlesLoading: boolean`, `articlesError: string | null`.
4. Add state for preview sheet: `previewOpen`, `previewPath`, `previewTitle`.
5. Add `useEffect` that fires when `job?.slug` changes and `job?.status === 'succeeded'`:
   ```typescript
   useEffect(() => {
     if (!job || job.status !== 'succeeded') {
       setArticles([])
       setArticlesLoading(false)
       setArticlesError(null)
       return
     }
     let stale = false
     setArticlesLoading(true)
     setArticlesError(null)
     listWiki(job.slug)
       .then(({ tree }) => {
         if (!stale) setArticles(flattenWikiTree(tree))
       })
       .catch((err) => {
         if (!stale) setArticlesError(err instanceof Error ? err.message : 'Failed to load articles')
       })
       .finally(() => {
         if (!stale) setArticlesLoading(false)
       })
     return () => { stale = true }
   }, [job?.id, job?.status])
   ```
   Note: uses `stale` flag instead of `AbortSignal` because `listWiki` doesn't accept one.
6. Add `flattenWikiTree` helper function (local to the file or extracted to a small utility).
7. **After** the existing result JSON section, add an articles section:
   - If `job.status !== 'succeeded'`: show nothing (articles section not rendered).
   - If `articlesLoading`: show skeleton rows.
   - If `articlesError`: show error message in muted text.
   - If `articles.length === 0`: show "No articles" message.
   - Otherwise: render an embedded table with columns:
     - **Title** — clickable, opens `DeriveWikiPreviewSheet`
     - **Path** — the category/directory, e.g. `concept/`
     - **Tags** — comma-joined tags or "—"
8. Add `DeriveWikiPreviewSheet` at the bottom of the component tree (same pattern as `BuildJobDetailSheet` nesting `FilePreviewSheet`).

**Step 1.3** — Add i18n keys

**File**: `web/src/i18n/strings.ts` (modify)

Add to both `en` and `zh` sections:

English:
```typescript
'builds.deriveArticles': 'Articles',
'builds.deriveArticlesEmpty': 'No articles produced.',
'builds.deriveArticlesError': 'Failed to load articles',
'builds.deriveArticlesLoading': 'Loading articles…',
'builds.deriveColTitle': 'Title',
'builds.deriveColPath': 'Category',
'builds.deriveColTags': 'Tags',
'builds.deriveArticlePreviewTitle': 'Article Preview',
'builds.deriveArticlePreviewDesc': 'Content of a derived wiki article',
```

Chinese (zh):
```typescript
'builds.deriveArticles': '文章列表',
'builds.deriveArticlesEmpty': '未生成文章。',
'builds.deriveArticlesError': '加载文章失败',
'builds.deriveArticlesLoading': '加载文章中…',
'builds.deriveColTitle': '标题',
'builds.deriveColPath': '分类',
'builds.deriveColTags': '标签',
'builds.deriveArticlePreviewTitle': '文章预览',
'builds.deriveArticlePreviewDesc': '派生 Wiki 文章内容',
```

### Phase 2: Update Tests

**Step 2.1** — Update `DeriveJobDetailSheet` tests

**File**: `web/src/features/builds/__tests__/DeriveJobDetailSheet.test.tsx` (modify)

Add test cases:
1. **Succeeded job shows articles section**: Mock `listWiki` to return a tree with 2 articles. Assert the "Articles" heading and article titles appear in the table.
2. **Failed job does not show articles section**: Provide a failed job. Assert no "Articles" heading, no wiki fetch.
3. **Running job does not show articles section**: Provide a running job. Assert no "Articles" heading.
4. **Articles loading shows skeletons**: Mock `listWiki` to never resolve. Assert skeleton elements appear.
5. **Wiki fetch error shows error message**: Mock `listWiki` to reject. Assert error message appears.
6. **Empty wiki tree shows empty message**: Mock `listWiki` to return `{ tree: [] }`. Assert "No articles produced." message.
7. **Clicking article title opens preview sheet**: Mock `listWiki`, click an article title, assert `DeriveWikiPreviewSheet` opens.

Mock strategy: Mock `@/api/wiki` module's `listWiki` and `fetchWikiArticle` using `vi.mock`.

**Step 2.2** — Add `DeriveWikiPreviewSheet` tests

**File**: `web/src/features/builds/__tests__/DeriveWikiPreviewSheet.test.tsx` (new file)

Test cases:
1. Shows loading skeleton when fetching.
2. Shows article title, tags, sources, and content when loaded.
3. Shows error state on fetch failure.
4. Does not render when `open` is false.

### Phase 3: Verify Integration

**Step 3.1** — Run frontend tests
```bash
cd web && pnpm test -- --run
```

**Step 3.2** — Manual verification checklist
- Open a succeeded derive job → article table appears with correct titles.
- Click an article title → preview sheet opens with content.
- Open a failed derive job → no article table shown.
- Open a running derive job → no article table shown.
- Navigate away from the detail sheet while articles are loading → no state update errors.

### Dependencies Between Steps
- Step 1.1 must complete before Step 1.2 (DeriveJobDetailSheet imports the new preview component).
- Step 1.3 (i18n) must complete before Step 1.2 (the i18n keys are used in the sheet).
- Steps 1.1 and 1.3 can be done in parallel.
- Phase 2 depends on Phase 1.
- Phase 3 depends on Phase 2.

## 6. Risks and Mitigations

### Risk 1: Wiki directory not yet available for recently succeeded jobs
**Scenario**: A derive job transitions to "succeeded" but the filesystem might have a slight lag before the wiki directory is fully written.
**Mitigation**: `GET /api/wiki?kb=<slug>` handles absent wiki directories gracefully — returns `{"tree": []}`. The UI shows "No articles produced." which is acceptable for a brief window. The user can close and reopen the drawer.

### Risk 2: Stale fetch when sheet is closed and reopened quickly
**Scenario**: User opens derive job A (succeeded), closes before wiki fetch completes, opens derive job B. The stale response from job A arrives and incorrectly populates job B's article list.
**Mitigation**: The `useEffect` uses a `stale` flag in its cleanup function. When the effect re-runs (job ID changes), the previous fetch's results are discarded. The `listWiki` function does not support `AbortSignal`, so we cannot cancel in-flight requests, but the stale flag prevents incorrect state updates.

### Risk 3: Large article trees
**Scenario**: A derived KB has hundreds of articles, making the table very long.
**Mitigation**: The table is inside the sheet's scrollable `overflow-auto` container. For v1 this is acceptable. If needed later, we can add client-side pagination or a search filter within the article table.

### Risk 4: `resolveKB` returns 400, not 404, for unknown slugs
**Scenario**: The slug on a derive job doesn't correspond to an on-disk KB (e.g., the derived directory was manually deleted).
**Mitigation**: The `listWiki` call will fail with a 400 error from `resolveKB`. The frontend's `apiFetch` converts any non-OK response to an `ApiError`. The article loading error state in `DeriveJobDetailSheet` will display the error message. No special 404 handling needed — the catch block handles all error codes uniformly.

### Risk 5: Test mocking for wiki API
**Scenario**: Tests need to mock `listWiki` and `fetchWikiArticle` without affecting other tests.
**Mitigation**: Use Vitest's `vi.mock('@/api/wiki')` at the top of the test file. Each test sets up its own mock return value. Use `vi.restoreAllMocks()` in `beforeEach`.
