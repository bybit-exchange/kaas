//go:build locallm

// This file drives a real four-phase compile — extract, classify, write, index —
// against a locally served model, over documents taken from a real raw corpus.
// It is not part of the default test run: it needs `uv`, an OpenAI-compatible
// server on localhost, and minutes of wall-clock per document.
//
//	make test-locallm
//	go test ./internal/e2e/ -tags locallm -run TestCompile -v -timeout 60m
//
// Every run logs a per-phase latency summary. Point KAAS_LOCALLM_METRICS at a
// .jsonl path to also append the run to a ledger and have it compared against
// earlier runs of the same shape, which is how a slow-down gets noticed rather
// than absorbed — see timing.go.
//
// The cost figures this test logs are zero unless the model has a pricing entry,
// which a locally served one will not have — the engine prints `no pricing entry
// for model ...` and reports 0.00. That is the expected reading here, not a bug;
// set KB_AI_PRICING if the token counts need a price attached. Token counts
// themselves are real, and this test asserts on them.
//
// Every precondition here fails rather than skips. Skipping is right for the
// env-gated daemon tests in internal/bridge, which a broad CI run can trip over
// by accident; the build tag here is already a deliberate opt-in, so "the server
// wasn't up" must not read as a pass.
//
// The same concern shapes the assertions. Three ways a run of this test could go
// green while certifying nothing, each closed deliberately:
//
//   - The engine reuses an extraction already on disk and makes no LLM call at
//     all. Closed by requiring the KB to start empty and by asserting each phase
//     reports a non-zero call and completion-token count.
//   - The compile runs on a different model than the one configured. The
//     extraction file's `extract_model` cannot detect this — the engine records
//     back whatever the request carried (server_daemon.py:168, :293) — so the
//     check that matters asks the server which model it actually loaded.
//   - The index phase does nothing, because the pipeline already wrote the same
//     four index files (pipeline/_entry.py:119-121). Closed by deleting them
//     before the index phase runs.

package e2e

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/frontmatter"
	"gopkg.in/yaml.v2"
)

// What bounds the sample size is not the test's patience but the engine: an
// extract call is capped at 180s (_EXTRACT_CALL_TIMEOUT_S, core/extract.py:30), a
// ceiling tuned for cloud models. A local model that reasons before answering can
// exceed it on a document a cloud model handles easily, and when it does the call
// is retried twice and the phase fails.
//
// Measured against qwen3.8:27b-mlx on an Apple-silicon laptop:
//
//	1.6 KB  → extract 118s, one attempt.               Comfortable.
//	2.7 KB  → extract 349s: timed out once at 180s,    Marginal.
//	          succeeded on the retry.
//	13.5 KB → all three attempts exceed 180s.          Fails.
//
// The default therefore sits at 2 KB, where a call has real headroom under the
// cap, and a two-document run takes about five minutes. Raising
// KAAS_LOCALLM_MAX_DOC_BYTES pushes toward that wall rather than toward a longer
// run: the fix for a timeout is a smaller document, not a larger `-timeout`.
// Raising KAAS_LOCALLM_DOCS is what needs a larger `-timeout`, and the test says
// so rather than dying anonymously.
//
// Read the pass this produces for what it is. 2 KB is the small tail of the
// corpus these numbers came from — 31 of its 1024 documents, against a 23.5 KB
// median — so a green run says the four phases work end to end, NOT that this
// model can compile a typical document. On the numbers above it cannot: at the
// median size every extract attempt would exceed the cap. Sizing a real compile
// is a separate exercise from proving the pipeline runs.
const (
	defaultBaseURL     = "http://127.0.0.1:11434/v1"
	defaultModel       = "qwen3.8:27b-mlx"
	defaultDocs        = 2
	defaultMaxDocBytes = 2 * 1024

	// The engine's per-extract-call ceiling, quoted only to explain the failure;
	// this test does not set it.
	engineExtractCallTimeout = 180 * time.Second

	// Held back from the test's own deadline so a phase that overruns fails
	// inside the test — naming the phase, and running t.Cleanup so the daemon is
	// stopped — instead of being killed by the `go test` timeout, which reports
	// no phase and leaves the `uv run kb-ai daemon` child orphaned.
	cleanupMargin = 2 * time.Minute
)

// The extraction file's body sections, hard-coded rather than read from the
// engine so that renaming a section on the Python side turns this test red.
// These pin the serializer's format only: it emits all six unconditionally, so
// they are not evidence about what the model returned.
var wantExtractionSections = []string{
	"\n## Concepts\n", "\n## Entities\n", "\n## Decisions\n",
	"\n## Action Items\n", "\n## Claims\n", "\n## Enumerations\n",
}

// The index files a compile must leave behind.
var wantIndexFiles = []string{
	"master-index.md", "topic-index.md", "topic-index-longtail.md", "document-index.md",
}

type harnessConfig struct {
	baseURL     string
	apiKey      string
	model       string
	corpus      string
	kbDir       string // empty means a temp dir the test cleans up
	docs        int
	maxDocBytes int64
}

func loadHarnessConfig(t *testing.T) harnessConfig {
	t.Helper()

	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatalf("resolve home dir: %v", err)
	}
	cfg := harnessConfig{
		baseURL: envOr("KAAS_LOCALLM_BASE_URL", defaultBaseURL),
		// Non-empty because the OpenAI client the engine uses rejects an empty
		// key before it ever reaches the local server, which ignores its value.
		apiKey:      envOr("KAAS_LOCALLM_API_KEY", "ollama"),
		model:       envOr("KAAS_LOCALLM_MODEL", defaultModel),
		corpus:      envOr("KAAS_LOCALLM_CORPUS", filepath.Join(home, ".knowledge", "raw")),
		kbDir:       os.Getenv("KAAS_LOCALLM_KB"),
		docs:        envInt(t, "KAAS_LOCALLM_DOCS", defaultDocs),
		maxDocBytes: int64(envInt(t, "KAAS_LOCALLM_MAX_DOC_BYTES", defaultMaxDocBytes)),
	}
	if info, err := os.Stat(cfg.corpus); err != nil {
		t.Fatalf("corpus %q is unreadable: %v\nSet KAAS_LOCALLM_CORPUS to a directory of raw documents.", cfg.corpus, err)
	} else if !info.IsDir() {
		t.Fatalf("corpus %q is not a directory", cfg.corpus)
	}
	return cfg
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(t *testing.T, key string, fallback int) int {
	t.Helper()
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		t.Fatalf("%s=%q is not an integer: %v", key, v, err)
	}
	return n
}

// requireServedModel checks the OpenAI-compatible endpoint lists cfg.model.
// A reachable server that does not serve the requested model is the interesting
// failure: the compile would otherwise run against whatever the server
// substitutes, and the wiki it produced would look fine.
func requireServedModel(t *testing.T, cfg harnessConfig) {
	t.Helper()

	url := strings.TrimSuffix(cfg.baseURL, "/") + "/models"
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("build request for %s: %v", url, err)
	}
	req.Header.Set("Authorization", "Bearer "+cfg.apiKey)

	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		t.Fatalf("no LLM server at %s: %v\nStart one (e.g. `ollama serve`) or point KAAS_LOCALLM_BASE_URL elsewhere.", cfg.baseURL, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("GET %s returned %s, want 200", url, resp.Status)
	}

	var body struct {
		Data []struct{ ID string } `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode %s: %v", url, err)
	}
	served := make([]string, 0, len(body.Data))
	for _, m := range body.Data {
		if m.ID == cfg.model {
			return
		}
		served = append(served, m.ID)
	}
	t.Fatalf("server at %s does not serve model %q; it serves %v\nPull it (e.g. `ollama pull %s`) or set KAAS_LOCALLM_MODEL.",
		cfg.baseURL, cfg.model, served, cfg.model)
}

// assertModelWasLoaded asks the server which models it currently holds in memory
// and requires cfg.model to be among them.
//
// This is the only check here that can actually catch a compile that ran on the
// wrong model, because it is the only one whose answer does not come from a value
// this test supplied. It is best-effort: /api/ps is an ollama route, so against
// another OpenAI-compatible server the check logs that it could not corroborate
// rather than inventing a failure. Call it while the model is still resident —
// ollama unloads after a few idle minutes.
func assertModelWasLoaded(t *testing.T, cfg harnessConfig) {
	t.Helper()

	root := strings.TrimSuffix(strings.TrimSuffix(cfg.baseURL, "/"), "/v1")
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Get(root + "/api/ps")
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Logf("cannot corroborate the model in use: %s/api/ps unavailable (err=%v); "+
			"the compile ran, but nothing independent of this test confirms which model served it", root, err)
		if resp != nil {
			resp.Body.Close()
		}
		return
	}
	defer resp.Body.Close()

	var body struct {
		Models []struct {
			Model string `json:"model"`
		} `json:"models"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Errorf("decode %s/api/ps: %v", root, err)
		return
	}
	loaded := make([]string, 0, len(body.Models))
	for _, m := range body.Models {
		loaded = append(loaded, m.Model)
	}
	if !slices.Contains(loaded, cfg.model) {
		t.Errorf("the server has %v loaded, not %q — the compile did not run on the model under test",
			loaded, cfg.model)
		return
	}
	t.Logf("server confirms %q is the loaded model", cfg.model)
}

// projectRoot walks up from the test's working directory to the module root.
func projectRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find the module root (no go.mod above the test dir)")
		}
		dir = parent
	}
}

// startEngine spawns the real Python AI engine and points it at the local model.
func startEngine(t *testing.T, ctx context.Context, cfg harnessConfig) *bridge.DaemonClient {
	t.Helper()

	if _, err := exec.LookPath("uv"); err != nil {
		t.Fatalf("uv is not on PATH: %v\nThe AI engine runs as `uv run --directory py kb-ai daemon`.", err)
	}
	pyDir := filepath.Join(projectRoot(t), "py")

	client, err := bridge.NewDaemonClient(ctx,
		bridge.DaemonConfig{
			Command: "uv",
			Args:    []string{"run", "--directory", pyDir, "kb-ai", "daemon"},
			// One in-flight request at a time. The point of this harness is a
			// legible phase-by-phase trace against a single local model that
			// would queue the requests anyway.
			Concurrency:      1,
			WarmupTimeoutSec: 120,
			// No restarts: a crash mid-compile must surface as a failure, not be
			// papered over by a fresh process with a cold cache.
			MaxRestarts: 0,
		},
		bridge.LLMConfig{
			APIKey:          cfg.apiKey,
			BaseURL:         cfg.baseURL,
			Model:           cfg.model,
			SummarizeModel:  cfg.model,
			ExtractStrategy: "chunked",
		})
	if err != nil {
		t.Fatalf("start AI engine: %v", err)
	}
	t.Cleanup(client.Stop)
	return client
}

// budgetContext returns a context that expires far enough before the test's own
// deadline for the failure to be reported and the daemon to be stopped.
//
// Derived from t.Deadline() rather than from constants of its own, so the phase
// budget and the `-timeout` the caller passed cannot drift apart. Without a
// -timeout there is no deadline to derive from and the compile runs unbounded,
// which is the caller's stated choice.
func budgetContext(t *testing.T) (context.Context, context.CancelFunc) {
	t.Helper()

	deadline, ok := t.Deadline()
	if !ok {
		t.Log("no -timeout set; the compile will run unbounded")
		return context.WithCancel(context.Background())
	}
	budget := time.Until(deadline) - cleanupMargin
	if budget <= 0 {
		t.Fatalf("the -timeout leaves %s, less than the %s reserved for shutdown; pass a larger -timeout",
			time.Until(deadline).Round(time.Second), cleanupMargin)
	}
	t.Logf("phase budget %s (test deadline minus %s for shutdown)", budget.Round(time.Second), cleanupMargin)
	return context.WithTimeout(context.Background(), budget)
}

// requireEmptyKB refuses to compile into a knowledge base that already holds
// output.
//
// The engine declines to re-extract an extraction whose provenance is still fresh
// and the classify phase has its own on-disk cache, so a second run over a
// populated KB would satisfy every assertion below without making a single LLM
// call. Since KAAS_LOCALLM_KB exists precisely so a KB can be kept and inspected,
// the second run is easy to trigger by accident.
func requireEmptyKB(t *testing.T, kbDir string) {
	t.Helper()

	for _, sub := range []string{"extraction", "wiki", "index"} {
		var found []string
		err := filepath.WalkDir(filepath.Join(kbDir, sub), func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				if errors.Is(err, fs.ErrNotExist) {
					return nil // absent is exactly what we want
				}
				// Anything else -- an unreadable directory, an I/O error -- must not
				// be reported as "empty", because empty is the answer that lets the
				// run proceed, which is what this guard exists to prevent.
				return err
			}
			if !d.IsDir() {
				found = append(found, p)
			}
			return nil
		})
		if err != nil {
			t.Fatalf("inspect %s: %v", sub, err)
		}
		if len(found) > 0 {
			t.Fatalf("%s/%s already holds %d file(s) from an earlier run; the engine would reuse them "+
				"and this test would pass without calling the model.\nPoint KAAS_LOCALLM_KB at a fresh directory.",
				kbDir, sub, len(found))
		}
	}
}

// TestCompileRawCorpusWithLocalModel compiles sampled documents from the raw
// corpus through all four phases and asserts the artifacts each phase owns.
func TestCompileRawCorpusWithLocalModel(t *testing.T) {
	cfg := loadHarnessConfig(t)
	requireServedModel(t, cfg)

	docs, err := Sample(cfg.corpus, SampleOptions{MaxFiles: cfg.docs, MaxBytes: cfg.maxDocBytes})
	if err != nil {
		t.Fatalf("sample corpus: %v", err)
	}
	if len(docs) == 0 {
		t.Fatalf("no document under %d bytes found in %s", cfg.maxDocBytes, cfg.corpus)
	}

	kbDir := cfg.kbDir
	if kbDir == "" {
		kbDir = filepath.Join(t.TempDir(), "kb")
	} else {
		t.Logf("keeping the compiled KB at %s (KAAS_LOCALLM_KB)", kbDir)
	}
	// Before staging, so a KB that is going to be rejected is not written to first.
	requireEmptyKB(t, kbDir)
	if err := Stage(kbDir, cfg.corpus, docs); err != nil {
		t.Fatalf("stage KB: %v", err)
	}

	var staged int64
	for _, d := range docs {
		staged += d.Bytes
		t.Logf("staged %s (%d bytes)", d.Rel, d.Bytes)
	}
	t.Logf("compiling %d document(s), %d bytes total, model %s at %s",
		len(docs), staged, cfg.model, cfg.baseURL)

	ctx, cancel := budgetContext(t)
	defer cancel()

	// Recorded so a run can be compared with earlier ones. Stamped before the
	// engine starts so the record covers the whole run, daemon warmup included.
	run := Record{
		Schema:    1,
		Kind:      "harness",
		StartedAt: time.Now().UTC().Format(time.RFC3339),
		Model:     cfg.model,
		BaseURL:   cfg.baseURL,
		Workers:   1,
		Documents: len(docs),
		RawBytes:  staged,
	}

	client := startEngine(t, ctx, cfg)

	// ── Phase 1: extract ──
	hashes := make(map[string]string, len(docs)) // Doc.Rel -> content hash
	for _, d := range docs {
		sourceRef := "raw/" + d.Rel
		body, err := os.ReadFile(filepath.Join(kbDir, "raw", filepath.FromSlash(d.Rel)))
		if err != nil {
			t.Fatalf("read staged %s: %v", d.Rel, err)
		}
		sum := sha256.Sum256(body)
		hash := hex.EncodeToString(sum[:])
		// Two documents with identical bytes share a hash, and the pipeline keys
		// its per-item results by it. Left undetected, the result-count assertion
		// below would report a mismatch that has nothing to do with the compile.
		for other, h := range hashes {
			if h == hash {
				t.Fatalf("%s and %s have identical content, so the pipeline cannot report them "+
					"separately; adjust KAAS_LOCALLM_DOCS or the corpus", other, d.Rel)
			}
		}
		hashes[d.Rel] = hash

		start := time.Now()
		resp, err := client.Extract(ctx, bridge.ExtractRequest{
			// Content, not FilePath: FilePath routes plain Markdown through the
			// rich-document converter, which is not the path a .md ingest takes.
			Content:        string(body),
			KBDir:          kbDir,
			Source:         sourceRef,
			Model:          cfg.model,
			SummarizeModel: cfg.model,
			Strategy:       "chunked",
		})
		if err != nil {
			// The failure a local model hits first, and it is not obvious from the
			// error text: the engine gives one extract call 180s regardless of how
			// long the model needs, so a document that is merely large fails here
			// while a smaller one from the same corpus compiles fine.
			if elapsed := time.Since(start); elapsed > engineExtractCallTimeout {
				t.Fatalf("extract %s failed after %s: %v\n"+
					"The engine caps a single extract call at %s (_EXTRACT_CALL_TIMEOUT_S, "+
					"py/src/kb_ai/core/extract.py:30) and retries twice. This %d-byte document "+
					"needs longer than that on %s.\nLower KAAS_LOCALLM_MAX_DOC_BYTES (currently %d) "+
					"to sample smaller documents.",
					d.Rel, elapsed.Round(time.Second), err, engineExtractCallTimeout,
					d.Bytes, cfg.model, cfg.maxDocBytes)
			}
			t.Fatalf("extract %s: %v", d.Rel, err)
		}
		elapsed := time.Since(start)
		t.Logf("extract %s took %s, cost %s", d.Rel, elapsed.Round(time.Second), resp.Cost)
		run.Phases = append(run.Phases, timingFrom("extract", d.Rel, "", elapsed, resp.Cost))

		assertRealLLMWork(t, "extract "+d.Rel, resp.Cost, cfg.model)
		assertExtraction(t, kbDir, d.Rel, sourceRef, cfg.model)
	}

	// While the model is still resident, and only meaningful after a call was
	// made: the one assertion here whose answer this test did not supply.
	assertModelWasLoaded(t, cfg)

	// ── Phases 2 and 3: classify and write ──
	items := make([]bridge.PipelineItem, 0, len(docs))
	for _, d := range docs {
		items = append(items, bridge.PipelineItem{
			SourceRef: "raw/" + d.Rel,
			// Set deliberately: without it the classify cache is bypassed and
			// every per-item result collapses onto one empty key, so the results
			// could not be matched back to the documents that produced them.
			ContentHash: hashes[d.Rel],
		})
	}

	start := time.Now()
	pipe, err := client.Pipeline(ctx, bridge.PipelineRequest{
		KBDir:   kbDir,
		Items:   items,
		Model:   cfg.model,
		Workers: 1,
	})
	if err != nil {
		t.Fatalf("pipeline: %v", err)
	}
	pipeElapsed := time.Since(start)
	t.Logf("pipeline took %s, cost %s", pipeElapsed.Round(time.Second), pipe.Cost)
	// One row for the phase, not one per document: this route classifies and writes
	// every item in a single call, so the response carries no per-document
	// durations. PipelineStream would emit per-item events if per-document
	// granularity is ever needed here; the 64-document compile runs get it from
	// their own serial log instead.
	run.Phases = append(run.Phases, timingFrom("pipeline", "*", "", pipeElapsed, pipe.Cost))

	assertRealLLMWork(t, "pipeline", pipe.Cost, cfg.model)
	written := assertPipelineResults(t, pipe.Results, hashes)

	articles := articlePaths(t, kbDir)
	if len(articles) == 0 {
		t.Fatal("the write phase reported no failure but wiki/ holds no article")
	}
	t.Logf("wrote %d article(s) from %d create/merge op(s): %v", len(articles), written, articles)

	for _, rel := range articles {
		body, err := os.ReadFile(filepath.Join(kbDir, filepath.FromSlash(rel)))
		if err != nil {
			t.Fatalf("read article %s: %v", rel, err)
		}
		if title := frontmatter.ExtractTitle(body); title == "" {
			t.Errorf("article %s has no title in its frontmatter or an H1", rel)
		}
		if len(strings.TrimSpace(string(body))) < 100 {
			t.Errorf("article %s is %d bytes; the write phase produced a stub, not an article",
				rel, len(body))
		}
	}

	// The classify phase freezes the category list into the KB on its first run.
	if _, err := os.Stat(filepath.Join(kbDir, "kaas.json")); err != nil {
		t.Errorf("stat kaas.json: %v; classify did not record the KB's categories", err)
	}

	// ── Phase 4: index ──
	//
	// The pipeline already wrote these four files, so asserting they exist after
	// the index phase would pass even if the index phase did nothing at all.
	// Delete them first and the assertions become about this phase.
	for _, name := range wantIndexFiles {
		p := filepath.Join(kbDir, "index", name)
		if _, err := os.Stat(p); err != nil {
			t.Errorf("the pipeline should have written index/%s: %v", name, err)
			continue
		}
		if err := os.Remove(p); err != nil {
			t.Fatalf("remove index/%s before the index phase: %v", name, err)
		}
	}

	start = time.Now()
	raw, err := client.Index(ctx, bridge.IndexRequest{KBDir: kbDir})
	if err != nil {
		t.Fatalf("index: %v", err)
	}
	var indexed struct {
		Indexed int `json:"indexed"`
	}
	if err := json.Unmarshal(raw, &indexed); err != nil {
		t.Fatalf("decode index response %s: %v", raw, err)
	}
	indexElapsed := time.Since(start)
	t.Logf("index took %s, reported %d article(s)", indexElapsed.Round(time.Second), indexed.Indexed)
	run.Phases = append(run.Phases, PhaseTiming{
		Phase: "index", Doc: "*", Seconds: indexElapsed.Seconds(), Status: "ok",
	})

	// Two independent walks of wiki/ — the engine's and this test's — agreeing on
	// the count. Not evidence that indexing happened; the file checks below are.
	if indexed.Indexed != len(articles) {
		t.Errorf("index reported %d article(s), but wiki/ holds %d", indexed.Indexed, len(articles))
	}
	for _, name := range wantIndexFiles {
		info, err := os.Stat(filepath.Join(kbDir, "index", name))
		if err != nil {
			t.Errorf("the index phase did not rewrite index/%s: %v", name, err)
			continue
		}
		if info.Size() == 0 {
			t.Errorf("index/%s is empty", name)
		}
	}

	// The whole point of the pipeline: an article that was written is reachable
	// from the index a reader starts at.
	master, err := os.ReadFile(filepath.Join(kbDir, "index", "master-index.md"))
	if err != nil {
		t.Fatalf("read master index: %v", err)
	}
	for _, rel := range articles {
		if !strings.Contains(string(master), "("+rel+")") {
			t.Errorf("master-index.md does not link %s; the article is unreachable", rel)
		}
	}

	recordRun(t, run)
}

// timingFrom builds one ledger row from a phase's elapsed time and cost payload.
func timingFrom(phase, doc, article string, elapsed time.Duration, raw json.RawMessage) PhaseTiming {
	row := PhaseTiming{
		Phase: phase, Doc: doc, Article: article,
		Seconds: elapsed.Seconds(), Status: "ok",
	}
	var c costSummary
	if err := json.Unmarshal(raw, &c); err != nil {
		return row
	}
	row.Calls = c.Calls
	row.PromptTokens = c.Prompt
	row.CompletionTokens = c.Completion
	row.CostUSD = c.Cost
	row.Retries = c.retries()
	row.TimedOut = row.Retries > 0
	return row
}

// recordRun appends this run to the latency ledger and reports how it compares
// with earlier runs of the same shape.
//
// Recording is opt-in via KAAS_LOCALLM_METRICS, because a test in a shared
// repository should not append to a file in a contributor's home directory
// uninvited. When it is off, the per-phase summary is still logged — the numbers
// are the point, the history is the bonus.
//
// A regression is logged, not failed, unless KAAS_LOCALLM_FAIL_ON_REGRESSION is
// set. On a laptop, thermal state and whatever else is running move these numbers
// by more than the tolerance on their own, and a check that cries wolf gets
// ignored, which is worse than no check.
func recordRun(t *testing.T, run Record) {
	t.Helper()

	for _, phase := range []string{"extract", "pipeline", "index"} {
		if s, ok := run.Summarize()[phase]; ok {
			t.Logf("timing %s: n=%d median=%.1fs p90=%.1fs min=%.1fs max=%.1fs retries=%d",
				phase, s.Count, s.Median, s.P90, s.Min, s.Max, s.Retries)
		}
	}

	ledger := LedgerPath()
	if ledger == "" {
		t.Logf("no latency ledger configured; set %s to a .jsonl path to record this "+
			"run and compare it with earlier ones", LedgerEnvVar)
		return
	}

	// Read the history before appending, so this run is not compared with itself,
	// but append regardless of whether that read worked. A single corrupt line used
	// to end the function here, which threw away the measurement this run just spent
	// minutes of model time producing -- and left the bad line in place, so every
	// later run paid the same price until someone edited the file by hand. An
	// unreadable history costs the comparison, never the record.
	history, historyErr := LoadRecords(ledger)

	if err := AppendRecord(ledger, run); err != nil {
		// Reported, but not fatal to the comparison: the history was already read
		// and still says whether this run regressed.
		t.Errorf("append to latency ledger: %v", err)
	} else {
		t.Logf("recorded this run in %s", ledger)
	}

	if historyErr != nil {
		// The mirror case: an unreadable history costs the comparison and nothing
		// else, because the append above never needed it.
		t.Errorf("read latency ledger to compare against: %v", historyErr)
		return
	}
	cmp := CompareToBaseline(history, run, 0.20)

	if !cmp.HasBaseline {
		t.Logf("no earlier run with this shape (%s); this run becomes the baseline",
			run.Fingerprint())
		return
	}
	if len(cmp.Regressions) == 0 {
		t.Logf("no regression against %d earlier run(s) of this shape", cmp.BaselineRuns)
		return
	}
	for _, r := range cmp.Regressions {
		msg := fmt.Sprintf("REGRESSION vs %d earlier run(s): %s", cmp.BaselineRuns, r)
		if os.Getenv("KAAS_LOCALLM_FAIL_ON_REGRESSION") != "" {
			t.Error(msg)
		} else {
			t.Log(msg)
		}
	}
}

// costSummary is the engine's per-request accounting, as returned in the `cost`
// field of an extract or pipeline response.
type costSummary struct {
	Cost        float64 `json:"cost"`
	Prompt      int     `json:"prompt"`
	Completion  int     `json:"completion"`
	Cached      int     `json:"cached"`
	Calls       int     `json:"calls"`
	CallDetails []struct {
		Model            string  `json:"model"`
		PromptTokens     int     `json:"prompt_tokens"`
		CompletionTokens int     `json:"completion_tokens"`
		DurationS        float64 `json:"duration_s"`
		// Attempts is absent on a call that succeeded first time, so it reads as
		// 0 rather than 1; retries() accounts for that. It is the only signal
		// here for a call that hit the extract timeout and was retried, which is
		// the dominant source of latency variance on a local model.
		Attempts int `json:"attempts"`
	} `json:"call_details"`
}

// retries counts how many LLM attempts beyond the first this phase needed.
func (c costSummary) retries() int {
	n := 0
	for _, d := range c.CallDetails {
		if d.Attempts > 1 {
			n += d.Attempts - 1
		}
	}
	return n
}

// assertRealLLMWork requires a phase to have actually called the model.
//
// This is what separates a compile from a cache replay: the engine declines to
// re-extract a fresh extraction and the classify phase reads its own cache, and
// in both cases it answers with a zeroed cost tracker rather than an error. The
// per-call model names are checked too, which catches a phase quietly falling
// back to some other model for part of its work — the summarize hop resolves its
// model through a separate chain that can end somewhere else entirely.
func assertRealLLMWork(t *testing.T, phase string, raw json.RawMessage, model string) {
	t.Helper()

	var c costSummary
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Errorf("%s: decode cost %s: %v", phase, raw, err)
		return
	}
	if c.Calls == 0 {
		t.Errorf("%s made 0 LLM calls; it reused cached output instead of compiling", phase)
	}
	if c.Completion == 0 {
		t.Errorf("%s recorded 0 completion tokens; the model returned nothing", phase)
	}
	if len(c.CallDetails) != c.Calls {
		t.Errorf("%s reports %d call(s) but %d call detail(s)", phase, c.Calls, len(c.CallDetails))
	}
	for i, d := range c.CallDetails {
		if d.Model != model {
			t.Errorf("%s call %d ran on model %q, want %q", phase, i, d.Model, model)
		}
	}
}

// extractionHeader is the subset of an extraction file's frontmatter this test
// asserts on. Deliberately without `topics`: the engine tolerates a non-string
// topic, which would fail this struct's decode and fail the run for a reason
// unrelated to the compile.
type extractionHeader struct {
	Source          string         `yaml:"source"`
	SourceChecksum  string         `yaml:"source_checksum"`
	ExtractModel    string         `yaml:"extract_model"`
	ExtractStrategy string         `yaml:"extract_strategy"`
	Summary         string         `yaml:"summary"`
	Counts          map[string]int `yaml:"counts"`
}

// assertExtraction checks the file the extract phase persisted for one document.
func assertExtraction(t *testing.T, kbDir, rel, sourceRef, model string) {
	t.Helper()

	// Derived from the document this test chose, not from anything the engine
	// returned: the path is part of the contract, so the test has to state it.
	p := filepath.Join(kbDir, "extraction", filepath.FromSlash(rel))
	body, err := os.ReadFile(p)
	if err != nil {
		t.Fatalf("extract wrote no file at extraction/%s: %v", rel, err)
	}

	header, rest, ok := splitFrontmatter(string(body))
	if !ok {
		t.Fatalf("extraction/%s has no frontmatter block", rel)
	}
	var h extractionHeader
	if err := yaml.Unmarshal([]byte(header), &h); err != nil {
		t.Fatalf("parse extraction/%s frontmatter: %v", rel, err)
	}

	if h.Source != sourceRef {
		t.Errorf("extraction/%s records source %q, want %q", rel, h.Source, sourceRef)
	}
	// Provenance plumbing only. The engine records back the model the request
	// carried (server_daemon.py:168, :293), so this cannot tell which model
	// served the call — assertModelWasLoaded is what does that.
	if h.ExtractModel != model {
		t.Errorf("extraction/%s records extract_model %q, want the requested %q", rel, h.ExtractModel, model)
	}
	if h.ExtractStrategy != "chunked" {
		t.Errorf("extraction/%s records extract_strategy %q, want %q", rel, h.ExtractStrategy, "chunked")
	}
	if h.SourceChecksum == "" {
		t.Errorf("extraction/%s records no source_checksum", rel)
	}
	if strings.TrimSpace(h.Summary) == "" {
		t.Errorf("extraction/%s has an empty summary; the model returned nothing usable", rel)
	}

	total := 0
	for _, n := range h.Counts {
		total += n
	}
	if total == 0 {
		t.Errorf("extraction/%s extracted 0 units in total (counts %v); the document compiled to nothing",
			rel, h.Counts)
	}

	for _, section := range wantExtractionSections {
		if !strings.Contains(rest, section) {
			t.Errorf("extraction/%s is missing the %q section", rel, strings.TrimSpace(section))
		}
	}
}

// splitFrontmatter returns the YAML header and the remaining body of a document
// that opens with a `---` fenced block.
func splitFrontmatter(text string) (header, body string, ok bool) {
	const fence = "---\n"
	if !strings.HasPrefix(text, fence) {
		return "", "", false
	}
	rest := text[len(fence):]
	end := strings.Index(rest, "\n"+fence)
	if end < 0 {
		return "", "", false
	}
	return rest[:end+1], rest[end+len("\n"+fence):], true
}

// pipelineResult is one per-document entry of the pipeline response.
type pipelineResult struct {
	ContentHash string   `json:"content_hash"`
	Status      string   `json:"status"`
	Error       string   `json:"error"`
	Phase       string   `json:"phase"`
	Created     []string `json:"created"`
	Merged      []string `json:"merged"`
}

// assertPipelineResults checks every document got an ok result and returns the
// total number of create and merge operations reported.
//
// Worth asserting explicitly: the pipeline reports a per-item failure inside an
// otherwise successful response, so a run where every document failed to
// classify still returns no error from Pipeline.
func assertPipelineResults(t *testing.T, raw json.RawMessage, hashes map[string]string) int {
	t.Helper()

	var results []pipelineResult
	if err := json.Unmarshal(raw, &results); err != nil {
		t.Fatalf("decode pipeline results: %v", err)
	}
	if len(results) != len(hashes) {
		t.Errorf("pipeline returned %d result(s) for %d document(s)", len(results), len(hashes))
	}

	byHash := make(map[string]pipelineResult, len(results))
	ops := 0
	for _, r := range results {
		if r.Status != "ok" {
			t.Errorf("document %s failed in phase %q: %s", shortHash(r.ContentHash), r.Phase, r.Error)
		}
		ops += len(r.Created) + len(r.Merged)
		byHash[r.ContentHash] = r
	}
	for rel, h := range hashes {
		if _, found := byHash[h]; !found {
			t.Errorf("no pipeline result for %s (content hash %s)", rel, shortHash(h))
		}
	}
	if ops == 0 {
		t.Error("every document classified to zero articles; nothing was created or merged")
	}
	return ops
}

func shortHash(h string) string {
	if h == "" {
		return "<none>"
	}
	if len(h) > 12 {
		return h[:12]
	}
	return h
}

// articlePaths lists the articles under the KB's wiki/, KB-root-relative and in
// slash form, which is how the indexes refer to them.
func articlePaths(t *testing.T, kbDir string) []string {
	t.Helper()

	var out []string
	wiki := filepath.Join(kbDir, "wiki")
	err := filepath.WalkDir(wiki, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.EqualFold(filepath.Ext(d.Name()), ".md") {
			return nil
		}
		rel, err := filepath.Rel(kbDir, p)
		if err != nil {
			return err
		}
		out = append(out, filepath.ToSlash(rel))
		return nil
	})
	if err != nil {
		t.Fatalf("walk wiki: %v", err)
	}
	// Guard the assumption the index-linkage assertion rests on.
	for _, rel := range out {
		if !strings.HasPrefix(rel, "wiki/") {
			t.Fatalf("article %q is not under wiki/", rel)
		}
		if rel != path.Clean(rel) {
			t.Fatalf("article path %q is not clean", rel)
		}
	}
	return out
}
