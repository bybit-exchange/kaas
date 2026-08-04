package derive

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// fakeJobStore is a minimal in-memory store.DerivedJobStore.
type fakeJobStore struct {
	mu      sync.Mutex
	pending []*store.DerivedJob
	jobs    map[string]*store.DerivedJob
	stages  []string
}

func newFakeJobStore(jobs ...*store.DerivedJob) *fakeJobStore {
	f := &fakeJobStore{jobs: map[string]*store.DerivedJob{}}
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

func (f *fakeJobStore) ListDerivedJobs(context.Context, int) ([]*store.DerivedJob, error) {
	return nil, nil
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
	defer f.mu.Unlock()
	j := f.jobs[id]
	j.Status, j.Error, j.Result, j.Stage = status, errMsg, result, store.DerivedStageDone
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

func runOnce(t *testing.T, js *fakeJobStore, br *fakeBridge) *Runner {
	t.Helper()
	r := NewRunner(js, br, Config{KBDir: "/kb", Model: "default-model",
		PollInterval: time.Millisecond, Timeout: time.Minute}, testLogger())
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	_ = r.Run(ctx)
	return r
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
