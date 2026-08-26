package worker

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// --- stubQueue: a TaskQueue whose every call can be made to fail, so the
// worker's lost-lease and error-swallowing paths can be driven without a store.

type stubQueue struct {
	mu           sync.Mutex
	heartbeatErr error
	setStageErr  error
	ackErr       error
	nackErr      error
	releaseErr   error

	setStageN int
	ackN      int
	nackN     int
	releaseN  int
	ackResult string
	nackMsg   string
	stages    []string
}

func (s *stubQueue) Heartbeat(ctx context.Context, id, owner string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.heartbeatErr
}

func (s *stubQueue) SetStage(ctx context.Context, id, owner, stage string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.setStageN++
	s.stages = append(s.stages, stage)
	return s.setStageErr
}

func (s *stubQueue) Ack(ctx context.Context, id, result string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ackN++
	s.ackResult = result
	return s.ackErr
}

func (s *stubQueue) Nack(ctx context.Context, task *store.Task, errMsg string) (bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.nackN++
	s.nackMsg = errMsg
	if s.nackErr != nil {
		return false, s.nackErr
	}
	return true, nil
}

func (s *stubQueue) Release(ctx context.Context, id, owner string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.releaseN++
	return s.releaseErr
}

func (s *stubQueue) snapshot() (setStageN, ackN, nackN int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.setStageN, s.ackN, s.nackN
}

func (s *stubQueue) releaseCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.releaseN
}

// taskWithRaw builds a claimed-looking task whose raw file contains body.
func taskWithRaw(t *testing.T, body string) *store.Task {
	t.Helper()
	raw := filepath.Join(t.TempDir(), "raw.txt")
	if err := writeFile(raw, body); err != nil {
		t.Fatalf("write raw: %v", err)
	}
	return &store.Task{
		ID: "t1", Source: "paste", RawPath: raw, ContentHash: "h1",
		Status: store.StatusRunning, Stage: store.StageExtract, Attempts: 1, MaxAttempts: 2,
	}
}

// taskWithRawUnder writes the raw document inside kbDir/raw/, which is the
// layout the worker's filepath.Rel assumes: submit.go joins KBDir with "raw".
func taskWithRawUnder(t *testing.T, kbDir, body string) *store.Task {
	t.Helper()
	dir := filepath.Join(kbDir, "raw")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir raw: %v", err)
	}
	raw := filepath.Join(dir, "doc.md")
	if err := writeFile(raw, body); err != nil {
		t.Fatalf("write raw: %v", err)
	}
	return &store.Task{
		ID: "t1", Source: "paste", RawPath: raw, ContentHash: "h1",
		Status: store.StatusRunning, Stage: store.StageExtract, Attempts: 1, MaxAttempts: 2,
	}
}

// --- NewWorker ---

func TestNewWorkerHeartbeatIntervalDefault(t *testing.T) {
	tests := []struct {
		name string
		in   time.Duration
		want time.Duration
	}{
		{"zero falls back", 0, 30 * time.Second},
		{"negative falls back", -time.Second, 30 * time.Second},
		{"explicit value kept", 250 * time.Millisecond, 250 * time.Millisecond},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			w := NewWorker(&stubQueue{}, &fakeEngine{}, newBrk(), "w1", Config{HeartbeatInterval: tc.in})
			if w.cfg.HeartbeatInterval != tc.want {
				t.Errorf("HeartbeatInterval = %v, want %v", w.cfg.HeartbeatInterval, tc.want)
			}
		})
	}
}

// --- Process error paths ---

// TestProcessUnreadableRawNacks asserts a missing raw file fails the task before
// any (paid) LLM call is made.
func TestProcessUnreadableRawNacks(t *testing.T) {
	q := &stubQueue{}
	eng := &fakeEngine{}
	task := taskWithRaw(t, "body")
	task.RawPath = filepath.Join(t.TempDir(), "gone.txt") // never created

	NewWorker(q, eng, newBrk(), "w1", wcfg()).Process(context.Background(), task)

	setStageN, ackN, nackN := q.snapshot()
	if nackN != 1 || ackN != 0 {
		t.Fatalf("want exactly one Nack and no Ack, got nack=%d ack=%d", nackN, ackN)
	}
	if setStageN != 0 {
		t.Errorf("stage must not advance when the raw file is unreadable, got %d SetStage calls", setStageN)
	}
	if eng.extractN != 0 || eng.pipelineN != 0 {
		t.Errorf("engine must not be called, got extract=%d pipeline=%d", eng.extractN, eng.pipelineN)
	}
	if !strings.Contains(q.nackMsg, "read raw") {
		t.Errorf("nack message = %q, want it to explain the read failure", q.nackMsg)
	}
}

// TestProcessSetStageFailureAbandons covers both SetStage failure modes: a lost
// lease (ErrNotFound) and a transient store error. Either way the worker must
// abandon the task without Ack/Nack so RecoverExpired can requeue it, and must
// not spend the pipeline call.
func TestProcessSetStageFailureAbandons(t *testing.T) {
	tests := []struct {
		name string
		err  error
	}{
		{"lease lost", store.ErrNotFound},
		{"transient store error", errors.New("database is locked")},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			q := &stubQueue{setStageErr: tc.err}
			eng := &fakeEngine{}

			NewWorker(q, eng, newBrk(), "w1", wcfg()).Process(context.Background(), taskWithRaw(t, "body"))

			setStageN, ackN, nackN := q.snapshot()
			if setStageN != 1 {
				t.Errorf("SetStage calls = %d, want 1", setStageN)
			}
			if ackN != 0 || nackN != 0 {
				t.Errorf("task must be abandoned, got ack=%d nack=%d", ackN, nackN)
			}
			if eng.extractN != 1 {
				t.Errorf("extract calls = %d, want 1", eng.extractN)
			}
			if eng.pipelineN != 0 {
				t.Errorf("pipeline must not run after a failed stage transition, got %d calls", eng.pipelineN)
			}
		})
	}
}

// TestProcessAdvancesToPipelineStage asserts the one stage transition the worker
// owns (Claim sets extract, MarkSucceeded sets done).
func TestProcessAdvancesToPipelineStage(t *testing.T) {
	q := &stubQueue{}
	NewWorker(q, &fakeEngine{}, newBrk(), "w1", wcfg()).Process(context.Background(), taskWithRaw(t, "body"))

	q.mu.Lock()
	stages := append([]string(nil), q.stages...)
	q.mu.Unlock()
	if len(stages) != 1 || stages[0] != store.StagePipeline {
		t.Fatalf("stages = %v, want exactly [%s]", stages, store.StagePipeline)
	}
}

// TestProcessAckFailureIsNotRetriedAsNack asserts a failed Ack (the lease was
// recovered and the task reclaimed elsewhere) is dropped: nacking it would
// clobber another worker's in-flight attempt.
func TestProcessAckFailureIsNotRetriedAsNack(t *testing.T) {
	q := &stubQueue{ackErr: store.ErrNotFound}

	NewWorker(q, &fakeEngine{}, newBrk(), "w1", wcfg()).Process(context.Background(), taskWithRaw(t, "body"))

	_, ackN, nackN := q.snapshot()
	if ackN != 1 {
		t.Errorf("Ack calls = %d, want 1", ackN)
	}
	if nackN != 0 {
		t.Errorf("a failed Ack must not turn into a Nack, got %d", nackN)
	}
}

// TestProcessNackFailureIsSwallowed asserts a failing Nack is logged, not
// panicked or retried — the task stays for RecoverExpired.
func TestProcessNackFailureIsSwallowed(t *testing.T) {
	q := &stubQueue{nackErr: errors.New("store gone")}
	eng := &fakeEngine{extractErr: errors.New("llm down")}

	NewWorker(q, eng, newBrk(), "w1", wcfg()).Process(context.Background(), taskWithRaw(t, "body"))

	_, ackN, nackN := q.snapshot()
	if nackN != 1 || ackN != 0 {
		t.Fatalf("want one Nack and no Ack, got nack=%d ack=%d", nackN, ackN)
	}
}

// TestProcessAckResultCarriesBothPhases asserts the result JSON handed to Ack
// keeps the extract and pipeline payloads the Status page and cost accounting
// read back.
func TestProcessAckResultCarriesBothPhases(t *testing.T) {
	q := &stubQueue{}
	NewWorker(q, &fakeEngine{}, newBrk(), "w1", wcfg()).Process(context.Background(), taskWithRaw(t, "body"))

	q.mu.Lock()
	result := q.ackResult
	q.mu.Unlock()

	var got map[string]json.RawMessage
	if err := json.Unmarshal([]byte(result), &got); err != nil {
		t.Fatalf("ack result is not JSON: %v (%q)", err, result)
	}
	want := map[string]string{
		"extract_cost":     `{"prompt":10}`,
		"pipeline_cost":    `{"prompt":20}`,
		"pipeline_results": `[{"content_hash":"h1","status":"created"}]`,
	}
	for k, v := range want {
		if string(got[k]) != v {
			t.Errorf("result[%q] = %s, want %s", k, got[k], v)
		}
	}
}

// TestProcessPassesConfigToEngine asserts the worker forwards its config to the
// bridge requests rather than letting the Python side guess.
func TestProcessPassesConfigToEngine(t *testing.T) {
	var extReq bridge.ExtractRequest
	var pipeReq bridge.PipelineRequest
	eng := &recordingEngine{
		onExtract:  func(r bridge.ExtractRequest) { extReq = r },
		onPipeline: func(r bridge.PipelineRequest) { pipeReq = r },
	}
	kbDir := t.TempDir()
	cfg := Config{KBDir: kbDir, PipelineWorkers: 7, HeartbeatInterval: time.Hour,
		Model: "cfg-model", SummarizeModel: "sum-model"}
	task := taskWithRawUnder(t, kbDir, "raw body text")

	NewWorker(&stubQueue{}, eng, newBrk(), "w1", cfg).Process(context.Background(), task)

	if extReq.Content != "raw body text" {
		t.Errorf("extract content = %q, want the raw file body", extReq.Content)
	}
	if extReq.SummarizeModel != "sum-model" {
		t.Errorf("extract summarize model = %q, want %q", extReq.SummarizeModel, "sum-model")
	}
	// The engine persists the extraction, so it needs the KB root and the
	// document's relative path; the model keeps the two routes recording the same
	// extract_model instead of the engine's own literal default.
	if extReq.KBDir != kbDir {
		t.Errorf("extract kb dir = %q, want %q", extReq.KBDir, kbDir)
	}
	if extReq.Source != filepath.Join("raw", "doc.md") {
		t.Errorf("extract source = %q, want raw/doc.md", extReq.Source)
	}
	if extReq.Model != "cfg-model" {
		t.Errorf("extract model = %q, want %q", extReq.Model, "cfg-model")
	}
	if pipeReq.KBDir != kbDir || pipeReq.Workers != 7 {
		t.Errorf("pipeline req = %+v, want KBDir=%s Workers=7", pipeReq, kbDir)
	}
	// The pipeline hop needs the model too. Without it the Python engine falls back
	// to its own literal default, so an endpoint that serves anything else answers
	// every classify call with HTTP 400 and no document ever reaches wiki/.
	if pipeReq.Model != "cfg-model" {
		t.Errorf("pipeline model = %q, want %q", pipeReq.Model, "cfg-model")
	}
	if len(pipeReq.Items) != 1 {
		t.Fatalf("pipeline items = %d, want 1", len(pipeReq.Items))
	}
	item := pipeReq.Items[0]
	// SourceRef must be KB-relative: it becomes the article's sources: entry and
	// the extraction file's key. Forwarding task.RawPath recorded an absolute
	// filesystem path in every article ingested through the HTTP API or the UI.
	if item.ContentHash != task.ContentHash || item.SourceRef != filepath.Join("raw", "doc.md") {
		t.Errorf("pipeline item = %+v, want hash h1 and source raw/doc.md", item)
	}
	if extReq.Source != item.SourceRef {
		t.Errorf("extract source %q and pipeline source ref %q must be the same value",
			extReq.Source, item.SourceRef)
	}
}

// TestProcessFailsWhenTheRawPathIsOutsideTheKB asserts the worker reports rather
// than sending a "../.." source ref that no extraction path could mirror.
func TestProcessFailsWhenTheRawPathIsOutsideTheKB(t *testing.T) {
	eng := &recordingEngine{
		onExtract:  func(bridge.ExtractRequest) {},
		onPipeline: func(bridge.PipelineRequest) {},
	}
	q := &stubQueue{}
	task := taskWithRaw(t, "body")
	cfg := Config{KBDir: "relative-kb", HeartbeatInterval: time.Hour}

	NewWorker(q, eng, newBrk(), "w1", cfg).Process(context.Background(), task)

	if q.nackMsg == "" {
		t.Fatal("expected the task to be nacked")
	}
	if !strings.Contains(q.nackMsg, "relative source ref") {
		t.Errorf("nack message = %q, want it to name the relative source ref", q.nackMsg)
	}
}

// recordingEngine captures the requests it receives and returns fixed payloads.
type recordingEngine struct {
	onExtract  func(bridge.ExtractRequest)
	onPipeline func(bridge.PipelineRequest)
}

func (e *recordingEngine) Extract(ctx context.Context, req bridge.ExtractRequest) (*bridge.ExtractResponse, error) {
	e.onExtract(req)
	return &bridge.ExtractResponse{Extraction: json.RawMessage(`{}`), Cost: json.RawMessage(`{}`)}, nil
}

func (e *recordingEngine) Pipeline(ctx context.Context, req bridge.PipelineRequest) (*bridge.PipelineResponse, error) {
	e.onPipeline(req)
	return &bridge.PipelineResponse{Results: json.RawMessage(`[]`), Cost: json.RawMessage(`{}`)}, nil
}

// --- buildResult ---

func TestBuildResult(t *testing.T) {
	ext := &bridge.ExtractResponse{Cost: json.RawMessage(`{"p":1}`)}
	pipe := &bridge.PipelineResponse{Results: json.RawMessage(`[1]`), Cost: json.RawMessage(`{"p":2}`)}

	tests := []struct {
		name string
		ext  *bridge.ExtractResponse
		pipe *bridge.PipelineResponse
		want string
	}{
		{"both phases", ext, pipe, `{"extract_cost":{"p":1},"pipeline_cost":{"p":2},"pipeline_results":[1]}`},
		{"extract only", ext, nil, `{"extract_cost":{"p":1}}`},
		{"pipeline only", nil, pipe, `{"pipeline_cost":{"p":2},"pipeline_results":[1]}`},
		{"neither", nil, nil, `{}`},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := buildResult(tc.ext, tc.pipe); got != tc.want {
				t.Errorf("buildResult() = %s, want %s", got, tc.want)
			}
		})
	}
}

// TestBuildResultUnmarshalableFallsBackToEmptyObject asserts a malformed cost
// blob from the Python side degrades to "{}" — the result column is NOT NULL and
// the Web UI parses it as JSON, so an empty object must be written.
func TestBuildResultUnmarshalableFallsBackToEmptyObject(t *testing.T) {
	bad := &bridge.ExtractResponse{Cost: json.RawMessage(`{"unterminated":`)}
	if got := buildResult(bad, nil); got != "{}" {
		t.Errorf("buildResult() = %s, want {}", got)
	}
}

// The configured strategy has to reach the engine, or the engine falls back to
// its own default and records an extract_strategy the CLI never expects -- which
// marked every UI-ingested extraction stale on the next CLI compile, forever,
// once per document. Same shape as Model, one field over.
func TestProcessForwardsTheConfiguredStrategy(t *testing.T) {
	var extReq bridge.ExtractRequest
	eng := &recordingEngine{
		onExtract:  func(r bridge.ExtractRequest) { extReq = r },
		onPipeline: func(bridge.PipelineRequest) {},
	}
	kbDir := t.TempDir()
	cfg := Config{KBDir: kbDir, HeartbeatInterval: time.Hour,
		Model: "extract-model", ExtractStrategy: "summarize"}
	task := taskWithRawUnder(t, kbDir, "raw body text")

	NewWorker(&stubQueue{}, eng, newBrk(), "w1", cfg).Process(context.Background(), task)

	if extReq.Strategy != "summarize" {
		t.Errorf("extract strategy = %q, want %q", extReq.Strategy, "summarize")
	}
}
