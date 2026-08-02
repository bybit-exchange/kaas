package api

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Containment of the wiki dir against symlinks. Lexical traversal ("..",
// absolute paths) is covered by TestWikiFileTraversalRejected in api_test.go.

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
