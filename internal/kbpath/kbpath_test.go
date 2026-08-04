package kbpath

import (
	"errors"
	"os"
	"path/filepath"
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

	tests := []struct {
		name    string
		slug    string
		want    string
		wantErr error
	}{
		{"empty slug is the root", "", root, nil},
		{"known slug", "pricing", derived, nil},
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

func TestListSlugsNoDerivedDir(t *testing.T) {
	got, err := ListSlugs(t.TempDir())
	if err != nil {
		t.Fatalf("ListSlugs: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("ListSlugs = %v, want empty", got)
	}
}
