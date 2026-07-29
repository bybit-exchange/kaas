package worker

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/queue"
	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
)

// *queue.Queue must satisfy the worker's TaskQueue interface.
var _ TaskQueue = (*queue.Queue)(nil)

// --- fakes ---

type fakeEngine struct {
	mu          sync.Mutex
	extractN    int
	pipelineN   int
	extractErr  error
	pipelineErr error
	onExtract   func(ctx context.Context) // optional hook (blocking tests)
}

func (f *fakeEngine) Extract(ctx context.Context, req bridge.ExtractRequest) (*bridge.ExtractResponse, error) {
	if f.onExtract != nil {
		f.onExtract(ctx)
	}
	f.mu.Lock()
	f.extractN++
	f.mu.Unlock()
	if f.extractErr != nil {
		return nil, f.extractErr
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return &bridge.ExtractResponse{
		Extraction: json.RawMessage(`{"concepts":[]}`),
		Cost:       json.RawMessage(`{"prompt":10}`),
	}, nil
}

func (f *fakeEngine) Pipeline(ctx context.Context, req bridge.PipelineRequest) (*bridge.PipelineResponse, error) {
	f.mu.Lock()
	f.pipelineN++
	f.mu.Unlock()
	if f.pipelineErr != nil {
		return nil, f.pipelineErr
	}
	return &bridge.PipelineResponse{
		Results: json.RawMessage(`[{"content_hash":"h1","status":"created"}]`),
		Cost:    json.RawMessage(`{"prompt":20}`),
	}, nil
}

// spyQueue wraps a real *queue.Queue, counting Heartbeat calls and optionally
// forcing Heartbeat to fail.
type spyQueue struct {
	*queue.Queue
	mu           sync.Mutex
	heartbeatN   int
	heartbeatErr error
}

func (s *spyQueue) Heartbeat(ctx context.Context, id, owner string) error {
	s.mu.Lock()
	s.heartbeatN++
	herr := s.heartbeatErr
	s.mu.Unlock()
	if herr != nil {
		return herr
	}
	return s.Queue.Heartbeat(ctx, id, owner)
}

func (s *spyQueue) hbCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.heartbeatN
}

// --- helpers ---

func newQ(t *testing.T) (*queue.Queue, store.Store) {
	t.Helper()
	st, err := sqlite.Open(filepath.Join(t.TempDir(), "w.db"))
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { st.Close() })
	if err := st.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	return queue.New(st, queue.Options{LeaseTTL: time.Minute}), st
}

func submitAndClaim(t *testing.T, q *queue.Queue, owner string) *store.Task {
	t.Helper()
	dir := t.TempDir()
	raw := filepath.Join(dir, "raw.txt")
	if err := os.WriteFile(raw, []byte("hello world"), 0o644); err != nil {
		t.Fatalf("write raw: %v", err)
	}
	if err := q.Submit(context.Background(), &store.Task{
		ID: "t1", Source: "paste", RawPath: raw, ContentHash: "h1", MaxAttempts: 2,
	}); err != nil {
		t.Fatalf("Submit: %v", err)
	}
	task, err := q.Claim(context.Background(), owner)
	if err != nil || task == nil {
		t.Fatalf("Claim: task=%v err=%v", task, err)
	}
	return task
}

func newBrk() *circuit.Breaker {
	return circuit.New(circuit.Options{FailureThreshold: 5, Cooldown: time.Second})
}

func wcfg() Config {
	return Config{KBDir: "/tmp/kb", PipelineWorkers: 2, HeartbeatInterval: 5 * time.Millisecond}
}

// --- tests ---

func TestProcessHappyPath(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())

	w.Process(context.Background(), task)

	final, err := st.GetTask(context.Background(), "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if final.Status != store.StatusSucceeded || final.Stage != store.StageDone {
		t.Fatalf("want succeeded/done, got %s/%s", final.Status, final.Stage)
	}
	if eng.extractN != 1 || eng.pipelineN != 1 {
		t.Fatalf("want 1 extract + 1 pipeline, got %d/%d", eng.extractN, eng.pipelineN)
	}
	var res map[string]json.RawMessage
	if err := json.Unmarshal([]byte(final.Result), &res); err != nil {
		t.Fatalf("result not JSON: %v (%q)", err, final.Result)
	}
	if _, ok := res["pipeline_results"]; !ok {
		t.Fatalf("result missing pipeline_results: %q", final.Result)
	}
}

func TestProcessExtractErrorNacks(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{extractErr: errors.New("llm down")}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())

	w.Process(context.Background(), task)

	final, _ := st.GetTask(context.Background(), "t1")
	// MaxAttempts=2, attempts=1 after claim → retry → back to pending
	if final.Status != store.StatusPending {
		t.Fatalf("want requeued pending, got %s", final.Status)
	}
	if eng.pipelineN != 0 {
		t.Fatalf("pipeline must not run after extract failure")
	}
}

func TestProcessExhaustsAttempts(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1") // attempts now 1, max 2
	eng := &fakeEngine{extractErr: errors.New("llm down")}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())
	w.Process(context.Background(), task) // → pending (retry)

	task2, _ := q.Claim(context.Background(), "w1") // attempts now 2
	w.Process(context.Background(), task2)          // → failed (no retry left)

	final, _ := st.GetTask(context.Background(), "t1")
	if final.Status != store.StatusFailed {
		t.Fatalf("want failed after exhausting attempts, got %s", final.Status)
	}
}

func TestProcessLostLeaseAbandons(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{}
	spy := &spyQueue{Queue: q, heartbeatErr: store.ErrNotFound}
	// Force heartbeat to fail on first tick; engine blocks until ctx cancelled.
	eng.onExtract = func(ctx context.Context) { <-ctx.Done() }
	w := NewWorker(spy, eng, newBrk(), "w1", wcfg())

	done := make(chan struct{})
	go func() { w.Process(context.Background(), task); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Process did not return after lease loss")
	}
	// Task was never Acked/Nacked by us; still running (lease will be recovered).
	final, _ := st.GetTask(context.Background(), "t1")
	if final.Status != store.StatusRunning {
		t.Fatalf("want still running (abandoned), got %s", final.Status)
	}
}

func TestProcessPipelineErrorNacks(t *testing.T) {
	q, st := newQ(t)
	task := submitAndClaim(t, q, "w1")
	eng := &fakeEngine{pipelineErr: errors.New("pipeline boom")}
	w := NewWorker(q, eng, newBrk(), "w1", wcfg())

	w.Process(context.Background(), task)

	final, _ := st.GetTask(context.Background(), "t1")
	// MaxAttempts=2, attempts=1 after claim → retry → back to pending; MarkFailed resets stage.
	if final.Status != store.StatusPending {
		t.Fatalf("want requeued pending after pipeline error, got %s", final.Status)
	}
	if eng.extractN != 1 || eng.pipelineN != 1 {
		t.Fatalf("want extract+pipeline both attempted once, got %d/%d", eng.extractN, eng.pipelineN)
	}
	if final.Stage != store.StageQueued {
		t.Fatalf("want stage reset to queued on requeue, got %s", final.Stage)
	}
}

func TestProcessHeartbeats(t *testing.T) {
	q, _ := newQ(t)
	task := submitAndClaim(t, q, "w1")
	release := make(chan struct{})
	eng := &fakeEngine{onExtract: func(ctx context.Context) {
		select {
		case <-release:
		case <-ctx.Done():
		}
	}}
	spy := &spyQueue{Queue: q}
	w := NewWorker(spy, eng, newBrk(), "w1", wcfg()) // hb interval 5ms

	done := make(chan struct{})
	go func() { w.Process(context.Background(), task); close(done) }()
	time.Sleep(30 * time.Millisecond) // allow several heartbeat ticks
	if spy.hbCount() < 1 {
		t.Fatalf("expected ≥1 heartbeat during slow extract, got %d", spy.hbCount())
	}
	close(release)
	<-done
}
