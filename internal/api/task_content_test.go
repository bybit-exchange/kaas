package api

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"

	"github.com/bybit-exchange/kaas/internal/store"
)

// errStoreDown simulates the task store being unavailable.
var errStoreDown = errors.New("store unavailable")

// contentResponse mirrors the JSON body of GET /api/tasks/{id}/content.
type contentResponse struct {
	Content   string `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// writeRaw creates a raw file under <kb>/raw and returns its path.
func writeRaw(t *testing.T, kb, name, content string) string {
	t.Helper()
	dir := filepath.Join(kb, "raw")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir raw: %v", err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write raw file: %v", err)
	}
	return path
}

// contentServer builds a server whose store holds a single task, letting the
// caller point RawPath wherever the test needs.
func contentServer(t *testing.T, rawPath func(kb string) string) (*Server, string) {
	t.Helper()
	st := &fakeStore{}
	s, kb := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})
	st.tasks = []*store.Task{{
		ID:      "t1",
		Status:  store.StatusSucceeded,
		RawPath: rawPath(kb),
	}}
	return s, kb
}

func TestTaskContentReturnsFile(t *testing.T) {
	body := "# Notes\nhello 世界\n"
	s, _ := contentServer(t, func(kb string) string { return writeRaw(t, kb, "t1.md", body) })

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var resp contentResponse
	mustJSON(t, rec, &resp)
	if resp.Content != body {
		t.Errorf("content = %q, want %q", resp.Content, body)
	}
	if resp.Size != int64(len(body)) {
		t.Errorf("size = %d, want %d", resp.Size, len(body))
	}
	if resp.Truncated {
		t.Error("truncated = true, want false for a small file")
	}
}

func TestTaskContentTaskNotFound(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks/missing/content", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "task not found") {
		t.Errorf("unexpected body: %s", rec.Body.String())
	}
}

func TestTaskContentStoreError(t *testing.T) {
	st := &fakeStore{getErr: errStoreDown}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "get task") {
		t.Errorf("unexpected body: %s", rec.Body.String())
	}
}

func TestTaskContentNoRawPath(t *testing.T) {
	s, _ := contentServer(t, func(string) string { return "" })

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "no raw file") {
		t.Errorf("unexpected body: %s", rec.Body.String())
	}
}

// TestTaskContentRejectsPathTraversal asserts a RawPath pointing outside
// <KBDir>/raw is refused even when the file exists and is readable.
func TestTaskContentRejectsPathTraversal(t *testing.T) {
	secret := filepath.Join(t.TempDir(), "secret.txt")
	if err := os.WriteFile(secret, []byte("top secret"), 0o644); err != nil {
		t.Fatalf("write secret: %v", err)
	}

	tests := []struct {
		name    string
		rawPath func(kb string) string
	}{
		{
			name:    "absolute path outside the kb dir",
			rawPath: func(string) string { return secret },
		},
		{
			name:    "dot-dot escape out of raw",
			rawPath: func(kb string) string { return filepath.Join(kb, "raw", "..", "..", "secret.txt") },
		},
		{
			name: "sibling directory sharing the raw prefix",
			rawPath: func(kb string) string {
				// <kb>/rawdata must not pass a naive prefix check on <kb>/raw.
				dir := filepath.Join(kb, "rawdata")
				if err := os.MkdirAll(dir, 0o755); err != nil {
					t.Fatalf("mkdir: %v", err)
				}
				p := filepath.Join(dir, "x.md")
				if err := os.WriteFile(p, []byte("nope"), 0o644); err != nil {
					t.Fatalf("write: %v", err)
				}
				return p
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s, _ := contentServer(t, tt.rawPath)

			rec := do(t, s, "GET", "/api/tasks/t1/content", "")

			if rec.Code != http.StatusForbidden {
				t.Fatalf("status = %d, want 403; body=%s", rec.Code, rec.Body.String())
			}
			if strings.Contains(rec.Body.String(), "top secret") {
				t.Error("file contents leaked through a rejected request")
			}
		})
	}
}

func TestTaskContentFileMissingOnDisk(t *testing.T) {
	s, _ := contentServer(t, func(kb string) string {
		return filepath.Join(kb, "raw", "gone.md")
	})

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "file not found") {
		t.Errorf("unexpected body: %s", rec.Body.String())
	}
}

// TestTaskContentTruncatesLargeFile asserts files over the 1 MiB cap come back
// flagged as truncated, with size reporting the real file length.
func TestTaskContentTruncatesLargeFile(t *testing.T) {
	body := strings.Repeat("a", maxContentBytes+512)
	s, _ := contentServer(t, func(kb string) string { return writeRaw(t, kb, "big.md", body) })

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var resp contentResponse
	mustJSON(t, rec, &resp)
	if !resp.Truncated {
		t.Error("truncated = false, want true for a file over the cap")
	}
	if len(resp.Content) != maxContentBytes {
		t.Errorf("content length = %d, want %d", len(resp.Content), maxContentBytes)
	}
	if resp.Size != int64(len(body)) {
		t.Errorf("size = %d, want the full file size %d", resp.Size, len(body))
	}
}

// TestTaskContentTruncatesOnRuneBoundary asserts a cut landing mid-rune backs
// off to the last valid UTF-8 boundary instead of emitting invalid UTF-8.
func TestTaskContentTruncatesOnRuneBoundary(t *testing.T) {
	// Pad so the 1 MiB cut falls inside the multi-byte rune that follows.
	padding := strings.Repeat("a", maxContentBytes-1)
	body := padding + "世界" + strings.Repeat("b", 100)

	s, _ := contentServer(t, func(kb string) string { return writeRaw(t, kb, "rune.md", body) })

	rec := do(t, s, "GET", "/api/tasks/t1/content", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var resp contentResponse
	mustJSON(t, rec, &resp)
	if !resp.Truncated {
		t.Error("truncated = false, want true")
	}
	if !utf8.ValidString(resp.Content) {
		t.Error("content is not valid UTF-8; truncation did not respect rune boundaries")
	}
	// The split rune must be dropped entirely, leaving only the padding.
	if resp.Content != padding {
		t.Errorf("content length = %d, want %d (padding only)", len(resp.Content), len(padding))
	}
}
