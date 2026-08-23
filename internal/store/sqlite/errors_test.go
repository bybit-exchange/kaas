package sqlite

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// TestOpenUnusableePathFails asserts Open pings the database eagerly, so a bad
// path is reported at startup rather than on the first query.
func TestOpenUnusableePathFails(t *testing.T) {
	// A regular file standing in for the parent directory makes SQLite unable to
	// create the database file.
	blocker := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(blocker, []byte("x"), 0o644); err != nil {
		t.Fatalf("write blocker: %v", err)
	}

	s, err := Open(filepath.Join(blocker, "kaas.db"))
	if err == nil {
		s.Close()
		t.Fatal("expected Open to fail for an unusable path")
	}
	if s != nil {
		t.Errorf("store must be nil on error, got %+v", s)
	}
	if !strings.Contains(err.Error(), "ping sqlite") {
		t.Errorf("err = %v, want it wrapped with %q", err, "ping sqlite")
	}
}

// TestOpenInMemory asserts the :memory: DSN branch produces a usable store —
// the API session tests depend on it.
func TestOpenInMemory(t *testing.T) {
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("Open(:memory:): %v", err)
	}
	defer s.Close()
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if err := s.CreateTask(context.Background(), mkTask("t1", "h1", 1)); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	if _, err := s.GetTask(context.Background(), "t1"); err != nil {
		t.Fatalf("GetTask: %v", err)
	}
}

// TestClosedStoreSurfacesRealErrors asserts every store operation reports a
// database failure as a wrapped error. The critical part is the negative
// assertion: a broken database must never be mistaken for ErrNotFound or
// ErrDuplicate, or callers would answer 404/409 and drop the work silently.
func TestClosedStoreSurfacesRealErrors(t *testing.T) {
	ctx := context.Background()
	task := mkTask("t1", "h1", 1)

	ops := []struct {
		name    string
		call    func(s *Store) error
		wantMsg string
	}{
		{"Migrate", func(s *Store) error { return s.Migrate(ctx) }, "migrate"},
		{"CreateTask", func(s *Store) error { return s.CreateTask(ctx, task) }, "create task"},
		{"GetTask", func(s *Store) error { _, err := s.GetTask(ctx, "t1"); return err }, "get task"},
		{"ListTasks", func(s *Store) error { _, err := s.ListTasks(ctx, store.ListFilter{}); return err }, "list tasks"},
		{"ListTasksPaged", func(s *Store) error {
			_, err := s.ListTasksPaged(ctx, store.PagedListFilter{Limit: 10})
			return err
		}, "list tasks paged"},
		{"DeleteTask", func(s *Store) error { return s.DeleteTask(ctx, "t1") }, "delete task"},
		{"ClaimNext", func(s *Store) error { _, err := s.ClaimNext(ctx, "w1", 1, 2); return err }, "claim next"},
		{"Heartbeat", func(s *Store) error { return s.Heartbeat(ctx, "t1", "w1", 2) }, "heartbeat"},
		{"SetStage", func(s *Store) error { return s.SetStage(ctx, "t1", "w1", store.StagePipeline, 2) }, "set stage"},
		{"MarkSucceeded", func(s *Store) error { return s.MarkSucceeded(ctx, "t1", "{}", 2) }, "mark succeeded"},
		{"MarkFailed", func(s *Store) error { return s.MarkFailed(ctx, "t1", "boom", false, 2) }, "mark failed"},
		{"ReleaseTask", func(s *Store) error { return s.ReleaseTask(ctx, "t1", "w1", 2) }, "release task"},
		{"RecoverExpired", func(s *Store) error { _, err := s.RecoverExpired(ctx, 2); return err }, "recover expired"},
		{"CreateSession", func(s *Store) error {
			return s.CreateSession(ctx, &store.Session{ID: "s1"})
		}, "create session"},
		{"ListSessions", func(s *Store) error { _, err := s.ListSessions(ctx); return err }, "list sessions"},
		{"GetSession", func(s *Store) error { _, err := s.GetSession(ctx, "s1"); return err }, "get session"},
		{"UpdateSessionTitle", func(s *Store) error { return s.UpdateSessionTitle(ctx, "s1", "t", 2) }, "update session title"},
		{"DeleteSession", func(s *Store) error { return s.DeleteSession(ctx, "s1") }, "delete session"},
		{"CreateMessage", func(s *Store) error {
			return s.CreateMessage(ctx, &store.Message{ID: "m1", SessionID: "s1"})
		}, "create message"},
		{"ListMessages", func(s *Store) error { _, err := s.ListMessages(ctx, "s1"); return err }, "list messages"},
		{"TouchSession", func(s *Store) error { return s.TouchSession(ctx, "s1", 2) }, "touch session"},
	}

	for _, op := range ops {
		t.Run(op.name, func(t *testing.T) {
			s := newStore(t)
			if err := s.Close(); err != nil {
				t.Fatalf("Close: %v", err)
			}

			err := op.call(s)
			if err == nil {
				t.Fatalf("%s on a closed store returned nil", op.name)
			}
			if errors.Is(err, store.ErrNotFound) || errors.Is(err, store.ErrDuplicate) {
				t.Errorf("%s: a database failure must not be reported as a queue sentinel: %v", op.name, err)
			}
			if !strings.Contains(err.Error(), op.wantMsg) {
				t.Errorf("%s err = %v, want it wrapped with %q", op.name, err, op.wantMsg)
			}
		})
	}
}

// TestMigrateUpgradesLegacyTasksTable asserts a database created before the
// file_title column exists is upgraded in place, keeping its rows.
func TestMigrateUpgradesLegacyTasksTable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "legacy.db")
	s, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	ctx := context.Background()

	// Pre-file_title schema, plus one row.
	legacy := `CREATE TABLE tasks (
		id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
		raw_path TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL,
		status TEXT NOT NULL, stage TEXT NOT NULL,
		attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 1,
		error TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '',
		lease_owner TEXT NOT NULL DEFAULT '', lease_expires_at INTEGER NOT NULL DEFAULT 0,
		created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);`
	if _, err := s.db.ExecContext(ctx, legacy); err != nil {
		t.Fatalf("create legacy schema: %v", err)
	}
	if _, err := s.db.ExecContext(ctx, `INSERT INTO tasks
		(id, source, title, raw_path, content_hash, status, stage, created_at, updated_at)
		VALUES ('old1','file','Legacy','/tmp/old.md','oldhash','pending','queued',1,1)`); err != nil {
		t.Fatalf("insert legacy row: %v", err)
	}

	if err := s.Migrate(ctx); err != nil {
		t.Fatalf("Migrate legacy db: %v", err)
	}

	got, err := s.GetTask(ctx, "old1")
	if err != nil {
		t.Fatalf("GetTask after migration: %v", err)
	}
	if got.Title != "Legacy" || got.RawPath != "/tmp/old.md" {
		t.Errorf("legacy row was not preserved: %+v", got)
	}
	if got.FileTitle != "" {
		t.Errorf("FileTitle = %q, want the new column to default to empty", got.FileTitle)
	}

	// New rows can use the added column, and the migration stays idempotent.
	if err := s.Migrate(ctx); err != nil {
		t.Fatalf("second Migrate: %v", err)
	}
	fresh := mkTask("new1", "newhash", 2)
	fresh.FileTitle = "brand new"
	if err := s.CreateTask(ctx, fresh); err != nil {
		t.Fatalf("CreateTask after migration: %v", err)
	}
	if got, err := s.GetTask(ctx, "new1"); err != nil || got.FileTitle != "brand new" {
		t.Errorf("file_title round-trip failed: task=%+v err=%v", got, err)
	}
}

// TestListTasksLimitAndOffset asserts the ListFilter window is applied by SQL.
func TestListTasksLimitAndOffset(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	// created_at ascending; ListTasks returns newest first → t3,t2,t1.
	for i, id := range []string{"t1", "t2", "t3"} {
		if err := s.CreateTask(ctx, mkTask(id, "h"+id, int64(100+i))); err != nil {
			t.Fatalf("CreateTask %s: %v", id, err)
		}
	}

	tests := []struct {
		name   string
		filter store.ListFilter
		want   []string
	}{
		{"no window", store.ListFilter{}, []string{"t3", "t2", "t1"}},
		{"limit only", store.ListFilter{Limit: 2}, []string{"t3", "t2"}},
		{"limit with offset", store.ListFilter{Limit: 2, Offset: 1}, []string{"t2", "t1"}},
		{"offset past the end", store.ListFilter{Limit: 2, Offset: 5}, nil},
		{"limit larger than the table", store.ListFilter{Limit: 10}, []string{"t3", "t2", "t1"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := s.ListTasks(ctx, tc.filter)
			if err != nil {
				t.Fatalf("ListTasks: %v", err)
			}
			if len(got) != len(tc.want) {
				t.Fatalf("ids = %v, want %v", ids(got), tc.want)
			}
			for i := range tc.want {
				if got[i].ID != tc.want[i] {
					t.Fatalf("ids = %v, want %v", ids(got), tc.want)
				}
			}
		})
	}
}

// TestListTasksPagedSorting asserts only whitelisted sort columns are honoured —
// an unknown SortBy must fall back to created_at rather than reach the SQL, since
// the column name is interpolated into the statement.
func TestListTasksPagedSorting(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	for i, spec := range []struct{ id, title string }{
		{"t1", "banana"},
		{"t2", "apple"},
		{"t3", "cherry"},
	} {
		task := mkTask(spec.id, "h"+spec.id, int64(100+i))
		task.Title = spec.title
		if err := s.CreateTask(ctx, task); err != nil {
			t.Fatalf("CreateTask %s: %v", spec.id, err)
		}
	}

	tests := []struct {
		name    string
		sortBy  string
		sortDir string
		want    []string
	}{
		{"title ascending", "title", "asc", []string{"t2", "t1", "t3"}},
		{"title descending", "title", "desc", []string{"t3", "t1", "t2"}},
		{"created_at default direction", "created_at", "", []string{"t3", "t2", "t1"}},
		{"unknown column falls back to created_at", "; DROP TABLE tasks", "asc", []string{"t1", "t2", "t3"}},
		{"empty sort falls back to created_at", "", "", []string{"t3", "t2", "t1"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			res, err := s.ListTasksPaged(ctx, store.PagedListFilter{SortBy: tc.sortBy, SortDir: tc.sortDir})
			if err != nil {
				t.Fatalf("ListTasksPaged: %v", err)
			}
			if res.Total != 3 {
				t.Errorf("Total = %d, want 3", res.Total)
			}
			if len(res.Tasks) != len(tc.want) {
				t.Fatalf("ids = %v, want %v", ids(res.Tasks), tc.want)
			}
			for i := range tc.want {
				if res.Tasks[i].ID != tc.want[i] {
					t.Fatalf("ids = %v, want %v", ids(res.Tasks), tc.want)
				}
			}
		})
	}
}

// TestListTasksPagedOffsetWithoutLimit documents a live bug: ListTasksPaged
// appends `OFFSET ?` independently of `LIMIT ?`, and SQLite rejects OFFSET
// without LIMIT ("near \"OFFSET\": syntax error"). It is reachable from the API:
// GET /api/tasks?limit=0&offset=10 sets Limit=0/Offset=10 and answers 500.
// Fixing it means either emitting `LIMIT -1` when only an offset is given, or
// ignoring a bare offset the way ListTasks does. Delete the Skip once fixed.
func TestListTasksPagedOffsetWithoutLimit(t *testing.T) {
	t.Skip("BUG: ListTasksPaged emits OFFSET without LIMIT, which SQLite rejects")

	s := newStore(t)
	ctx := context.Background()
	for i, id := range []string{"t1", "t2", "t3"} {
		if err := s.CreateTask(ctx, mkTask(id, "h"+id, int64(100+i))); err != nil {
			t.Fatalf("CreateTask %s: %v", id, err)
		}
	}

	res, err := s.ListTasksPaged(ctx, store.PagedListFilter{Offset: 2})
	if err != nil {
		t.Fatalf("ListTasksPaged: %v", err)
	}
	if res.Total != 3 {
		t.Errorf("Total = %d, want the unpaged total 3", res.Total)
	}
	if len(res.Tasks) != 1 || res.Tasks[0].ID != "t1" {
		t.Errorf("ids = %v, want the oldest task after skipping 2", ids(res.Tasks))
	}
}

// TestIsUniqueViolationRejectsOtherErrors asserts only unique/primary-key
// violations map to ErrDuplicate, so a NOT NULL breach is not reported as a
// harmless duplicate submission.
func TestIsUniqueViolationRejectsOtherErrors(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// content_hash is NOT NULL; a NULL insert must surface as a real error.
	_, err := s.db.ExecContext(ctx, `INSERT INTO tasks
		(id, source, content_hash, status, stage, created_at, updated_at)
		VALUES ('x','paste',NULL,'pending','queued',1,1)`)
	if err == nil {
		t.Fatal("expected a NOT NULL constraint failure")
	}
	if isUniqueViolation(err) {
		t.Errorf("isUniqueViolation(%v) = true, want false for a NOT NULL breach", err)
	}

	if err := s.CreateTask(ctx, mkTask("t1", "dup", 1)); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	dupErr := s.CreateTask(ctx, mkTask("t2", "dup", 2))
	if !errors.Is(dupErr, store.ErrDuplicate) {
		t.Fatalf("duplicate content_hash = %v, want ErrDuplicate", dupErr)
	}
	// The primary key is also unique: a repeated id must map to the same sentinel.
	if err := s.CreateTask(ctx, mkTask("t1", "other", 3)); !errors.Is(err, store.ErrDuplicate) {
		t.Errorf("duplicate id = %v, want ErrDuplicate", err)
	}
}
