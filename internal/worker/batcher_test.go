package worker

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
)

// --- echoEngine: records Pipeline calls, optionally blocks or delays each
// one, and by default echoes every item back as a successful per-item result.

// echoResults is the default Pipeline response body shared by the worker test
// engines: every request item echoed back as a successful per-item result.
func echoResults(req bridge.PipelineRequest) json.RawMessage {
	items := make([]map[string]string, 0, len(req.Items))
	for _, it := range req.Items {
		items = append(items, map[string]string{"content_hash": it.ContentHash, "status": "created"})
	}
	b, _ := json.Marshal(items)
	return b
}

type echoEngine struct {
	mu          sync.Mutex
	calls       []bridge.PipelineRequest
	ctxs        []context.Context
	inflightN   int
	maxInflight int

	// Fixed before Run starts; read inside Pipeline under the lock.
	err     error
	results json.RawMessage // overrides the echo when set
	cost    json.RawMessage
	block   chan struct{} // when set, every call waits for the close
	delay   time.Duration
}

func (e *echoEngine) Extract(ctx context.Context, req bridge.ExtractRequest) (*bridge.ExtractResponse, error) {
	return &bridge.ExtractResponse{Extraction: json.RawMessage(`{}`), Cost: json.RawMessage(`{}`)}, nil
}

func (e *echoEngine) Pipeline(ctx context.Context, req bridge.PipelineRequest) (*bridge.PipelineResponse, error) {
	e.mu.Lock()
	e.inflightN++
	if e.inflightN > e.maxInflight {
		e.maxInflight = e.inflightN
	}
	e.calls = append(e.calls, req)
	e.ctxs = append(e.ctxs, ctx)
	block, delay, err, results, cost := e.block, e.delay, e.err, e.results, e.cost
	e.mu.Unlock()
	defer func() {
		e.mu.Lock()
		e.inflightN--
		e.mu.Unlock()
	}()

	if delay > 0 {
		time.Sleep(delay)
	}
	if block != nil {
		<-block
	}
	if err != nil {
		return nil, err
	}
	if results != nil {
		return &bridge.PipelineResponse{Results: results, Cost: cost}, nil
	}
	return &bridge.PipelineResponse{Results: echoResults(req), Cost: cost}, nil
}

func (e *echoEngine) callCount() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return len(e.calls)
}

func (e *echoEngine) snapshotCalls() []bridge.PipelineRequest {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]bridge.PipelineRequest(nil), e.calls...)
}

func (e *echoEngine) maxConcurrent() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.maxInflight
}

func (e *echoEngine) inflightNow() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.inflightN
}

// --- helpers ---

// newTestBatcher builds a batcher whose base request carries the fields the
// passthrough assertions check.
func newTestBatcher(eng Engine, brk *circuit.Breaker, cfg BatcherConfig) *PipelineBatcher {
	return NewPipelineBatcher(eng, brk, cfg, func() bridge.PipelineRequest {
		return bridge.PipelineRequest{KBDir: "/kb", Model: "m", Workers: 3}
	})
}

// runBatcher starts the collect loop under a cancellable context and drains
// it on cleanup.
func runBatcher(t *testing.T, b *PipelineBatcher) context.CancelFunc {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Errorf("batcher Run did not exit within 5s")
		}
		b.Close()
	})
	go func() { b.Run(ctx); close(done) }()
	return cancel
}

type submitResult struct {
	itemRes json.RawMessage
	cost    json.RawMessage
	err     error
}

// submitTo submits hash and reports the outcome on ch (buffered).
func submitTo(ch chan submitResult, b *PipelineBatcher, ctx context.Context, hash string) {
	res, cost, err := b.Submit(ctx, bridge.PipelineItem{ContentHash: hash})
	ch <- submitResult{itemRes: res, cost: cost, err: err}
}

func goSubmit(b *PipelineBatcher, ctx context.Context, hash string) chan submitResult {
	ch := make(chan submitResult, 1)
	go submitTo(ch, b, ctx, hash)
	return ch
}

func recvSubmit(t *testing.T, ch chan submitResult) submitResult {
	t.Helper()
	select {
	case r := <-ch:
		return r
	case <-time.After(5 * time.Second):
		t.Fatal("Submit did not return within 5s")
		return submitResult{}
	}
}

// itemHash extracts content_hash from a per-item result blob.
func itemHash(t *testing.T, raw json.RawMessage) string {
	t.Helper()
	var item struct {
		ContentHash string `json:"content_hash"`
		Status      string `json:"status"`
	}
	if err := json.Unmarshal(raw, &item); err != nil {
		t.Fatalf("item result is not JSON: %v (%s)", err, raw)
	}
	return item.ContentHash
}

// --- tests ---

// TestBatcherSizeTriggerFlush: a full batch dispatches exactly one Pipeline
// call, each waiter gets its own result by content_hash, and the base
// request's common fields plus BatchDeadline reach the engine.
func TestBatcherSizeTriggerFlush(t *testing.T) {
	eng := &echoEngine{cost: json.RawMessage(`{"prompt":20}`)}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:      4,
		FlushWait:     10 * time.Second, // size trigger only
		MaxInflight:   2,
		BatchDeadline: 2400 * time.Second,
	})
	runBatcher(t, b)

	hashes := []string{"h1", "h2", "h3", "h4"}
	chs := make([]chan submitResult, len(hashes))
	for i, h := range hashes {
		chs[i] = goSubmit(b, context.Background(), h)
	}
	for i, ch := range chs {
		r := recvSubmit(t, ch)
		if r.err != nil {
			t.Fatalf("Submit(%s) err = %v", hashes[i], r.err)
		}
		if got := itemHash(t, r.itemRes); got != hashes[i] {
			t.Errorf("waiter %s got result for %q", hashes[i], got)
		}
		if string(r.cost) != `{"prompt":20}` {
			t.Errorf("batch cost = %s, want the shared batch blob", r.cost)
		}
	}

	calls := eng.snapshotCalls()
	if len(calls) != 1 {
		t.Fatalf("Pipeline calls = %d, want 1", len(calls))
	}
	if len(calls[0].Items) != 4 {
		t.Fatalf("batch items = %d, want 4", len(calls[0].Items))
	}
	if calls[0].KBDir != "/kb" || calls[0].Model != "m" || calls[0].Workers != 3 {
		t.Errorf("base fields not forwarded: %+v", calls[0])
	}
	if calls[0].DeadlineSeconds != 2400 {
		t.Errorf("DeadlineSeconds = %d, want 2400", calls[0].DeadlineSeconds)
	}
}

// TestBatcherTimeTriggerFlush: a partial batch flushes once its oldest item
// reaches FlushWait, without waiting for MaxItems.
func TestBatcherTimeTriggerFlush(t *testing.T) {
	eng := &echoEngine{}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:    8,
		FlushWait:   40 * time.Millisecond,
		MaxInflight: 1,
	})
	runBatcher(t, b)

	start := time.Now()
	r := recvSubmit(t, goSubmit(b, context.Background(), "h1"))
	if r.err != nil {
		t.Fatalf("Submit err = %v", r.err)
	}
	if elapsed := time.Since(start); elapsed < 30*time.Millisecond {
		t.Errorf("flush fired after %v, want it to wait for the FlushWait window", elapsed)
	}
	calls := eng.snapshotCalls()
	if len(calls) != 1 || len(calls[0].Items) != 1 {
		t.Fatalf("calls = %d (items %d), want a single 1-item call", len(calls), len(calls[0].Items))
	}
}

// TestBatcherMaxInflightCap: with a slow engine and MaxInflight=2, five
// batches never produce more than 2 concurrent Pipeline calls.
func TestBatcherMaxInflightCap(t *testing.T) {
	eng := &echoEngine{delay: 60 * time.Millisecond}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:    1, // each item is its own batch
		MaxInflight: 2,
	})
	runBatcher(t, b)

	chs := make([]chan submitResult, 5)
	for i := range chs {
		chs[i] = goSubmit(b, context.Background(), "h")
	}
	for _, ch := range chs {
		if r := recvSubmit(t, ch); r.err != nil {
			t.Fatalf("Submit err = %v", r.err)
		}
	}
	if got := eng.maxConcurrent(); got > 2 {
		t.Errorf("max concurrent Pipeline calls = %d, want <= 2", got)
	}
	if got := eng.callCount(); got != 5 {
		t.Errorf("Pipeline calls = %d, want 5", got)
	}
}

// TestBatcherCallFailureFansSameError: a call-level failure delivers the same
// error to every waiter in the batch.
func TestBatcherCallFailureFansSameError(t *testing.T) {
	boom := errors.New("batch transport down")
	eng := &echoEngine{err: boom}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{MaxItems: 3, MaxInflight: 1})
	runBatcher(t, b)

	chs := []chan submitResult{
		goSubmit(b, context.Background(), "h1"),
		goSubmit(b, context.Background(), "h2"),
		goSubmit(b, context.Background(), "h3"),
	}
	for i, ch := range chs {
		r := recvSubmit(t, ch)
		if !errors.Is(r.err, boom) {
			t.Fatalf("waiter %d err = %v, want the shared call error", i+1, r.err)
		}
		if r.itemRes != nil || r.cost != nil {
			t.Errorf("waiter %d should get no result blobs on error", i+1)
		}
	}
}

// TestBatcherWaiterCancelDoesNotAffectBatch: cancelling one waiter's ctx
// abandons only that waiter; the batch call still runs and completes for the
// others.
func TestBatcherWaiterCancelDoesNotAffectBatch(t *testing.T) {
	block := make(chan struct{})
	eng := &echoEngine{block: block}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{MaxItems: 2, MaxInflight: 1})
	runBatcher(t, b)

	wctx, cancelWaiter := context.WithCancel(context.Background())
	h1ch := goSubmit(b, context.Background(), "h1")
	h2ch := goSubmit(b, wctx, "h2")
	waitFor(t, func() bool { return eng.callCount() == 1 }, 2*time.Second)

	cancelWaiter()
	// The cancelled waiter returns promptly with its ctx error...
	select {
	case r := <-h2ch:
		if !errors.Is(r.err, context.Canceled) {
			t.Fatalf("cancelled waiter err = %v, want context.Canceled", r.err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("cancelled Submit did not return")
	}
	// ...while the batch is still in flight for the remaining waiter.
	if got := eng.inflightNow(); got != 1 {
		t.Fatalf("in-flight calls = %d, want 1 (batch must survive waiter cancel)", got)
	}
	close(block)

	r := recvSubmit(t, h1ch)
	if r.err != nil {
		t.Fatalf("surviving waiter err = %v", r.err)
	}
	if got := itemHash(t, r.itemRes); got != "h1" {
		t.Errorf("surviving waiter got result for %q", got)
	}
	if got := eng.callCount(); got != 1 {
		t.Errorf("Pipeline calls = %d, want 1 (no re-issue for the cancelled waiter)", got)
	}
}

// TestBatcherDetachedContextSurvivesAppCancel: cancelling the app ctx (the
// one Run received) while a batch is in flight does not cancel the batch
// call — it runs on a detached context.Background() and its waiter still gets
// the result.
func TestBatcherDetachedContextSurvivesAppCancel(t *testing.T) {
	block := make(chan struct{})
	eng := &echoEngine{block: block}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{MaxItems: 1, MaxInflight: 1})
	appCancel := runBatcher(t, b)

	h1ch := goSubmit(b, context.Background(), "h1")
	waitFor(t, func() bool { return eng.callCount() == 1 }, 2*time.Second)

	appCancel()
	if eng.ctxs[0].Err() != nil {
		t.Errorf("batch call ctx was cancelled by the app ctx: %v", eng.ctxs[0].Err())
	}
	close(block)

	r := recvSubmit(t, h1ch)
	if r.err != nil {
		t.Fatalf("waiter err = %v, want the detached batch to complete", r.err)
	}
	waitFor(t, func() bool {
		select {
		case <-b.runDone:
			return true
		default:
			return false
		}
	}, 2*time.Second)
}

// TestBatcherCloseWaitsAndFlushesFinalBatch: Close flushes the leftover batch
// and returns only after every in-flight flush (including the final one)
// completed.
func TestBatcherCloseWaitsAndFlushesFinalBatch(t *testing.T) {
	block := make(chan struct{})
	eng := &echoEngine{block: block}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:    2,
		FlushWait:   10 * time.Second,
		MaxInflight: 2,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	runDone := make(chan struct{})
	go func() { b.Run(ctx); close(runDone) }()

	// h1+h2 fill a batch and block inside the engine; h3 then sits in cur
	// (batch not full, FlushWait long) until Close flushes it as the final
	// batch. The sleep lets h3's send land before Close.
	h1ch := goSubmit(b, context.Background(), "h1")
	h2ch := goSubmit(b, context.Background(), "h2")
	waitFor(t, func() bool { return eng.callCount() == 1 }, 2*time.Second)
	h3ch := goSubmit(b, context.Background(), "h3")
	time.Sleep(50 * time.Millisecond)

	closed := make(chan struct{})
	go func() { b.Close(); close(closed) }()
	select {
	case <-closed:
		t.Fatal("Close returned while batches were still in flight")
	case <-time.After(50 * time.Millisecond):
		// Close is expected to be parked waiting for the flushes.
	}
	close(block)

	// Close unblocks only after the in-flight batch AND the final batch
	// completed, so every waiter has its result by then.
	<-closed
	if got := eng.callCount(); got != 2 {
		t.Fatalf("Pipeline calls = %d, want 2 (in-flight batch + final flush)", got)
	}
	for _, ch := range []chan submitResult{h1ch, h2ch, h3ch} {
		if r := recvSubmit(t, ch); r.err != nil {
			t.Fatalf("waiter err = %v, want its result after Close", r.err)
		}
	}
	<-runDone
}

// TestBatcherCloseTimesOut: when an in-flight batch outlives BatchDeadline,
// Close logs and gives up instead of blocking forever; the batch itself still
// finishes in the background and its waiter is served.
func TestBatcherCloseTimesOut(t *testing.T) {
	block := make(chan struct{})
	eng := &echoEngine{block: block}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:      1,
		MaxInflight:   1,
		BatchDeadline: 60 * time.Millisecond,
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go b.Run(ctx)

	h1ch := goSubmit(b, context.Background(), "h1")
	waitFor(t, func() bool { return eng.callCount() == 1 }, 2*time.Second)

	closed := make(chan struct{})
	go func() { b.Close(); close(closed) }()
	<-closed // bounded by BatchDeadline even though the call is still blocked

	if got := eng.inflightNow(); got != 1 {
		t.Fatalf("in-flight calls = %d, want 1 (Close must not cancel it)", got)
	}
	close(block)
	if r := recvSubmit(t, h1ch); r.err != nil {
		t.Fatalf("waiter err = %v, want the batch to finish after Close gave up", r.err)
	}
}

// TestBatcherErrOpenRejectedWithoutCall: an open breaker rejects the batch
// before any engine call, and every waiter receives circuit.ErrOpen.
func TestBatcherErrOpenRejectedWithoutCall(t *testing.T) {
	openBrk := circuit.New(circuit.Options{FailureThreshold: 1, Cooldown: time.Hour})
	if err := openBrk.Do(func() error { return errors.New("open the breaker") }); err == nil {
		t.Fatal("failed to open the breaker")
	}
	eng := &echoEngine{}
	b := newTestBatcher(eng, openBrk, BatcherConfig{MaxItems: 1, MaxInflight: 1})
	runBatcher(t, b)

	r := recvSubmit(t, goSubmit(b, context.Background(), "h1"))
	if !errors.Is(r.err, circuit.ErrOpen) {
		t.Fatalf("Submit err = %v, want circuit.ErrOpen", r.err)
	}
	if got := eng.callCount(); got != 0 {
		t.Errorf("Pipeline calls = %d, want 0 (rejected without issuing)", got)
	}
}

// TestBatcherMissingHashSynthesizesError: a hash absent from the batch
// results gets a synthesized error item result instead of nothing.
func TestBatcherMissingHashSynthesizesError(t *testing.T) {
	eng := &echoEngine{results: json.RawMessage(`[{"content_hash":"h1","status":"created"}]`)}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{MaxItems: 2, MaxInflight: 1})
	runBatcher(t, b)

	h1ch := goSubmit(b, context.Background(), "h1")
	h2ch := goSubmit(b, context.Background(), "h2")

	if r := recvSubmit(t, h1ch); r.err != nil || itemHash(t, r.itemRes) != "h1" {
		t.Fatalf("h1 waiter: err=%v item=%s, want its reported result", r.err, r.itemRes)
	}
	r2 := recvSubmit(t, h2ch)
	if r2.err != nil {
		t.Fatalf("h2 waiter err = %v, want a synthesized result not an error", r2.err)
	}
	var synth struct {
		ContentHash string `json:"content_hash"`
		Status      string `json:"status"`
		Error       string `json:"error"`
	}
	if err := json.Unmarshal(r2.itemRes, &synth); err != nil {
		t.Fatalf("synthesized result is not JSON: %v (%s)", err, r2.itemRes)
	}
	if synth.ContentHash != "h2" || synth.Status != "error" || synth.Error == "" {
		t.Errorf("synthesized result = %s, want an error item for h2", r2.itemRes)
	}
}

// TestBatcherFIFO: items are dispatched in arrival order and none is starved.
// h2..h8 are submitted sequentially from one goroutine, each blocking until
// its own batch flushed (FlushWait is short so a lone item still completes),
// which makes their relative dispatch order through the single collect loop
// deterministic; h1 races only against h2.
func TestBatcherFIFO(t *testing.T) {
	eng := &echoEngine{}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{
		MaxItems:    2,
		FlushWait:   25 * time.Millisecond,
		MaxInflight: 2,
	})
	runBatcher(t, b)

	const n = 8
	chs := make([]chan submitResult, n)
	hashes := make([]string, n)
	for i := 0; i < n; i++ {
		hashes[i] = "h" + string(rune('1'+i))
		chs[i] = make(chan submitResult, 1)
	}
	go func() {
		for i := 1; i < n; i++ {
			submitTo(chs[i], b, context.Background(), hashes[i])
		}
	}()
	go submitTo(chs[0], b, context.Background(), hashes[0])

	// Every waiter gets its own result back (no starvation, no duplication).
	for i, ch := range chs {
		r := recvSubmit(t, ch)
		if r.err != nil {
			t.Fatalf("waiter %s err = %v", hashes[i], r.err)
		}
		if got := itemHash(t, r.itemRes); got != hashes[i] {
			t.Fatalf("waiter %s got result for %q", hashes[i], got)
		}
	}

	// Concatenated dispatch order preserves the sequential sender's order.
	var dispatched []string
	for _, call := range eng.snapshotCalls() {
		for _, it := range call.Items {
			dispatched = append(dispatched, it.ContentHash)
		}
	}
	if len(dispatched) != n {
		t.Fatalf("dispatched %d items, want %d", len(dispatched), n)
	}
	pos := map[string]int{}
	for i, h := range dispatched {
		if _, dup := pos[h]; dup {
			t.Fatalf("item %s dispatched twice", h)
		}
		pos[h] = i
	}
	last := -1
	for i := 1; i < n; i++ { // hashes[1:] = h2..h8 in submit order
		p, ok := pos[hashes[i]]
		if !ok {
			t.Fatalf("item %s never dispatched", hashes[i])
		}
		if p <= last {
			t.Errorf("item %s dispatched at %d after a later item at %d; FIFO violated", hashes[i], p, last)
		}
		last = p
	}
}

// TestBatcherSubmitAfterClose: once Close has run, Submit fails fast instead
// of parking the waiter forever.
func TestBatcherSubmitAfterClose(t *testing.T) {
	eng := &echoEngine{}
	b := newTestBatcher(eng, newBrk(), BatcherConfig{MaxItems: 4, MaxInflight: 1})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go b.Run(ctx)
	b.Close()

	r := recvSubmit(t, goSubmit(b, context.Background(), "h1"))
	if !errors.Is(r.err, ErrBatcherClosed) {
		t.Fatalf("Submit err = %v, want ErrBatcherClosed", r.err)
	}
	if got := eng.callCount(); got != 0 {
		t.Errorf("Pipeline calls = %d, want 0", got)
	}
}
