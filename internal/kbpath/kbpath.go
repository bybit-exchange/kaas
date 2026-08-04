// Package kbpath resolves a derived knowledge base's directory from a
// client-supplied slug.
//
// The slug arrives from MCP tool calls and HTTP query strings, so it is
// untrusted input to a path join. Validation is lexical here, matching the
// convention in internal/api/wiki.go; the Python layer runs its own
// symlink-resolving check (KBStore._resolve). Duplicating the check is
// deliberate: neither layer should trust the other's input.
package kbpath

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
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

// Resolve returns root for an empty slug, else <root>/derived/<slug>.
//
// Returns ErrInvalidSlug for a slug failing lexical validation and ErrUnknownKB
// when the directory does not exist or holds no manifest.json.
func Resolve(root, slug string) (string, error) {
	if slug == "" {
		return root, nil
	}
	if !ValidSlug(slug) {
		return "", fmt.Errorf("%w: %q", ErrInvalidSlug, slug)
	}
	dir := filepath.Join(root, DerivedDirName, slug)
	if _, err := os.Stat(filepath.Join(dir, manifestName)); err != nil {
		return "", fmt.Errorf("%w: %q", ErrUnknownKB, slug)
	}
	return dir, nil
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
