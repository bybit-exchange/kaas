# Builds Page Refactor: Build Jobs Entity + Tab Rename (Revision 2)

## 1. Background and Goals

### Why
The Builds page currently has an asymmetry: the Derive tab lists **job records** (clicking opens a detail sheet), while the Normal tab lists **individual tasks** directly. The product requires both tabs to behave the same way: list build job records at the top level, with a click-to-open sheet showing the tasks belonging to that job.

Additionally, the tab labels need renaming from "Normal Tasks" / "Derive Jobs" to "Normal" / "Derive Topic".

### What We Want to Achieve
1. **Rename tabs**: "Normal Tasks" → "Normal", "Derive Jobs" → "Derive Topic"
2. **New `build_jobs` backend entity** (Option A): A `build_jobs` table that groups tasks by submission. Both `POST /api/submit` and `POST /api/submit/files` create a `BuildJob` row, and each task links to it via `build_job_id` FK.
3. **Normal tab shows build jobs**: Lists `BuildJob` records (source, title, status, task count, timestamps). Clicking a row opens a Sheet showing the tasks belonging to that job.
4. **New API endpoints**: List build jobs, get build job (with its tasks), delete build job.
5. **New `partial` status**: Build jobs can have a "partial" status (mix of succeeded and failed tasks).

### In Scope
- New `build_jobs` DB table + migration
- New `BuildJob` model in `internal/store/store.go`
- New `BuildJobStore` interface + SQLite implementation
- New API endpoints for build jobs (list, get, delete)
- Modified submit endpoints to create build jobs
- New frontend API client (`web/src/api/buildJobs.ts`)
- Refactored Normal tab component (`BuildJobsTab`) replacing `TasksTab`
- New `BuildJobDetailSheet` component showing tasks list
- Tab label + i18n changes
- `StatusStageBadge` updates to support `partial` status and optional `stage`
- Test updates for all affected components

### Out of Scope
- Retroactive migration of existing tasks (they will have `build_job_id = ""` and won't appear in the Normal tab's job list; acceptable for an early-stage product)
- Changes to the Derive tab's internal logic
- Changes to the task queue/worker system

## 2. Current State Analysis

### Backend
- **Task model** (`internal/store/store.go`): Has no `build_job_id` or grouping field. Tasks are created individually.
- **Submit endpoints**:
  - `POST /api/submit` (`internal/api/submit.go`): Creates 1 task per request via `s.q.Submit()`.
  - `POST /api/submit/files` (`internal/api/submit_files.go`): Creates N tasks (1 per file) via `s.q.Submit()` in a loop. No shared batch concept.
- **DerivedJob model**: Good reference pattern — has its own table, CRUD endpoints, status lifecycle.
- **Queue** (`internal/queue/queue.go`): `Submit()` stamps `status=pending`, `stage=queued`, timestamps on a `*store.Task`, then calls `store.CreateTask()`.
- **taskDTO** (`internal/api/tasks.go`): Uses `omitempty` for `error`, `result`, `title`, `file_title` — fields are absent from JSON when empty.
- **Server.NewServer** detects `DerivedJobStore` via type assertion: `if js, ok := st.(store.DerivedJobStore); ok { s.js = js }`. The same pattern applies for `BuildJobStore`.

### Frontend
- **TasksTab** (`web/src/features/builds/TasksTab.tsx`): Flat list of individual tasks. Row click → `TaskDetailSheet` (single task detail). Filename click → `FilePreviewSheet`.
- **DeriveJobsTab** (`web/src/features/builds/DeriveJobsTab.tsx`): List of derive jobs. Row click → fetch full detail → `DeriveJobDetailSheet`.
- **StatusStageBadge**: Takes `status: string` and `stage: string` (both required). Shows "Running · Extracting" for non-terminal, "Succeeded" for terminal. Has `statusColor()` mapping for `succeeded`, `failed`, `cancelled`, `running`, `pending` — **no `partial` case**.
- **Builds.tsx**: Routes between tabs, fetches stats with 4 API calls.
- **StatsBar.tsx**: Tab labels from i18n keys `builds.tabTasks` and `builds.tabDerive`.
- **i18n**: `status.filter.*` exists for `all`, `pending`, `running`, `succeeded`, `failed`, `cancelled` — **no `partial` key**.

### Constraints
- SQLite single-writer model — all writes serialized through 1 connection.
- The `Queue.Submit()` method is the only path for task creation. The `BuildJob` creation must happen in the API handler **before** calling `q.Submit()`.
- Foreign key enforcement is already enabled (`_pragma=foreign_keys(ON)` in the DSN).
- Existing tasks in production DBs have no `build_job_id` — the column default must be `''` (empty string) rather than a real FK constraint.

## 3. Technical Design

### 3.1 Database Schema

**New table: `build_jobs`**

```sql
CREATE TABLE IF NOT EXISTS build_jobs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,      -- "paste" | "file" | "url"
    title       TEXT NOT NULL DEFAULT '',
    file_count  INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,       -- "pending" | "running" | "succeeded" | "failed" | "partial"
    error       TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_build_jobs_status_created ON build_jobs(status, created_at);
```

**Alter `tasks` table**: Add `build_job_id` column.

```sql
ALTER TABLE tasks ADD COLUMN build_job_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_tasks_build_job_id ON tasks(build_job_id);
```

**Initial CREATE TABLE** (for fresh databases): Add `build_job_id TEXT NOT NULL DEFAULT ''` to the `tasks` schema constant, between `updated_at` and the closing `)`. Also add the `idx_tasks_build_job_id` index to the schema constant.

Note: `build_job_id` defaults to `''` (not a hard FK) so existing rows are unaffected. New tasks always have a non-empty `build_job_id`.

### 3.2 BuildJob Status Lifecycle

A BuildJob's status is **derived** from its tasks' statuses. The `status` column in the `build_jobs` table is written at creation time (`pending`) and **refreshed lazily** when the API queries build jobs.

**Status computation rules (from child tasks)**:
- Any task `running` → `"running"`
- Any task `pending` (and none running) → `"pending"`
- All tasks `succeeded` → `"succeeded"`
- All tasks in terminal states (`failed` / `cancelled`) with none succeeded → `"failed"`
- Mix of `succeeded` and `failed`/`cancelled` (none pending/running) → `"partial"`

**Refresh strategy**: `RefreshBuildJobStatuses(ctx, now)` runs a single UPDATE...FROM subquery that recomputes status for all non-terminal build jobs (`WHERE status IN ('pending', 'running')`). This is called once before `ListBuildJobsPaged` returns. For `GetBuildJob`, the handler refreshes just the one job's status.

**Performance note (addressing N+1 risk)**: The refresh uses a single CTE/batch UPDATE rather than per-job queries:

```sql
WITH job_status AS (
    SELECT
        t.build_job_id,
        CASE
            WHEN SUM(CASE WHEN t.status = 'running' THEN 1 ELSE 0 END) > 0 THEN 'running'
            WHEN SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) > 0 THEN 'pending'
            WHEN COUNT(*) = SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) THEN 'succeeded'
            WHEN SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) > 0 THEN 'partial'
            ELSE 'failed'
        END AS computed_status
    FROM tasks t
    WHERE t.build_job_id IN (
        SELECT id FROM build_jobs WHERE status IN ('pending', 'running')
    )
    GROUP BY t.build_job_id
)
UPDATE build_jobs
SET status = js.computed_status, updated_at = ?
FROM job_status js
WHERE build_jobs.id = js.build_job_id
  AND build_jobs.status != js.computed_status;
```

This is one statement, no N+1.

### 3.3 BuildJob Model

```go
// BuildJob groups one or more tasks from a single submission.
type BuildJob struct {
    ID        string // UUID
    Source    string // "paste" | "file" | "url"
    Title     string // for paste/url: user title; for files: ZIP filename or first filename; for multi: "N files"
    FileCount int    // number of tasks in this job
    Status    string // pending | running | succeeded | failed | partial
    Error     string // aggregated error summary (empty if no failures)
    CreatedAt int64  // unix ms
    UpdatedAt int64  // unix ms
}
```

**New status constant**:
```go
const StatusPartial = "partial"
```

### 3.4 Task model change

Add `BuildJobID` field to the existing `Task` struct:

```go
type Task struct {
    // ... existing fields ...
    BuildJobID string // FK to build_jobs.id; "" for legacy tasks
}
```

### 3.5 taskColumns and scanTask changes

In `internal/store/sqlite/sqlite.go`:

- Append `build_job_id` to the end of `taskColumns`:
  ```go
  const taskColumns = `id, source, title, raw_path, file_title, content_hash, status, stage,
      attempts, max_attempts, error, result, lease_owner, lease_expires_at,
      created_at, updated_at, build_job_id`
  ```

- Add `&t.BuildJobID` as the **last** field in `scanTask`:
  ```go
  func scanTask(row rowScanner) (*store.Task, error) {
      var t store.Task
      err := row.Scan(
          &t.ID, &t.Source, &t.Title, &t.RawPath, &t.FileTitle, &t.ContentHash, &t.Status, &t.Stage,
          &t.Attempts, &t.MaxAttempts, &t.Error, &t.Result, &t.LeaseOwner,
          &t.LeaseExpiresAt, &t.CreatedAt, &t.UpdatedAt, &t.BuildJobID,
      )
      if err != nil {
          return nil, err
      }
      return &t, nil
  }
  ```

- Update `CreateTask` to pass 17 values (add `t.BuildJobID` at the end matching column order).

### 3.6 taskDTO change: add `build_job_id`

In `internal/api/tasks.go`, add `build_job_id` to `taskDTO`:

```go
type taskDTO struct {
    ID          string          `json:"id"`
    BuildJobID  string          `json:"build_job_id,omitempty"`
    Source      string          `json:"source"`
    Title       string          `json:"title,omitempty"`
    FileTitle   string          `json:"file_title,omitempty"`
    Status      string          `json:"status"`
    Stage       string          `json:"stage"`
    Attempts    int             `json:"attempts"`
    MaxAttempts int             `json:"max_attempts"`
    Error       string          `json:"error,omitempty"`
    Result      json.RawMessage `json:"result,omitempty"`
    CreatedAt   int64           `json:"created_at"`
    UpdatedAt   int64           `json:"updated_at"`
}
```

Update `toDTO()` to set `d.BuildJobID = t.BuildJobID`.

Note: `build_job_id` uses `omitempty` — legacy tasks (with `BuildJobID = ""`) will not include this field in the response, maintaining backward compatibility.

### 3.7 API Endpoint Design

| Method | Path | Purpose |
|--------|------|---------|
| `GET /api/build-jobs` | List build jobs (paged, filtered, sorted) |
| `GET /api/build-jobs/{id}` | Get build job detail + its tasks |
| `DELETE /api/build-jobs/{id}` | Delete a terminal build job + its tasks |

### 3.8 Submit Endpoint Changes

**`POST /api/submit`** (single task):
1. Create a `BuildJob` (source, title, file_count=1). If `CreateBuildJob` fails, return 500 immediately.
2. Create the `Task` with `build_job_id = buildJob.ID`.
3. If `q.Submit()` fails, also clean up the build job (best-effort `DeleteBuildJob`).
4. Response unchanged (backward compatible).

**`POST /api/submit/files`** (multi-file):
1. Create a `BuildJob` before the file loop. If `CreateBuildJob` fails, return 500 immediately.
   - For regular files: source="file", title = first filename, file_count = len(files)
   - For ZIP uploads: source="file", title = ZIP filename, file_count = 0 (updated after extraction)
2. Pass `buildJobID string` as a new parameter to `processFile` and `commitFiles`.
3. Inside `processFile`, set `task.BuildJobID = buildJobID` before calling `s.q.Submit()`.
4. Inside `commitFiles`, set `task.BuildJobID = buildJobID` before calling `s.q.Submit()`.
5. After processing all files, update file_count to actual count:
   ```go
   actualCount := len(resp.Uploaded)
   if actualCount == 0 {
       // All files failed — delete the empty build job
       s.bjs.DeleteBuildJob(ctx, buildJob.ID)
   } else {
       s.bjs.UpdateBuildJobFileCount(ctx, buildJob.ID, actualCount, now)
   }
   ```
6. Response unchanged (backward compatible).

**Updated function signatures**:

```go
// processFile — add buildJobID parameter
func (s *Server) processFile(r *http.Request, name string, ext string, content []byte, resp *submitFilesResponse, buildJobID string)

// commitFiles — add buildJobID parameter
func (s *Server) commitFiles(ctx context.Context, files []preparedFile, buildJobID string) ([]submitFilesItem, *submitFilesItem)

// processZip — add buildJobID parameter (passes through to commitFiles)
func (s *Server) processZip(r *http.Request, data []byte, zipName string, resp *submitFilesResponse, buildJobID string)
```

Inside `processFile`, before `s.q.Submit()`:
```go
task.BuildJobID = buildJobID
```

Inside `commitFiles`, in the enqueue loop, before `s.q.Submit()`:
```go
task.BuildJobID = buildJobID
```

**ZIP title heuristic**: For ZIP uploads, `title` = ZIP filename (e.g., "docs.zip"). `file_count` starts at 0, and is updated to the actual number of successfully created tasks after the ZIP is fully processed.

### 3.9 Frontend Architecture

**New/Modified Components**:

| Component | Action |
|-----------|--------|
| `web/src/api/buildJobs.ts` | **New**: API client for build jobs |
| `web/src/features/builds/BuildJobsTab.tsx` | **New**: Replaces `TasksTab`, lists build jobs |
| `web/src/features/builds/BuildJobDetailSheet.tsx` | **New**: Sheet showing tasks list for a build job |
| `web/src/features/builds/TasksTab.tsx` | **Remove** (replaced by BuildJobsTab) |
| `web/src/features/builds/TaskDetailSheet.tsx` | **Keep** (reused inside BuildJobDetailSheet for task detail) |
| `web/src/features/builds/StatusStageBadge.tsx` | **Modify**: Support `partial` status, make `stage` optional |
| `web/src/pages/Builds.tsx` | **Modify**: Use BuildJobsTab instead of TasksTab, update stats |
| `web/src/features/builds/StatsBar.tsx` | **Modify**: Only i18n label keys change |
| `web/src/features/builds/types.ts` | **Modify**: Keep same tab keys |
| `web/src/i18n/strings.ts` | **Modify**: Add new keys, rename tab labels, add `partial` |

### 3.10 StatusStageBadge Changes (addressing SEVERE #1, #3)

Make `stage` prop **optional**. When `stage` is empty/undefined, show only the status label without the separator dot. Add `partial` status color and i18n key.

Updated component:

```tsx
export interface StatusStageBadgeProps {
  status: string
  stage?: string  // optional — build jobs don't have stages
  className?: string
}

export function statusColor(status: string): string {
  switch (status) {
    // ... existing cases ...
    case 'partial':
      return 'border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-400'
    default:
      return ''
  }
}

export function StatusStageBadge({ status, stage, className }: StatusStageBadgeProps) {
  const t = useT()
  const color = statusColor(status)
  const sLabel = statusLabel(t, status)

  let text: string
  if (TERMINAL_STATUSES.has(status) || !stage) {
    // Terminal statuses, partial status, or no stage: show status only
    text = sLabel
  } else {
    const sgLabel = stageLabel(t, stage)
    text = `${sLabel} · ${sgLabel}`
  }

  return (
    <Badge variant="outline" className={cn(color, className)}>
      {text}
    </Badge>
  )
}
```

Add `'partial'` to `TERMINAL_STATUSES`:
```tsx
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'partial'])
```

### 3.11 Stats Bar Changes

Replace `listTasks` calls with `listBuildJobs` calls for the Normal tab:
- `listBuildJobs({ status: 'pending', limit: 1 })` for pending count
- `listBuildJobs({ status: 'running', limit: 1 })` for running count

### 3.12 ListTasksByBuildJob on TaskStore (addressing MEDIUM #2)

`ListTasksByBuildJob` belongs on the `Store` interface (which `TaskStore` wraps for the API) rather than on `BuildJobStore`, because it queries the `tasks` table. However, to avoid modifying the existing `Store` interface (which is the full queue interface), we add it to a new method on `TaskStore` in the API layer — or more practically, we add it directly to the `BuildJobStore` interface since the concrete `sqlite.Store` implements both `Store` and `BuildJobStore`, and the API layer receives both.

**Decision**: Add `ListTasksByBuildJob` as a method on `Store` (the main task store interface) since it queries tasks:

```go
// In internal/store/store.go, add to Store interface:
// ListTasksByBuildJob returns all tasks belonging to a build job, ordered by created_at ASC.
ListTasksByBuildJob(ctx context.Context, buildJobID string) ([]*Task, error)
```

Then in the API layer, `TaskStore` (which is the interface the Server uses for task reads) also gains this method:

```go
// In internal/api/server.go, update TaskStore:
type TaskStore interface {
    GetTask(ctx context.Context, id string) (*store.Task, error)
    ListTasks(ctx context.Context, f store.ListFilter) ([]*store.Task, error)
    ListTasksPaged(ctx context.Context, f store.PagedListFilter) (*store.ListResult, error)
    DeleteTask(ctx context.Context, id string) error
    ListTasksByBuildJob(ctx context.Context, buildJobID string) ([]*store.Task, error)
}
```

This is consistent with the pattern: task queries live on the task store.

## 4. Interface Contracts

### 4.1 Endpoint: GET /api/build-jobs

**Query Parameters**:
| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `status` | string | (none) | Exact match: `pending`, `running`, `succeeded`, `failed`, `partial` |
| `q` | string | (none) | LIKE match on `title` |
| `sort` | string | `created_at` | Allowed: `title`, `source`, `status`, `file_count`, `created_at`, `updated_at` |
| `order` | string | `desc` | `asc` or `desc` |
| `limit` | int | `20` | Page size |
| `offset` | int | `0` | Pagination offset |

**Response (200)**:
```json
{
  "jobs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "source": "file",
      "title": "docs.zip",
      "file_count": 5,
      "status": "running",
      "created_at": 1718000000000,
      "updated_at": 1718000000000
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "source": "paste",
      "title": "My notes",
      "file_count": 1,
      "status": "failed",
      "error": "1 of 1 tasks failed",
      "created_at": 1718000000000,
      "updated_at": 1718000000000
    }
  ],
  "total": 42
}
```

**Error Responses**: 500 (internal error)

**Backend model** (Go):
```go
type buildJobDTO struct {
    ID        string `json:"id"`
    Source    string `json:"source"`
    Title     string `json:"title"`
    FileCount int    `json:"file_count"`
    Status    string `json:"status"`
    Error     string `json:"error,omitempty"`
    CreatedAt int64  `json:"created_at"`
    UpdatedAt int64  `json:"updated_at"`
}
```

- `error` uses `omitempty`: the field is **absent** from JSON when the build job has no error (empty string in DB). It is **present** only when non-empty.
- `file_count` is always ≥ 1 (or 0 only transiently during ZIP processing before the count is updated).
- `jobs` is always a non-null array (empty array `[]` when no results).
- The handler calls `RefreshBuildJobStatuses(ctx, now)` (single CTE-based UPDATE) before the main SELECT.

**Frontend model** (TypeScript):
```typescript
export interface BuildJobDTO {
  id: string
  source: string
  title: string
  file_count: number
  status: string  // "pending" | "running" | "succeeded" | "failed" | "partial"
  error?: string  // undefined when omitted by backend omitempty
  created_at: number
  updated_at: number
}
```

- `error` is typed as optional (`?`) because the backend uses `omitempty`. When no error exists, the field is absent from the JSON, so TypeScript sees `undefined`.

---

### 4.2 Endpoint: GET /api/build-jobs/{id}

Returns the build job detail **including its tasks array**.

**Response (200)**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "file",
  "title": "docs.zip",
  "file_count": 5,
  "status": "partial",
  "error": "2 of 5 tasks failed",
  "created_at": 1718000000000,
  "updated_at": 1718000000000,
  "tasks": [
    {
      "id": "aaa-111",
      "build_job_id": "550e8400-e29b-41d4-a716-446655440000",
      "source": "file",
      "title": "readme.md",
      "file_title": "README",
      "status": "succeeded",
      "stage": "done",
      "attempts": 1,
      "max_attempts": 3,
      "created_at": 1718000000000,
      "updated_at": 1718000000000
    },
    {
      "id": "bbb-222",
      "build_job_id": "550e8400-e29b-41d4-a716-446655440000",
      "source": "file",
      "title": "notes.md",
      "file_title": "Notes",
      "status": "failed",
      "stage": "done",
      "attempts": 3,
      "max_attempts": 3,
      "error": "LLM timeout",
      "created_at": 1718000000000,
      "updated_at": 1718000000000
    }
  ]
}
```

**Error Responses**: 404 (not found) / 500 (internal error)

**Backend model** (Go):
```go
type buildJobDetailDTO struct {
    ID        string    `json:"id"`
    Source    string    `json:"source"`
    Title     string    `json:"title"`
    FileCount int       `json:"file_count"`
    Status    string    `json:"status"`
    Error     string    `json:"error,omitempty"`
    CreatedAt int64     `json:"created_at"`
    UpdatedAt int64     `json:"updated_at"`
    Tasks     []taskDTO `json:"tasks"`
}
```

- `tasks` is always a non-null array. The tasks are the same `taskDTO` shape used by `GET /api/tasks/{id}`, reusing the existing `toDTO()` function.
- `error` field on `buildJobDetailDTO`: uses `omitempty`, **absent** from JSON when empty. See first example in 4.1 (no error field when status is "running").
- `error` and `result` fields **inside each task**: follow the same `omitempty` rules as the existing `taskDTO`. The `error` field is absent when the task has no error; `result` is absent when empty or invalid JSON.
- `build_job_id` is present on each task (omitted only for legacy tasks with empty string, per `omitempty`).
- The handler fetches the build job, refreshes its status, then queries all tasks with `build_job_id = id` via `ListTasksByBuildJob`, orders by `created_at ASC`.

**Frontend model** (TypeScript):
```typescript
import type { TaskDTO } from './tasks'

export interface BuildJobDetailDTO {
  id: string
  source: string
  title: string
  file_count: number
  status: string
  error?: string  // absent when no error (omitempty)
  created_at: number
  updated_at: number
  tasks: TaskDTO[]
}
```

- `tasks` array reuses the existing `TaskDTO` type from `web/src/api/tasks.ts`.
- `tasks` is always present and is an array (never null/undefined).

**TaskDTO update** (add `build_job_id`):
```typescript
export interface TaskDTO {
  id: string
  build_job_id?: string  // absent for legacy tasks (omitempty)
  source: string
  title: string
  file_title?: string
  status: string
  stage: string
  attempts: number
  max_attempts: number
  error?: string
  result?: unknown
  created_at: number
  updated_at: number
}
```

---

### 4.3 Endpoint: DELETE /api/build-jobs/{id}

Deletes a build job and all its tasks. Only terminal build jobs can be deleted.

**Response (204)**: No body.

**Error Responses**:
- 404: `{"error": "build job not found"}`
- 409: `{"error": "build job is still active"}` — returned when the build job's **refreshed** status is `pending` or `running`
- 500: `{"error": "..."}`

**Backend behavior**:
1. Fetch the build job by ID → 404 if not found.
2. Refresh this build job's status from its child tasks (single-row status recompute, not the batch refresh).
3. If refreshed status is `pending` or `running` → 409 with message `"build job is still active"`.
4. Delete all tasks belonging to this build job (also remove their raw files, best-effort, log failures).
5. Delete the build job row.
6. Return 204.

The 409 check is against the **build job's computed status** (not individual task statuses). The handler first refreshes the cached status, then checks the refreshed value.

**Deletable statuses**: `succeeded`, `failed`, `partial` (all are terminal for build jobs).

**Frontend**: `deleteBuildJob(id: string): Promise<void>` — same pattern as `deleteDeriveJob`.

---

### 4.4 Modified Endpoint: POST /api/submit (backward compatible)

**Request Body** (unchanged):
```json
{
  "source": "string (required: paste|file|url)",
  "title": "string (optional)",
  "content": "string (required for paste/file)",
  "url": "string (required for url source)"
}
```

**Response (202)** (unchanged):
```json
{
  "id": "string (task UUID)",
  "status": "string",
  "stage": "string"
}
```

**Backend change** (in `handleSubmit`):

```go
// Create build job FIRST. If this fails, return 500 immediately.
now := time.Now().UnixMilli()
buildJob := &store.BuildJob{
    ID:        uuid.NewString(),
    Source:    req.Source,
    Title:     title,
    FileCount: 1,
    Status:    store.StatusPending,
    CreatedAt: now,
    UpdatedAt: now,
}
if err := s.bjs.CreateBuildJob(r.Context(), buildJob); err != nil {
    writeErr(w, http.StatusInternalServerError, "create build job: "+err.Error())
    return
}

task.BuildJobID = buildJob.ID

// If q.Submit() fails, clean up the build job (best-effort):
if err := s.q.Submit(r.Context(), task); err != nil {
    _ = os.Remove(rawPath)
    _ = s.bjs.DeleteBuildJob(r.Context(), buildJob.ID) // best-effort cleanup
    // ... existing error handling ...
}
```

---

### 4.5 Modified Endpoint: POST /api/submit/files (backward compatible)

**Request**: Multipart form (unchanged).

**Response (202)** (unchanged):
```json
{
  "uploaded": [{ "name": "string", "id": "string", "status": "uploaded" }],
  "failed": [{ "name": "string", "status": "failed", "reason": "string" }]
}
```

**Backend change** (in `handleSubmitFiles`):

```go
// Create build job FIRST. If this fails, return 500 immediately.
now := time.Now().UnixMilli()
buildJob := &store.BuildJob{
    ID:        uuid.NewString(),
    Source:    "file",
    Title:     files[0].Filename,   // for single/multi files: first filename
    FileCount: len(files),
    Status:    store.StatusPending,
    CreatedAt: now,
    UpdatedAt: now,
}
if err := s.bjs.CreateBuildJob(r.Context(), buildJob); err != nil {
    writeErr(w, http.StatusInternalServerError, "create build job: "+err.Error())
    return
}

// Pass buildJob.ID to processFile/processZip
for _, fh := range files {
    // ... existing validation ...
    if ext == ".zip" {
        s.processZip(r, data, fh.Filename, &resp, buildJob.ID)
    } else {
        s.processFile(r, fh.Filename, ext, data, &resp, buildJob.ID)
    }
}

// After processing, update file_count or clean up
actualCount := len(resp.Uploaded)
now = time.Now().UnixMilli()
if actualCount == 0 {
    _ = s.bjs.DeleteBuildJob(r.Context(), buildJob.ID)
} else {
    _ = s.bjs.UpdateBuildJobFileCount(r.Context(), buildJob.ID, actualCount, now)
}
```

**ZIP title handling**: For ZIP files, since the `processZip` call happens inside the file loop, the initial `Title` is `files[0].Filename` which will be the ZIP filename if a ZIP is the first (or only) file. If multiple files are uploaded with a ZIP among them, the title is the first file's name. The `file_count` is corrected after processing.

### 4.6 Store Interface: `BuildJobStore`

```go
// BuildJobStore persists build jobs.
type BuildJobStore interface {
    CreateBuildJob(ctx context.Context, j *BuildJob) error
    GetBuildJob(ctx context.Context, id string) (*BuildJob, error)
    ListBuildJobsPaged(ctx context.Context, f BuildJobListFilter) (*BuildJobListResult, error)
    DeleteBuildJob(ctx context.Context, id string) error
    UpdateBuildJobFileCount(ctx context.Context, id string, count int, now int64) error
    // RefreshBuildJobStatuses recomputes status for all non-terminal build jobs
    // from their child tasks using a single CTE-based UPDATE.
    RefreshBuildJobStatuses(ctx context.Context, now int64) error
    // RefreshBuildJobStatus recomputes status for a single build job.
    RefreshBuildJobStatus(ctx context.Context, id string, now int64) error
}
```

```go
type BuildJobListFilter struct {
    Status  string
    Query   string
    SortBy  string
    SortDir string
    Limit   int
    Offset  int
}

type BuildJobListResult struct {
    Jobs  []*BuildJob
    Total int
}
```

**`UpdateBuildJobFileCount` code sketch** (4 args matching interface):
```go
func (s *Store) UpdateBuildJobFileCount(ctx context.Context, id string, count int, now int64) error {
    const q = `UPDATE build_jobs SET file_count = ?, updated_at = ? WHERE id = ?`
    res, err := s.db.ExecContext(ctx, q, count, now, id)
    if err != nil {
        return fmt.Errorf("update build job file count: %w", err)
    }
    return requireOneRow(res, "update build job file count")
}
```

### 4.7 Frontend API Client: `web/src/api/buildJobs.ts`

```typescript
import { apiFetch } from './client'
import type { TaskDTO } from './tasks'

export interface BuildJobDTO {
  id: string
  source: string
  title: string
  file_count: number
  status: string
  error?: string
  created_at: number
  updated_at: number
}

export interface BuildJobDetailDTO extends BuildJobDTO {
  tasks: TaskDTO[]
}

export interface ListBuildJobsParams {
  status?: string
  q?: string
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

export interface ListBuildJobsResponse {
  jobs: BuildJobDTO[]
  total: number
}

export async function listBuildJobs(p?: ListBuildJobsParams): Promise<ListBuildJobsResponse> {
  const qs = new URLSearchParams()
  if (p?.status !== undefined) qs.set('status', p.status)
  if (p?.q !== undefined) qs.set('q', p.q)
  if (p?.sort) qs.set('sort', p.sort)
  if (p?.order) qs.set('order', p.order)
  qs.set('limit', String(p?.limit ?? 20))
  if (p?.offset !== undefined) qs.set('offset', String(p.offset))
  const str = qs.toString()
  const path = str ? `/build-jobs?${str}` : '/build-jobs'
  const res = await apiFetch(path)
  return res.json() as Promise<ListBuildJobsResponse>
}

export async function getBuildJob(id: string, signal?: AbortSignal): Promise<BuildJobDetailDTO> {
  const res = await apiFetch(`/build-jobs/${encodeURIComponent(id)}`, { signal })
  return res.json() as Promise<BuildJobDetailDTO>
}

export async function deleteBuildJob(id: string): Promise<void> {
  await apiFetch(`/build-jobs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
```

### 4.8 BuildJobsTab STATUS_FILTERS

The `BuildJobsTab` component includes `partial` in its status filter dropdown:

```typescript
const STATUS_FILTERS = ['all', 'pending', 'running', 'succeeded', 'failed', 'partial'] as const
```

And the `DELETABLE_STATUSES` set includes `partial`:

```typescript
const DELETABLE_STATUSES = new Set(['succeeded', 'failed', 'partial'])
```

## 5. Implementation Steps

### Phase 1: Backend — Data Model & Store (no API changes yet)

**Step 1.1: Add BuildJob model to store**
- File: `internal/store/store.go`
- Add `StatusPartial = "partial"` constant
- Add `BuildJob` struct with fields: `ID`, `Source`, `Title`, `FileCount`, `Status`, `Error`, `CreatedAt`, `UpdatedAt`
- Add `BuildJobListFilter`, `BuildJobListResult` structs
- Add `BuildJobStore` interface with: `CreateBuildJob`, `GetBuildJob`, `ListBuildJobsPaged`, `DeleteBuildJob`, `UpdateBuildJobFileCount`, `RefreshBuildJobStatuses`, `RefreshBuildJobStatus`
- Add `BuildJobID string` field to `Task` struct (after `UpdatedAt`)
- Add `ListTasksByBuildJob(ctx context.Context, buildJobID string) ([]*Task, error)` to `Store` interface

**Step 1.2: Implement SQLite build_jobs table**
- File: `internal/store/sqlite/build_jobs.go` (new)
- Define `buildJobSchema` constant with CREATE TABLE + indexes
- Define `buildJobColumns` and `scanBuildJob` helper
- Implement all `BuildJobStore` methods:
  - `CreateBuildJob`: INSERT
  - `GetBuildJob`: SELECT by ID, return ErrNotFound if missing
  - `ListBuildJobsPaged`: SELECT with WHERE/LIKE/ORDER BY/LIMIT, plus COUNT query
  - `DeleteBuildJob`: DELETE WHERE id = ?
  - `UpdateBuildJobFileCount(ctx, id, count, now)`: UPDATE file_count and updated_at
  - `RefreshBuildJobStatuses(ctx, now)`: Single CTE-based UPDATE (see §3.2)
  - `RefreshBuildJobStatus(ctx, id, now)`: Single-row version for GetBuildJob/DeleteBuildJob
- Implement `ListTasksByBuildJob`: `SELECT <taskColumns> FROM tasks WHERE build_job_id = ? ORDER BY created_at ASC`

**Step 1.3: Migrate tasks table**
- File: `internal/store/sqlite/sqlite.go`
- Add `build_job_id TEXT NOT NULL DEFAULT ''` to the initial `CREATE TABLE` schema constant (after `updated_at`), for fresh databases
- Add `CREATE INDEX IF NOT EXISTS idx_tasks_build_job_id ON tasks(build_job_id)` to the schema constant
- Update `taskColumns` constant: append `, build_job_id` at the end
- Update `scanTask` function: add `&t.BuildJobID` as the last Scan field
- Update `CreateTask`: add `t.BuildJobID` as the 17th parameter
- Add migration in `Migrate()`:
  ```go
  if err := s.migrateBuildJobID(ctx); err != nil {
      return err
  }
  if _, err := s.db.ExecContext(ctx, buildJobSchema); err != nil {
      return fmt.Errorf("migrate build_jobs schema: %w", err)
  }
  ```
  Where `migrateBuildJobID` uses `addColumnIfMissing(ctx, "build_job_id", "tasks", "build_job_id", "TEXT NOT NULL DEFAULT ''")`.
  Also add `CREATE INDEX IF NOT EXISTS idx_tasks_build_job_id ON tasks(build_job_id)` inside `migrateBuildJobID` (or as part of the build_jobs schema execution block, since it's idempotent).

**Step 1.4: Wire BuildJobStore in sqlite.Store**
- File: `internal/store/sqlite/sqlite.go`
- Add `var _ store.BuildJobStore = (*Store)(nil)` compile-time check

**Step 1.5: Write store-level tests**
- File: `internal/store/sqlite/build_jobs_test.go` (new)
- Test CRUD operations, status refresh (CTE query), list with filters, task listing by build_job_id

*Depends on: nothing*

### Phase 2: Backend — API Endpoints

**Step 2.1: Add build job handlers**
- File: `internal/api/build_jobs.go` (new)
- Define `buildJobDTO` and `buildJobDetailDTO` structs (see §4.1, §4.2)
- Define `toBuildJobDTO(j *store.BuildJob) buildJobDTO` helper
- `handleListBuildJobs`:
  1. Parse query params (status, q, sort, order, limit, offset)
  2. Call `s.bjs.RefreshBuildJobStatuses(ctx, now)` — single CTE update
  3. Call `s.bjs.ListBuildJobsPaged(ctx, filter)`
  4. Convert to DTOs, return `{ "jobs": [...], "total": N }`
- `handleGetBuildJob`:
  1. Get job by ID → 404 if not found
  2. Call `s.bjs.RefreshBuildJobStatus(ctx, id, now)` — single-row refresh
  3. Re-fetch the job (status may have changed)
  4. Call `s.st.ListTasksByBuildJob(ctx, id)` — returns tasks ordered by created_at ASC
  5. Convert to `buildJobDetailDTO`, return
- `handleDeleteBuildJob`:
  1. Get job by ID → 404 if not found
  2. Call `s.bjs.RefreshBuildJobStatus(ctx, id, now)` — single-row refresh
  3. Re-fetch the job to get refreshed status
  4. If status is `"pending"` or `"running"` → 409 with `"build job is still active"`
  5. Fetch all tasks via `s.st.ListTasksByBuildJob(ctx, id)`
  6. For each task, best-effort remove raw file (`os.Remove`, log failures)
  7. For each task, `s.st.DeleteTask(ctx, task.ID)` (already terminal — the job is terminal)
  8. `s.bjs.DeleteBuildJob(ctx, id)`
  9. Return 204

**Step 2.2: Register routes**
- File: `internal/api/server.go`
- Add `bjs store.BuildJobStore` field to `Server` struct
- In `NewServer`, detect `BuildJobStore`:
  ```go
  if bjs, ok := st.(store.BuildJobStore); ok {
      s.bjs = bjs
  }
  ```
- In `routes()`, register:
  ```go
  mux.HandleFunc("GET /api/build-jobs", s.handleListBuildJobs)
  mux.HandleFunc("GET /api/build-jobs/{id}", s.handleGetBuildJob)
  mux.HandleFunc("DELETE /api/build-jobs/{id}", s.handleDeleteBuildJob)
  ```

**Step 2.3: Update TaskStore interface**
- File: `internal/api/server.go`
- Add `ListTasksByBuildJob(ctx context.Context, buildJobID string) ([]*store.Task, error)` to `TaskStore` interface

**Step 2.4: Modify submit handlers**
- File: `internal/api/submit.go`
  - In `handleSubmit`:
    1. After resolving content and writing raw file, before `q.Submit()`:
    2. Create `BuildJob` → if fails, remove raw file, return 500
    3. Set `task.BuildJobID = buildJob.ID`
    4. Call `q.Submit()` → if fails, also `s.bjs.DeleteBuildJob()` (best-effort)
- File: `internal/api/submit_files.go`
  - In `handleSubmitFiles`:
    1. Create `BuildJob` before the file loop → if fails, return 500
    2. Update `processFile` signature: add `buildJobID string` parameter
    3. Update `processZip` signature: add `buildJobID string` parameter
    4. Update `commitFiles` signature: add `buildJobID string` parameter
    5. In `processFile`: set `task.BuildJobID = buildJobID` before `s.q.Submit()`
    6. In `commitFiles`: set `task.BuildJobID = buildJobID` before `s.q.Submit()`
    7. After the file loop: update file_count or delete empty job

**Step 2.5: Update taskDTO**
- File: `internal/api/tasks.go`
- Add `BuildJobID string \`json:"build_job_id,omitempty"\`` to `taskDTO`
- Update `toDTO()`: set `d.BuildJobID = t.BuildJobID`

**Step 2.6: Write API handler tests**
- File: `internal/api/build_jobs_test.go` (new)
  - Test list, get, delete handlers
- Update `internal/api/api_test.go` (or equivalent test helper):
  - Add `BuildJobStore` and `ListTasksByBuildJob` methods to fake store
- Update existing submit tests: verify build job creation

*Depends on: Phase 1*

### Phase 3: Frontend — API Client & Types

**Step 3.1: Create build jobs API client**
- File: `web/src/api/buildJobs.ts` (new)
- As specified in §4.7

**Step 3.2: Update TaskDTO**
- File: `web/src/api/tasks.ts`
- Add `build_job_id?: string` to `TaskDTO` interface (optional due to omitempty)

**Step 3.3: Update types**
- File: `web/src/features/builds/types.ts`
- No changes to `BuildTab` type (keep `'tasks' | 'derive'` for URL stability)

*Depends on: nothing (can be done in parallel with Phase 2)*

### Phase 4: Frontend — Components

**Step 4.1: Update StatusStageBadge**
- File: `web/src/features/builds/StatusStageBadge.tsx`
- Make `stage` optional in `StatusStageBadgeProps`: `stage?: string`
- Add `'partial'` to `TERMINAL_STATUSES` set
- Add `case 'partial'` to `statusColor()`: `border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-400`
- Update text logic: when `stage` is falsy (empty/undefined), show only status label

**Step 4.2: Create BuildJobsTab**
- File: `web/src/features/builds/BuildJobsTab.tsx` (new)
- Mirror `DeriveJobsTab` structure
- `STATUS_FILTERS`: `['all', 'pending', 'running', 'succeeded', 'failed', 'partial']`
- `DELETABLE_STATUSES`: `new Set(['succeeded', 'failed', 'partial'])`
- Columns: Title, Source, Tasks (file_count), Status (StatusStageBadge — **no stage prop**), Updated, Actions
- Row click → `getBuildJob(id)` → open `BuildJobDetailSheet`
- Delete button → AlertDialog → `deleteBuildJob(id)`
- Search, status filter, sort, pagination (PAGE_SIZE=10)

**Step 4.3: Create BuildJobDetailSheet**
- File: `web/src/features/builds/BuildJobDetailSheet.tsx` (new)
- Props: `{ open, onOpenChange, job: BuildJobDetailDTO | null, loading: boolean }`
- Shows job summary: source, status (StatusStageBadge, no stage), timestamps, error (if any)
- Shows embedded task table:
  - Columns: File Title, Status (StatusStageBadge with stage), Attempts, Updated
  - Each task row clickable → opens `TaskDetailSheet` (nested)
  - File title clickable → opens `FilePreviewSheet`

**Step 4.4: Update Builds page**
- File: `web/src/pages/Builds.tsx`
- Replace `<TasksTab>` with `<BuildJobsTab>`
- Update stats fetching: replace `listTasks` calls with `listBuildJobs` calls for the Normal tab
- Remove `import { TasksTab }` → add `import { BuildJobsTab }`

**Step 4.5: Update i18n strings**
- File: `web/src/i18n/strings.ts`
- English:
  - `'builds.tabTasks'` → `'Normal'` (was `'Normal Tasks'`)
  - `'builds.tabDerive'` → `'Derive Topic'` (was `'Derive Jobs'`)
  - Add: `'status.filter.partial': 'Partial'`
  - Add: `'builds.colSource': 'Source'`
  - Add: `'builds.colTasks': 'Tasks'`
  - Add: `'builds.jobsEmpty': 'No build jobs found.'`
  - Add: `'builds.jobsEmptyAction': 'Submit content to get started'`
  - Add: `'builds.jobDeleteConfirmTitle': 'Delete Build Job'`
  - Add: `'builds.jobDeleteConfirmDesc': 'Are you sure you want to delete this build job and all its tasks? This action cannot be undone.'`
  - Add: `'builds.jobDeleteSuccess': 'Build job deleted'`
  - Add: `'builds.jobDeleteFailed': 'Failed to delete build job'`
  - Add: `'builds.jobDetailTitle': 'Build Job Detail'`
  - Add: `'builds.jobDetailDesc': 'View build job status and task list'`
- Chinese:
  - `'builds.tabTasks'` → `'普通'`
  - `'builds.tabDerive'` → `'派生主题'`
  - Add: `'status.filter.partial': '部分成功'`
  - Add corresponding zh translations for all new keys

**Step 4.6: Remove old TasksTab**
- File: `web/src/features/builds/TasksTab.tsx` — **Delete**
- Note: `TaskDetailSheet` and `FilePreviewSheet` are **kept** (reused by BuildJobDetailSheet)

*Depends on: Phase 3*

### Phase 5: Tests

**Step 5.1: Update StatusStageBadge tests**
- File: `web/src/features/builds/__tests__/StatusStageBadge.test.tsx`
- Add test: `partial` status renders amber badge with "Partial" text
- Add test: when `stage` is omitted/undefined, only status label is shown (no separator dot)
- Add test: when `stage` is empty string, only status label is shown

**Step 5.2: Create BuildJobsTab tests**
- File: `web/src/features/builds/__tests__/BuildJobsTab.test.tsx` (new)
- Test table rendering, sorting, search, pagination, delete, detail sheet opening
- Test that `partial` appears in status filter dropdown
- Test that `partial` status jobs have enabled delete button

**Step 5.3: Create BuildJobDetailSheet tests**
- File: `web/src/features/builds/__tests__/BuildJobDetailSheet.test.tsx` (new)
- Test job detail display, task list, nested task detail, file preview

**Step 5.4: Update StatsBar tests**
- File: `web/src/features/builds/__tests__/StatsBar.test.tsx`
- Update label assertions: "Normal Tasks" → "Normal", "Derive Jobs" → "Derive Topic"

**Step 5.5: Update Builds page tests**
- File: `web/src/pages/__tests__/Builds.test.tsx`
- Update label assertions, replace TasksTab references with BuildJobsTab
- Update stats mock to use `listBuildJobs` instead of `listTasks`

**Step 5.6: Remove old TasksTab tests**
- File: `web/src/features/builds/__tests__/TasksTab.test.tsx` — **Delete**

**Step 5.7: Backend store tests**
- File: `internal/store/sqlite/build_jobs_test.go` (new)
- Test CRUD, status refresh (CTE), filter, pagination, task listing

**Step 5.8: Backend API tests**
- File: `internal/api/build_jobs_test.go` (new)
- Handler tests for list/get/delete
- Update fake store to include BuildJobStore + ListTasksByBuildJob methods
- Update submit handler tests to verify build job creation

*Depends on: Phase 4*

## 6. Risks and Mitigations

### Risk 1: Existing tasks have no build_job_id
**Impact**: Old tasks won't appear in the new Normal tab's build job list.
**Mitigation**: Acceptable for early-stage product. Old tasks remain queryable via `GET /api/tasks` (unchanged endpoint). Document in release notes. A future backfill migration can group orphan tasks into synthetic build jobs if needed.

### Risk 2: Status computation performance
**Impact**: `RefreshBuildJobStatuses` runs a CTE-based UPDATE before every list request.
**Mitigation**: The CTE only touches non-terminal build jobs (`WHERE status IN ('pending', 'running')`). In practice, the number of active build jobs is small (single-user product). The `idx_build_jobs_status_created` index on `build_jobs` and `idx_tasks_build_job_id` index on `tasks` ensure efficient lookups. No N+1 — single statement.

### Risk 3: Build job creation failure leaves orphan state
**Impact**: If `CreateBuildJob` fails in submit handlers, no task should be created.
**Mitigation**: `CreateBuildJob` is called first. If it fails, return 500 immediately (no task creation attempted). If `q.Submit()` fails after build job creation, best-effort `DeleteBuildJob` cleans up, same pattern as raw file cleanup.

### Risk 4: Concurrent raw file deletion during build job delete
**Impact**: `handleDeleteBuildJob` iterates tasks and removes raw files + DB rows.
**Mitigation**: Same best-effort pattern as existing `handleDeleteTask`. Log failures but don't fail the request. Build job delete is only allowed for terminal jobs (no active tasks), so no race with workers.

### Risk 5: Breaking existing submit API consumers
**Impact**: External tools calling `POST /api/submit` or `POST /api/submit/files`.
**Mitigation**: Response shapes are unchanged. The `build_job_id` on tasks uses `omitempty` — backward compatible.

### Risk 6: Test update scope
**Impact**: Many existing tests assert on tab labels and component behavior.
**Mitigation**: Phase 5 explicitly lists every test file to update/create/delete. Run the full test suite (`vitest` + `go test ./...`) before merging.

### Risk 7: processFile/commitFiles signature change breaks internal callers
**Impact**: Adding `buildJobID` parameter changes the function signature.
**Mitigation**: These are unexported methods on `*Server`, only called from `handleSubmitFiles` and `processZip`. All call sites are updated in the same step. The compiler catches any missed call sites.
