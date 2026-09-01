package worker

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"sync"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
)

// ErrBatcherClosed is returned by Submit when the batcher has stopped
// collecting items (shutdown); the item was not submitted.
var ErrBatcherClosed = errors.New("batcher: shut down before the item was submitted")

// BatcherConfig tunes a PipelineBatcher.
type BatcherConfig struct {
	// MaxItems is the flush threshold: a batch is dispatched as soon as it
	// holds this many items. 1 disables batching (one call per item).
	MaxItems int
	// FlushWait is the maximum age of the oldest pending item before the
	// batch flushes even if not full. <=0 means size-only flushing.
	FlushWait time.Duration
	// MaxInflight bounds concurrent in-flight batch calls; collection pauses
	// (and Submit back-pressures) while all slots are busy.
	MaxInflight int
	// BatchDeadline is the per-batch upper bound, wired to
	// PipelineRequest.DeadlineSeconds so a wedged daemon call cannot hold a
	// whole batch's dispatcher slots forever. It also bounds the shutdown
	// wait for in-flight flushes. <=0 = unset.
	BatchDeadline time.Duration
}

// batchOutcome is what a flush goroutine delivers to each waiter.
type batchOutcome struct {
	itemResult json.RawMessage
	batchCost  json.RawMessage
	err        error
}

// batchWaiter pairs a submitted item with its private reply channel.
type batchWaiter struct {
	item  bridge.PipelineItem
	waitc chan batchOutcome // buffered 1: delivery never blocks the flush
}

// PipelineBatcher fans per-task pipeline items into batched Pipeline calls,
// so documents distilled in the same window share grouped write LLM calls.
// Each task keeps its own lease/heartbeat/Ack lifecycle: the worker only
// swaps its direct eng.Pipeline call for Submit and blocks until the batch
// containing its item completes.
type PipelineBatcher struct {
	eng  Engine
	brk  *circuit.Breaker
	cfg  BatcherConfig
	base func() bridge.PipelineRequest // fills the per-call common fields

	submitc   chan *batchWaiter
	closed    chan struct{} // closed by Close: stop collecting
	closeOnce sync.Once
	runDone   chan struct{} // closed when Run (incl. its drain) returned

	inflightSem chan struct{} // MaxInflight slots
	inflightWG  sync.WaitGroup
}

// NewPipelineBatcher builds a PipelineBatcher. base supplies a fresh template
// request per batch call (KBDir/Model/Workers and future common fields), so
// the batcher stays independent of the config package. Call Run once to start
// collecting; Close to drain and stop.
func NewPipelineBatcher(eng Engine, brk *circuit.Breaker, cfg BatcherConfig, base func() bridge.PipelineRequest) *PipelineBatcher {
	if cfg.MaxItems < 1 {
		cfg.MaxItems = 1
	}
	if cfg.MaxInflight < 1 {
		cfg.MaxInflight = 1
	}
	return &PipelineBatcher{
		eng:         eng,
		brk:         brk,
		cfg:         cfg,
		base:        base,
		submitc:     make(chan *batchWaiter),
		closed:      make(chan struct{}),
		runDone:     make(chan struct{}),
		inflightSem: make(chan struct{}, cfg.MaxInflight),
	}
}

// Submit blocks until the batch containing this item completes. It returns
// the item's own result blob, the batch-wide cost blob, or a call-level error
// (circuit.ErrOpen when the breaker rejected the call without issuing it).
// Cancelling ctx abandons this waiter only: batches run on a detached
// context.Background() and always run to completion.
func (b *PipelineBatcher) Submit(ctx context.Context, item bridge.PipelineItem) (json.RawMessage, json.RawMessage, error) {
	w := &batchWaiter{item: item, waitc: make(chan batchOutcome, 1)}
	select {
	case b.submitc <- w:
	case <-b.closed:
		return nil, nil, ErrBatcherClosed
	case <-b.runDone:
		return nil, nil, ErrBatcherClosed
	case <-ctx.Done():
		return nil, nil, ctx.Err()
	}
	select {
	case out := <-w.waitc:
		return out.itemResult, out.batchCost, out.err
	case <-ctx.Done():
		// Lease lost mid-batch: abandon this waiter. The batch is unaffected —
		// the other items still need it — and the outcome lands in the
		// buffered waitc for the garbage collector.
		return nil, nil, ctx.Err()
	}
}

// Run is the collect loop: gathers submitted items and dispatches a flush
// when the batch is full (MaxItems) or its oldest item reaches FlushWait.
// In-flight flushes cap at MaxInflight; while all slots are busy collection
// pauses, so Submit back-pressures instead of unbounding the engine.
// It returns when ctx is cancelled or Close is called, after flushing the
// leftover batch and waiting (bounded by BatchDeadline) for in-flight flushes.
func (b *PipelineBatcher) Run(ctx context.Context) error {
	defer close(b.runDone)

	var cur []*batchWaiter
	var flushTimer *time.Timer
	var flushC <-chan time.Time
	disarm := func() {
		if flushTimer != nil {
			flushTimer.Stop()
			flushTimer = nil
			flushC = nil
		}
	}
	defer disarm()

	for {
		select {
		case <-ctx.Done():
			disarm()
			b.drain(cur)
			return nil
		case <-b.closed:
			disarm()
			b.drain(cur)
			return nil
		case w := <-b.submitc:
			if len(cur) == 0 && b.cfg.FlushWait > 0 {
				// Deadline is anchored to the oldest item; it never moves
				// while items accumulate behind it.
				flushTimer = time.NewTimer(b.cfg.FlushWait)
				flushC = flushTimer.C
			}
			cur = append(cur, w)
			if len(cur) >= b.cfg.MaxItems {
				disarm()
				cur = b.launchFlush(cur)
			}
		case <-flushC:
			disarm()
			cur = b.launchFlush(cur)
		}
	}
}

// Close stops collecting, flushes the leftover batch as a final batch, then
// waits for ALL in-flight flush goroutines, bounded by BatchDeadline. On
// timeout it logs and gives up; tasks whose waiters never woke are re-queued
// by RecoverExpired after the lease TTL (at-least-once).
func (b *PipelineBatcher) Close() {
	b.closeOnce.Do(func() { close(b.closed) })
	if b.cfg.BatchDeadline <= 0 {
		<-b.runDone
		return
	}
	select {
	case <-b.runDone:
	case <-time.After(b.cfg.BatchDeadline):
		log.Printf("worker: batcher: close timed out after %v waiting for the collect loop; giving up",
			b.cfg.BatchDeadline)
	}
}

// drain implements the shutdown half of Run: flush cur, then wait for every
// in-flight flush, bounded by BatchDeadline.
func (b *PipelineBatcher) drain(cur []*batchWaiter) {
	if len(cur) > 0 {
		b.launchFlush(cur)
	}
	done := make(chan struct{})
	go func() {
		b.inflightWG.Wait()
		close(done)
	}()
	if b.cfg.BatchDeadline <= 0 {
		<-done
		return
	}
	select {
	case <-done:
	case <-time.After(b.cfg.BatchDeadline):
		log.Printf("worker: batcher: timed out after %v waiting for in-flight batch flushes; giving up "+
			"(abandoned tasks are re-queued by RecoverExpired)", b.cfg.BatchDeadline)
	}
}

// launchFlush blocks until an inflight slot is free (pausing collection,
// FIFO, no starvation), then spawns the flush goroutine for ws.
func (b *PipelineBatcher) launchFlush(ws []*batchWaiter) []*batchWaiter {
	b.inflightSem <- struct{}{}
	b.inflightWG.Add(1)
	go func() {
		defer b.inflightWG.Done()
		defer func() { <-b.inflightSem }()
		b.flush(ws)
	}()
	return nil
}

// flush issues one batched Pipeline call and splits its results back to the
// waiters by content_hash.
func (b *PipelineBatcher) flush(ws []*batchWaiter) {
	items := make([]bridge.PipelineItem, len(ws))
	for i, w := range ws {
		items[i] = w.item
	}
	req := b.base()
	req.Items = items
	if b.cfg.BatchDeadline > 0 {
		req.DeadlineSeconds = int(b.cfg.BatchDeadline / time.Second)
	}

	// Detached context on purpose: daemon.call returns ctx.Err() the moment a
	// context is cancelled, so reusing a waiter's or the app's ctx would turn
	// every restart/shutdown into a Nack that burns task attempts. Batch
	// calls always run to completion; the deadline bounds a wedged daemon.
	// The breaker wrap counts a call-level failure once per batch, not once
	// per waiter.
	var resp *bridge.PipelineResponse
	err := b.brk.Do(func() error {
		var e error
		resp, e = b.eng.Pipeline(context.Background(), req)
		return e
	})
	if err != nil {
		out := batchOutcome{err: err}
		for _, w := range ws {
			w.waitc <- out
		}
		return
	}

	byHash := resultsByHash(resp.Results)
	for _, w := range ws {
		res, ok := byHash[w.item.ContentHash]
		if !ok {
			// Defensive: the engine reports every item back, so a missing
			// hash is a contract violation. Synthesize an error item result
			// so the task still Acks with a visible failure.
			log.Printf("worker: batcher: content_hash %q missing from batch results; synthesizing error item result",
				w.item.ContentHash)
			res = missingItemResult(w.item.ContentHash)
		}
		w.waitc <- batchOutcome{itemResult: res, batchCost: resp.Cost}
	}
}

// resultsByHash indexes a per-item results array by content_hash. First
// occurrence wins; elements without a usable hash are skipped.
func resultsByHash(results json.RawMessage) map[string]json.RawMessage {
	m := map[string]json.RawMessage{}
	var arr []json.RawMessage
	if err := json.Unmarshal(results, &arr); err != nil {
		return m
	}
	for _, el := range arr {
		var h struct {
			ContentHash string `json:"content_hash"`
		}
		if err := json.Unmarshal(el, &h); err != nil || h.ContentHash == "" {
			continue
		}
		if _, dup := m[h.ContentHash]; !dup {
			m[h.ContentHash] = el
		}
	}
	return m
}

// missingItemResult builds the synthesized error item result for a hash the
// batch response did not report. Marshal of a map[string]string cannot fail,
// so the error return is ignored.
func missingItemResult(hash string) json.RawMessage {
	b, _ := json.Marshal(map[string]string{
		"content_hash": hash,
		"status":       "error",
		"error":        "missing from batch results",
	})
	return b
}
