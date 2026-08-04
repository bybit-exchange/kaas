// Package kbpath resolves a derived knowledge base's directory from a
// client-supplied slug.
//
// The slug arrives from MCP tool calls and HTTP query strings, so it is
// untrusted input to a path join. Resolve performs a symlink-resolving
// containment check: it resolves the target path with filepath.EvalSymlinks
// and requires the result to reside strictly under the (un-resolved) derived/
// base directory. A symlink planted at <root>/derived/<slug> or at
// <root>/derived/ itself therefore cannot escape the KB root.
//
// This mirrors resolve_kb_dir in py/src/kb_ai/derive/_layout.py, which uses
// the same strategy (Path.resolve + is_relative_to). Both layers are
// independent gates: Go validates and resolves the slug, returning a
// canonical path; Python's KBStore receives that path and constrains reads
// within it.
package kbpath

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Sentinel errors callers map to their own status codes.
var (
	// ErrInvalidSlug is returned when a slug is not a single safe path segment.
	ErrInvalidSlug = errors.New("kbpath: invalid derived-kb slug")
	// ErrUnknownKB is returned when no derived knowledge base has that slug.
	// Never a fallback to the root KB: answering from the wrong corpus silently
	// is worse than an error.
	ErrUnknownKB = errors.New("kbpath: unknown derived knowledge base")
)

// DerivedDirName is the subdirectory of a KB holding its derived knowledge bases.
const DerivedDirName = "derived"

// manifestName marks a directory as one derive created. A directory under
// derived/ without it is not a derived KB.
const manifestName = "manifest.json"

// slugRe must stay in step with SLUG_RE in py/src/kb_ai/derive/_layout.py.
var slugRe = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,39}$`)

// ValidSlug reports whether slug is a single safe path segment.
func ValidSlug(slug string) bool {
	return slugRe.MatchString(slug)
}

// Resolve returns the canonical path for the given KB root and optional slug.
//
// Empty slug: returns the resolved root path (canonical symlinks followed).
// Non-empty slug: validates the slug and verifies:
//   - the slug passes lexical validation (ErrInvalidSlug on failure),
//   - EvalSymlinks of the target stays strictly under the un-resolved derived/
//     base so a symlink at derived/<slug> or at derived/ itself cannot reach
//     outside the KB root (ErrUnknownKB on containment failure),
//   - manifest.json is present in the resolved directory (ErrUnknownKB if not).
//
// The returned path for a non-empty slug is the EvalSymlinks-resolved target of
// <root>/derived/<slug>. When the slug entry is a symlink to a sibling directory
// inside derived/ (the accepted case in TestResolveSymlinkContainment/
// slug_symlinked_to_sibling_inside), the sibling's canonical path is returned
// rather than <resolved-root>/derived/<slug>.
//
// root is absolutised with filepath.Abs before symlink resolution so a relative
// root (e.g. "./mykb") produces a consistent absolute path matching what
// Python's Path.resolve() returns. Tilde (~) expansion is not performed;
// callers that accept shell input must expand "~" before calling Resolve.
//
// When root does not exist yet (e.g. during tests) EvalSymlinks fails silently
// and the absolutised root is returned — this only matters for empty slug since
// any non-empty slug would fail the subsequent EvalSymlinks of the target.
func Resolve(root, slug string) (string, error) {
	// Absolutise before resolving symlinks so a relative root ("./kb") and
	// Python's Path.resolve() name the same KB with the same string. Abs errors
	// only when os.Getwd() fails (an unrecoverable OS condition); fall back to
	// the original root in that unlikely case.
	abs := root
	if a, err := filepath.Abs(root); err == nil {
		abs = a
	}

	// Resolve root once so the base prefix used for containment is symlink-free.
	// Silent fallback keeps a not-yet-created root from erroring on empty slug.
	resolvedRoot := abs
	if r, err := filepath.EvalSymlinks(abs); err == nil {
		resolvedRoot = r
	}

	if slug == "" {
		return resolvedRoot, nil
	}
	if !ValidSlug(slug) {
		return "", fmt.Errorf("%w: %q", ErrInvalidSlug, slug)
	}

	// base is a plain path join — deliberately not resolved — so a symlink
	// planted at <root>/derived/ is caught: its resolved target cannot share
	// the base prefix.
	base := filepath.Join(resolvedRoot, DerivedDirName)
	resolved, err := filepath.EvalSymlinks(filepath.Join(base, slug))
	if err != nil {
		// Path does not exist or a dangling symlink.
		return "", fmt.Errorf("%w: %q", ErrUnknownKB, slug)
	}
	// Containment: resolved path must be strictly under base (not equal to it).
	if !strings.HasPrefix(resolved, base+string(filepath.Separator)) {
		return "", fmt.Errorf("%w: %q", ErrUnknownKB, slug)
	}
	if _, err := os.Stat(filepath.Join(resolved, manifestName)); err != nil {
		return "", fmt.Errorf("%w: %q", ErrUnknownKB, slug)
	}
	return resolved, nil
}

// ListSlugs returns the slugs of every derived knowledge base under root,
// sorted. An absent derived/ directory yields an empty slice, not an error.
func ListSlugs(root string) ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(root, DerivedDirName))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("kbpath: read derived dir: %w", err)
	}
	var slugs []string
	for _, e := range entries {
		if !e.IsDir() || !ValidSlug(e.Name()) {
			continue
		}
		if _, err := os.Stat(filepath.Join(root, DerivedDirName, e.Name(), manifestName)); err != nil {
			continue
		}
		slugs = append(slugs, e.Name())
	}
	sort.Strings(slugs)
	return slugs, nil
}
