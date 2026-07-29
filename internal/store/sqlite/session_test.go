package sqlite

import (
	"context"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// newMemoryStore opens an in-memory SQLite store with foreign_keys enabled.
func newMemoryStore(t *testing.T) *Store {
	t.Helper()
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("Open :memory:: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	return s
}

func TestSessionCreateAndGet(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	sess := &store.Session{
		ID:        "sess-001",
		Title:     "hello world",
		CreatedAt: 1000,
		UpdatedAt: 1000,
	}
	if err := s.CreateSession(ctx, sess); err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	got, err := s.GetSession(ctx, "sess-001")
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if got.ID != "sess-001" || got.Title != "hello world" || got.CreatedAt != 1000 || got.UpdatedAt != 1000 {
		t.Fatalf("round-trip mismatch: %+v", got)
	}
}

func TestSessionGetNotFound(t *testing.T) {
	s := newMemoryStore(t)
	_, err := s.GetSession(context.Background(), "nope")
	if err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestSessionListOrder(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	_ = s.CreateSession(ctx, &store.Session{ID: "old", Title: "old", CreatedAt: 100, UpdatedAt: 100})
	_ = s.CreateSession(ctx, &store.Session{ID: "new", Title: "new", CreatedAt: 200, UpdatedAt: 300})
	_ = s.CreateSession(ctx, &store.Session{ID: "mid", Title: "mid", CreatedAt: 150, UpdatedAt: 200})

	list, err := s.ListSessions(ctx)
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(list) != 3 {
		t.Fatalf("expected 3 sessions, got %d", len(list))
	}
	// Order: updated_at DESC → new(300), mid(200), old(100)
	if list[0].ID != "new" || list[1].ID != "mid" || list[2].ID != "old" {
		t.Fatalf("order wrong: %s, %s, %s", list[0].ID, list[1].ID, list[2].ID)
	}
}

func TestSessionUpdateTitle(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	_ = s.CreateSession(ctx, &store.Session{ID: "s1", Title: "original", CreatedAt: 100, UpdatedAt: 100})

	if err := s.UpdateSessionTitle(ctx, "s1", "renamed", 200); err != nil {
		t.Fatalf("UpdateSessionTitle: %v", err)
	}
	got, _ := s.GetSession(ctx, "s1")
	if got.Title != "renamed" || got.UpdatedAt != 200 {
		t.Fatalf("title/updated not applied: %+v", got)
	}
}

func TestSessionUpdateTitleNotFound(t *testing.T) {
	s := newMemoryStore(t)
	err := s.UpdateSessionTitle(context.Background(), "nope", "x", 100)
	if err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestSessionDeleteCascade(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	_ = s.CreateSession(ctx, &store.Session{ID: "s1", Title: "test", CreatedAt: 100, UpdatedAt: 100})
	_ = s.CreateMessage(ctx, &store.Message{ID: "m1", SessionID: "s1", Role: "user", Content: "hello", Sources: "[]", Usage: "{}", CreatedAt: 101})
	_ = s.CreateMessage(ctx, &store.Message{ID: "m2", SessionID: "s1", Role: "assistant", Content: "hi", Sources: "[]", Usage: "{}", CreatedAt: 102})

	// Verify messages exist
	msgs, _ := s.ListMessages(ctx, "s1")
	if len(msgs) != 2 {
		t.Fatalf("expected 2 messages before delete, got %d", len(msgs))
	}

	// Delete session → cascade deletes messages
	if err := s.DeleteSession(ctx, "s1"); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}

	// Session gone
	if _, err := s.GetSession(ctx, "s1"); err != store.ErrNotFound {
		t.Fatalf("session should be gone, got %v", err)
	}

	// Messages also gone
	msgs, err := s.ListMessages(ctx, "s1")
	if err != nil {
		t.Fatalf("ListMessages after delete: %v", err)
	}
	if len(msgs) != 0 {
		t.Fatalf("expected 0 messages after cascade delete, got %d", len(msgs))
	}
}

func TestSessionDeleteNotFound(t *testing.T) {
	s := newMemoryStore(t)
	err := s.DeleteSession(context.Background(), "nope")
	if err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestMessageCreateAndList(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	_ = s.CreateSession(ctx, &store.Session{ID: "s1", Title: "test", CreatedAt: 100, UpdatedAt: 100})

	m1 := &store.Message{ID: "m1", SessionID: "s1", Role: "user", Content: "q1", Sources: "[]", Usage: "{}", CreatedAt: 200}
	m2 := &store.Message{ID: "m2", SessionID: "s1", Role: "assistant", Content: "a1", Sources: `[{"title":"doc"}]`, Usage: `{"tokens":10}`, CreatedAt: 300}

	if err := s.CreateMessage(ctx, m1); err != nil {
		t.Fatalf("CreateMessage m1: %v", err)
	}
	if err := s.CreateMessage(ctx, m2); err != nil {
		t.Fatalf("CreateMessage m2: %v", err)
	}

	msgs, err := s.ListMessages(ctx, "s1")
	if err != nil {
		t.Fatalf("ListMessages: %v", err)
	}
	if len(msgs) != 2 {
		t.Fatalf("expected 2 messages, got %d", len(msgs))
	}
	// Order: created_at ASC
	if msgs[0].ID != "m1" || msgs[1].ID != "m2" {
		t.Fatalf("order wrong: %s, %s", msgs[0].ID, msgs[1].ID)
	}
	if msgs[1].Sources != `[{"title":"doc"}]` {
		t.Fatalf("sources not preserved: %s", msgs[1].Sources)
	}
}

func TestMessageForeignKeyConstraint(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	// Attempt to create a message with non-existent session_id → should fail
	m := &store.Message{ID: "m1", SessionID: "nonexistent", Role: "user", Content: "hi", Sources: "[]", Usage: "{}", CreatedAt: 100}
	err := s.CreateMessage(ctx, m)
	if err == nil {
		t.Fatal("expected foreign key error, got nil")
	}
}

func TestTouchSession(t *testing.T) {
	s := newMemoryStore(t)
	ctx := context.Background()

	_ = s.CreateSession(ctx, &store.Session{ID: "s1", Title: "test", CreatedAt: 100, UpdatedAt: 100})

	if err := s.TouchSession(ctx, "s1", 500); err != nil {
		t.Fatalf("TouchSession: %v", err)
	}
	got, _ := s.GetSession(ctx, "s1")
	if got.UpdatedAt != 500 {
		t.Fatalf("updated_at not touched: got %d", got.UpdatedAt)
	}
}

func TestTouchSessionNotFound(t *testing.T) {
	s := newMemoryStore(t)
	err := s.TouchSession(context.Background(), "nope", 100)
	if err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}
