package derive

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// fakeJobStore is a minimal in-memory store.DerivedJobStore.
type fakeJobStore struct {
	mu      sync.Mutex
	once    sync.Once
	done    chan struct{} // closed once when FinishDerivedJob is first called
	pending []*store.DerivedJob
	jobs    map[string]*store.DerivedJob
	stages  []string
}

func newFakeJobStore(jobs ...*store.DerivedJob) *fakeJobStore {
	f := &fakeJobStore{
		jobs: map[string]*store.DerivedJob{},
		done: make(chan struct{}),
	}
	for _, j := range jobs {
		f.pending = append(f.pending, j)
		f.jobs[j.ID] = j
	}
	return f
}

func (f *fakeJobStore) CreateDerivedJob(context.Context, *store.DerivedJob) error { return nil }

func (f *fakeJobStore) GetDerivedJob(_ context.Context, id string) (*store.DerivedJob, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	j, ok := f.jobs[id]
	if !ok {
		return nil, store.ErrNotFound
	}
	return j, nil
}

func (f *fakeJobStore) ClaimNextDerivedJob(_ context.Context, _ int64) (*store.DerivedJob, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.pending) == 0 {
		return nil, nil
	}
	j := f.pending[0]
	f.pending = f.pending[1:]
	j.Status = store.DerivedStatusRunning
	return j, nil
}

func (f *fakeJobStore) SetDerivedJobStage(_ context.Context, id, stage string, _ int64) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stages = append(f.stages, stage)
	f.jobs[id].Stage = stage
	return nil
}

func (f *fakeJobStore) FinishDerivedJob(_ context.Context, id, status, errMsg, result string, _ int64) error {
	f.mu.Lock()
	j := f.jobs[id]
	j.Status, j.Error, j.Result, j.Stage = status, errMsg, result, store.DerivedStageDone
	f.mu.Unlock()
	// Signal any runOnce waiter that the job has reached a terminal state.
	f.once.Do(func() { close(f.done) })
	return nil
}

func (f *fakeJobStore) RecoverRunningDerivedJobs(context.Context, int64) (int, error) {
	return 0, nil
}

func (f *fakeJobStore) job(id string) store.DerivedJob {
	f.mu.Lock()
	defer f.mu.Unlock()
	return *f.jobs[id]
}

type fakeBridge struct {
	req  bridge.DeriveRequest
	resp *bridge.DeriveResponse
	err  error
}

func (f *fakeBridge) Derive(_ context.Context, req bridge.DeriveRequest) (*bridge.DeriveResponse, error) {
	f.req = req
	return f.resp, f.err
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// runOnce starts Run in a goroutine and returns as soon as FinishDerivedJob
// signals completion, cancelling Run immediately after. A 5-second backstop
// fails the test if the job never finishes; it is not the synchronisation
// mechanism — the done channel is.
func runOnce(t *testing.T, js *fakeJobStore, br *fakeBridge) {
	t.Helper()
	runOnceIn(t, js, br, "/kb")
}

// runOnceIn is runOnce with an explicit KB root, for the cases that need a real
// derived/ directory on disk.
func runOnceIn(t *testing.T, js *fakeJobStore, br *fakeBridge, kbDir string) {
	t.Helper()
	r := NewRunner(js, br, Config{KBDir: kbDir, Model: "default-model",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	runDone := make(chan struct{})
	go func() {
		_ = r.Run(ctx)
		close(runDone)
	}()

	select {
	case <-js.done:
		cancel() // job is terminal; stop the poll loop
	case <-ctx.Done():
		t.Error("runOnce: safety deadline exceeded before job finished")
	}
	<-runDone // wait for Run to return before assertions read store state
}

func TestRunnerRunsAPendingJobToSuccess(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "pricing and fees", Model: "",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{
		Slug: "pricing", Documents: 3, Compiled: true,
		Cost: json.RawMessage(`{"total_cost_usd":1.5}`),
	}}
	runOnce(t, js, br)

	if br.req.KBDir != "/kb" || br.req.Topic != "pricing and fees" || br.req.Slug != "pricing" {
		t.Errorf("request = %+v", br.req)
	}
	if br.req.Model != "default-model" {
		t.Errorf("model = %q, want the server default when the job omits one", br.req.Model)
	}
	got := js.job("j1")
	if got.Status != store.DerivedStatusSucceeded {
		t.Errorf("status = %q, want succeeded (error: %q)", got.Status, got.Error)
	}
	var result bridge.DeriveResponse
	if err := json.Unmarshal([]byte(got.Result), &result); err != nil {
		t.Fatalf("result is not the derive response: %v (%q)", err, got.Result)
	}
	if result.Documents != 3 || !result.Compiled {
		t.Errorf("result = %+v", result)
	}
}

func TestRunnerUsesTheJobsModelOverride(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t", Model: "job-model",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{Slug: "pricing", Compiled: true}}
	runOnce(t, js, br)

	if br.req.Model != "job-model" {
		t.Errorf("model = %q, want job-model", br.req.Model)
	}
}

func TestRunnerRecordsAFailure(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{err: &bridge.APIError{Code: "NO_DOCUMENTS", Message: "nothing to derive"}}
	runOnce(t, js, br)

	got := js.job("j1")
	if got.Status != store.DerivedStatusFailed {
		t.Errorf("status = %q, want failed", got.Status)
	}
	if got.Error == "" || got.Result != "" {
		t.Errorf("error = %q, result = %q", got.Error, got.Result)
	}
	// String-embedding is the only channel for the Python error code; verify it
	// survives the err.Error() path through finish so future changes can't drop it.
	if !strings.Contains(got.Error, "NO_DOCUMENTS") {
		t.Errorf("error = %q, want it to contain the API error code NO_DOCUMENTS", got.Error)
	}
}

func TestRunnerMarksStagesAsItGoes(t *testing.T) {
	js := newFakeJobStore(&store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
	})
	br := &fakeBridge{resp: &bridge.DeriveResponse{Slug: "pricing", Compiled: true}}
	runOnce(t, js, br)

	js.mu.Lock()
	stages := append([]string(nil), js.stages...)
	js.mu.Unlock()
	if len(stages) == 0 || stages[0] != store.DerivedStageCompile {
		t.Errorf("stages = %v, want the compile stage recorded", stages)
	}
}

// TestRunnerForcesOnlyAnIncompleteDerive covers the replace path: the API lets a
// retry through when derived/<slug>/manifest.json says compiled:false, and the
// engine refuses to write into an existing directory without force. The decision
// is made here, at claim time, from what is on disk — not persisted on the job row
// at request time, which would need a schema change and could be stale by now.
func TestRunnerForcesOnlyAnIncompleteDerive(t *testing.T) {
	tests := []struct {
		name      string
		manifest  string // "" = no derived/<slug>/ directory at all
		wantForce bool
	}{
		{"no directory", "", false},
		{"incomplete derive", `{"slug":"pricing","compiled":false}`, true},
		{"manifest without the compiled key", `{"slug":"pricing"}`, true},
		{"compiled kb", `{"slug":"pricing","compiled":true}`, false},
		{"unreadable manifest", `{not json`, false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			kbDir := t.TempDir()
			if tc.manifest != "" {
				dir := filepath.Join(kbDir, "derived", "pricing")
				if err := os.MkdirAll(dir, 0o755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(dir, "manifest.json"),
					[]byte(tc.manifest), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			js := newFakeJobStore(&store.DerivedJob{
				ID: "j1", Slug: "pricing", Topic: "t",
				Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
			})
			br := &fakeBridge{resp: &bridge.DeriveResponse{Slug: "pricing", Compiled: true}}
			runOnceIn(t, js, br, kbDir)

			if br.req.Force != tc.wantForce {
				t.Errorf("force = %v, want %v", br.req.Force, tc.wantForce)
			}
		})
	}
}

func TestRunnerRecoversRunningJobsOnStart(t *testing.T) {
	js := &recordingRecoverStore{fakeJobStore: newFakeJobStore()}
	br := &fakeBridge{}
	r := NewRunner(js, br, Config{KBDir: "/kb", PollInterval: time.Millisecond,
		Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	_ = r.Run(ctx)

	if !js.recovered {
		t.Error("Run did not recover jobs left running by a previous process")
	}
}

type recordingRecoverStore struct {
	*fakeJobStore
	recovered bool
}

func (r *recordingRecoverStore) RecoverRunningDerivedJobs(context.Context, int64) (int, error) {
	r.recovered = true
	return 1, nil
}

func TestRunnerStopsOnContextCancel(t *testing.T) {
	js := newFakeJobStore()
	r := NewRunner(js, &fakeBridge{}, Config{KBDir: "/kb",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := r.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		t.Errorf("Run = %v, want nil or context.Canceled", err)
	}
}

// failRecoverStore returns an error from RecoverRunningDerivedJobs.
type failRecoverStore struct {
	*fakeJobStore
}

func (f *failRecoverStore) RecoverRunningDerivedJobs(context.Context, int64) (int, error) {
	return 0, errors.New("db locked")
}

func TestRunnerRecoveryErrorStopsRun(t *testing.T) {
	js := &failRecoverStore{fakeJobStore: newFakeJobStore()}
	r := NewRunner(js, &fakeBridge{}, Config{KBDir: "/kb",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	err := r.Run(context.Background())
	if err == nil {
		t.Fatal("Run returned nil, want an error when recovery fails")
	}
	if !strings.Contains(err.Error(), "db locked") {
		t.Errorf("err = %v, want it to wrap the recovery error", err)
	}
}

// TestNewRunnerFillsMissingConfig pins the constructor's fallbacks. Both matter
// operationally: a zero PollInterval would make time.NewTicker panic and take
// the process down, and a zero Timeout would let one derive hang forever behind
// the single-flight claim, blocking every later job.
func TestNewRunnerFillsMissingConfig(t *testing.T) {
	r := NewRunner(newFakeJobStore(), &fakeBridge{}, Config{KBDir: "/kb"}, nil)

	if r.cfg.PollInterval != 2*time.Second {
		t.Errorf("PollInterval = %v, want the 2s default", r.cfg.PollInterval)
	}
	if r.cfg.Timeout != 2*time.Hour {
		t.Errorf("Timeout = %v, want the 2h default", r.cfg.Timeout)
	}
	if r.logger == nil {
		t.Error("logger is nil; a nil logger must fall back to slog.Default()")
	}
}

// TestNewRunnerRejectsNegativeDurations covers the same fallbacks reached via
// negative values rather than the zero value, which a hand-edited config file
// can produce.
func TestNewRunnerRejectsNegativeDurations(t *testing.T) {
	r := NewRunner(newFakeJobStore(), &fakeBridge{}, Config{
		KBDir: "/kb", PollInterval: -time.Second, Timeout: -time.Hour,
	}, testLogger())

	if r.cfg.PollInterval != 2*time.Second {
		t.Errorf("PollInterval = %v, want the 2s default", r.cfg.PollInterval)
	}
	if r.cfg.Timeout != 2*time.Hour {
		t.Errorf("Timeout = %v, want the 2h default", r.cfg.Timeout)
	}
}
