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
	"strconv"
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
	// DocumentWorkers is the dispatcher's document-level concurrency: how many
	// tasks run through the full extract + pipeline lifecycle in parallel. It
	// was historically named extract_workers, which never limited only the
	// extract stage despite the name.
	DocumentWorkers int `json:"document_workers,optional"`
	// ExtractWorkers is the deprecated alias of DocumentWorkers, kept one
	// release so existing config files keep loading. When both keys are set,
	// DocumentWorkers wins.
	ExtractWorkers      int `json:"extract_workers,optional"`
	PipelineConcurrency int `json:"pipeline_concurrency,default=2"`
	PollIntervalMS      int `json:"poll_interval_ms,default=1000"`
	LeaseTimeoutSec     int `json:"lease_timeout_sec,default=300"`
	CBFailureThreshold  int `json:"cb_failure_threshold,default=5"`
	CBCooldownSec       int `json:"cb_cooldown_sec,default=30"`
	// PipelineBatchMaxItems is the maximum number of pipeline items per
	// batched Pipeline call (grouped write). The default 1 disables batching:
	// every task issues its own call, the pre-batching behaviour.
	PipelineBatchMaxItems int `json:"pipeline_batch_max_items,default=1"`
	// PipelineBatchFlushMS is the batching window in milliseconds: a partial
	// batch flushes when its oldest pending item is this old.
	PipelineBatchFlushMS int `json:"pipeline_batch_flush_ms,default=500"`
	// PipelineBatchMaxInflight caps concurrent in-flight batch calls. Write
	// LLM concurrency is bounded by this × pipeline_concurrency, because the
	// bridge semaphore counts daemon commands, not a batch's internal write
	// fan-out.
	PipelineBatchMaxInflight int `json:"pipeline_batch_max_inflight,default=1"`
	// PipelineBatchDeadlineSec bounds a single batched Pipeline call. It is
	// wired to PipelineRequest.DeadlineSeconds, which the daemon enforces as
	// one absolute wall clock shared by every item in the batch, and to the
	// batcher's shutdown drain. The default 2400 covers the worst expected
	// batch (two ~723s write waves); raise it for slow models or deployments
	// that raised the write call timeout, since a batch slower than the
	// deadline fails items that a direct (pre-batching) call would have
	// finished -- the direct path never carried a deadline.
	PipelineBatchDeadlineSec int `json:"pipeline_batch_deadline_sec,default=2400"`
	// IndexDebounceSec is the index-refresh debounce interval: pipeline
	// completions mark the indexes dirty and one refresh follows this many
	// seconds after the last completion. 0 (default) disables the Go-side
	// refresher and every pipeline call rebuilds the indexes itself (legacy
	// behaviour, rollback switch).
	IndexDebounceSec int `json:"index_debounce_sec,default=0"`
	// IndexMaxStaleSec bounds index staleness under continuous load: a dirty
	// state older than this forces a refresh even while completions keep
	// re-arming the debounce timer. 0 (default) auto-sizes to 5x
	// IndexDebounceSec. Only meaningful when IndexDebounceSec > 0.
	IndexMaxStaleSec int `json:"index_max_stale_sec,default=0"`
}

// defaultDocumentWorkers is the document-level concurrency used when neither
// document_workers nor the deprecated extract_workers alias is set.
const defaultDocumentWorkers = 4

// EffectiveDocumentWorkers resolves the dispatcher's document-level
// concurrency: the first explicitly-set key wins, document_workers over the
// deprecated extract_workers alias, falling back to the built-in default when
// neither is set. An explicitly-set but unusable (negative) value passes
// through so validate() rejects it rather than being masked by the other key
// or the default. Pure -- both validate() and startup logging call it, so the
// shadowed-alias warning lives in validate() where it fires exactly once.
func (w WorkerConf) EffectiveDocumentWorkers() int {
	if w.DocumentWorkers != 0 {
		return w.DocumentWorkers
	}
	if w.ExtractWorkers != 0 {
		return w.ExtractWorkers
	}
	return defaultDocumentWorkers
}

// DocumentWorkersSource names where EffectiveDocumentWorkers resolves its
// value from: "document_workers", the deprecated "extract_workers" alias, or
// "default". Startup logging reports it instead of re-deriving the switch.
func (w WorkerConf) DocumentWorkersSource() string {
	switch {
	case w.DocumentWorkers != 0:
		return "document_workers"
	case w.ExtractWorkers != 0:
		return "extract_workers"
	default:
		return "default"
	}
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
	Command          string   `json:"command,default=uv"`
	Args             []string `json:"args,optional"`
	Concurrency      int      `json:"concurrency,default=8"`
	WarmupTimeoutSec int      `json:"warmup_timeout_sec,default=30"`
	MaxRestarts      int      `json:"max_restarts,default=5"`
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
	if err := applyEnvOverrides(&c); err != nil {
		return nil, err
	}
	applyDefaults(&c)
	if err := c.validate(); err != nil {
		return nil, err
	}
	if err := c.resolvePaths(); err != nil {
		return nil, err
	}
	return &c, nil
}

// envInt reads an integer tuning override. An invalid value warns and reports
// not-ok so the file/default value stands: a typo in an env var must not abort
// startup, and validate() still rejects resolved values that are unusable.
func envInt(name string) (int, bool) {
	v := os.Getenv(name)
	if v == "" {
		return 0, false
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		log.Printf("[config] invalid %s=%q, ignoring (must be an integer)", name, v)
		return 0, false
	}
	return n, true
}

// applyEnvOverrides lets a few environment variables override file values, so
// the same kaas.toml works in a container without baking deployment topology,
// secrets, or tuning knobs into it. A set-but-empty var is treated as unset
// (no clobbering). Used by docker-compose to point the backend at the AI
// service (ai:8081), to inject the LLM key without writing it to disk, and to
// retune worker concurrency without rebuilding the image.
func applyEnvOverrides(c *Config) error {
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
	if n, ok := envInt("KAAS_WORKER_DOCUMENT_WORKERS"); ok {
		c.Worker.DocumentWorkers = n
	}
	if n, ok := envInt("KAAS_WORKER_EXTRACT_WORKERS"); ok {
		c.Worker.ExtractWorkers = n
		log.Printf("[config] KAAS_WORKER_EXTRACT_WORKERS is deprecated and will be removed in the next release. " +
			"Use KAAS_WORKER_DOCUMENT_WORKERS or worker.document_workers in kaas.toml instead.")
	}
	if n, ok := envInt("KAAS_AI_DAEMON_CONCURRENCY"); ok {
		c.AI.Daemon.Concurrency = n
	}
	if n, ok := envInt("KAAS_WORKER_PIPELINE_BATCH_MAX_ITEMS"); ok {
		c.Worker.PipelineBatchMaxItems = n
	}
	if n, ok := envInt("KAAS_WORKER_PIPELINE_BATCH_MAX_INFLIGHT"); ok {
		c.Worker.PipelineBatchMaxInflight = n
	}
	if n, ok := envInt("KAAS_WORKER_PIPELINE_BATCH_DEADLINE_SEC"); ok {
		c.Worker.PipelineBatchDeadlineSec = n
	}
	if n, ok := envInt("KAAS_WORKER_INDEX_DEBOUNCE_SEC"); ok {
		c.Worker.IndexDebounceSec = n
	}
	if n, ok := envInt("KAAS_WORKER_INDEX_MAX_STALE_SEC"); ok {
		c.Worker.IndexMaxStaleSec = n
	}
	return nil
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
	if c.Worker.DocumentWorkers > 0 && c.Worker.ExtractWorkers > 0 {
		log.Printf("[config] worker.extract_workers is deprecated and will be removed in the next release; "+
			"both it and worker.document_workers are set, using document_workers=%d.", c.Worker.DocumentWorkers)
	}
	if n := c.Worker.EffectiveDocumentWorkers(); n < 1 {
		return fmt.Errorf("worker.document_workers resolves to %d, must be >= 1", n)
	}
	// A non-positive inflight with batching enabled starves the batcher's
	// semaphore -- every flushed batch would wait on a slot that never frees.
	if c.Worker.PipelineBatchMaxItems > 1 && c.Worker.PipelineBatchMaxInflight < 1 {
		return fmt.Errorf("worker.pipeline_batch_max_inflight must be >= 1 when pipeline_batch_max_items > 1")
	}
	// The deadline is what bounds a wedged daemon call and the shutdown
	// drain; 0 or negative would silently lift both bounds (no
	// DeadlineSeconds, no Go-side call timeout, Close waits forever), so only
	// positive values are accepted. The TOML default tag maps an omitted key
	// to 2400 (go-zero does not substitute an explicitly written 0), so an
	// explicit zero/negative -- file or env -- is rejected here, loudly.
	if c.Worker.PipelineBatchDeadlineSec < 1 {
		return fmt.Errorf("worker.pipeline_batch_deadline_sec must be >= 1, got %d",
			c.Worker.PipelineBatchDeadlineSec)
	}
	if c.Worker.IndexDebounceSec < 0 {
		return fmt.Errorf("worker.index_debounce_sec must be >= 0 (0 disables the debounced index refresher)")
	}
	if c.Worker.IndexMaxStaleSec < 0 {
		return fmt.Errorf("worker.index_max_stale_sec must be >= 0")
	}
	if c.Worker.IndexDebounceSec > 0 && c.Worker.IndexMaxStaleSec > 0 &&
		c.Worker.IndexMaxStaleSec < c.Worker.IndexDebounceSec {
		return fmt.Errorf("worker.index_max_stale_sec (%d) must be 0 (auto) or >= worker.index_debounce_sec (%d)",
			c.Worker.IndexMaxStaleSec, c.Worker.IndexDebounceSec)
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
