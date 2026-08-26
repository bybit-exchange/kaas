package e2e

// Latency ledger for local-model compile runs.
//
// One run appends one JSON line. The point of keeping a history rather than
// printing a summary is that a slow run only reads as slow next to the runs
// before it — an unnoticed 30% regression looks exactly like a normal run when
// you have nothing to compare against.
//
// Two decisions shape everything here, both driven by how this pipeline actually
// behaves on a local model:
//
//   - Latency is bimodal, because the engine caps an extract call at 180s and
//     retries it. A document that retries takes roughly twice as long as the same
//     document that does not. Means are therefore useless: the summary reports
//     medians and p90, and counts retries as a separate signal. Retries move
//     first — a configuration starting to strain shows up as extra retries a
//     while before it shows up as a slower median.
//   - Only runs of the same shape may be compared. A run on another model, with
//     another worker count, or over another document set is not a baseline for
//     this one, so records carry a fingerprint and comparison is scoped to it.
//     Without that, every deliberate change reads as a regression and the output
//     stops being read.

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// LedgerEnvVar names the environment variable holding the ledger path.
const LedgerEnvVar = "KAAS_LOCALLM_METRICS"

// ErrNoLedger is returned when no ledger path is configured. Recording is
// opt-in — a contributor running the harness should not have a file appended
// somewhere in their home directory — so callers treat this as "skip", which is
// only safe if it is distinguishable from a failed write.
var ErrNoLedger = errors.New("e2e: no metrics ledger configured")

// PhaseTiming is one measured unit of work: one document through one phase.
type PhaseTiming struct {
	Phase   string  `json:"phase"`
	Doc     string  `json:"doc"`
	Seconds float64 `json:"seconds"`
	// Status is "ok", "cached" or "error". Only "ok" rows enter the latency
	// statistics: a cached row did no LLM work and an errored row measures how
	// long a failure took.
	Status           string  `json:"status"`
	Article          string  `json:"article,omitempty"`
	Calls            int     `json:"calls,omitempty"`
	PromptTokens     int     `json:"prompt_tokens,omitempty"`
	CompletionTokens int     `json:"completion_tokens,omitempty"`
	Retries          int     `json:"retries,omitempty"`
	TimedOut         bool    `json:"timed_out,omitempty"`
	CostUSD          float64 `json:"cost_usd,omitempty"`
}

// Record is one run of the pipeline.
type Record struct {
	Schema int    `json:"schema"`
	Kind   string `json:"kind"`
	// StartedAt is passed in rather than read from the clock, so a caller can
	// record the run's real start and tests stay deterministic.
	StartedAt string        `json:"started_at"`
	Model     string        `json:"model"`
	BaseURL   string        `json:"base_url,omitempty"`
	Workers   int           `json:"workers"`
	Documents int           `json:"documents"`
	RawBytes  int64         `json:"raw_bytes"`
	Phases    []PhaseTiming `json:"phases"`
}

// Fingerprint identifies runs that may be compared with one another.
//
// Timings and the clock are deliberately absent: a record has to match its own
// history. The document count and total byte size stand in for "the same corpus"
// — not exact, but it separates a 2-document smoke run from a 64-document
// compile, which is the confusion that matters.
func (r Record) Fingerprint() string {
	return fmt.Sprintf("%s|%s|w=%d|n=%d|b=%d", r.Kind, r.Model, r.Workers, r.Documents, r.RawBytes)
}

// PhaseSummary aggregates one phase of one run.
type PhaseSummary struct {
	Phase        string
	Count        int // rows that did real work, i.e. the basis of the percentiles
	Median       float64
	P90          float64
	Min          float64
	Max          float64
	Total        float64
	Cached       int
	Errors       int
	Retries      int
	TimedOutDocs int
}

// Summarize reduces a run to one summary per phase.
func (r Record) Summarize() map[string]PhaseSummary {
	byPhase := map[string][]float64{}
	out := map[string]PhaseSummary{}

	for _, p := range r.Phases {
		s := out[p.Phase]
		s.Phase = p.Phase
		s.Retries += p.Retries
		if p.TimedOut {
			s.TimedOutDocs++
		}
		switch p.Status {
		case "cached":
			s.Cached++
		case "error":
			s.Errors++
		default:
			byPhase[p.Phase] = append(byPhase[p.Phase], p.Seconds)
			s.Total += p.Seconds
		}
		out[p.Phase] = s
	}

	for phase, secs := range byPhase {
		sort.Float64s(secs)
		s := out[phase]
		s.Count = len(secs)
		s.Median = median(secs)
		s.P90 = percentile(secs, 0.90)
		s.Min = secs[0]
		s.Max = secs[len(secs)-1]
		out[phase] = s
	}
	return out
}

// median returns the middle value of sorted xs, averaging the two middle values
// for an even count. Returns 0 for an empty slice.
func median(xs []float64) float64 {
	if len(xs) == 0 {
		return 0
	}
	mid := len(xs) / 2
	if len(xs)%2 == 1 {
		return xs[mid]
	}
	return (xs[mid-1] + xs[mid]) / 2
}

// percentile returns the nearest-rank percentile of sorted xs. Nearest-rank
// rather than interpolated: with a handful of documents per run, an interpolated
// p90 reports a duration no document actually had.
func percentile(xs []float64, q float64) float64 {
	if len(xs) == 0 {
		return 0
	}
	rank := int(float64(len(xs))*q + 0.999999) // ceil, tolerating float slop
	rank = min(max(rank, 1), len(xs))
	return xs[rank-1]
}

// Regression is one flagged deterioration against the baseline.
type Regression struct {
	// Kind is "latency" or "retries".
	Kind     string
	Phase    string
	Baseline float64
	Latest   float64
}

func (r Regression) String() string {
	if r.Kind == "retries" {
		return fmt.Sprintf("%s: retries %.0f → %.0f", r.Phase, r.Baseline, r.Latest)
	}
	pct := 0.0
	if r.Baseline > 0 {
		pct = (r.Latest/r.Baseline - 1) * 100
	}
	return fmt.Sprintf("%s: median %.1fs → %.1fs (%+.0f%%)", r.Phase, r.Baseline, r.Latest, pct)
}

// Comparison is the verdict for one run against its history.
type Comparison struct {
	HasBaseline  bool
	BaselineRuns int
	Regressions  []Regression
}

// CompareToBaseline flags phases where latest deteriorated against the runs in
// history that share its fingerprint.
//
// The baseline for a phase is the median of that phase's per-run medians, so one
// unlucky earlier run cannot move the bar much. tolerance is a fraction: 0.20
// means "flag anything more than 20% slower". A phase the baseline never ran is
// skipped rather than reported, and an improvement is never a regression.
func CompareToBaseline(history []Record, latest Record, tolerance float64) Comparison {
	fp := latest.Fingerprint()
	var baselineMedians = map[string][]float64{}
	var baselineRetries = map[string][]float64{}
	runs := 0

	for _, h := range history {
		if h.Fingerprint() != fp {
			continue
		}
		runs++
		for phase, s := range h.Summarize() {
			if s.Count > 0 {
				baselineMedians[phase] = append(baselineMedians[phase], s.Median)
			}
			baselineRetries[phase] = append(baselineRetries[phase], float64(s.Retries))
		}
	}

	res := Comparison{HasBaseline: runs > 0, BaselineRuns: runs}
	if runs == 0 {
		return res
	}

	current := latest.Summarize()
	// Sorted so the output is stable run to run; a diffable report is worth more
	// than one that reshuffles.
	phases := make([]string, 0, len(current))
	for phase := range current {
		phases = append(phases, phase)
	}
	sort.Strings(phases)

	for _, phase := range phases {
		cur := current[phase]

		if prior, ok := baselineMedians[phase]; ok && cur.Count > 0 {
			sort.Float64s(prior)
			base := median(prior)
			if base > 0 && cur.Median > base*(1+tolerance) {
				res.Regressions = append(res.Regressions, Regression{
					Kind: "latency", Phase: phase, Baseline: base, Latest: cur.Median,
				})
			}
		}

		if prior, ok := baselineRetries[phase]; ok {
			sort.Float64s(prior)
			base := median(prior)
			// Any increase counts. Retries are discrete and rare; a tolerance band
			// on a baseline of zero would never fire, which is exactly the case
			// worth catching.
			if float64(cur.Retries) > base {
				res.Regressions = append(res.Regressions, Regression{
					Kind: "retries", Phase: phase, Baseline: base, Latest: float64(cur.Retries),
				})
			}
		}
	}
	return res
}

// LedgerPath returns the configured ledger path, or "" when recording is off.
func LedgerPath() string {
	return os.Getenv(LedgerEnvVar)
}

// AppendRecord appends one run to the ledger at path, creating it and its parent
// directories if needed.
func AppendRecord(path string, r Record) error {
	if path == "" {
		return ErrNoLedger
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("e2e: create ledger dir: %w", err)
	}
	line, err := json.Marshal(r)
	if err != nil {
		return fmt.Errorf("e2e: encode record: %w", err)
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("e2e: open ledger: %w", err)
	}
	defer f.Close()
	if _, err := f.Write(append(line, '\n')); err != nil {
		return fmt.Errorf("e2e: append record: %w", err)
	}
	return nil
}

// LoadRecords reads every run from the ledger at path. A missing ledger is an
// empty history, not an error: the first run of a configuration has none.
//
// A malformed line is an error naming its number. Skipping it would turn a
// truncated ledger into a short history, and a short history reads as "nothing
// to compare against" — the one outcome that must not happen silently.
func LoadRecords(path string) ([]Record, error) {
	f, err := os.Open(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("e2e: open ledger: %w", err)
	}
	defer f.Close()

	var out []Record
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for line := 1; sc.Scan(); line++ {
		text := strings.TrimSpace(sc.Text())
		if text == "" {
			continue
		}
		var r Record
		if err := json.Unmarshal([]byte(text), &r); err != nil {
			return nil, fmt.Errorf("e2e: ledger %s line %d: %w", path, line, err)
		}
		out = append(out, r)
	}
	if err := sc.Err(); err != nil {
		return nil, fmt.Errorf("e2e: read ledger: %w", err)
	}
	return out, nil
}
