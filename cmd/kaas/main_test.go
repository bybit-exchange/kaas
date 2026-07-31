package main

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/config"
	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
	"github.com/bybit-exchange/kaas/internal/version"
)

// --- helpers ---

// captureStd swaps *target (os.Stdout or os.Stderr) for a pipe while fn runs and
// returns everything written to it. Tests using it must not run in parallel.
func captureStd(t *testing.T, target **os.File, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	orig := *target
	*target = w
	out := make(chan string, 1)
	go func() {
		b, _ := io.ReadAll(r)
		out <- string(b)
	}()
	fn()
	*target = orig
	w.Close()
	s := <-out
	r.Close()
	return s
}

// writeConfig writes a kaas.toml into a temp dir and returns its path.
func writeConfig(t *testing.T, body string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "kaas.toml")
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}
	return p
}

// seedTask builds a pending task row with an empty file_title — the shape the
// startup backfill targets.
func seedTask(rawPath string) *store.Task {
	now := time.Now().UnixMilli()
	return &store.Task{
		ID:          "backfill-1",
		Source:      "file",
		RawPath:     rawPath,
		ContentHash: "hash-backfill-1",
		Status:      store.StatusPending,
		Stage:       store.StageQueued,
		MaxAttempts: 1,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
}

// clearKaasEnv neutralises every environment variable the config-path and
// install-layout probes consult, so a developer's shell cannot alter results.
func clearKaasEnv(t *testing.T) {
	t.Helper()
	for _, k := range []string{"KAAS_CONFIG", "KAAS_HOME", "XDG_CONFIG_HOME"} {
		t.Setenv(k, "")
	}
}

// --- heartbeatInterval ---

// TestHeartbeatInterval pins the lease-renewal cadence: a third of the TTL so
// two renewals can be missed before the lease lapses, never below 1s.
func TestHeartbeatInterval(t *testing.T) {
	tests := []struct {
		name string
		ttl  time.Duration
		want time.Duration
	}{
		{"default 300s lease", 300 * time.Second, 100 * time.Second},
		{"90s lease", 90 * time.Second, 30 * time.Second},
		{"3s lease is exactly the floor", 3 * time.Second, time.Second},
		{"2s lease clamps to floor", 2 * time.Second, time.Second},
		{"zero clamps to floor", 0, time.Second},
		{"negative clamps to floor", -time.Minute, time.Second},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := heartbeatInterval(tc.ttl); got != tc.want {
				t.Errorf("heartbeatInterval(%v) = %v, want %v", tc.ttl, got, tc.want)
			}
		})
	}
}

// TestHeartbeatIntervalLeavesLeaseHeadroom asserts the derived interval always
// leaves room for at least two renewals inside the lease window — the property
// the /3 exists for.
func TestHeartbeatIntervalLeavesLeaseHeadroom(t *testing.T) {
	for _, ttl := range []time.Duration{3 * time.Second, 30 * time.Second, 300 * time.Second} {
		hb := heartbeatInterval(ttl)
		if hb*2 >= ttl {
			t.Errorf("ttl=%v: heartbeat %v leaves no room for two renewals", ttl, hb)
		}
	}
}

// --- newLogger ---

func TestNewLoggerLevels(t *testing.T) {
	tests := []struct {
		level     string
		wantLevel slog.Level
	}{
		{"debug", slog.LevelDebug},
		{"info", slog.LevelInfo},
		{"", slog.LevelInfo},
		{"WARN", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"Error", slog.LevelError},
	}
	for _, tc := range tests {
		t.Run("level="+tc.level, func(t *testing.T) {
			lg := newLogger(config.LogConf{Level: tc.level, Format: "json"})
			ctx := context.Background()
			if !lg.Enabled(ctx, tc.wantLevel) {
				t.Errorf("level %q: %v should be enabled", tc.level, tc.wantLevel)
			}
			if tc.wantLevel > slog.LevelDebug && lg.Enabled(ctx, tc.wantLevel-1) {
				t.Errorf("level %q: %v should be filtered out", tc.level, tc.wantLevel-1)
			}
		})
	}
}

// TestNewLoggerUnknownLevel asserts an unparsable level warns on stderr and
// degrades to info rather than silently dropping logs.
func TestNewLoggerUnknownLevel(t *testing.T) {
	var lg *slog.Logger
	stderr := captureStd(t, &os.Stderr, func() {
		lg = newLogger(config.LogConf{Level: "verbose", Format: "json"})
	})
	if !strings.Contains(stderr, `unknown log level "verbose"`) {
		t.Errorf("stderr = %q, want a warning naming the bad level", stderr)
	}
	ctx := context.Background()
	if !lg.Enabled(ctx, slog.LevelInfo) || lg.Enabled(ctx, slog.LevelDebug) {
		t.Error("fallback logger should behave like info")
	}
}

func TestNewLoggerFormats(t *testing.T) {
	tests := []struct {
		format   string
		wantJSON bool
	}{
		{"json", true},
		{"", true},
		{"JSON", true},
		{"text", false},
		{"TEXT", false},
	}
	for _, tc := range tests {
		t.Run("format="+tc.format, func(t *testing.T) {
			lg := newLogger(config.LogConf{Format: tc.format})
			_, isJSON := lg.Handler().(*slog.JSONHandler)
			if isJSON != tc.wantJSON {
				t.Errorf("format %q: handler = %T, wantJSON=%v", tc.format, lg.Handler(), tc.wantJSON)
			}
		})
	}
}

func TestNewLoggerUnknownFormat(t *testing.T) {
	var lg *slog.Logger
	stderr := captureStd(t, &os.Stderr, func() {
		lg = newLogger(config.LogConf{Format: "logfmt"})
	})
	if !strings.Contains(stderr, `unknown log format "logfmt"`) {
		t.Errorf("stderr = %q, want a warning naming the bad format", stderr)
	}
	if _, ok := lg.Handler().(*slog.JSONHandler); !ok {
		t.Errorf("fallback handler = %T, want *slog.JSONHandler", lg.Handler())
	}
}

// TestNewLoggerWritesToStdout guards the operational contract that structured
// logs go to stdout (stderr is reserved for the daemon's own diagnostics).
func TestNewLoggerWritesToStdout(t *testing.T) {
	stdout := captureStd(t, &os.Stdout, func() {
		newLogger(config.LogConf{Level: "info", Format: "json"}).Info("hello", "k", "v")
	})
	if !strings.Contains(stdout, `"msg":"hello"`) || !strings.Contains(stdout, `"k":"v"`) {
		t.Errorf("stdout = %q, want the JSON log line", stdout)
	}
}

// --- openStore ---

func TestOpenStoreSQLiteCreatesParentDir(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "nested", "deeper", "kaas.db")
	st, err := openStore(&config.Config{Storage: config.StorageConf{
		Driver:     "sqlite",
		SQLitePath: dbPath,
	}})
	if err != nil {
		t.Fatalf("openStore: %v", err)
	}
	defer st.Close()

	if _, ok := st.(*sqlite.Store); !ok {
		t.Errorf("openStore returned %T, want *sqlite.Store", st)
	}
	// A usable store proves the file and its parents were created.
	if err := st.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate on fresh store: %v", err)
	}
	if _, err := os.Stat(dbPath); err != nil {
		t.Errorf("db file not created at %s: %v", dbPath, err)
	}
}

func TestOpenStoreErrors(t *testing.T) {
	// A regular file where a directory must go makes MkdirAll fail.
	blocker := filepath.Join(t.TempDir(), "not-a-dir")
	if err := os.WriteFile(blocker, []byte("x"), 0o644); err != nil {
		t.Fatalf("write blocker: %v", err)
	}

	tests := []struct {
		name    string
		cfg     config.StorageConf
		wantMsg string
	}{
		{
			name:    "mysql is not implemented",
			cfg:     config.StorageConf{Driver: "mysql", MySQLDSN: "user:pw@/db"},
			wantMsg: "mysql backend not implemented",
		},
		{
			name:    "unknown driver",
			cfg:     config.StorageConf{Driver: "postgres"},
			wantMsg: `unknown storage driver "postgres"`,
		},
		{
			name:    "unwritable sqlite parent",
			cfg:     config.StorageConf{Driver: "sqlite", SQLitePath: filepath.Join(blocker, "sub", "kaas.db")},
			wantMsg: "create sqlite dir",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			st, err := openStore(&config.Config{Storage: tc.cfg})
			if err == nil {
				st.Close()
				t.Fatalf("expected an error for %+v", tc.cfg)
			}
			if st != nil {
				t.Errorf("store must be nil on error, got %T", st)
			}
			if !strings.Contains(err.Error(), tc.wantMsg) {
				t.Errorf("err = %v, want it to mention %q", err, tc.wantMsg)
			}
		})
	}
}

// --- defaultConfigPath ---

func TestDefaultConfigPath(t *testing.T) {
	t.Run("KAAS_CONFIG wins over everything", func(t *testing.T) {
		clearKaasEnv(t)
		dir := t.TempDir()
		t.Chdir(dir)
		// A cwd kaas.toml exists but must lose to the explicit env var.
		if err := os.WriteFile(filepath.Join(dir, "kaas.toml"), nil, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		t.Setenv("KAAS_CONFIG", "/explicit/kaas.toml")
		if got := defaultConfigPath(); got != "/explicit/kaas.toml" {
			t.Errorf("defaultConfigPath() = %q, want the KAAS_CONFIG value", got)
		}
	})

	t.Run("cwd kaas.toml", func(t *testing.T) {
		clearKaasEnv(t)
		dir := t.TempDir()
		t.Chdir(dir)
		if err := os.WriteFile(filepath.Join(dir, "kaas.toml"), nil, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		if got := defaultConfigPath(); got != "kaas.toml" {
			t.Errorf("defaultConfigPath() = %q, want %q", got, "kaas.toml")
		}
	})

	t.Run("KAAS_HOME etc/kaas.toml", func(t *testing.T) {
		clearKaasEnv(t)
		t.Chdir(t.TempDir()) // no kaas.toml in cwd
		home := t.TempDir()
		want := filepath.Join(home, "etc", "kaas.toml")
		if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
			t.Fatalf("mkdir: %v", err)
		}
		if err := os.WriteFile(want, nil, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		t.Setenv("KAAS_HOME", home)
		if got := defaultConfigPath(); got != want {
			t.Errorf("defaultConfigPath() = %q, want %q", got, want)
		}
	})

	t.Run("KAAS_HOME set but file absent falls through", func(t *testing.T) {
		clearKaasEnv(t)
		t.Chdir(t.TempDir())
		t.Setenv("KAAS_HOME", t.TempDir()) // no etc/kaas.toml inside
		xdg := t.TempDir()
		t.Setenv("XDG_CONFIG_HOME", xdg)
		want := filepath.Join(xdg, "kaas", "kaas.toml")
		if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
			t.Fatalf("mkdir: %v", err)
		}
		if err := os.WriteFile(want, nil, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		if got := defaultConfigPath(); got != want {
			t.Errorf("defaultConfigPath() = %q, want the XDG path %q", got, want)
		}
	})

	t.Run("HOME/.config when XDG_CONFIG_HOME unset", func(t *testing.T) {
		clearKaasEnv(t)
		t.Chdir(t.TempDir())
		home := t.TempDir()
		t.Setenv("HOME", home)
		want := filepath.Join(home, ".config", "kaas", "kaas.toml")
		if err := os.MkdirAll(filepath.Dir(want), 0o755); err != nil {
			t.Fatalf("mkdir: %v", err)
		}
		if err := os.WriteFile(want, nil, 0o644); err != nil {
			t.Fatalf("write: %v", err)
		}
		if got := defaultConfigPath(); got != want {
			t.Errorf("defaultConfigPath() = %q, want %q", got, want)
		}
	})

	t.Run("falls back to repo-relative etc/kaas.toml", func(t *testing.T) {
		clearKaasEnv(t)
		t.Chdir(t.TempDir())
		t.Setenv("HOME", t.TempDir())
		if got := defaultConfigPath(); got != "etc/kaas.toml" {
			t.Errorf("defaultConfigPath() = %q, want %q", got, "etc/kaas.toml")
		}
	})
}

// --- setKaasHomeIfInstalled ---

func TestSetKaasHomeIfInstalledKeepsExistingValue(t *testing.T) {
	t.Setenv("KAAS_HOME", "/preset/home")
	setKaasHomeIfInstalled()
	if got := os.Getenv("KAAS_HOME"); got != "/preset/home" {
		t.Errorf("KAAS_HOME = %q, an explicit value must not be overwritten", got)
	}
}

func TestSetKaasHomeIfInstalledNoInstallLayout(t *testing.T) {
	t.Setenv("KAAS_HOME", "")
	setKaasHomeIfInstalled()
	if got := os.Getenv("KAAS_HOME"); got != "" {
		t.Errorf("KAAS_HOME = %q, want it left unset without a venv next to the binary", got)
	}
}

// TestSetKaasHomeIfInstalledDetectsVenv builds the tarball layout
// (<install>/bin/kaas + <install>/py/.venv/bin/python3) around the running test
// binary so the probe fires. Skipped unless the binary sits under TMPDIR, so it
// can never write outside a temporary tree.
func TestSetKaasHomeIfInstalledDetectsVenv(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Skipf("os.Executable unavailable: %v", err)
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		t.Skipf("EvalSymlinks: %v", err)
	}
	installDir := filepath.Dir(filepath.Dir(exe))

	tmp, err := filepath.EvalSymlinks(os.TempDir())
	if err != nil {
		t.Skipf("EvalSymlinks(TMPDIR): %v", err)
	}
	if !strings.HasPrefix(installDir, tmp+string(filepath.Separator)) {
		t.Skipf("test binary is not under TMPDIR (%s); refusing to write to %s", tmp, installDir)
	}

	venvBin := filepath.Join(installDir, "py", ".venv", "bin")
	if err := os.MkdirAll(venvBin, 0o755); err != nil {
		t.Skipf("cannot create fake install layout: %v", err)
	}
	t.Cleanup(func() { os.RemoveAll(filepath.Join(installDir, "py")) })
	if err := os.WriteFile(filepath.Join(venvBin, "python3"), []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write fake python3: %v", err)
	}

	t.Setenv("KAAS_HOME", "")
	setKaasHomeIfInstalled()
	if got := os.Getenv("KAAS_HOME"); got != installDir {
		t.Errorf("KAAS_HOME = %q, want the detected install dir %q", got, installDir)
	}
}

// --- resolveDaemonForInstall ---

// installLayout creates <dir>/py/.venv/bin/python3 and returns the python path.
func installLayout(t *testing.T, dir string) string {
	t.Helper()
	bin := filepath.Join(dir, "py", ".venv", "bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatalf("mkdir venv: %v", err)
	}
	py := filepath.Join(bin, "python3")
	if err := os.WriteFile(py, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write python3: %v", err)
	}
	return py
}

func TestResolveDaemonForInstallNoKaasHome(t *testing.T) {
	t.Setenv("KAAS_HOME", "")
	cfg := &config.Config{}
	cfg.AI.Daemon.Command = "uv"
	resolveDaemonForInstall(cfg)
	if cfg.AI.Daemon.Command != "uv" || cfg.AI.Daemon.Args != nil {
		t.Errorf("daemon config must be untouched without KAAS_HOME: %+v", cfg.AI.Daemon)
	}
}

func TestResolveDaemonForInstallNoVenv(t *testing.T) {
	t.Setenv("KAAS_HOME", t.TempDir()) // exists but has no py/.venv
	cfg := &config.Config{}
	cfg.AI.Daemon.Command = "uv"
	resolveDaemonForInstall(cfg)
	if cfg.AI.Daemon.Command != "uv" {
		t.Errorf("command = %q, want it untouched when the venv is missing", cfg.AI.Daemon.Command)
	}
}

func TestResolveDaemonForInstallUsesVenv(t *testing.T) {
	home := t.TempDir()
	py := installLayout(t, home)
	webDist := filepath.Join(home, "web", "dist")
	if err := os.MkdirAll(webDist, 0o755); err != nil {
		t.Fatalf("mkdir web/dist: %v", err)
	}
	t.Setenv("KAAS_HOME", home)

	cfg := &config.Config{}
	cfg.AI.Daemon.Command = "uv"
	cfg.AI.Daemon.Args = []string{"run", "kb-ai"}
	resolveDaemonForInstall(cfg)

	if cfg.AI.Daemon.Command != py {
		t.Errorf("command = %q, want the venv python %q", cfg.AI.Daemon.Command, py)
	}
	want := []string{"-m", "kb_ai", "daemon"}
	if len(cfg.AI.Daemon.Args) != len(want) {
		t.Fatalf("args = %v, want %v", cfg.AI.Daemon.Args, want)
	}
	for i := range want {
		if cfg.AI.Daemon.Args[i] != want[i] {
			t.Fatalf("args = %v, want %v", cfg.AI.Daemon.Args, want)
		}
	}
	if cfg.Server.WebDir != webDist {
		t.Errorf("web_dir = %q, want the installed %q", cfg.Server.WebDir, webDist)
	}
}

func TestResolveDaemonForInstallKeepsConfiguredWebDir(t *testing.T) {
	home := t.TempDir()
	installLayout(t, home)
	if err := os.MkdirAll(filepath.Join(home, "web", "dist"), 0o755); err != nil {
		t.Fatalf("mkdir web/dist: %v", err)
	}
	t.Setenv("KAAS_HOME", home)

	cfg := &config.Config{}
	cfg.Server.WebDir = "/custom/dist"
	resolveDaemonForInstall(cfg)
	if cfg.Server.WebDir != "/custom/dist" {
		t.Errorf("web_dir = %q, an explicit value must win over the install layout", cfg.Server.WebDir)
	}
}

func TestResolveDaemonForInstallWithoutWebDist(t *testing.T) {
	home := t.TempDir()
	installLayout(t, home) // no web/dist
	t.Setenv("KAAS_HOME", home)

	cfg := &config.Config{}
	resolveDaemonForInstall(cfg)
	if cfg.Server.WebDir != "" {
		t.Errorf("web_dir = %q, want empty (static serving stays disabled)", cfg.Server.WebDir)
	}
}

// --- runServe ---

// TestRunServeRejectsPositionalArgs covers the common "kaas -f x.toml serve"
// mistake: flags placed before the subcommand leave a stray positional arg.
func TestRunServeRejectsPositionalArgs(t *testing.T) {
	var code int
	stderr := captureStd(t, &os.Stderr, func() {
		code = runServe([]string{"extra", "args"})
	})
	if code != 1 {
		t.Errorf("runServe exit code = %d, want 1", code)
	}
	if !strings.Contains(stderr, "unexpected arguments") {
		t.Errorf("stderr = %q, want it to name the unexpected arguments", stderr)
	}
	if !strings.Contains(stderr, "flags must come after the subcommand") {
		t.Errorf("stderr = %q, want the corrective hint", stderr)
	}
}

// --- run ---

func TestRunConfigLoadError(t *testing.T) {
	clearKaasEnv(t)
	err := run(filepath.Join(t.TempDir(), "missing.toml"))
	if err == nil {
		t.Fatal("expected an error for a missing config file")
	}
	if !strings.Contains(err.Error(), "load config") {
		t.Errorf("err = %v, want it wrapped with %q", err, "load config")
	}
}

func TestRunStoreOpenError(t *testing.T) {
	clearKaasEnv(t)
	// mysql passes validation but has no implementation, so run must surface
	// openStore's error instead of proceeding to migrations.
	p := writeConfig(t, `
[storage]
driver = "mysql"
mysql_dsn = "user:pw@tcp(127.0.0.1:3306)/kaas"
kb_dir = "/tmp/kaas-test-kb"
`)
	err := run(p)
	if err == nil {
		t.Fatal("expected an error for the mysql driver")
	}
	if !strings.Contains(err.Error(), "mysql backend not implemented") {
		t.Errorf("err = %v, want the mysql stub error", err)
	}
}

// TestRunDaemonStartFailure drives run() through config load, store open,
// migration and backfill, and stops at the daemon spawn (a path that does not
// exist), asserting the failure is reported rather than swallowed.
func TestRunDaemonStartFailure(t *testing.T) {
	clearKaasEnv(t)
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "data", "kaas.db")
	p := writeConfig(t, `
[storage]
driver = "sqlite"
sqlite_path = "`+dbPath+`"
kb_dir = "`+dir+`"

[ai.daemon]
command = "`+filepath.Join(dir, "definitely-not-a-real-binary")+`"
args = ["daemon"]
warmup_timeout_sec = 5

[llm]
api_key = "sk-test"
`)
	err := run(p)
	if err == nil {
		t.Fatal("expected an error when the daemon binary is missing")
	}
	if !strings.Contains(err.Error(), "daemon start failed") {
		t.Errorf("err = %v, want it wrapped with %q", err, "daemon start failed")
	}
	// The store was opened and migrated before the daemon spawn.
	if _, statErr := os.Stat(dbPath); statErr != nil {
		t.Errorf("expected the sqlite file to exist after migration: %v", statErr)
	}
}

// TestRunBackfillsFileTitles asserts run() repairs rows written before the
// file_title column existed, using the markdown frontmatter of the raw file.
func TestRunBackfillsFileTitles(t *testing.T) {
	clearKaasEnv(t)
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "kaas.db")
	rawPath := filepath.Join(dir, "raw.md")
	if err := os.WriteFile(rawPath, []byte("---\ntitle: Backfilled Title\n---\nbody\n"), 0o644); err != nil {
		t.Fatalf("write raw: %v", err)
	}

	// Seed a task with an empty file_title, then close the store so run() can
	// open it again.
	st, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := st.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	seed := seedTask(rawPath)
	if err := st.CreateTask(context.Background(), seed); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	st.Close()

	p := writeConfig(t, `
[storage]
driver = "sqlite"
sqlite_path = "`+dbPath+`"
kb_dir = "`+dir+`"

[ai.daemon]
command = "`+filepath.Join(dir, "definitely-not-a-real-binary")+`"
warmup_timeout_sec = 5
`)
	if err := run(p); err == nil {
		t.Fatal("expected run to stop at the daemon spawn")
	}

	st2, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer st2.Close()
	got, err := st2.GetTask(context.Background(), seed.ID)
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.FileTitle != "Backfilled Title" {
		t.Errorf("file_title = %q, want it backfilled from frontmatter", got.FileTitle)
	}
}

// --- createEngine ---

func TestCreateEngineDaemonStartFailure(t *testing.T) {
	cfg := &config.Config{}
	cfg.AI.Daemon.Command = filepath.Join(t.TempDir(), "no-such-daemon")
	cfg.AI.Daemon.WarmupTimeoutSec = 5

	eng, chat, cleanup, err := createEngine(context.Background(), cfg)
	if err == nil {
		cleanup()
		t.Fatal("expected an error for a missing daemon command")
	}
	if eng != nil || chat != nil {
		t.Errorf("engine/chat must be nil on error, got %v/%v", eng, chat)
	}
	if cleanup != nil {
		t.Error("cleanup must be nil on error, otherwise callers defer a no-op teardown")
	}
	if !strings.Contains(err.Error(), "daemon start failed") {
		t.Errorf("err = %v, want it wrapped with %q", err, "daemon start failed")
	}
}

// --- main dispatch ---

// TestMainVersion asserts `kaas version` prints the build metadata. main() only
// returns (rather than calling os.Exit) for the version and help commands, so
// those are the two branches a test can drive in-process.
func TestMainVersion(t *testing.T) {
	origArgs := os.Args
	t.Cleanup(func() { os.Args = origArgs })

	stdout := captureStd(t, &os.Stdout, func() {
		os.Args = []string{"kaas", "version"}
		main()
	})
	if stdout != version.String() {
		t.Errorf("stdout = %q, want %q", stdout, version.String())
	}
}

func TestMainHelp(t *testing.T) {
	origArgs := os.Args
	t.Cleanup(func() { os.Args = origArgs })

	for _, arg := range []string{"-h", "--help", "help"} {
		t.Run(arg, func(t *testing.T) {
			stderr := captureStd(t, &os.Stderr, func() {
				os.Args = []string{"kaas", arg}
				main()
			})
			for _, want := range []string{"Usage: kaas", "serve", "version", "-f <path>"} {
				if !strings.Contains(stderr, want) {
					t.Errorf("usage output missing %q; got:\n%s", want, stderr)
				}
			}
		})
	}
}
