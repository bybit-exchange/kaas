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

// fakeIndexer records Index calls and can be told to fail the next N calls.
type fakeIndexer struct {
	mu    sync.Mutex
	calls []bridge.IndexRequest
	fail  int
}

func (f *fakeIndexer) Index(ctx context.Context, req bridge.IndexRequest) (json.RawMessage, error) {
	f.mu.Lock()
	f.calls = append(f.calls, req)
	fail := f.fail > 0
	if fail {
		f.fail--
	}
	f.mu.Unlock()
	if fail {
		return nil, errors.New("index engine down")
	}
	return json.RawMessage(`{"indexed":0}`), nil
}

func (f *fakeIndexer) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

func (f *fakeIndexer) requests() []bridge.IndexRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]bridge.IndexRequest(nil), f.calls...)
}

func (f *fakeIndexer) failNext(n int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.fail = n
}

// newTestRefresher builds a refresher with a millisecond-scale startup
// backoff so failure-path tests do not sleep through the production 1s base.
func newTestRefresher(eng Indexer, brk *circuit.Breaker, debounce, maxStale time.Duration) *IndexRefresher {
	r := NewIndexRefresher(eng, brk, "/kb", debounce, maxStale)
	r.startupBackoff = time.Millisecond
	return r
}

// runRefresher starts Run under a cancellable context and stops it on cleanup.
func runRefresher(t *testing.T, r *IndexRefresher) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Errorf("index refresher Run did not exit within 5s")
		}
	})
	go func() { r.Run(ctx); close(done) }()
}

// TestIndexerStartupRebuildRunsExactlyOnce: a healthy engine gets exactly one
// index call at startup (carrying the KB dir) and nothing more while the
// system stays quiet.
func TestIndexerStartupRebuildRunsExactlyOnce(t *testing.T) {
	eng := &fakeIndexer{}
	r := newTestRefresher(eng, newBrk(), 50*time.Millisecond, 5*time.Second)
	runRefresher(t, r)

	waitFor(t, func() bool { return eng.count() == 1 }, 2*time.Second)
	time.Sleep(150 * time.Millisecond)
	if got := eng.count(); got != 1 {
		t.Errorf("Index calls = %d after a quiet period, want 1 (startup only)", got)
	}
	if reqs := eng.requests(); len(reqs) != 1 || reqs[0].KBDir != "/kb" {
		t.Errorf("startup request = %+v, want one Index call with KBDir /kb", reqs)
	}
}

// TestIndexerDebounceCoalescesBurst: three MarkDirty calls inside one
// debounce window produce exactly one Index call.
func TestIndexerDebounceCoalescesBurst(t *testing.T) {
	eng := &fakeIndexer{}
	r := newTestRefresher(eng, newBrk(), 80*time.Millisecond, 5*time.Second)
	runRefresher(t, r)
	waitFor(t, func() bool { return eng.count() == 1 }, 2*time.Second) // startup rebuild

	r.MarkDirty()
	r.MarkDirty()
	r.MarkDirty()

	waitFor(t, func() bool { return eng.count() == 2 }, 2*time.Second) // the one coalesced refresh
	time.Sleep(200 * time.Millisecond)
	if got := eng.count(); got != 2 {
		t.Errorf("Index calls = %d, want 2 (startup + one coalesced refresh)", got)
	}
}

// TestIndexerForcedRefreshBoundsStaleness: MarkDirty arriving faster than the
// debounce would keep the timer re-armed forever; the maxStale bound forces a
// refresh anyway, and the epoch reset on success keeps the forced refreshes
// sparse instead of firing on every mark.
func TestIndexerForcedRefreshBoundsStaleness(t *testing.T) {
	eng := &fakeIndexer{}
	deb, stale := 200*time.Millisecond, 400*time.Millisecond
	r := newTestRefresher(eng, newBrk(), deb, stale)
	runRefresher(t, r)
	waitFor(t, func() bool { return eng.count() == 1 }, 2*time.Second)

	// Continuous marking: gaps stay well under the debounce, so only the
	// maxStale throttle can fire a refresh mid-window.
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		r.MarkDirty()
		time.Sleep(10 * time.Millisecond)
	}

	// The marking window alone must have produced a forced refresh; under a
	// pure trailing debounce the count would still be 1 here.
	if got := eng.count(); got < 2 {
		t.Fatalf("Index calls = %d during continuous marking, want >= 2 (maxStale must force a refresh)", got)
	}
	// Let the trailing dirty state settle: a missing epoch reset would have
	// refreshed on nearly every mark (dozens of calls), while the correct
	// behaviour settles at a handful.
	time.Sleep(deb + 2*stale)
	if got := eng.count(); got > 6 {
		t.Errorf("Index calls = %d, want <= 6 (a successful forced refresh must reset the staleness epoch)", got)
	}
}

// TestIndexerStartupFailureStaysDirtyAndRetries: when every startup attempt
// fails, the refresher stays dirty and the Run loop retries on the debounce
// cadence until a call succeeds — then it stops.
func TestIndexerStartupFailureStaysDirtyAndRetries(t *testing.T) {
	eng := &fakeIndexer{}
	brk := circuit.New(circuit.Options{FailureThreshold: 1000, Cooldown: time.Millisecond})
	r := newTestRefresher(eng, brk, 30*time.Millisecond, 5*time.Second)
	eng.failNext(8) // 6 startup attempts + 2 debounce-cadence retries
	runRefresher(t, r)

	// All 6 startup attempts (initial + 5 backoff retries) fail...
	waitFor(t, func() bool { return eng.count() >= 6 }, 2*time.Second)
	// ...then the debounce cadence keeps retrying until success.
	waitFor(t, func() bool { return eng.count() == 9 }, 4*time.Second)
	time.Sleep(150 * time.Millisecond)
	if got := eng.count(); got != 9 {
		t.Errorf("Index calls = %d, want 9 (6 startup + 2 failed retries + 1 success) then quiet", got)
	}
}

// TestIndexerFailedRefreshRetriggeredByMarkDirty: after a failed refresh the
// dirty state is kept, and a later MarkDirty still leads to a successful
// refresh — the pipeline completion is not lost to the failure.
func TestIndexerFailedRefreshRetriggeredByMarkDirty(t *testing.T) {
	eng := &fakeIndexer{}
	r := newTestRefresher(eng, newBrk(), 60*time.Millisecond, 5*time.Second)
	runRefresher(t, r)
	waitFor(t, func() bool { return eng.count() == 1 }, 2*time.Second)

	eng.failNext(1)
	r.MarkDirty() // refresh attempt fails; the state stays dirty
	waitFor(t, func() bool { return eng.count() == 2 }, 2*time.Second)

	r.MarkDirty() // retrigger with a healthy engine
	waitFor(t, func() bool { return eng.count() == 3 }, 2*time.Second)
	time.Sleep(150 * time.Millisecond)
	if got := eng.count(); got != 3 {
		t.Errorf("Index calls = %d, want 3 (startup + failed + successful retry) then quiet", got)
	}
}
