package sqlite

import (
	"context"
	"strings"
	"testing"
)

// storeWithConflictingObject opens an in-memory store and plants a view under
// name, standing in for a database file that is not the one KaaS expects — a
// foreign or half-migrated file pointed at by config. CREATE TABLE IF NOT EXISTS
// tolerates the name collision, but the index the schema then builds on it does
// not, so the stage that owns that table fails.
func storeWithConflictingObject(t *testing.T, name string) *Store {
	t.Helper()
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("Open(:memory:): %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if _, err := s.db.ExecContext(context.Background(), "CREATE VIEW "+name+" AS SELECT 1 AS x"); err != nil {
		t.Fatalf("plant view %q: %v", name, err)
	}
	return s
}

// TestMigrateLabelsTheFailingStage asserts each schema stage wraps its own
// failure with a distinct prefix. Migrate runs five stages against one database;
// without the labels a startup failure says only "SQL logic error" and gives no
// clue which schema is at fault.
func TestMigrateLabelsTheFailingStage(t *testing.T) {
	tests := []struct {
		name       string
		plant      string
		wantPrefix string
	}{
		{name: "task schema", plant: "tasks", wantPrefix: "migrate:"},
		{name: "session schema", plant: "chat_sessions", wantPrefix: "migrate session schema:"},
		{name: "derived schema", plant: "derived_jobs", wantPrefix: "migrate derived schema:"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := storeWithConflictingObject(t, tc.plant)

			err := s.Migrate(context.Background())
			if err == nil {
				t.Fatalf("Migrate succeeded despite a conflicting %q object", tc.plant)
			}
			if !strings.HasPrefix(err.Error(), tc.wantPrefix) {
				t.Errorf("err = %q, want it prefixed with %q", err, tc.wantPrefix)
			}
		})
	}
}

// TestMigrateOnClosedStoreFails covers the path a caller actually hits when the
// database handle is gone: Migrate must report it rather than return nil and let
// the process start against a schema-less database.
func TestMigrateOnClosedStoreFails(t *testing.T) {
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("Open(:memory:): %v", err)
	}
	if err := s.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	if err := s.Migrate(context.Background()); err == nil {
		t.Fatal("expected Migrate to fail on a closed store")
	}
}

// TestColumnMigrationsSurfaceRealErrors calls each ALTER TABLE migration against
// a database that has none of the tables. They tolerate one specific failure
// to stay idempotent — a column that already exists — and this pins that
// carve-out as narrow: any other failure must be returned, or a database that
// never got the column would be treated as fully migrated and every later query
// naming that column would fail at runtime instead of at startup.
func TestColumnMigrationsSurfaceRealErrors(t *testing.T) {
	tests := []struct {
		name       string
		migrate    func(*Store) error
		wantPrefix string
	}{
		{
			name:       "session schema",
			migrate:    func(s *Store) error { return s.migrateSessionSchema(context.Background()) },
			wantPrefix: "migrate chat_messages add reasoning:",
		},
		{
			name:       "file_title",
			migrate:    func(s *Store) error { return s.migrateFileTitle(context.Background()) },
			wantPrefix: "migrate file_title: alter:",
		},
		{
			name:       "select_from",
			migrate:    func(s *Store) error { return s.migrateDeriveSelectFrom(context.Background()) },
			wantPrefix: "migrate select_from: alter:",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s, err := Open(":memory:")
			if err != nil {
				t.Fatalf("Open(:memory:): %v", err)
			}
			defer s.Close()

			err = tc.migrate(s)
			if err == nil {
				t.Fatal("migration reported success against a database with no tables")
			}
			if !strings.HasPrefix(err.Error(), tc.wantPrefix) {
				t.Errorf("err = %q, want it prefixed with %q", err, tc.wantPrefix)
			}
		})
	}
}

// TestMigrateIsIdempotent pins the property every stage's IF NOT EXISTS is there
// for: KaaS calls Migrate on every start, so a second run over an already
// migrated database must be a no-op rather than an error.
func TestMigrateIsIdempotent(t *testing.T) {
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("Open(:memory:): %v", err)
	}
	defer s.Close()

	ctx := context.Background()
	for i := range 3 {
		if err := s.Migrate(ctx); err != nil {
			t.Fatalf("Migrate run %d: %v", i+1, err)
		}
	}
}
