package sqlite

import (
	"context"
	"errors"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// TestReleaseTaskUndoesTheClaim asserts ReleaseTask is the exact inverse of
// ClaimNext: pending and queued again, no lease, and the attempt handed back so
// a task returned without being processed keeps its full retry budget.
func TestReleaseTaskUndoesTheClaim(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	if err := s.CreateTask(ctx, mkTask("t1", "h1", 1)); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	claimed, err := s.ClaimNext(ctx, "w1", 10, 100)
	if err != nil || claimed == nil {
		t.Fatalf("ClaimNext: task=%v err=%v", claimed, err)
	}
	if claimed.Attempts != 1 {
		t.Fatalf("Attempts after claim = %d, want 1", claimed.Attempts)
	}

	if err := s.ReleaseTask(ctx, "t1", "w1", 20); err != nil {
		t.Fatalf("ReleaseTask: %v", err)
	}

	got, err := s.GetTask(ctx, "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending {
		t.Errorf("Status = %q, want %q", got.Status, store.StatusPending)
	}
	if got.Stage != store.StageQueued {
		t.Errorf("Stage = %q, want %q", got.Stage, store.StageQueued)
	}
	if got.Attempts != 0 {
		t.Errorf("Attempts = %d, want 0 — the claim's increment must be handed back", got.Attempts)
	}
	if got.LeaseOwner != "" || got.LeaseExpiresAt != 0 {
		t.Errorf("lease not cleared: owner=%q expires=%d", got.LeaseOwner, got.LeaseExpiresAt)
	}
	if got.UpdatedAt != 20 {
		t.Errorf("UpdatedAt = %d, want 20", got.UpdatedAt)
	}

	// The released task must be claimable again, and that claim spends the
	// attempt that was handed back rather than a second one.
	again, err := s.ClaimNext(ctx, "w2", 30, 300)
	if err != nil || again == nil {
		t.Fatalf("ClaimNext after release: task=%v err=%v", again, err)
	}
	if again.ID != "t1" {
		t.Fatalf("re-claimed %q, want t1", again.ID)
	}
	if again.Attempts != 1 {
		t.Errorf("Attempts after re-claim = %d, want 1", again.Attempts)
	}
}

// TestReleaseTaskIsOwnerScoped asserts a worker that has lost its lease cannot
// hand back an attempt on a task somebody else now owns.
func TestReleaseTaskIsOwnerScoped(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	if err := s.CreateTask(ctx, mkTask("t1", "h1", 1)); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	if _, err := s.ClaimNext(ctx, "w1", 10, 100); err != nil {
		t.Fatalf("ClaimNext: %v", err)
	}

	if err := s.ReleaseTask(ctx, "t1", "w2", 20); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("release by a non-owner = %v, want store.ErrNotFound", err)
	}
	if err := s.ReleaseTask(ctx, "nosuch", "w1", 20); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("release of a missing task = %v, want store.ErrNotFound", err)
	}
	// A refused release must leave the row exactly as it was.
	got, _ := s.GetTask(ctx, "t1")
	if got.Status != store.StatusRunning || got.Attempts != 1 || got.LeaseOwner != "w1" {
		t.Fatalf("a refused release changed the row: status=%q attempts=%d owner=%q",
			got.Status, got.Attempts, got.LeaseOwner)
	}

	// Not running any more: the task reached a terminal status, so there is no
	// attempt left to hand back.
	if err := s.MarkSucceeded(ctx, "t1", "{}", 30); err != nil {
		t.Fatalf("MarkSucceeded: %v", err)
	}
	if err := s.ReleaseTask(ctx, "t1", "w1", 40); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("release of a succeeded task = %v, want store.ErrNotFound", err)
	}
}

// TestReleaseTaskFloorsAttemptsAtZero pins the floor on the decrement. ClaimNext
// is the only writer of status=running and always increments, so every
// releasable row has attempts >= 1; the floor matters because a negative
// attempts reads as "retries left forever" in queue.Nack.
func TestReleaseTaskFloorsAttemptsAtZero(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	corrupt := mkTask("t1", "h1", 1)
	corrupt.Status = store.StatusRunning
	corrupt.Stage = store.StageExtract
	corrupt.Attempts = 0
	corrupt.LeaseOwner = "w1"
	if err := s.CreateTask(ctx, corrupt); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	if err := s.ReleaseTask(ctx, "t1", "w1", 20); err != nil {
		t.Fatalf("ReleaseTask: %v", err)
	}

	got, _ := s.GetTask(ctx, "t1")
	if got.Attempts != 0 {
		t.Fatalf("Attempts = %d, want 0", got.Attempts)
	}
}
