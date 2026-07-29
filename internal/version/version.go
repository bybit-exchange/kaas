// Package version exposes build-time metadata injected via ldflags.
package version

import (
	"fmt"
	"runtime"
)

// These variables are set at build time via -ldflags -X.
var (
	Version   = "dev"
	GitCommit = "unknown"
	BuildTime = "unknown"
)

// String returns a human-readable version string.
func String() string {
	return fmt.Sprintf("kaas %s (commit: %s, built: %s, %s/%s)",
		Version, GitCommit, BuildTime, runtime.GOOS, runtime.GOARCH)
}
