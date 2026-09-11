# Builds Page & Chat Page UI Polish

## 1. Background and Goals

### Why
The Builds page and Chat page have accumulated several UX papercuts that affect usability and visual quality:
- **Builds page**: status badges use Tailwind utility classes that are not visually distinctive; column widths are inconsistent; the only way to open a detail sheet is clicking the entire row (no explicit "Details" button); the Chinese tab label "普通" is misleading (should be "默认"); the stats bar badge dot is concatenated directly with text; detail sheets are too narrow at 50vw.
- **Chat page**: when a user sends the first message in a new conversation, `createSession()` blocks before any loading indicator appears, leaving a dead UI gap.

### Goals
1. Restyle status badges with a tinted-background pill design and WCAG AA-compliant text colors.
2. Unify column widths across both tabs for visual consistency.
3. Add an explicit "Details" button in the actions column and remove whole-row click behavior.
4. Fix the Chinese tab label: "普通" → "默认".
5. Add a space between the "●" dot and the active-count text in StatsBar badges.
6. Widen all detail sheets from 50vw to 80vw.
7. Eliminate the dead-UI gap in chat by showing a loading indicator immediately when the user sends a message.

### Scope
- **In scope**: All 7 items above. Frontend-only changes (no API changes).
- **Out of scope**: Dark mode color refinement (follow-up), backend changes, new feature work.

## 2. Current State Analysis

### Builds page
- **StatusStageBadge** uses `statusColor()` which returns Tailwind `border-*` and `text-*` classes with no background. The `outline` badge variant adds only a border, no fill — badges look thin and hard to scan.
- **PagedJobTable** has the entire `<tr>` clickable via `onClick={() => handleRowClick(job)}`. The actions column is 80px wide and only contains a Delete button.
- **StatsBar** concatenates `●{t('builds.statsActive', ...)}` — no whitespace between the dot and the number.
- **Column widths**: BuildJobsTab uses `w-[100px]` for file_count and `w-[140px]` for status/updated_at. DeriveJobsTab uses `w-[100px]` for select_from and `w-[140px]` for status/updated_at. Title/topic and source/slug have no fixed width.
- **All 5 sheets** use `w-[50vw] min-w-[400px]`.
- **TaskDetailSheet** imports and uses `statusColor()` directly (line 14, 83).

### Chat page
- **handleSend** in `Chat.tsx`: when `sessionId` is null, it awaits `createSession()` before calling `beginStream()`. During this await (potentially hundreds of ms), `isStreaming` remains false, the input is not disabled, and no loading indicator is shown.
- Once `beginStream()` is called, `isStreaming` becomes true and MessageList shows the Loader2 spinner + "Thinking…" text. The gap is specifically **before** `beginStream()`.

### Constraints
- Tailwind CSS 4.2 — supports arbitrary values in `[]` syntax.
- Badge component uses CVA; the `outline` variant sets `text-foreground` with no bg.
- `statusColor()` is exported and used in TaskDetailSheet — cannot just delete it without updating that consumer.
- Tests in `StatusStageBadge.test.tsx` check for Tailwind class names (`text-green-700`, `text-amber-700`, etc.) — these will need updating.

## 3. Technical Design

### 3.1 Status Badge Restyle

**Approach**: Replace the `statusColor()` function with a new `statusBadgeStyles()` function that returns inline style objects for background, text color, and border color. This avoids Tailwind arbitrary value proliferation for hex colors and gives us precise WCAG-compliant colors.

**WCAG AA Color Palette** (all ≥ 4.5:1 contrast ratio):

| Status     | Text Color | BG Color  | Border Color | Contrast Ratio |
|------------|-----------|-----------|-------------|---------------|
| succeeded  | `#1a7a3a` | `#e8f5e9` | `#a5d6a7`   | 4.80:1         |
| failed     | `#b5302b` | `#ffe8e7` | `#ef9a9a`   | 5.24:1         |
| cancelled  | `#a04a1b` | `#fff3e0` | `#ffcc80`   | 5.49:1         |
| partial    | `#7a6010` | `#fff8e1` | `#ffe082`   | 5.63:1         |
| running    | `#0f5f6d` | `#e0f5f5` | `#80cbc4`   | 6.45:1         |
| pending    | `#6a5f10` | `#fdf8e8` | `#fff59d`   | 6.07:1         |
| default    | `#4b5563` | `#f3f4f6` | `#d1d5db`   | 6.87:1         |

**Badge padding**: Override the base badge's `px-2.5 py-0.5` with `px-2 py-0.5` via className (reduce horizontal padding slightly for a more compact pill).

**`statusColor()` deprecation**: Keep the old function exported with a `@deprecated` JSDoc annotation for backward compatibility. TaskDetailSheet will be migrated to use `StatusStageBadge` directly instead of manually composing Badge + statusColor. Tests will be updated to check for inline styles instead of Tailwind class names.

### 3.2 Column Width Unification

Standardize widths across both tabs:

| Column     | BuildJobsTab | DeriveJobsTab | New Width |
|------------|-------------|---------------|-----------|
| Title/Topic | auto       | auto          | auto (no change) |
| Source/Slug | auto       | auto          | auto (no change) |
| Tasks/SelectFrom | `w-[100px]` | `w-[100px]` | `w-[100px]` (no change) |
| Status     | `w-[140px]` | `w-[140px]`  | `w-[160px]` (widen for "Running · Extracting" text) |
| Updated    | `w-[140px]` | `w-[140px]`  | `w-[160px]` (match status for visual balance) |

### 3.3 Details Button + Remove Row Click

- Add a "Details" button (`Eye` icon from lucide-react) in the actions `<td>`, next to the Delete button.
- Remove `onClick` from `<tr>` and remove `cursor-pointer` class.
- Widen the actions column from `w-[80px]` to `w-[120px]` to fit both buttons.
- The Details button calls the existing `handleRowClick(job)` function with `e.stopPropagation()`.
- Use the existing i18n key `tasks.viewDetail` for the button label.

### 3.4 Tab Label Fix

Change `builds.tabTasks` Chinese value from `'普通'` to `'默认'` in `strings.ts`. English value stays `'Normal'`.

### 3.5 StatsBar Badge Spacing

Change `●{t('builds.statsActive', ...)}` to `● {t('builds.statsActive', ...)}` — add a space after the dot character. This is the simplest fix. Alternatively, wrap `●` in a `<span>` element and rely on the existing `gap-1` flex spacing, but a literal space is simpler and more reliable.

### 3.6 Sheet Width

Replace `w-[50vw]` with `w-[80vw]` in all 5 files. Keep `min-w-[400px]`.

### 3.7 Chat Loading Indicator

**Approach**: Add a local `isSending` state in `Chat.tsx` using `useState`. Set it `true` at the very top of `handleSend()`, before any async work. Pass it to `MessageList` as a new `isSending` prop. MessageList shows the Loader2/"Thinking…" spinner when `isSending` is true, even if `isStreaming` is still false.

**State transitions**:
```
User clicks Send → isSending=true (immediate, synchronous)
  → createSession() awaited (if new session)
  → beginStream() called → isStreaming=true
  → isSending=false (reset after beginStream)
  → ... stream events ...
  → endStream() → isStreaming=false
```

On error during session creation, `isSending` is reset to `false`.

**Input disable**: MessageInput's `disabled` prop becomes `streamState.streaming || isSending`.

**Auto-scroll**: The MessageList scroll effect dependency array must include `isSending` so the view scrolls to the bottom when the spinner appears.

## 4. Interface Contracts

### 4.1 StatusStageBadge — New `statusBadgeStyles()` Function

**File**: `web/src/features/builds/StatusStageBadge.tsx`

**New export** (replaces `statusColor` as primary API):

```typescript
export interface StatusBadgeStyle {
  color: string       // text color (hex)
  backgroundColor: string  // bg color (hex)
  borderColor: string      // border color (hex)
}

/** Returns inline style properties for a status badge. All text colors are WCAG AA compliant (≥4.5:1) against their backgrounds. */
export function statusBadgeStyles(status: string): StatusBadgeStyle {
  switch (status) {
    case 'succeeded':  return { color: '#1a7a3a', backgroundColor: '#e8f5e9', borderColor: '#a5d6a7' }
    case 'failed':     return { color: '#b5302b', backgroundColor: '#ffe8e7', borderColor: '#ef9a9a' }
    case 'cancelled':  return { color: '#a04a1b', backgroundColor: '#fff3e0', borderColor: '#ffcc80' }
    case 'partial':    return { color: '#7a6010', backgroundColor: '#fff8e1', borderColor: '#ffe082' }
    case 'running':    return { color: '#0f5f6d', backgroundColor: '#e0f5f5', borderColor: '#80cbc4' }
    case 'pending':    return { color: '#6a5f10', backgroundColor: '#fdf8e8', borderColor: '#fff59d' }
    default:           return { color: '#4b5563', backgroundColor: '#f3f4f6', borderColor: '#d1d5db' }
  }
}
```

**Deprecated export** (kept for backward compatibility):

```typescript
/** @deprecated Use statusBadgeStyles() instead. Will be removed in a future version. */
export function statusColor(status: string): string { /* unchanged body */ }
```

**StatusStageBadge component change**:

```typescript
export function StatusStageBadge({ status, stage, className }: StatusStageBadgeProps) {
  const t = useT()
  const styles = statusBadgeStyles(status)
  // ... text computation unchanged ...
  return (
    <Badge
      variant="outline"
      className={cn('px-2 py-0.5', className)}
      style={styles}
    >
      {text}
    </Badge>
  )
}
```

The `style` prop applies `color`, `backgroundColor`, and `borderColor` as inline CSS, overriding the Tailwind `text-foreground` from the `outline` variant and adding the tinted background.

### 4.2 PagedJobTable — Details Button Addition

**File**: `web/src/features/builds/PagedJobTable.tsx`

**Changes to `<tr>`**: Remove `onClick` handler and `cursor-pointer` class.

Before:
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

After:
```tsx
<tr
  key={job.id}
  className={cn(
    'border-b transition-colors last:border-0 hover:bg-muted/50',
    job.status === 'failed' && 'border-l-4 border-l-destructive',
  )}
>
```

**Changes to actions `<th>`**: Widen from `w-[80px]` to `w-[120px]`.

**Changes to actions `<td>`**: Add Details button before Delete button.

```tsx
<td className="whitespace-nowrap px-4 py-3">
  <div className="flex items-center gap-1">
    <Button
      variant="ghost"
      size="sm"
      className="h-7 px-2 text-xs"
      onClick={(e) => {
        e.stopPropagation()
        handleRowClick(job)
      }}
    >
      <Eye className="mr-1 h-3.5 w-3.5" />
      {t('tasks.viewDetail')}
    </Button>
    <Button
      variant="ghost"
      size="sm"
      className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
      disabled={!deletableStatuses.has(job.status)}
      onClick={(e) => {
        e.stopPropagation()
        setDeleteTarget(job)
      }}
    >
      <Trash2 className="mr-1 h-3.5 w-3.5" />
      {t('tasks.delete')}
    </Button>
  </div>
</td>
```

New import: `Eye` from `lucide-react`.

### 4.3 MessageList — New `isSending` Prop

**File**: `web/src/features/chat/MessageList.tsx`

**Interface change**:

```typescript
interface MessageListProps {
  messages: ChatMessage[]
  streamingContent?: string
  streamingStatus?: string | null
  streamingReasoning?: string
  streamingStatusEntries?: string[]
  streamingPhase?: StreamPhase
  isStreaming?: boolean
  isSending?: boolean        // NEW: true during session creation, before stream starts
  onCitationClick?: (index: number) => void
}
```

**Rendering change**: The streaming bubble condition becomes:

```tsx
{(streamingContent || streamingStatus || isStreaming || isSending) && (
  <div className="flex justify-start" aria-live="polite" aria-atomic="false">
    <div className="max-w-[100%] px-1">
      {/* ... existing ThinkingBlock ... */}
      {/* ... existing content/phase checks ... */}
      {/* Fallback now also triggers on isSending */}
      : !(streamingStatusEntries?.length) && !streamingReasoning ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>{t('chat.thinking')}</span>
        </div>
      ) : null
    </div>
  </div>
)}
```

**Scroll effect**: Add `isSending` to the dependency array:

```typescript
useEffect(() => {
  if (isAtBottomRef.current && typeof bottomRef.current?.scrollIntoView === 'function') {
    bottomRef.current.scrollIntoView({ behavior: 'smooth' })
  }
}, [messages.length, streamingContent, streamingStatus, streamingReasoning, streamingStatusEntries, isSending])
```

### 4.4 Chat.tsx — `isSending` State

**File**: `web/src/pages/Chat.tsx`

**New state**:

```typescript
const [isSending, setIsSending] = useState(false)
```

**handleSend changes** (pseudocode showing only the new lines):

```typescript
const handleSend = useCallback(async (query: string) => {
  setIsSending(true)                        // ← NEW: immediate feedback
  const store = useChatStore.getState()
  let currentSessionId = sessionId
  if (!currentSessionId) {
    try {
      const session = await createSession(query.slice(0, 100), kbSlugForAPI)
      // ... existing session setup ...
    } catch {
      setIsSending(false)                   // ← NEW: reset on error
      toast.error(t('chat.errorCreateSession'))
      return
    }
  }
  // ... existing abort/clear error logic ...
  store.beginStream(targetSessionId, controller)
  setIsSending(false)                       // ← NEW: handoff to isStreaming
  // ... rest unchanged ...
}, [...])
```

**MessageList prop change**:

```tsx
<MessageList
  messages={messages}
  // ... existing props ...
  isStreaming={streamState.streaming}
  isSending={isSending}                     // ← NEW
/>
```

**MessageInput disabled change**:

```tsx
<MessageInput
  // ... existing props ...
  streaming={streamState.streaming || isSending}   // ← show stop button during send
  disabled={streamState.streaming || isSending}     // ← disable input during send
/>
```

Note: During the `isSending` phase, the MessageInput shows a Stop button (since `streaming` is true). Clicking Stop while `isSending` is true should abort. To handle this cleanly, `handleStop` should also reset `isSending`:

```typescript
const handleStop = useCallback(() => {
  setIsSending(false)                       // ← NEW
  if (!sessionId) return
  // ... existing logic ...
}, [sessionId])
```

### 4.5 StatsBar Badge Spacing

**File**: `web/src/features/builds/StatsBar.tsx`

Before:
```tsx
●{t('builds.statsActive', { count: activeCount })}
```

After:
```tsx
● {t('builds.statsActive', { count: activeCount })}
```

### 4.6 i18n String Change

**File**: `web/src/i18n/strings.ts`

| Key | Current ZH | New ZH |
|-----|-----------|--------|
| `builds.tabTasks` | `'普通'` | `'默认'` |

English value `'Normal'` stays unchanged.

### 4.7 Sheet Width Changes

**Files**: All 5 files listed below.

Before: `className="w-[50vw] min-w-[400px] flex flex-col"`
After: `className="w-[80vw] min-w-[400px] flex flex-col"`

### 4.8 TaskDetailSheet — Migrate Away from `statusColor()`

**File**: `web/src/features/builds/TaskDetailSheet.tsx`

Replace the manual `Badge + statusColor()` usage with `StatusStageBadge`:

Before:
```tsx
import { statusColor } from './StatusStageBadge'
// ...
<Badge variant="outline" className={statusColor(task.status)}>
  {statusLabel(t, task.status)}
</Badge>
```

After:
```tsx
import { StatusStageBadge } from './StatusStageBadge'
// ...
<StatusStageBadge status={task.status} />
```

Remove the `statusColor` import and the local `statusLabel` function if it becomes unused (check whether it's used elsewhere in the file).

## 5. Implementation Steps

### Phase 1: Status Badge Restyle (independent)

**Step 1.1**: Update `web/src/features/builds/StatusStageBadge.tsx`
- Add `StatusBadgeStyle` interface and `statusBadgeStyles()` function.
- Add `@deprecated` JSDoc to `statusColor()`.
- Update `StatusStageBadge` component to use `statusBadgeStyles()` with inline `style` prop, add `px-2 py-0.5` class override.

**Step 1.2**: Update `web/src/features/builds/TaskDetailSheet.tsx`
- Replace `Badge + statusColor()` usage with `StatusStageBadge` component.
- Remove `statusColor` import.
- Remove `statusLabel` function if unused after this change.

**Step 1.3**: Update `web/src/features/builds/__tests__/StatusStageBadge.test.tsx`
- Replace tests that check for Tailwind class names (e.g., `text-green-700`) with tests that check:
  - `statusBadgeStyles()` returns correct objects for each status.
  - The rendered badge element has the correct inline `style.color` and `style.backgroundColor`.
- Add test for the default case (unknown status).

### Phase 2: Column Widths (independent)

**Step 2.1**: Update `web/src/features/builds/BuildJobsTab.tsx`
- Change `status` column `widthClass` from `'w-[140px]'` to `'w-[160px]'`.
- Change `updated_at` column `widthClass` from `'w-[140px]'` to `'w-[160px]'`.

**Step 2.2**: Update `web/src/features/builds/DeriveJobsTab.tsx`
- Change `status` column `widthClass` from `'w-[140px]'` to `'w-[160px]'`.
- Change `updated_at` column `widthClass` from `'w-[140px]'` to `'w-[160px]'`.

### Phase 3: Details Button (independent)

**Step 3.1**: Update `web/src/features/builds/PagedJobTable.tsx`
- Add `Eye` to the lucide-react import.
- Remove `onClick` from `<tr>` element.
- Remove `cursor-pointer` from `<tr>` className.
- Widen actions `<th>` from `w-[80px]` to `w-[120px]`.
- Add "Details" button in actions `<td>` before the Delete button.
  - Button calls `handleRowClick(job)` on click.
  - Uses `Eye` icon + `t('tasks.viewDetail')` label.
  - `e.stopPropagation()` on click (defensive, even though row click is removed).

### Phase 4: Tab Label + Badge Spacing (independent)

**Step 4.1**: Update `web/src/i18n/strings.ts`
- Change `builds.tabTasks` zh value from `'普通'` to `'默认'`.

**Step 4.2**: Update `web/src/features/builds/StatsBar.tsx`
- Add a space after `●`: change `●{t(...)}` to `● {t(...)}`.

### Phase 5: Sheet Width (independent)

**Step 5.1**: Update all 5 files:
- `web/src/features/builds/BuildJobDetailSheet.tsx` (line 39)
- `web/src/features/builds/DeriveJobDetailSheet.tsx` (line 110)
- `web/src/features/builds/TaskDetailSheet.tsx` (line 67)
- `web/src/features/builds/DeriveWikiPreviewSheet.tsx` (line 62)
- `web/src/components/FilePreviewSheet.tsx` (line 68)

In each file: `w-[50vw]` → `w-[80vw]`.

### Phase 6: Chat Loading Indicator (independent)

**Step 6.1**: Update `web/src/features/chat/MessageList.tsx`
- Add `isSending?: boolean` to `MessageListProps` interface.
- Add `isSending` to function destructuring.
- Update streaming bubble condition: `(streamingContent || streamingStatus || isStreaming || isSending)`.
- Add `isSending` to the scroll `useEffect` dependency array.

**Step 6.2**: Update `web/src/pages/Chat.tsx`
- Add `const [isSending, setIsSending] = useState(false)`.
- Set `isSending` to `true` at the top of `handleSend()`.
- Set `isSending` to `false` after `beginStream()` is called.
- Set `isSending` to `false` in the `catch` block of `createSession()`.
- Set `isSending` to `false` in `handleStop()`.
- Pass `isSending` prop to `MessageList`.
- Update `MessageInput` `disabled` and `streaming` props to `|| isSending`.

### Phase 7: Verify

**Step 7.1**: Run existing tests and fix any failures:
```bash
cd web && npx vitest run
```

**Step 7.2**: Manual verification checklist:
- [ ] All 7 status badge colors render with tinted backgrounds
- [ ] Status badge text is readable on all tinted backgrounds
- [ ] Column widths align between Normal and Derive tabs
- [ ] "Details" button opens the detail sheet; rows are no longer clickable
- [ ] Chinese tab label shows "默认" not "普通"
- [ ] Space between ● and count text in StatsBar
- [ ] Detail sheets open at 80vw width
- [ ] Chat: sending first message immediately shows "Thinking…" spinner
- [ ] Chat: input is disabled during session creation
- [ ] Chat: clicking stop during session creation resets UI

## 6. Risks and Mitigations

### Risk 1: Inline styles override specificity
**Issue**: Inline `style` attributes have higher specificity than Tailwind classes. The `text-foreground` from the `outline` variant will be overridden by `style.color`, which is the desired behavior. However, if any consumer passes additional color classes via `className`, they will also be overridden.
**Mitigation**: This is acceptable because `StatusStageBadge` is the owner of its color styling. No external consumer should be passing color overrides via `className`. The `className` prop is still useful for layout/spacing adjustments.

### Risk 2: Dark mode
**Issue**: The hardcoded hex colors won't adapt to dark mode. The current Tailwind classes did have `dark:` variants.
**Mitigation**: This is a known trade-off. The plan prioritizes WCAG compliance in light mode. A follow-up task should add CSS custom properties (e.g., `--status-succeeded-text`, `--status-succeeded-bg`) that swap values in `@media (prefers-color-scheme: dark)` or via the theme class. For now, the colors are acceptable in dark mode as well (tinted backgrounds will appear slightly bright on dark backgrounds, but the contrast ratio remains readable).

### Risk 3: Test breakage
**Issue**: 7 tests in `StatusStageBadge.test.tsx` check for specific Tailwind class names.
**Mitigation**: Step 1.3 explicitly updates these tests to check inline styles instead. The `statusColor()` function tests can remain (testing the deprecated but still-exported function).

### Risk 4: `isSending` not reset on unexpected errors
**Issue**: If `handleSend` throws before reaching `beginStream()` (e.g., during abort logic), `isSending` could remain true permanently.
**Mitigation**: Wrap the critical section in try/finally to ensure `isSending` is always reset. The `beginStream` → `setIsSending(false)` path should be in a finally or the catch block should always reset it. Specifically:

```typescript
try {
  // ... session creation, beginStream ...
  setIsSending(false)
  // ... streamChat, readChatStream ...
} catch (err) {
  setIsSending(false)
  // ... error handling ...
}
```

### Risk 5: `truncate` class on slug/source columns
**Issue**: The reviewer noted `truncate` needs an explicit width constraint. Currently, slug and source columns use `auto` width which allows CSS `truncate` to work since the table layout constrains the cell width. However, without `max-w-*`, extremely long values might push the table wider.
**Mitigation**: Add `max-w-[300px]` to the `<span>` inside source and slug column renders in BuildJobsTab and DeriveJobsTab. This is a minor improvement not blocking the main work.

### Risk 6: Double-send during `isSending`
**Issue**: Before this change, the user could click Send again during session creation (input wasn't disabled). After this change, `disabled={streamState.streaming || isSending}` prevents it.
**Mitigation**: This is the fix, not a risk. The `isSending` state explicitly covers the gap.
