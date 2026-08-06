package bridge

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// initEchoScript answers every request with a success response carrying the
// request's own id, which is the minimum a process must do to get through
// NewDaemonClient's init handshake.
const initEchoScript = `echo __READY__ >&2
while IFS= read -r line; do
  id=$(printf '%s\n' "$line" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  printf '{"id":"%s","ok":true}\n' "$id"
done
`

// writeFakeDaemon writes body to an executable script and returns a config that
// runs it, so a test can stand in for the Python daemon without the Python
// engine being installed.
func writeFakeDaemon(t *testing.T, body string) DaemonConfig {
	t.Helper()
	path := filepath.Join(t.TempDir(), "fake-daemon.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body), 0o700); err != nil {
		t.Fatalf("write fake daemon: %v", err)
	}
	return DaemonConfig{Command: "sh", Args: []string{path}, WarmupTimeoutSec: 5, MaxRestarts: 1}
}

// TestNewDaemonClientReady covers the constructor's happy path end to end: a
// real process is spawned, the init handshake completes, and the returned client
// reports itself usable. Nothing else exercises the wiring between Start,
// sendInit and the supervisor goroutine.
func TestNewDaemonClientReady(t *testing.T) {
	requireShell(t)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	c, err := NewDaemonClient(ctx, writeFakeDaemon(t, initEchoScript), LLMConfig{
		APIKey: "k", BaseURL: "http://example.invalid", Model: "m", SummarizeModel: "s",
	})
	if err != nil {
		t.Fatalf("NewDaemonClient: %v", err)
	}
	defer c.Stop()

	if !c.Ready() {
		t.Fatal("expected a client returned without error to be ready")
	}
}

// TestNewDaemonClientStartFailure asserts the constructor propagates a spawn
// failure instead of returning a client that would panic on first use.
func TestNewDaemonClientStartFailure(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	cfg := DaemonConfig{Command: filepath.Join(t.TempDir(), "no-such-daemon"), WarmupTimeoutSec: 1}
	c, err := NewDaemonClient(ctx, cfg, LLMConfig{})
	if err == nil {
		c.Stop()
		t.Fatal("expected an error when the daemon command does not exist")
	}
	if c != nil {
		t.Fatalf("expected a nil client alongside the error, got %+v", c)
	}
}

// TestNewDaemonClientInitRejected covers the path where the process starts but
// refuses the init command. The constructor must surface the daemon's own
// message and tear the process down, because a client whose init failed has no
// LLM credentials loaded and would fail every later call.
func TestNewDaemonClientInitRejected(t *testing.T) {
	requireShell(t)

	script := `echo __READY__ >&2
while IFS= read -r line; do
  id=$(printf '%s\n' "$line" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  printf '{"id":"%s","ok":false,"error":{"code":"bad_config","message":"missing api key"}}\n' "$id"
done
`

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	c, err := NewDaemonClient(ctx, writeFakeDaemon(t, script), LLMConfig{})
	if err == nil {
		c.Stop()
		t.Fatal("expected an error when the daemon rejects init")
	}
	if c != nil {
		t.Fatalf("expected a nil client alongside the error, got %+v", c)
	}
	if !strings.Contains(err.Error(), "missing api key") {
		t.Fatalf("expected the daemon's own message in the error, got %v", err)
	}
}

// TestNewDaemonClientInitRejectedWithoutMessage pins the fallback for a daemon
// that reports failure without saying why: the constructor still fails rather
// than treating a bare ok:false as success.
func TestNewDaemonClientInitRejectedWithoutMessage(t *testing.T) {
	requireShell(t)

	script := `echo __READY__ >&2
while IFS= read -r line; do
  id=$(printf '%s\n' "$line" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
  printf '{"id":"%s","ok":false}\n' "$id"
done
`

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	c, err := NewDaemonClient(ctx, writeFakeDaemon(t, script), LLMConfig{})
	if err == nil {
		c.Stop()
		t.Fatal("expected an error when the daemon rejects init without a message")
	}
	if !strings.Contains(err.Error(), "unknown error") {
		t.Fatalf("expected the unknown-error fallback, got %v", err)
	}
}
