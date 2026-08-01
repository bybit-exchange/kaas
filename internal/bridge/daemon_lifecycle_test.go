package bridge

import (
	"context"
	"encoding/json"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// requireShell skips the test if a POSIX shell is unavailable. The daemon is
// Unix-only (it relies on process groups), so this should always be present.
func requireShell(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("sh"); err != nil {
		t.Skipf("sh not available: %v", err)
	}
}

func TestNewMultiplexStreamDaemonConcurrency(t *testing.T) {
	tests := []struct {
		name            string
		concurrency     int
		wantConcurrency int
	}{
		{"zero falls back to one", 0, 1},
		{"negative falls back to one", -5, 1},
		{"explicit value is kept", 8, 8},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := NewMultiplexStreamDaemon(DaemonConfig{
				Command:     "python",
				Args:        []string{"-m", "kb_ai"},
				Concurrency: tt.concurrency,
			})

			if d.concurrency != tt.wantConcurrency {
				t.Errorf("expected concurrency %d, got %d", tt.wantConcurrency, d.concurrency)
			}
			if cap(d.sem) != tt.wantConcurrency {
				t.Errorf("expected semaphore cap %d, got %d", tt.wantConcurrency, cap(d.sem))
			}
			if d.command != "python" || len(d.args) != 2 {
				t.Errorf("command/args not stored: %q %v", d.command, d.args)
			}
			if d.Ready() {
				t.Error("expected a freshly constructed daemon to not be ready")
			}
			if d.done == nil {
				t.Error("expected the done channel to be initialised")
			}
		})
	}
}

// TestDaemonStartCommandNotFound covers the spawn failure path.
func TestDaemonStartCommandNotFound(t *testing.T) {
	d := NewMultiplexStreamDaemon(DaemonConfig{Command: "kaas-no-such-binary-xyz"})

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := d.Start(ctx)
	if err == nil {
		t.Fatal("expected Start to fail for a missing command")
	}
	if !strings.Contains(err.Error(), "failed to start process") {
		t.Errorf("unexpected error: %v", err)
	}
	if d.Ready() {
		t.Error("expected the daemon to not be ready after a failed start")
	}
}

// TestDaemonStartProcessExitsBeforeReady covers a process that dies without
// ever emitting the __READY__ marker.
func TestDaemonStartProcessExitsBeforeReady(t *testing.T) {
	requireShell(t)

	d := NewMultiplexStreamDaemon(DaemonConfig{
		Command: "sh",
		Args:    []string{"-c", "exit 3"},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := d.Start(ctx)
	if err == nil {
		t.Fatal("expected Start to fail when the process exits early")
	}
	if !strings.Contains(err.Error(), "exited before becoming ready") {
		t.Errorf("unexpected error: %v", err)
	}
	if d.Ready() {
		t.Error("expected the daemon to not be ready")
	}
}

// TestDaemonStartTimesOutWaitingForReady covers the context-deadline path: the
// process runs but never signals readiness.
func TestDaemonStartTimesOutWaitingForReady(t *testing.T) {
	requireShell(t)

	// `cat` stays alive holding stdin open but prints no __READY__ marker, and
	// exits promptly when Stop closes stdin.
	d := NewMultiplexStreamDaemon(DaemonConfig{Command: "cat"})

	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()

	err := d.Start(ctx)
	if err == nil {
		t.Fatal("expected Start to time out")
	}
	if !strings.Contains(err.Error(), "timed out waiting for __READY__") {
		t.Errorf("unexpected error: %v", err)
	}
	if d.Ready() {
		t.Error("expected the daemon to not be ready after a timeout")
	}
}

// TestDaemonStartStopRealProcess exercises the full lifecycle against a real
// child process: readiness handshake, a request/response round trip over the
// pipes, and graceful shutdown.
func TestDaemonStartStopRealProcess(t *testing.T) {
	requireShell(t)

	// Announce readiness on stderr, then echo stdin back on stdout. Echoing a
	// request verbatim yields a response whose id matches but which carries no
	// "ok" field, so the round trip surfaces as a failed daemon response.
	d := NewMultiplexStreamDaemon(DaemonConfig{
		Command:     "sh",
		Args:        []string{"-c", "echo __READY__ >&2; exec cat"},
		Concurrency: 2,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := d.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	if !d.Ready() {
		t.Fatal("expected the daemon to be ready after __READY__")
	}

	resp, err := d.call(ctx, daemonRequest{Cmd: "ping"})
	if err != nil {
		t.Fatalf("call: %v", err)
	}
	if resp.ID == "" {
		t.Error("expected the echoed response to carry the request id")
	}
	if resp.OK {
		t.Error("expected ok=false from the echoed request")
	}

	d.Stop()
	if d.Ready() {
		t.Error("expected the daemon to not be ready after Stop")
	}

	// Calls after Stop must fail fast rather than hang.
	if _, err := d.call(context.Background(), daemonRequest{Cmd: "ping"}); err == nil {
		t.Error("expected a call after Stop to fail")
	}
}

// TestDaemonRestartRealProcess asserts Restart brings the daemon back to a
// ready state with a usable done channel.
func TestDaemonRestartRealProcess(t *testing.T) {
	requireShell(t)

	d := NewMultiplexStreamDaemon(DaemonConfig{
		Command: "sh",
		Args:    []string{"-c", "echo __READY__ >&2; exec cat"},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := d.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	firstPID := d.cmd.Process.Pid

	if err := d.Restart(ctx); err != nil {
		t.Fatalf("Restart: %v", err)
	}
	defer d.Stop()

	if !d.Ready() {
		t.Error("expected the daemon to be ready after Restart")
	}
	if d.stopping.Load() {
		t.Error("expected the stopping flag to be cleared by Restart")
	}
	if d.cmd.Process.Pid == firstPID {
		t.Error("expected Restart to spawn a new process")
	}
	if _, err := d.call(ctx, daemonRequest{Cmd: "ping"}); err != nil {
		t.Errorf("expected the restarted daemon to serve calls: %v", err)
	}
}

func TestFilterEnv(t *testing.T) {
	tests := []struct {
		name    string
		env     []string
		exclude []string
		want    []string
	}{
		{
			name:    "removes the excluded key",
			env:     []string{"PATH=/bin", "VIRTUAL_ENV=/tmp/venv", "HOME=/root"},
			exclude: []string{"VIRTUAL_ENV"},
			want:    []string{"PATH=/bin", "HOME=/root"},
		},
		{
			name:    "keeps everything when nothing matches",
			env:     []string{"PATH=/bin", "HOME=/root"},
			exclude: []string{"VIRTUAL_ENV"},
			want:    []string{"PATH=/bin", "HOME=/root"},
		},
		{
			name:    "removes several keys",
			env:     []string{"A=1", "B=2", "C=3"},
			exclude: []string{"A", "C"},
			want:    []string{"B=2"},
		},
		{
			name:    "matches on the full key only, not a prefix",
			env:     []string{"VIRTUAL_ENV_PROMPT=x", "VIRTUAL_ENV=/tmp/venv"},
			exclude: []string{"VIRTUAL_ENV"},
			want:    []string{"VIRTUAL_ENV_PROMPT=x"},
		},
		{
			name:    "no exclusions is a passthrough",
			env:     []string{"A=1"},
			exclude: nil,
			want:    []string{"A=1"},
		},
		{
			name:    "empty env stays empty",
			env:     nil,
			exclude: []string{"A"},
			want:    []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := filterEnv(tt.env, tt.exclude...)
			if !equalStrings(got, tt.want) {
				t.Errorf("expected %v, got %v", tt.want, got)
			}
		})
	}
}

func TestAPIErrorError(t *testing.T) {
	err := &APIError{Code: "LLM_TIMEOUT", Message: "upstream timed out"}
	want := "bridge: AI engine error LLM_TIMEOUT: upstream timed out"
	if err.Error() != want {
		t.Errorf("expected %q, got %q", want, err.Error())
	}
}

func TestEventType(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{"delta event", `{"type":"delta","content":"hi"}`, "delta"},
		{"done event", `{"type":"done"}`, "done"},
		{"error event", `{"type":"error","message":"boom"}`, "error"},
		{"missing type", `{"content":"hi"}`, ""},
		{"non-string type", `{"type":42}`, ""},
		{"malformed json", `{not json`, ""},
		{"empty payload", ``, ""},
		{"json null", `null`, ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := EventType(json.RawMessage(tt.raw)); got != tt.want {
				t.Errorf("expected %q, got %q", tt.want, got)
			}
		})
	}
}
