// Package config loads the KaaS backend configuration from a TOML file.
//
// It mirrors etc/kaas.toml and is loaded via go-zero's conf package so the
// same loader serves the REST server in later slices.
package config

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/zeromicro/go-zero/core/conf"
)

// Config is the root configuration, matching the tables in etc/kaas.toml.
type Config struct {
	Server  ServerConf  `json:"server"`
	Storage StorageConf `json:"storage"`
	Worker  WorkerConf  `json:"worker"`
	AI      AIConf      `json:"ai"`
	LLM     LLMConf     `json:"llm"`
	Upload  UploadConf  `json:"upload"`
	Log     LogConf     `json:"log"`
}

// LogConf configures structured logging output.
type LogConf struct {
	Level  string `json:"level,default=info"`
	Format string `json:"format,default=json"`
}

// UploadConf configures file upload limits for POST /api/submit/files.
type UploadConf struct {
	MaxBodyBytes        int64 `json:"max_body_bytes,default=52428800"`
	MaxFileSize         int64 `json:"max_file_size,default=1048576"`
	MaxRichFileSize     int64 `json:"max_rich_file_size,default=10485760"`
	MaxZipFileSize      int64 `json:"max_zip_file_size,default=5242880"`
	MaxFilesPerUpload   int   `json:"max_files_per_upload,default=20"`
	MaxZipEntries       int   `json:"max_zip_entries,default=200"`
	MaxZipExtractedSize int64 `json:"max_zip_extracted_size,default=31457280"`
}

// ServerConf configures the HTTP listener.
type ServerConf struct {
	Host string `json:"host,default=0.0.0.0"`
	Port int    `json:"port,default=8080"`
	// WebDir is the built Web UI (web/dist) served by the backend. Empty
	// disables static serving (e.g. local dev where Vite serves the UI).
	WebDir string `json:"web_dir,optional"`
}

// StorageConf selects and configures the persistence backend.
type StorageConf struct {
	// Driver is "sqlite" (default) or "mysql".
	Driver string `json:"driver,default=sqlite"`
	// SQLitePath is the database file path when Driver=="sqlite".
	SQLitePath string `json:"sqlite_path,default=./data/kaas.db"`
	// MySQLDSN is the DSN when Driver=="mysql".
	MySQLDSN string `json:"mysql_dsn,optional"`
	// KBDir is the knowledge-base data directory (raw/, wiki/, index/).
	KBDir string `json:"kb_dir,default=./data"`
}

// WorkerConf tunes the compile worker pool.
type WorkerConf struct {
	// ExtractWorkers is how many documents the dispatcher runs at once, and it is
	// the ceiling on a bulk ingest's throughput: each queue task carries a single
	// document, so the per-phase fan-out inside Python collapses to one group and
	// this is the only document-level parallelism there is. At 4 it made the queue
	// route roughly 3x slower than `kb-ai compile`, which runs 16 for the same
	// work. 12 is the highest figure this pipeline has actually been measured at
	// against a live gateway (108 documents, zero extract errors), so it is
	// preferred over matching the CLI's unmeasured 16. Every worker holds a daemon
	// slot, so AIConf.Daemon.Concurrency has to stay at or above this.
	ExtractWorkers      int `json:"extract_workers,default=12"`
	PipelineConcurrency int `json:"pipeline_concurrency,default=2"`
	PollIntervalMS      int `json:"poll_interval_ms,default=1000"`
	LeaseTimeoutSec     int `json:"lease_timeout_sec,default=300"`
	CBFailureThreshold  int `json:"cb_failure_threshold,default=5"`
	CBCooldownSec       int `json:"cb_cooldown_sec,default=30"`
}

// AIConf configures the AI engine (daemon) and optional MCP reverse proxy.
type AIConf struct {
	// MCPURL is the streamable-http MCP server (ai-mcp) the backend reverse
	// proxies at /mcp. Empty (default) leaves /mcp unregistered — remote MCP
	// disabled. Set via compose to http://ai-mcp:8082.
	MCPURL string `json:"mcp_url,optional"`
	// Daemon configures the in-process Python daemon spawned at startup.
	Daemon DaemonConf `json:"daemon"`
	// MCP configures the native Go MCP streamable-http endpoint.
	MCP MCPConf `json:"mcp"`
}

// MCPConf controls the native Go MCP streamable-http endpoint.
type MCPConf struct {
	Enabled    bool   `json:"enabled,default=false"`
	Token      string `json:"token,optional"`
	TimeoutSec int    `json:"timeout_sec,default=120"`
}

// DaemonConf configures the multiplexed Python daemon process lifecycle.
type DaemonConf struct {
	Command string   `json:"command,default=uv"`
	Args    []string `json:"args,optional"`
	// Concurrency sizes the daemon's in-flight semaphore. It has to cover
	// WorkerConf.ExtractWorkers, since every dispatched document occupies a slot
	// for its whole pipeline; below that the daemon, not the dispatcher, is what
	// limits a bulk ingest. The margin over it leaves room for the KB-level calls
	// that share the daemon — chat, derive, retrieval — so a bulk ingest does not
	// lock interactive requests out.
	Concurrency      int `json:"concurrency,default=16"`
	WarmupTimeoutSec int `json:"warmup_timeout_sec,default=30"`
	MaxRestarts      int `json:"max_restarts,default=5"`
}

// LLMConf holds OpenAI-compatible LLM credentials forwarded to the AI engine.
//
// ExtractStrategy is a per-knowledge-base contract rather than a tuning knob:
// "chunked" sends the document text to the structured extractor, "summarize"
// summarizes each chunk first and extracts from the joined summaries, so the
// structured pass never sees the original words. Both ingestion routes read this
// one value -- the CLI compares it in its freshness gate and the worker forwards
// it -- because when the CLI assumed "chunked" instead, every extraction the
// engine recorded as summarize read as stale and was re-extracted once per
// document, silently downgraded.
type LLMConf struct {
	APIKey          string `json:"api_key,optional"`
	BaseURL         string `json:"base_url,default=https://api.openai.com/v1"`
	Model           string `json:"model,default=gpt-4o-mini"`
	SummarizeModel  string `json:"summarize_model,optional"`
	ExtractStrategy string `json:"extract_strategy,default=chunked"`
}

// The strategies the AI engine's router accepts. Mirrors EXTRACT_STRATEGIES in
// py/src/kb_ai/core/extract.py; validated here so a typo fails at startup rather
// than once per document after the scan.
var extractStrategies = []string{"chunked", "summarize", "auto"}

// Load reads and validates the configuration at path (TOML/YAML/JSON by ext).
func Load(path string) (*Config, error) {
	var c Config
	if err := conf.Load(path, &c); err != nil {
		return nil, fmt.Errorf("load config %q: %w", path, err)
	}
	applyEnvOverrides(&c)
	applyDefaults(&c)
	if err := c.validate(); err != nil {
		return nil, err
	}
	if err := c.resolvePaths(); err != nil {
		return nil, err
	}
	return &c, nil
}

// applyEnvOverrides lets a few environment variables override file values, so
// the same kaas.toml works in a container without baking deployment topology or
// secrets into it. A set-but-empty var is treated as unset (no clobbering).
// Used by docker-compose to point the backend at the AI service (ai:8081) and
// to inject the LLM key without writing it to disk.
func applyEnvOverrides(c *Config) {
	if v := os.Getenv("KAAS_AI_MCP_URL"); v != "" {
		c.AI.MCPURL = v
		log.Printf("[config] KAAS_AI_MCP_URL is deprecated and will be removed in v2.0 (2026 Q4). " +
			"Use [ai.mcp] enabled=true in kaas.toml or KAAS_MCP_ENABLED=true instead.")
	}
	if v := os.Getenv("KAAS_WEB_DIR"); v != "" {
		c.Server.WebDir = v
	}
	if v := os.Getenv("KAAS_MCP_ENABLED"); v == "true" || v == "1" {
		c.AI.MCP.Enabled = true
	}
	if v := os.Getenv("KAAS_MCP_TOKEN"); v != "" {
		c.AI.MCP.Token = v
	}
	if v := os.Getenv("LLM_API_KEY"); v != "" {
		c.LLM.APIKey = v
	}
	if v := os.Getenv("LLM_BASE_URL"); v != "" {
		c.LLM.BaseURL = v
	}
	if v := os.Getenv("LLM_MODEL"); v != "" {
		c.LLM.Model = v
	}
	if v := os.Getenv("LLM_SUMMARIZE_MODEL"); v != "" {
		c.LLM.SummarizeModel = v
	}
	if v := os.Getenv("LLM_EXTRACT_STRATEGY"); v != "" {
		c.LLM.ExtractStrategy = v
	}
}

func applyDefaults(c *Config) {
	if c.LLM.SummarizeModel == "" {
		c.LLM.SummarizeModel = c.LLM.Model
	}
}

func (c *Config) validate() error {
	switch c.Storage.Driver {
	case "sqlite":
		if c.Storage.SQLitePath == "" {
			return fmt.Errorf("storage.sqlite_path must be set when driver=sqlite")
		}
	case "mysql":
		if c.Storage.MySQLDSN == "" {
			return fmt.Errorf("storage.mysql_dsn must be set when driver=mysql")
		}
	default:
		return fmt.Errorf("storage.driver must be \"sqlite\" or \"mysql\", got %q", c.Storage.Driver)
	}
	if c.Storage.KBDir == "" {
		return fmt.Errorf("storage.kb_dir must be set")
	}
	if c.Worker.LeaseTimeoutSec <= 0 {
		return fmt.Errorf("worker.lease_timeout_sec must be > 0")
	}
	if !slices.Contains(extractStrategies, c.LLM.ExtractStrategy) {
		return fmt.Errorf("llm.extract_strategy must be one of %s, got %q",
			strings.Join(extractStrategies, ", "), c.LLM.ExtractStrategy)
	}
	return nil
}

// resolvePaths converts relative paths in storage config to absolute paths so
// that subprocesses with a different CWD (e.g. the Python daemon launched via
// "uv run --directory py") resolve them correctly. When KAAS_HOME is set,
// relative paths are resolved against it instead of CWD.
func (c *Config) resolvePaths() error {
	base := os.Getenv("KAAS_HOME")
	if base == "" {
		var err error
		base, err = os.Getwd()
		if err != nil {
			return fmt.Errorf("getwd: %w", err)
		}
	}

	if !filepath.IsAbs(c.Storage.KBDir) {
		c.Storage.KBDir = filepath.Join(base, c.Storage.KBDir)
	}
	if c.Storage.SQLitePath != "" && !filepath.IsAbs(c.Storage.SQLitePath) {
		c.Storage.SQLitePath = filepath.Join(base, c.Storage.SQLitePath)
	}
	return nil
}
