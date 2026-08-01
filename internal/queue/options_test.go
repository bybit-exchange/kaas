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

// newStore opens a migrated on-disk store for tests that need Queue defaults
// (and therefore cannot use newQueue, which injects a clock and TTL).
func newStore(t *testing.T) store.Store {
	t.Helper()
	s, err := sqlite.Open(filepath.Join(t.TempDir(), "q.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	return s
}

// TestNewDefaultsLeaseTTL asserts the zero Options yield a 5-minute lease off
// the real clock, so a caller that passes Options{} still gets a usable queue.
func TestNewDefaultsLeaseTTL(t *testing.T) {
	tests := []struct {
		name string
		ttl  time.Duration
	}{
		{"zero TTL", 0},
		{"negative TTL", -time.Minute},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := newStore(t)
			q := New(s, Options{LeaseTTL: tc.ttl})
			if q.leaseTTL != 5*time.Minute {
				t.Errorf("leaseTTL = %v, want the 5m default", q.leaseTTL)
			}

			ctx := context.Background()
			if err := q.Submit(ctx, &store.Task{ID: "t1", Source: "paste", ContentHash: "h1"}); err != nil {
				t.Fatalf("Submit: %v", err)
			}
			before := time.Now()
			task, err := q.Claim(ctx, "w1")
			if err != nil || task == nil {
				t.Fatalf("Claim: task=%v err=%v", task, err)
			}
			// The default clock is time.Now, so the lease must land ~5 minutes out.
			lo := before.Add(5 * time.Minute).UnixMilli()
			hi := time.Now().Add(5*time.Minute + time.Second).UnixMilli()
			if task.LeaseExpiresAt < lo || task.LeaseExpiresAt > hi {
				t.Errorf("LeaseExpiresAt = %d, want within [%d,%d]", task.LeaseExpiresAt, lo, hi)
			}
			if task.CreatedAt == 0 || task.UpdatedAt == 0 {
				t.Errorf("timestamps must come from the default clock: %+v", task)
			}
		})
	}
}

// TestSubmitStampsQueueState asserts Submit owns the lifecycle columns: a caller
// handing over a dirty task (e.g. a resubmitted struct) cannot inject a running
// status, a stale lease, or an attempt count.
func TestSubmitStampsQueueState(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()

	dirty := &store.Task{
		ID:             "t1",
		Source:         "paste",
		ContentHash:    "h1",
		Status:         store.StatusSucceeded,
		Stage:          store.StageDone,
		Attempts:       7,
		LeaseOwner:     "ghost",
		LeaseExpiresAt: 12345,
	}
	if err := q.Submit(ctx, dirty); err != nil {
		t.Fatalf("Submit: %v", err)
	}

	got, err := q.store.GetTask(ctx, "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending || got.Stage != store.StageQueued {
		t.Errorf("status/stage = %s/%s, want pending/queued", got.Status, got.Stage)
	}
	if got.Attempts != 0 {
		t.Errorf("Attempts = %d, want 0", got.Attempts)
	}
	if got.LeaseOwner != "" || got.LeaseExpiresAt != 0 {
		t.Errorf("lease not cleared: owner=%q expires=%d", got.LeaseOwner, got.LeaseExpiresAt)
	}
	wantNow := q.nowMS()
	if got.CreatedAt != wantNow || got.UpdatedAt != wantNow {
		t.Errorf("timestamps = %d/%d, want the injected clock %d", got.CreatedAt, got.UpdatedAt, wantNow)
	}
}

// TestSubmitDefaultsMaxAttempts asserts an unset ceiling becomes 1 (deliver once)
// rather than 0, which would make Nack fail the task without ever retrying — and
// which the store's NOT NULL default would otherwise silently accept.
func TestSubmitDefaultsMaxAttempts(t *testing.T) {
	tests := []struct {
		name string
		in   int
		want int
	}{
		{"zero", 0, 1},
		{"negative", -3, 1},
		{"explicit", 5, 5},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			q, _ := newQueue(t, time.Minute)
			ctx := context.Background()
			if err := q.Submit(ctx, &store.Task{
				ID: "t1", Source: "paste", ContentHash: "h1", MaxAttempts: tc.in,
			}); err != nil {
				t.Fatalf("Submit: %v", err)
			}
			got, err := q.store.GetTask(ctx, "t1")
			if err != nil {
				t.Fatalf("GetTask: %v", err)
			}
			if got.MaxAttempts != tc.want {
				t.Errorf("MaxAttempts = %d, want %d", got.MaxAttempts, tc.want)
			}
		})
	}
}

// TestSubmitDuplicatePropagatesSentinel asserts the dedup sentinel survives the
// queue layer — the API relies on errors.Is(err, store.ErrDuplicate) to answer
// 409 instead of 500.
func TestSubmitDuplicatePropagatesSentinel(t *testing.T) {
	q, _ := newQueue(t, time.Minute)
	ctx := context.Background()
	submit(t, q, "t1", "same-hash")

	err := q.Submit(ctx, &store.Task{ID: "t2", Source: "paste", ContentHash: "same-hash", MaxAttempts: 1})
	if !errors.Is(err, store.ErrDuplicate) {
		t.Fatalf("Submit duplicate = %v, want store.ErrDuplicate", err)
	}
}

// failingStore wraps a store and forces one primitive to fail, so the queue's
// error propagation can be checked without a broken database.
type failingStore struct {
	store.Store
	markFailedErr error
	claimErr      error
	recoverErr    error
}

func (f failingStore) MarkFailed(ctx context.Context, id, errMsg string, retry bool, now int64) error {
	if f.markFailedErr != nil {
		return f.markFailedErr
	}
	return f.Store.MarkFailed(ctx, id, errMsg, retry, now)
}

func (f failingStore) ClaimNext(ctx context.Context, owner string, now, exp int64) (*store.Task, error) {
	if f.claimErr != nil {
		return nil, f.claimErr
	}
	return f.Store.ClaimNext(ctx, owner, now, exp)
}

func (f failingStore) RecoverExpired(ctx context.Context, now int64) (int, error) {
	if f.recoverErr != nil {
		return 0, f.recoverErr
	}
	return f.Store.RecoverExpired(ctx, now)
}

// TestNackReportsStoreFailure asserts a write failure is surfaced and, crucially,
// that requeued is false — a caller told "requeued" for a task the store never
// touched would silently drop the work.
func TestNackReportsStoreFailure(t *testing.T) {
	boom := errors.New("disk full")
	q := New(failingStore{Store: newStore(t), markFailedErr: boom}, Options{LeaseTTL: time.Minute})

	requeued, err := q.Nack(context.Background(),
		&store.Task{ID: "t1", Attempts: 1, MaxAttempts: 3}, "some failure")
	if !errors.Is(err, boom) {
		t.Fatalf("Nack err = %v, want %v", err, boom)
	}
	if requeued {
		t.Error("requeued must be false when the store write failed")
	}
}

// TestClaimAndRecoverPropagateStoreErrors asserts the read-side primitives do not
// swallow store failures into an "empty queue" answer, which would make the
// dispatcher idle silently.
func TestClaimAndRecoverPropagateStoreErrors(t *testing.T) {
	boom := errors.New("database is locked")
	base := newStore(t)

	q := New(failingStore{Store: base, claimErr: boom}, Options{LeaseTTL: time.Minute})
	task, err := q.Claim(context.Background(), "w1")
	if !errors.Is(err, boom) {
		t.Errorf("Claim err = %v, want %v", err, boom)
	}
	if task != nil {
		t.Errorf("Claim task = %+v, want nil on error", task)
	}

	q = New(failingStore{Store: base, recoverErr: boom}, Options{LeaseTTL: time.Minute})
	n, err := q.RecoverExpired(context.Background())
	if !errors.Is(err, boom) {
		t.Errorf("RecoverExpired err = %v, want %v", err, boom)
	}
	if n != 0 {
		t.Errorf("RecoverExpired n = %d, want 0 on error", n)
	}
}
