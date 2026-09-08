# Make Derive `reorganize` a Global Configuration Item

## 1. Background and Goals

### Why
The `reorganize=True` parameter in `py/src/kb_ai/server_daemon.py:_handle_derive()` is hardcoded with a `# TEMP: hardcoded for validation` comment. It needs to be promoted to a configurable item read from the TOML config file so operators can disable it without code changes.

### What we want to achieve
- Add `reorganize` as a config item under a new `[derive]` TOML section, defaulting to `true`
- Thread the value from Go config → derive runner → bridge → daemon JSON payload → `derive_kb()` call
- Remove the hardcoded `reorganize=True` in `server_daemon.py`
- Support env-var override (`KAAS_DERIVE_REORGANIZE`) following the existing pattern

### Scope
- **In scope**: TOML config, Go config struct, bridge payload, Python daemon handler, tests
- **Out of scope**: API changes, DB migration, frontend changes, CLI `derive` command (keeps its own `reorganize=False` default via the `derive_kb()` function signature)

## 2. Current State Analysis

### Config system
- `etc/kaas.toml` → `config.Load()` → `Config` struct → `applyEnvOverrides()` → `applyDefaults()` → `validate()` → `resolvePaths()`
- **No `[derive]` section exists today.** No `DeriveConf` struct. The derive runner's `Config` is populated ad-hoc from `cfg.Storage.KBDir`, `cfg.LLM.Model`, `cfg.Worker.PollIntervalMS` in `cmd/kaas/main.go:312-316`.

### Data flow for derive
```
etc/kaas.toml → config.Load() → Config → derive.Config (wired in main.go)
    → derive.Runner.process() → bridge.DaemonClient.Derive(DeriveRequest)
    → JSON over stdin → Python _handle_derive() → derive_kb(reorganize=???)
```

### The hardcoded line
`py/src/kb_ai/server_daemon.py:409`:
```python
reorganize=True,  # TEMP: hardcoded for validation
```

### Existing `DeriveRequest` (no `Reorganize` field)
```go
type DeriveRequest struct {
    KBDir      string `json:"kb_dir"`
    Topic      string `json:"topic"`
    Slug       string `json:"slug,omitempty"`
    Force      bool   `json:"force,omitempty"`
    Model      string `json:"model,omitempty"`
    SelectFrom string `json:"select_from,omitempty"`
}
```

### Key constraints
1. go-zero's `default=` tag only works for strings/numbers; for booleans, `default=true` **does** work in go-zero since it parses the tag as `strconv.ParseBool`. A plain `bool` field with `default=true` is sufficient.
2. The bridge payload uses `*bool` + `omitempty` for fields where the distinction between "unset" and "false" matters (see `PipelineRequest.RebuildIndex`, `ChatRequest.Temperature`). For `Reorganize`, this distinction **does** matter on the wire: the Python side needs to tell `true` from `false` from absent, because `derive_kb()` defaults to `False`. Using `*bool` ensures an explicit `false` is serialized rather than silently dropped by `omitempty`.
3. No `boolPtr` helper exists anywhere in the codebase — it must be added in test files that need it.
4. No test in `py/tests/test_server_daemon.py` currently asserts `reorganize` in any form. The existing `test_derive_command_dispatches_to_derive_kb` captures kwargs via `seen.update(kw)` but never checks `reorganize`.

## 3. Technical Design

### Architecture decisions

**Decision 1: New `[derive]` section in TOML (not under `[llm]`)**
Rationale: `reorganize` is a derive behavior, not an LLM setting. A dedicated `[derive]` section is cleaner and provides a home for future derive-specific config (e.g., timeout, concurrency).

**Decision 2: Plain `bool` with `default=true` in the Go config struct**
The config struct uses `bool` with go-zero's `default=true` tag. This is the simplest approach: when the `[derive]` section is omitted, the field defaults to `true`. The config system needs no `*bool` or `applyDefaults()` logic for this field.

**Decision 3: `*bool` on the bridge `DeriveRequest`**
On the wire, the field must be `*bool` with `json:"reorganize,omitempty"` so that:
- An explicit `true` is sent as `"reorganize": true`
- An explicit `false` is sent as `"reorganize": false`
- The Go runner always sets it (from config), so `nil` never occurs in practice, but using `*bool` follows the established pattern (`RebuildIndex`, `IncludeSources`)

**Decision 4: Forward via per-call payload (not init/env)**
Following `select_from`'s pattern: the value is forwarded in the derive command's JSON payload. This is more explicit than the init/env path and allows per-job override in the future without changing the protocol.

**Decision 5: Env override `KAAS_DERIVE_REORGANIZE`**
Following the existing pattern. Accepted values: `"true"`, `"1"` → true; `"false"`, `"0"` → false; anything else → warn and fall back. Empty string → no override.

### Data flow (after change)
```
etc/kaas.toml [derive] reorganize = true
    → config.DeriveConf.Reorganize (bool, default=true)
    → env override KAAS_DERIVE_REORGANIZE
    → derive.Config.Reorganize (bool)
    → bridge.DeriveRequest.Reorganize (*bool)
    → JSON {"reorganize": true}
    → Python inner.get("reorganize", True) → derive_kb(reorganize=...)
```

## 4. Interface Contracts

### 4.1 Go Config Struct — `DeriveConf`

**File**: `internal/config/config.go`

```go
// DeriveConf configures knowledge-base derive behavior.
type DeriveConf struct {
    // Reorganize controls whether the reorganize phase runs before compile in
    // derive jobs. When true, the engine produces an aggregation plan that
    // groups related extractions. Defaults to true.
    Reorganize bool `json:"reorganize,default=true"`
}
```

Added to the root `Config`:
```go
type Config struct {
    Server  ServerConf  `json:"server"`
    Storage StorageConf `json:"storage"`
    Worker  WorkerConf  `json:"worker"`
    AI      AIConf      `json:"ai"`
    LLM     LLMConf     `json:"llm"`
    Derive  DeriveConf  `json:"derive"`    // ← new
    Upload  UploadConf  `json:"upload"`
    Log     LogConf     `json:"log"`
}
```

**Behavior**:
- When `[derive]` is absent from TOML: `Reorganize` defaults to `true` (via go-zero `default=true` tag)
- When `[derive]` is present with `reorganize = false`: `Reorganize` is `false`
- When env `KAAS_DERIVE_REORGANIZE` is `"true"` or `"1"`: overrides to `true`
- When env `KAAS_DERIVE_REORGANIZE` is `"false"` or `"0"`: overrides to `false`
- When env `KAAS_DERIVE_REORGANIZE` is any other non-empty string: warn and ignore (file/default value stands)

### 4.2 Derive Runner Config

**File**: `internal/derive/runner.go`

```go
type Config struct {
    KBDir        string
    Model        string
    PollInterval time.Duration
    Timeout      time.Duration
    Reorganize   bool          // ← new, forwarded to every DeriveRequest
}
```

### 4.3 Bridge `DeriveRequest` — Wire Format

**File**: `internal/bridge/api.go`

```go
type DeriveRequest struct {
    KBDir      string `json:"kb_dir"`
    Topic      string `json:"topic"`
    Slug       string `json:"slug,omitempty"`
    Force      bool   `json:"force,omitempty"`
    Model      string `json:"model,omitempty"`
    SelectFrom string `json:"select_from,omitempty"`
    // Reorganize controls whether the reorganize phase runs before compile.
    // Pointer so an explicit false is serialized rather than dropped by omitempty.
    // The runner always sets it from config; nil is never sent in practice.
    Reorganize *bool  `json:"reorganize,omitempty"` // ← new
}
```

**JSON on the wire (Go → Python)**:
```json
{
  "kb_dir": "/data",
  "topic": "pricing",
  "slug": "pricing",
  "force": false,
  "model": "gpt-4o",
  "select_from": "articles",
  "reorganize": true
}
```

When `Reorganize` is `nil` (should not happen in practice), the `reorganize` key is absent from the JSON, and the Python side falls back to `True`.

When `Reorganize` is a pointer to `false`, the JSON contains `"reorganize": false`.

### 4.4 Python Daemon — Payload Consumption

**File**: `py/src/kb_ai/server_daemon.py`

The `_handle_derive()` function reads:
```python
reorganize = inner.get("reorganize", True)
```

- Key present, value `true` → `reorganize=True`
- Key present, value `false` → `reorganize=False`
- Key absent → defaults to `True` (backward compat: old Go binary without the field)

### 4.5 TOML Config File

**File**: `etc/kaas.toml`

New section added between `[llm]` and `[log]`:
```toml
[derive]
# Whether the reorganize phase runs before compile in derive jobs. When true,
# the engine produces an aggregation plan that groups related extractions
# before writing articles. Override with KAAS_DERIVE_REORGANIZE.
reorganize = true
```

## 5. Implementation Steps

### Step 1: Add `DeriveConf` to the Go config struct
**File**: `internal/config/config.go`

1. Define `DeriveConf` struct with `Reorganize bool` field and `json:"reorganize,default=true"` tag.
2. Add `Derive DeriveConf` field to `Config` struct with `json:"derive"` tag.
3. Add env override in `applyEnvOverrides()`:
   ```go
   if v := os.Getenv("KAAS_DERIVE_REORGANIZE"); v != "" {
       switch strings.ToLower(v) {
       case "true", "1":
           c.Derive.Reorganize = true
       case "false", "0":
           c.Derive.Reorganize = false
       default:
           log.Printf("[config] invalid KAAS_DERIVE_REORGANIZE=%q, ignoring (must be true/false/1/0)", v)
       }
   }
   ```
4. No changes needed in `applyDefaults()` or `validate()` — the `default=true` tag handles the default, and a boolean has no invalid states.

**Depends on**: nothing

### Step 2: Add `[derive]` section to the TOML file
**File**: `etc/kaas.toml`

Add the `[derive]` section with `reorganize = true` between the `[llm]` section and the `[log]` section, with a doc comment explaining the setting and the env override.

**Depends on**: nothing (but conceptually paired with Step 1)

### Step 3: Add `Reorganize *bool` to `DeriveRequest`
**File**: `internal/bridge/api.go`

Add `Reorganize *bool \`json:"reorganize,omitempty"\`` to the `DeriveRequest` struct.

**Depends on**: nothing

### Step 4: Add `Reorganize bool` to `derive.Config` and forward it
**File**: `internal/derive/runner.go`

1. Add `Reorganize bool` field to `Config`.
2. In `process()`, when constructing the `bridge.DeriveRequest`, set `Reorganize`:
   ```go
   reorg := r.cfg.Reorganize
   resp, err := r.br.Derive(callCtx, bridge.DeriveRequest{
       KBDir:      r.cfg.KBDir,
       Topic:      job.Topic,
       Slug:       job.Slug,
       Force:      r.replaceable(job.Slug),
       Model:      model,
       SelectFrom: job.SelectFrom,
       Reorganize: &reorg,
   })
   ```

**Depends on**: Step 3

### Step 5: Wire config to derive runner in `main.go`
**File**: `cmd/kaas/main.go`

Update the `derive.Config` construction (~line 312-316) to include `Reorganize`:
```go
deriveRunner = derive.NewRunner(js, dc, derive.Config{
    KBDir:        cfg.Storage.KBDir,
    Model:        cfg.LLM.Model,
    PollInterval: time.Duration(cfg.Worker.PollIntervalMS) * time.Millisecond,
    Reorganize:   cfg.Derive.Reorganize,
}, logger)
```

**Depends on**: Steps 1, 4

### Step 6: Remove hardcoded `reorganize=True` in Python daemon
**File**: `py/src/kb_ai/server_daemon.py`

In `_handle_derive()`, replace:
```python
reorganize=True,  # TEMP: hardcoded for validation
```
with:
```python
reorganize=inner.get("reorganize", True),
```

**Depends on**: nothing (can be done independently; backward-compatible because absent key falls back to `True`)

### Step 7: Go tests — config
**File**: `internal/config/config_test.go`

1. **`TestLoadDefaults`**: Add assertion that `c.Derive.Reorganize == true` (the default when `[derive]` is absent from the minimal TOML). This test uses a minimal TOML with only `[storage]` and `[llm]`, so the new `[derive]` section is omitted and the `default=true` tag must fire.

2. **`TestLoadRepoConfig`**: Add assertion that `c.Derive.Reorganize == true` (the value in the committed `etc/kaas.toml`). This test loads the actual repo config file and must pass after Step 2 adds `[derive]`.

3. **`TestLoadFull`**: Add `[derive]` section with `reorganize = false` to the TOML literal and assert `c.Derive.Reorganize == false`. This verifies explicit TOML values override the default.

4. **New test `TestDeriveReorganizeEnvOverride`**: Write a TOML with `[derive] reorganize = false`, set env `KAAS_DERIVE_REORGANIZE=true`, assert `c.Derive.Reorganize == true`. Also test the reverse (`reorganize = true` in file, env `false`), and test that an invalid env value (`"yes"`) warns and falls back to the file value.

5. **New test `TestDeriveReorganizeDefaultTrue`**: Minimal TOML without any `[derive]` section. Assert `c.Derive.Reorganize == true`.

**Depends on**: Steps 1, 2

### Step 8: Go tests — bridge
**File**: `internal/bridge/daemon_client_test.go`

1. **`TestDeriveMarshalsTheRequestAndDecodesTheResponse`**: Add `Reorganize: boolPtr(true)` to the `DeriveRequest` and assert `sent.Reorganize != nil && *sent.Reorganize == true` on the deserialized payload.

2. **New test `TestDeriveCarriesExplicitFalseReorganize`**: Send `DeriveRequest` with `Reorganize: boolPtr(false)`, unmarshal the payload, assert `sent.Reorganize != nil && *sent.Reorganize == false`. This pins the `*bool` + `omitempty` behavior — an explicit `false` must appear on the wire.

3. **New test `TestDeriveOmitsNilReorganize`**: Send `DeriveRequest` with `Reorganize: nil`, unmarshal to `map[string]any`, assert the `"reorganize"` key is absent. This tests backward compat with a hypothetical old code path.

4. **Helper function**: Add `boolPtr(b bool) *bool` helper at the top of the test file (it does not exist anywhere in the codebase):
   ```go
   func boolPtr(b bool) *bool { return &b }
   ```

**Depends on**: Step 3

### Step 9: Go tests — derive runner
**File**: `internal/derive/runner_test.go`

1. **`TestRunnerRunsAPendingJobToSuccess`**: Update the `Config` in `runOnce` calls to include `Reorganize: true` where appropriate, and add an assertion that `br.req.Reorganize != nil && *br.req.Reorganize == true`.

2. **New test `TestRunnerForwardsReorganizeFalse`**: Create a runner with `Config{..., Reorganize: false}`, run a job, assert `br.req.Reorganize != nil && *br.req.Reorganize == false`.

3. Note: The `runOnce` / `runOnceIn` helpers construct `Config` with `KBDir` and `Model`. The new `Reorganize` field defaults to `false` (Go zero value), so existing tests where `Reorganize` is not set will send `false`. Either:
   - Update `runOnce`/`runOnceIn` to set `Reorganize: true` (matching the production default), or
   - Accept that existing tests assert the behavior with `Reorganize=false` (which is fine — they test request forwarding, not the config default).

   Recommended: leave existing tests as-is (they test other concerns) and add the dedicated test from point 2.

**Depends on**: Steps 3, 4

### Step 10: Python tests — daemon
**File**: `py/tests/test_server_daemon.py`

1. **`test_derive_command_dispatches_to_derive_kb`**: Add `"reorganize": True` to the payload dict, and add assertion `assert seen["reorganize"] is True`.

2. **New test `test_derive_command_passes_reorganize_false`**: Send `"reorganize": false` in the payload, assert `seen["reorganize"] is False`.

3. **New test `test_derive_command_defaults_reorganize_to_true`**: Send a payload without `"reorganize"` key, assert `seen["reorganize"] is True`. This pins the backward-compatibility default.

**Depends on**: Step 6

## 6. Risks and Mitigations

### Risk 1: go-zero `default=true` on a bool field
**Concern**: go-zero's `default=` tag is well-tested for strings and ints but less commonly used for bools. If it silently ignores the tag, the field defaults to `false` (Go zero value).
**Mitigation**: `TestDeriveReorganizeDefaultTrue` (Step 7.5) explicitly tests this. If the test fails, fall back to applying the default in `applyDefaults()`:
```go
func applyDefaults(c *Config) {
    // ... existing ...
    // go-zero's default=true handles this; this is a safety net.
    // Uncomment only if default=true does not work for bool fields.
    // if !c.Derive.Reorganize { c.Derive.Reorganize = true }
}
```
However, the above fallback cannot distinguish "explicitly set to false" from "omitted and defaulted to false", so the real fix would require `*bool` in the config struct. We do NOT use `*bool` in the config struct because go-zero's `default=true` tag is verified to work with plain `bool` (it uses `strconv.ParseBool` internally). If the test fails, switch the config struct to `*bool` and add `applyDefaults` logic:
```go
// DeriveConf — fallback approach only if go-zero default=true doesn't work for bool
type DeriveConf struct {
    Reorganize *bool `json:"reorganize,optional"`
}
// applyDefaults
if c.Derive.Reorganize == nil {
    t := true
    c.Derive.Reorganize = &t
}
```

### Risk 2: Existing tests break due to new config field
**Concern**: `TestLoadRepoConfig` loads `etc/kaas.toml` and will fail if `[derive]` is added to the TOML but `DeriveConf` is not in the struct (or vice versa, if go-zero rejects unknown keys — but it doesn't; `TestLoadIgnoresUnknownWorkerKeys` confirms this). `TestLoadDefaults` uses a minimal TOML without `[derive]` and should still pass because of the `default=true` tag.
**Mitigation**: Steps 2 and 7 are always deployed together. The explicit test assertions in Step 7 verify both paths.

### Risk 3: Omitted `reorganize` key on the wire
**Concern**: If Go code constructs a `DeriveRequest` without setting `Reorganize` (e.g., a test or future code path), the `*bool` is `nil`, and `omitempty` drops the key. The Python side then defaults to `True` via `inner.get("reorganize", True)`, which matches the config default but silently hides the omission.
**Mitigation**: Acceptable behavior — the Python default matches the intended system default. The runner always sets the pointer from config, so `nil` only occurs in test code or future code that forgets. The `TestDeriveOmitsNilReorganize` test documents this contract.

### Risk 4: Env override for bool is a new pattern
**Concern**: The existing `applyEnvOverrides()` only handles strings and ints (via `envInt()`). There is no `envBool()` helper. The inline `switch` in Step 1 is a new pattern.
**Mitigation**: The inline switch is small (6 lines) and self-contained. If more bool env overrides are needed later, extract an `envBool()` helper. For now, one inline switch is simpler than a new helper for a single use.
