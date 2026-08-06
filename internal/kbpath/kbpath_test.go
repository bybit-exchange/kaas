package kbpath

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestValidSlug(t *testing.T) {
	tests := []struct {
		slug string
		want bool
	}{
		{"pricing", true},
		{"pricing-and-fees", true},
		{"a", true},
		{"0abc", true},
		{"", false},
		{"-lead", false},
		{"Upper", false},
		{"a/b", false},
		{".", false},
		{"..", false},
		{"with space", false},
		{"under_score", false},
		{"定价", false},
		// Length boundary: regexp is {0,39} so 1+39=40 chars is the maximum.
		{strings.Repeat("a", 40), true},
		{strings.Repeat("a", 41), false},
	}
	for _, tc := range tests {
		if got := ValidSlug(tc.slug); got != tc.want {
			t.Errorf("ValidSlug(%q) = %v, want %v", tc.slug, got, tc.want)
		}
	}
}

func TestResolve(t *testing.T) {
	root := t.TempDir()
	derived := filepath.Join(root, "derived", "pricing")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(derived, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	// A directory under derived/ with no manifest is not a derived KB.
	if err := os.MkdirAll(filepath.Join(root, "derived", "junk"), 0o755); err != nil {
		t.Fatal(err)
	}

	// Resolve expected paths: Resolve now calls EvalSymlinks internally, so on
	// platforms where t.TempDir() returns a path that contains a symlink (e.g.
	// macOS /tmp -> /private/tmp) the want values must use the canonical form.
	wantRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	wantDerived, err := filepath.EvalSymlinks(derived)
	if err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name    string
		slug    string
		want    string
		wantErr error
	}{
		{"empty slug is the root", "", wantRoot, nil},
		{"known slug", "pricing", wantDerived, nil},
		{"no manifest", "junk", "", ErrUnknownKB},
		{"absent", "nope", "", ErrUnknownKB},
		{"traversal", "../..", "", ErrInvalidSlug},
		{"absolute", "/etc", "", ErrInvalidSlug},
		{"uppercase", "Pricing", "", ErrInvalidSlug},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := Resolve(root, tc.slug)
			if tc.wantErr != nil {
				if !errors.Is(err, tc.wantErr) {
					t.Fatalf("Resolve(%q) err = %v, want %v", tc.slug, err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("Resolve(%q) unexpected err: %v", tc.slug, err)
			}
			if got != tc.want {
				t.Errorf("Resolve(%q) = %q, want %q", tc.slug, got, tc.want)
			}
		})
	}
}

func TestListSlugs(t *testing.T) {
	root := t.TempDir()
	for _, slug := range []string{"compliance", "pricing"} {
		d := filepath.Join(root, "derived", slug)
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(d, "manifest.json"), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(filepath.Join(root, "derived", "junk"), 0o755); err != nil {
		t.Fatal(err)
	}

	got, err := ListSlugs(root)
	if err != nil {
		t.Fatalf("ListSlugs: %v", err)
	}
	want := []string{"compliance", "pricing"}
	if len(got) != len(want) {
		t.Fatalf("ListSlugs = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("ListSlugs[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}

// TestListSlugsAgreesWithResolve covers the two layouts where the pre-fix
// ListSlugs (os.ReadDir + IsDir + ValidSlug + manifest Stat) omitted a slug that
// Resolve accepts, so GET /api/derived hid a KB that ?kb= served happily.
//
// Pre-fix behaviour documented per sub-case so the RED→GREEN transition is
// auditable.
func TestListSlugsAgreesWithResolve(t *testing.T) {
	t.Run("slug_symlinked_to_sibling_inside", func(t *testing.T) {
		// Pre-fix: os.ReadDir reports the symlink entry with IsDir()==false
		// (DirEntry.IsDir is lstat-based), so "alias" is skipped even though
		// Resolve follows it to the sibling and accepts it.
		root := t.TempDir()
		compliance := filepath.Join(root, DerivedDirName, "compliance")
		if err := os.MkdirAll(compliance, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(compliance, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// derived/alias -> derived/compliance
		if err := os.Symlink(compliance, filepath.Join(root, DerivedDirName, "alias")); err != nil {
			t.Fatal(err)
		}
		if _, err := Resolve(root, "alias"); err != nil {
			t.Fatalf("precondition: Resolve(alias) = %v, want nil", err)
		}

		got, err := ListSlugs(root)
		if err != nil {
			t.Fatalf("ListSlugs: %v", err)
		}
		if !contains(got, "alias") {
			t.Errorf("ListSlugs = %v, want it to contain the resolvable alias", got)
		}
	})

	t.Run("case_insensitive_filesystem", func(t *testing.T) {
		// Pre-fix: the on-disk name "Pricing" fails ValidSlug so the entry is
		// skipped, while Resolve("pricing") succeeds on a case-insensitive
		// filesystem (EvalSymlinks does not case-canonicalise).
		root := t.TempDir()
		upper := filepath.Join(root, DerivedDirName, "Pricing")
		if err := os.MkdirAll(upper, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(upper, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := Resolve(root, "pricing"); err != nil {
			t.Skipf("case-sensitive filesystem: Resolve(pricing) = %v", err)
		}

		got, err := ListSlugs(root)
		if err != nil {
			t.Fatalf("ListSlugs: %v", err)
		}
		if !contains(got, "pricing") {
			t.Errorf("ListSlugs = %v, want it to contain pricing, which Resolve accepts", got)
		}
	})
}

func contains(ss []string, want string) bool {
	for _, s := range ss {
		if s == want {
			return true
		}
	}
	return false
}

func TestListSlugsNoDerivedDir(t *testing.T) {
	got, err := ListSlugs(t.TempDir())
	if err != nil {
		t.Fatalf("ListSlugs: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("ListSlugs = %v, want empty", got)
	}
}

func TestReadManifest(t *testing.T) {
	dir := t.TempDir()
	raw := `{"slug":"pricing","topic":"Pricing","created_at":"2024-01-01","compiled":true}`
	if err := os.WriteFile(filepath.Join(dir, manifestName), []byte(raw), 0o644); err != nil {
		t.Fatal(err)
	}
	m, err := ReadManifest(dir)
	if err != nil {
		t.Fatalf("ReadManifest: %v", err)
	}
	if m.Slug != "pricing" || m.Topic != "Pricing" || m.CreatedAt != "2024-01-01" || !m.Compiled {
		t.Errorf("manifest = %+v", m)
	}
}

func TestReadManifestErrors(t *testing.T) {
	t.Run("absent", func(t *testing.T) {
		if _, err := ReadManifest(t.TempDir()); err == nil {
			t.Error("ReadManifest of a directory with no manifest returned nil error")
		}
	})
	t.Run("not_json", func(t *testing.T) {
		dir := t.TempDir()
		if err := os.WriteFile(filepath.Join(dir, manifestName), []byte("{oops"), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := ReadManifest(dir); err == nil {
			t.Error("ReadManifest of a corrupt manifest returned nil error")
		}
	})
	t.Run("compiled_absent_is_false", func(t *testing.T) {
		// A manifest written before the compile pass has no compiled key at all
		// (spec E1), which must read as an incomplete derive rather than an error.
		dir := t.TempDir()
		if err := os.WriteFile(filepath.Join(dir, manifestName), []byte(`{"slug":"x"}`), 0o644); err != nil {
			t.Fatal(err)
		}
		m, err := ReadManifest(dir)
		if err != nil {
			t.Fatalf("ReadManifest: %v", err)
		}
		if m.Compiled {
			t.Error("compiled = true for a manifest without the key")
		}
	})
}

// TestResolveSymlinkContainment verifies that Resolve rejects three symlink
// layouts that the pre-fix (lexical + os.Stat-only) implementation would have
// accepted or misreported.
//
// Pre-fix behaviour documented here so the RED→GREEN transition is auditable:
//
//	case slug_symlinked_outside: pre-fix os.Stat follows the symlink into the
//	  outside directory, finds manifest.json, and returns the unresolved
//	  derived/pricing path with err==nil. Post-fix EvalSymlinks resolves to the
//	  outside path, HasPrefix fails, returns ErrUnknownKB.
//
//	case derived_dir_symlinked_outside: pre-fix filepath.Join(root,"derived","pricing")
//	  traverses the derived/ symlink into the outside directory, Stat finds the
//	  manifest, returns the path with err==nil. Post-fix EvalSymlinks resolves
//	  through both symlinks, HasPrefix fails, returns ErrUnknownKB.
//
//	case slug_symlinked_to_sibling: pre-fix returns filepath.Join(base,"pricing")
//	  verbatim (the unresolved symlink path). Post-fix EvalSymlinks follows the
//	  symlink to derived/compliance and returns that resolved path instead,
//	  so the want assertion (resolved sibling path) fails against pre-fix code.
func TestResolveSymlinkContainment(t *testing.T) {
	t.Run("slug_symlinked_outside", func(t *testing.T) {
		root := t.TempDir()
		outside := t.TempDir()
		// Provide a manifest in the outside directory so pre-fix Stat succeeds.
		if err := os.WriteFile(filepath.Join(outside, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(filepath.Join(root, DerivedDirName), 0o755); err != nil {
			t.Fatal(err)
		}
		// derived/pricing -> outside/
		if err := os.Symlink(outside, filepath.Join(root, DerivedDirName, "pricing")); err != nil {
			t.Fatal(err)
		}
		_, err := Resolve(root, "pricing")
		if !errors.Is(err, ErrUnknownKB) {
			t.Fatalf("Resolve with outside symlink: err = %v, want ErrUnknownKB", err)
		}
	})

	t.Run("derived_dir_symlinked_outside", func(t *testing.T) {
		root := t.TempDir()
		outside := t.TempDir()
		// Provide pricing/manifest.json inside the outside directory.
		if err := os.MkdirAll(filepath.Join(outside, "pricing"), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(outside, "pricing", manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// <root>/derived -> outside/
		if err := os.Symlink(outside, filepath.Join(root, DerivedDirName)); err != nil {
			t.Fatal(err)
		}
		_, err := Resolve(root, "pricing")
		if !errors.Is(err, ErrUnknownKB) {
			t.Fatalf("Resolve with derived/ symlinked outside: err = %v, want ErrUnknownKB", err)
		}
	})

	t.Run("slug_symlinked_to_sibling_inside", func(t *testing.T) {
		root := t.TempDir()
		compliance := filepath.Join(root, DerivedDirName, "compliance")
		if err := os.MkdirAll(compliance, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(compliance, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// derived/pricing -> derived/compliance
		if err := os.Symlink(compliance, filepath.Join(root, DerivedDirName, "pricing")); err != nil {
			t.Fatal(err)
		}

		got, err := Resolve(root, "pricing")
		if err != nil {
			t.Fatalf("Resolve with sibling symlink: unexpected err: %v", err)
		}
		// Post-fix returns the resolved sibling path, not the unresolved symlink.
		// Pre-fix returns filepath.Join(base, "pricing") which differs from this.
		wantResolved, err := filepath.EvalSymlinks(compliance)
		if err != nil {
			t.Fatal(err)
		}
		if got != wantResolved {
			t.Errorf("Resolve with sibling symlink = %q, want resolved %q", got, wantResolved)
		}
	})
}

// TestResolveContainmentBoundaries pins the two boundary conditions of the
// containment check in Resolve, plus the dangling-symlink case that mirrors the
// Python write-path suite. All three already behave correctly; the tests exist so
// that weakening the check is caught.
//
// Pre-fix behaviour documented here as "what a plausible simplification would
// do", since the failure mode is a future edit rather than the original code:
//
//	case slug_symlinked_to_derived_itself: with the check written as
//	  strings.HasPrefix(resolved, base) the resolved path equals base, the prefix
//	  matches, derived/manifest.json is found and derived/ itself is served as a
//	  KB — every other derived KB visible underneath it.
//
//	case sibling_derived_evil_dir: with the same simplification the resolved
//	  path <root>/derived-evil shares the "<root>/derived" prefix, so a KB
//	  outside derived/ is served (the classic /kb/derived-evil bypass). The
//	  separator in base+string(filepath.Separator) is what rejects it.
func TestResolveContainmentBoundaries(t *testing.T) {
	t.Run("slug_symlinked_to_derived_itself", func(t *testing.T) {
		root := t.TempDir()
		derivedDir := filepath.Join(root, DerivedDirName)
		if err := os.MkdirAll(derivedDir, 0o755); err != nil {
			t.Fatal(err)
		}
		// A manifest directly in derived/ so only the containment check can reject.
		if err := os.WriteFile(filepath.Join(derivedDir, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// derived/self -> derived/
		if err := os.Symlink(derivedDir, filepath.Join(derivedDir, "self")); err != nil {
			t.Fatal(err)
		}
		if _, err := Resolve(root, "self"); !errors.Is(err, ErrUnknownKB) {
			t.Fatalf("Resolve with slug symlinked to derived/ itself: err = %v, want ErrUnknownKB", err)
		}
	})

	t.Run("sibling_derived_evil_dir", func(t *testing.T) {
		root := t.TempDir()
		derivedDir := filepath.Join(root, DerivedDirName)
		if err := os.MkdirAll(derivedDir, 0o755); err != nil {
			t.Fatal(err)
		}
		// <root>/derived-evil shares the "<root>/derived" string prefix but is not
		// inside derived/.
		evil := filepath.Join(root, DerivedDirName+"-evil")
		if err := os.MkdirAll(evil, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(evil, manifestName), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// derived/evil -> ../derived-evil
		if err := os.Symlink(evil, filepath.Join(derivedDir, "evil")); err != nil {
			t.Fatal(err)
		}
		if _, err := Resolve(root, "evil"); !errors.Is(err, ErrUnknownKB) {
			t.Fatalf("Resolve with sibling derived-evil: err = %v, want ErrUnknownKB", err)
		}
		// The same layout must not surface in the listing either.
		got, err := ListSlugs(root)
		if err != nil {
			t.Fatalf("ListSlugs: %v", err)
		}
		if contains(got, "evil") {
			t.Errorf("ListSlugs = %v, want it to omit the out-of-tree evil slug", got)
		}
	})

	t.Run("dangling_symlink", func(t *testing.T) {
		root := t.TempDir()
		derivedDir := filepath.Join(root, DerivedDirName)
		if err := os.MkdirAll(derivedDir, 0o755); err != nil {
			t.Fatal(err)
		}
		// derived/gone -> a target that never existed.
		if err := os.Symlink(filepath.Join(root, "no-such-target"),
			filepath.Join(derivedDir, "gone")); err != nil {
			t.Fatal(err)
		}
		if _, err := Resolve(root, "gone"); !errors.Is(err, ErrUnknownKB) {
			t.Fatalf("Resolve with dangling symlink: err = %v, want ErrUnknownKB", err)
		}
		got, err := ListSlugs(root)
		if err != nil {
			t.Fatalf("ListSlugs: %v", err)
		}
		if contains(got, "gone") {
			t.Errorf("ListSlugs = %v, want it to omit the dangling symlink", got)
		}
	})
}

// TestResolveRelativeRoot verifies that a relative root is absolutised so the
// returned path is always absolute and matches what Python's Path.resolve() returns.
//
// Pre-fix evidence: without filepath.Abs, filepath.EvalSymlinks receives the
// relative string and returns it in relative form (e.g. "../../tmp/TestXxx" on
// Linux, or the symlink-resolved but still relative path on macOS). The test
// assertion got == wantRoot (absolute) therefore fails.
func TestResolveRelativeRoot(t *testing.T) {
	root := t.TempDir()
	derived := filepath.Join(root, "derived", "pricing")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(derived, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}

	wantRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	wantDerived, err := filepath.EvalSymlinks(derived)
	if err != nil {
		t.Fatal(err)
	}

	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	relRoot, err := filepath.Rel(cwd, root)
	if err != nil {
		t.Fatal(err)
	}

	t.Run("empty slug", func(t *testing.T) {
		got, err := Resolve(relRoot, "")
		if err != nil {
			t.Fatalf("Resolve(relRoot, \"\") unexpected err: %v", err)
		}
		if got != wantRoot {
			t.Errorf("Resolve(relRoot, \"\") = %q, want %q", got, wantRoot)
		}
	})
	t.Run("known slug", func(t *testing.T) {
		got, err := Resolve(relRoot, "pricing")
		if err != nil {
			t.Fatalf("Resolve(relRoot, \"pricing\") unexpected err: %v", err)
		}
		if got != wantDerived {
			t.Errorf("Resolve(relRoot, \"pricing\") = %q, want %q", got, wantDerived)
		}
	})
}
