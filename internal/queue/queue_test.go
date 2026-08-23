package queue

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
)

// fakeClock is a manually-advanced clock for deterministic lease tests.
type fakeClock struct{ t time.Time }

func (c *fakeClock) now() time.Time          { return c.t }
func (c *fakeClock) advance(d time.Duration) { c.t = c.t.Add(d) }

func newQueue(t *testing.T, ttl time.Duration) (*Queue, *fakeClock) {
	t.Helper()
	s, err := sqlite.Open(filepath.Join(t.TempDir(), "q.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	clk := &fakeClock{t: time.Unix(1_000, 0)}
	q := New(s, Options{LeaseTTL: ttl, Clock: clk.now})
	return q, clk
}

func submit(t *testing.T, q *Queue, id, hash string) {
	t.Helper()
	err := q.Submit(context.Background(), &store.Task{
		ID: id, Source: "paste", ContentHash: hash, MaxAttempts: 2,
	})
	if err != nil {
		t.Fatalf("Submit %s: %v", id, err)
	}
}

func TestSubmitClaimAck(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1")

	task, err := q.Claim(ctx, "w1")
	if err != nil || task == nil {
		t.Fatalf("Claim: task=%v err=%v", task, err)
	}
	if task.Status != store.StatusRunning || task.Attempts != 1 {
		t.Fatalf("claimed task wrong: %+v", task)
	}
	if err := q.Ack(ctx, task.ID, `{"ok":1}`); err != nil {
		t.Fatalf("Ack: %v", err)
	}
	// queue now empty
	if got, _ := q.Claim(ctx, "w1"); got != nil {
		t.Fatalf("expected empty queue, got %v", got)
	}
}

func TestClaimEmptyReturnsNil(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	got, err := q.Claim(context.Background(), "w1")
	if err != nil {
		t.Fatalf("Claim: %v", err)
	}
	if got != nil {
		t.Fatalf("expected nil on empty queue, got %v", got)
	}
}

func TestNackRequeuesUntilCeiling(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1") // MaxAttempts=2

	// attempt 1 → Nack → requeued
	task, _ := q.Claim(ctx, "w1") // Attempts=1
	requeued, err := q.Nack(ctx, task, "fail-1")
	if err != nil {
		t.Fatalf("Nack 1: %v", err)
	}
	if !requeued {
		t.Fatalf("attempt 1 (<max 2) should requeue")
	}

	// attempt 2 → Nack → permanent (Attempts == MaxAttempts)
	task, _ = q.Claim(ctx, "w1") // Attempts=2
	requeued, err = q.Nack(ctx, task, "fail-2")
	if err != nil {
		t.Fatalf("Nack 2: %v", err)
	}
	if requeued {
		t.Fatalf("attempt 2 (==max) should NOT requeue")
	}
	got, _ := q.store.GetTask(ctx, "t1")
	if got.Status != store.StatusFailed || got.Error != "fail-2" {
		t.Fatalf("expected permanent failure: %+v", got)
	}
}

func TestHeartbeatExtendsLease(t *testing.T) {
	q, clk := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1")
	task, _ := q.Claim(ctx, "w1")

	clk.advance(30 * time.Second)
	if err := q.Heartbeat(ctx, task.ID, "w1"); err != nil {
		t.Fatalf("Heartbeat: %v", err)
	}
	got, _ := q.store.GetTask(ctx, "t1")
	wantExp := clk.now().Add(time.Minute).UnixMilli()
	if got.LeaseExpiresAt != wantExp {
		t.Fatalf("lease not extended to %d, got %d", wantExp, got.LeaseExpiresAt)
	}
}

func TestRecoverExpiredViaClock(t *testing.T) {
	q, clk := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1")
	task, _ := q.Claim(ctx, "w1")

	// before lease expiry → nothing recovered, task stays claimable by no one
	n, err := q.RecoverExpired(ctx)
	if err != nil {
		t.Fatalf("RecoverExpired: %v", err)
	}
	if n != 0 {
		t.Fatalf("nothing should expire yet, got %d", n)
	}

	// advance past the lease → recovered and re-claimable
	clk.advance(2 * time.Minute)
	n, err = q.RecoverExpired(ctx)
	if err != nil {
		t.Fatalf("RecoverExpired: %v", err)
	}
	if n != 1 {
		t.Fatalf("expected 1 recovered, got %d", n)
	}
	reclaimed, _ := q.Claim(ctx, "w2")
	if reclaimed == nil || reclaimed.ID != task.ID {
		t.Fatalf("expected to reclaim t1, got %v", reclaimed)
	}
}

func TestSetStage(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1")
	task, err := q.Claim(ctx, "w1")
	if err != nil || task == nil {
		t.Fatalf("Claim: task=%v err=%v", task, err)
	}
	if err := q.SetStage(ctx, "t1", "w1", store.StagePipeline); err != nil {
		t.Fatalf("SetStage: %v", err)
	}
	if err := q.SetStage(ctx, "t1", "other", store.StagePipeline); err != store.ErrNotFound {
		t.Fatalf("wrong owner: want ErrNotFound, got %v", err)
	}
}

// TestReleaseHandsTheAttemptBack asserts Release is not a Nack: the task returns
// to the queue with no error recorded and with the attempt Claim spent, so a
// caller that was refused before doing any work costs the task nothing.
func TestReleaseHandsTheAttemptBack(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "h1") // MaxAttempts 2
	task, err := q.Claim(ctx, "w1")
	if err != nil || task == nil {
		t.Fatalf("Claim: task=%v err=%v", task, err)
	}

	if err := q.Release(ctx, "t1", "w1"); err != nil {
		t.Fatalf("Release: %v", err)
	}

	got, err := q.store.GetTask(ctx, "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending {
		t.Errorf("Status = %q, want %q", got.Status, store.StatusPending)
	}
	if got.Attempts != 0 {
		t.Errorf("Attempts = %d, want 0", got.Attempts)
	}
	if got.Error != "" {
		t.Errorf("Error = %q, want empty — a release is not a failure", got.Error)
	}

	// The wrong-owner sentinel must survive the queue layer, same as SetStage's:
	// the worker treats it as "lease lost, abandon".
	if err := q.Release(ctx, "t1", "w1"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("Release of an already-released task = %v, want store.ErrNotFound", err)
	}
}
