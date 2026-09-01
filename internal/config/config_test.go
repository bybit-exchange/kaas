package config

import (
	"bytes"
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeTOML(t *testing.T, body string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "kaas.toml")
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatalf("write toml: %v", err)
	}
	return p
}

// TestLoadFull confirms explicit TOML values map onto the struct.
func TestLoadFull(t *testing.T) {
	p := writeTOML(t, `
[server]
host = "127.0.0.1"
port = 9090

[storage]
driver = "sqlite"
sqlite_path = "/tmp/x.db"
kb_dir = "/tmp/kb"

[worker]
extract_workers = 8
pipeline_concurrency = 3
poll_interval_ms = 500
lease_timeout_sec = 120

[ai]
mcp_url = "http://ai-mcp:8082"

[llm]
api_key = "sk-test"
base_url = "https://example.com/v1"
model = "gpt-4o"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Server.Port != 9090 || c.Server.Host != "127.0.0.1" {
		t.Fatalf("server: %+v", c.Server)
	}
	if c.AI.MCPURL != "http://ai-mcp:8082" {
		t.Fatalf("ai mcp_url: %+v", c.AI)
	}
	if c.Storage.SQLitePath != "/tmp/x.db" || c.Storage.KBDir != "/tmp/kb" {
		t.Fatalf("storage: %+v", c.Storage)
	}
	if c.Worker.ExtractWorkers != 8 || c.Worker.EffectiveDocumentWorkers() != 8 || c.Worker.LeaseTimeoutSec != 120 {
		t.Fatalf("worker: %+v", c.Worker)
	}
	if c.LLM.APIKey != "sk-test" || c.LLM.Model != "gpt-4o" {
		t.Fatalf("llm: %+v", c.LLM)
	}
}

// TestLoadDefaults confirms the go-zero `default=` tags fill omitted fields.
func TestLoadDefaults(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Server.Host != "0.0.0.0" || c.Server.Port != 8080 {
		t.Fatalf("server defaults not applied: %+v", c.Server)
	}
	// resolvePaths converts relative defaults to absolute; verify they end with
	// the expected suffixes and are absolute.
	if !filepath.IsAbs(c.Storage.SQLitePath) || filepath.Base(c.Storage.SQLitePath) != "kaas.db" {
		t.Fatalf("storage.sqlite_path not resolved to absolute: %q", c.Storage.SQLitePath)
	}
	if !filepath.IsAbs(c.Storage.KBDir) || filepath.Base(c.Storage.KBDir) != "data" {
		t.Fatalf("storage.kb_dir not resolved to absolute: %q", c.Storage.KBDir)
	}
	if c.Worker.EffectiveDocumentWorkers() != 4 || c.Worker.LeaseTimeoutSec != 300 {
		t.Fatalf("worker defaults not applied: %+v", c.Worker)
	}
	if c.AI.MCPURL != "" {
		t.Fatalf("ai mcp_url should default empty (proxy disabled): %+v", c.AI)
	}
	if c.Worker.CBFailureThreshold != 5 || c.Worker.CBCooldownSec != 30 {
		t.Fatalf("worker cb defaults not applied: %+v", c.Worker)
	}
	if c.LLM.BaseURL != "https://api.openai.com/v1" || c.LLM.Model != "gpt-4o-mini" {
		t.Fatalf("llm defaults not applied: %+v", c.LLM)
	}
}

func TestLoadRepoConfig(t *testing.T) {
	// The committed etc/kaas.toml must load cleanly.
	c, err := Load("../../etc/kaas.toml")
	if err != nil {
		t.Fatalf("Load repo config: %v", err)
	}
	if c.Storage.Driver != "sqlite" {
		t.Fatalf("expected sqlite driver, got %q", c.Storage.Driver)
	}
	if c.Worker.EffectiveDocumentWorkers() != 16 {
		t.Errorf("effective document workers = %d, want 16", c.Worker.EffectiveDocumentWorkers())
	}
	if c.AI.Daemon.Concurrency != 16 {
		t.Errorf("daemon concurrency = %d, want 16", c.AI.Daemon.Concurrency)
	}
	if c.Worker.PipelineConcurrency != 8 {
		t.Errorf("pipeline concurrency = %d, want 8", c.Worker.PipelineConcurrency)
	}
	if c.Worker.PipelineBatchMaxItems != 16 || c.Worker.PipelineBatchFlushMS != 2000 || c.Worker.PipelineBatchMaxInflight != 2 {
		t.Errorf("pipeline batch keys = %d/%d/%d, want 16/2000/2",
			c.Worker.PipelineBatchMaxItems, c.Worker.PipelineBatchFlushMS, c.Worker.PipelineBatchMaxInflight)
	}
	if c.Worker.IndexDebounceSec != 30 || c.Worker.IndexMaxStaleSec != 300 {
		t.Errorf("index refresh keys = %d/%d, want 30/300",
			c.Worker.IndexDebounceSec, c.Worker.IndexMaxStaleSec)
	}
}

// TestEnvOverrides confirms env vars override file values, and that a
// set-but-empty var does not clobber the configured value.
func TestEnvOverrides(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk-file"
base_url = "https://file.example/v1"
model = "gpt-file"
`)
	t.Setenv("KAAS_AI_MCP_URL", "http://ai-mcp:8082")
	t.Setenv("KAAS_WEB_DIR", "/app/web/dist")
	t.Setenv("LLM_API_KEY", "sk-env")
	t.Setenv("LLM_MODEL", "gpt-env")
	t.Setenv("LLM_BASE_URL", "") // set-but-empty must not clobber

	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.AI.MCPURL != "http://ai-mcp:8082" {
		t.Errorf("mcp_url = %q, want env override", c.AI.MCPURL)
	}
	if c.Server.WebDir != "/app/web/dist" {
		t.Errorf("web_dir = %q, want env override", c.Server.WebDir)
	}
	if c.LLM.APIKey != "sk-env" {
		t.Errorf("api_key = %q, want env override", c.LLM.APIKey)
	}
	if c.LLM.Model != "gpt-env" {
		t.Errorf("model = %q, want env override", c.LLM.Model)
	}
	if c.LLM.BaseURL != "https://file.example/v1" {
		t.Errorf("base_url = %q, empty env must not clobber file value", c.LLM.BaseURL)
	}
}

func TestSummarizeModelExplicit(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
summarize_model = "gpt-4o-mini"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.SummarizeModel != "gpt-4o-mini" {
		t.Errorf("summarize_model = %q, want %q", c.LLM.SummarizeModel, "gpt-4o-mini")
	}
}

func TestSummarizeModelFallback(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.SummarizeModel != "gpt-4o" {
		t.Errorf("summarize_model = %q, want fallback to model %q", c.LLM.SummarizeModel, "gpt-4o")
	}
}

func TestSummarizeModelEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
summarize_model = "from-file"
`)
	t.Setenv("LLM_SUMMARIZE_MODEL", "from-env")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.SummarizeModel != "from-env" {
		t.Errorf("summarize_model = %q, want env override %q", c.LLM.SummarizeModel, "from-env")
	}
}

func TestValidateBadDriver(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "postgres"
`)
	if _, err := Load(p); err == nil {
		t.Fatalf("expected error for unknown driver")
	}
}

func TestValidateMySQLNeedsDSN(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "mysql"
`)
	if _, err := Load(p); err == nil {
		t.Fatalf("expected error for mysql without dsn")
	}
}

func TestExtractStrategyDefaultsToChunked(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.ExtractStrategy != "chunked" {
		t.Errorf("extract_strategy = %q, want %q", c.LLM.ExtractStrategy, "chunked")
	}
}

func TestExtractStrategyFromFile(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
extract_strategy = "auto"
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.ExtractStrategy != "auto" {
		t.Errorf("extract_strategy = %q, want %q", c.LLM.ExtractStrategy, "auto")
	}
}

func TestExtractStrategyEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
extract_strategy = "chunked"
`)
	t.Setenv("LLM_EXTRACT_STRATEGY", "summarize")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLM.ExtractStrategy != "summarize" {
		t.Errorf("extract_strategy = %q, want %q", c.LLM.ExtractStrategy, "summarize")
	}
}

// An unknown strategy fails at load rather than at extract time: the engine would
// refuse it once per document, after the scan, and a typo in a deployment's
// configuration is worth catching before the process starts serving.
func TestUnknownExtractStrategyIsRejected(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[llm]
api_key = "sk"
model = "gpt-4o"
extract_strategy = "Chunked"
`)
	if _, err := Load(p); err == nil {
		t.Fatal("expected Load to reject an unknown extract_strategy")
	}
}

// TestEffectiveDocumentWorkersAliasPriority locks the document_workers >
// extract_workers > default resolution, including the compatibility contract
// that a legacy config file keeps loading unchanged.
func TestEffectiveDocumentWorkersAliasPriority(t *testing.T) {
	cases := []struct {
		name       string
		workerTOML string
		want       int
		wantDeprec bool
	}{
		{
			name:       "legacy file with extract_workers only",
			workerTOML: "extract_workers = 16",
			want:       16,
		},
		{
			name:       "document_workers only",
			workerTOML: "document_workers = 12",
			want:       12,
		},
		{
			name:       "both set: document_workers wins",
			workerTOML: "document_workers = 12\nextract_workers = 8",
			want:       12,
			wantDeprec: true,
		},
		{
			name:       "neither set: built-in default",
			workerTOML: "",
			want:       4,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			// Neutralize host env so the case under test is the only input.
			t.Setenv("KAAS_WORKER_DOCUMENT_WORKERS", "")
			t.Setenv("KAAS_WORKER_EXTRACT_WORKERS", "")
			t.Setenv("KAAS_AI_MCP_URL", "")

			p := writeTOML(t, "[storage]\ndriver = \"sqlite\"\n\n[worker]\n"+tc.workerTOML+"\n")
			var logs bytes.Buffer
			log.SetOutput(&logs)
			defer log.SetOutput(os.Stderr)

			c, err := Load(p)
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if got := c.Worker.EffectiveDocumentWorkers(); got != tc.want {
				t.Errorf("EffectiveDocumentWorkers() = %d, want %d", got, tc.want)
			}
			if tc.wantDeprec && !strings.Contains(logs.String(), "extract_workers is deprecated") {
				t.Errorf("missing deprecation warning; logs: %q", logs.String())
			}
			if !tc.wantDeprec && strings.Contains(logs.String(), "deprecated") {
				t.Errorf("unexpected deprecation warning; logs: %q", logs.String())
			}
		})
	}
}

// TestWorkerConcurrencyEnvOverrides confirms the Docker tuning knobs retune
// concurrency without an image rebuild.
func TestWorkerConcurrencyEnvOverrides(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
document_workers = 16

[ai.daemon]
concurrency = 16
`)
	t.Setenv("KAAS_WORKER_DOCUMENT_WORKERS", "8")
	t.Setenv("KAAS_AI_DAEMON_CONCURRENCY", "8")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got := c.Worker.EffectiveDocumentWorkers(); got != 8 {
		t.Errorf("effective document workers = %d, want env override 8", got)
	}
	if c.AI.Daemon.Concurrency != 8 {
		t.Errorf("daemon concurrency = %d, want env override 8", c.AI.Daemon.Concurrency)
	}
}

// TestExtractWorkersEnvOverride confirms the deprecated env alias still tunes
// concurrency for deployments carrying the old name, with a warning.
func TestExtractWorkersEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"
`)
	t.Setenv("KAAS_WORKER_EXTRACT_WORKERS", "6")
	var logs bytes.Buffer
	log.SetOutput(&logs)
	defer log.SetOutput(os.Stderr)

	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got := c.Worker.EffectiveDocumentWorkers(); got != 6 {
		t.Errorf("effective document workers = %d, want env override 6", got)
	}
	if !strings.Contains(logs.String(), "KAAS_WORKER_EXTRACT_WORKERS is deprecated") {
		t.Errorf("missing deprecation warning for KAAS_WORKER_EXTRACT_WORKERS; logs: %q", logs.String())
	}
}

// TestInvalidWorkerConcurrencyRejected confirms a mistuned concurrency knob
// fails at startup rather than degrading silently. Non-integer env values are
// different: envInt warns and falls back (TestInvalidIntEnvFallsBackToConfig);
// values that parse but resolve unusable are validate()'s to reject.
func TestInvalidWorkerConcurrencyRejected(t *testing.T) {
	cases := []struct {
		name string
		toml string
		env  map[string]string
	}{
		{
			name: "negative document_workers in toml",
			toml: "[storage]\ndriver = \"sqlite\"\n\n[worker]\ndocument_workers = -1\n",
		},
		{
			name: "negative document_workers via env",
			toml: "[storage]\ndriver = \"sqlite\"\n",
			env:  map[string]string{"KAAS_WORKER_DOCUMENT_WORKERS": "-1"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for k, v := range tc.env {
				t.Setenv(k, v)
			}
			p := writeTOML(t, tc.toml)
			if _, err := Load(p); err == nil {
				t.Fatal("expected Load to reject the invalid worker concurrency")
			}
		})
	}
}

// TestInvalidIntEnvFallsBackToConfig confirms a non-integer tuning env var
// warns and falls back to the file value instead of aborting startup
// (mirroring KB_MERGE_FULL_REWRITE_LIMIT handling in the Python write phase).
func TestInvalidIntEnvFallsBackToConfig(t *testing.T) {
	var logs bytes.Buffer
	log.SetOutput(&logs)
	defer log.SetOutput(os.Stderr)

	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
document_workers = 12

[ai.daemon]
concurrency = 6
`)
	t.Setenv("KAAS_WORKER_DOCUMENT_WORKERS", "eight")
	t.Setenv("KAAS_AI_DAEMON_CONCURRENCY", "x")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if got := c.Worker.EffectiveDocumentWorkers(); got != 12 {
		t.Errorf("effective document workers = %d, want toml value 12", got)
	}
	if c.AI.Daemon.Concurrency != 6 {
		t.Errorf("daemon concurrency = %d, want toml value 6", c.AI.Daemon.Concurrency)
	}
	for _, name := range []string{"KAAS_WORKER_DOCUMENT_WORKERS", "KAAS_AI_DAEMON_CONCURRENCY"} {
		if !strings.Contains(logs.String(), "invalid "+name) {
			t.Errorf("missing warning for %s; logs: %q", name, logs.String())
		}
	}
}

// TestLoadIgnoresUnknownWorkerKeys locks the go-zero loader behaviour the
// rename relies on: unknown keys in a newer config file are ignored rather
// than rejected, so an older binary keeps running against an updated TOML.
func TestLoadIgnoresUnknownWorkerKeys(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
document_workers = 4
future_key = 99
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.EffectiveDocumentWorkers() != 4 {
		t.Errorf("effective document workers = %d, want 4", c.Worker.EffectiveDocumentWorkers())
	}
}

// TestPipelineBatchDefaults confirms omitted batch keys keep the pre-batching
// behaviour (max_items=1 = one call per task).
func TestPipelineBatchDefaults(t *testing.T) {
	p := writeTOML(t, "[storage]\ndriver = \"sqlite\"\n")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.PipelineBatchMaxItems != 1 || c.Worker.PipelineBatchFlushMS != 500 || c.Worker.PipelineBatchMaxInflight != 1 {
		t.Fatalf("pipeline batch defaults = %d/%d/%d, want 1/500/1",
			c.Worker.PipelineBatchMaxItems, c.Worker.PipelineBatchFlushMS, c.Worker.PipelineBatchMaxInflight)
	}
}

// TestPipelineBatchFromFile confirms explicit TOML values map onto the struct.
func TestPipelineBatchFromFile(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
pipeline_batch_max_items = 16
pipeline_batch_flush_ms = 2000
pipeline_batch_max_inflight = 2
`)
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.PipelineBatchMaxItems != 16 || c.Worker.PipelineBatchFlushMS != 2000 || c.Worker.PipelineBatchMaxInflight != 2 {
		t.Fatalf("pipeline batch keys = %d/%d/%d, want 16/2000/2",
			c.Worker.PipelineBatchMaxItems, c.Worker.PipelineBatchFlushMS, c.Worker.PipelineBatchMaxInflight)
	}
}

// TestPipelineBatchEnvOverride confirms the batch rollback switch works
// without an image rebuild, and that a non-integer value warns and falls
// back to the file value rather than aborting startup.
func TestPipelineBatchEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
pipeline_batch_max_items = 16
`)
	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_ITEMS", "1") // rollback value
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.PipelineBatchMaxItems != 1 {
		t.Errorf("pipeline_batch_max_items = %d, want env override 1", c.Worker.PipelineBatchMaxItems)
	}

	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_ITEMS", "")
	c2, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c2.Worker.PipelineBatchMaxItems != 16 {
		t.Errorf("empty env must not clobber the file value, got %d", c2.Worker.PipelineBatchMaxItems)
	}

	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_ITEMS", "sixteen")
	c3, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c3.Worker.PipelineBatchMaxItems != 16 {
		t.Errorf("invalid env must fall back to the file value, got %d", c3.Worker.PipelineBatchMaxItems)
	}
}

// TestPipelineBatchMaxInflightEnvOverride confirms the inflight cap is
// retunable without an image rebuild: a valid env value wins, a non-integer
// falls back to the file value, and a resolved value < 1 is rejected.
func TestPipelineBatchMaxInflightEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
pipeline_batch_max_items = 16
pipeline_batch_max_inflight = 2
`)
	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_INFLIGHT", "8")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.PipelineBatchMaxInflight != 8 {
		t.Errorf("pipeline_batch_max_inflight = %d, want env override 8", c.Worker.PipelineBatchMaxInflight)
	}

	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_INFLIGHT", "eight")
	c2, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c2.Worker.PipelineBatchMaxInflight != 2 {
		t.Errorf("invalid env must fall back to the file value, got %d", c2.Worker.PipelineBatchMaxInflight)
	}

	t.Setenv("KAAS_WORKER_PIPELINE_BATCH_MAX_INFLIGHT", "0")
	if _, err := Load(p); err == nil {
		t.Fatal("expected Load to reject inflight 0 with batching enabled")
	}
}

// TestIndexRefreshDefaultsOff confirms the index-refresh keys stay disabled
// when omitted (0 = legacy per-call rebuild, the rollback switch).
func TestIndexRefreshDefaultsOff(t *testing.T) {
	p := writeTOML(t, "[storage]\ndriver = \"sqlite\"\n")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.IndexDebounceSec != 0 || c.Worker.IndexMaxStaleSec != 0 {
		t.Fatalf("index refresh keys = %d/%d, want 0/0 (disabled by default)",
			c.Worker.IndexDebounceSec, c.Worker.IndexMaxStaleSec)
	}
}

// TestIndexRefreshFromFile confirms explicit TOML values map onto the struct.
func TestIndexRefreshFromFile(t *testing.T) {
	p := writeTOML(t, "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 30\nindex_max_stale_sec = 300\n")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.IndexDebounceSec != 30 || c.Worker.IndexMaxStaleSec != 300 {
		t.Fatalf("index refresh keys = %d/%d, want 30/300",
			c.Worker.IndexDebounceSec, c.Worker.IndexMaxStaleSec)
	}
}

// TestIndexRefreshEnvOverride confirms the Docker tuning knobs retune index
// refreshing without an image rebuild, and that a non-integer value warns
// and falls back to the file value rather than aborting startup.
func TestIndexRefreshEnvOverride(t *testing.T) {
	p := writeTOML(t, `
[storage]
driver = "sqlite"

[worker]
index_debounce_sec = 30
index_max_stale_sec = 300
`)
	t.Setenv("KAAS_WORKER_INDEX_DEBOUNCE_SEC", "5")
	t.Setenv("KAAS_WORKER_INDEX_MAX_STALE_SEC", "60")
	c, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Worker.IndexDebounceSec != 5 {
		t.Errorf("index_debounce_sec = %d, want env override 5", c.Worker.IndexDebounceSec)
	}
	if c.Worker.IndexMaxStaleSec != 60 {
		t.Errorf("index_max_stale_sec = %d, want env override 60", c.Worker.IndexMaxStaleSec)
	}

	t.Setenv("KAAS_WORKER_INDEX_DEBOUNCE_SEC", "")
	c2, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c2.Worker.IndexDebounceSec != 30 {
		t.Errorf("empty env must not clobber the file value, got %d", c2.Worker.IndexDebounceSec)
	}

	t.Setenv("KAAS_WORKER_INDEX_MAX_STALE_SEC", "soon")
	c3, err := Load(p)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c3.Worker.IndexMaxStaleSec != 300 {
		t.Errorf("invalid env must fall back to the file value, got %d", c3.Worker.IndexMaxStaleSec)
	}
}

// TestIndexRefreshValidation confirms the staleness bound is rejected when
// positive but smaller than the debounce (it would make the throttle fire on
// every drain), while the auto (0) and disabled (debounce 0) combinations
// stay valid.
func TestIndexRefreshValidation(t *testing.T) {
	cases := []struct {
		name     string
		toml     string
		env      map[string]string
		wantLoad bool
	}{
		{
			name:     "max stale below debounce rejected",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 30\nindex_max_stale_sec = 10\n",
			wantLoad: false,
		},
		{
			name:     "max stale below debounce via env rejected",
			toml:     "[storage]\ndriver = \"sqlite\"\n",
			env:      map[string]string{"KAAS_WORKER_INDEX_DEBOUNCE_SEC": "30", "KAAS_WORKER_INDEX_MAX_STALE_SEC": "29"},
			wantLoad: false,
		},
		{
			name:     "equal debounce and max stale accepted",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 30\nindex_max_stale_sec = 30\n",
			wantLoad: true,
		},
		{
			name:     "auto max stale (0) accepted",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 30\n",
			wantLoad: true,
		},
		{
			name:     "refresher off (debounce 0) accepted regardless of max stale",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 0\nindex_max_stale_sec = 300\n",
			wantLoad: true,
		},
		{
			name:     "negative debounce rejected",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = -1\n",
			wantLoad: false,
		},
		{
			name:     "negative max stale rejected",
			toml:     "[storage]\ndriver = \"sqlite\"\n\n[worker]\nindex_debounce_sec = 30\nindex_max_stale_sec = -5\n",
			wantLoad: false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			for k, v := range tc.env {
				t.Setenv(k, v)
			}
			p := writeTOML(t, tc.toml)
			_, err := Load(p)
			if tc.wantLoad && err != nil {
				t.Fatalf("expected Load to succeed, got: %v", err)
			}
			if !tc.wantLoad && err == nil {
				t.Fatal("expected Load to reject the invalid index refresh combination")
			}
		})
	}
}
