package api

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// captureStdLog redirects the standard logger for the duration of the test.
// rollbackFiles reports through it rather than the server logger, so this is the
// only way to observe what an operator would see.
func captureStdLog(t *testing.T) *strings.Builder {
	t.Helper()
	buf := &strings.Builder{}
	prevOut, prevFlags := log.Writer(), log.Flags()
	log.SetOutput(buf)
	log.SetFlags(0)
	t.Cleanup(func() {
		log.SetOutput(prevOut)
		log.SetFlags(prevFlags)
	})
	return buf
}

// TestRollbackFilesRemovesEveryWrittenFile asserts the ZIP commit rollback is
// complete: one failed entry must leave no raw file behind, or the next upload of
// the same archive would be rejected as a duplicate of a task that was never
// enqueued.
func TestRollbackFilesRemovesEveryWrittenFile(t *testing.T) {
	dir := t.TempDir()
	written := make([]writtenFile, 0, 3)
	for _, name := range []string{"a.md", "b.md", "c.md"} {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
		written = append(written, writtenFile{Name: name, RawPath: path})
	}

	logs := captureStdLog(t)
	(&Server{}).rollbackFiles(written)

	for _, wf := range written {
		if _, err := os.Stat(wf.RawPath); !os.IsNotExist(err) {
			t.Errorf("%s still exists after rollback (stat err = %v)", wf.Name, err)
		}
	}
	if logs.String() != "" {
		t.Errorf("a clean rollback must log nothing, got %q", logs.String())
	}
}

// TestRollbackFilesIgnoresAlreadyGoneFiles pins the ErrNotExist carve-out. A
// duplicate entry is removed during the commit loop before rollback runs, so an
// absent file is the expected case and must not be reported as a problem.
func TestRollbackFilesIgnoresAlreadyGoneFiles(t *testing.T) {
	logs := captureStdLog(t)

	(&Server{}).rollbackFiles([]writtenFile{
		{Name: "gone.md", RawPath: filepath.Join(t.TempDir(), "never-written.md")},
	})

	if logs.String() != "" {
		t.Errorf("an already-removed file must not be logged, got %q", logs.String())
	}
}

// TestRollbackFilesLogsUnremovableFiles covers the other half of that carve-out:
// a removal that fails for any reason other than the file being gone leaves a
// stale raw file whose hash now blocks re-upload, so it must reach the log
// instead of being swallowed. rollbackFiles has no error return — the log is the
// only signal.
func TestRollbackFilesLogsUnremovableFiles(t *testing.T) {
	// A non-empty directory cannot be removed by os.Remove, which fails with
	// ENOTEMPTY rather than ErrNotExist.
	stuck := filepath.Join(t.TempDir(), "stuck")
	if err := os.MkdirAll(filepath.Join(stuck, "child"), 0o755); err != nil {
		t.Fatalf("seed unremovable path: %v", err)
	}

	logs := captureStdLog(t)
	(&Server{}).rollbackFiles([]writtenFile{{Name: "doc.md", RawPath: stuck}})

	got := logs.String()
	if !strings.Contains(got, "rollbackFiles") {
		t.Errorf("log = %q, want it to report the failed removal", got)
	}
	if !strings.Contains(got, "doc.md") {
		t.Errorf("log = %q, want it to name the file the operator has to clean up", got)
	}
}
