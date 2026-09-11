# Builds Page Redesign — Unified Task & Derive Job Visibility

## 1. Background and Goals

### Why
The current Tasks page (`/tasks`) shows only document compilation tasks. Derive jobs — which build topic-scoped knowledge bases and cost real money — have no visibility beyond the modal dialog in the Wiki page. Users cannot see historical derive jobs, cannot revisit a failed derive's error, and lose all context once the DeriveDialog closes.

### Goals
1. Unify task and derive-job monitoring into a single "Builds" page with two tabs
2. Add a backend endpoint to list derive jobs (currently missing — only single-job GET exists)
3. Auto-poll when pending/running items exist, pause when browser tab is hidden
4. Global stats bar showing active counts, doubling as tab navigation
5. Detail dialogs for both entity types
6. Simplify the Wiki derive dialog to a "Job started" confirmation with a link to Builds
7. Full i18n support (en/zh)

### Scope
- **In scope**: Backend `ListDerivedJobsPaged` + `DeleteDerivedJob` store methods & SQLite implementation; `GET /api/derive/jobs` and `DELETE /api/derive/jobs/{id}` endpoints; new frontend page/components; routing changes; nav update; i18n; DeriveDialog simplification; test migration
- **Out of scope**: Log streaming, timeline visualization, cancel-job support, WebSocket-based push

## 2. Current State Analysis

### Backend
- `DerivedJobStore` interface in `internal/store/store.go` has: `CreateDerivedJob`, `GetDerivedJob`, `ClaimNextDerivedJob`, `SetDerivedJobStage`, `FinishDerivedJob`, `RecoverRunningDerivedJobs`
- **No `ListDerivedJobsPaged` method** — the interface cannot list derive jobs
- **No `DeleteDerivedJob` method** — terminal derive jobs cannot be deleted
- SQLite table `derived_jobs` has columns: `id, slug, topic, model, select_from, status, stage, error, result, created_at, updated_at`
- Index `idx_derived_jobs_status_created` already exists on `(status, created_at)`, which supports the new listing query
- `GET /api/derive/{id}` returns a `deriveJobResponse` struct with Result as `json.RawMessage`; currently does **not** include `model` or `select_from`
- `GET /api/tasks` uses `PagedListFilter` pattern: status, query, sort, order, limit, offset → returns `{tasks, total}`
- `handleDerive` (POST) checks **both** `s.js == nil` and `s.cfg.DeriveEnabled`; `handleGetDeriveJob` checks only `s.js == nil`
- **`limit=0` behavior**: `ListTasksPaged` with `Limit=0` emits NO `LIMIT` clause — it returns ALL rows, not zero rows. The `if f.Limit > 0` guard means `Limit=0` is treated as "no limit". This is a known issue (documented in `TestListTasksPagedOffsetWithoutLimit`).

### Frontend
- `Tasks.tsx` is a monolithic ~300-line component with inline table, dialogs, pagination, search, sort
- `web/src/pages/Tasks.test.tsx` has **593 lines** of comprehensive tests covering: rendering, filter changes, detail dialog, status/stage colour coding, date formatting fallback, error handling, delete confirmation flow, sorting, debounced search, pagination (including ellipsis), file preview, error indicator badge
- `web/src/api/derived.ts` has `DeriveJob` interface and `getDeriveJob(id)` function — currently missing `model` and `select_from` fields
- `DeriveDialog.tsx` manages the full derive lifecycle inline (start → poll → terminal)
- No Zustand store for tasks or derive jobs — all state is component-local
- Routing: `/tasks` → `<Tasks />`, `/status` → redirect to `/tasks`
- Nav: `layout.tasks` key shows "Tasks" (en) / "蒸馏任务" (zh)
- UI primitives: Tabs (controlled/uncontrolled via Radix), Badge, Card, Dialog, AlertDialog, Button, Input, Select, Skeleton
- i18n: `useT()` returns `(key, vars?) => string` with `{{varName}}` interpolation. However, two existing task strings (`tasks.totalRecords`, `tasks.filePreviewLines`) use the old `{count}` pattern with manual `.replace()` — these are the only ones.

### Constraints
- Backend uses Go 1.22+ ServeMux method routing (`"GET /api/..."`)
- SQLite single-connection serialized access (no concurrent write concerns)
- Frontend has no React Query — manual `useState`/`useEffect` data fetching
- `apiFetch` throws `ApiError` on non-2xx
- i18n uses `{{placeholder}}` interpolation in `useT()` — use this consistently for new strings

## 3. Technical Design

### 3.1 Backend: Store Interface Extension

Add two methods to `DerivedJobStore`:

```go
// ListDerivedJobsPaged returns a page of derive jobs matching the filter.
ListDerivedJobsPaged(ctx context.Context, f DerivedJobListFilter) (*DerivedJobListResult, error)
// DeleteDerivedJob removes a terminal derive job. Returns ErrNotFound if
// the job does not exist or is not in a terminal status.
DeleteDerivedJob(ctx context.Context, id string) error
```

New types in `store.go`:

```go
type DerivedJobListFilter struct {
    Status  string // optional exact status match
    Query   string // LIKE match on topic or slug
    SortBy  string // column to sort by (empty = created_at)
    SortDir string // "asc" or "desc" (empty = desc)
    Limit   int
    Offset  int
}

type DerivedJobListResult struct {
    Jobs  []*DerivedJob
    Total int
}
```

### 3.2 Backend: SQLite Implementation

Mirror `ListTasksPaged` pattern exactly:
1. Build WHERE clause from filter (status exact match, query LIKE on `topic` and `slug`)
2. COUNT(*) for total
3. SELECT with ORDER BY + LIMIT/OFFSET
4. Whitelist sort columns: `topic`, `slug`, `status`, `stage`, `created_at`, `updated_at`

`DeleteDerivedJob`: `DELETE FROM derived_jobs WHERE id = ? AND status IN ('succeeded', 'failed')` + `requireOneRow` for ErrNotFound mapping.

### 3.3 Backend: API Endpoints

Two new endpoints registered in `routes()`:

```go
mux.HandleFunc("GET /api/derive/jobs", s.handleListDeriveJobs)
mux.HandleFunc("DELETE /api/derive/jobs/{id}", s.handleDeleteDeriveJob)
```

**Route ordering note**: Go 1.22 ServeMux uses most-specific-pattern matching. `GET /api/derive/jobs` is a static path and always beats `GET /api/derive/{id}` (wildcard). No conflict. A request for `GET /api/derive/jobs` matches the list endpoint, not the single-job endpoint with `id="jobs"`.

**`DeriveEnabled` access control decision**: `handleListDeriveJobs` and `handleDeleteDeriveJob` check only `s.js == nil` (no job store → 501), NOT `s.cfg.DeriveEnabled`. This is intentional: listing and deleting historical jobs works even when the derive runner is disabled. The derive runner is only required to *create* new jobs (POST /api/derive checks both `s.js == nil` and `DeriveEnabled`). A backend with a derive store but a disabled runner may still have historical jobs worth viewing and cleaning up.

`handleListDeriveJobs` mirrors `handleListTasks`: reads query params, calls `ListDerivedJobsPaged`, projects to `deriveJobResponse` DTOs, returns `{jobs, total}`.

`handleDeleteDeriveJob`: gets job ID from path, calls `GetDerivedJob` (→ 404 if not found), checks terminal status (succeeded/failed → 409 if not), calls `DeleteDerivedJob`, returns 204.

**TOCTOU error handling for `handleDeleteDeriveJob`** (addresses MEDIUM #3): After confirming the job is terminal via `GetDerivedJob`, if `DeleteDerivedJob` returns `ErrNotFound`, the most likely cause is concurrent deletion (another request deleted the job between our GET and DELETE). Return **404** with `"derive job not found"` — not 409, because the job no longer exists, which is closer to 404 semantics than conflict semantics. This mirrors the real-world outcome: the job is gone. The same fix should be applied to the existing `handleDeleteTask` (documented as an optimization note, not changed in this plan since it's outside scope).

### 3.4 Frontend: Routing

**Problem**: Two separate routes (`builds/tasks` and `builds/derive`) both rendering `<Builds />` would cause React Router 6 to unmount/remount the component on tab switch, losing all parent state (stats, polling state).

**Solution**: Use a single route with an optional path parameter:

```tsx
<Route path="builds/:tab?" element={<Suspense fallback={<PageSpinner />}><Builds /></Suspense>} />
```

Inside `Builds.tsx`, the component reads `useParams().tab` to determine the active tab:
- `tab === undefined` or `tab === 'tasks'` → tasks tab
- `tab === 'derive'` → derive tab
- Anything else → `<Navigate to="/builds/tasks" replace />`

Tab switching uses `useNavigate()` with `replace: true` to update the URL without pushing history entries. Because the same `<Route>` element renders in both cases, React Router reuses the component instance — no remount, no state loss.

Full route changes in `App.tsx`:
```tsx
// Remove:
<Route path="tasks" element={...} />
<Route path="status" element={<Navigate to="/tasks" replace />} />

// Add:
<Route path="builds/:tab?" element={<Suspense fallback={<PageSpinner />}><Builds /></Suspense>} />
<Route path="tasks" element={<Navigate to="/builds/tasks" replace />} />
<Route path="status" element={<Navigate to="/builds/tasks" replace />} />
```

### 3.5 Frontend: Component Architecture

```
web/src/pages/Builds.tsx           — Shell: stats bar + tab routing (single component instance)
web/src/features/builds/
  TasksTab.tsx                     — Normal Tasks table (extracted from Tasks.tsx)
  DeriveJobsTab.tsx                — Derive Jobs table (new)
  TaskDetailDialog.tsx             — Task detail dialog (extracted from Tasks.tsx)
  DeriveJobDetailDialog.tsx        — Derive job detail dialog (new)
  StatsBar.tsx                     — Global stats bar with counts
  StatusStageBadge.tsx             — Merged status+stage colored badge
  useAutoPolling.ts                — Shared polling hook with Page Visibility
  types.ts                         — Shared types (tab names, stats shape)
```

### 3.6 Auto-Polling Design

Custom hook `useAutoPolling`:
- Accepts `fetchFn: () => Promise<void>` and `hasActiveItems: boolean`
- Polls every 5s when `hasActiveItems` is true
- Pauses when `document.hidden` (Page Visibility API)
- Resumes immediately on `visibilitychange` when becoming visible (fires one immediate fetch then resumes interval)
- Returns `{ isPolling: boolean }`
- Cleanup on unmount

### 3.7 Stats Bar Design (addresses SEVERE #1 — `limit=0` strategy is broken)

The stats bar displays pending+running counts for each tab and provides tab navigation. It requires knowing per-status counts that the paginated list responses don't provide.

**SEVERE #1 FIX**: The previous plan proposed using `limit=0` to get counts efficiently. However, `ListTasksPaged` with `Limit=0` emits NO `LIMIT` clause — it returns ALL rows. This is confirmed by the SQLite implementation: `if f.Limit > 0 { selectQ += " LIMIT ?" }`. Using `limit=0` would fetch the entire task/job table every 5 seconds.

**Corrected approach**: Use `limit=1` instead of `limit=0`. This:
- Returns at most 1 row per call (bounded, negligible overhead)
- Still provides the correct `total` count in the response
- Requires NO backend changes — the existing API and store work correctly with `limit=1`
- The single returned row is discarded; only `total` is used

The `Builds.tsx` parent component makes 4 lightweight API calls on mount and each poll tick:

| Call | Purpose | Response size |
|---|---|---|
| `GET /api/tasks?status=pending&limit=1` | Pending tasks count | `{tasks:[...1 item], total: N}` ~200 bytes |
| `GET /api/tasks?status=running&limit=1` | Running tasks count | ~200 bytes |
| `GET /api/derive/jobs?status=pending&limit=1` | Pending derive jobs count | ~200 bytes |
| `GET /api/derive/jobs?status=running&limit=1` | Running derive jobs count | ~200 bytes |

**Why 4 calls, not a summary endpoint**: Adding a `/api/builds/summary` endpoint would require aggregating across two different stores (tasks + derive jobs) in a new handler, adding interface surface, and coupling the two entity types. The 4 calls reuse existing endpoints, each hitting an indexed `status` column for a COUNT(*) with bounded row scanning (1 row max). At a 5s poll interval, this is ~800 bytes/tick — negligible.

**Polling lifecycle**: Stats polling runs only when `tasksPending + tasksRunning + derivePending + deriveRunning > 0`. When all counts hit zero, polling stops. It also pauses when the browser tab is hidden. The `useAutoPolling` hook manages this.

The `StatsBar` component renders:
```
┌──────────────────────────────────────┐
│ [Normal Tasks ●2 active] [Derive Jobs ●1 active] │
└──────────────────────────────────────┘
```
- Two clickable segments, active tab highlighted
- Each segment shows: tab label + "●N active" badge when pending+running > 0
- Clicking switches tabs via URL navigation

### 3.8 Result Field Serialization

The `result` field on `deriveJobResponse` is `json.RawMessage` with `omitempty`. Go's `json.RawMessage` treats `nil` as the "zero value", and `omitempty` omits zero-valued fields. This means:

- When `job.Result` is a non-empty string containing valid JSON: `result` appears as a JSON object in the response
- When `job.Result` is empty or invalid JSON: `result` is **absent from the response entirely** (not `null`, not `""`)

**Wire format contract**: `result` is either a JSON object or absent — it is never `null`.

**Frontend typing**: The `DeriveJob.result` field must be typed as `DeriveResult | undefined` (not `DeriveResult | null`). The existing `DeriveJob` interface in `web/src/api/derived.ts` already uses `result?: DeriveResult` which correctly maps to `DeriveResult | undefined`. No change needed for this field.

**Same applies to `error`**: `json:"error,omitempty"` means the field is absent when empty, never `null`. Frontend types it as `error?: string` (string | undefined).

### 3.9 Table Columns

**Normal Tasks tab** (changed from current):
| Column | Sortable | Notes |
|---|---|---|
| File Title | Yes (`file_title`) | Clickable → file preview sheet (unchanged) |
| Status / Stage | Yes (`status`) | Single merged `StatusStageBadge` |
| Attempts | Yes (`attempts`) | `{attempts}/{max_attempts}` |
| Updated | Yes (`updated_at`) | Formatted date |
| Actions | No | Detail button + Delete button |

Dropped: Source column (low-value, clutters the table).

**Derive Jobs tab** (new):
| Column | Sortable | Notes |
|---|---|---|
| Topic | Yes (`topic`) | The derive topic string |
| Slug | Yes (`slug`) | The derived KB slug |
| Status / Stage | Yes (`status`) | Merged `StatusStageBadge` |
| Select From | No | `job.select_from || '—'` (em-dash when empty, meaning engine default) |
| Updated | Yes (`updated_at`) | Formatted date |
| Actions | No | Detail button + Delete button |

### 3.10 DeriveDialog Simplification & onDerived Removal

**Decision**: Remove the `onDerived` callback entirely. Remove the `kbListVersion` state from `Wiki.tsx`.

**Rationale**: The current `onDerived` fires when a derive *succeeds* (terminal), triggering a KB selector refresh in Wiki.tsx. After simplification, the DeriveDialog no longer polls for completion — it only starts the job and shows a link to the Builds page. There is no moment to fire "onDerived" that would be useful.

The KB selector won't auto-refresh after a derive completes. This is acceptable because:
1. The user navigates to the Builds page to track progress
2. Navigating back to Wiki will re-mount the component, triggering a fresh KB list fetch
3. The KB selector already fetches on mount — there's no stale data problem on navigation

**Changes to `DeriveDialog.tsx`**:
- Remove `onDerived` prop entirely
- Remove polling `useEffect` (no more `getDeriveJob` calls)
- Remove `announced` ref and success-announce effect
- After successful `startDerive()`: show "Job started" toast + render `<Link to="/builds/derive">View in Builds</Link>`
- Keep: topic input, select_from radio, start button, error display for start failure
- Dialog can close at any time (no "running" lock needed since we don't poll)

**Changes to `Wiki.tsx`**:
- Remove `kbListVersion` state
- Remove `onDerived` prop from `<DeriveDialog />`
- Remove `reloadKey={kbListVersion}` from `<KBSelector />` — the prop is optional (default 0), so just removing it is safe

### 3.11 Nav Bar Update

Change nav item from:
```ts
{ key: 'layout.tasks', to: '/tasks', icon: Activity }
```
to:
```ts
{ key: 'layout.builds', to: '/builds', icon: Activity }
```

The `NavLink` active detection: `pathname === to || pathname.startsWith(to + '/')`. Since `to` is `/builds`, this matches `/builds`, `/builds/tasks`, `/builds/derive`. Works correctly.

### 3.12 Delete Behavior: Terminal Status Differences (addresses OPTIMIZATION note)

**Tasks**: `TERMINAL_STATUSES = ['pending', 'succeeded', 'failed', 'cancelled']` — includes `pending` because a user-submitted task that hasn't been picked up yet can be discarded.

**Derive Jobs**: Terminal statuses for deletion are `succeeded` and `failed` only. Derive jobs do NOT have a `cancelled` status (the `DerivedStatus*` constants only define `pending`, `running`, `succeeded`, `failed`). And `pending` is NOT deletable for derive jobs because: a pending derive job holds a unique slug slot and will be picked up by the runner; deleting it mid-queue would leave a "gap" in the slug reservation system without the runner knowing.

This difference should be communicated in the UI:
- Tasks tab: delete button enabled for pending/succeeded/failed/cancelled
- Derive Jobs tab: delete button enabled for succeeded/failed only
- Derive Jobs tab: pending/running jobs show a disabled delete button with a tooltip explaining why

### 3.13 Empty States

Both tabs show actionable empty states:
- Tasks tab empty: "No tasks found. Submit content to get started." with link to `/submit`
- Derive Jobs tab empty: "No derive jobs yet. Derive a topic KB from the Wiki page." with link to `/wiki`

### 3.14 Tab State Preservation (addresses OPTIMIZATION note)

Both tab components are conditionally rendered (not kept mounted). Switching tabs unmounts the inactive tab, losing filter/sort/page state. This is acceptable for v1 and consistent with the rest of the app (navigating away from Tasks and back resets state). For a future optimization, both tabs could be kept mounted using CSS `display:none`/`display:block`, but this adds complexity for marginal benefit.

### 3.15 Invalid Query Param Behavior (addresses OPTIMIZATION note)

Invalid query parameters silently fall back to defaults — this matches the existing `handleListTasks` handler pattern. `queryInt` returns the default when parsing fails. Unknown `sort` values fall back to `created_at`. Unknown `status` values produce an empty result (correct SQL behavior). This is documented here for awareness but requires no code changes.

## 4. Interface Contracts

### 4.1 Endpoint: GET /api/derive/jobs

List all derive jobs with pagination, filtering, sorting, and search.

**Query Parameters**:
| Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | (none) | Exact match: `pending`, `running`, `succeeded`, `failed` |
| `q` | string | (none) | LIKE search on `topic` and `slug` |
| `sort` | string | `created_at` | Sort column: `topic`, `slug`, `status`, `stage`, `created_at`, `updated_at` |
| `order` | string | `desc` | Sort direction: `asc` or `desc` |
| `limit` | int | `20` | Page size (min 0; 0 means no limit — returns all rows) |
| `offset` | int | `0` | Offset for pagination |

**Response (200)**:
```json
{
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "slug": "golang-concurrency",
      "topic": "Go concurrency patterns",
      "model": "gpt-4o",
      "select_from": "documents",
      "status": "succeeded",
      "stage": "done",
      "result": {
        "select_from": "documents",
        "selected": 12,
        "documents": 8,
        "bytes": 45000,
        "filter_batches": 3,
        "compiled": true,
        "cost": { "total_cost_usd": 0.0342 }
      },
      "created_at": 1704103200000,
      "updated_at": 1704103500000
    },
    {
      "id": "660e9500-f30c-52e5-b827-557766551111",
      "slug": "rust-basics",
      "topic": "Rust language basics",
      "model": "",
      "select_from": "",
      "status": "running",
      "stage": "filter",
      "created_at": 1704106800000,
      "updated_at": 1704107400000
    }
  ],
  "total": 42
}
```

**Response when `limit=1` (used by stats bar)**:
```json
{
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "slug": "golang-concurrency",
      "topic": "Go concurrency patterns",
      "model": "gpt-4o",
      "select_from": "documents",
      "status": "succeeded",
      "stage": "done",
      "result": { "..." : "..." },
      "created_at": 1704103200000,
      "updated_at": 1704103500000
    }
  ],
  "total": 42
}
```

**Error Responses**:
- `501` — `{"error": "derive is not available on this backend"}` — no job store (s.js == nil)

**Backend model** (Go):

The existing `deriveJobResponse` struct in `internal/api/derive.go` is extended with `Model` and `SelectFrom`:
```go
type deriveJobResponse struct {
    ID         string          `json:"id"`
    Slug       string          `json:"slug"`
    Topic      string          `json:"topic"`
    Model      string          `json:"model"`
    SelectFrom string          `json:"select_from"`
    Status     string          `json:"status"`
    Stage      string          `json:"stage"`
    Error      string          `json:"error,omitempty"`
    Result     json.RawMessage `json:"result,omitempty"`
    CreatedAt  int64           `json:"created_at"`
    UpdatedAt  int64           `json:"updated_at"`
}
```

Serialization behavior:
- `model`: Always present in JSON. Empty string `""` when no override. Deliberately NOT `omitempty` — the frontend needs to distinguish "no override" from "field absent".
- `select_from`: Always present in JSON. Empty string `""` when engine default. Deliberately NOT `omitempty` — the frontend needs to show whether the user chose articles vs documents vs engine default. (Addresses MEDIUM #2.)
- `error`: Omitted entirely when empty string (via `omitempty`). Never serialized as `null` or `""`.
- `result`: Omitted entirely when `json.RawMessage` is nil (via `omitempty`). Never serialized as `null`. When present, it is a raw JSON object from the engine.
- `created_at`, `updated_at`: Always present. Unix milliseconds (int64).
- `jobs`: Always an array. Empty `[]` when no results, never `null`.
- `total`: Always present. Integer ≥ 0.

The handler writes `map[string]any{"jobs": dtos, "total": result.Total}` — same pattern as `handleListTasks`.

The projection from `*store.DerivedJob` to `deriveJobResponse` is extracted into a helper `toDeriveDTO(j *store.DerivedJob) deriveJobResponse` shared by `handleGetDeriveJob` and `handleListDeriveJobs`. The helper:
1. Sets all scalar fields directly from the store struct (including `Model` and `SelectFrom`)
2. For `Result`: if `job.Result != ""` and `json.Valid([]byte(job.Result))`, sets `resp.Result = json.RawMessage(job.Result)`; otherwise leaves it nil (omitted)

**Frontend model** (TypeScript):

```ts
// web/src/api/derived.ts — extended

export interface DeriveJob {
  id: string
  slug: string
  topic: string
  model: string            // empty string when no override
  select_from: string      // 'articles' | 'documents' | '' (empty = engine default)
  status: DeriveStatus     // 'pending' | 'running' | 'succeeded' | 'failed'
  stage: string            // 'queued' | 'filter' | 'compile' | 'done'
  error?: string           // undefined when absent (omitempty on backend)
  result?: DeriveResult    // undefined when absent (omitempty on backend), NOT null
  created_at: number       // unix ms
  updated_at: number       // unix ms
}

export interface ListDeriveJobsParams {
  status?: string
  q?: string
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

export interface ListDeriveJobsResponse {
  jobs: DeriveJob[]
  total: number
}
```

Key frontend typing notes:
- `result` is typed as `DeriveResult | undefined` (via optional `?`), **not** `DeriveResult | null`. The backend never sends `"result": null` — it either sends a JSON object or omits the field entirely.
- `error` is typed as `string | undefined` (via optional `?`), **not** `string | null`. Same omitempty behavior.
- `model` is typed as `string` (always present, may be empty `""`).
- `select_from` is typed as `string` (always present, may be empty `""`). The frontend shows "—" (em-dash) for empty values in the table, and can show a human-readable label ("Articles"/"Documents") for non-empty values in the detail dialog.

---

### 4.2 Endpoint: DELETE /api/derive/jobs/{id}

Delete a terminal derive job.

**Request**: No body. Job ID in URL path.

**Response (204)**: No content.

**Error Responses**:
- `404` — `{"error": "derive job not found"}` — job does not exist
- `409` — `{"error": "derive job is not in a terminal status"}` — job is pending or running
- `501` — `{"error": "derive is not available on this backend"}` — no job store

**TOCTOU handling** (addresses MEDIUM #3): The handler flow is:
1. `GetDerivedJob(id)` → 404 if not found
2. Check terminal status (succeeded/failed) → 409 if not
3. `DeleteDerivedJob(id)` → if `ErrNotFound`, return **404** with `"derive job not found"` (not 409)

The TOCTOU case: `GetDerivedJob` succeeds, confirming the job exists and is terminal, but `DeleteDerivedJob` returns `ErrNotFound`. The most likely cause is concurrent deletion — another request deleted the job between our GET and DELETE. Since the job no longer exists, **404 is the correct response**, not 409. The 409 response would mislead the client into thinking the job still exists but in a non-terminal state.

```go
if err := s.js.DeleteDerivedJob(r.Context(), id); errors.Is(err, store.ErrNotFound) {
    // TOCTOU: job was deleted concurrently between GetDerivedJob and DeleteDerivedJob.
    // 404 is correct — the job is gone, not in a conflicting state.
    writeErr(w, http.StatusNotFound, "derive job not found")
    return
} else if err != nil {
    writeErr(w, http.StatusInternalServerError, "delete derive job: "+err.Error())
    return
}
w.WriteHeader(http.StatusNoContent)
```

**Backend notes**:
- Terminal statuses for derive jobs: `succeeded`, `failed` (derive jobs have no `cancelled` status unlike tasks)
- No raw file cleanup needed (unlike task deletion which removes the raw content file)
- Access control: checks `s.js == nil` → 501. Does NOT check `DeriveEnabled`. Historical jobs are deletable regardless of runner state.

**Frontend notes**:
- New function in `web/src/api/derived.ts`:
```ts
export async function deleteDeriveJob(id: string): Promise<void> {
  await apiFetch(`/derive/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
```

---

### 4.3 Endpoint: GET /api/derive/{id} (modified — add `model` and `select_from` fields)

**Response (200)** — updated to include `model` and `select_from`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "slug": "golang-concurrency",
  "topic": "Go concurrency patterns",
  "model": "gpt-4o",
  "select_from": "documents",
  "status": "succeeded",
  "stage": "done",
  "result": { "selected": 12, "documents": 8, "bytes": 45000 },
  "created_at": 1704103200000,
  "updated_at": 1704103500000
}
```

This is a backward-compatible addition (new fields). The existing `DeriveDialog` polling code does not use `model` or `select_from`, so it is unaffected. The shared `toDeriveDTO` helper ensures both endpoints produce identical JSON shapes.

---

### 4.4 Endpoint: GET /api/tasks (unchanged)

No changes to the tasks API. Listed for completeness as the stats bar uses it.

**Response (200)**:
```json
{
  "tasks": [ { "id": "...", ... } ],
  "total": 42
}
```

Stats bar uses `limit=1` calls with `status=pending` and `status=running` to get counts efficiently. These return `{tasks: [at most 1 item], total: N}` — the single returned task is discarded, only `total` is used. `limit=1` is safe because the store code emits `LIMIT 1` (the `if f.Limit > 0` guard passes).

---

### 4.5 Cross-Module Frontend Types

```ts
// web/src/features/builds/types.ts

/** Which tab is active in the Builds page */
export type BuildTab = 'tasks' | 'derive'

/** Per-tab active item counts for the stats bar */
export interface TabActiveCounts {
  pending: number
  running: number
}

/** Combined stats for both tabs */
export interface BuildsStats {
  tasks: TabActiveCounts
  derive: TabActiveCounts
  loading: boolean
}
```

## 5. Implementation Steps

### Phase 1: Backend — Store & API (no frontend dependency)

**Step 1.1: Extend `DerivedJobStore` interface**
- File: `internal/store/store.go`
- Add `DerivedJobListFilter` and `DerivedJobListResult` types
- Add `ListDerivedJobsPaged(ctx context.Context, f DerivedJobListFilter) (*DerivedJobListResult, error)` to `DerivedJobStore` interface
- Add `DeleteDerivedJob(ctx context.Context, id string) error` to `DerivedJobStore` interface

**Step 1.2: SQLite implementation**
- File: `internal/store/sqlite/derived.go`
- Add `ListDerivedJobsPaged` method mirroring `ListTasksPaged` in `sqlite.go`:
  - Build WHERE clause: optional `status = ?`, optional `(topic LIKE ? OR slug LIKE ?)`
  - COUNT(*) query for total
  - SELECT with ORDER BY (whitelist: `topic`, `slug`, `status`, `stage`, `created_at`, `updated_at`) + LIMIT/OFFSET
  - Reuse existing `derivedJobColumns` and `scanDerivedJob`
  - Default sort: `created_at DESC`
- Add `DeleteDerivedJob` method:
  - SQL: `DELETE FROM derived_jobs WHERE id = ? AND status IN ('succeeded', 'failed')`
  - Use `requireOneRow` — returns `ErrNotFound` if no row affected (not found or non-terminal)

**Step 1.3: SQLite tests**
- File: `internal/store/sqlite/derived_test.go`
- Tests to add:
  - `TestListDerivedJobsPagedEmpty` — empty table returns `{Jobs: [], Total: 0}`
  - `TestListDerivedJobsPagedFilterByStatus` — status filter works
  - `TestListDerivedJobsPagedSearchQuery` — q matches topic and slug via LIKE
  - `TestListDerivedJobsPagedPagination` — limit/offset returns correct page with correct total
  - `TestListDerivedJobsPagedSorting` — whitelist works, unknown columns fall back to created_at
  - `TestDeleteDerivedJobTerminal` — succeeds for succeeded and failed jobs
  - `TestDeleteDerivedJobNonTerminal` — returns ErrNotFound for pending/running jobs
  - `TestDeleteDerivedJobNotFound` — returns ErrNotFound for nonexistent ID

**Step 1.4: Add `model` and `select_from` fields to `deriveJobResponse` and extract `toDeriveDTO` helper**
- File: `internal/api/derive.go`
- Add `Model string \`json:"model"\`` to `deriveJobResponse` struct
- Add `SelectFrom string \`json:"select_from"\`` to `deriveJobResponse` struct (addresses MEDIUM #2)
- Extract `toDeriveDTO(j *store.DerivedJob) deriveJobResponse` helper function from the inline projection in `handleGetDeriveJob`
- The helper sets `resp.Model = job.Model` and `resp.SelectFrom = job.SelectFrom`
- Update `handleGetDeriveJob` to use `toDeriveDTO`

**Step 1.5: Add API handlers**
- File: `internal/api/derive.go`
- Add `handleListDeriveJobs(w, r)`:
  - Check `s.js == nil` → 501 (does NOT check `DeriveEnabled` — intentional, see Section 3.3)
  - Parse query params (status, q, sort, order, limit, offset) using existing `queryInt` helper
  - Call `s.js.ListDerivedJobsPaged(ctx, filter)`
  - Project `[]*store.DerivedJob` to `[]deriveJobResponse` DTOs using `toDeriveDTO`
  - Write `{"jobs": dtos, "total": result.Total}`
- Add `handleDeleteDeriveJob(w, r)`:
  - Check `s.js == nil` → 501
  - Get job ID from `r.PathValue("id")`
  - `s.js.GetDerivedJob(ctx, id)` → 404 if not found
  - Check terminal status (succeeded/failed) → 409 if not
  - `s.js.DeleteDerivedJob(ctx, id)` → if `ErrNotFound`, return **404** (TOCTOU: concurrent deletion, see Section 4.2)
  - Return 204

**Step 1.6: Register routes**
- File: `internal/api/server.go`
- Add to `routes()` function:
  ```go
  mux.HandleFunc("GET /api/derive/jobs", s.handleListDeriveJobs)
  mux.HandleFunc("DELETE /api/derive/jobs/{id}", s.handleDeleteDeriveJob)
  ```
  Placement relative to `GET /api/derive/{id}` doesn't matter for Go 1.22 ServeMux (static paths always beat wildcards), but keeping related endpoints together aids readability.

**Step 1.7: Update fake store in tests**
- File: `internal/api/derive_test.go`
- Add `ListDerivedJobsPaged` and `DeleteDerivedJob` methods to `fakeDerivedJobStore`

**Step 1.8: API handler tests**
- File: `internal/api/derive_test.go`
- Tests to add:
  - `TestListDeriveJobs` — returns paginated list with correct DTO shape, including `model` and `select_from`
  - `TestListDeriveJobsFilterByStatus` — status filter works
  - `TestListDeriveJobsSearchQuery` — q parameter matches topic/slug
  - `TestListDeriveJobsWithoutJobStore` — 501 when s.js == nil
  - `TestDeleteDeriveJob` — 204 for terminal job (both succeeded and failed)
  - `TestDeleteDeriveJobNotFound` — 404
  - `TestDeleteDeriveJobNonTerminal` — 409 for running/pending job
  - `TestDeleteDeriveJobWithoutJobStore` — 501
  - `TestDeleteDeriveJobConcurrentDeletion` — TOCTOU case returns 404 (not 409)
  - `TestGetDeriveJobIncludesModelAndSelectFrom` — verify both fields in response
  - `TestListDeriveJobsRouteDoesNotConflictWithGetById` — `GET /api/derive/jobs` returns list, `GET /api/derive/{some-uuid}` returns single job

### Phase 2: Frontend — API Client & Types

**Step 2.1: Extend derived API client**
- File: `web/src/api/derived.ts`
- Add `model: string` field to existing `DeriveJob` interface
- Add `select_from: string` field to existing `DeriveJob` interface (addresses MEDIUM #2)
- Add `ListDeriveJobsParams` interface
- Add `ListDeriveJobsResponse` interface
- Add `listDeriveJobs(p?: ListDeriveJobsParams): Promise<ListDeriveJobsResponse>` function (mirrors `listTasks` pattern)
- Add `deleteDeriveJob(id: string): Promise<void>` function

**Step 2.2: Create shared build types**
- File: `web/src/features/builds/types.ts`
- Define `BuildTab`, `TabActiveCounts`, `BuildsStats` types (as in Section 4.5)

### Phase 3: Frontend — Shared Components

**Step 3.1: Auto-polling hook**
- File: `web/src/features/builds/useAutoPolling.ts`
- Hook signature: `useAutoPolling(fetchFn: () => Promise<void>, hasActiveItems: boolean, intervalMs?: number)`
- Default interval: 5000ms
- Uses `setInterval` when `hasActiveItems` is true
- Listens to `document.visibilitychange`: clears interval when hidden, restarts (with immediate fetch) when visible
- Returns `{ isPolling: boolean }`
- Cleans up on unmount

**Step 3.2: StatusStageBadge component**
- File: `web/src/features/builds/StatusStageBadge.tsx`
- Props: `{ status: string; stage: string }`
- Renders a single `<Badge>` with combined status+stage label
- Status determines the badge color (reuses existing `statusColor` logic from Tasks.tsx)
- When status is `running` or `pending` and stage is not terminal, appends stage: "Running · Extracting"
- When status is terminal (`succeeded`/`failed`), shows only status: "Succeeded"
- Reuses stage label translation (`stage.${stage}` for tasks, `deriveStage.${stage}` for derive stages)

**Step 3.3: StatsBar component**
- File: `web/src/features/builds/StatsBar.tsx`
- Props: `{ stats: BuildsStats; activeTab: BuildTab; onTabChange: (tab: BuildTab) => void }`
- Renders two clickable segments (Normal Tasks | Derive Jobs)
- Each segment shows: tab label + active count badge (pending+running) when > 0
- Active tab segment has highlighted background
- Uses `Card` primitive for container

### Phase 4: Frontend — Tab Components

**Step 4.1: TasksTab component**
- File: `web/src/features/builds/TasksTab.tsx`
- Extracted from `Tasks.tsx` with these changes:
  - Drop Source column
  - Replace separate Status and Stage columns with single `StatusStageBadge`
  - Add red left border (`border-l-4 border-destructive`) on failed rows
  - Keep: search, status filter, sort, pagination, file preview sheet, delete confirmation
  - Use `{{count}}` style interpolation for new i18n strings. Migrate `tasks.totalRecords` from `{count}` to `{{count}}` and update call site to use `t('tasks.totalRecords', { count: total })` instead of `.replace('{count}', ...)`
  - Similarly migrate `tasks.filePreviewLines` from `{count}` to `{{count}}`

**Step 4.2: DeriveJobsTab component**
- File: `web/src/features/builds/DeriveJobsTab.tsx`
- Columns: Topic, Slug, StatusStageBadge, Select From, Updated, Actions
- Select From column: show human-readable label — `'Articles'` for `'articles'`, `'Documents'` for `'documents'`, `'—'` (em-dash) for empty (engine default). Use i18n keys for labels.
- Reuse same pagination, search, status filter, sort patterns as TasksTab
- Delete confirmation dialog for terminal jobs (succeeded/failed only — see Section 3.12)
- Delete button disabled for pending/running jobs
- Detail button opens `DeriveJobDetailDialog`
- Actionable empty state with link to `/wiki`
- Status filter dropdown: `all`, `pending`, `running`, `succeeded`, `failed` (no `cancelled` — derive jobs don't have it)
- `useAutoPolling` integration: poll when pending/running jobs exist in the current view

**Step 4.3: TaskDetailDialog component**
- File: `web/src/features/builds/TaskDetailDialog.tsx`
- Extracted from the detail dialog in `Tasks.tsx`
- Props: `{ open: boolean; onOpenChange: (open: boolean) => void; taskId: string | null }`
- Fetches full task detail via `getTask(id)` when opened
- Shows: status badge, stage, attempts, error, result JSON (line-numbered)

**Step 4.4: DeriveJobDetailDialog component**
- File: `web/src/features/builds/DeriveJobDetailDialog.tsx`
- Props: `{ open: boolean; onOpenChange: (open: boolean) => void; jobId: string | null }`
- Fetches full job detail via `getDeriveJob(id)` when opened
- Shows: status badge, stage, topic, slug, model (or "—"), **select_from** (human-readable label or "Engine default" for empty), error (if failed), result details (if succeeded): documents compiled, bytes, cost

### Phase 5: Frontend — Page Shell & Routing

**Step 5.1: Builds page component**
- File: `web/src/pages/Builds.tsx`
- Reads `useParams().tab` to determine active tab (defaults to `'tasks'`)
- Invalid tab values → `<Navigate to="/builds/tasks" replace />`
- Uses `useNavigate(..., { replace: true })` to switch tabs (URL-driven)
- Fetches summary stats via 4 lightweight `limit=1` calls (see Section 3.7)
- Passes stats to `StatsBar`
- Conditionally renders `TasksTab` or `DeriveJobsTab` based on active tab
- `useAutoPolling` for stats fetching: active when any pending+running count > 0
- Page title: `t('builds.title')` = "Builds"

**Step 5.2: Update routing**
- File: `web/src/App.tsx`
- Replace:
  ```tsx
  <Route path="tasks" element={<Suspense fallback={<PageSpinner />}><Tasks /></Suspense>} />
  <Route path="status" element={<Navigate to="/tasks" replace />} />
  ```
  With:
  ```tsx
  <Route path="builds/:tab?" element={<Suspense fallback={<PageSpinner />}><Builds /></Suspense>} />
  <Route path="tasks" element={<Navigate to="/builds/tasks" replace />} />
  <Route path="status" element={<Navigate to="/builds/tasks" replace />} />
  ```
- Update lazy import: `const Builds = lazy(() => import('@/pages/Builds').then(m => ({ default: m.Builds })))`
- Remove old `Tasks` lazy import

**Step 5.3: Update nav bar**
- File: `web/src/layouts/AppLayout.tsx`
- Change nav item:
  ```ts
  { key: 'layout.builds', to: '/builds', icon: Activity }
  ```

### Phase 6: Frontend — DeriveDialog Simplification

**Step 6.1: Simplify DeriveDialog**
- File: `web/src/features/wiki/DeriveDialog.tsx`
- Remove `onDerived` prop from interface
- Remove polling `useEffect` (no more `getDeriveJob` calls)
- Remove `announced` ref and success-announce effect
- Remove `timer` ref
- Remove `terminal`, `running` derived state
- After successful `startDerive()`:
  - Show success message text
  - Render `<Link to="/builds/derive">` styled as a button/link: "View in Builds →"
  - User can close dialog at any time
- Keep: topic input, select_from radio, start button, inline error display for start failure

**Step 6.2: Update Wiki.tsx**
- File: `web/src/pages/Wiki.tsx`
- Remove `kbListVersion` state: `const [kbListVersion, setKBListVersion] = useState(0)` → delete
- Remove `onDerived` callback from `<DeriveDialog />`: `<DeriveDialog onDerived={() => setKBListVersion((v) => v + 1)} />` → `<DeriveDialog />`
- Remove `reloadKey={kbListVersion}` from `<KBSelector />`: `<KBSelector reloadKey={kbListVersion} />` → `<KBSelector />` (prop is optional with default 0, safe to remove)

### Phase 7: i18n

**Step 7.1: Add i18n strings**
- File: `web/src/i18n/strings.ts`
- All new strings use `{{varName}}` interpolation (not `{varName}`)
- Migrate existing `tasks.totalRecords` from `'Total {count} records'` to `'Total {{count}} records'` (en) and from `'共 {count} 条记录'` to `'共 {{count}} 条记录'` (zh)
- Migrate existing `tasks.filePreviewLines` from `'{count} lines'` to `'{{count}} lines'` (en) and from `'共 {count} 行'` to `'共 {{count}} 行'` (zh)
- Update call sites in TasksTab to use `t('tasks.totalRecords', { count: total })` instead of `.replace('{count}', ...)`

New keys (en / zh):

```ts
// Layout
'layout.builds': 'Builds' / '构建任务'

// Builds page
'builds.title': 'Builds' / '构建任务'
'builds.tabTasks': 'Normal Tasks' / '普通任务'
'builds.tabDerive': 'Derive Jobs' / '派生任务'
'builds.statsActive': '{{count}} active' / '{{count}} 进行中'

// Derive jobs tab
'builds.deriveEmpty': 'No derive jobs yet.' / '暂无派生任务'
'builds.deriveEmptyAction': 'Derive a topic KB from the Wiki page' / '从Wiki页面派生主题知识库'
'builds.deriveDeleteConfirmTitle': 'Delete Derive Job' / '删除派生任务'
'builds.deriveDeleteConfirmDesc': 'Are you sure you want to delete this derive job? This action cannot be undone.' / '确定要删除此派生任务吗？此操作不可撤销。'
'builds.deriveDeleteSuccess': 'Derive job deleted' / '派生任务已删除'
'builds.deriveDeleteFailed': 'Failed to delete derive job' / '删除派生任务失败'
'builds.deriveDetailTitle': 'Derive Job Detail' / '派生任务详情'
'builds.colTopic': 'Topic' / '主题'
'builds.colSlug': 'Slug' / '标识'
'builds.colSelectFrom': 'Source' / '来源类型'
'builds.selectFromArticles': 'Articles' / '文章'
'builds.selectFromDocuments': 'Documents' / '文档'
'builds.selectFromDefault': 'Engine default' / '引擎默认'

// Tasks tab
'builds.tasksEmpty': 'No tasks found.' / '暂无任务'
'builds.tasksEmptyAction': 'Submit content to get started' / '提交内容以开始'

// Derive dialog (simplified)
'derive.jobStarted': 'Derive job started successfully' / '派生任务已启动'
'derive.viewInBuilds': 'View in Builds' / '在构建页面查看'

// Derive stage labels (for StatusStageBadge)
'deriveStage.queued': 'Queued' / '排队中'
'deriveStage.filter': 'Filtering' / '筛选中'
'deriveStage.compile': 'Compiling' / '编译中'
'deriveStage.done': 'Done' / '已完成'
```

### Phase 8: Test Migration & New Tests

**Step 8.1: Inventory existing Tasks.test.tsx scenarios (593 lines)**

The existing test file covers these scenarios. Each is mapped to its new home:

| Existing test scenario | Destination | Action |
|---|---|---|
| Renders task titles + status badges | `TasksTab.test.tsx` | Port (adapt column structure — no Source column, merged Status/Stage) |
| Filter change calls listTasks with status | `TasksTab.test.tsx` | Port as-is |
| Detail button → getTask → shows result | `TasksTab.test.tsx` + `TaskDetailDialog.test.tsx` | Split: table click → TasksTab, dialog content → TaskDetailDialog |
| Status colour coding (succeeded/failed/cancelled/running/pending) | `StatusStageBadge.test.tsx` | Port to new component (test badge colors) |
| Stage colour coding (done/extract/pipeline/index/queued) | `StatusStageBadge.test.tsx` | Port to new component |
| Unrecognised status/stage fallback | `StatusStageBadge.test.tsx` | Port to new component |
| Date formatting fallback | `TasksTab.test.tsx` | Port as-is (formatDate is shared) |
| Error toast on fetch failure | `TasksTab.test.tsx` | Port as-is |
| Detail fetch failure + optimistic data | `TaskDetailDialog.test.tsx` | Port |
| Failed task shows error in dialog | `TaskDetailDialog.test.tsx` | Port |
| Empty state message | `TasksTab.test.tsx` | Port (update expected text to new empty state) |
| Delete: confirmation dialog | `TasksTab.test.tsx` | Port as-is |
| Delete: confirm → deleteTask → reload | `TasksTab.test.tsx` | Port as-is |
| Delete: API rejection | `TasksTab.test.tsx` | Port as-is |
| Delete: cancel abandons | `TasksTab.test.tsx` | Port as-is |
| Delete: disabled for running tasks | `TasksTab.test.tsx` | Port as-is |
| Delete: page step-back when last item | `TasksTab.test.tsx` | Port as-is |
| Sorting: ascending first click | `TasksTab.test.tsx` | Port (remove Source column test) |
| Sorting: reverse on second click | `TasksTab.test.tsx` | Port |
| Sorting: restart asc on column change | `TasksTab.test.tsx` | Port |
| Search: debounce 300ms | `TasksTab.test.tsx` | Port as-is |
| Search: Enter fires immediately | `TasksTab.test.tsx` | Port as-is |
| Search: other keys ignored | `TasksTab.test.tsx` | Port |
| Pagination: no pager for single page | `TasksTab.test.tsx` | Port as-is |
| Pagination: forward/back | `TasksTab.test.tsx` | Port as-is |
| Pagination: disabled edges | `TasksTab.test.tsx` | Port as-is |
| Pagination: all pages when ≤7 | `TasksTab.test.tsx` | Port as-is |
| Pagination: ellipsis for long range | `TasksTab.test.tsx` | Port as-is |
| File preview from name click | `TasksTab.test.tsx` | Port as-is |
| Error indicator badge | `TasksTab.test.tsx` | Port as-is |

**Obsolete scenarios**: The "Source" sorting test becomes obsolete since the Source column is removed. The source column rendering assertions in the "renders both task titles" test should be updated to not assert Source.

**Step 8.2: Create new test files**

- `web/src/features/builds/__tests__/TasksTab.test.tsx` — Port ~80% of Tasks.test.tsx scenarios (as catalogued above). Update column indices (Source column removed, Status/Stage merged). Mock `listTasks` same as before.

- `web/src/features/builds/__tests__/DeriveJobsTab.test.tsx` — New tests:
  - Renders job rows with topic, slug, status, select_from columns
  - Filter change calls `listDeriveJobs` with status
  - Empty state shows message + link to Wiki
  - Delete confirmation for terminal jobs (succeeded/failed)
  - Delete disabled for pending/running jobs
  - Pagination
  - Search debounce
  - Select From column shows "Articles"/"Documents"/"—" correctly

- `web/src/features/builds/__tests__/StatusStageBadge.test.tsx` — Port colour tests:
  - Each status maps to correct colour class
  - Each stage displayed when status is running/pending
  - Terminal status shows only status text
  - Unknown status/stage falls back gracefully

- `web/src/features/builds/__tests__/TaskDetailDialog.test.tsx` — Port dialog tests:
  - Fetches detail on open
  - Shows result JSON with line numbers
  - Shows error for failed task
  - Shows status badge in dialog
  - Handles fetch failure gracefully

- `web/src/features/builds/__tests__/DeriveJobDetailDialog.test.tsx` — New tests:
  - Fetches job detail on open
  - Shows topic, slug, select_from (human-readable label), cost
  - Shows error for failed job
  - Handles fetch failure

- `web/src/features/builds/__tests__/useAutoPolling.test.ts` — New tests:
  - Calls fetchFn at interval when hasActiveItems is true
  - Does not call fetchFn when hasActiveItems is false
  - Pauses when document.hidden
  - Resumes when document becomes visible
  - Cleans up on unmount

- `web/src/features/builds/__tests__/StatsBar.test.tsx` — New tests:
  - Renders both tab labels
  - Shows active count badge when > 0
  - Hides badge when counts are 0
  - Calls onTabChange when segment clicked
  - Highlights active tab

- `web/src/pages/__tests__/Builds.test.tsx` — Integration tests:
  - Renders TasksTab by default (no tab param)
  - Renders DeriveJobsTab for `/builds/derive`
  - Redirects unknown tab to `/builds/tasks`
  - Stats bar fetches summary counts using `limit=1`
  - Tab switch navigates without remount

**Step 8.3: Delete old files**
- Delete: `web/src/pages/Tasks.tsx`
- Delete: `web/src/pages/Tasks.test.tsx`

### Dependencies Between Steps

```
Phase 1 (backend) ← no dependency, can start immediately
Phase 2 (API client) ← can code against contract (Section 4), parallel with Phase 1
Phase 3 (shared components) ← depends on Phase 2 (types)
Phase 4 (tab components) ← depends on Phase 2 + Phase 3
Phase 5 (page shell + routing) ← depends on Phase 3 + Phase 4
Phase 6 (DeriveDialog simplification) ← depends on Phase 5 (needs /builds/derive route to exist)
Phase 7 (i18n) ← can run in parallel from Phase 2 onward; used by Phases 3-6
Phase 8 (tests + cleanup) ← depends on all above
```

Backend (Phase 1) and Frontend (Phases 2-7) can be developed fully in parallel since the API contract is defined in Section 4.

## 6. Risks and Mitigations

### Risk 1: Route conflict between `/api/derive/jobs` and `/api/derive/{id}`
- **Severity**: Medium
- **Analysis**: Go 1.22 ServeMux static paths always win over wildcards. `GET /api/derive/jobs` (static) beats `GET /api/derive/{id}` (wildcard with id="jobs"). `DELETE /api/derive/jobs/{id}` is more specific than `GET /api/derive/{id}` (different method + more specific path).
- **Mitigation**: Add an explicit integration test (`TestListDeriveJobsRouteDoesNotConflictWithGetById`) that sends `GET /api/derive/jobs` and verifies it returns a list response, not a single-job 404.

### Risk 2: Stats bar polling — 4 extra API calls per tick
- **Severity**: Low
- **Analysis**: Each call is `limit=1` returning ~200 bytes (one row + total). SQLite COUNT(*) with a status WHERE clause hits the `idx_derived_jobs_status_created` index. 4 × 200 bytes every 5s is trivial. Using `limit=1` instead of `limit=0` avoids the SEVERE bug where `limit=0` returns all rows.
- **Mitigation**: Polling only runs when pending+running > 0. When everything is terminal, polling stops entirely. Also pauses when browser tab is hidden.

### Risk 3: Breaking existing bookmarks to `/tasks`
- **Severity**: Low
- **Mitigation**: `<Route path="tasks" element={<Navigate to="/builds/tasks" replace />} />` preserves old URLs. Also `/status` → `/builds/tasks`.

### Risk 4: Tab switch conditionally renders — state lost
- **Severity**: Low
- **Analysis**: Switching from TasksTab to DeriveJobsTab unmounts TasksTab, losing filter/sort/page state. This matches the current UX (navigating away from Tasks and back resets state).
- **Mitigation**: Acceptable for v1. Future optimization: keep both mounted with `display:none`/`display:block`, but this adds complexity for marginal benefit.

### Risk 5: KBSelector `reloadKey` prop removal
- **Severity**: Low
- **Analysis**: `KBSelector` declares `reloadKey` as optional with `reloadKey?: number` and default `reloadKey = 0`. Removing it from the call site is safe — the component continues to fetch on mount.
- **Mitigation**: None needed. The component's interface already handles the absence of this prop.

### Risk 6: Existing test migration effort
- **Severity**: Medium
- **Analysis**: 593 lines of tests need to be reorganized into 7+ new test files. Risk of missing coverage during migration.
- **Mitigation**: Step 8.1 provides an explicit inventory mapping every existing test to its new home. Run `vitest --coverage` before and after migration to verify no coverage regression. The old test file is deleted only after all new tests pass.

### Risk 7: `model` and `select_from` field addition to `deriveJobResponse`
- **Severity**: Very Low
- **Analysis**: Adding new fields to a JSON response is backward-compatible. No consumer rejects unknown fields. The existing `DeriveDialog` polling code in `handleGetDeriveJob` does not use `model` or `select_from` fields.
- **Mitigation**: None needed.

### Risk 8: TOCTOU race in `handleDeleteDeriveJob`
- **Severity**: Low
- **Analysis**: Between `GetDerivedJob` and `DeleteDerivedJob`, another request could delete the same job. The previous plan returned 409 for this case, which is misleading (implies the job still exists but in a conflicting state).
- **Mitigation**: Return 404 instead of 409 for the TOCTOU fallback. This correctly communicates "the job is gone." From the client's perspective, this is idempotent: the job they wanted to delete is already deleted.
