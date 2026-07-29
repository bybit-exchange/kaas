package bridge

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// ErrDaemonNotReady is returned when the daemon process is not in a ready state.
var ErrDaemonNotReady = errors.New("daemon not ready")

// DaemonConfig holds configuration for the MultiplexStreamDaemon.
type DaemonConfig struct {
	Command          string
	Args             []string
	Concurrency      int
	WarmupTimeoutSec int
	MaxRestarts      int
}

// MultiplexStreamDaemon manages a long-running Python daemon process that
// supports multiplexed streaming over stdin/stdout. This file implements process
// lifecycle management only; the protocol layer (readLoop, call, stream) is
// implemented separately.
type MultiplexStreamDaemon struct {
	command string
	args    []string
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	stdout  io.ReadCloser
	writerMu sync.Mutex

	// pendingOnce and pendingStream are used by the protocol layer (feat-005).
	pendingOnce   sync.Map // map[string]chan *daemonResponse — non-streaming
	pendingStream sync.Map // map[string]*streamEntry — streaming

	nextID    atomic.Uint64
	ready     atomic.Bool
	stopping  atomic.Bool
	done      chan struct{}
	cancelFunc context.CancelFunc

	// concurrency control
	concurrency int
	sem         chan struct{}
	wg          sync.WaitGroup

	cfg DaemonConfig
}

// NewMultiplexStreamDaemon creates a new daemon configured to launch the given
// command. Call Start to spawn the process.
func NewMultiplexStreamDaemon(cfg DaemonConfig) *MultiplexStreamDaemon {
	concurrency := cfg.Concurrency
	if concurrency < 1 {
		concurrency = 1
	}
	return &MultiplexStreamDaemon{
		command:     cfg.Command,
		args:        cfg.Args,
		concurrency: concurrency,
		sem:         make(chan struct{}, concurrency),
		done:        make(chan struct{}),
		cfg:         cfg,
	}
}

// Ready returns whether the daemon is currently in a ready state.
func (d *MultiplexStreamDaemon) Ready() bool {
	return d.ready.Load()
}

// Start spawns the Python daemon process and blocks until it signals readiness
// (by printing "__READY__" to stderr) or the context is cancelled/times out.
func (d *MultiplexStreamDaemon) Start(ctx context.Context) error {
	childCtx, cancel := context.WithCancel(context.Background())
	d.cancelFunc = cancel

	cmd := exec.CommandContext(childCtx, d.command, d.args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if killErr := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL); killErr == syscall.ESRCH {
			return os.ErrProcessDone
		} else { //nolint:revive
			return killErr
		}
	}
	cmd.Env = filterEnv(os.Environ(), "VIRTUAL_ENV")

	// Pass concurrency as max workers for the Python thread pool.
	if d.concurrency > 0 {
		cmd.Env = append(cmd.Env, fmt.Sprintf("KAAS_DAEMON_MAX_WORKERS=%d", d.concurrency))
	}

	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("multiplex stream daemon: failed to create stdin pipe: %w", err)
	}

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("multiplex stream daemon: failed to create stdout pipe: %w", err)
	}

	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		return fmt.Errorf("multiplex stream daemon: failed to create stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		cancel()
		return fmt.Errorf("multiplex stream daemon: failed to start process: %w", err)
	}

	d.cmd = cmd
	d.stdin = stdinPipe
	d.stdout = stdoutPipe

	// Start stderr reader that watches for __READY__ signal.
	readyCh := make(chan struct{}, 1)
	go d.readStderr(stderrPipe, readyCh)

	// Start process monitor goroutine.
	doneCh := d.done
	go d.monitorProcess(doneCh)

	// Wait for ready signal or context timeout.
	select {
	case <-readyCh:
		// Start the readLoop goroutine to process responses from stdout.
		scanner := bufio.NewScanner(d.stdout)
		scanner.Buffer(make([]byte, 0, 8<<20), 8<<20) // 8MB buffer for large responses
		go d.readLoop(scanner)
		d.ready.Store(true)
		log.Printf("[multiplex-stream] process ready (pid=%d)", cmd.Process.Pid)
		return nil
	case <-ctx.Done():
		d.Stop()
		return fmt.Errorf("multiplex stream daemon: timed out waiting for __READY__: %w", ctx.Err())
	case <-doneCh:
		return fmt.Errorf("multiplex stream daemon: process exited before becoming ready")
	}
}

// Stop gracefully shuts down the daemon process.
// It closes stdin to signal the Python process to exit, then waits for it to
// finish. If the process does not exit within 5 seconds, it is force-killed
// via process group SIGKILL.
func (d *MultiplexStreamDaemon) Stop() {
	d.stopping.Store(true)
	d.ready.Store(false)

	// Close stdin — causes Python readline loop to exit.
	if d.stdin != nil {
		_ = d.stdin.Close()
	}

	// Wait for process exit or force kill after timeout.
	select {
	case <-d.done:
	case <-time.After(5 * time.Second):
		if d.cancelFunc != nil {
			d.cancelFunc()
		}
		<-d.done
	}

	// Wait for all in-flight goroutines to complete cleanup.
	d.wg.Wait()
}

// Restart gracefully stops the current daemon and starts a new one.
func (d *MultiplexStreamDaemon) Restart(ctx context.Context) error {
	log.Printf("[multiplex-stream] restarting daemon")
	d.Stop()
	d.done = make(chan struct{})
	d.stopping.Store(false)
	return d.Start(ctx)
}

// readStderr continuously reads the daemon's stderr, looking for the __READY__
// marker and logging all other output.
func (d *MultiplexStreamDaemon) readStderr(r io.Reader, readyCh chan<- struct{}) {
	scanner := bufio.NewScanner(r)
	readySent := false
	for scanner.Scan() {
		line := scanner.Text()
		if !readySent && line == "__READY__" {
			readySent = true
			readyCh <- struct{}{}
			continue
		}
		log.Printf("[multiplex-stream][stderr]: %s", line)
	}
}

// monitorProcess waits for the daemon process to exit and updates state.
// doneCh is the captured d.done channel from Start to avoid races with Restart.
func (d *MultiplexStreamDaemon) monitorProcess(doneCh chan struct{}) {
	err := d.cmd.Wait()

	pid := d.cmd.Process.Pid
	stopping := d.stopping.Load()

	d.ready.Store(false)
	close(doneCh)

	if stopping {
		if err != nil {
			log.Printf("[multiplex-stream] process exited during shutdown (pid=%d, err=%v)", pid, err)
		} else {
			log.Printf("[multiplex-stream] process exited normally (pid=%d)", pid)
		}
	} else if err != nil {
		log.Printf("[multiplex-stream] process crashed (pid=%d, err=%v)", pid, err)
	} else {
		log.Printf("[multiplex-stream] process exited normally (pid=%d)", pid)
	}
}

// filterEnv returns a copy of env with any entries whose key matches one of the
// excluded keys removed. This prevents leaking host virtualenv paths into the
// child process.
func filterEnv(env []string, exclude ...string) []string {
	out := make([]string, 0, len(env))
	for _, e := range env {
		skip := false
		for _, key := range exclude {
			if strings.HasPrefix(e, key+"=") {
				skip = true
				break
			}
		}
		if !skip {
			out = append(out, e)
		}
	}
	return out
}
