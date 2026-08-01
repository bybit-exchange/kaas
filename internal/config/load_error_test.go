package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestLoadReportsUnreadableFile asserts a missing config path fails loudly with
// the offending path in the message, instead of silently starting on defaults.
func TestLoadReportsUnreadableFile(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "nope.toml")
	c, err := Load(missing)
	if err == nil {
		t.Fatal("expected an error for a missing config file")
	}
	if c != nil {
		t.Errorf("config must be nil on error, got %+v", c)
	}
	if !strings.Contains(err.Error(), "load config") || !strings.Contains(err.Error(), missing) {
		t.Errorf("err = %v, want it wrapped with %q and the path", err, "load config")
	}
}

func TestLoadReportsMalformedTOML(t *testing.T) {
	p := writeTOML(t, "not = = toml [[[")
	if _, err := Load(p); err == nil {
		t.Fatal("expected an error for malformed TOML")
	} else if !strings.Contains(err.Error(), "load config") {
		t.Errorf("err = %v, want it wrapped with %q", err, "load config")
	}
}

// TestValidateRejectsIncompleteConfig covers each validate() guard. All of these
// are reachable because an explicit zero in the file bypasses the `default=` tag.
func TestValidateRejectsIncompleteConfig(t *testing.T) {
	tests := []struct {
		name    string
		body    string
		wantMsg string
	}{
		{
			name:    "sqlite without a path",
			body:    "[storage]\ndriver = \"sqlite\"\nsqlite_path = \"\"\nkb_dir = \"/tmp/kb\"\n",
			wantMsg: "storage.sqlite_path must be set when driver=sqlite",
		},
		{
			name:    "mysql without a dsn",
			body:    "[storage]\ndriver = \"mysql\"\nkb_dir = \"/tmp/kb\"\n",
			wantMsg: "storage.mysql_dsn must be set when driver=mysql",
		},
		{
			name:    "unknown driver",
			body:    "[storage]\ndriver = \"postgres\"\n",
			wantMsg: `storage.driver must be "sqlite" or "mysql", got "postgres"`,
		},
		{
			name:    "empty kb_dir",
			body:    "[storage]\ndriver = \"sqlite\"\nsqlite_path = \"/tmp/x.db\"\nkb_dir = \"\"\n",
			wantMsg: "storage.kb_dir must be set",
		},
		{
			name:    "non-positive lease timeout",
			body:    "[storage]\ndriver = \"sqlite\"\nkb_dir = \"/tmp/kb\"\n\n[worker]\nlease_timeout_sec = 0\n",
			wantMsg: "worker.lease_timeout_sec must be > 0",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := Load(writeTOML(t, tc.body))
			if err == nil {
				t.Fatalf("expected an error for %s", tc.name)
			}
			if err.Error() != tc.wantMsg {
				t.Errorf("err = %q, want %q", err.Error(), tc.wantMsg)
			}
		})
	}
}

// TestLoadMySQLDriver asserts the mysql driver passes validation (the backend
// itself is still a stub, rejected later at store construction).
func TestLoadMySQLDriver(t *testing.T) {
	c, err := Load(writeTOML(t, `
[storage]
driver = "mysql"
mysql_dsn = "user:pw@tcp(db:3306)/kaas"
kb_dir = "/tmp/kb"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Storage.Driver != "mysql" || c.Storage.MySQLDSN != "user:pw@tcp(db:3306)/kaas" {
		t.Errorf("storage = %+v, want the mysql values", c.Storage)
	}
}

// TestMCPEnvOverrides covers the native-MCP switches: only "true" and "1" enable
// the endpoint, so a typo cannot accidentally expose it.
func TestMCPEnvOverrides(t *testing.T) {
	tests := []struct {
		env         string
		wantEnabled bool
	}{
		{"true", true},
		{"1", true},
		{"false", false},
		{"yes", false},
		{"TRUE", false},
		{"", false},
	}
	for _, tc := range tests {
		t.Run("KAAS_MCP_ENABLED="+tc.env, func(t *testing.T) {
			t.Setenv("KAAS_MCP_ENABLED", tc.env)
			c, err := Load(writeTOML(t, "[storage]\ndriver = \"sqlite\"\n"))
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if c.AI.MCP.Enabled != tc.wantEnabled {
				t.Errorf("mcp.enabled = %v, want %v", c.AI.MCP.Enabled, tc.wantEnabled)
			}
		})
	}
}

// TestMCPEnvCannotDisableFileValue documents the override direction: the env var
// can only turn MCP on, never off (a file-enabled endpoint stays enabled).
func TestMCPEnvCannotDisableFileValue(t *testing.T) {
	t.Setenv("KAAS_MCP_ENABLED", "false")
	c, err := Load(writeTOML(t, `
[storage]
driver = "sqlite"

[ai.mcp]
enabled = true
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !c.AI.MCP.Enabled {
		t.Error("mcp.enabled = false, want the file value to stay enabled")
	}
}

func TestMCPTokenEnvOverride(t *testing.T) {
	t.Setenv("KAAS_MCP_TOKEN", "tok-env")
	c, err := Load(writeTOML(t, `
[storage]
driver = "sqlite"

[ai.mcp]
enabled = true
token = "tok-file"
timeout_sec = 45
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.AI.MCP.Token != "tok-env" {
		t.Errorf("mcp.token = %q, want the env override", c.AI.MCP.Token)
	}
	if c.AI.MCP.TimeoutSec != 45 {
		t.Errorf("mcp.timeout_sec = %d, want 45", c.AI.MCP.TimeoutSec)
	}
}

// TestResolvePathsAgainstKaasHome asserts relative storage paths are anchored to
// KAAS_HOME when set: the Python daemon runs with a different CWD, so a relative
// path resolved twice would point at two different directories.
func TestResolvePathsAgainstKaasHome(t *testing.T) {
	home := t.TempDir()
	t.Setenv("KAAS_HOME", home)

	c, err := Load(writeTOML(t, `
[storage]
driver = "sqlite"
sqlite_path = "./data/kaas.db"
kb_dir = "data"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if want := filepath.Join(home, "data", "kaas.db"); c.Storage.SQLitePath != want {
		t.Errorf("sqlite_path = %q, want %q", c.Storage.SQLitePath, want)
	}
	if want := filepath.Join(home, "data"); c.Storage.KBDir != want {
		t.Errorf("kb_dir = %q, want %q", c.Storage.KBDir, want)
	}
}

// TestResolvePathsKeepsAbsolutePaths asserts absolute paths are passed through
// untouched, whatever KAAS_HOME says.
func TestResolvePathsKeepsAbsolutePaths(t *testing.T) {
	t.Setenv("KAAS_HOME", t.TempDir())
	c, err := Load(writeTOML(t, `
[storage]
driver = "sqlite"
sqlite_path = "/var/lib/kaas/kaas.db"
kb_dir = "/var/lib/kaas/kb"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.Storage.SQLitePath != "/var/lib/kaas/kaas.db" || c.Storage.KBDir != "/var/lib/kaas/kb" {
		t.Errorf("absolute paths were rewritten: %+v", c.Storage)
	}
}

// TestResolvePathsAgainstCWD asserts CWD is the anchor when KAAS_HOME is unset.
func TestResolvePathsAgainstCWD(t *testing.T) {
	t.Setenv("KAAS_HOME", "")
	dir := t.TempDir()
	t.Chdir(dir)
	// t.TempDir may hand back a symlinked path (/var vs /private/var on macOS);
	// compare against what the process actually reports as its CWD.
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatalf("Getwd: %v", err)
	}

	c, err := Load(writeTOML(t, `
[storage]
driver = "sqlite"
sqlite_path = "kaas.db"
kb_dir = "kb"
`))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if want := filepath.Join(cwd, "kaas.db"); c.Storage.SQLitePath != want {
		t.Errorf("sqlite_path = %q, want %q", c.Storage.SQLitePath, want)
	}
	if want := filepath.Join(cwd, "kb"); c.Storage.KBDir != want {
		t.Errorf("kb_dir = %q, want %q", c.Storage.KBDir, want)
	}
}
