package api

import (
	"bytes"
	"errors"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"gopkg.in/yaml.v2"
)

// wikiCacheTTL is the maximum age of a cached wiki tree before it is
// unconditionally rebuilt, even if the directory modtime has not changed.
const wikiCacheTTL = 60 * time.Second

// wikiCache holds the in-memory cached wiki tree with dual invalidation:
// directory modtime change triggers immediate rebuild; TTL expiry guarantees
// eventual consistency even when modtime does not reflect nested changes.
type wikiCache struct {
	mu      sync.RWMutex
	tree    []wikiTreeNode
	builtAt time.Time
	dirMod  time.Time
}

// wikiArticle is a list entry for a compiled wiki page.
type wikiArticle struct {
	Path  string   `json:"path"`           // path relative to the wiki dir, slash-separated
	Title string   `json:"title"`          // first H1, or the filename stem if none
	Tags  []string `json:"tags,omitempty"` // tags from frontmatter
}

// wikiFileResponse is the body for GET /api/wiki/file.
type wikiFileResponse struct {
	Path    string   `json:"path"`
	Title   string   `json:"title"`
	Tags    []string `json:"tags,omitempty"`
	Sources []string `json:"sources,omitempty"`
	Created string   `json:"created,omitempty"`
	Content string   `json:"content"`
}

// wikiTreeNode represents a node (directory or file) in the wiki tree.
type wikiTreeNode struct {
	Name      string         `json:"name"`                // dir name or file stem (without .md)
	Path      string         `json:"path"`                // relative path used as unique identifier
	Title     string         `json:"title,omitempty"`     // only for files: H1 title
	Tags      []string       `json:"tags,omitempty"`      // only for files: tags from frontmatter
	IsDir     bool           `json:"isDir"`               // whether this node is a directory
	FileCount int            `json:"fileCount,omitempty"` // only for dirs: recursive file count
	Children  []wikiTreeNode `json:"children,omitempty"`  // only for dirs: child nodes
}

// buildTree converts a flat list of wikiArticle into a tree of wikiTreeNode.
func buildTree(articles []wikiArticle) []wikiTreeNode {
	dirs := make(map[string]*wikiTreeNode)
	root := &wikiTreeNode{Children: []wikiTreeNode{}}

	// ensureDir lazily creates directory nodes along the path, returning
	// the node for dirPath. The root virtual node is returned for "." or "".
	var ensureDir func(dirPath string) *wikiTreeNode
	ensureDir = func(dirPath string) *wikiTreeNode {
		if dirPath == "." || dirPath == "" {
			return root
		}
		if n, ok := dirs[dirPath]; ok {
			return n
		}
		parent := filepath.ToSlash(filepath.Dir(dirPath))
		pNode := ensureDir(parent)
		node := &wikiTreeNode{
			Name:     filepath.Base(dirPath),
			Path:     dirPath,
			IsDir:    true,
			Children: []wikiTreeNode{},
		}
		dirs[dirPath] = node
		pNode.Children = append(pNode.Children, *node)
		return node
	}

	for _, a := range articles {
		dir := filepath.ToSlash(filepath.Dir(a.Path))
		parentNode := ensureDir(dir)
		fileNode := wikiTreeNode{
			Name:  stem(a.Path),
			Path:  a.Path,
			Title: a.Title,
			Tags:  a.Tags,
			IsDir: false,
		}
		parentNode.Children = append(parentNode.Children, fileNode)
	}

	// Children are stored by value; appends after a node was copied into its
	// parent's slice won't be reflected. Rebuild from the authoritative dirs map.
	return rebuildChildren(root, dirs)
}

// rebuildChildren recursively reconstructs the tree from the dirs map,
// since slice append after copy means parent copies are stale.
func rebuildChildren(node *wikiTreeNode, dirs map[string]*wikiTreeNode) []wikiTreeNode {
	result := make([]wikiTreeNode, 0, len(node.Children))
	for _, child := range node.Children {
		if child.IsDir {
			if dirNode, ok := dirs[child.Path]; ok {
				rebuilt := wikiTreeNode{
					Name:     dirNode.Name,
					Path:     dirNode.Path,
					IsDir:    true,
					Children: rebuildChildren(dirNode, dirs),
				}
				result = append(result, rebuilt)
			}
		} else {
			// 文件节点通过值拷贝保留全部字段（包括 Title、Tags）。
			// 若未来修改此逻辑为重建文件节点，须确保所有字段被显式赋值。
			result = append(result, child)
		}
	}
	return result
}

// countFiles recursively counts files under each directory node and sets
// FileCount. Returns the total file count for the given slice.
func countFiles(nodes []wikiTreeNode) int {
	total := 0
	for i := range nodes {
		if nodes[i].IsDir {
			nodes[i].FileCount = countFiles(nodes[i].Children)
			total += nodes[i].FileCount
		} else {
			total++
		}
	}
	return total
}

// sortTree recursively sorts nodes: directories first, then files,
// alphabetical by Name within each group.
func sortTree(nodes []wikiTreeNode) {
	sort.SliceStable(nodes, func(i, j int) bool {
		if nodes[i].IsDir != nodes[j].IsDir {
			return nodes[i].IsDir // dirs first
		}
		return nodes[i].Name < nodes[j].Name
	})
	for i := range nodes {
		if nodes[i].IsDir {
			sortTree(nodes[i].Children)
		}
	}
}

// handleListWiki serves GET /api/wiki: returns a tree structure of all *.md
// files under KBDir/wiki. An absent wiki dir is treated as empty.
//
// The response is cached in memory; the cache is invalidated when either:
//   - the wiki directory's modtime changes (immediate rebuild), or
//   - 60 seconds have elapsed since the last build (TTL expiry).
func (s *Server) handleListWiki(w http.ResponseWriter, r *http.Request) {
	wikiDir := filepath.Join(s.cfg.KBDir, "wiki")

	// Stat the directory to detect modtime changes.
	dirInfo, statErr := os.Stat(wikiDir)

	// Fast path: serve from cache if still valid.
	if statErr == nil {
		s.wikiC.mu.RLock()
		if s.wikiC.tree != nil &&
			s.wikiC.dirMod.Equal(dirInfo.ModTime()) &&
			time.Since(s.wikiC.builtAt) < wikiCacheTTL {
			tree := s.wikiC.tree
			s.wikiC.mu.RUnlock()
			writeJSON(w, http.StatusOK, map[string]any{"tree": tree})
			return
		}
		s.wikiC.mu.RUnlock()
	}

	// Slow path: full rebuild.
	articles := make([]wikiArticle, 0)
	err := filepath.WalkDir(wikiDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(strings.ToLower(d.Name()), ".md") {
			return nil
		}
		rel, rerr := filepath.Rel(wikiDir, path)
		if rerr != nil {
			return rerr
		}
		relSlash := filepath.ToSlash(rel)
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			articles = append(articles, wikiArticle{
				Path:  relSlash,
				Title: stem(rel),
			})
			return nil
		}
		meta, body := parseFrontmatter(content)
		title := meta.Title
		if title == "" {
			title = titleFromBytes(body, relSlash)
		}
		articles = append(articles, wikiArticle{
			Path:  relSlash,
			Title: title,
			Tags:  meta.Tags,
		})
		return nil
	})
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		writeErr(w, http.StatusInternalServerError, "list wiki: "+err.Error())
		return
	}
	tree := buildTree(articles)
	countFiles(tree)
	sortTree(tree)

	// Update cache. Re-stat to get the most recent modtime after the walk.
	if di, e := os.Stat(wikiDir); e == nil {
		s.wikiC.mu.Lock()
		s.wikiC.tree = tree
		s.wikiC.builtAt = time.Now()
		s.wikiC.dirMod = di.ModTime()
		s.wikiC.mu.Unlock()
	}

	writeJSON(w, http.StatusOK, map[string]any{"tree": tree})
}

// handleWikiFile serves GET /api/wiki/file?path=<rel>: the raw markdown of one
// article. The path is confined to the wiki dir (traversal is rejected).
func (s *Server) handleWikiFile(w http.ResponseWriter, r *http.Request) {
	rel := r.URL.Query().Get("path")
	if rel == "" {
		writeErr(w, http.StatusBadRequest, "path is required")
		return
	}
	wikiDir := filepath.Join(s.cfg.KBDir, "wiki")
	full, ok := safeJoin(wikiDir, rel)
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid path")
		return
	}
	content, err := os.ReadFile(full)
	if errors.Is(err, fs.ErrNotExist) {
		writeErr(w, http.StatusNotFound, "article not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "read article: "+err.Error())
		return
	}
	relClean := filepath.ToSlash(strings.TrimPrefix(full, wikiDir+string(os.PathSeparator)))
	meta, body := parseFrontmatter(content)
	title := meta.Title
	if title == "" {
		title = titleFromBytes(body, relClean)
	}
	writeJSON(w, http.StatusOK, wikiFileResponse{
		Path:    relClean,
		Title:   title,
		Tags:    meta.Tags,
		Sources: meta.Sources,
		Created: meta.Created,
		Content: string(body),
	})
}

// safeJoin resolves rel under base, rejecting any path that escapes base
// (via "..", absolute paths, or symlink-free traversal). Returns the cleaned
// absolute-ish path and whether it is safe.
func safeJoin(base, rel string) (string, bool) {
	if filepath.IsAbs(rel) {
		return "", false
	}
	cleaned := filepath.Clean(rel)
	// Reject any path that climbs out of base ("..", "../x", "a/../../x").
	if cleaned == ".." || strings.HasPrefix(cleaned, ".."+string(os.PathSeparator)) {
		return "", false
	}
	full := filepath.Join(base, cleaned)
	// Defense in depth: the joined path must still live under base.
	if full != base && !strings.HasPrefix(full, base+string(os.PathSeparator)) {
		return "", false
	}
	return full, true
}

// frontmatter holds the YAML front matter fields we expose via the API.
type frontmatter struct {
	Title   string   `yaml:"title"`
	Tags    []string `yaml:"tags"`
	Sources []string `yaml:"sources"`
	Created string   `yaml:"created"`
}

// parseFrontmatter splits YAML front matter (delimited by "---") from body.
// If no valid front matter is found, meta is zero-value and body is the full content.
func parseFrontmatter(content []byte) (frontmatter, []byte) {
	if !bytes.HasPrefix(bytes.TrimSpace(content), []byte("---")) {
		return frontmatter{}, content
	}
	// Find opening delimiter (skip leading whitespace).
	rest := bytes.TrimLeft(content, " \t\r\n")
	rest = rest[3:] // skip "---"
	// Find closing delimiter.
	raw, body, found := bytes.Cut(rest, []byte("\n---"))
	if !found {
		return frontmatter{}, content
	}
	// Strip leading newline from body.
	body = bytes.TrimLeft(body, "\r\n")

	var meta frontmatter
	_ = yaml.Unmarshal(raw, &meta)
	return meta, body
}


// titleFromBytes extracts the first H1 from already-read content.
func titleFromBytes(b []byte, rel string) string {
	for line := range strings.Lines(string(b)) {
		if t, ok := h1(line); ok {
			return t
		}
	}
	return stem(rel)
}

// h1 returns the heading text if line is a top-level "# " heading.
func h1(line string) (string, bool) {
	line = strings.TrimSpace(line)
	if strings.HasPrefix(line, "# ") {
		return strings.TrimSpace(line[2:]), true
	}
	return "", false
}

// stem returns the filename without directory or .md extension.
func stem(rel string) string {
	base := filepath.Base(rel)
	return strings.TrimSuffix(base, filepath.Ext(base))
}
