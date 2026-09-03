package worker

import (
	"context"
	"encoding/json"
	"log"
	"sync"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
)

// Indexer is the subset of the bridge client the index refresher needs.
// *bridge.DaemonClient satisfies it; tests inject a fake.
type Indexer interface {
	Index(ctx context.Context, req bridge.IndexRequest) (json.RawMessage, error)
}

// Compile-time assertion that the real client satisfies Indexer.
var _ Indexer = (*bridge.DaemonClient)(nil)

// startupRetries is how often the startup rebuild is retried with a doubling
// backoff starting at startupBackoff (1s/2s/4s/8s/16s), covering the window
// where the daemon process is still warming up.
const startupRetries = 5

// IndexRefresher rebuilds the KB indexes after pipeline writes, debounced and
// throttle-bounded: bursts of MarkDirty coalesce into one refresh one
// debounce later, while a dirty state older than maxStale forces a refresh
// even while MarkDirty keeps re-arming the timer, so staleness stays bounded
// under continuous load.
type IndexRefresher struct {
	eng      Indexer
	brk      *circuit.Breaker
	req      bridge.IndexRequest
	debounce time.Duration
	maxStale time.Duration

	// startupBackoff is the base of the startup retry backoff; overridable so
	// failure-path tests do not sleep through the production 1s base.
	startupBackoff time.Duration

	// dirtyc coalesces MarkDirty calls: its single buffered slot holds one
	// pending signal for an entire burst.
	dirtyc chan struct{}

	// firstDirty is when the current dirty state began (zero = clean). Set by
	// MarkDirty, cleared only after a successful refresh.
	mu         sync.Mutex
	firstDirty time.Time

	// Timer state is owned by the Run goroutine.
	timer  *time.Timer
	timerC <-chan time.Time
}

// NewIndexRefresher builds an IndexRefresher. kbDir is forwarded as the
// IndexRequest's KBDir. A non-positive maxStale auto-sizes to 5x the debounce
// (matching index_max_stale_sec's default); the log line reports the
// post-clamp values so callers need not re-derive them.
func NewIndexRefresher(eng Indexer, brk *circuit.Breaker, kbDir string, debounce, maxStale time.Duration) *IndexRefresher {
	if maxStale <= 0 {
		maxStale = 5 * debounce
	}
	log.Printf("worker: debounced index refresh enabled: debounce %v, max stale %v", debounce, maxStale)
	return &IndexRefresher{
		eng:            eng,
		brk:            brk,
		req:            bridge.IndexRequest{KBDir: kbDir},
		debounce:       debounce,
		maxStale:       maxStale,
		startupBackoff: time.Second,
		dirtyc:         make(chan struct{}, 1),
	}
}

// MarkDirty records that pipeline writes have landed and an index refresh is
// due. It never blocks: the 1-slot buffer holds one pending signal for an
// entire burst, and Run re-arms the debounce timer every time it drains one.
func (r *IndexRefresher) MarkDirty() {
	r.markFirstDirty()
	select {
	case r.dirtyc <- struct{}{}:
	default:
	}
}

// markFirstDirty records the start of the dirty epoch if none is running.
func (r *IndexRefresher) markFirstDirty() {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.firstDirty.IsZero() {
		r.firstDirty = time.Now()
	}
}

// firstDirtyTime returns the current epoch start (zero = clean).
func (r *IndexRefresher) firstDirtyTime() time.Time {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.firstDirty
}

// Run performs the startup rebuild, then serves the debounce/throttle loop
// until ctx is cancelled. A failed refresh keeps the dirty state and retries
// on the debounce cadence, so the loop never spins and a quiet restart (no
// MarkDirty ever arriving) still self-heals the indexes.
func (r *IndexRefresher) Run(ctx context.Context) error {
	if !r.startupRebuild(ctx) {
		// Final startup failure: stay dirty and let the loop retry the
		// rebuild on the debounce cadence.
		r.markFirstDirty()
		r.armTimer(r.debounce)
	}
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-r.dirtyc:
			first := r.firstDirtyTime()
			if first.IsZero() {
				// This signal's MarkDirty raced a successful refresh that
				// cleared the epoch afterwards; the writes happened at or
				// before now, so now is a safe epoch start.
				r.markFirstDirty()
				first = r.firstDirtyTime()
			}
			if time.Since(first) >= r.maxStale {
				// Throttle: continuous MarkDirty keeps re-arming the debounce
				// timer; once the dirty age reaches maxStale a forced
				// refresh bounds staleness.
				r.disarmTimer()
				r.refresh(ctx)
			} else {
				r.armTimer(r.debounce)
			}
		case <-r.timerC:
			r.timerC = nil
			r.refresh(ctx)
		}
	}
}

// startupRebuild runs one index rebuild at startup, retried with a doubling
// backoff so a daemon that is still warming up does not leave the indexes
// stale forever. It reports success; on final failure the refresher stays
// dirty and Run retries on the debounce cadence.
func (r *IndexRefresher) startupRebuild(ctx context.Context) bool {
	backoff := r.startupBackoff
	for attempt := 0; ; attempt++ {
		err := r.brk.Do(func() error {
			var e error
			_, e = r.eng.Index(ctx, r.req)
			return e
		})
		if err == nil {
			if attempt > 0 {
				log.Printf("worker: startup index rebuild succeeded on attempt %d", attempt+1)
			}
			return true
		}
		if ctx.Err() != nil || attempt >= startupRetries {
			log.Printf("worker: startup index rebuild failed after %d attempts; staying dirty and retrying every %v: %v",
				attempt+1, r.debounce, err)
			return false
		}
		select {
		case <-ctx.Done():
			return false
		case <-time.After(backoff):
		}
		backoff *= 2
	}
}

// refresh issues one breaker-wrapped Index call. Success clears the dirty
// epoch; failure keeps it and re-arms the retry timer one debounce later, so
// failed refreshes never spin.
func (r *IndexRefresher) refresh(ctx context.Context) {
	err := r.brk.Do(func() error {
		var e error
		_, e = r.eng.Index(ctx, r.req)
		return e
	})
	if err == nil {
		r.mu.Lock()
		r.firstDirty = time.Time{}
		r.mu.Unlock()
		log.Printf("worker: index refreshed")
		return
	}
	if ctx.Err() != nil {
		return // shutting down; keep the dirty state for the next Run
	}
	log.Printf("worker: index refresh failed, staying dirty and retrying in %v: %v", r.debounce, err)
	r.armTimer(r.debounce)
}

// armTimer (re)arms the debounce timer for d. Only the Run goroutine may call
// it, so the stale-value drain cannot race another receiver.
func (r *IndexRefresher) armTimer(d time.Duration) {
	if r.timer == nil {
		r.timer = time.NewTimer(d)
	} else {
		if !r.timer.Stop() {
			select {
			case <-r.timer.C:
			default:
			}
		}
		r.timer.Reset(d)
	}
	r.timerC = r.timer.C
}

// disarmTimer stops the debounce timer. Only the Run goroutine may call it.
func (r *IndexRefresher) disarmTimer() {
	if r.timer == nil {
		return
	}
	if !r.timer.Stop() {
		select {
		case <-r.timer.C:
		default:
		}
	}
	r.timerC = nil
}
