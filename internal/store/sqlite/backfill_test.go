package sqlite

import (
	"context"
	"strings"
	"testing"
)

// seedBackfillTask inserts a task with the given raw_path / file_title.
func seedBackfillTask(t *testing.T, s *Store, id, rawPath, fileTitle string) {
	t.Helper()
	task := mkTask(id, "hash-"+id, 100)
	task.RawPath = rawPath
	task.FileTitle = fileTitle
	if err := s.CreateTask(context.Background(), task); err != nil {
		t.Fatalf("CreateTask(%s): %v", id, err)
	}
}

// fileTitleOf reads a task's file_title back from the store.
func fileTitleOf(t *testing.T, s *Store, id string) string {
	t.Helper()
	task, err := s.GetTask(context.Background(), id)
	if err != nil {
		t.Fatalf("GetTask(%s): %v", id, err)
	}
	return task.FileTitle
}

// TestBackfillFileTitles asserts only rows missing a file_title but holding a
// raw_path are visited, and that the reported count matches the rows written.
func TestBackfillFileTitles(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	seedBackfillTask(t, s, "needs-1", "/kb/raw/a.md", "")
	seedBackfillTask(t, s, "needs-2", "/kb/raw/b.md", "")
	seedBackfillTask(t, s, "has-title", "/kb/raw/c.md", "Already Titled")
	seedBackfillTask(t, s, "no-raw-path", "", "")

	var visited []string
	count, err := s.BackfillFileTitles(ctx, func(rawPath string) string {
		visited = append(visited, rawPath)
		return "Title of " + rawPath
	})
	if err != nil {
		t.Fatalf("BackfillFileTitles: %v", err)
	}

	if count != 2 {
		t.Errorf("count = %d, want 2", count)
	}
	if len(visited) != 2 {
		t.Fatalf("readTitle called for %v, want only the two eligible rows", visited)
	}
	for _, p := range visited {
		if p != "/kb/raw/a.md" && p != "/kb/raw/b.md" {
			t.Errorf("readTitle called for an ineligible row: %s", p)
		}
	}

	if got := fileTitleOf(t, s, "needs-1"); got != "Title of /kb/raw/a.md" {
		t.Errorf("needs-1 file_title = %q, want the backfilled title", got)
	}
	if got := fileTitleOf(t, s, "needs-2"); got != "Title of /kb/raw/b.md" {
		t.Errorf("needs-2 file_title = %q, want the backfilled title", got)
	}
	if got := fileTitleOf(t, s, "has-title"); got != "Already Titled" {
		t.Errorf("has-title file_title = %q, want it left untouched", got)
	}
	if got := fileTitleOf(t, s, "no-raw-path"); got != "" {
		t.Errorf("no-raw-path file_title = %q, want it left empty", got)
	}
}

// TestBackfillFileTitlesSkipsEmptyTitles asserts an unreadable file (readTitle
// returning "") leaves the row alone and is not counted.
func TestBackfillFileTitlesSkipsEmptyTitles(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	seedBackfillTask(t, s, "unreadable", "/kb/raw/gone.md", "")
	seedBackfillTask(t, s, "readable", "/kb/raw/ok.md", "")

	count, err := s.BackfillFileTitles(ctx, func(rawPath string) string {
		if rawPath == "/kb/raw/gone.md" {
			return ""
		}
		return "Readable"
	})
	if err != nil {
		t.Fatalf("BackfillFileTitles: %v", err)
	}

	if count != 1 {
		t.Errorf("count = %d, want 1 (the empty title must not be counted)", count)
	}
	if got := fileTitleOf(t, s, "unreadable"); got != "" {
		t.Errorf("unreadable file_title = %q, want it left empty", got)
	}
	if got := fileTitleOf(t, s, "readable"); got != "Readable" {
		t.Errorf("readable file_title = %q, want %q", got, "Readable")
	}
}

// TestBackfillFileTitlesNoEligibleRows asserts the no-op case does not call
// readTitle at all.
func TestBackfillFileTitlesNoEligibleRows(t *testing.T) {
	s := newStore(t)

	seedBackfillTask(t, s, "has-title", "/kb/raw/a.md", "Titled")

	called := false
	count, err := s.BackfillFileTitles(context.Background(), func(string) string {
		called = true
		return "x"
	})
	if err != nil {
		t.Fatalf("BackfillFileTitles: %v", err)
	}
	if count != 0 {
		t.Errorf("count = %d, want 0", count)
	}
	if called {
		t.Error("readTitle was called despite no eligible rows")
	}
}

// TestBackfillFileTitlesOnClosedStore asserts the query error is wrapped rather
// than surfacing as a bare driver error.
func TestBackfillFileTitlesOnClosedStore(t *testing.T) {
	s := newStore(t)
	if err := s.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	_, err := s.BackfillFileTitles(context.Background(), func(string) string { return "x" })
	if err == nil {
		t.Fatal("expected an error from a closed store")
	}
	if !strings.Contains(err.Error(), "backfill query") {
		t.Errorf("expected the error to be wrapped with context, got %v", err)
	}
}
