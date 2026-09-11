# Chat Page Knowledge Base Switcher

## 1. Background and Goals

### Why
KaaS supports knowledge base derivation — users can create topic-scoped derived KBs from the root knowledge base. The Wiki page already has a `KBSelector` component that lets users switch between the root and derived KBs. However, the Chat page is blind to this distinction: sessions are not associated with any specific knowledge base, session lists are not filtered by KB, and the chat KB selection is coupled to the Wiki page's `useKB` global store.

### What we want to achieve
1. **KB switcher in chat sidebar**: A Select component above the "+ New chat" button in the chat sidebar, letting users choose between root and derived KBs.
2. **Sessions associated with a KB**: Each session is tagged with a `kb_slug` at creation time. The slug is stored in the DB and returned in API responses.
3. **KB-scoped session history**: The session list is filtered by the currently selected KB. Users see only conversations that belong to the selected KB.
4. **Independent KB selection**: Chat page has its own KB state, decoupled from the Wiki page.

### Scope
- **In scope**: DB schema migration, backend API changes (create/list sessions with kb_slug), frontend KB selector in chat sidebar, filtered session list, independent chat KB state.
- **Out of scope**: Migrating existing sessions to a KB (they become root-KB sessions by default), cross-KB session search, session transfer between KBs.

## 2. Current State Analysis

### Backend
- `chat_sessions` table: `(id TEXT PK, title TEXT, created_at INTEGER, updated_at INTEGER)` — no KB column.
- `Session` struct: `{ID, Title, CreatedAt, UpdatedAt}` — no KB field.
- `POST /api/sessions`: accepts `{title}`, creates a session with no KB association. Uses `decodeJSON()` which calls `dec.DisallowUnknownFields()` — any unknown JSON field in the request body causes a 400 error.
- `GET /api/sessions`: returns all sessions unfiltered, ordered by `updated_at DESC`.
- `POST /api/chat`: reads `?kb=<slug>` from URL for KB resolution, but does not store the KB on the session.
- Migration pattern: `migrateSessionSchema()` uses idempotent `ALTER TABLE ADD COLUMN` with "duplicate column" error suppression.

### Frontend
- `useKB` store (zustand, persisted): shared between Wiki and Chat. `kb: string | null`.
- `KBSelector` component in `features/wiki/`: loads `listDerived()`, renders a Radix Select, writes to `useKB` store. Wiki-specific.
- `Chat.tsx`: reads `kb` from `useKB` store, passes it to `streamChat()`. Loads all sessions on mount with `listSessions()` (no filter). Creates sessions with `createSession(title)` (no KB). The stream `done` handler (~line 274) calls `listSessions()` to refresh the sidebar after a chat completes — this call is also unfiltered.
- `SessionList.tsx`: receives `sessions: Session[]` as prop, renders them grouped by date.
- `Session` type: `{id, title, created_at, updated_at}` — no `kb_slug`.

### Key callers of `ListSessions` that must be updated
All callers of the `ListSessions` method (which is changing signature) must be updated:

1. **`internal/store/sqlite/session.go`** — the implementation (`func (s *Store) ListSessions(ctx)`)
2. **`internal/api/session.go`** — the interface definition and `handleListSessions` handler
3. **`internal/api/session_errors_test.go`** — the `stubSessionStore.ListSessions` mock (line 30)
4. **`internal/store/sqlite/session_test.go`** — inline `s.ListSessions(ctx)` call (line 62)
5. **`internal/store/sqlite/errors_test.go`** — inline `s.ListSessions(ctx)` call (line 87)

### Constraints
1. Schema migration must be idempotent (follow existing `ALTER TABLE ADD COLUMN` pattern).
2. Existing sessions get `kb_slug = ''` (empty string = root KB), matching `kbpath.Resolve(root, "")` convention.
3. i18n parity test enforces en/zh key parity in `strings.ts`.
4. `decodeJSON()` uses `DisallowUnknownFields` — the `handleCreateSession` request struct **must** include a `KBSlug` field with JSON tag `"kb_slug"`, or clients sending `kb_slug` in the body will get a 400 error.
5. Existing tests must continue to pass.

## 3. Technical Design

### Architecture Decisions

**A1: `kb_slug` as empty string for root KB (not NULL)**
The existing codebase uses empty string consistently for "root KB" in `kbpath.Resolve()`. Using `TEXT NOT NULL DEFAULT ''` avoids nullable column complexity and aligns with the Go convention (zero value for strings).

**A2: Separate `chatKB` state in the KB store**
Adding a `chatKB` field to the existing `useKB` store keeps KB state co-located but allows independent selection for Chat and Wiki pages.

**A3: Filter sessions in the API, not client-side**
The `GET /api/sessions` endpoint will accept an optional `?kb=<slug>` query parameter to filter sessions by KB. This scales better than loading all sessions client-side.

**A4: Reuse KBSelector pattern with new component**
Create `ChatKBSelector` at `features/chat/ChatKBSelector.tsx` that writes to `chatKB` in the KB store. This avoids modifying the existing Wiki KBSelector.

**A5: Session creation automatically uses chatKB**
When creating a new session, the current `chatKB` value is sent as `kb_slug`. The session is permanently bound to that KB.

**A6: `chatKB: null` ↔ `kb_slug: ""` conversion convention**
The frontend uses `null` for "root KB" in the KB store (matching the existing Radix Select `ROOT_VALUE = '__root__'` pattern, since Radix Select forbids empty string values). The API uses `""` (empty string) for "root KB". The single authoritative conversion point is a `kbSlugForAPI` local variable computed in `Chat.tsx`:

```ts
const kbSlugForAPI = chatKB ?? ''
```

This value is used for ALL API calls: `listSessions(kbSlugForAPI)`, `createSession(title, kbSlugForAPI)`, and `streamChat(req, signal, chatKB)` (where `streamChat` already handles null→no-param conversion).

### Data Flow (Modified)

1. User selects a KB in the chat sidebar → writes to `useKB.chatKB`
2. `Chat.tsx` computes `kbSlugForAPI = chatKB ?? ''` and calls `listSessions(kbSlugForAPI)`
3. Backend filters `chat_sessions WHERE kb_slug = ?`
4. On new chat: `createSession(title, kbSlugForAPI)` → session stored with `kb_slug`
5. On chat message: `streamChat(req, signal, chatKB)` → backend resolves KB for RAG
6. On stream `done`: `listSessions(kbSlugForAPI)` refreshes sidebar (KB-filtered)
7. Session list re-filtered when `chatKB` changes

### Key Workflow

```
Chat page mount / chatKB change
  → const kbSlugForAPI = chatKB ?? ''
  → listSessions(kbSlugForAPI) → filtered session list
  → setSessions(filtered)
  → render SessionList

New chat
  → createSession(title, kbSlugForAPI) → session with kb_slug
  → navigate to /chat/:sessionId
  → streamChat(req, signal, chatKB) → RAG from correct KB

Stream done
  → listSessions(kbSlugForAPI) → refresh sidebar with KB-filtered list
```

## 4. Interface Contracts

### Endpoint: POST /api/sessions (MODIFIED)

**Request Body**:
```json
{
  "title": "string (required)",
  "kb_slug": "string (optional, default: \"\", pattern: ^[a-z0-9][a-z0-9-]{0,39}$ or empty string)"
}
```

When `kb_slug` is omitted or empty string, the session is associated with the root KB.
When `kb_slug` is provided and non-empty, the backend validates it against `kbpath.ValidSlug()`. Return 400 if it fails the regex. The backend does NOT verify the derived KB directory exists — a session can reference a KB that was later deleted.

**Response (201)**:
```json
{
  "id": "string (UUID)",
  "title": "string",
  "kb_slug": "string (empty string for root KB)",
  "created_at": "string (ISO 8601 / RFC3339)",
  "updated_at": "string (ISO 8601 / RFC3339)"
}
```

**Error Responses**:
- 400: invalid request body (malformed JSON, unknown fields — enforced by `decodeJSON` with `DisallowUnknownFields`), or non-empty `kb_slug` fails `ValidSlug()` regex check

**Backend model notes**:
- The `handleCreateSession` request struct MUST be updated to include `KBSlug string "json:\"kb_slug\""` alongside `Title string "json:\"title\""`. Without this field, `decodeJSON` with `DisallowUnknownFields` will reject any request body containing `"kb_slug"`, returning 400.
- `Session.KBSlug` is `string` in Go (zero value `""` = root KB). Never null/pointer.
- `kb_slug` DB column is `TEXT NOT NULL DEFAULT ''`.
- `toSessionDTO()` serializes `KBSlug` as `"kb_slug"` JSON field. Empty string is the root KB sentinel.
- If `kb_slug` is omitted from the JSON body, Go's zero value `""` is used (root KB).

**Frontend model notes**:
- `Session.kb_slug` is `string` (never null/undefined). Empty string = root KB.
- `createSession(title: string, kbSlug: string = '')` sends `{ title, kb_slug: kbSlug }` in body.
- Chat.tsx always computes `const kbSlugForAPI = chatKB ?? ''` and passes that to `createSession`.

---

### Endpoint: GET /api/sessions (MODIFIED)

**Query Parameters**:
- `kb` (optional): filter sessions by `kb_slug`.
  - **Absent** (`/api/sessions` with no `kb` param) → return ALL sessions (no filter). This preserves backward compatibility.
  - **Present with empty value** (`/api/sessions?kb=`) → filter for root KB sessions (`kb_slug = ''`).
  - **Present with value** (`/api/sessions?kb=some-slug`) → filter for that derived KB's sessions.

**Error behavior for invalid `kb` values**: The endpoint does NOT validate the `kb` query parameter value. Any string (including invalid slugs like `"!@#$"`) is used as an exact match against the `kb_slug` column. Invalid values simply return zero results, since no session can have a `kb_slug` that failed `ValidSlug()` at creation time. Only `POST /api/sessions` validates the slug.

**Response (200)**:
```json
{
  "sessions": [
    {
      "id": "string (UUID)",
      "title": "string",
      "kb_slug": "string",
      "created_at": "string (ISO 8601 / RFC3339)",
      "updated_at": "string (ISO 8601 / RFC3339)"
    }
  ]
}
```

When no sessions match, the response is `{"sessions":[]}` (empty array, never null).

**Error Responses**: 500 (internal store error)

**Backend model notes**:
- `ListSessions(ctx context.Context, kbSlug *string) ([]*store.Session, error)` — pointer to string.
  - `nil` → no filter (all sessions)
  - `ptr("")` → root KB only (WHERE kb_slug = '')
  - `ptr("some-slug")` → that derived KB
- Handler uses `r.URL.Query().Has("kb")` to distinguish "param present" from "param absent".
  - If `Has("kb")` is true: `val := r.URL.Query().Get("kb"); s.ss.ListSessions(ctx, &val)`
  - If `Has("kb")` is false: `s.ss.ListSessions(ctx, nil)`

**Frontend model notes**:
- `listSessions(kb?: string)` — signature uses optional parameter.
  - Called with no argument (`listSessions()`) → no `?kb` param → all sessions. Used only for backward compat or testing; NOT used by Chat.tsx.
  - Called with `""` (`listSessions("")`) → appends `?kb=` → root KB sessions.
  - Called with `"slug"` (`listSessions("slug")`) → appends `?kb=slug` → that KB's sessions.
- Chat.tsx always calls `listSessions(kbSlugForAPI)` where `kbSlugForAPI = chatKB ?? ''`, ensuring the `kb` param is always present.

---

### Endpoint: PATCH /api/sessions/{id} (MODIFIED — response shape only)

**Request Body** (unchanged):
```json
{
  "title": "string (required)"
}
```

`kb_slug` is NOT changeable via PATCH. A session's KB is immutable after creation.

**Response (200)**:
```json
{
  "id": "string",
  "title": "string",
  "kb_slug": "string",
  "created_at": "string (ISO 8601)",
  "updated_at": "string (ISO 8601)"
}
```

**Error Responses**: 400 (bad body) / 404 (not found) / 500 (internal)

---

### Endpoint: DELETE /api/sessions/{id} (UNCHANGED)

Response: 204 No Content. No changes.

---

### Endpoint: GET /api/sessions/{id}/messages (UNCHANGED)

Response shape unchanged. The session lookup (`GetSession`) now scans `kb_slug` from the row but the messages response does not include it.

---

### Backend Model: `store.Session` (Go)

```go
type Session struct {
    ID        string // UUID
    Title     string
    KBSlug    string // "" = root KB, non-empty = derived KB slug
    CreatedAt int64  // unix ms
    UpdatedAt int64  // unix ms
}
```

### Backend DTO: `sessionDTO` (Go)

```go
type sessionDTO struct {
    ID        string `json:"id"`
    Title     string `json:"title"`
    KBSlug    string `json:"kb_slug"`
    CreatedAt string `json:"created_at"`
    UpdatedAt string `json:"updated_at"`
}
```

### Backend Request Struct: `handleCreateSession` (Go)

```go
var req struct {
    Title  string `json:"title"`
    KBSlug string `json:"kb_slug"`
}
```

This is critical: `decodeJSON` calls `dec.DisallowUnknownFields()`, so without `KBSlug` in the struct, any request body containing `"kb_slug"` would be rejected with 400.

### Backend Store Interface Change: `SessionStore`

```go
type SessionStore interface {
    CreateSession(ctx context.Context, s *store.Session) error
    ListSessions(ctx context.Context, kbSlug *string) ([]*store.Session, error)  // CHANGED
    GetSession(ctx context.Context, id string) (*store.Session, error)
    UpdateSessionTitle(ctx context.Context, id, title string, now int64) error
    DeleteSession(ctx context.Context, id string) error
    CreateMessage(ctx context.Context, m *store.Message) error
    ListMessages(ctx context.Context, sessionID string) ([]*store.Message, error)
    TouchSession(ctx context.Context, id string, now int64) error
}
```

### Frontend Model: `Session` (TypeScript)

```ts
export interface Session {
  id: string
  title: string
  kb_slug: string   // "" = root KB, non-empty = derived KB slug
  created_at: string
  updated_at: string
}
```

### Frontend KB Store: `useKB` (TypeScript)

```ts
interface KBState {
  kb: string | null         // Wiki page KB selection (unchanged)
  chatKB: string | null     // Chat page KB selection (new); null = root KB
  setKB: (slug: string | null) => void
  setChatKB: (slug: string | null) => void
}
```

**Conversion rule**: `chatKB: null` in the store maps to `kb_slug: ""` over the wire. The single conversion point is `Chat.tsx`:
```ts
const chatKB = useKB((s) => s.chatKB)
const kbSlugForAPI = chatKB ?? ''  // null → "" for API calls
```

### Frontend API Functions: `sessions.ts` (TypeScript)

```ts
export async function listSessions(kb?: string): Promise<Session[]> {
  // When kb is undefined: no ?kb param (all sessions)
  // When kb is '' or a slug string: append ?kb=<value>
  const params = kb !== undefined ? `?kb=${encodeURIComponent(kb)}` : ''
  const res = await apiFetch(`/sessions${params}`)
  const data = (await res.json()) as { sessions: Session[] }
  return data.sessions
}

export async function createSession(title: string, kbSlug: string = ''): Promise<Session> {
  const res = await apiFetch('/sessions', {
    method: 'POST',
    body: JSON.stringify({ title, kb_slug: kbSlug }),
  })
  return res.json() as Promise<Session>
}
```

## 5. Implementation Steps

### Phase 1: Backend — Schema & Store Layer

**Step 1.1: Add `KBSlug` to Session model**
- File: `internal/store/session.go`
- Add `KBSlug string` field to `Session` struct.

**Step 1.2: Schema migration — add `kb_slug` column**
- File: `internal/store/sqlite/session.go`
- In `migrateSessionSchema()`, add an idempotent `ALTER TABLE chat_sessions ADD COLUMN kb_slug TEXT NOT NULL DEFAULT ''` (suppress "duplicate column" error, same pattern as the `reasoning` column migration).
- Add an index: `CREATE INDEX IF NOT EXISTS idx_sessions_kb_slug ON chat_sessions(kb_slug)` in the migration function.

**Step 1.3: Update CRUD queries for `kb_slug`**
- File: `internal/store/sqlite/session.go`
- `CreateSession`: Update INSERT to include `kb_slug`.
  ```sql
  INSERT INTO chat_sessions (id, title, kb_slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)
  ```
- `ListSessions(ctx context.Context, kbSlug *string)`: Change signature. When `kbSlug` is `nil`, use the existing query (no WHERE clause). When non-nil, add `WHERE kb_slug = ?`. Keep `ORDER BY updated_at DESC`. Both query variants must include `kb_slug` in the SELECT column list.
  ```go
  func (s *Store) ListSessions(ctx context.Context, kbSlug *string) ([]*store.Session, error) {
      var rows *sql.Rows
      var err error
      if kbSlug != nil {
          rows, err = s.db.QueryContext(ctx,
              `SELECT id, title, kb_slug, created_at, updated_at FROM chat_sessions WHERE kb_slug = ? ORDER BY updated_at DESC`, *kbSlug)
      } else {
          rows, err = s.db.QueryContext(ctx,
              `SELECT id, title, kb_slug, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC`)
      }
      // ... scan including &sess.KBSlug ...
  }
  ```
- `GetSession`: Update SELECT to include `kb_slug` in the column list and scan.
  ```sql
  SELECT id, title, kb_slug, created_at, updated_at FROM chat_sessions WHERE id = ?
  ```

**Step 1.4: Update store tests**
- File: `internal/store/sqlite/session_test.go`
  - Update `s.ListSessions(ctx)` call (line 62) to `s.ListSessions(ctx, nil)` for "no filter" behavior.
  - Update session creation to set and verify `KBSlug`.
  - Add `TestSessionListFilterByKBSlug`: create sessions with different KB slugs, verify:
    - `ListSessions(ctx, ptr(""))` returns root-only sessions
    - `ListSessions(ctx, ptr("my-kb"))` returns only that KB's sessions
    - `ListSessions(ctx, nil)` returns all sessions
- File: `internal/store/sqlite/errors_test.go`
  - Update the `"ListSessions"` entry (line 87) from `s.ListSessions(ctx)` to `s.ListSessions(ctx, nil)`.

### Phase 2: Backend — API Layer

**Step 2.1: Update sessionDTO and toSessionDTO**
- File: `internal/api/session.go`
- Add `KBSlug string "json:\"kb_slug\""` to `sessionDTO`.
- Update `toSessionDTO()` to set `KBSlug: s.KBSlug`.

**Step 2.2: Update handleCreateSession**
- File: `internal/api/session.go`
- Change the request struct from:
  ```go
  var req struct {
      Title string `json:"title"`
  }
  ```
  To:
  ```go
  var req struct {
      Title  string `json:"title"`
      KBSlug string `json:"kb_slug"`
  }
  ```
  This is REQUIRED because `decodeJSON()` calls `dec.DisallowUnknownFields()`. Without `KBSlug` in the struct, any request body containing `"kb_slug"` is rejected with 400.
- After `decodeJSON`, validate: if `req.KBSlug != ""` and `!kbpath.ValidSlug(req.KBSlug)`, return 400 with `"invalid kb_slug"`.
- Set `sess.KBSlug = req.KBSlug` before `CreateSession()`.
- Import `kbpath` package: `"github.com/bybit-exchange/kaas/internal/kbpath"`.

**Step 2.3: Update handleListSessions**
- File: `internal/api/session.go`
- Read `kb` query parameter:
  ```go
  var kbFilter *string
  if r.URL.Query().Has("kb") {
      v := r.URL.Query().Get("kb")
      kbFilter = &v
  }
  sessions, err := s.ss.ListSessions(r.Context(), kbFilter)
  ```

**Step 2.4: Update SessionStore interface**
- File: `internal/api/session.go`
- Change `ListSessions(ctx context.Context) ([]*store.Session, error)` to `ListSessions(ctx context.Context, kbSlug *string) ([]*store.Session, error)`.

**Step 2.5: Update API test files**
- File: `internal/api/session_errors_test.go`
  - Update `stubSessionStore.ListSessions` signature from `ListSessions(context.Context)` to `ListSessions(context.Context, *string)`:
    ```go
    func (s *stubSessionStore) ListSessions(_ context.Context, _ *string) ([]*store.Session, error) {
        if s.listErr != nil {
            return nil, s.listErr
        }
        return nil, nil
    }
    ```
  - Update test case `"create with an unknown field"` — the body `'{"title":"x","admin":true}'` should still return 400, but `"kb_slug"` is no longer unknown. Add a new test verifying `{"title":"x","kb_slug":"valid","admin":true}` returns 400.
  - Add test case for `"create with invalid kb_slug"`: body `{"title":"x","kb_slug":"INVALID!"}` → 400.
  - Add test case for `"create with valid kb_slug"`: body `{"title":"x","kb_slug":"my-kb"}` → 201 with `kb_slug: "my-kb"` in response.
- File: `internal/api/session_test.go` (if exists)
  - Update any `ListSessions` mock calls.
  - Add tests for `GET /api/sessions?kb=` and `GET /api/sessions?kb=slug` filtering.

### Phase 3: Frontend — API & State

**Step 3.1: Update Session type and API functions**
- File: `web/src/api/sessions.ts`
- Add `kb_slug: string` to `Session` interface.
- Update `createSession`:
  ```ts
  export async function createSession(title: string, kbSlug: string = ''): Promise<Session> {
    const res = await apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, kb_slug: kbSlug }),
    })
    return res.json() as Promise<Session>
  }
  ```
- Update `listSessions`:
  ```ts
  export async function listSessions(kb?: string): Promise<Session[]> {
    const params = kb !== undefined ? `?kb=${encodeURIComponent(kb)}` : ''
    const res = await apiFetch(`/sessions${params}`)
    const data = (await res.json()) as { sessions: Session[] }
    return data.sessions
  }
  ```

**Step 3.2: Add `chatKB` to KB store**
- File: `web/src/store/kb.ts`
- Add `chatKB: string | null` and `setChatKB: (slug: string | null) => void` to the store.
- Default `chatKB: null` (root KB).
- Persisted alongside `kb` in `kaas-kb` localStorage key.

**Step 3.3: Update Chat store — no structural changes**
- File: `web/src/store/chat.ts`
- No changes. The `sessions` array continues to hold the currently loaded sessions. Filtering is done at the API level.

### Phase 4: Frontend — UI Components

**Step 4.1: Create ChatKBSelector component**
- File: `web/src/features/chat/ChatKBSelector.tsx` (NEW)
- Similar to `features/wiki/KBSelector.tsx` but:
  - Reads/writes `chatKB` / `setChatKB` from `useKB` store (not `kb` / `setKB`).
  - Accepts an `onChange?: () => void` callback prop (so Chat.tsx can react to selection changes).
  - Uses the same `listDerived()` API to populate the dropdown.
  - Uses `ROOT_VALUE = '__root__'` sentinel for Radix Select (same pattern as Wiki KBSelector).
  - Reuses existing i18n keys where applicable (`wiki.kbRoot`, `wiki.kbArticleCount`) plus one new key `chat.kbLabel`.
  - Compact styling appropriate for sidebar placement.

**Step 4.2: Add ChatKBSelector to SessionList**
- File: `web/src/features/chat/SessionList.tsx`
- Add `kbSlug: string | null` and `onKBChange: (slug: string | null) => void` to `SessionListProps`.
- Render `ChatKBSelector` above the "+ New chat" button, inside the existing `<div className="px-2 py-4">` container.
- Layout: KBSelector on top, then the New Chat button below it, with `space-y-2` gap.

**Step 4.3: Update Chat.tsx — KB-scoped session loading, creation, and stream refresh**
- File: `web/src/pages/Chat.tsx`

**KB state setup** (replaces `const kb = useKB((s) => s.kb)`):
```ts
const chatKB = useKB((s) => s.chatKB)
const setChatKB = useKB((s) => s.setChatKB)
const kbSlugForAPI = chatKB ?? ''  // single authoritative conversion point
```

**Session loading `useEffect`** (update dependency array):
```ts
useEffect(() => {
  listSessions(kbSlugForAPI)
    .then((s) => useChatStore.getState().setSessions(s))
    .catch(() => {
      toast.error(t('chat.errorLoadSessions'))
    })
}, [t, kbSlugForAPI])  // re-run when KB changes
```

**Session creation in `handleSend`**:
```ts
const session = await createSession(query.slice(0, 100), kbSlugForAPI)
```

**Stream chat call in `handleSend`** (pass chatKB, not kb):
```ts
const res = await streamChat(
  { query, messages: history, include_sources: true, session_id: targetSessionId },
  controller.signal,
  chatKB,  // streamChat already handles null→no-param
)
```

**Stream `done` handler** — this is the critical fix for the sidebar refresh after chat completes (~line 274). The current code:
```ts
// BEFORE (broken): unfiltered listSessions() overwrites KB-filtered sidebar
listSessions()
  .then((sessions) => useChatStore.getState().setSessions(sessions))
  .catch(() => {})
```
Must become:
```ts
// AFTER: KB-filtered refresh
listSessions(kbSlugForAPI)
  .then((sessions) => useChatStore.getState().setSessions(sessions))
  .catch(() => {})
```
Since `kbSlugForAPI` is derived from `chatKB` and `handleSend` captures it via the `useCallback` dependency array, this works correctly. Add `kbSlugForAPI` to the `useCallback` dependency array for `handleSend`.

**Pass KB props to SessionList**:
```tsx
<SessionList
  sessions={sessions}
  activeSessionId={sessionId}
  kbSlug={chatKB}
  onKBChange={handleKBChange}
  onNewChat={handleNewChat}
  onSelect={handleSelectSession}
  onDelete={handleDeleteSession}
  onRename={handleRenameSession}
/>
```

**Step 4.4: Handle KB change — clear active session**
- File: `web/src/pages/Chat.tsx`
- Add a `handleKBChange` callback:
```ts
const handleKBChange = useCallback(
  (slug: string | null) => {
    setChatKB(slug)
    // Navigate away from any active session (it belongs to the previous KB)
    if (sessionId) {
      navigate('/chat')
    }
  },
  [setChatKB, sessionId, navigate],
)
```

### Phase 5: i18n

**Step 5.1: Add i18n keys**
- File: `web/src/i18n/strings.ts`
- Add to `en`:
  - `'chat.kbLabel': 'Knowledge base'`
- Add to `zh`:
  - `'chat.kbLabel': '知识库'`

### Phase 6: Tests

**Step 6.1: Update frontend tests**
- File: `web/src/api/sessions.test.ts` — update mocks for new `kb_slug` field and `listSessions(kb)` signature.
- File: `web/src/features/chat/SessionList.test.tsx` — add `kbSlug` and `onKBChange` props to test renders. Add test for ChatKBSelector rendering.
- File: `web/src/store/kb.test.ts` — test `chatKB` / `setChatKB` behavior.
- File: `web/src/store/chat.test.ts` — verify sessions include `kb_slug`.
- File: `web/src/pages/Chat.test.tsx` (if exists) — update session mocks to include `kb_slug`.

### Dependency Graph

```
Phase 1 (Store) → Phase 2 (API) → Phase 3 (Frontend API/State) → Phase 4 (UI) → Phase 5 (i18n)
                                                                                ↗
Phase 6 (Tests) runs alongside each phase
```

Phase 1 and Phase 2 are backend-only. Phase 3-5 are frontend-only. They can be done in parallel once the interface contracts (Section 4) are agreed upon.

### Exhaustive List of Files Modified

**Backend** (Go):
1. `internal/store/session.go` — add `KBSlug` field
2. `internal/store/sqlite/session.go` — migration, CreateSession, ListSessions, GetSession queries
3. `internal/api/session.go` — SessionStore interface, sessionDTO, toSessionDTO, handleCreateSession, handleListSessions
4. `internal/store/sqlite/session_test.go` — update ListSessions calls, add filter tests
5. `internal/store/sqlite/errors_test.go` — update ListSessions call (line 87) to `ListSessions(ctx, nil)`
6. `internal/api/session_errors_test.go` — update stubSessionStore.ListSessions signature, add kb_slug test cases

**Frontend** (TypeScript/React):
1. `web/src/api/sessions.ts` — Session type, createSession, listSessions
2. `web/src/store/kb.ts` — add chatKB, setChatKB
3. `web/src/features/chat/ChatKBSelector.tsx` — NEW component
4. `web/src/features/chat/SessionList.tsx` — add KB props, render ChatKBSelector
5. `web/src/pages/Chat.tsx` — KB-scoped loading, creation, stream refresh
6. `web/src/i18n/strings.ts` — new i18n keys
7. `web/src/api/sessions.test.ts` — update mocks
8. `web/src/features/chat/SessionList.test.tsx` — update props
9. `web/src/store/kb.test.ts` — test chatKB
10. `web/src/store/chat.test.ts` — update session mocks

## 6. Risks and Mitigations

### R1: Existing sessions have no `kb_slug` — migration assigns root KB
**Risk**: Existing sessions get `kb_slug = ''` (root KB). If a user was using derived KBs for chat before (via the shared `useKB` store), their sessions won't appear under the derived KB.
**Mitigation**: This is acceptable. The `DEFAULT ''` migration assigns all existing sessions to root, which is correct since no KB was tracked. Document in release notes.

### R2: `ListSessions` signature change breaks existing callers
**Risk**: Changing `ListSessions(ctx)` to `ListSessions(ctx, *string)` is a breaking interface change.
**Mitigation**: All callers are identified exhaustively (see Section 2 and Phase 1/2). The Go compiler will catch any missed implementations since it's an interface method. Specifically:
- `internal/store/sqlite/session.go` — implementation
- `internal/api/session.go` — interface + handler
- `internal/api/session_errors_test.go` — stubSessionStore mock (line 30)
- `internal/store/sqlite/session_test.go` — direct call (line 62)
- `internal/store/sqlite/errors_test.go` — direct call (line 87)

### R3: `decodeJSON` with `DisallowUnknownFields` rejects `kb_slug`
**Risk**: If the `handleCreateSession` request struct does not include a `KBSlug` field, any request body containing `"kb_slug"` will be rejected with 400 — making it impossible for the frontend to send the KB slug.
**Mitigation**: Step 2.2 explicitly adds `KBSlug string "json:\"kb_slug\""` to the request struct. This is flagged as critical.

### R4: KB deleted after session creation
**Risk**: A derived KB can be deleted, leaving orphan sessions with a stale `kb_slug`.
**Mitigation**: Sessions with a stale KB slug are effectively hidden since the ChatKBSelector only shows KBs that exist (from `listDerived()`). No data loss. A future cleanup sweep could remove orphaned sessions.

### R5: Race between KB selection and session creation
**Risk**: User selects a KB, starts typing, KB changes before send.
**Mitigation**: `handleSend` captures `kbSlugForAPI` via the `useCallback` dependency array. The session is created with whatever `kbSlugForAPI` was at invocation time.

### R6: Shared `useKB` localStorage key with new `chatKB` field
**Risk**: Adding `chatKB` to the persisted `useKB` store changes the `kaas-kb` localStorage shape.
**Mitigation**: Zustand's `persist` middleware merges saved state with defaults, so `chatKB` defaults to `null` on first load after upgrade.

### R7: Stream `done` handler overwrites KB-filtered sidebar
**Risk**: The stream `done` handler (Chat.tsx ~line 274) calls `listSessions()` to refresh the sidebar. Without the `kb` parameter, this would overwrite the KB-filtered session list with the unfiltered list.
**Mitigation**: Step 4.3 explicitly changes this call to `listSessions(kbSlugForAPI)`, and `kbSlugForAPI` is captured in the `handleSend` callback's closure via the dependency array.

### R8: `GET /api/sessions?kb=<invalid>` returns unexpected results
**Risk**: Calling the endpoint with an invalid slug value could cause confusion.
**Mitigation**: Invalid `kb` values are used as an exact match against `kb_slug`. Since `POST /api/sessions` validates slugs at creation time, no session can have an invalid `kb_slug`, so invalid filter values simply return zero results. This is documented in the Interface Contracts.
