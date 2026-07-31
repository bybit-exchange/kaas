package worker

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/store"
)

// stubClaimer is a Claimer with an unlimited task supply, so concurrency limits
// can be observed without a store. Every RecoverExpired call (one per poll tick)
// pushes to ticks, giving tests a deterministic "time has advanced" signal that
// does not rely on sleeping.
type stubClaimer struct {
	mu         sync.Mutex
	claimErr   error
	recoverErr error
	claimN     int
	recoverN   int

	newTask func(n int) *store.Task // nil → claim returns an empty queue
	ticks   chan struct{}
}

func newStubClaimer() *stubClaimer {
	return &stubClaimer{ticks: make(chan struct{}, 256)}
}

func (s *stubClaimer) Claim(ctx context.Context, owner string) (*store.Task, error) {
	s.mu.Lock()
	s.claimN++
	n := s.claimN
	err := s.claimErr
	newTask := s.newTask
	s.mu.Unlock()
	if err != nil {
		return nil, err
	}
	if newTask == nil {
		return nil, nil
	}
	return newTask(n), nil
}

func (s *stubClaimer) RecoverExpired(ctx context.Context) (int, error) {
	s.mu.Lock()
	s.recoverN++
	err := s.recoverErr
	s.mu.Unlock()
	select {
	case s.ticks <- struct{}{}:
	default: // never block the dispatcher
	}
	if err != nil {
		return 0, err
	}
	return 0, nil
}

func (s *stubClaimer) counts() (claimN, recoverN int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.claimN, s.recoverN
}

// waitTicks blocks until the dispatcher has completed n poll ticks.
func (s *stubClaimer) waitTicks(t *testing.T, n int) {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for i := 0; i < n; i++ {
		select {
		case <-s.ticks:
		case <-deadline:
			t.Fatalf("only %d/%d poll ticks observed before timeout", i, n)
		}
	}
}

// runDispatcher starts d.Run and returns a stop function that cancels it and
// waits for a clean return.
func runDispatcher(t *testing.T, d *Dispatcher) func() {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	errc := make(chan error, 1)
	go func() { errc <- d.Run(ctx) }()
	return func() {
		cancel()
		select {
		case err := <-errc:
			if err != nil {
				t.Errorf("Run returned %v, want nil on cancellation", err)
			}
		case <-time.After(5 * time.Second):
			t.Fatal("Run did not return after cancellation")
		}
	}
}

func TestNewDispatcherClampsOptions(t *testing.T) {
	tests := []struct {
		name        string
		poll        time.Duration
		maxConc     int
		wantPoll    time.Duration
		wantMaxConc int
	}{
		{"zero values get safe defaults", 0, 0, time.Second, 1},
		{"negative values get safe defaults", -time.Second, -4, time.Second, 1},
		{"explicit values kept", 20 * time.Millisecond, 3, 20 * time.Millisecond, 3},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			d := NewDispatcher(newStubClaimer(), nil, newBrk(), "w1", tc.poll, tc.maxConc)
			if d.poll != tc.wantPoll {
				t.Errorf("poll = %v, want %v", d.poll, tc.wantPoll)
			}
			if d.maxConc != tc.wantMaxConc {
				t.Errorf("maxConc = %d, want %d", d.maxConc, tc.wantMaxConc)
			}
		})
	}
}

// TestDispatcherSurvivesClaimAndRecoverErrors asserts a failing store does not
// kill the poll loop: the dispatcher keeps ticking so it recovers once the store
// does, and it never leaks the slot it acquired before the failed Claim.
func TestDispatcherSurvivesClaimAndRecoverErrors(t *testing.T) {
	c := newStubClaimer()
	c.claimErr = errors.New("database is locked")
	c.recoverErr = errors.New("recover boom")
	w := NewWorker(&stubQueue{}, &fakeEngine{}, newBrk(), "w1", wcfg())
	d := NewDispatcher(c, w, newBrk(), "w1", time.Millisecond, 2)

	stop := runDispatcher(t, d)
	c.waitTicks(t, 5)
	stop()

	claimN, recoverN := c.counts()
	if recoverN < 5 {
		t.Errorf("RecoverExpired calls = %d, want the loop to keep polling", recoverN)
	}
	// One Claim per tick: a leaked semaphore slot would stop claiming entirely.
	if claimN < 5 {
		t.Errorf("Claim calls = %d after %d ticks, want the slot to be released after each error", claimN, recoverN)
	}
}

// TestDispatcherStopsClaimingWhenEmpty asserts drain gives up on the first empty
// Claim instead of spinning through the whole semaphore each tick.
func TestDispatcherStopsClaimingWhenEmpty(t *testing.T) {
	c := newStubClaimer() // newTask == nil → always empty
	w := NewWorker(&stubQueue{}, &fakeEngine{}, newBrk(), "w1", wcfg())
	d := NewDispatcher(c, w, newBrk(), "w1", time.Millisecond, 8)

	stop := runDispatcher(t, d)
	c.waitTicks(t, 6)
	stop()

	claimN, recoverN := c.counts()
	if claimN > recoverN+1 {
		t.Errorf("Claim calls = %d for %d ticks, want at most one per tick on an empty queue", claimN, recoverN)
	}
}

// TestDispatcherRespectsConcurrencyCap asserts the semaphore actually bounds
// in-flight work: with maxConc=1 and a task stuck in Extract, no second task is
// claimed no matter how many poll ticks elapse, and claiming resumes once the
// slot frees.
func TestDispatcherRespectsConcurrencyCap(t *testing.T) {
	release := make(chan struct{})
	started := make(chan struct{}, 8)
	eng := &fakeEngine{onExtract: func(ctx context.Context) {
		// Non-blocking so a worker goroutine can never wedge on a full channel
		// and stall the drain that Run waits for on shutdown.
		select {
		case started <- struct{}{}:
		default:
		}
		select {
		case <-release:
		case <-ctx.Done():
		}
	}}

	// One shared raw file: building tasks happens on the dispatcher's goroutine,
	// which must not touch *testing.T.
	template := taskWithRaw(t, "body")
	c := newStubClaimer()
	c.newTask = func(n int) *store.Task {
		task := *template
		return &task
	}
	w := NewWorker(&stubQueue{}, eng, newBrk(), "w1", wcfg())
	d := NewDispatcher(c, w, newBrk(), "w1", time.Millisecond, 1)

	stop := runDispatcher(t, d)
	<-started         // first task is in flight, holding the only slot
	c.waitTicks(t, 6) // several further poll ticks pass

	if claimN, _ := c.counts(); claimN != 1 {
		t.Fatalf("Claim calls = %d while the only slot is busy, want 1", claimN)
	}

	close(release) // let the in-flight task finish and free the slot
	<-started      // a second task got claimed and dispatched
	stop()

	if claimN, _ := c.counts(); claimN < 2 {
		t.Errorf("Claim calls = %d, want claiming to resume after the slot freed", claimN)
	}
}
