package version

import (
	"runtime"
	"strings"
	"testing"
)

func TestStringIncludesBuildMetadata(t *testing.T) {
	// Restore the package defaults so this test does not affect others.
	origVersion, origCommit, origBuildTime := Version, GitCommit, BuildTime
	t.Cleanup(func() {
		Version, GitCommit, BuildTime = origVersion, origCommit, origBuildTime
	})

	Version = "v1.2.3"
	GitCommit = "abc1234"
	BuildTime = "2026-07-31T00:00:00Z"

	got := String()
	want := "kaas v1.2.3 (commit: abc1234, built: 2026-07-31T00:00:00Z, " +
		runtime.GOOS + "/" + runtime.GOARCH + ")"
	if got != want {
		t.Errorf("String() = %q, want %q", got, want)
	}
}

// TestStringWithDefaults asserts an un-stamped build (no ldflags) still yields
// a usable string rather than blanks.
func TestStringWithDefaults(t *testing.T) {
	got := String()

	for _, part := range []string{"kaas", Version, GitCommit, BuildTime, runtime.GOOS, runtime.GOARCH} {
		if !strings.Contains(got, part) {
			t.Errorf("String() = %q, missing %q", got, part)
		}
	}
}
