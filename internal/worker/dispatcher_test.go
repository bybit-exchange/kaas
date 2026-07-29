package worker

import (
	"context"
	"errors"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/queue"
	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
)

func newQClock(t *testing.T, ttl time.Duration) (*queue.Queue, store.Store, *qClock) {
	t.Helper()
	st, err := sqlite.Open(t.TempDir() + "/d.db")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { st.Close() })
	if err := st.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	clk := &qClock{t: time.Unix(1000, 0)}
	return queue.New(st, queue.Options{LeaseTTL: ttl, Clock: clk.now}), st, clk
}

type qClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *qClock) now() time.Time          { c.mu.Lock(); defer c.mu.Unlock(); return c.t }
func (c *qClock) advance(d time.Duration) { c.mu.Lock(); c.t = c.t.Add(d); c.mu.Unlock() }

func submitRaw(t *testing.T, q *queue.Queue, id, hash string) {
	t.Helper()
	dir := t.TempDir()
	raw := dir + "/" + id + ".txt"
	if err := writeFile(raw, "content "+id); err != nil {
		t.Fatalf("write raw: %v", err)
	}
	if err := q.Submit(context.Background(), &store.Task{
		ID: id, Source: "paste", RawPath: raw, ContentHash: hash, MaxAttempts: 2,
	}); err != nil {
		t.Fatalf("Submit %s: %v", id, err)
	}
}

func writeFile(path, body string) error { return os.WriteFile(path, []byte(body), 0o644) }

func waitFor(t *testing.T, cond func() bool, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(2 * time.Millisecond)
	}
	t.Fatal("condition not met before timeout")
}

func TestDispatcherProcessesTasks(t *testing.T) {
	q, st, _ := newQClock(t, time.Minute)
	submitRaw(t, q, "t1", "h1")
	submitRaw(t, q, "t2", "h2")
	eng := &fakeEngine{}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())
	d := NewDispatcher(q, w, newBrk(), "w1", 5*time.Millisecond, 2)

	ctx, cancel := context.WithCancel(context.Background())
	doneRun := make(chan struct{})
	go func() { _ = d.Run(ctx); close(doneRun) }()

	waitFor(t, func() bool {
		a, _ := st.GetTask(context.Background(), "t1")
		b, _ := st.GetTask(context.Background(), "t2")
		return a.Status == store.StatusSucceeded && b.Status == store.StatusSucceeded
	}, 3*time.Second)

	cancel()
	<-doneRun
}

func TestDispatcherPausesWhenBreakerOpen(t *testing.T) {
	q, st, _ := newQClock(t, time.Minute)
	submitRaw(t, q, "t1", "h1")
	brk := circuit.New(circuit.Options{FailureThreshold: 1, Cooldown: time.Hour})
	_ = brk.Do(func() error { return errors.New("trip") }) // open it
	if brk.State() != circuit.StateOpen {
		t.Fatalf("breaker should be open")
	}
	eng := &fakeEngine{}
	w := NewWorker(q, eng, brk, "w1", wcfg())
	d := NewDispatcher(q, w, brk, "w1", 5*time.Millisecond, 2)

	ctx, cancel := context.WithCancel(context.Background())
	doneRun := make(chan struct{})
	go func() { _ = d.Run(ctx); close(doneRun) }()
	time.Sleep(40 * time.Millisecond) // several poll ticks
	cancel()
	<-doneRun

	got, _ := st.GetTask(context.Background(), "t1")
	if got.Status != store.StatusPending {
		t.Fatalf("task should stay pending while breaker open, got %s", got.Status)
	}
	if eng.extractN != 0 {
		t.Fatalf("engine must not be called while breaker open")
	}
}

func TestDispatcherRecoversExpiredLease(t *testing.T) {
	q, st, clk := newQClock(t, time.Minute)
	submitRaw(t, q, "t1", "h1")
	// Simulate a dead worker holding the lease.
	if _, err := q.Claim(context.Background(), "dead"); err != nil {
		t.Fatalf("Claim: %v", err)
	}
	clk.advance(2 * time.Minute) // lease now expired

	eng := &fakeEngine{}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())
	d := NewDispatcher(q, w, newBrk(), "w1", 5*time.Millisecond, 1)

	ctx, cancel := context.WithCancel(context.Background())
	doneRun := make(chan struct{})
	go func() { _ = d.Run(ctx); close(doneRun) }()
	waitFor(t, func() bool {
		got, _ := st.GetTask(context.Background(), "t1")
		return got.Status == store.StatusSucceeded
	}, 3*time.Second)
	cancel()
	<-doneRun
}

func TestDispatcherGracefulShutdownDrains(t *testing.T) {
	q, st, _ := newQClock(t, time.Minute)
	submitRaw(t, q, "t1", "h1")
	release := make(chan struct{})
	eng := &fakeEngine{onExtract: func(ctx context.Context) {
		select {
		case <-release:
		case <-ctx.Done():
		}
	}}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())
	d := NewDispatcher(q, w, newBrk(), "w1", 5*time.Millisecond, 1)

	ctx, cancel := context.WithCancel(context.Background())
	doneRun := make(chan struct{})
	go func() { _ = d.Run(ctx); close(doneRun) }()

	waitFor(t, func() bool {
		got, _ := st.GetTask(context.Background(), "t1")
		return got.Status == store.StatusRunning
	}, 2*time.Second) // task claimed & in flight

	cancel() // request shutdown while task in flight
	// Run must not return until the in-flight task drains.
	select {
	case <-doneRun:
		t.Fatal("Run returned before draining in-flight task")
	case <-time.After(30 * time.Millisecond):
	}
	close(release) // let the task finish
	select {
	case <-doneRun:
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after drain")
	}
	got, _ := st.GetTask(context.Background(), "t1")
	if got.Status != store.StatusSucceeded {
		t.Fatalf("in-flight task should complete on drain, got %s", got.Status)
	}
}
