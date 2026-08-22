package config

import (
	"os"
	"path/filepath"
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
	if c.Worker.ExtractWorkers != 8 || c.Worker.LeaseTimeoutSec != 120 {
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
	if c.Worker.ExtractWorkers != 12 || c.Worker.LeaseTimeoutSec != 300 {
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

// TestDaemonPoolCoversTheWorkerPool guards the pairing between two defaults that
// have to move together. The dispatcher runs ExtractWorkers documents at once,
// but each one occupies a slot in the Python daemon's semaphore
// (internal/bridge/daemon.go), so a daemon pool smaller than the worker pool
// quietly becomes the real limit and raising ExtractWorkers alone buys nothing.
func TestDaemonPoolCoversTheWorkerPool(t *testing.T) {
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
	if c.AI.Daemon.Concurrency < c.Worker.ExtractWorkers {
		t.Fatalf("daemon pool %d is smaller than the worker pool %d, so the daemon "+
			"caps document concurrency instead of the dispatcher",
			c.AI.Daemon.Concurrency, c.Worker.ExtractWorkers)
	}
}
