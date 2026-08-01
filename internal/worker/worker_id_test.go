package worker

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
)

// TestWorkerID asserts the owner id is hostname-pid, which is what lets
// RecoverExpired tell a restarted process from a still-live one.
func TestWorkerID(t *testing.T) {
	got := WorkerID()

	host, err := os.Hostname()
	if err != nil || host == "" {
		host = "kaas"
	}
	want := fmt.Sprintf("%s-%d", host, os.Getpid())
	if got != want {
		t.Errorf("WorkerID() = %q, want %q", got, want)
	}
}

// TestWorkerIDEndsWithPID guards the suffix contract independently of the
// hostname, which may itself contain hyphens.
func TestWorkerIDEndsWithPID(t *testing.T) {
	got := WorkerID()

	idx := strings.LastIndex(got, "-")
	if idx < 0 {
		t.Fatalf("WorkerID() = %q, want a hostname-pid form", got)
	}
	if got[:idx] == "" {
		t.Errorf("WorkerID() = %q, want a non-empty hostname part", got)
	}

	pid, err := strconv.Atoi(got[idx+1:])
	if err != nil {
		t.Fatalf("WorkerID() = %q, suffix is not a pid: %v", got, err)
	}
	if pid != os.Getpid() {
		t.Errorf("WorkerID() pid = %d, want %d", pid, os.Getpid())
	}
}

// TestWorkerIDStable asserts the id does not change within a process, so a
// worker can reclaim the leases it took out earlier.
func TestWorkerIDStable(t *testing.T) {
	first := WorkerID()
	second := WorkerID()
	if first != second {
		t.Errorf("WorkerID() is not stable within a process: %q then %q", first, second)
	}
}
