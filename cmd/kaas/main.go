// Command kaas is the KaaS Go backend entry point.
//
// This slice wires the foundation plus the compile worker engine: load config,
// open the store, run migrations, then run the dispatcher (which polls the
// queue and drives Extract → Pipeline via the Python bridge) until a shutdown
// signal. The REST server is added in a later slice.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/bybit-exchange/kaas/internal/api"
	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/config"
	"github.com/bybit-exchange/kaas/internal/frontmatter"
	"github.com/bybit-exchange/kaas/internal/queue"
	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
	"github.com/bybit-exchange/kaas/internal/version"
	"github.com/bybit-exchange/kaas/internal/worker"
)

func main() {
	if len(os.Args) < 2 {
		os.Exit(runServe([]string{}))
	}

	switch os.Args[1] {
	case "serve":
		os.Exit(runServe(os.Args[2:]))
	case "version":
		cmdVersion()
	case "-h", "--help", "help":
		printUsage()
	default:
		// 以 - 开头 = flag，走 serve 兼容旧用法
		if len(os.Args[1]) > 0 && os.Args[1][0] == '-' {
			os.Exit(runServe(os.Args[1:]))
		}
		// 否则未知子命令
		fmt.Fprintf(os.Stderr, "kaas: unknown command %q\n\n", os.Args[1])
		printUsage()
		os.Exit(1)
	}
}

func runServe(args []string) int {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	configFile := fs.String("f", "", "config file path (TOML)")
	fs.Parse(args)

	if fs.NArg() > 0 {
		fmt.Fprintf(os.Stderr, "kaas serve: unexpected arguments: %v\n", fs.Args())
		fmt.Fprintf(os.Stderr, "Note: flags must come after the subcommand (e.g. kaas serve -f config.toml)\n")
		return 1
	}

	setKaasHomeIfInstalled()

	cfgPath := *configFile
	if cfgPath == "" {
		cfgPath = defaultConfigPath()
	}

	if err := run(cfgPath); err != nil {
		log.Fatalf("kaas: %v", err)
	}
	return 0
}

// setKaasHomeIfInstalled detects tarball installation layout and sets KAAS_HOME.
func setKaasHomeIfInstalled() {
	if os.Getenv("KAAS_HOME") != "" {
		return
	}
	exe, err := os.Executable()
	if err != nil {
		return
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return
	}
	exeDir := filepath.Dir(exe)
	installDir := filepath.Dir(exeDir)

	venvPython := filepath.Join(installDir, "py", ".venv", "bin", "python3")
	if _, err := os.Stat(venvPython); err == nil {
		os.Setenv("KAAS_HOME", installDir)
	}
}

// resolveDaemonForInstall overrides daemon and webDir config when running from tarball install.
func resolveDaemonForInstall(cfg *config.Config) {
	installDir := os.Getenv("KAAS_HOME")
	if installDir == "" {
		return
	}

	venvPython := filepath.Join(installDir, "py", ".venv", "bin", "python3")
	if _, err := os.Stat(venvPython); err != nil {
		return
	}

	cfg.AI.Daemon.Command = venvPython
	cfg.AI.Daemon.Args = []string{"-m", "kb_ai", "daemon"}

	if cfg.Server.WebDir == "" {
		webDir := filepath.Join(installDir, "web", "dist")
		if fi, err := os.Stat(webDir); err == nil && fi.IsDir() {
			cfg.Server.WebDir = webDir
		}
	}
}

// defaultConfigPath searches for config file in standard locations.
func defaultConfigPath() string {
	if v := os.Getenv("KAAS_CONFIG"); v != "" {
		return v
	}
	if _, err := os.Stat("kaas.toml"); err == nil {
		return "kaas.toml"
	}
	if home := os.Getenv("KAAS_HOME"); home != "" {
		p := filepath.Join(home, "etc", "kaas.toml")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	cfgDir := os.Getenv("XDG_CONFIG_HOME")
	if cfgDir == "" {
		cfgDir = filepath.Join(os.Getenv("HOME"), ".config")
	}
	p := filepath.Join(cfgDir, "kaas", "kaas.toml")
	if _, err := os.Stat(p); err == nil {
		return p
	}
	return "etc/kaas.toml"
}

func cmdVersion() {
	fmt.Print(version.String())
}

func printUsage() {
	fmt.Fprintf(os.Stderr, `Usage: kaas <command> [options]

Commands:
  serve     启动 KaaS 服务（默认命令）
  version   显示版本信息
  help      显示此帮助

Options for "serve":
  -f <path>   配置文件路径（TOML）

Examples:
  kaas serve -f /path/to/kaas.toml
  kaas -f etc/kaas.toml
  kaas version
`)
}

func run(configFile string) error {
	cfg, err := config.Load(configFile)
	if err != nil {
		return err
	}

	resolveDaemonForInstall(cfg)

	st, err := openStore(cfg)
	if err != nil {
		return err
	}
	defer st.Close()

	if err := st.Migrate(context.Background()); err != nil {
		return err
	}

	if sqlSt, ok := st.(*sqlite.Store); ok {
		n, err := sqlSt.BackfillFileTitles(context.Background(), func(rawPath string) string {
			data, err := os.ReadFile(rawPath)
			if err != nil {
				return ""
			}
			return frontmatter.ExtractTitle(data)
		})
		if err != nil {
			return fmt.Errorf("backfill file titles: %w", err)
		}
		if n > 0 {
			log.Printf("kaas: backfilled file titles: %d", n)
		}
	}

	leaseTTL := time.Duration(cfg.Worker.LeaseTimeoutSec) * time.Second
	q := queue.New(st, queue.Options{LeaseTTL: leaseTTL})

	workerEng, chatBr, cleanup, err := createEngine(context.Background(), cfg)
	if err != nil {
		return err
	}
	defer cleanup()

	brk := circuit.New(circuit.Options{
		FailureThreshold: cfg.Worker.CBFailureThreshold,
		Cooldown:         time.Duration(cfg.Worker.CBCooldownSec) * time.Second,
	})

	owner := worker.WorkerID()
	w := worker.NewWorker(q, workerEng, brk, owner, worker.Config{
		KBDir:             cfg.Storage.KBDir,
		PipelineWorkers:   cfg.Worker.PipelineConcurrency,
		HeartbeatInterval: heartbeatInterval(leaseTTL),
		SummarizeModel:    cfg.LLM.SummarizeModel,
	})
	d := worker.NewDispatcher(q, w, brk, owner,
		time.Duration(cfg.Worker.PollIntervalMS)*time.Millisecond,
		cfg.Worker.ExtractWorkers,
	)

	logger := newLogger(cfg.Log)

	// The sqlite.Store satisfies both api.TaskStore and api.SessionStore; cast
	// to extract the session persistence interface from the same store instance.
	ss, _ := st.(api.SessionStore)
	srv := api.NewServer(q, st, ss, chatBr, api.Config{
		Addr:          net.JoinHostPort(cfg.Server.Host, strconv.Itoa(cfg.Server.Port)),
		KBDir:         cfg.Storage.KBDir,
		Model:         cfg.LLM.Model,
		WebDir:        cfg.Server.WebDir,
		MCPURL:        cfg.AI.MCPURL,
		Upload:        cfg.Upload,
		MCPEnabled:    cfg.AI.MCP.Enabled,
		MCPToken:      cfg.AI.MCP.Token,
		MCPTimeoutSec: cfg.AI.MCP.TimeoutSec,
	}, logger)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Readiness line, mirroring the Python engine's contract so a supervisor
	// can detect the backend is up.
	fmt.Printf("{\"ready\": true, \"port\": %d}\n", cfg.Server.Port)

	// Run the REST server and the compile dispatcher together under one ctx; a
	// shutdown signal cancels both. Either returning an error cancels the other.
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var wg sync.WaitGroup
	errc := make(chan error, 2)
	for name, fn := range map[string]func(context.Context) error{
		"server":     srv.Run,
		"dispatcher": d.Run,
	} {
		wg.Add(1)
		go func(name string, fn func(context.Context) error) {
			defer wg.Done()
			if err := fn(ctx); err != nil {
				errc <- fmt.Errorf("%s: %w", name, err)
				cancel() // bring the other component down too
			}
		}(name, fn)
	}
	wg.Wait()
	close(errc)

	var firstErr error
	for err := range errc {
		if firstErr == nil {
			firstErr = err
		} else {
			log.Printf("kaas: additional shutdown error: %v", err)
		}
	}
	if firstErr != nil {
		return firstErr
	}
	log.Printf("kaas: shut down cleanly")
	return nil
}

// heartbeatInterval renews the lease at a third of its TTL, with a 1s floor.
func heartbeatInterval(ttl time.Duration) time.Duration {
	hb := ttl / 3
	if hb < time.Second {
		hb = time.Second
	}
	return hb
}

// createEngine builds the AI engine (worker.Engine + api.ChatBridge) via daemon.
func createEngine(ctx context.Context, cfg *config.Config) (worker.Engine, api.ChatBridge, func(), error) {
	// Build daemon config, using sensible default args if not specified.
	args := cfg.AI.Daemon.Args
	if len(args) == 0 {
		args = []string{"run", "--directory", "py", "kb-ai", "daemon"}
	}

	daemonCfg := bridge.DaemonConfig{
		Command:          cfg.AI.Daemon.Command,
		Args:             args,
		Concurrency:      cfg.AI.Daemon.Concurrency,
		WarmupTimeoutSec: cfg.AI.Daemon.WarmupTimeoutSec,
		MaxRestarts:      cfg.AI.Daemon.MaxRestarts,
	}
	llmCfg := bridge.LLMConfig{
		APIKey:         cfg.LLM.APIKey,
		BaseURL:        cfg.LLM.BaseURL,
		Model:          cfg.LLM.Model,
		SummarizeModel: cfg.LLM.SummarizeModel,
	}

	warmupTimeout := time.Duration(daemonCfg.WarmupTimeoutSec) * time.Second
	startCtx, startCancel := context.WithTimeout(ctx, warmupTimeout)
	defer startCancel()

	dc, err := bridge.NewDaemonClient(startCtx, daemonCfg, llmCfg)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("daemon start failed: %w", err)
	}
	return dc, dc, func() { dc.Stop() }, nil
}

// openStore selects the persistence backend from config.
func openStore(cfg *config.Config) (store.Store, error) {
	switch cfg.Storage.Driver {
	case "sqlite":
		if err := os.MkdirAll(filepath.Dir(cfg.Storage.SQLitePath), 0o755); err != nil {
			return nil, fmt.Errorf("create sqlite dir: %w", err)
		}
		return sqlite.Open(cfg.Storage.SQLitePath)
	case "mysql":
		return nil, fmt.Errorf("mysql backend not implemented yet")
	default:
		return nil, fmt.Errorf("unknown storage driver %q", cfg.Storage.Driver)
	}
}

func newLogger(c config.LogConf) *slog.Logger {
	var level slog.Level
	switch strings.ToLower(c.Level) {
	case "debug":
		level = slog.LevelDebug
	case "info", "":
		level = slog.LevelInfo
	case "warn", "warning":
		level = slog.LevelWarn
	case "error":
		level = slog.LevelError
	default:
		fmt.Fprintf(os.Stderr, "kaas: unknown log level %q, falling back to \"info\"\n", c.Level)
		level = slog.LevelInfo
	}

	opts := &slog.HandlerOptions{Level: level}

	var handler slog.Handler
	switch strings.ToLower(c.Format) {
	case "text":
		handler = slog.NewTextHandler(os.Stdout, opts)
	case "json", "":
		handler = slog.NewJSONHandler(os.Stdout, opts)
	default:
		fmt.Fprintf(os.Stderr, "kaas: unknown log format %q, falling back to \"json\"\n", c.Format)
		handler = slog.NewJSONHandler(os.Stdout, opts)
	}

	return slog.New(handler)
}
