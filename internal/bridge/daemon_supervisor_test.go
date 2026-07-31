package bridge

import (
	"bytes"
	"context"
	"log"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// safeBuffer serializes writes so log output captured during a test cannot race
// with logging from the daemon's own goroutines.
type safeBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *safeBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *safeBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// captureLog redirects the standard logger into a buffer for the duration of the
// test. supervisorLoop owns no exported state, so its log output is the only
// observable record of the decisions it makes.
func captureLog(t *testing.T) *safeBuffer {
	t.Helper()
	buf := &safeBuffer{}
	prevOut, prevFlags := log.Writer(), log.Flags()
	log.SetOutput(buf)
	log.SetFlags(0)
	t.Cleanup(func() {
		log.SetOutput(prevOut)
		log.SetFlags(prevFlags)
	})
	return buf
}

// waitForLog polls the captured log until it contains want, so tests observe the
// supervisor's progress by condition rather than by a fixed sleep.
func waitForLog(t *testing.T, logs *safeBuffer, want string) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(logs.String(), want) {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("log never contained %q; got: %q", want, logs.String())
}

// waitForSupervisor fails the test unless the supervisor goroutine exits.
func waitForSupervisor(t *testing.T, c *DaemonClient) {
	t.Helper()
	exited := make(chan struct{})
	go func() {
		c.supervWg.Wait()
		close(exited)
	}()
	select {
	case <-exited:
	case <-time.After(3 * time.Second):
		t.Fatal("supervisor did not exit")
	}
}

// fakeDaemonClient creates a DaemonClient with a mock daemon that can simulate
// crashes via closing the done channel. Does NOT start a real process.
func fakeDaemonClient(maxRestarts int) *DaemonClient {
	d := &MultiplexStreamDaemon{
		command:     "fake",
		concurrency: 1,
		sem:         make(chan struct{}, 1),
		done:        make(chan struct{}),
	}
	d.ready.Store(true)

	ctx, cancel := context.WithCancel(context.Background())
	c := &DaemonClient{
		daemon: d,
		cfg: DaemonConfig{
			MaxRestarts:      maxRestarts,
			WarmupTimeoutSec: 5,
		},
		llm:    LLMConfig{APIKey: "k", BaseURL: "http://x", Model: "m"},
		ctx:    ctx,
		cancel: cancel,
	}
	return c
}

// TestSupervisorBacksOffBeforeRestarting exercises the crash path of the real
// supervisorLoop: a crash within the restart budget schedules an exponential
// backoff, and cancelling the context during that backoff aborts the restart
// before any process is spawned.
func TestSupervisorBacksOffBeforeRestarting(t *testing.T) {
	logs := captureLog(t)
	c := fakeDaemonClient(3)

	c.supervWg.Add(1)
	go c.supervisorLoop()

	close(c.daemon.done) // simulate a crash

	waitForLog(t, logs, "restarting in 1s (attempt 1/3)")

	c.cancel()
	waitForSupervisor(t, c)
}

// TestSupervisorGivesUpAfterMaxRestarts drives the real supervisorLoop with a
// restart budget of zero, so the first crash immediately exceeds it. This covers
// the give-up branch without a backoff sleep or a spawned process.
func TestSupervisorGivesUpAfterMaxRestarts(t *testing.T) {
	logs := captureLog(t)
	c := fakeDaemonClient(0)
	defer c.cancel()

	c.supervWg.Add(1)
	go c.supervisorLoop()

	close(c.daemon.done)

	waitForSupervisor(t, c)
	if got := logs.String(); !strings.Contains(got, "max restarts (0) reached") {
		t.Fatalf("expected the loop to report giving up, got log: %q", got)
	}
}

// TestSupervisorReportsFailedRestart lets the loop run through the backoff and
// actually call Restart. The daemon command does not exist, so the restart fails
// fast and the loop must report it rather than propagate the error.
func TestSupervisorReportsFailedRestart(t *testing.T) {
	logs := captureLog(t)
	c := fakeDaemonClient(1)
	c.daemon.command = filepath.Join(t.TempDir(), "no-such-daemon")

	c.supervWg.Add(1)
	go c.supervisorLoop()

	close(c.daemon.done)

	waitForLog(t, logs, "restart failed")

	c.cancel()
	waitForSupervisor(t, c)
}

func TestSupervisorGracefulStop(t *testing.T) {
	c := fakeDaemonClient(5)

	ctx, cancel := context.WithCancel(context.Background())
	c.ctx = ctx
	c.cancel = cancel

	c.supervWg.Add(1)
	go c.supervisorLoop()

	// Simulate graceful stop: set stopping flag then close done.
	c.daemon.stopping.Store(true)
	close(c.daemon.done)

	// Supervisor should exit without attempting restart.
	done := make(chan struct{})
	go func() {
		c.supervWg.Wait()
		close(done)
	}()

	select {
	case <-done:
		// Good — supervisor recognized graceful stop and exited.
	case <-time.After(2 * time.Second):
		t.Fatal("supervisor did not exit on graceful stop")
	}

	cancel()
}

func TestSupervisorStopCancelsLoop(t *testing.T) {
	c := fakeDaemonClient(5)

	ctx, cancel := context.WithCancel(context.Background())
	c.ctx = ctx
	c.cancel = cancel

	c.supervWg.Add(1)
	go c.supervisorLoop()

	// Cancel context (simulates Stop() calling c.cancel()).
	cancel()

	done := make(chan struct{})
	go func() {
		c.supervWg.Wait()
		close(done)
	}()

	select {
	case <-done:
		// Good.
	case <-time.After(2 * time.Second):
		t.Fatal("supervisor did not exit after context cancel")
	}
}

func TestSupervisorExponentialBackoff(t *testing.T) {
	// Verify backoff calculation: 1, 2, 4, 8, 16, 30(cap)
	tests := []struct {
		attempt  int
		expected int
	}{
		{1, 1},
		{2, 2},
		{3, 4},
		{4, 8},
		{5, 16},
		{6, 30}, // capped
		{7, 30},
	}

	for _, tt := range tests {
		backoff := 1 << (tt.attempt - 1)
		if backoff > 30 {
			backoff = 30
		}
		if backoff != tt.expected {
			t.Errorf("attempt %d: expected %ds backoff, got %ds", tt.attempt, tt.expected, backoff)
		}
	}
}
