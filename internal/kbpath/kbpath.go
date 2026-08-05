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
	"encoding/json"
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
// Resolve is deliberately indifferent to whether the KB finished compiling: a
// manifest saying compiled:false resolves like any other. Reaching an incomplete
// KB is a CLI-driven flow — a declined volume gate leaves exactly that state
// (spec F5) — and browsing it simply finds an empty wiki. The listing side is
// stricter: ListSlugs's caller filters uncompiled KBs out of GET /api/derived so
// the KB selector cannot offer one. The asymmetry is intentional; do not "fix" it
// by making Resolve reject uncompiled KBs, or the CLI loses read access to them.
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

// Manifest is the subset of a derived KB's manifest.json that the Go side reads.
// The engine writes many more fields (see _manifest_payload in
// py/src/kb_ai/derive/__init__.py); unknown ones are ignored.
type Manifest struct {
	Slug      string `json:"slug"`
	Topic     string `json:"topic"`
	CreatedAt string `json:"created_at"`
	// Compiled is written true only once the compile pass has finished (spec F3).
	// The manifest itself is written before compiling (spec E1), so compiled=false
	// — or the key missing entirely — marks a derive that never completed: a
	// directory with no wiki/ to browse. It is also the deliberate resting state
	// of a CLI run whose volume gate was declined (spec F5).
	Compiled bool `json:"compiled"`
}

// ReadManifest reads the manifest of the derived KB at dir, as returned by
// Resolve. An absent, unreadable or malformed manifest is an error, so a caller
// can tell "not compiled" from "cannot tell".
func ReadManifest(dir string) (Manifest, error) {
	raw, err := os.ReadFile(filepath.Join(dir, manifestName))
	if err != nil {
		return Manifest{}, fmt.Errorf("kbpath: read manifest: %w", err)
	}
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return Manifest{}, fmt.Errorf("kbpath: parse manifest: %w", err)
	}
	return m, nil
}

// ListSlugs returns the slugs of every derived knowledge base under root,
// sorted. An absent derived/ directory yields an empty slice, not an error.
//
// Membership is decided by Resolve, one entry at a time, so "what is a derived
// KB" is encoded once. Deciding it here independently drifted twice: os.ReadDir
// reports DirEntry.IsDir from an lstat, so a slug symlinked to a sibling inside
// derived/ was skipped while Resolve followed it; and a lexical ValidSlug on the
// on-disk name skipped a "Pricing" directory that Resolve serves for slug
// "pricing" on a case-insensitive filesystem. The listing must not hide a KB
// that ?kb= answers for.
//
// The candidate slug is the lower-cased entry name — the form a client can pass,
// since ValidSlug rejects upper case. Lower-casing is a no-op for a name that is
// already a valid slug, and on a case-sensitive filesystem the lower-cased
// candidate simply fails Resolve, so nothing that cannot be served is listed.
func ListSlugs(root string) ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(root, DerivedDirName))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("kbpath: read derived dir: %w", err)
	}
	seen := make(map[string]struct{}, len(entries))
	var slugs []string
	for _, e := range entries {
		slug := strings.ToLower(e.Name())
		if _, dup := seen[slug]; dup {
			continue
		}
		if _, err := Resolve(root, slug); err != nil {
			continue
		}
		seen[slug] = struct{}{}
		slugs = append(slugs, slug)
	}
	sort.Strings(slugs)
	return slugs, nil
}
