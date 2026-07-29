package api

import (
	"encoding/json"
	"net/http"
	"testing"
)

// --- buildTree ---

func TestBuildTreeEmpty(t *testing.T) {
	tree := buildTree(nil)
	if len(tree) != 0 {
		t.Fatalf("buildTree(nil) = %d nodes, want 0", len(tree))
	}
	tree = buildTree([]wikiArticle{})
	if len(tree) != 0 {
		t.Fatalf("buildTree([]) = %d nodes, want 0", len(tree))
	}
}

func TestBuildTreeSingleRootFile(t *testing.T) {
	articles := []wikiArticle{{Path: "hello.md", Title: "Hello"}}
	tree := buildTree(articles)
	if len(tree) != 1 {
		t.Fatalf("got %d root nodes, want 1", len(tree))
	}
	n := tree[0]
	if n.IsDir {
		t.Fatalf("expected file node, got dir")
	}
	if n.Name != "hello" {
		t.Errorf("name = %q, want %q", n.Name, "hello")
	}
	if n.Path != "hello.md" {
		t.Errorf("path = %q, want %q", n.Path, "hello.md")
	}
	if n.Title != "Hello" {
		t.Errorf("title = %q, want %q", n.Title, "Hello")
	}
}

func TestBuildTreeNestedDirs(t *testing.T) {
	// guide/sub/file.md should produce 3 levels: guide -> sub -> file
	articles := []wikiArticle{{Path: "guide/sub/file.md", Title: "Deep File"}}
	tree := buildTree(articles)

	if len(tree) != 1 {
		t.Fatalf("got %d root nodes, want 1", len(tree))
	}
	guideDir := tree[0]
	if !guideDir.IsDir || guideDir.Name != "guide" || guideDir.Path != "guide" {
		t.Fatalf("expected guide dir, got %+v", guideDir)
	}
	if len(guideDir.Children) != 1 {
		t.Fatalf("guide has %d children, want 1", len(guideDir.Children))
	}
	subDir := guideDir.Children[0]
	if !subDir.IsDir || subDir.Name != "sub" || subDir.Path != "guide/sub" {
		t.Fatalf("expected sub dir, got %+v", subDir)
	}
	if len(subDir.Children) != 1 {
		t.Fatalf("sub has %d children, want 1", len(subDir.Children))
	}
	fileNode := subDir.Children[0]
	if fileNode.IsDir {
		t.Fatal("expected file node at leaf")
	}
	if fileNode.Name != "file" || fileNode.Path != "guide/sub/file.md" || fileNode.Title != "Deep File" {
		t.Errorf("file node wrong: %+v", fileNode)
	}
}

// --- countFiles ---

func TestCountFilesRecursive(t *testing.T) {
	// dir with 2 direct files and subdir with 3 files -> parent fileCount = 5
	articles := []wikiArticle{
		{Path: "docs/a.md", Title: "A"},
		{Path: "docs/b.md", Title: "B"},
		{Path: "docs/sub/x.md", Title: "X"},
		{Path: "docs/sub/y.md", Title: "Y"},
		{Path: "docs/sub/z.md", Title: "Z"},
	}
	tree := buildTree(articles)
	total := countFiles(tree)

	if total != 5 {
		t.Fatalf("total = %d, want 5", total)
	}
	if len(tree) != 1 {
		t.Fatalf("expected 1 root dir, got %d", len(tree))
	}
	docs := tree[0]
	if docs.FileCount != 5 {
		t.Errorf("docs.FileCount = %d, want 5", docs.FileCount)
	}
	// Find the sub directory
	var sub *wikiTreeNode
	for i := range docs.Children {
		if docs.Children[i].IsDir && docs.Children[i].Name == "sub" {
			sub = &docs.Children[i]
			break
		}
	}
	if sub == nil {
		t.Fatal("sub dir not found")
	}
	if sub.FileCount != 3 {
		t.Errorf("sub.FileCount = %d, want 3", sub.FileCount)
	}
}

// --- sortTree ---

func TestSortTreeDirsBeforeFiles(t *testing.T) {
	articles := []wikiArticle{
		{Path: "zebra.md", Title: "Zebra"},
		{Path: "alpha/one.md", Title: "One"},
		{Path: "beta/two.md", Title: "Two"},
		{Path: "aardvark.md", Title: "Aardvark"},
	}
	tree := buildTree(articles)
	countFiles(tree)
	sortTree(tree)

	// Expected order: alpha (dir), beta (dir), aardvark (file), zebra (file)
	if len(tree) != 4 {
		t.Fatalf("got %d root nodes, want 4", len(tree))
	}
	// First two must be dirs, sorted alphabetically
	if !tree[0].IsDir || tree[0].Name != "alpha" {
		t.Errorf("tree[0] = %+v, want alpha dir", tree[0])
	}
	if !tree[1].IsDir || tree[1].Name != "beta" {
		t.Errorf("tree[1] = %+v, want beta dir", tree[1])
	}
	// Last two must be files, sorted alphabetically
	if tree[2].IsDir || tree[2].Name != "aardvark" {
		t.Errorf("tree[2] = %+v, want aardvark file", tree[2])
	}
	if tree[3].IsDir || tree[3].Name != "zebra" {
		t.Errorf("tree[3] = %+v, want zebra file", tree[3])
	}
}

// --- directory path uniqueness ---

func TestBuildTreeDirPathUniqueness(t *testing.T) {
	// guide/intro/ and api/intro/ should have distinct paths
	articles := []wikiArticle{
		{Path: "guide/intro/start.md", Title: "Start"},
		{Path: "api/intro/overview.md", Title: "Overview"},
	}
	tree := buildTree(articles)

	if len(tree) != 2 {
		t.Fatalf("got %d root nodes, want 2", len(tree))
	}
	paths := make(map[string]bool)
	for _, n := range tree {
		if !n.IsDir {
			t.Fatalf("expected dir node at root, got %+v", n)
		}
		paths[n.Path] = true
		for _, child := range n.Children {
			if child.IsDir {
				paths[child.Path] = true
			}
		}
	}
	if !paths["guide/intro"] {
		t.Error("missing path guide/intro")
	}
	if !paths["api/intro"] {
		t.Error("missing path api/intro")
	}
	if paths["intro"] {
		t.Error("ambiguous bare 'intro' path should not exist")
	}
}

// --- handleListWiki HTTP endpoint with omitempty verification ---

func TestHandleListWikiTreeOmitempty(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "guide/intro.md", "# Intro\n\nbody")
	writeWiki(t, kb, "readme.md", "# Readme\n\ncontent")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	// Parse raw JSON to check omitempty behavior
	var raw struct {
		Tree []json.RawMessage `json:"tree"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &raw); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	for _, nodeBytes := range raw.Tree {
		var m map[string]any
		if err := json.Unmarshal(nodeBytes, &m); err != nil {
			t.Fatalf("unmarshal node: %v", err)
		}
		isDir, _ := m["isDir"].(bool)
		if isDir {
			// Dir nodes should have fileCount but NOT title (omitempty)
			if _, has := m["title"]; has {
				t.Errorf("dir node has title key (should be omitted): %s", nodeBytes)
			}
			if _, has := m["fileCount"]; !has {
				t.Errorf("dir node missing fileCount: %s", nodeBytes)
			}
		} else {
			// File nodes should have title but NOT fileCount (omitempty)
			if _, has := m["fileCount"]; has {
				t.Errorf("file node has fileCount key (should be omitted): %s", nodeBytes)
			}
			if _, has := m["title"]; !has {
				t.Errorf("file node missing title: %s", nodeBytes)
			}
		}
	}
}

func TestHandleListWikiTreeStructure(t *testing.T) {
	s, kb := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})
	writeWiki(t, kb, "guide/deep/nested.md", "# Nested\n\nbody")
	writeWiki(t, kb, "guide/top.md", "# Top\n\nbody")
	writeWiki(t, kb, "standalone.md", "# Standalone\n\nbody")

	rec := do(t, s, "GET", "/api/wiki", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var out struct {
		Tree []wikiTreeNode `json:"tree"`
	}
	mustJSON(t, rec, &out)

	// Expect: guide dir (sorted first), then standalone file
	if len(out.Tree) != 2 {
		t.Fatalf("got %d root nodes, want 2: %+v", len(out.Tree), out.Tree)
	}
	guide := out.Tree[0]
	if !guide.IsDir || guide.Name != "guide" {
		t.Fatalf("first node should be guide dir: %+v", guide)
	}
	if guide.FileCount != 2 {
		t.Errorf("guide.FileCount = %d, want 2", guide.FileCount)
	}
	standalone := out.Tree[1]
	if standalone.IsDir || standalone.Name != "standalone" {
		t.Fatalf("second node should be standalone file: %+v", standalone)
	}
}
