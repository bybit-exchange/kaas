package circuit

import (
	"testing"
	"time"
)

func TestStateString(t *testing.T) {
	tests := []struct {
		state State
		want  string
	}{
		{StateClosed, "closed"},
		{StateOpen, "open"},
		{StateHalfOpen, "half-open"},
		{State(99), "unknown"},
		{State(-1), "unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.want, func(t *testing.T) {
			if got := tt.state.String(); got != tt.want {
				t.Errorf("State(%d).String(): expected %q, got %q", tt.state, tt.want, got)
			}
		})
	}
}

// TestNewAppliesDefaults covers the zero-value Options path, where the breaker
// must fall back to 5 failures / 30s cooldown / time.Now.
func TestNewAppliesDefaults(t *testing.T) {
	b := New(Options{})

	if b.threshold != 5 {
		t.Errorf("expected default threshold 5, got %d", b.threshold)
	}
	if b.cooldown != 30*time.Second {
		t.Errorf("expected default cooldown 30s, got %s", b.cooldown)
	}
	if b.now == nil {
		t.Fatal("expected a default clock to be installed")
	}
	if b.State() != StateClosed {
		t.Errorf("expected a new breaker to be closed, got %s", b.State())
	}

	// The default clock must be usable, i.e. actually wired to a real time
	// source rather than left as a nil func that would panic on first use.
	if b.now().IsZero() {
		t.Error("expected the default clock to return a real time")
	}
}

// TestNewRejectsNonPositiveOptions asserts negative and zero values are both
// treated as "unset" rather than being taken literally (a zero threshold would
// otherwise open the breaker immediately).
func TestNewRejectsNonPositiveOptions(t *testing.T) {
	tests := []struct {
		name string
		opts Options
	}{
		{"zero values", Options{FailureThreshold: 0, Cooldown: 0}},
		{"negative values", Options{FailureThreshold: -3, Cooldown: -time.Second}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := New(tt.opts)
			if b.threshold != 5 {
				t.Errorf("expected threshold 5, got %d", b.threshold)
			}
			if b.cooldown != 30*time.Second {
				t.Errorf("expected cooldown 30s, got %s", b.cooldown)
			}

			// A single failure must not open a breaker with the default threshold.
			_ = b.Do(func() error { return errBoom })
			if b.State() != StateClosed {
				t.Errorf("expected the breaker to stay closed after 1 failure, got %s", b.State())
			}
		})
	}
}

// TestStateReportsHalfOpenAfterCooldown covers the State() accessor's
// cooldown-elapsed branch, which lets the dispatcher poll for recovery without
// making a call.
func TestStateReportsHalfOpenAfterCooldown(t *testing.T) {
	b, clk := newBreaker(1, time.Minute)

	_ = b.Do(func() error { return errBoom })
	if got := b.State(); got != StateOpen {
		t.Fatalf("expected open after hitting the threshold, got %s", got)
	}

	clk.advance(59 * time.Second)
	if got := b.State(); got != StateOpen {
		t.Errorf("expected still open before the cooldown elapses, got %s", got)
	}

	clk.advance(time.Second)
	if got := b.State(); got != StateHalfOpen {
		t.Errorf("expected half-open once the cooldown elapses, got %s", got)
	}
}

// TestSuccessResetsFailureCount asserts the consecutive-failure counter is
// cleared by a success, so intermittent failures never accumulate into an open
// breaker.
func TestSuccessResetsFailureCount(t *testing.T) {
	b, _ := newBreaker(3, time.Minute)

	for range 5 {
		_ = b.Do(func() error { return errBoom })
		_ = b.Do(func() error { return nil })
	}

	if got := b.State(); got != StateClosed {
		t.Errorf("expected the breaker to stay closed on alternating results, got %s", got)
	}
}
