package api

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Containment of the wiki dir against symlinks. Lexical traversal ("..",
// absolute paths) is covered by TestWikiFileTraversalRejected in api_test.go.

// newTestServerWithLog mirrors newTestServer but captures the server log, so a
// test can assert on what an operator would see.
func newTestServerWithLog(t *testing.T, buf *bytes.Buffer) (*Server, string) {
	t.Helper()
	kb := t.TempDir()
	cfg := Config{KBDir: kb, Model: "test-model", Upload: testUploadConf()}
	return NewServer(&fakeQueue{}, &fakeStore{}, nil, &fakeBridge{}, cfg, testLogger(buf)), kb
}

// --- handleWikiFile: symlinks may not escape the wiki dir ---

func TestHandleWikiFile_RejectsSymlinkEscape(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "ok.md", "# ok")

	outside := t.TempDir()
	secret := filepath.Join(outside, "secret.md")
	if err := os.WriteFile(secret, []byte("TOP SECRET"), 0o600); err != nil {
		t.Fatal(err)
	}

	wikiDir := filepath.Join(kb, "wiki")
	// A symlink to a file outside the wiki dir, and a symlink to the whole
	// outside dir: both are lexically clean paths under wikiDir.
	if err := os.Symlink(secret, filepath.Join(wikiDir, "leak.md")); err != nil {
		t.Skipf("symlinks unsupported on this platform: %v", err)
	}
	if err := os.Symlink(outside, filepath.Join(wikiDir, "out")); err != nil {
		t.Fatal(err)
	}

	for _, rel := range []string{"leak.md", "out/secret.md"} {
		rec := do(t, s, "GET", "/api/wiki/file?path="+rel, "")
		if rec.Code == 200 {
			t.Errorf("path=%q: status = 200, want a rejection; body=%s", rel, rec.Body.String())
		}
		if strings.Contains(rec.Body.String(), "TOP SECRET") {
			t.Errorf("path=%q: leaked file content through a symlink out of the wiki dir", rel)
		}
	}
}

// --- handleWikiFile: relative symlinks that stay inside the wiki dir work ---

func TestHandleWikiFile_AllowsInternalSymlink(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "notes/real.md", "# Real\n\nreal body")

	wikiDir := filepath.Join(kb, "wiki")
	// Relative target: it resolves inside the wiki dir at every step, so it is
	// served. An absolute target is refused even when it lands inside the tree,
	// because an absolute path is by definition outside the confined root.
	if err := os.Symlink(filepath.Join("notes", "real.md"), filepath.Join(wikiDir, "alias.md")); err != nil {
		t.Skipf("symlinks unsupported on this platform: %v", err)
	}

	rec := do(t, s, "GET", "/api/wiki/file?path=alias.md", "")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out wikiFileResponse
	mustJSON(t, rec, &out)
	if !strings.Contains(out.Content, "real body") {
		t.Errorf("content = %q, want it to contain %q", out.Content, "real body")
	}
}

// --- handleListWiki: symlinked articles are not listed ---

func TestHandleListWiki_SkipsSymlinks(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "real.md", "---\ntitle: Real\n---\n# Real")

	outside := t.TempDir()
	secret := filepath.Join(outside, "secret.md")
	if err := os.WriteFile(secret, []byte("---\ntitle: TOP SECRET\n---\nbody"), 0o600); err != nil {
		t.Fatal(err)
	}
	wikiDir := filepath.Join(kb, "wiki")
	if err := os.Symlink(secret, filepath.Join(wikiDir, "leak.md")); err != nil {
		t.Skipf("symlinks unsupported on this platform: %v", err)
	}

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "TOP SECRET") {
		t.Errorf("tree leaked the title of a file outside the wiki dir: %s", rec.Body.String())
	}
	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)
	if len(out.Tree) != 1 {
		t.Fatalf("got %d root nodes, want 1 (only real.md); body=%s", len(out.Tree), rec.Body.String())
	}
}

// --- handleListWiki: a skipped symlink is diagnosable from the log ---

func TestHandleListWiki_LogsSkippedSymlink(t *testing.T) {
	var buf bytes.Buffer
	s, kb := newTestServerWithLog(t, &buf)
	writeWiki(t, kb, "real.md", "# Real")

	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(kb, "wiki", "linked-notes")); err != nil {
		t.Skipf("symlinks unsupported on this platform: %v", err)
	}

	if rec := do(t, s, "GET", "/api/wiki", ""); rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	logged := buf.String()
	if !strings.Contains(logged, "linked-notes") {
		t.Errorf("log does not name the skipped symlink, so a vanished article is undiagnosable; log=%s", logged)
	}
}

// --- handleWikiFile: the real cause of a 400 reaches the log, not the client ---

func TestHandleWikiFile_LogsCauseKeepsResponseGeneric(t *testing.T) {
	var buf bytes.Buffer
	s, kb := newTestServerWithLog(t, &buf)
	writeWiki(t, kb, "real.md", "# Real")

	outside := t.TempDir()
	secret := filepath.Join(outside, "secret.md")
	if err := os.WriteFile(secret, []byte("TOP SECRET"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(secret, filepath.Join(kb, "wiki", "leak.md")); err != nil {
		t.Skipf("symlinks unsupported on this platform: %v", err)
	}

	rec := do(t, s, "GET", "/api/wiki/file?path=leak.md", "")
	if rec.Code != 400 {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}

	// The client learns nothing about the filesystem.
	if body := rec.Body.String(); strings.Contains(body, outside) || strings.Contains(body, "escapes") {
		t.Errorf("response leaks filesystem detail: %s", body)
	}
	// The operator does.
	logged := buf.String()
	if !strings.Contains(logged, "leak.md") {
		t.Errorf("log does not name the rejected path; log=%s", logged)
	}
	if !strings.Contains(logged, "err=") && !strings.Contains(logged, `"err"`) {
		t.Errorf("log does not carry the underlying error; log=%s", logged)
	}
}
