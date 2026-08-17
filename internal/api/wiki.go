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

	"github.com/bybit-exchange/kaas/internal/fadvise"
	"github.com/bybit-exchange/kaas/internal/kbpath"
	"gopkg.in/yaml.v2"
)

// wikiCacheTTL is the maximum age of a cached wiki tree before it is
// unconditionally rebuilt, even if the directory modtime has not changed.
const wikiCacheTTL = 60 * time.Second

// wikiHeadBytes is the maximum number of bytes read from each wiki file
// during tree listing. 4KB is enough for frontmatter in virtually all cases.
const wikiHeadBytes = 4096

// wikiCacheEntry holds one KB's cached wiki tree with dual invalidation:
// directory modtime change triggers an immediate rebuild; TTL expiry guarantees
// eventual consistency even when modtime does not reflect nested changes.
type wikiCacheEntry struct {
	tree    []wikiTreeNode
	builtAt time.Time
	dirMod  time.Time
}

// wikiCache holds one entry per knowledge base, keyed by derived-KB slug ("" for
// the root). A single shared entry would thrash the moment a user switches KBs in
// the selector, and could serve one KB's tree for another's request.
type wikiCache struct {
	mu      sync.RWMutex
	entries map[string]*wikiCacheEntry
}

func (c *wikiCache) get(slug string, dirMod time.Time) ([]wikiTreeNode, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.entries[slug]
	if !ok || e.tree == nil {
		return nil, false
	}
	if !e.dirMod.Equal(dirMod) || time.Since(e.builtAt) >= wikiCacheTTL {
		return nil, false
	}
	return e.tree, true
}

func (c *wikiCache) put(slug string, tree []wikiTreeNode, dirMod time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil {
		c.entries = map[string]*wikiCacheEntry{}
	}
	c.entries[slug] = &wikiCacheEntry{tree: tree, builtAt: time.Now(), dirMod: dirMod}
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

// resolveKB maps the request's optional ?kb=<slug> to a knowledge-base root.
//
// The slug reaches us from a browser query string, so it is untrusted input to a
// path join: kbpath validates it lexically and requires the target to hold a
// manifest. An unknown slug answers 400 rather than falling back to the root KB
// (spec H3) — silently answering from the wrong corpus is the failure worth
// avoiding. Returns (dir, slug, true) on success, or writes the error and returns
// ("", "", false). The slug comes back with the directory so a caller that keys
// per-KB state on it does not parse the query string a second time.
func (s *Server) resolveKB(w http.ResponseWriter, r *http.Request) (string, string, bool) {
	slug := r.URL.Query().Get("kb")
	dir, err := kbpath.Resolve(s.cfg.KBDir, slug)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return "", "", false
	}
	return dir, slug, true
}

// handleListWiki serves GET /api/wiki: returns a tree structure of all *.md
// files under KBDir/wiki (or a derived KB's wiki when ?kb=<slug> is set).
// An absent wiki dir is treated as empty.
//
// The response is cached in memory per slug; the cache is invalidated when either:
//   - the wiki directory's modtime changes (immediate rebuild), or
//   - 60 seconds have elapsed since the last build (TTL expiry).
func (s *Server) handleListWiki(w http.ResponseWriter, r *http.Request) {
	kbDir, slug, ok := s.resolveKB(w, r)
	if !ok {
		return
	}
	wikiDir := filepath.Join(kbDir, "wiki")

	// Stat the directory to detect modtime changes.
	dirInfo, statErr := os.Stat(wikiDir)

	// Fast path: serve from cache if still valid.
	if statErr == nil {
		if tree, hit := s.wikiC.get(slug, dirInfo.ModTime()); hit {
			writeJSON(w, http.StatusOK, map[string]any{"tree": tree})
			return
		}
	}

	// Slow path: full rebuild.
	articles := make([]wikiArticle, 0)
	err := filepath.WalkDir(wikiDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		// Regular files only: a symlink here could point outside the wiki dir,
		// and listing it would leak the target's title through the tree while
		// handleWikiFile refuses to serve it. (WalkDir never descends into
		// symlinked directories, so only file entries need this check.)
		if !d.Type().IsRegular() {
			// Say so, or a curated wiki dir loses articles from the tree with no
			// way to find out why. A symlinked directory costs its whole subtree,
			// since WalkDir will not follow it either.
			if d.Type()&fs.ModeSymlink != 0 {
				s.logger.Warn("wiki: skipping symlink, articles under it are not listed", "path", path)
			}
			return nil
		}
		if !strings.HasSuffix(strings.ToLower(d.Name()), ".md") {
			return nil
		}
		rel, rerr := filepath.Rel(wikiDir, path)
		if rerr != nil {
			return rerr
		}
		relSlash := filepath.ToSlash(rel)
		buf, readErr := fadvise.ReadHeadAndEvict(path, wikiHeadBytes)
		if readErr != nil {
			articles = append(articles, wikiArticle{
				Path:  relSlash,
				Title: stem(rel),
			})
			return nil
		}
		meta, body := parseFrontmatter(buf)
		title := meta.Title
		if title == "" {
			// Partial read (len==wikiHeadBytes) with zero meta: frontmatter
			// may exceed 4KB or be unparseable. Fall back to stem to avoid
			// misidentifying YAML comments as H1 headings.
			if len(buf) == wikiHeadBytes && isZeroFrontmatter(meta) {
				title = stem(rel)
			} else {
				title = titleFromBytes(body, relSlash)
			}
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
		s.wikiC.put(slug, tree, di.ModTime())
	}

	writeJSON(w, http.StatusOK, map[string]any{"tree": tree})
}

// handleWikiFile serves GET /api/wiki/file?path=<rel>: the raw markdown of one
// article. The path is confined to the wiki dir: "..", absolute paths and
// symlinks leading out of the tree are all rejected.
func (s *Server) handleWikiFile(w http.ResponseWriter, r *http.Request) {
	rel := r.URL.Query().Get("path")
	if rel == "" {
		writeErr(w, http.StatusBadRequest, "path is required")
		return
	}
	// Reject absolute paths and ".." climbs up front, so a malformed path always
	// answers 400 instead of depending on which directories happen to exist.
	if !filepath.IsLocal(rel) {
		writeErr(w, http.StatusBadRequest, "invalid path")
		return
	}
	rel = filepath.Clean(rel)

	kbDir, _, ok := s.resolveKB(w, r)
	if !ok {
		return
	}
	wikiDir := filepath.Join(kbDir, "wiki")
	// os.Root enforces containment per path element at the syscall level, which
	// a lexical check cannot do: it also refuses a symlink inside the wiki dir
	// that points outside it, and is not subject to check-then-open races.
	root, err := os.OpenRoot(wikiDir)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			writeErr(w, http.StatusNotFound, "article not found")
			return
		}
		writeErr(w, http.StatusInternalServerError, "open wiki dir: "+err.Error())
		return
	}
	defer root.Close()

	content, err := root.ReadFile(rel)
	if errors.Is(err, fs.ErrNotExist) {
		writeErr(w, http.StatusNotFound, "article not found")
		return
	}
	if err != nil {
		// A path that escapes the wiki dir, a directory, an unreadable file. The
		// response stays generic so it cannot be used to probe the filesystem,
		// but the cause goes to the log: answering 400 hides a genuine
		// server-side fault (broken mount, bad file mode) from 5xx alerting, so
		// an operator needs some way to see it.
		s.logger.Warn("wiki: cannot read article", "path", rel, "err", err)
		writeErr(w, http.StatusBadRequest, "invalid path")
		return
	}
	relClean := filepath.ToSlash(rel)
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

// frontmatter holds the YAML front matter fields we expose via the API.
type frontmatter struct {
	Title   string   `yaml:"title"`
	Tags    []string `yaml:"tags"`
	Sources []string `yaml:"sources"`
	Created string   `yaml:"created"`
}

// isZeroFrontmatter reports whether meta is the zero-value (no fields parsed).
func isZeroFrontmatter(m frontmatter) bool {
	return m.Title == "" && len(m.Tags) == 0 && len(m.Sources) == 0 && m.Created == ""
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
