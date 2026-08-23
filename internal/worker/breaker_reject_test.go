package worker

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/queue"
	"github.com/bybit-exchange/kaas/internal/store"
)

// openBrk returns a breaker that is open and stays open for the whole test, so
// every brk.Do is rejected without reaching the engine.
func openBrk(t *testing.T) *circuit.Breaker {
	t.Helper()
	brk := circuit.New(circuit.Options{FailureThreshold: 1, Cooldown: time.Hour})
	_ = brk.Do(func() error { return errors.New("engine down") })
	if got := brk.State(); got != circuit.StateOpen {
		t.Fatalf("breaker state = %v, want open", got)
	}
	return brk
}

// hookQueue runs hook from SetStage, which the worker calls between its two
// brk.Do calls — the only place a test can change the breaker's state after
// Extract has succeeded but before Pipeline is attempted.
type hookQueue struct {
	*queue.Queue
	hook func()
}

func (h *hookQueue) SetStage(ctx context.Context, id, owner, stage string) error {
	h.hook()
	return h.Queue.SetStage(ctx, id, owner, stage)
}

// TestProcessBreakerRejectionKeepsTheAttempt asserts a rejected call is not
// charged to the document: the engine never ran, so the task returns to the
// queue with its retry budget intact instead of being Nacked.
func TestProcessBreakerRejectionKeepsTheAttempt(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{}
	w := NewWorker(q, eng, openBrk(t), "w1", wcfg())

	w.Process(context.Background(), task)

	if eng.extractN != 0 {
		t.Fatalf("Extract calls = %d, want 0 while the breaker is open", eng.extractN)
	}
	got, err := st.GetTask(context.Background(), "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending {
		t.Errorf("Status = %q, want %q", got.Status, store.StatusPending)
	}
	if got.Attempts != 0 {
		t.Errorf("Attempts = %d, want 0 — a rejected call must not spend a retry", got.Attempts)
	}
	if got.Error != "" {
		t.Errorf("Error = %q, want empty — the document did not fail", got.Error)
	}
}

// TestProcessBreakerRejectionOutlastsMaxAttempts is the 500-article defect in
// miniature. With extract_workers at 12 the dispatcher hands out a batch but the
// breaker admits one trial, so a healthy document can be refused round after
// round; before the fix each refusal spent an attempt and the document failed
// permanently once max_attempts ran out.
func TestProcessBreakerRejectionOutlastsMaxAttempts(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1") // MaxAttempts 2
	brk := openBrk(t)
	w := NewWorker(q, &fakeEngine{}, brk, "w1", wcfg())

	for round := 1; round <= 4; round++ {
		w.Process(context.Background(), task)

		got, err := st.GetTask(context.Background(), "t1")
		if err != nil {
			t.Fatalf("round %d: GetTask: %v", round, err)
		}
		if got.Status != store.StatusPending {
			t.Fatalf("round %d: Status = %q, want the document still queued", round, got.Status)
		}
		task, err = q.Claim(context.Background(), "w1")
		if err != nil || task == nil {
			t.Fatalf("round %d: Claim: task=%v err=%v", round, task, err)
		}
	}
}

// TestProcessBreakerRejectionAtPipelineKeepsTheAttempt covers the other half of
// the window: Extract already succeeded and persisted its result, then the
// breaker opened. The document still did nothing wrong, so the attempt goes back
// and the cached extraction is replayed for free on the next delivery.
func TestProcessBreakerRejectionAtPipelineKeepsTheAttempt(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	brk := circuit.New(circuit.Options{FailureThreshold: 1, Cooldown: time.Hour})
	hq := &hookQueue{Queue: q, hook: func() {
		_ = brk.Do(func() error { return errors.New("engine down") })
	}}
	eng := &fakeEngine{}
	w := NewWorker(hq, eng, brk, "w1", wcfg())

	w.Process(context.Background(), task)

	if eng.extractN != 1 || eng.pipelineN != 0 {
		t.Fatalf("Extract/Pipeline calls = %d/%d, want 1/0", eng.extractN, eng.pipelineN)
	}
	got, err := st.GetTask(context.Background(), "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending {
		t.Errorf("Status = %q, want %q", got.Status, store.StatusPending)
	}
	if got.Attempts != 0 {
		t.Errorf("Attempts = %d, want 0", got.Attempts)
	}
}

// TestProcessEngineErrorStillSpendsTheAttempt guards the opposite direction: the
// hand-back is for breaker rejections only. A real engine failure is the
// document's problem and must keep counting against max_attempts, otherwise a
// poison document retries forever.
func TestProcessEngineErrorStillSpendsTheAttempt(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{extractErr: errors.New("llm down")}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())

	w.Process(context.Background(), task)

	got, err := st.GetTask(context.Background(), "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Status != store.StatusPending {
		t.Fatalf("Status = %q, want %q with one retry left", got.Status, store.StatusPending)
	}
	if got.Attempts != 1 {
		t.Errorf("Attempts = %d, want 1 — a real failure spends a retry", got.Attempts)
	}
	if got.Error == "" {
		t.Error("Error is empty, want the engine failure recorded")
	}
}

// TestProcessReleaseFailureIsSwallowed asserts a failing Release is logged, not
// panicked or escalated into a Nack — the task stays for RecoverExpired, which
// costs it the attempt but keeps the queue moving.
func TestProcessReleaseFailureIsSwallowed(t *testing.T) {
	sq := &stubQueue{releaseErr: errors.New("store gone")}
	w := NewWorker(sq, &fakeEngine{}, openBrk(t), "w1", wcfg())

	w.Process(context.Background(), taskWithRaw(t, "body"))

	if sq.releaseCount() != 1 {
		t.Fatalf("Release calls = %d, want 1", sq.releaseCount())
	}
	if _, _, nackN := sq.snapshot(); nackN != 0 {
		t.Errorf("a failed Release must not turn into a Nack, got %d", nackN)
	}
}

// TestProcessBreakerRejectionAfterLeaseLossAbandons asserts a rejection on a
// task whose lease is already gone takes the same road as a failure: no write at
// all, because the row belongs to whoever RecoverExpired hands it to next.
func TestProcessBreakerRejectionAfterLeaseLossAbandons(t *testing.T) {
	sq := &stubQueue{}
	task := taskWithRaw(t, "body")
	w := NewWorker(sq, &fakeEngine{}, openBrk(t), "w1", wcfg())

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // lease lost / shutdown before the breaker refused

	w.Process(ctx, task)

	if sq.releaseCount() != 0 {
		t.Errorf("Release calls = %d, want 0 on a cancelled context", sq.releaseCount())
	}
	if _, _, nackN := sq.snapshot(); nackN != 0 {
		t.Errorf("Nack calls = %d, want 0 on a cancelled context", nackN)
	}
}
