// Package queue provides a lease-based task queue on top of store.Store.
//
// Workers Submit tasks, Claim them (taking a time-bounded lease), Heartbeat to
// extend the lease during long work, then Ack on success or Nack on failure.
// Nack re-queues the task until its attempt ceiling is reached. RecoverExpired
// reclaims tasks whose owner died mid-work.
package queue

import (
	"context"
	"time"

	"github.com/bybit-exchange/kaas/internal/store"
)

// Clock returns the current time. Injected so tests can advance leases without
// sleeping.
type Clock func() time.Time

// Queue is a lease-based view over a store.Store.
type Queue struct {
	store    store.Store
	leaseTTL time.Duration
	now      Clock
}

// Options configures a Queue.
type Options struct {
	// LeaseTTL is how long a claimed task stays leased before it can be
	// recovered. Defaults to 5 minutes if zero.
	LeaseTTL time.Duration
	// Clock overrides the time source (defaults to time.Now).
	Clock Clock
}

// New builds a Queue over s.
func New(s store.Store, opts Options) *Queue {
	if opts.LeaseTTL <= 0 {
		opts.LeaseTTL = 5 * time.Minute
	}
	if opts.Clock == nil {
		opts.Clock = time.Now
	}
	return &Queue{store: s, leaseTTL: opts.LeaseTTL, now: opts.Clock}
}

func (q *Queue) nowMS() int64 { return q.now().UnixMilli() }

// Submit enqueues a new task as pending. Caller supplies ID/Source/RawPath/
// ContentHash/MaxAttempts; Submit stamps status, stage, and timestamps.
// Returns store.ErrDuplicate if the content_hash already exists.
func (q *Queue) Submit(ctx context.Context, t *store.Task) error {
	now := q.nowMS()
	t.Status = store.StatusPending
	t.Stage = store.StageQueued
	t.Attempts = 0
	if t.MaxAttempts <= 0 {
		t.MaxAttempts = 1
	}
	t.LeaseOwner = ""
	t.LeaseExpiresAt = 0
	t.CreatedAt = now
	t.UpdatedAt = now
	return q.store.CreateTask(ctx, t)
}

// Claim takes the oldest pending task for owner with a fresh lease. Returns
// (nil, nil) when the queue is empty.
func (q *Queue) Claim(ctx context.Context, owner string) (*store.Task, error) {
	now := q.nowMS()
	exp := q.now().Add(q.leaseTTL).UnixMilli()
	return q.store.ClaimNext(ctx, owner, now, exp)
}

// Heartbeat extends owner's lease on a task it still holds.
func (q *Queue) Heartbeat(ctx context.Context, id, owner string) error {
	exp := q.now().Add(q.leaseTTL).UnixMilli()
	return q.store.Heartbeat(ctx, id, owner, exp)
}

// SetStage updates owner's task progress stage (owner-scoped; see store.SetStage).
func (q *Queue) SetStage(ctx context.Context, id, owner, stage string) error {
	return q.store.SetStage(ctx, id, owner, stage, q.nowMS())
}

// Ack marks a claimed task succeeded with the given result JSON.
func (q *Queue) Ack(ctx context.Context, id, result string) error {
	return q.store.MarkSucceeded(ctx, id, result, q.nowMS())
}

// Nack reports a failed attempt. The task is re-queued if it has retries left
// (attempts < max_attempts), otherwise marked permanently failed. It returns
// whether the task was re-queued.
//
// task is the value returned by Claim, whose Attempts reflects this delivery.
func (q *Queue) Nack(ctx context.Context, task *store.Task, errMsg string) (requeued bool, err error) {
	retry := task.Attempts < task.MaxAttempts
	if err := q.store.MarkFailed(ctx, task.ID, errMsg, retry, q.nowMS()); err != nil {
		return false, err
	}
	return retry, nil
}

// Release returns a claimed task to the queue without charging it an attempt.
// Use it when the delivery did no work — the caller was refused before reaching
// the engine — so the task's retry budget is untouched. Unlike Nack it records
// no error and never marks the task failed.
func (q *Queue) Release(ctx context.Context, id, owner string) error {
	return q.store.ReleaseTask(ctx, id, owner, q.nowMS())
}

// RecoverExpired re-queues tasks whose lease has elapsed. Returns the count.
func (q *Queue) RecoverExpired(ctx context.Context) (int, error) {
	return q.store.RecoverExpired(ctx, q.nowMS())
}
