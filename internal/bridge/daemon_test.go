package bridge

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mockWriteCloser captures writes and satisfies io.WriteCloser.
type mockWriteCloser struct {
	mu      sync.Mutex
	buf     strings.Builder
	closed  bool
	writeFn func([]byte) (int, error) // optional override
}

func (m *mockWriteCloser) Write(p []byte) (int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.closed {
		return 0, io.ErrClosedPipe
	}
	if m.writeFn != nil {
		return m.writeFn(p)
	}
	return m.buf.Write(p)
}

func (m *mockWriteCloser) Close() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.closed = true
	return nil
}

func (m *mockWriteCloser) Written() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.buf.String()
}

// newTestDaemon creates a MultiplexStreamDaemon wired to a mock stdin and
// a scanner over the provided stdout content. The daemon is set to ready state.
func newTestDaemon(stdoutContent string) (*MultiplexStreamDaemon, *mockWriteCloser) {
	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)
	_ = stdoutContent // stdout is handled separately per test
	return d, stdin
}

func TestReadLoopNonStream(t *testing.T) {
	// Prepare mock stdout with two non-streaming responses.
	lines := []string{
		`{"id":"1","ok":true,"data":{"result":"hello"}}`,
		`{"id":"2","ok":false,"error":{"code":"ERR","message":"bad"}}`,
	}
	stdoutContent := strings.Join(lines, "\n") + "\n"
	reader := strings.NewReader(stdoutContent)
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	d, stdin := newTestDaemon("")
	_ = stdin

	// Pre-register pending channels (simulating what call() does).
	ch1 := make(chan *daemonResponse, 1)
	ch2 := make(chan *daemonResponse, 1)
	d.pendingOnce.Store("1", ch1)
	d.pendingOnce.Store("2", ch2)

	// Run readLoop (it will exit when scanner reaches EOF, then drainAll).
	d.readLoop(scanner)

	// Verify responses were dispatched.
	resp1 := <-ch1
	if resp1 == nil {
		t.Fatal("expected non-nil response for id=1")
	}
	if !resp1.OK {
		t.Errorf("expected OK=true for id=1, got false")
	}
	if string(resp1.Data) != `{"result":"hello"}` {
		t.Errorf("unexpected data for id=1: %s", resp1.Data)
	}

	resp2 := <-ch2
	if resp2 == nil {
		t.Fatal("expected non-nil response for id=2")
	}
	if resp2.OK {
		t.Errorf("expected OK=false for id=2, got true")
	}
	if resp2.Error == nil || resp2.Error.Code != "ERR" {
		t.Errorf("unexpected error for id=2: %+v", resp2.Error)
	}
}

func TestReadLoopStream(t *testing.T) {
	// Prepare mock stdout with streaming responses for id=1.
	lines := []string{
		`{"id":"1","stream":true,"event":{"type":"delta","content":"Hi"}}`,
		`{"id":"1","stream":true,"event":{"type":"delta","content":" there"}}`,
		`{"id":"1","stream":true,"event":{"type":"done"},"final":true}`,
	}
	stdoutContent := strings.Join(lines, "\n") + "\n"
	reader := strings.NewReader(stdoutContent)
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	d, _ := newTestDaemon("")

	// Pre-register stream entry.
	entry := &streamEntry{
		ch: make(chan *daemonResponse, 64),
	}
	d.pendingStream.Store("1", entry)

	// Run readLoop in background.
	done := make(chan struct{})
	go func() {
		d.readLoop(scanner)
		close(done)
	}()

	// Collect events from the stream channel.
	var events []*daemonResponse
	for resp := range entry.ch {
		events = append(events, resp)
	}

	<-done

	if len(events) != 3 {
		t.Fatalf("expected 3 stream events, got %d", len(events))
	}
	if !events[2].Final {
		t.Error("expected final=true on last event")
	}

	// Verify entry was deleted from pendingStream.
	if _, ok := d.pendingStream.Load("1"); ok {
		t.Error("expected stream entry to be deleted after final")
	}
}

func TestReadLoopStreamCanceled(t *testing.T) {
	// When canceled=true, readLoop should discard non-final messages
	// and only clean up on final.
	lines := []string{
		`{"id":"1","stream":true,"event":{"type":"delta","content":"ignored"}}`,
		`{"id":"1","stream":true,"event":{"type":"done"},"final":true}`,
	}
	stdoutContent := strings.Join(lines, "\n") + "\n"
	reader := strings.NewReader(stdoutContent)
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	d, _ := newTestDaemon("")

	entry := &streamEntry{
		ch: make(chan *daemonResponse, 64),
	}
	entry.canceled.Store(true) // pre-cancel
	d.pendingStream.Store("1", entry)

	d.readLoop(scanner)

	// Channel should be closed (cleanup on final) with no messages sent.
	select {
	case _, ok := <-entry.ch:
		if ok {
			t.Error("expected channel to be closed, but received a value")
		}
	default:
		t.Error("expected channel to be closed")
	}

	if _, ok := d.pendingStream.Load("1"); ok {
		t.Error("expected stream entry to be deleted")
	}
}

func TestCallSuccess(t *testing.T) {
	// Create a pipe to simulate stdout.
	pr, pw := io.Pipe()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	// Start readLoop.
	go d.readLoop(scanner)

	// Call in a goroutine.
	ctx := context.Background()
	type result struct {
		resp *daemonResponse
		err  error
	}
	resCh := make(chan result, 1)
	go func() {
		resp, err := d.call(ctx, daemonRequest{Cmd: "ping"})
		resCh <- result{resp, err}
	}()

	// Wait for the request to be written to stdin, then respond.
	time.Sleep(50 * time.Millisecond)
	written := stdin.Written()
	var req daemonRequest
	if err := json.Unmarshal([]byte(strings.TrimSpace(written)), &req); err != nil {
		t.Fatalf("failed to parse request from stdin: %v (raw: %s)", err, written)
	}

	// Write response to stdout.
	resp := fmt.Sprintf(`{"id":"%s","ok":true,"data":{"pong":true}}`, req.ID)
	_, _ = pw.Write([]byte(resp + "\n"))

	// Get result.
	res := <-resCh
	if res.err != nil {
		t.Fatalf("call() returned error: %v", res.err)
	}
	if !res.resp.OK {
		t.Error("expected OK=true")
	}
	if string(res.resp.Data) != `{"pong":true}` {
		t.Errorf("unexpected data: %s", res.resp.Data)
	}

	// Cleanup.
	pw.Close()
}

func TestCallDrain(t *testing.T) {
	// When readLoop exits (EOF), pending calls should get nil → ErrDaemonNotReady.
	pr, pw := io.Pipe()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	go d.readLoop(scanner)

	type result struct {
		resp *daemonResponse
		err  error
	}
	resCh := make(chan result, 1)
	go func() {
		resp, err := d.call(context.Background(), daemonRequest{Cmd: "slow"})
		resCh <- result{resp, err}
	}()

	// Let the call register, then close stdout (simulates daemon crash).
	time.Sleep(50 * time.Millisecond)
	pw.Close()

	res := <-resCh
	if res.err != ErrDaemonNotReady {
		t.Fatalf("expected ErrDaemonNotReady, got: %v", res.err)
	}
}

func TestCallContextCancel(t *testing.T) {
	pr, pw := io.Pipe()
	defer pw.Close()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	go d.readLoop(scanner)

	ctx, cancel := context.WithCancel(context.Background())

	type result struct {
		resp *daemonResponse
		err  error
	}
	resCh := make(chan result, 1)
	go func() {
		resp, err := d.call(ctx, daemonRequest{Cmd: "slow"})
		resCh <- result{resp, err}
	}()

	// Let call register, then cancel context.
	time.Sleep(50 * time.Millisecond)
	cancel()

	res := <-resCh
	if res.err != context.Canceled {
		t.Fatalf("expected context.Canceled, got: %v", res.err)
	}

	// Cleanup: close pipe to end readLoop.
	pw.Close()
}

func TestStreamSuccess(t *testing.T) {
	pr, pw := io.Pipe()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	go d.readLoop(scanner)

	var events []json.RawMessage
	errCh := make(chan error, 1)
	go func() {
		err := d.stream(context.Background(), daemonRequest{Cmd: "chat"}, func(event json.RawMessage) error {
			events = append(events, event)
			return nil
		})
		errCh <- err
	}()

	// Wait for request, parse ID.
	time.Sleep(50 * time.Millisecond)
	written := stdin.Written()
	var req daemonRequest
	if err := json.Unmarshal([]byte(strings.TrimSpace(written)), &req); err != nil {
		t.Fatalf("failed to parse request: %v (raw: %s)", err, written)
	}

	// Send streaming events.
	_, _ = pw.Write([]byte(fmt.Sprintf(`{"id":"%s","stream":true,"event":{"type":"delta","content":"Hi"}}`+"\n", req.ID)))
	_, _ = pw.Write([]byte(fmt.Sprintf(`{"id":"%s","stream":true,"event":{"type":"done"},"final":true}`+"\n", req.ID)))

	err := <-errCh
	if err != nil {
		t.Fatalf("stream() returned error: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}

	pw.Close()
}

func TestDaemonStreamContextCancel(t *testing.T) {
	pr, pw := io.Pipe()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)

	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	go d.readLoop(scanner)

	ctx, cancel := context.WithCancel(context.Background())

	errCh := make(chan error, 1)
	go func() {
		err := d.stream(ctx, daemonRequest{Cmd: "chat"}, func(event json.RawMessage) error {
			return nil
		})
		errCh <- err
	}()

	// Let stream register.
	time.Sleep(50 * time.Millisecond)

	// Cancel context.
	cancel()

	err := <-errCh
	if err != context.Canceled {
		t.Fatalf("expected context.Canceled, got: %v", err)
	}

	// Verify cancel was sent to stdin.
	time.Sleep(20 * time.Millisecond)
	written := stdin.Written()
	if !strings.Contains(written, `"cmd":"cancel"`) {
		t.Errorf("expected cancel command in stdin, got: %s", written)
	}

	// Send final to allow readLoop cleanup.
	var req daemonRequest
	firstLine := strings.Split(strings.TrimSpace(written), "\n")[0]
	if err := json.Unmarshal([]byte(firstLine), &req); err == nil {
		_, _ = pw.Write([]byte(fmt.Sprintf(`{"id":"%s","stream":true,"event":{"type":"cancelled"},"final":true}`+"\n", req.ID)))
	}

	pw.Close()
}

func TestDrainAll(t *testing.T) {
	d, _ := newTestDaemon("")

	// Register a non-streaming pending.
	ch1 := make(chan *daemonResponse, 1)
	d.pendingOnce.Store("once-1", ch1)

	// Register a streaming pending.
	entry := &streamEntry{
		ch: make(chan *daemonResponse, 64),
	}
	d.pendingStream.Store("stream-1", entry)

	d.drainAll()

	// Non-streaming should receive nil.
	resp := <-ch1
	if resp != nil {
		t.Error("expected nil from drained non-streaming channel")
	}

	// Streaming channel should be closed.
	_, ok := <-entry.ch
	if ok {
		t.Error("expected streaming channel to be closed")
	}

	// Maps should be empty.
	count := 0
	d.pendingOnce.Range(func(_, _ any) bool { count++; return true })
	d.pendingStream.Range(func(_, _ any) bool { count++; return true })
	if count != 0 {
		t.Errorf("expected empty maps after drainAll, found %d entries", count)
	}

	// ready should be false.
	if d.ready.Load() {
		t.Error("expected ready=false after drainAll")
	}
}

func TestSendCancel(t *testing.T) {
	stdin := &mockWriteCloser{}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 10,
		sem:         make(chan struct{}, 10),
		done:        make(chan struct{}),
		stdin:       stdin,
	}

	d.sendCancel("target-42")

	written := stdin.Written()
	if !strings.Contains(written, `"cmd":"cancel"`) {
		t.Errorf("expected cancel cmd in output, got: %s", written)
	}
	if !strings.Contains(written, `"target_id":"target-42"`) {
		t.Errorf("expected target_id in payload, got: %s", written)
	}
}

func TestConcurrentCallsNoPanic(t *testing.T) {
	// Stress test: 100 goroutines making mixed call/stream requests for 2 seconds.
	pr, pw := io.Pipe()
	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 8<<20), 8<<20)

	stdin := &mockWriteCloser{
		writeFn: func(p []byte) (int, error) {
			return len(p), nil // discard writes
		},
	}
	d := &MultiplexStreamDaemon{
		command:     "test",
		concurrency: 100,
		sem:         make(chan struct{}, 100),
		done:        make(chan struct{}),
		stdin:       stdin,
	}
	d.ready.Store(true)

	// Responder: reads requests and sends responses.
	var responderWg sync.WaitGroup
	responderWg.Add(1)
	go func() {
		defer responderWg.Done()
		d.readLoop(scanner)
	}()

	// Track registrations to respond to them.
	// We'll write responses directly from a separate goroutine.
	var stopResponder atomic.Bool
	responderWg.Add(1)
	go func() {
		defer responderWg.Done()
		ticker := time.NewTicker(1 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			if stopResponder.Load() {
				return
			}
			// Respond to all pending once entries.
			d.pendingOnce.Range(func(key, val any) bool {
				id := key.(string)
				resp := fmt.Sprintf(`{"id":"%s","ok":true,"data":{}}`, id)
				_, _ = pw.Write([]byte(resp + "\n"))
				return true
			})
			// Respond to all pending stream entries with a final event.
			d.pendingStream.Range(func(key, val any) bool {
				id := key.(string)
				resp := fmt.Sprintf(`{"id":"%s","stream":true,"event":{"type":"done"},"final":true}`, id)
				_, _ = pw.Write([]byte(resp + "\n"))
				return true
			})
		}
	}()

	// Launch 100 goroutines doing mixed calls.
	var wg sync.WaitGroup
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				default:
				}
				if idx%2 == 0 {
					_, _ = d.call(ctx, daemonRequest{Cmd: "ping"})
				} else {
					_ = d.stream(ctx, daemonRequest{Cmd: "chat"}, func(event json.RawMessage) error {
						return nil
					})
				}
			}
		}(i)
	}

	// Wait for test duration.
	<-ctx.Done()
	wg.Wait()

	// Stop responder and close pipe.
	stopResponder.Store(true)
	pw.Close()
	responderWg.Wait()
}
