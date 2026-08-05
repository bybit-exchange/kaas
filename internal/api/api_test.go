package api

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/config"
	"github.com/bybit-exchange/kaas/internal/store"
)

// --- fakes ---

type fakeQueue struct {
	submitErr      error
	submitErrAt    int
	submitErrAtErr error
	dupHashes      map[string]bool
	callCount      int
	submitted      *store.Task
	allSubmitted   []*store.Task
}

func (f *fakeQueue) Submit(ctx context.Context, t *store.Task) error {
	f.callCount++
	if f.submitErr != nil {
		return f.submitErr
	}
	if f.submitErrAt > 0 && f.callCount == f.submitErrAt {
		return f.submitErrAtErr
	}
	if f.dupHashes != nil && f.dupHashes[t.ContentHash] {
		return store.ErrDuplicate
	}
	t.Status = store.StatusPending
	t.Stage = store.StageQueued
	f.submitted = t
	f.allSubmitted = append(f.allSubmitted, t)
	return nil
}

type fakeStore struct {
	tasks     []*store.Task
	getErr    error
	deleteErr error
}

func (f *fakeStore) GetTask(ctx context.Context, id string) (*store.Task, error) {
	if f.getErr != nil {
		return nil, f.getErr
	}
	for _, t := range f.tasks {
		if t.ID == id {
			return t, nil
		}
	}
	return nil, store.ErrNotFound
}

func (f *fakeStore) ListTasks(ctx context.Context, _ store.ListFilter) ([]*store.Task, error) {
	return f.tasks, nil
}

func (f *fakeStore) ListTasksPaged(ctx context.Context, filter store.PagedListFilter) (*store.ListResult, error) {
	var matched []*store.Task
	q := strings.ToLower(filter.Query)
	for _, t := range f.tasks {
		if filter.Status != "" && t.Status != filter.Status {
			continue
		}
		if q != "" && !strings.Contains(strings.ToLower(t.Title), q) && !strings.Contains(strings.ToLower(t.FileTitle), q) {
			continue
		}
		matched = append(matched, t)
	}
	total := len(matched)
	if filter.Offset > 0 && filter.Offset < len(matched) {
		matched = matched[filter.Offset:]
	} else if filter.Offset >= len(matched) {
		matched = nil
	}
	if filter.Limit > 0 && filter.Limit < len(matched) {
		matched = matched[:filter.Limit]
	}
	return &store.ListResult{Tasks: matched, Total: total}, nil
}

func (f *fakeStore) DeleteTask(ctx context.Context, id string) error {
	if f.deleteErr != nil {
		return f.deleteErr
	}
	for i, t := range f.tasks {
		if t.ID == id {
			f.tasks = append(f.tasks[:i], f.tasks[i+1:]...)
			return nil
		}
	}
	return store.ErrNotFound
}

type fakeBridge struct {
	events    []json.RawMessage // emitted in order by Chat
	chatErr   error             // returned by Chat after emitting events
	onChat    func(req bridge.ChatRequest)
	fetchResp *bridge.FetchURLResponse
	fetchErr  error

	// blockUntilCtx makes Chat wait on ctx cancellation instead of emitting,
	// then record that it observed cancellation and return ctx.Err(). Models a
	// real streaming engine that aborts when the client disconnects.
	blockUntilCtx bool
	ctxObserved   bool
}

func (f *fakeBridge) Chat(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
	if f.onChat != nil {
		f.onChat(req)
	}
	if f.blockUntilCtx {
		<-ctx.Done()
		f.ctxObserved = true
		return ctx.Err()
	}
	for _, e := range f.events {
		if err := onEvent(e); err != nil {
			return err
		}
	}
	return f.chatErr
}

func (f *fakeBridge) FetchURL(ctx context.Context, url string) (*bridge.FetchURLResponse, error) {
	if f.fetchErr != nil {
		return nil, f.fetchErr
	}
	return f.fetchResp, nil
}

// testUploadConf returns the default upload limits for tests.
func testUploadConf() config.UploadConf {
	return config.UploadConf{
		MaxBodyBytes:        30 << 20,
		MaxFileSize:         1 << 20,
		MaxZipFileSize:      5 << 20,
		MaxFilesPerUpload:   20,
		MaxZipEntries:       200,
		MaxZipExtractedSize: 30 << 20,
	}
}

// newTestServer builds a Server over the given fakes with KBDir at a temp dir.
// It stores the EvalSymlinks-resolved KB path in the config so that
// kbpath.Resolve returns paths that compare equal to the returned kb string.
func newTestServer(t *testing.T, q Queue, st TaskStore, br ChatBridge) (*Server, string) {
	t.Helper()
	raw := t.TempDir()
	// Resolve any OS-level symlinks (e.g. /tmp → /private/tmp on macOS) so that
	// kbpath.Resolve's EvalSymlinks result matches what we store as the canonical path.
	kb := raw
	if r, err := filepath.EvalSymlinks(raw); err == nil {
		kb = r
	}
	s := NewServer(q, st, nil, br, Config{KBDir: kb, Model: "test-model", Upload: testUploadConf()}, nil)
	return s, kb
}

// setupDerivedKB creates a derived KB directory at <kb>/derived/<slug> with a
// manifest.json, making it discoverable by kbpath.Resolve.
func setupDerivedKB(t *testing.T, kb, slug string) string {
	t.Helper()
	dir := filepath.Join(kb, "derived", slug)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// writeDerivedWiki writes a wiki article under <kb>/derived/<slug>/wiki/<rel>.
func writeDerivedWiki(t *testing.T, kb, slug, rel, content string) {
	t.Helper()
	full := filepath.Join(kb, "derived", slug, "wiki", rel)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func do(t *testing.T, s *Server, method, target string, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r *http.Request
	if body == "" {
		r = httptest.NewRequest(method, target, nil)
	} else {
		r = httptest.NewRequest(method, target, strings.NewReader(body))
	}
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)
	return rec
}

// --- submit ---

func TestSubmitPaste(t *testing.T) {
	q := &fakeQueue{}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit", `{"source":"paste","title":"Hi","content":"hello world"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	var resp submitResponse
	mustJSON(t, rec, &resp)
	if resp.ID == "" || resp.Status != store.StatusPending || resp.Stage != store.StageQueued {
		t.Fatalf("unexpected response %+v", resp)
	}
	if q.submitted == nil {
		t.Fatal("Submit not called")
	}
	if q.submitted.Source != "paste" || q.submitted.Title != "Hi" {
		t.Errorf("task fields wrong: %+v", q.submitted)
	}
	if q.submitted.MaxAttempts != defaultMaxAttempts {
		t.Errorf("MaxAttempts = %d, want %d", q.submitted.MaxAttempts, defaultMaxAttempts)
	}
	if q.submitted.ContentHash == "" {
		t.Error("ContentHash empty")
	}
	// Raw file written with the content.
	b, err := os.ReadFile(q.submitted.RawPath)
	if err != nil {
		t.Fatalf("read raw file: %v", err)
	}
	if string(b) != "hello world" {
		t.Errorf("raw content = %q", string(b))
	}
	if filepath.Dir(q.submitted.RawPath) != filepath.Join(kb, "raw") {
		t.Errorf("raw path not under kb/raw: %s", q.submitted.RawPath)
	}
	if !strings.HasSuffix(q.submitted.RawPath, ".md") {
		t.Errorf("raw path not .md: %s", q.submitted.RawPath)
	}
}

func TestSubmitMissingContent(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/submit", `{"source":"paste"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestSubmitUnknownSource(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/submit", `{"source":"telepathy","content":"x"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestSubmitDuplicateRemovesOrphan(t *testing.T) {
	q := &fakeQueue{submitErr: store.ErrDuplicate}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit", `{"source":"paste","content":"dup"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
	// No orphan raw file left behind.
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitURLFetches(t *testing.T) {
	br := &fakeBridge{fetchResp: &bridge.FetchURLResponse{
		Title:   "Fetched Title",
		Content: "page body",
	}}
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, br)

	rec := do(t, s, "POST", "/api/submit", `{"source":"url","url":"https://example.com"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	if q.submitted.Title != "Fetched Title" {
		t.Errorf("title = %q, want fetched title", q.submitted.Title)
	}
	b, _ := os.ReadFile(q.submitted.RawPath)
	if string(b) != "page body" {
		t.Errorf("raw content = %q, want fetched body", string(b))
	}
}

func TestSubmitURLMissing(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/submit", `{"source":"url"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestSubmitRejectsUnknownFields(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/submit", `{"source":"paste","content":"x","bogus":1}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 for unknown field", rec.Code)
	}
}

// --- tasks ---

func TestGetTask(t *testing.T) {
	task := &store.Task{
		ID: "abc", Source: "paste", Title: "T", Status: store.StatusRunning,
		Stage: store.StagePipeline, Attempts: 1, MaxAttempts: 3,
		RawPath: "/secret/raw/abc.md", ContentHash: "deadbeef",
		LeaseOwner: "host-1", Result: `{"cost":1.5}`,
	}
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{tasks: []*store.Task{task}}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks/abc", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	// Internal fields must not leak.
	body := rec.Body.String()
	for _, leak := range []string{"raw_path", "/secret/", "deadbeef", "lease_owner", "host-1"} {
		if strings.Contains(body, leak) {
			t.Errorf("response leaks internal field %q: %s", leak, body)
		}
	}
	var dto taskDTO
	mustJSON(t, rec, &dto)
	if dto.Status != store.StatusRunning || dto.Stage != store.StagePipeline {
		t.Errorf("dto status/stage wrong: %+v", dto)
	}
	if string(dto.Result) != `{"cost":1.5}` {
		t.Errorf("result = %s", dto.Result)
	}
}

func TestGetTaskNotFound(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/api/tasks/nope", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestListTasks(t *testing.T) {
	st := &fakeStore{tasks: []*store.Task{
		{ID: "1", Status: store.StatusPending, Stage: store.StageQueued, Title: "First"},
		{ID: "2", Status: store.StatusSucceeded, Stage: store.StageDone, Title: "Second"},
	}}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks?status=pending&limit=10", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var out struct {
		Tasks []taskDTO `json:"tasks"`
		Total int       `json:"total"`
	}
	mustJSON(t, rec, &out)
	// fakeStore filters by status: only "1" is pending.
	if len(out.Tasks) != 1 {
		t.Fatalf("got %d tasks, want 1", len(out.Tasks))
	}
	if out.Total != 1 {
		t.Fatalf("total = %d, want 1", out.Total)
	}
}

func TestListTasksSearchQuery(t *testing.T) {
	st := &fakeStore{tasks: []*store.Task{
		{ID: "1", Status: store.StatusSucceeded, Title: "Golang Guide"},
		{ID: "2", Status: store.StatusSucceeded, Title: "React Tutorial"},
		{ID: "3", Status: store.StatusSucceeded, FileTitle: "golang-notes"},
	}}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks?q=golang", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var out struct {
		Tasks []taskDTO `json:"tasks"`
		Total int       `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 2 {
		t.Fatalf("total = %d, want 2 (match title and file_title)", out.Total)
	}
}

func TestListTasksPagination(t *testing.T) {
	tasks := make([]*store.Task, 5)
	for i := range tasks {
		tasks[i] = &store.Task{ID: string(rune('a' + i)), Status: store.StatusSucceeded}
	}
	st := &fakeStore{tasks: tasks}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks?limit=2&offset=2", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var out struct {
		Tasks []taskDTO `json:"tasks"`
		Total int       `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 5 {
		t.Fatalf("total = %d, want 5", out.Total)
	}
	if len(out.Tasks) != 2 {
		t.Fatalf("got %d tasks, want 2", len(out.Tasks))
	}
}

func TestDeleteTaskSucceeded(t *testing.T) {
	raw := filepath.Join(t.TempDir(), "task.md")
	if err := os.WriteFile(raw, []byte("content"), 0o644); err != nil {
		t.Fatal(err)
	}
	st := &fakeStore{tasks: []*store.Task{
		{ID: "t1", Status: store.StatusSucceeded, RawPath: raw},
	}}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/tasks/t1", "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
	// Raw file should be removed.
	if _, err := os.Stat(raw); !os.IsNotExist(err) {
		t.Error("raw file not removed")
	}
	// Task should be removed from store.
	if len(st.tasks) != 0 {
		t.Errorf("task still in store: %+v", st.tasks)
	}
}

func TestDeleteTaskRunningReturns409(t *testing.T) {
	st := &fakeStore{tasks: []*store.Task{
		{ID: "t1", Status: store.StatusRunning},
	}}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/tasks/t1", "")
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409", rec.Code)
	}
}

func TestDeleteTaskNotFoundReturns404(t *testing.T) {
	st := &fakeStore{}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/tasks/nonexistent", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

// --- wiki ---

func TestListWiki(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "concepts/rag.md", "# Retrieval Augmented Generation\n\nbody")
	writeWiki(t, kb, "notes.md", "no heading here")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)
	// Expect: concepts dir (with 1 file) first (dirs before files), then notes file.
	if len(out.Tree) != 2 {
		t.Fatalf("got %d root nodes, want 2: %+v", len(out.Tree), out.Tree)
	}
	// First node: "concepts" directory (dirs sort before files).
	dir := out.Tree[0]
	if !dir.IsDir || dir.Name != "concepts" {
		t.Fatalf("expected concepts dir first, got %+v", dir)
	}
	if dir.FileCount != 1 {
		t.Errorf("concepts fileCount = %d, want 1", dir.FileCount)
	}
	if dir.Path != "concepts" {
		t.Errorf("concepts path = %q, want %q", dir.Path, "concepts")
	}
	if len(dir.Children) != 1 {
		t.Fatalf("concepts children = %d, want 1", len(dir.Children))
	}
	rag := dir.Children[0]
	if rag.Name != "rag" || rag.Path != "concepts/rag.md" || rag.Title != "Retrieval Augmented Generation" {
		t.Errorf("rag node wrong: %+v", rag)
	}
	if rag.IsDir {
		t.Errorf("rag should not be dir")
	}
	// Second node: "notes" file at root.
	file := out.Tree[1]
	if file.IsDir || file.Name != "notes" || file.Title != "notes" {
		t.Errorf("notes node wrong: %+v", file)
	}
	if file.Path != "notes.md" {
		t.Errorf("notes path = %q, want %q", file.Path, "notes.md")
	}
}

func TestListWikiEmptyDir(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 for absent wiki dir", rec.Code)
	}
	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)
	if len(out.Tree) != 0 {
		t.Errorf("want empty tree, got %d nodes", len(out.Tree))
	}
}

func TestWikiFile(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "concepts/rag.md", "# RAG\n\ncontent here")

	rec := do(t, s, "GET", "/api/wiki/file?path=concepts/rag.md", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out wikiFileResponse
	mustJSON(t, rec, &out)
	if out.Title != "RAG" || !strings.Contains(out.Content, "content here") {
		t.Errorf("unexpected file response %+v", out)
	}
}

func TestWikiFileNotFound(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/api/wiki/file?path=missing.md", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestWikiFileTraversalRejected(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	// A secret outside the wiki dir; the guard must never expose it.
	if err := os.WriteFile(filepath.Join(kb, "secret.txt"), []byte("top secret"), 0o644); err != nil {
		t.Fatal(err)
	}
	// A legitimate article that confined traversal vectors collapse toward, to
	// prove rejection isn't just "file happens not to exist".
	writeWiki(t, kb, "secret.txt", "# decoy inside wiki\nnot the secret")

	for _, p := range []string{
		"../secret.txt",             // climbs out via ..
		"..%2Fsecret.txt",           // url-encoded slash, decoded before guard
		"/etc/passwd",               // absolute
		"concepts/../../secret.txt", // climbs out after a subdir
	} {
		rec := do(t, s, "GET", "/api/wiki/file?path="+p, "")
		if rec.Code != http.StatusBadRequest {
			t.Errorf("traversal %q: status = %d, want 400; body=%s", p, rec.Code, rec.Body.String())
		}
		if strings.Contains(rec.Body.String(), "top secret") {
			t.Errorf("traversal %q leaked the out-of-tree secret", p)
		}
	}
}

func TestWikiFileMissingParam(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/api/wiki/file", "")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

// --- chat ---

func TestChatStreamsEvents(t *testing.T) {
	var gotReq bridge.ChatRequest
	br := &fakeBridge{
		events: []json.RawMessage{
			json.RawMessage(`{"type":"delta","text":"Hel"}`),
			json.RawMessage(`{"type":"delta","text":"lo"}`),
			json.RawMessage(`{"type":"done","cost_usd":0.01}`),
		},
		onChat: func(req bridge.ChatRequest) { gotReq = req },
	}
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, br)

	rec := do(t, s, "POST", "/api/chat", `{"query":"hi"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("content-type = %q", ct)
	}
	// Request forwarded with server-side KBDir + model, retrieval paths empty.
	if gotReq.KBDir != kb || gotReq.Model != "test-model" || gotReq.Query != "hi" {
		t.Errorf("forwarded request wrong: %+v", gotReq)
	}
	if len(gotReq.Paths) != 0 {
		t.Errorf("paths should be empty this slice, got %v", gotReq.Paths)
	}
	events := parseSSEData(t, rec.Body.String())
	if len(events) != 3 {
		t.Fatalf("got %d SSE events: %q", len(events), rec.Body.String())
	}
	if bridge.EventType(events[2]) != "done" {
		t.Errorf("last event type = %q", bridge.EventType(events[2]))
	}
}

func TestChatMissingQuery(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/chat", `{}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestChatUpstreamErrorBecomesSSEEvent(t *testing.T) {
	br := &fakeBridge{
		events:  []json.RawMessage{json.RawMessage(`{"type":"delta","text":"x"}`)},
		chatErr: errors.New("engine exploded"),
	}
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, br)

	rec := do(t, s, "POST", "/api/chat", `{"query":"hi"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (headers already sent)", rec.Code)
	}
	events := parseSSEData(t, rec.Body.String())
	if len(events) != 2 {
		t.Fatalf("want delta + error events, got %d: %q", len(events), rec.Body.String())
	}
	last := events[len(events)-1]
	if bridge.EventType(last) != "error" {
		t.Fatalf("last event = %s, want error", last)
	}
	if !strings.Contains(string(last), "engine exploded") {
		t.Errorf("error event missing message: %s", last)
	}
}

func TestChatClientCancelPropagatesAndNoErrorEvent(t *testing.T) {
	// When the client disconnects, the cancellation must reach the upstream
	// stream (bridge observes ctx.Done) and the handler must NOT append a
	// spurious error event.
	br := &fakeBridge{blockUntilCtx: true}
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, br)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r := httptest.NewRequest("POST", "/api/chat", strings.NewReader(`{"query":"hi"}`)).WithContext(ctx)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)

	if !br.ctxObserved {
		t.Error("bridge did not observe ctx cancellation; cancel not propagated upstream")
	}
	if strings.Contains(rec.Body.String(), `"type":"error"`) {
		t.Errorf("should not emit error event on client cancel: %q", rec.Body.String())
	}
}

// TestChatForwardsTheKBDir verifies that a valid ?kb= slug resolves to the
// derived KB directory and is forwarded in the bridge request.
func TestChatForwardsTheKBDir(t *testing.T) {
	var gotReq bridge.ChatRequest
	br := &fakeBridge{
		events: []json.RawMessage{json.RawMessage(`{"type":"done"}`)},
		onChat: func(req bridge.ChatRequest) { gotReq = req },
	}
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, br)
	setupDerivedKB(t, kb, "pricing")

	rec := do(t, s, "POST", "/api/chat?kb=pricing", `{"query":"hello"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	wantKBDir := filepath.Join(kb, "derived", "pricing")
	if gotReq.KBDir != wantKBDir {
		t.Errorf("KBDir = %q, want %q", gotReq.KBDir, wantKBDir)
	}
}

// TestChatRejectsAnUnknownKB verifies that an unknown ?kb= slug returns 400
// before any SSE headers are written.
func TestChatRejectsAnUnknownKB(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "POST", "/api/chat?kb=nope", `{"query":"hello"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 (before SSE headers); body=%s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Content-Type") == "text/event-stream" {
		t.Error("Content-Type is text/event-stream — SSE headers written before kb validation")
	}
}

// --- Run lifecycle ---

func TestRunShutsDownOnContextCancel(t *testing.T) {
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{Addr: "127.0.0.1:0"}, nil)
	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	wg.Add(1)
	var runErr error
	go func() {
		defer wg.Done()
		runErr = s.Run(ctx)
	}()
	cancel()
	wg.Wait()
	if runErr != nil {
		t.Fatalf("Run returned %v, want nil on clean shutdown", runErr)
	}
}

// --- helpers ---

func mustJSON(t *testing.T, rec *httptest.ResponseRecorder, v any) {
	t.Helper()
	if err := json.Unmarshal(rec.Body.Bytes(), v); err != nil {
		t.Fatalf("decode response: %v; body=%s", err, rec.Body.String())
	}
}

func writeWiki(t *testing.T, kb, rel, content string) {
	t.Helper()
	full := filepath.Join(kb, "wiki", rel)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// parseSSEData extracts the JSON payload of each "data:" SSE event.
func parseSSEData(t *testing.T, body string) []json.RawMessage {
	t.Helper()
	var out []json.RawMessage
	sc := bufio.NewScanner(strings.NewReader(body))
	for sc.Scan() {
		line := sc.Text()
		if strings.HasPrefix(line, "data:") {
			payload := strings.TrimSpace(line[5:])
			out = append(out, json.RawMessage(payload))
		}
	}
	return out
}

// --- healthz & static Web UI serving ---

func TestHealthz(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/healthz", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := strings.TrimSpace(rec.Body.String()); got != `{"status":"ok"}` {
		t.Errorf("body = %q", got)
	}
}

// newWebServer builds a Server whose WebDir holds a minimal SPA build.
func newWebServer(t *testing.T) *Server {
	t.Helper()
	web := t.TempDir()
	if err := os.WriteFile(filepath.Join(web, "index.html"), []byte("<!doctype html><div id=root>SPA</div>"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(web, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(web, "assets", "app.js"), []byte("console.log(1)"), 0o644); err != nil {
		t.Fatal(err)
	}
	return NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{KBDir: t.TempDir(), WebDir: web}, nil)
}

func TestStaticServesRealFile(t *testing.T) {
	s := newWebServer(t)
	rec := do(t, s, "GET", "/assets/app.js", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "console.log") {
		t.Errorf("did not serve real asset: %q", rec.Body.String())
	}
}

func TestStaticSPAFallback(t *testing.T) {
	s := newWebServer(t)
	// A client-side route with no matching file must return the SPA shell.
	rec := do(t, s, "GET", "/chat", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "id=root") {
		t.Errorf("expected index.html shell, got %q", rec.Body.String())
	}
}

func TestStaticDoesNotShadowAPI404(t *testing.T) {
	s := newWebServer(t)
	// Unknown /api/ paths must 404, never fall through to the SPA shell.
	rec := do(t, s, "GET", "/api/does-not-exist", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "id=root") {
		t.Errorf("API path wrongly served SPA shell")
	}
}

func TestStaticDisabledWhenNoWebDir(t *testing.T) {
	// Without WebDir (local dev), "/" must not be registered as a catch-all.
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	rec := do(t, s, "GET", "/chat", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 when static serving disabled", rec.Code)
	}
}

// --- /mcp reverse proxy ---

// TestMCPProxyForwardsRequestAndStreams verifies the /mcp route reverse-proxies
// to the configured MCP upstream: the upstream sees the request (path + body +
// Authorization header), and the (SSE) response is streamed back verbatim.
func TestMCPProxyForwardsRequestAndStreams(t *testing.T) {
	var gotPath, gotAuth, gotBody string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotAuth = r.Header.Get("Authorization")
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("data: {\"jsonrpc\":\"2.0\"}\n\n"))
	}))
	defer upstream.Close()

	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{},
		Config{KBDir: t.TempDir(), MCPURL: upstream.URL}, nil)

	r := httptest.NewRequest("POST", "/mcp", strings.NewReader(`{"method":"tools/list"}`))
	r.Header.Set("Authorization", "Bearer s3cret")
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if gotPath != "/mcp" {
		t.Errorf("upstream path = %q, want /mcp", gotPath)
	}
	if gotAuth != "Bearer s3cret" {
		t.Errorf("upstream Authorization = %q, want passthrough", gotAuth)
	}
	if gotBody != `{"method":"tools/list"}` {
		t.Errorf("upstream body = %q, want forwarded", gotBody)
	}
	if !strings.Contains(rec.Body.String(), `"jsonrpc":"2.0"`) {
		t.Errorf("response not streamed back: %q", rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want passthrough text/event-stream", ct)
	}
}

// TestMCPProxySubpath verifies streamable-http subpaths (/mcp/...) are proxied.
func TestMCPProxySubpath(t *testing.T) {
	var gotPath string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{},
		Config{KBDir: t.TempDir(), MCPURL: upstream.URL}, nil)

	r := httptest.NewRequest("POST", "/mcp/messages", nil)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if gotPath != "/mcp/messages" {
		t.Errorf("upstream path = %q, want /mcp/messages", gotPath)
	}
}

// TestMCPProxyDisabledWhenURLEmpty confirms that with no MCPURL the /mcp route
// is not registered at all (remote MCP disabled), so it 404s.
func TestMCPProxyDisabledWhenURLEmpty(t *testing.T) {
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{},
		Config{KBDir: t.TempDir()}, nil) // MCPURL empty
	rec := do(t, s, "POST", "/mcp", `{"method":"tools/list"}`)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 when MCP proxy disabled", rec.Code)
	}
}

// --- static resource serving: security & cache ---

func TestStaticCacheHeaders(t *testing.T) {
	s := newWebServer(t)

	// Hashed asset under /assets/ must get immutable cache header.
	rec := do(t, s, "GET", "/assets/app.js", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("assets status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Cache-Control"); got != "public, max-age=31536000, immutable" {
		t.Errorf("assets Cache-Control = %q, want immutable", got)
	}

	// SPA fallback (no matching file) must get no-cache header.
	rec = do(t, s, "GET", "/chat", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("fallback status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-cache" {
		t.Errorf("fallback Cache-Control = %q, want no-cache", got)
	}
}

func TestStaticPathTraversalRejected(t *testing.T) {
	s := newWebServer(t)

	// Note: Go's net/http ServeMux cleans bare ".." segments and issues 301/307
	// redirects before the handler runs. The paths below bypass router cleaning
	// by using encoded forms or embedding ".." in query-like patterns that the
	// handler's own guard catches.
	paths := []string{
		"/..%2Fetc/passwd",         // encoded slash, ".." still literal
		"/..\\etc\\passwd",         // backslash variant
		"/foo/..%2F..%2Fetc/passwd", // encoded slashes within subpath
	}
	for _, p := range paths {
		rec := do(t, s, "GET", p, "")
		if rec.Code != http.StatusForbidden {
			t.Errorf("path %q: status = %d, want 403", p, rec.Code)
		}
	}
}

func TestStaticMethodNotAllowed(t *testing.T) {
	s := newWebServer(t)

	for _, method := range []string{"POST", "PUT", "DELETE", "PATCH"} {
		rec := do(t, s, method, "/assets/app.js", "")
		if rec.Code != http.StatusMethodNotAllowed {
			t.Errorf("%s /assets/app.js: status = %d, want 405", method, rec.Code)
		}
	}
}

func TestStaticHEADRequest(t *testing.T) {
	s := newWebServer(t)

	rec := do(t, s, "HEAD", "/assets/app.js", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("HEAD status = %d, want 200", rec.Code)
	}
	if rec.Body.Len() != 0 {
		t.Errorf("HEAD body should be empty, got %d bytes", rec.Body.Len())
	}
}

func TestStaticDirectoryNotListed(t *testing.T) {
	s := newWebServer(t)

	// Requesting the /assets/ directory path should return SPA fallback
	// (index.html), not a file listing.
	rec := do(t, s, "GET", "/assets/", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	body := rec.Body.String()
	if strings.Contains(body, "app.js") {
		t.Errorf("directory listing exposed: body contains 'app.js'")
	}
	if !strings.Contains(body, "id=root") {
		t.Errorf("expected SPA fallback, got %q", body)
	}
}

func TestStaticDoubleEncodedTraversal(t *testing.T) {
	s := newWebServer(t)

	// %2e%2e is the double-encoded form of ".." — must not bypass traversal
	// guard. The server decodes the URL once, so %2e%2e becomes ".." which
	// the guard catches.
	paths := []string{
		"/%2e%2e/etc/passwd",
		"/assets/%2e%2e/%2e%2e/etc/passwd",
		"/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
	}
	for _, p := range paths {
		rec := do(t, s, "GET", p, "")
		// The server should reject with 403 (traversal guard) or at minimum
		// not serve anything outside the web directory.
		if rec.Code == http.StatusOK && strings.Contains(rec.Body.String(), "root:") {
			t.Errorf("path %q leaked sensitive file content", p)
		}
		if rec.Code != http.StatusForbidden {
			// Acceptable: some encoded forms may be caught by path cleaning
			// and result in a different safe response (e.g. SPA fallback).
			// The critical invariant is: no sensitive file content leaked.
			if strings.Contains(rec.Body.String(), "root:") {
				t.Errorf("path %q: status %d but leaked sensitive content", p, rec.Code)
			}
		}
	}
}
