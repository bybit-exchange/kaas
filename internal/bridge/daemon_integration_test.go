package bridge

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// findProjectRoot walks up from the test binary's directory to find the project root
// (identified by the presence of go.mod).
func findProjectRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find project root (go.mod)")
		}
		dir = parent
	}
}

// TestDaemonIntegrationLifecycle spawns a real Python daemon, sends ping and init,
// then stops it. Requires `uv` and the Python project to be available.
func TestDaemonIntegrationLifecycle(t *testing.T) {
	if os.Getenv("KAAS_INTEGRATION_TEST") == "" {
		t.Skip("set KAAS_INTEGRATION_TEST=1 to run daemon integration tests")
	}

	root := findProjectRoot(t)
	pyDir := filepath.Join(root, "py")

	// Verify uv is available
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not found in PATH, skipping integration test")
	}

	cfg := DaemonConfig{
		Command:          "uv",
		Args:             []string{"run", "--directory", pyDir, "kb-ai", "daemon"},
		Concurrency:      4,
		WarmupTimeoutSec: 30,
		MaxRestarts:      1,
	}

	d := NewMultiplexStreamDaemon(cfg)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Start
	if err := d.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer d.Stop()

	if !d.Ready() {
		t.Fatal("daemon not ready after Start")
	}

	// Ping
	resp, err := d.call(ctx, daemonRequest{Cmd: "ping"})
	if err != nil {
		t.Fatalf("ping call: %v", err)
	}
	if !resp.OK {
		t.Fatalf("ping not ok: %+v", resp)
	}

	// Init with dummy LLM config
	initPayload := []byte(`{"llm":{"api_key":"test","base_url":"https://api.example.com/v1","model":"test-model"}}`)
	resp, err = d.call(ctx, daemonRequest{Cmd: "init", Payload: initPayload})
	if err != nil {
		t.Fatalf("init call: %v", err)
	}
	if !resp.OK {
		t.Fatalf("init not ok: %+v", resp)
	}

	// Stop
	d.Stop()
	if d.Ready() {
		t.Fatal("daemon still ready after Stop")
	}
}

// TestDaemonIntegrationRestart verifies that Stop + Start recovers service.
func TestDaemonIntegrationRestart(t *testing.T) {
	if os.Getenv("KAAS_INTEGRATION_TEST") == "" {
		t.Skip("set KAAS_INTEGRATION_TEST=1 to run daemon integration tests")
	}

	root := findProjectRoot(t)
	pyDir := filepath.Join(root, "py")

	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv not found in PATH, skipping integration test")
	}

	cfg := DaemonConfig{
		Command:          "uv",
		Args:             []string{"run", "--directory", pyDir, "kb-ai", "daemon"},
		Concurrency:      4,
		WarmupTimeoutSec: 30,
		MaxRestarts:      2,
	}

	d := NewMultiplexStreamDaemon(cfg)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := d.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Verify working
	resp, err := d.call(ctx, daemonRequest{Cmd: "ping"})
	if err != nil || !resp.OK {
		t.Fatalf("first ping failed: err=%v resp=%+v", err, resp)
	}

	// Restart
	if err := d.Restart(ctx); err != nil {
		t.Fatalf("Restart: %v", err)
	}

	if !d.Ready() {
		t.Fatal("daemon not ready after Restart")
	}

	// Verify working after restart
	resp, err = d.call(ctx, daemonRequest{Cmd: "ping"})
	if err != nil || !resp.OK {
		t.Fatalf("post-restart ping failed: err=%v resp=%+v", err, resp)
	}

	d.Stop()
}
