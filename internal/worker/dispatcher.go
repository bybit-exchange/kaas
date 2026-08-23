package worker

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/store"
)

// Claimer is the subset of *queue.Queue the dispatcher needs.
type Claimer interface {
	Claim(ctx context.Context, owner string) (*store.Task, error)
	RecoverExpired(ctx context.Context) (int, error)
}

// Dispatcher polls the queue, recovers expired leases, and dispatches claimed
// tasks to worker goroutines under a concurrency cap. It pauses claiming while
// the circuit breaker is open.
type Dispatcher struct {
	q       Claimer
	w       *Worker
	brk     *circuit.Breaker
	owner   string
	poll    time.Duration
	maxConc int
}

// NewDispatcher builds a Dispatcher. maxConc<1 is clamped to 1; poll<=0 to 1s.
func NewDispatcher(q Claimer, w *Worker, brk *circuit.Breaker, owner string, poll time.Duration, maxConc int) *Dispatcher {
	if maxConc < 1 {
		maxConc = 1
	}
	if poll <= 0 {
		poll = time.Second
	}
	return &Dispatcher{q: q, w: w, brk: brk, owner: owner, poll: poll, maxConc: maxConc}
}

// Run blocks until ctx is cancelled, then drains in-flight tasks and returns nil.
func (d *Dispatcher) Run(ctx context.Context) error {
	sem := make(chan struct{}, d.maxConc)
	var wg sync.WaitGroup
	ticker := time.NewTicker(d.poll)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			wg.Wait()
			return nil
		case <-ticker.C:
			if n, err := d.q.RecoverExpired(ctx); err != nil {
				log.Printf("worker: recover expired: %v", err)
			} else if n > 0 {
				log.Printf("worker: recovered %d expired task(s)", n)
			}
			// Scale the batch to what the breaker will actually admit. Fully
			// open (still cooling down) it admits nothing. Once the cooldown
			// elapses State() reports half-open, where it admits exactly one
			// trial call: claiming a whole semaphore's worth there means one
			// task becomes the recovery probe and every other comes straight
			// back with ErrOpen, so we hand out a single task per tick instead.
			switch d.brk.State() {
			case circuit.StateOpen:
				continue
			case circuit.StateHalfOpen:
				d.drain(ctx, sem, &wg, 1)
			default:
				d.drain(ctx, sem, &wg, d.maxConc)
			}
		}
	}
}

// drain claims and dispatches up to limit tasks, stopping early when the queue
// is empty or no slot is free.
func (d *Dispatcher) drain(ctx context.Context, sem chan struct{}, wg *sync.WaitGroup, limit int) {
	for i := 0; i < limit; i++ {
		select {
		case sem <- struct{}{}: // acquire a slot
		default:
			return // at capacity
		}
		task, err := d.q.Claim(ctx, d.owner)
		if err != nil {
			<-sem
			log.Printf("worker: claim: %v", err)
			return
		}
		if task == nil {
			<-sem
			return // queue empty
		}
		wg.Add(1)
		go func(t *store.Task) {
			defer wg.Done()
			defer func() { <-sem }()
			// Process with a fresh context, not the dispatcher's: on shutdown we
			// let in-flight tasks finish (preserving their in-progress paid LLM
			// work) rather than aborting them. Lost-lease abort still works — it
			// is driven by the heartbeat cancelling Process's own child context.
			d.w.Process(context.Background(), t)
		}(task)
	}
}
