// Package circuit provides a thread-safe three-state circuit breaker used to
// stop hammering the Python AI engine's LLM endpoints when they fail
// repeatedly. After FailureThreshold consecutive failures it opens; after
// Cooldown it allows a single half-open trial before closing or re-opening.
package circuit

import (
	"errors"
	"sync"
	"time"
)

// ErrOpen is returned by Do when the breaker is open and the call is rejected
// without invoking fn.
var ErrOpen = errors.New("circuit: breaker open")

// State is the breaker's current mode.
type State int

const (
	StateClosed State = iota
	StateOpen
	StateHalfOpen
)

func (s State) String() string {
	switch s {
	case StateClosed:
		return "closed"
	case StateOpen:
		return "open"
	case StateHalfOpen:
		return "half-open"
	default:
		return "unknown"
	}
}

// Clock returns the current time; injected so tests can advance the cooldown
// without sleeping.
type Clock func() time.Time

// Options configures a Breaker.
type Options struct {
	// FailureThreshold is the consecutive-failure count that opens the breaker.
	// Defaults to 5 if <= 0.
	FailureThreshold int
	// Cooldown is how long the breaker stays open before allowing a half-open
	// trial. Defaults to 30s if <= 0.
	Cooldown time.Duration
	// Clock overrides the time source (defaults to time.Now).
	Clock Clock
}

// Breaker is a thread-safe circuit breaker shared across worker goroutines.
type Breaker struct {
	mu               sync.Mutex
	state            State
	consecFails      int
	openedAt         time.Time
	halfOpenInFlight bool
	threshold        int
	cooldown         time.Duration
	now              Clock
}

// New builds a Breaker.
func New(opts Options) *Breaker {
	if opts.FailureThreshold <= 0 {
		opts.FailureThreshold = 5
	}
	if opts.Cooldown <= 0 {
		opts.Cooldown = 30 * time.Second
	}
	if opts.Clock == nil {
		opts.Clock = time.Now
	}
	return &Breaker{
		state:     StateClosed,
		threshold: opts.FailureThreshold,
		cooldown:  opts.Cooldown,
		now:       opts.Clock,
	}
}

// Do runs fn unless the breaker rejects the call (ErrOpen). fn's own error is
// returned verbatim and recorded as a failure. fn runs outside the lock so a
// slow LLM call does not block other goroutines' state checks.
func (b *Breaker) Do(fn func() error) error {
	if err := b.beforeCall(); err != nil {
		return err
	}
	err := fn()
	b.afterCall(err)
	return err
}

func (b *Breaker) beforeCall() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch b.state {
	case StateOpen:
		if b.now().Sub(b.openedAt) < b.cooldown {
			return ErrOpen
		}
		b.state = StateHalfOpen
		b.halfOpenInFlight = true
		return nil
	case StateHalfOpen:
		if b.halfOpenInFlight {
			return ErrOpen
		}
		b.halfOpenInFlight = true
		return nil
	default: // StateClosed
		return nil
	}
}

func (b *Breaker) afterCall(err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if err != nil {
		switch b.state {
		case StateHalfOpen:
			// A failed trial re-opens immediately, regardless of count.
			b.state = StateOpen
			b.openedAt = b.now()
		case StateClosed:
			b.consecFails++
			if b.consecFails >= b.threshold {
				b.state = StateOpen
				b.openedAt = b.now()
			}
		}
		b.halfOpenInFlight = false
		return
	}
	b.consecFails = 0
	b.state = StateClosed
	b.halfOpenInFlight = false
}

// State reports the breaker's mode. When open and the cooldown has elapsed it
// reports half-open so a poller (the Dispatcher) knows it may resume.
func (b *Breaker) State() State {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.state == StateOpen && b.now().Sub(b.openedAt) >= b.cooldown {
		return StateHalfOpen
	}
	return b.state
}
