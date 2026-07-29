package api

import (
	"encoding/json"
	"testing"
)

// --- handleListWiki: tags from frontmatter ---

func TestHandleListWiki_TagsFromFrontmatter(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "tagged.md", "---\ntitle: Tagged Article\ntags:\n  - golang\n  - testing\n---\n# Tagged Article\n\nbody")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)

	if len(out.Tree) != 1 {
		t.Fatalf("got %d root nodes, want 1", len(out.Tree))
	}
	node := out.Tree[0]
	if node.IsDir {
		t.Fatal("expected file node, got dir")
	}
	if len(node.Tags) != 2 {
		t.Fatalf("tags len = %d, want 2; tags=%v", len(node.Tags), node.Tags)
	}
	if node.Tags[0] != "golang" || node.Tags[1] != "testing" {
		t.Errorf("tags = %v, want [golang testing]", node.Tags)
	}
}

// --- handleListWiki: no tags when no frontmatter ---

func TestHandleListWiki_NoTags(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "plain.md", "# Plain Article\n\nno frontmatter here")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	// Parse raw JSON to verify tags field is absent (omitempty).
	var raw struct {
		Tree []json.RawMessage `json:"tree"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &raw); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(raw.Tree) != 1 {
		t.Fatalf("got %d root nodes, want 1", len(raw.Tree))
	}

	var m map[string]any
	if err := json.Unmarshal(raw.Tree[0], &m); err != nil {
		t.Fatalf("unmarshal node: %v", err)
	}
	if _, has := m["tags"]; has {
		t.Errorf("tags field should be absent for file without frontmatter, got %v", m["tags"])
	}
}

// --- handleListWiki: title priority ---

func TestHandleListWiki_TitlePriority(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	// Case 1: frontmatter title + H1 → frontmatter title wins
	writeWiki(t, kb, "fm-title.md", "---\ntitle: FM Title\n---\n# H1 Title\n\nbody")
	// Case 2: no frontmatter title, has H1 → H1 wins
	writeWiki(t, kb, "h1-title.md", "# H1 Only Title\n\nbody")
	// Case 3: no frontmatter, no H1 → filename stem
	writeWiki(t, kb, "filename-stem.md", "just some content without any heading")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)

	if len(out.Tree) != 3 {
		t.Fatalf("got %d root nodes, want 3: %+v", len(out.Tree), out.Tree)
	}

	// Build a lookup map by path for deterministic assertions.
	byPath := make(map[string]wikiTreeNode)
	for _, n := range out.Tree {
		byPath[n.Path] = n
	}

	// Case 1: frontmatter title takes priority
	if n, ok := byPath["fm-title.md"]; !ok {
		t.Fatal("fm-title.md not found in tree")
	} else if n.Title != "FM Title" {
		t.Errorf("fm-title.md title = %q, want %q (frontmatter title should win over H1)", n.Title, "FM Title")
	}

	// Case 2: H1 title when no frontmatter title
	if n, ok := byPath["h1-title.md"]; !ok {
		t.Fatal("h1-title.md not found in tree")
	} else if n.Title != "H1 Only Title" {
		t.Errorf("h1-title.md title = %q, want %q (H1 should be used when no frontmatter title)", n.Title, "H1 Only Title")
	}

	// Case 3: filename stem as fallback
	if n, ok := byPath["filename-stem.md"]; !ok {
		t.Fatal("filename-stem.md not found in tree")
	} else if n.Title != "filename-stem" {
		t.Errorf("filename-stem.md title = %q, want %q (filename stem should be fallback)", n.Title, "filename-stem")
	}
}

// --- handleListWiki: cache hit returns same data without rebuild ---

func TestHandleListWiki_Cache(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "cached.md", "---\ntitle: Cached\ntags:\n  - cache\n---\n# Cached\n\nbody")

	// First request: populates the cache.
	rec1 := do(t, s, "GET", "/api/wiki", "")
	if rec1.Code != 200 {
		t.Fatalf("first request status = %d, want 200", rec1.Code)
	}

	// Second request: should hit the cache and return identical data.
	rec2 := do(t, s, "GET", "/api/wiki", "")
	if rec2.Code != 200 {
		t.Fatalf("second request status = %d, want 200", rec2.Code)
	}

	// Responses must be byte-for-byte identical (same JSON output from cache).
	if rec1.Body.String() != rec2.Body.String() {
		t.Errorf("cache miss: responses differ.\nfirst:  %s\nsecond: %s", rec1.Body.String(), rec2.Body.String())
	}

	// Verify the cache was actually populated (internal state check).
	s.wikiC.mu.RLock()
	defer s.wikiC.mu.RUnlock()
	if s.wikiC.tree == nil {
		t.Error("wikiC.tree is nil after two requests; cache not populated")
	}
	if s.wikiC.builtAt.IsZero() {
		t.Error("wikiC.builtAt is zero; cache not populated")
	}
}
