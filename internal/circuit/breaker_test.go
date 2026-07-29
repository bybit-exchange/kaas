package circuit

import (
	"errors"
	"sync"
	"testing"
	"time"
)

type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}
func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

var errBoom = errors.New("boom")

func newBreaker(threshold int, cooldown time.Duration) (*Breaker, *fakeClock) {
	clk := &fakeClock{t: time.Unix(1000, 0)}
	b := New(Options{FailureThreshold: threshold, Cooldown: cooldown, Clock: clk.now})
	return b, clk
}

func TestClosedRunsFn(t *testing.T) {
	b, _ := newBreaker(3, time.Second)
	ran := false
	err := b.Do(func() error { ran = true; return nil })
	if err != nil || !ran {
		t.Fatalf("want ran with nil err, got ran=%v err=%v", ran, err)
	}
	if b.State() != StateClosed {
		t.Fatalf("want Closed, got %v", b.State())
	}
}

func TestOpensAfterThreshold(t *testing.T) {
	b, _ := newBreaker(3, time.Second)
	for i := 0; i < 3; i++ {
		_ = b.Do(func() error { return errBoom })
	}
	if b.State() != StateOpen {
		t.Fatalf("want Open after 3 fails, got %v", b.State())
	}
	err := b.Do(func() error { t.Fatal("fn must not run while Open"); return nil })
	if !errors.Is(err, ErrOpen) {
		t.Fatalf("want ErrOpen, got %v", err)
	}
}

func TestHalfOpenAfterCooldownSuccessCloses(t *testing.T) {
	b, clk := newBreaker(2, 10*time.Second)
	_ = b.Do(func() error { return errBoom })
	_ = b.Do(func() error { return errBoom })
	clk.advance(10 * time.Second)
	if b.State() != StateHalfOpen {
		t.Fatalf("want HalfOpen after cooldown, got %v", b.State())
	}
	ran := false
	if err := b.Do(func() error { ran = true; return nil }); err != nil || !ran {
		t.Fatalf("half-open trial should run: ran=%v err=%v", ran, err)
	}
	if b.State() != StateClosed {
		t.Fatalf("want Closed after successful trial, got %v", b.State())
	}
}

func TestHalfOpenFailureReopens(t *testing.T) {
	b, clk := newBreaker(2, 10*time.Second)
	_ = b.Do(func() error { return errBoom })
	_ = b.Do(func() error { return errBoom })
	clk.advance(10 * time.Second)
	if err := b.Do(func() error { return errBoom }); !errors.Is(err, errBoom) {
		t.Fatalf("trial should run and return its error, got %v", err)
	}
	if b.State() != StateOpen {
		t.Fatalf("want Open after failed trial, got %v", b.State())
	}
	// openedAt reset → immediate retry blocked again
	if err := b.Do(func() error { return nil }); !errors.Is(err, ErrOpen) {
		t.Fatalf("want ErrOpen right after reopen, got %v", err)
	}
}

func TestHalfOpenSingleTrial(t *testing.T) {
	b, clk := newBreaker(1, 10*time.Second)
	_ = b.Do(func() error { return errBoom }) // open
	clk.advance(10 * time.Second)

	started := make(chan struct{})
	release := make(chan struct{})
	go func() {
		_ = b.Do(func() error {
			close(started)
			<-release
			return nil
		})
	}()
	<-started // trial in flight
	if err := b.Do(func() error { t.Fatal("second trial must not run"); return nil }); !errors.Is(err, ErrOpen) {
		t.Fatalf("want ErrOpen for concurrent second trial, got %v", err)
	}
	close(release)
}

func TestConcurrentDoRace(t *testing.T) {
	b, _ := newBreaker(5, time.Millisecond)
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_ = b.Do(func() error {
				if i%2 == 0 {
					return errBoom
				}
				return nil
			})
		}(i)
	}
	wg.Wait()
	_ = b.State()
}
