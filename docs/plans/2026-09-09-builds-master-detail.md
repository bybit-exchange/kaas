# Refactor Builds Page into Master-Detail Layout

## 1. Background and Goals

### Why
The Builds page currently shows task/derive-job lists as flat tables. Viewing details requires opening a centered Dialog modal that obscures the list, losing context. Users frequently need to scan multiple build records and drill into individual items without losing their position in the list.

### Goals
1. **Master pane**: Retain the existing tab switcher (StatsBar) and list tables for tasks and derive jobs — the "master" view.
2. **Detail pane**: Replace the centered Dialog modals (`TaskDetailDialog`, `DeriveJobDetailDialog`) with a right-side Sheet (drawer) that slides in when a row is clicked, showing full task/derive-job detail — the "detail" view.
3. Clicking a row in the master list opens the detail Sheet; the master list remains visible and scrollable behind the overlay.
4. Maintain all existing functionality: filter, sort, search, pagination, delete, file preview, auto-polling.
5. Update all existing tests to reflect the new component structure.
6. Add i18n entries (en + zh) for any new UI strings.

### Scope
- **In scope**: Frontend refactor only — no backend API changes, no new endpoints.
- **In scope**: Converting `TaskDetailDialog` → `TaskDetailSheet`, `DeriveJobDetailDialog` → `DeriveJobDetailSheet`.
- **In scope**: Making table rows clickable to open detail (currently only the "Detail" button opens the dialog).
- **In scope**: Adding `SheetClose` (X button) and `SheetDescription` (for accessibility) to the `sheet.tsx` UI component.
- **Out of scope**: Replacing `StatsBar` with the `Tabs` UI component. The requirement says "uses existing Tabs" — `StatsBar` already acts as tabs via URL-driven switching and is well-tested. Replacing it would be cosmetic churn with no functional gain.
- **Out of scope**: Global state store for builds.
- **Out of scope**: Layout changes to place master and detail side-by-side without overlay (true split-pane). The Sheet component provides a right-side overlay, matching the existing `FilePreviewSheet` pattern.

## 2. Current State Analysis

### Components
| Component | Role | Detail Mechanism |
|---|---|---|
| `Builds.tsx` | Page shell, URL-driven tab, stats polling | — |
| `StatsBar.tsx` | Tab switcher (Card with buttons) | — |
| `TasksTab.tsx` | Task list, filter/sort/search/pagination | Opens `TaskDetailDialog` (Dialog) via "Detail" button; opens `FilePreviewSheet` (Sheet) via filename click |
| `DeriveJobsTab.tsx` | Derive job list, filter/sort/search/pagination | Opens `DeriveJobDetailDialog` (Dialog) via "Detail" button |
| `TaskDetailDialog.tsx` | Centered Dialog, fetches `getTask(id)` on open | — |
| `DeriveJobDetailDialog.tsx` | Centered Dialog, receives `job` + `loading` as props | — |
| `FilePreviewSheet.tsx` | Right-side Sheet for file content preview | Fetches `getTaskContent(id)` |

### Constraints
1. **No Ant Design** — only shadcn/ui components on Radix primitives + Tailwind.
2. **Sheet component exists** at `web/src/components/ui/sheet.tsx` — slides from right, same Radix Dialog primitive. However, it currently **lacks** a close button (X), `SheetClose`, and `SheetDescription` — all of which `DialogContent` provides. These must be added.
3. **Tests cover every builds component** — must not break; update in lockstep.
4. **i18n requires en + zh entries** in `web/src/i18n/strings.ts`.
5. **All builds state is local** — no global store. Sheet open/close state will also be local.

### Current Click Behaviors
- **TasksTab**: Clicking filename → FilePreviewSheet. Clicking "Detail" button → TaskDetailDialog.
- **DeriveJobsTab**: Clicking "Detail" button → DeriveJobDetailDialog.

### Post-Refactor Click Behaviors
- **TasksTab**: Clicking anywhere on a row (except Delete button and filename link) → TaskDetailSheet. Clicking filename → FilePreviewSheet (unchanged, but closes detail sheet first). The "Detail" button in the Actions column is removed (the row click replaces it).
- **DeriveJobsTab**: Clicking anywhere on a row (except Delete button) → DeriveJobDetailSheet. The "Detail" button in the Actions column is removed (the row click replaces it).

### Gap Analysis from Reviews (Rounds 1–2)
| Issue | Status | Resolution |
|---|---|---|
| M1 (R1) — Missing close button in Sheet | Resolved | Phase 0 adds X close button to `SheetContent` |
| M2 (R1) — Missing SheetDescription / aria-describedby | Resolved | Phase 0 adds `SheetDescription` export; all Sheet consumers use it |
| M3 (R1) — No tests for stopPropagation on Delete/filename | Resolved | Phase 4 adds explicit test cases |
| M4 (R1) — Incomplete handleRowClick rename instructions | Resolved | Phase 2 Step 2.2 provides full rename mapping |
| O1 (R1) — Abort-on-close for TaskDetailSheet fetch | Resolved | Phase 1 Step 1.1 implements AbortController pattern |
| O3 (R1) — Avoid double overflow-y-auto | Resolved | Phase 1 uses flex-col + inner scrollable div |
| M1 (R2) — Test assertion mismatch for signal arg | Resolved | Phase 4 Step 4.1 and 4.3 use `expect.any(AbortSignal)` for getTask assertions |
| M2 (R2) — Risk 1 mitigation missing from Step 2.1 | Resolved | Phase 2 Step 2.1 now includes `setDetailSheetOpen(false)` in filename click handler |
| O1 (R2) — SheetDescription should differ from title | Resolved | SheetDescription uses distinct descriptive text, not the same as SheetTitle |
| O2 (R2) — AbortController for DeriveJobDetailSheet | Acknowledged | Out of scope — DeriveJobDetailSheet receives data from parent, not internal fetch. Parent (`DeriveJobsTab.handleRowClick`) could add abort, but this is a pre-existing pattern and separate concern. |
| O3 (R2) — Reorder Phase 5 before Phase 1 | Resolved | Phase 5 moved to Phase 0.5, executed before Phase 1 |

## 3. Technical Design

### Architecture Decision: Sheet over Dialog
- Reuse the existing `Sheet` component (`web/src/components/ui/sheet.tsx`) for detail views.
- This matches the existing `FilePreviewSheet` pattern: controlled `open`/`onOpenChange` props, fetch-on-open, abort-on-close.
- The Sheet slides in from the right with a semi-transparent overlay. The master list is still visible (dimmed) behind the overlay. Users can click the overlay or press Escape to close.

### Architecture Decision: Add SheetClose + SheetDescription to sheet.tsx
The existing `sheet.tsx` is missing two things that `dialog.tsx` provides:
1. **Close button (X)**: `DialogContent` in `dialog.tsx` includes a `<DialogPrimitive.Close>` with an X icon at the top-right. `SheetContent` does not. We will add an identical close button inside `SheetContent`, matching the `dialog.tsx` pattern exactly (same positioning, same icon, same sr-only label).
2. **SheetDescription**: Radix Dialog logs a console warning when no `aria-describedby` is set. We must export a `SheetDescription` component (wrapping `DialogPrimitive.Description`). Each new Sheet consumer must include a `SheetDescription` with text that differs from the title (to be meaningful for screen readers).
3. **SheetClose**: Export `DialogPrimitive.Close` as `SheetClose` for consumers that need programmatic close buttons beyond the built-in X.

### Architecture Decision: Row Click Replaces "Detail" Button
- Currently each row has a "Detail" button in the Actions column. After the refactor, clicking anywhere on the row (except the delete button area and the filename link) opens the detail Sheet. This is more discoverable and reduces one action button.
- The "Detail" (Eye) button is removed from the Actions column. The delete button remains.
- Add `cursor-pointer` to `<tr>` elements to signal clickability.

### Architecture Decision: Rename Files
- `TaskDetailDialog.tsx` → `TaskDetailSheet.tsx` (new file; old file deleted)
- `DeriveJobDetailDialog.tsx` → `DeriveJobDetailSheet.tsx` (new file; old file deleted)
- This avoids confusion and keeps naming consistent with the component type.

### Architecture Decision: Abort-on-Close for TaskDetailSheet
`TaskDetailDialog` currently uses a plain `useCallback` + `useEffect` without an `AbortController`. `TaskDetailSheet` will follow the `FilePreviewSheet` pattern:
- Create an `AbortController` in a `useRef`.
- Abort on close or when taskId changes.
- Pass `signal` to `getTask()`.

**Verified**: `getTask(id)` in `web/src/api/tasks.ts` does NOT currently accept a `signal` parameter. Must be added (see Phase 0.5). The `apiFetch` function already passes through `init` (including `signal`) to `fetch()`.

### Architecture Decision: Avoid Double overflow-y-auto
`SheetContent` should NOT have `overflow-y-auto` in its base classes. The inner content wrapper handles scrolling. Following `FilePreviewSheet` pattern:
- `SheetContent` gets `flex flex-col` from the consumer's className.
- The scrollable area is a child `<div className="flex-1 overflow-auto ...">`.
- The SheetHeader stays fixed at top.

### Component Hierarchy (Post-Refactor)
```
Builds.tsx
├── StatsBar (unchanged)
├── TasksTab
│   ├── <table> (rows now clickable → opens detail)
│   ├── TaskDetailSheet (replaces TaskDetailDialog)
│   ├── FilePreviewSheet (unchanged, but adds SheetDescription)
│   └── AlertDialog (delete confirmation, unchanged)
└── DeriveJobsTab
    ├── <table> (rows now clickable → opens detail)
    ├── DeriveJobDetailSheet (replaces DeriveJobDetailDialog)
    └── AlertDialog (delete confirmation, unchanged)
```

### Sheet Width
- Detail sheets will use the same width as `FilePreviewSheet`: `w-[50vw] min-w-[400px]`.
- This keeps a consistent visual feel and leaves enough master list visible.

### Row Click Event Handling
- The `<tr>` gets an `onClick` handler that opens the detail Sheet.
- The delete button and the filename link need `e.stopPropagation()` to prevent the row click from firing when those elements are clicked.

## 4. Interface Contracts

### No New/Modified API Endpoints

This is a frontend-only refactor. All existing API endpoints are consumed as-is, with no changes to request/response shapes. The contracts below document the existing API shapes that the new Sheet components will consume, for completeness and to ensure frontend workers implement correctly.

---

### Existing API: GET /api/tasks/{id}

**Response (200)**:
```json
{
  "id": "string",
  "source": "string",
  "title": "string",
  "file_title": "string | undefined",
  "status": "string (enum: pending|running|succeeded|failed|cancelled)",
  "stage": "string (enum: queued|extract|pipeline|index|done)",
  "attempts": "number",
  "max_attempts": "number",
  "error": "string | undefined",
  "result": "unknown | undefined",
  "created_at": "number (epoch ms)",
  "updated_at": "number (epoch ms)"
}
```

**Error Responses**: 404 (task not found) / 500 (internal error)

**Frontend model** (`web/src/api/tasks.ts` — unchanged):
```typescript
export interface TaskDTO {
  id: string
  source: string
  title: string
  file_title?: string      // optional — may be absent from JSON (Go omitempty)
  status: string
  stage: string
  attempts: number
  max_attempts: number
  error?: string            // optional — absent when no error
  result?: unknown          // optional — absent until task completes
  created_at: number
  updated_at: number
}
```

**Nullability notes**:
- `file_title`: omitted from JSON when not set (Go `omitempty`). Frontend uses `task.file_title || task.title || task.source` as display name.
- `error`: omitted when empty. Frontend checks truthiness.
- `result`: omitted or `null` when not available. Frontend checks `!== undefined && !== null`.

---

### Existing API: GET /api/derive/{id}

**Response (200)**:
```json
{
  "id": "string",
  "slug": "string",
  "topic": "string",
  "model": "string",
  "select_from": "string (articles|documents|empty string)",
  "status": "string (enum: pending|running|succeeded|failed)",
  "stage": "string (enum: queued|filter|compile|done)",
  "error": "string | undefined",
  "result": {
    "select_from": "string | undefined",
    "selected": "number",
    "documents": "number",
    "bytes": "number",
    "filter_batches": "number",
    "compiled": "boolean",
    "cost": { "total_cost_usd": "number" } | undefined,
    "warnings": ["string"] | undefined
  } | undefined,
  "created_at": "number (epoch ms)",
  "updated_at": "number (epoch ms)"
}
```

**Error Responses**: 404 (job not found) / 500 (internal error)

**Frontend model** (`web/src/api/derived.ts` — unchanged):
```typescript
export interface DeriveJob {
  id: string
  slug: string
  topic: string
  model: string
  select_from: string
  status: DeriveStatus        // 'pending' | 'running' | 'succeeded' | 'failed'
  stage: string
  error?: string
  result?: DeriveResult
  created_at: number
  updated_at: number
}
```

**Nullability notes**:
- `error`: omitted when empty. Frontend checks truthiness.
- `result`: omitted or null until job completes. Frontend checks `!== undefined && !== null`.
- `model`: always present as string, but may be empty string `""`.
- `select_from`: always present as string, but may be empty string `""` (engine default).

---

### Modified API Function: getTask

**File**: `web/src/api/tasks.ts`

**Before**:
```typescript
export async function getTask(id: string): Promise<TaskDTO> {
  const res = await apiFetch(`/tasks/${id}`)
  return res.json() as Promise<TaskDTO>
}
```

**After** (add optional `signal` parameter):
```typescript
export async function getTask(id: string, signal?: AbortSignal): Promise<TaskDTO> {
  const res = await apiFetch(`/tasks/${id}`, { signal })
  return res.json() as Promise<TaskDTO>
}
```

This is backwards-compatible — all existing callers that pass only `id` continue to work. The `apiFetch` function already passes through `init` (including `signal`) to `fetch()`.

---

### New/Modified Component Prop Interfaces

#### Updated Sheet UI Component (`web/src/components/ui/sheet.tsx`)

New exports to add:
```typescript
// Re-export Radix's Close as SheetClose (for programmatic close buttons)
const SheetClose = DialogPrimitive.Close

// Description primitive for aria-describedby accessibility
const SheetDescription = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm text-muted-foreground', className)}
    {...props}
  />
))

// SheetContent now includes a built-in X close button
// (matching DialogContent's pattern in dialog.tsx)
```

Updated export list:
```typescript
export { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle }
```

---

#### TaskDetailSheet

**File**: `web/src/features/builds/TaskDetailSheet.tsx`

```typescript
export interface TaskDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  taskId: string | null
}
```

**Behavior**:
- Identical signature to `TaskDetailDialogProps`. Drop-in replacement.
- When `open` becomes `true` and `taskId` is non-null, fetches `getTask(taskId, signal)` with an `AbortController` signal.
- When `open` becomes `false`, aborts the in-flight request (if any) and clears internal `task` state.
- Renders a `Sheet` with `SheetHeader` > `SheetTitle` + `SheetDescription`.
- `SheetTitle` shows: `task?.title ?? t('status.detailTitle')` (same as before — e.g., "Alpha Task" or "Task Detail").
- `SheetDescription` shows: `t('tasks.detailDesc')` → en: `"View task status, stage, attempts, and result"`, zh: `"查看任务状态、阶段、尝试次数和结果"` — a distinct, descriptive string different from the title (resolves O1-R2).
- The built-in X close button in `SheetContent` provides dismiss affordance.

---

#### DeriveJobDetailSheet

**File**: `web/src/features/builds/DeriveJobDetailSheet.tsx`

```typescript
export interface DeriveJobDetailSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: DeriveJob | null
  loading: boolean
}
```

**Behavior**:
- Identical signature to `DeriveJobDetailDialogProps`. Drop-in replacement.
- Data is provided by parent (no internal fetch). Parent (`DeriveJobsTab`) fetches `getDeriveJob(id)` on row click and passes `job` + `loading`.
- Renders a `Sheet` with `SheetHeader` > `SheetTitle` + `SheetDescription`.
- `SheetTitle` shows: `t('builds.deriveDetailTitle')` → "Derive Job Detail".
- `SheetDescription` shows: `t('builds.deriveDetailDesc')` → en: `"View derive job configuration, status, and result"`, zh: `"查看派生任务配置、状态和结果"` — a distinct, descriptive string different from the title (resolves O1-R2).
- The built-in X close button in `SheetContent` provides dismiss affordance.

---

#### Updated TasksTab Internal State

The existing `TasksTabProps` interface is **unchanged**:
```typescript
export interface TasksTabProps {
  headerLeft?: React.ReactNode
}
```

Internal state changes:
- `const [detailDialogOpen, setDetailDialogOpen]` → `const [detailSheetOpen, setDetailSheetOpen]`
- `detailTaskId` remains unchanged (same name)
- Remove import of `Eye` from `lucide-react`
- Remove import of `TaskDetailDialog`; add import of `TaskDetailSheet`

---

#### Updated DeriveJobsTab Internal State (full rename mapping)

The existing `DeriveJobsTabProps` interface is **unchanged**:
```typescript
export interface DeriveJobsTabProps {
  headerLeft?: React.ReactNode
}
```

Internal state changes — full rename mapping:
| Before | After |
|---|---|
| `const [dialogOpen, setDialogOpen] = useState(false)` | `const [detailSheetOpen, setDetailSheetOpen] = useState(false)` |

Inside `handleRowClick`:
| Before | After |
|---|---|
| `setDialogOpen(true)` | `setDetailSheetOpen(true)` |

In JSX:
| Before | After |
|---|---|
| `<DeriveJobDetailDialog open={dialogOpen}` | `<DeriveJobDetailSheet open={detailSheetOpen}` |
| `onOpenChange={setDialogOpen}` | `onOpenChange={setDetailSheetOpen}` |

Other state variables (`selectedJob`, `detailLoading`) remain unchanged. Import changes:
- Remove `DeriveJobDetailDialog` import; add `DeriveJobDetailSheet`
- Remove `Eye` from `lucide-react` imports

## 5. Implementation Steps

### Phase 0: Extend Sheet UI Component (prerequisite)

**Step 0.1**: Modify `web/src/components/ui/sheet.tsx`

Add the following to resolve close button and SheetDescription gaps:

1. Add import of `X` from `lucide-react` (matching `dialog.tsx`).
2. Add a close button inside `SheetContent`, identical to the one in `DialogContent`:
   ```tsx
   <DialogPrimitive.Close className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-accent data-[state=open]:text-muted-foreground">
     <X className="h-4 w-4" />
     <span className="sr-only">Close</span>
   </DialogPrimitive.Close>
   ```
3. Add `SheetClose` export:
   ```tsx
   const SheetClose = DialogPrimitive.Close
   ```
4. Add `SheetDescription` component:
   ```tsx
   const SheetDescription = React.forwardRef<
     React.ComponentRef<typeof DialogPrimitive.Description>,
     React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
   >(({ className, ...props }, ref) => (
     <DialogPrimitive.Description
       ref={ref}
       className={cn('text-sm text-muted-foreground', className)}
       {...props}
     />
   ))
   SheetDescription.displayName = 'SheetDescription'
   ```
5. Update exports: `export { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle }`

**Step 0.2**: Update `web/src/components/FilePreviewSheet.tsx`

Add `SheetDescription` import and usage for accessibility consistency:
```tsx
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
// ...
<SheetHeader>
  <SheetTitle className="truncate">
    {displayTitle || t('tasks.filePreviewTitle')}
  </SheetTitle>
  <SheetDescription className="sr-only">
    {t('tasks.filePreviewDesc')}
  </SheetDescription>
  {content != null && (
    <p className="text-sm text-muted-foreground">
      {t('tasks.filePreviewLines', { count: lines.length })}
    </p>
  )}
</SheetHeader>
```

**Dependencies**: None.

---

### Phase 0.5: Add Signal Support to getTask (prerequisite for Phase 1)

**Step 0.5.1**: Modify `web/src/api/tasks.ts`

Change:
```typescript
export async function getTask(id: string): Promise<TaskDTO> {
  const res = await apiFetch(`/tasks/${id}`)
  return res.json() as Promise<TaskDTO>
}
```

To:
```typescript
export async function getTask(id: string, signal?: AbortSignal): Promise<TaskDTO> {
  const res = await apiFetch(`/tasks/${id}`, { signal })
  return res.json() as Promise<TaskDTO>
}
```

This is backwards-compatible — all existing callers that pass only `id` continue to work. The `apiFetch` function already passes through `init` to `fetch()`.

**Dependencies**: None. Must be done before Phase 1, Step 1.1.

---

### Phase 1: Create Sheet-Based Detail Components

**Step 1.1**: Create `web/src/features/builds/TaskDetailSheet.tsx`
- Copy content structure from `TaskDetailDialog.tsx`.
- Replace `Dialog`/`DialogContent`/`DialogHeader`/`DialogTitle` imports with `Sheet`/`SheetContent`/`SheetDescription`/`SheetHeader`/`SheetTitle` from `@/components/ui/sheet`.
- Change `<DialogContent className="max-w-2xl">` to `<SheetContent className="w-[50vw] min-w-[400px] flex flex-col">`.
- Add `<SheetDescription>{t('tasks.detailDesc')}</SheetDescription>` inside `<SheetHeader>` after `<SheetTitle>` — this uses a distinct descriptive text, NOT the same as the title.
- Wrap body content in `<div className="flex-1 overflow-auto p-4">` (only one scrollable layer).
- Replace the fetch logic with an `AbortController` pattern matching `FilePreviewSheet`:
  ```tsx
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!open || !taskId) {
      setTask(null)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    getTask(taskId, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted) setTask(detail)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        const msg = err instanceof Error ? err.message : t('status.fetchError')
        toast.error(msg)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => { controller.abort() }
  }, [open, taskId, t])
  ```
- Export `TaskDetailSheet` and `TaskDetailSheetProps`.

**Step 1.2**: Create `web/src/features/builds/DeriveJobDetailSheet.tsx`
- Copy content structure from `DeriveJobDetailDialog.tsx`.
- Replace `Dialog`/`DialogContent`/`DialogHeader`/`DialogTitle` with `Sheet`/`SheetContent`/`SheetDescription`/`SheetHeader`/`SheetTitle`.
- Change `<DialogContent className="max-w-2xl">` to `<SheetContent className="w-[50vw] min-w-[400px] flex flex-col">`.
- Add `<SheetDescription>{t('builds.deriveDetailDesc')}</SheetDescription>` inside `<SheetHeader>` — distinct descriptive text, NOT the same as the title.
- Wrap body content in `<div className="flex-1 overflow-auto p-4">`.
- Keep all rendering logic identical (no fetch — parent provides data).
- Export `DeriveJobDetailSheet` and `DeriveJobDetailSheetProps`.

**Dependencies**: Phase 0 and Phase 0.5 must be complete.

---

### Phase 2: Update Tab Components to Use Sheets

**Step 2.1**: Modify `web/src/features/builds/TasksTab.tsx`
- Replace import of `TaskDetailDialog` with `TaskDetailSheet` from `./TaskDetailSheet`.
- Remove `Eye` from `lucide-react` imports (no longer needed for Detail button).
- Rename state: `detailDialogOpen` → `detailSheetOpen`, `setDetailDialogOpen` → `setDetailSheetOpen`.
- Add `cursor-pointer` and `onClick` to each `<tr>`:
  ```tsx
  <tr
    key={task.id}
    className={cn(
      'cursor-pointer border-b transition-colors last:border-0 hover:bg-muted/50',
      task.status === 'failed' && 'border-l-4 border-destructive',
    )}
    onClick={() => {
      setDetailTaskId(task.id)
      setDetailSheetOpen(true)
    }}
  >
  ```
- Add `e.stopPropagation()` to the filename button's `onClick` AND close the detail sheet first to prevent stacking (resolves M2-R2 — Risk 1 mitigation):
  ```tsx
  onClick={(e) => {
    e.stopPropagation()
    setDetailSheetOpen(false)   // close detail sheet to prevent stacked overlays
    setPreviewTaskId(task.id)
    setPreviewTitle(displayName)
    setPreviewOpen(true)
  }}
  ```
- Add `e.stopPropagation()` to the delete button's `onClick`:
  ```tsx
  onClick={(e) => {
    e.stopPropagation()
    setDeleteTarget(task)
  }}
  ```
- Remove the "Detail" (Eye) button from the Actions `<td>` entirely. The Actions column now contains only the Delete button.
- Update the column header: change `<th className="w-[120px] ...">` to `<th className="w-[80px] ...">` (narrower since only Delete remains).
- Replace `<TaskDetailDialog ... />` with `<TaskDetailSheet open={detailSheetOpen} onOpenChange={setDetailSheetOpen} taskId={detailTaskId} />`.

**Step 2.2**: Modify `web/src/features/builds/DeriveJobsTab.tsx` (full rename mapping)
- Replace import of `DeriveJobDetailDialog` with `DeriveJobDetailSheet` from `./DeriveJobDetailSheet`.
- Remove `Eye` from `lucide-react` imports.
- Rename state variable and setter:
  - `const [dialogOpen, setDialogOpen] = useState(false)` → `const [detailSheetOpen, setDetailSheetOpen] = useState(false)`
- Update `handleRowClick` function body:
  - `setDialogOpen(true)` → `setDetailSheetOpen(true)`
  - All other logic (setDetailLoading, setSelectedJob, getDeriveJob call, error handling) remains unchanged.
- Add `cursor-pointer` and `onClick` to each `<tr>`:
  ```tsx
  <tr
    key={job.id}
    className={cn(
      'cursor-pointer border-b transition-colors last:border-0 hover:bg-muted/50',
      job.status === 'failed' && 'border-l-4 border-l-destructive',
    )}
    onClick={() => handleRowClick(job)}
  >
  ```
- Add `e.stopPropagation()` to the delete button's `onClick`:
  ```tsx
  onClick={(e) => {
    e.stopPropagation()
    setDeleteTarget(job)
  }}
  ```
- Remove the "Detail" (Eye) button from the Actions `<td>`.
- Update column header width for Actions column (narrower).
- Replace `<DeriveJobDetailDialog open={dialogOpen} onOpenChange={setDialogOpen} ... />` with `<DeriveJobDetailSheet open={detailSheetOpen} onOpenChange={setDetailSheetOpen} job={selectedJob} loading={detailLoading} />`.

**Dependencies**: Phase 1 must be complete.

---

### Phase 3: Delete Old Dialog Components

**Step 3.1**: Delete `web/src/features/builds/TaskDetailDialog.tsx`
**Step 3.2**: Delete `web/src/features/builds/DeriveJobDetailDialog.tsx`

**Dependencies**: Phase 2 must be complete.

---

### Phase 4: Update Tests

**Step 4.1**: Rename and update `web/src/features/builds/__tests__/TaskDetailDialog.test.tsx` → `web/src/features/builds/__tests__/TaskDetailSheet.test.tsx`
- Update import: `TaskDetailDialog` → `TaskDetailSheet` from `../TaskDetailSheet`
- Update all `render(<TaskDetailDialog ...>)` calls to `render(<TaskDetailSheet ...>)`
- Update `describe('TaskDetailDialog', ...)` to `describe('TaskDetailSheet', ...)`
- The `Sheet` uses the same Radix Dialog primitive internally, so `screen.getByRole('dialog')` will still work.
- **Critical (M1-R2)**: Update the assertion for the `getTask` call to account for the new `AbortSignal` parameter:
  ```typescript
  // BEFORE (would fail with AbortController):
  expect(mockGetTask).toHaveBeenCalledWith('task-1')

  // AFTER:
  expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))
  ```
  This applies to the following test:
  - `'fetches task detail when opened'` — change `expect(mockGetTask).toHaveBeenCalledWith('task-1')` to `expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))`

**Step 4.2**: Rename and update `web/src/features/builds/__tests__/DeriveJobDetailDialog.test.tsx` → `web/src/features/builds/__tests__/DeriveJobDetailSheet.test.tsx`
- Update import: `DeriveJobDetailDialog` → `DeriveJobDetailSheet` from `../DeriveJobDetailSheet`
- Update all `render(<DeriveJobDetailDialog ...>)` calls to `render(<DeriveJobDetailSheet ...>)`
- Update `describe('DeriveJobDetailDialog', ...)` to `describe('DeriveJobDetailSheet', ...)`
- All existing test cases remain valid (no fetch inside this component — props only).

**Step 4.3**: Update `web/src/features/builds/__tests__/TasksTab.test.tsx`

Existing test to update — `'clicking the Detail button opens TaskDetailDialog and fetches detail'`:
- Change to clicking the row directly (Detail button is removed):
  ```tsx
  it('clicking a row opens TaskDetailSheet and fetches detail', async () => {
    const taskWithResult = { ...TASK_1, result: { answer: 42 } }
    mockGetTask.mockResolvedValue(taskWithResult)

    await renderTab()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()

    const row = screen.getByText('Alpha Task').closest('tr')!
    fireEvent.click(row)

    await flushPromises()

    // CRITICAL (M1-R2): use expect.any(AbortSignal) for the signal arg
    expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Result')).toBeInTheDocument()
    expect(dialog.textContent).toContain('"answer": 42')
  })
  ```

**New test — stopPropagation on filename click**:
```tsx
it('clicking the filename opens file preview without opening the detail sheet', async () => {
  await renderTab()

  const filenameBtn = screen.getByRole('button', { name: 'Alpha Task' })
  fireEvent.click(filenameBtn)
  await flushPromises()

  // File preview should open
  expect(mockGetTaskContent).toHaveBeenCalledWith('task-1', expect.anything())
  // Detail sheet should NOT have opened (getTask should not be called)
  expect(mockGetTask).not.toHaveBeenCalled()
})
```

**New test — stopPropagation on delete button click**:
```tsx
it('clicking delete does not open the detail sheet', async () => {
  await renderTab()

  const row = screen.getByText('Alpha Task').closest('tr')!
  fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
  await flushPromises()

  // Delete confirmation should appear
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  // Detail sheet should NOT have opened
  expect(mockGetTask).not.toHaveBeenCalled()
})
```

**Step 4.4**: Update `web/src/features/builds/__tests__/DeriveJobsTab.test.tsx`

Update the `'detail dialog'` describe block:
- Rename describe to `'detail sheet'`
- Change test `'opens the detail dialog when clicking Detail'` → `'opens the detail sheet when clicking a row'`
- Replace `within(row).getByRole('button', { name: 'Detail' })` with clicking the row directly:
  ```tsx
  it('opens the detail sheet when clicking a row', async () => {
    await renderTab()

    const row = screen.getByText('pricing and fees').closest('tr')!
    fireEvent.click(row)
    await flushPromises()

    expect(mockGetDeriveJob).toHaveBeenCalledWith('dj-1')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Derive Job Detail')).toBeInTheDocument()
  })
  ```
- Same row-click change for `'shows optimistic data on detail fetch failure'` test:
  ```tsx
  it('shows optimistic data on detail fetch failure', async () => {
    mockGetDeriveJob.mockRejectedValue(new Error('detail unavailable'))

    await renderTab()

    const row = screen.getByText('pricing and fees').closest('tr')!
    fireEvent.click(row)
    await flushPromises()

    expect(mockToast.error).toHaveBeenCalledWith('detail unavailable')
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('pricing and fees')).toBeInTheDocument()
  })
  ```

**New test — stopPropagation on delete button click**:
```tsx
it('clicking delete does not open the detail sheet', async () => {
  await renderTab()

  const row = screen.getByText('pricing and fees').closest('tr')!
  fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
  await flushPromises()

  // Delete confirmation should appear
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  // Detail sheet should NOT have opened (getDeriveJob should not be called)
  expect(mockGetDeriveJob).not.toHaveBeenCalled()
})
```

**Step 4.5**: Verify `web/src/pages/__tests__/Builds.test.tsx`
- This test doesn't directly test detail dialogs — it tests tab switching and stats. Should pass without changes.
- Run and verify.

**Dependencies**: Phases 2 and 3 must be complete.

---

### Phase 5: Add i18n Entries

**Step 5.1**: Update `web/src/i18n/strings.ts`:

```typescript
// In en map — add these keys:
'tasks.detailDesc': 'View task status, stage, attempts, and result',
'tasks.filePreviewDesc': 'File content preview',
'builds.deriveDetailDesc': 'View derive job configuration, status, and result',

// In zh map — add these keys:
'tasks.detailDesc': '查看任务状态、阶段、尝试次数和结果',
'tasks.filePreviewDesc': '文件内容预览',
'builds.deriveDetailDesc': '查看派生任务配置、状态和结果',
```

**Dependencies**: None. Can be done in parallel with Phase 0.

---

### Phase 6: Final Verification

**Step 6.1**: Run the full Vitest suite:
```bash
cd web && pnpm test --run
```

**Step 6.2**: Run TypeScript type checking:
```bash
cd web && pnpm tsc --noEmit
```

**Step 6.3**: Manual smoke test in browser:
- Navigate to `/builds` → Tasks tab visible, table renders.
- Click a table row → Sheet slides in from right with X close button visible, shows task detail.
- Verify SheetDescription is present in DOM (inspect) but uses distinct text from SheetTitle.
- Click the X button → Sheet closes.
- Click filename → FilePreviewSheet opens (detail sheet does NOT open). If detail sheet was already open, it closes first.
- Click delete button on a row → AlertDialog opens (detail sheet does NOT open).
- Close sheet → row click again works.
- Switch to Derive Jobs tab → same behavior.
- Verify responsive: sheet at 50vw, min 400px.
- Press Escape while sheet is open → sheet closes.
- Click overlay while sheet is open → sheet closes.

**Dependencies**: All previous phases.

---

### Execution Order Summary

```
Phase 0   (Sheet UI)        ─┐
Phase 0.5 (getTask signal)   │── can run in parallel
Phase 5   (i18n entries)     ─┘
          │
Phase 1   (create Sheet detail components) — depends on Phase 0, 0.5, 5
          │
Phase 2   (update Tab components) — depends on Phase 1
          │
Phase 3   (delete old Dialog components) — depends on Phase 2
          │
Phase 4   (update tests) — depends on Phases 2 + 3
          │
Phase 6   (final verification) — depends on all above
```

## 6. Risks and Mitigations

### Risk 1: Two Sheets open simultaneously
**Scenario**: User clicks a row (opens TaskDetailSheet), then clicks a filename (opens FilePreviewSheet). Both use Radix Dialog Portal → two overlays stack.
**Mitigation**: In `TasksTab`, the filename button handler already has `e.stopPropagation()` so the row click won't fire. But if the detail sheet is already open when the user clicks a filename cell, we must close the detail sheet first. The filename click handler in Phase 2 Step 2.1 explicitly includes:
```tsx
onClick={(e) => {
  e.stopPropagation()
  setDetailSheetOpen(false)   // ← close detail first
  setPreviewTaskId(task.id)
  setPreviewTitle(displayName)
  setPreviewOpen(true)
}
```
This prevents confusing stacked overlays.

### Risk 2: Sheet role="dialog" in tests
**Scenario**: Sheet uses Radix Dialog primitive internally. If the Sheet implementation uses a different ARIA role, `screen.getByRole('dialog')` in tests would break.
**Mitigation**: Verified — `sheet.tsx` wraps `@radix-ui/react-dialog`, which always renders `role="dialog"`. No issue expected. If it does break, the test failure will be immediately visible.

### Risk 3: Row click fires on interactive children
**Scenario**: Clicking inside the delete button's `<Button>` also triggers the `<tr onClick>`.
**Mitigation**: `e.stopPropagation()` on all interactive elements within the row (delete button, filename link). This is explicitly called out in Phase 2 steps and tested in Phase 4 (new tests for stopPropagation on both filename and delete).

### Risk 4: Losing scroll position in master list
**Scenario**: Opening the Sheet triggers a layout shift or scroll reset.
**Mitigation**: The Sheet uses a Portal (renders outside the DOM tree) with `position: fixed`. The master list's scroll position is unaffected. The overlay dims the background but doesn't reflow it.

### Risk 5: Mobile viewport — 50vw too narrow
**Scenario**: On small screens, `w-[50vw]` could be too narrow; `min-w-[400px]` could overflow.
**Mitigation**: This is the same width used by `FilePreviewSheet`, so parity is maintained. If mobile support is needed later, a responsive breakpoint can change the Sheet to full-width on small screens — but that's out of scope for this refactor.

### Risk 6: Console warning for missing aria-describedby on existing FilePreviewSheet
**Scenario**: Even after fixing new components, the existing `FilePreviewSheet` would still trigger the Radix warning.
**Mitigation**: Phase 0 Step 0.2 explicitly adds `SheetDescription` to `FilePreviewSheet.tsx` as well. This eliminates the warning project-wide.

### Risk 7: getTask may not support AbortSignal
**Scenario**: The `getTask` API function does not currently pass `signal` to the underlying `apiFetch`.
**Mitigation**: Phase 0.5 explicitly adds the optional `signal` parameter. This is a safe, backwards-compatible change. Verified that `apiFetch` passes through `init` (including `signal`) to `fetch()`.

### Risk 8: Test assertion mismatch after adding AbortController
**Scenario**: After adding AbortController to TaskDetailSheet, `getTask` is called with `(taskId, signal)` but existing tests assert `toHaveBeenCalledWith('task-1')` — a strict single-arg match that would fail.
**Mitigation**: Phase 4 Steps 4.1 and 4.3 explicitly update all `getTask` assertions to `expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))`. This is called out in each step with a "CRITICAL (M1-R2)" marker to ensure it is not missed.
