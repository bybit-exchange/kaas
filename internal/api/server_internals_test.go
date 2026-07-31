package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// --- queryInt ---

func TestQueryInt(t *testing.T) {
	tests := []struct {
		name   string
		target string
		key    string
		def    int
		want   int
	}{
		{"absent uses the default", "/api/tasks", "limit", 20, 20},
		{"empty value uses the default", "/api/tasks?limit=", "limit", 20, 20},
		{"valid value", "/api/tasks?limit=5", "limit", 20, 5},
		{"explicit zero is honoured", "/api/tasks?limit=0", "limit", 20, 0},
		{"negative is honoured", "/api/tasks?offset=-3", "offset", 0, -3},
		{"non-numeric falls back", "/api/tasks?limit=abc", "limit", 20, 20},
		{"float falls back", "/api/tasks?limit=1.5", "limit", 20, 20},
		{"first of repeated params wins", "/api/tasks?limit=7&limit=9", "limit", 20, 7},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodGet, tc.target, nil)
			if got := queryInt(r, tc.key, tc.def); got != tc.want {
				t.Errorf("queryInt(%q, %q, %d) = %d, want %d", tc.target, tc.key, tc.def, got, tc.want)
			}
		})
	}
}

// --- decodeJSON ---

func TestDecodeJSON(t *testing.T) {
	type payload struct {
		Title string `json:"title"`
	}
	tests := []struct {
		name      string
		body      string
		wantErr   bool
		wantTitle string
	}{
		{"valid object", `{"title":"hi"}`, false, "hi"},
		{"unknown field is rejected", `{"title":"hi","nope":1}`, true, ""},
		{"empty body is rejected", ``, true, ""},
		{"malformed JSON is rejected", `{"title":`, true, ""},
		{"trailing second object is rejected", `{"title":"a"}{"title":"b"}`, true, ""},
		{"trailing garbage is rejected", `{"title":"a"} oops`, true, ""},
		{"trailing whitespace is fine", "{\"title\":\"a\"}\n  ", false, "a"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodPost, "/api/sessions", strings.NewReader(tc.body))
			var got payload
			err := decodeJSON(r, &got)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("decodeJSON(%q) = nil, want an error", tc.body)
				}
				return
			}
			if err != nil {
				t.Fatalf("decodeJSON(%q): %v", tc.body, err)
			}
			if got.Title != tc.wantTitle {
				t.Errorf("title = %q, want %q", got.Title, tc.wantTitle)
			}
		})
	}
}

// --- NewServer ---

// TestNewServerDefaultsLogger asserts a nil logger does not leave the access-log
// middleware dereferencing nil at the first request.
func TestNewServerDefaultsLogger(t *testing.T) {
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{}, nil)
	if s.logger == nil {
		t.Fatal("logger must never be nil")
	}
	rec := do(t, s, http.MethodGet, "/healthz", "")
	if rec.Code != http.StatusOK {
		t.Errorf("healthz status = %d, want 200", rec.Code)
	}
}

// TestNewServerNativeMCPHandler asserts [ai.mcp] enabled=true registers the
// in-process MCP endpoint on both /mcp and /mcp/.
func TestNewServerNativeMCPHandler(t *testing.T) {
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{
		KBDir:         t.TempDir(),
		Model:         "test-model",
		MCPEnabled:    true,
		MCPTimeoutSec: 30,
	}, nil)
	if s.mcpH == nil {
		t.Fatal("native MCP handler must be built when MCPEnabled is set")
	}

	for _, target := range []string{"/mcp", "/mcp/"} {
		rec := do(t, s, http.MethodPost, target, `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s status = %d, want 200; body=%s", target, rec.Code, rec.Body.String())
		}
		var resp struct {
			Result json.RawMessage `json:"result"`
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
			t.Fatalf("%s: response is not JSON-RPC: %v (%s)", target, err, rec.Body.String())
		}
		if !strings.Contains(string(resp.Result), "serverInfo") {
			t.Errorf("%s result = %s, want the initialize result from the native handler", target, resp.Result)
		}
	}
}

// TestNewServerNativeMCPWinsOverProxy asserts the deprecated MCPURL reverse proxy
// is bypassed (and a warning logged) when the native handler is enabled — the
// upstream must receive nothing.
func TestNewServerNativeMCPWinsOverProxy(t *testing.T) {
	var upstreamHits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstreamHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	var logBuf bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&logBuf, &slog.HandlerOptions{Level: slog.LevelWarn}))

	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{
		KBDir:         t.TempDir(),
		Model:         "test-model",
		MCPURL:        upstream.URL,
		MCPEnabled:    true,
		MCPTimeoutSec: 30,
	}, logger)

	if !strings.Contains(logBuf.String(), "native MCP handler takes precedence") {
		t.Errorf("expected a deprecation warning, got %q", logBuf.String())
	}
	rec := do(t, s, http.MethodPost, "/mcp", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if n := upstreamHits.Load(); n != 0 {
		t.Errorf("upstream received %d requests, want 0 (native handler must serve it)", n)
	}
}

// TestMCPProxyDisabledForUnparsableURL asserts a malformed upstream URL leaves
// the route unregistered instead of panicking the whole server at startup.
func TestMCPProxyDisabledForUnparsableURL(t *testing.T) {
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{
		KBDir:  t.TempDir(),
		MCPURL: "http://bad host/mcp", // space in host → url.Parse fails
	}, nil)
	if s.mcpHandler() != nil {
		t.Fatal("mcpHandler must be nil for an unparsable URL")
	}
	rec := do(t, s, http.MethodPost, "/mcp", `{}`)
	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404 (route unregistered)", rec.Code)
	}
}

// --- static serving ---

// TestStaticNoIndexHTMLReturns404 asserts a WebDir without an index.html cannot
// serve the SPA fallback (a half-built web/dist must 404, not 500).
func TestStaticNoIndexHTMLReturns404(t *testing.T) {
	webDir := t.TempDir()
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{WebDir: webDir}, nil)

	rec := do(t, s, http.MethodGet, "/some/deep/route", "")
	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404 without an index.html", rec.Code)
	}
}

// TestStaticServesNestedAssetWithImmutableCache asserts hashed asset paths get
// the long-lived cache header while other files stay revalidated.
func TestStaticServesNestedAssetWithImmutableCache(t *testing.T) {
	webDir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(webDir, "assets"), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "assets", "app-abc123.js"), []byte("console.log(1)"), 0o644); err != nil {
		t.Fatalf("write asset: %v", err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "favicon.ico"), []byte("icon"), 0o644); err != nil {
		t.Fatalf("write favicon: %v", err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "index.html"), []byte("<html>"), 0o644); err != nil {
		t.Fatalf("write index: %v", err)
	}
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{WebDir: webDir}, nil)

	tests := []struct {
		path      string
		wantCache string
		wantBody  string
	}{
		{"/assets/app-abc123.js", "public, max-age=31536000, immutable", "console.log(1)"},
		{"/favicon.ico", "no-cache", "icon"},
		{"/deep/link", "no-cache", "<html>"},
	}
	for _, tc := range tests {
		t.Run(tc.path, func(t *testing.T) {
			rec := do(t, s, http.MethodGet, tc.path, "")
			if rec.Code != http.StatusOK {
				t.Fatalf("status = %d, want 200", rec.Code)
			}
			if got := rec.Header().Get("Cache-Control"); got != tc.wantCache {
				t.Errorf("Cache-Control = %q, want %q", got, tc.wantCache)
			}
			if rec.Body.String() != tc.wantBody {
				t.Errorf("body = %q, want %q", rec.Body.String(), tc.wantBody)
			}
		})
	}
}

// TestStaticDirectoryPathFallsBackToIndex asserts a request for a real directory
// serves the SPA shell rather than a directory listing.
func TestStaticDirectoryPathFallsBackToIndex(t *testing.T) {
	webDir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(webDir, "assets"), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "index.html"), []byte("<html>shell"), 0o644); err != nil {
		t.Fatalf("write index: %v", err)
	}
	s := NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, Config{WebDir: webDir}, nil)

	rec := do(t, s, http.MethodGet, "/assets/", "")
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), "shell") {
		t.Errorf("status=%d body=%q, want the SPA shell", rec.Code, rec.Body.String())
	}
}

// --- clientIP ---

// TestClientIPMultiValueForwardedFor asserts only the original client (leftmost
// hop) is logged when a chain of proxies appends to X-Forwarded-For.
func TestClientIPMultiValueForwardedFor(t *testing.T) {
	tests := []struct {
		name       string
		xff        string
		remoteAddr string
		want       string
	}{
		{"chain of proxies", "203.0.113.7, 70.41.3.18, 150.172.238.178", "10.0.0.1:1234", "203.0.113.7"},
		{"chain without spaces", "203.0.113.7,70.41.3.18", "10.0.0.1:1234", "203.0.113.7"},
		{"leading comma falls through to the whole value", ",203.0.113.7", "10.0.0.1:1234", ",203.0.113.7"},
		{"remote addr without a port", "", "unix-socket", "unix-socket"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodGet, "/", nil)
			r.RemoteAddr = tc.remoteAddr
			if tc.xff != "" {
				r.Header.Set("X-Forwarded-For", tc.xff)
			}
			if got := clientIP(r); got != tc.want {
				t.Errorf("clientIP() = %q, want %q", got, tc.want)
			}
		})
	}
}

// --- task deletion error paths ---

func TestDeleteTaskStoreErrors(t *testing.T) {
	terminal := &store.Task{ID: "t1", Status: store.StatusSucceeded}

	t.Run("get task fails", func(t *testing.T) {
		st := &fakeStore{getErr: errors.New("database is locked")}
		s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})
		rec := do(t, s, http.MethodDelete, "/api/tasks/t1", "")
		if rec.Code != http.StatusInternalServerError {
			t.Fatalf("status = %d, want 500; body=%s", rec.Code, rec.Body.String())
		}
		if !strings.Contains(rec.Body.String(), "get task") {
			t.Errorf("body = %s, want it to name the failing step", rec.Body.String())
		}
	})

	t.Run("concurrent modification maps to 409", func(t *testing.T) {
		st := &fakeStore{tasks: []*store.Task{terminal}, deleteErr: store.ErrNotFound}
		s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})
		rec := do(t, s, http.MethodDelete, "/api/tasks/t1", "")
		if rec.Code != http.StatusConflict {
			t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
		}
		if !strings.Contains(rec.Body.String(), "modified concurrently") {
			t.Errorf("body = %s, want the TOCTOU message", rec.Body.String())
		}
	})

	t.Run("delete fails", func(t *testing.T) {
		st := &fakeStore{tasks: []*store.Task{terminal}, deleteErr: errors.New("disk full")}
		s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})
		rec := do(t, s, http.MethodDelete, "/api/tasks/t1", "")
		if rec.Code != http.StatusInternalServerError {
			t.Fatalf("status = %d, want 500; body=%s", rec.Code, rec.Body.String())
		}
	})
}

// TestDeleteTaskRemovesRawFile asserts the raw file is cleaned up with the row,
// and that an already-missing file is not treated as an error.
func TestDeleteTaskRemovesRawFile(t *testing.T) {
	raw := filepath.Join(t.TempDir(), "raw.txt")
	if err := os.WriteFile(raw, []byte("content"), 0o644); err != nil {
		t.Fatalf("write raw: %v", err)
	}
	st := &fakeStore{tasks: []*store.Task{
		{ID: "t1", Status: store.StatusSucceeded, RawPath: raw},
		{ID: "t2", Status: store.StatusFailed, RawPath: filepath.Join(t.TempDir(), "gone.txt")},
	}}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	if rec := do(t, s, http.MethodDelete, "/api/tasks/t1", ""); rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
	if _, err := os.Stat(raw); !os.IsNotExist(err) {
		t.Errorf("raw file still present after delete: %v", err)
	}
	// A task whose raw file has already vanished must still delete cleanly.
	if rec := do(t, s, http.MethodDelete, "/api/tasks/t2", ""); rec.Code != http.StatusNoContent {
		t.Errorf("status = %d, want 204 when the raw file is already gone", rec.Code)
	}
}

// --- list tasks error path ---

func TestListTasksStoreError(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &failingTaskStore{err: errors.New("database is locked")}, &fakeBridge{})
	rec := do(t, s, http.MethodGet, "/api/tasks", "")
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "list tasks") {
		t.Errorf("body = %s, want it to name the failing step", rec.Body.String())
	}
}

// failingTaskStore fails every read, modelling a broken database.
type failingTaskStore struct{ err error }

func (f *failingTaskStore) GetTask(context.Context, string) (*store.Task, error) { return nil, f.err }
func (f *failingTaskStore) ListTasks(context.Context, store.ListFilter) ([]*store.Task, error) {
	return nil, f.err
}
func (f *failingTaskStore) ListTasksPaged(context.Context, store.PagedListFilter) (*store.ListResult, error) {
	return nil, f.err
}
func (f *failingTaskStore) DeleteTask(context.Context, string) error { return f.err }
