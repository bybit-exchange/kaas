package e2e

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func sampleRecord() Record {
	return Record{
		Schema:    1,
		Kind:      "harness",
		StartedAt: "2026-08-25T00:00:00Z",
		Model:     "qwen3.8:27b-mlx",
		Workers:   1,
		Documents: 2,
		RawBytes:  4295,
		Phases: []PhaseTiming{
			{Phase: "extract", Doc: "a.md", Seconds: 100, Status: "ok", Calls: 1},
			{Phase: "extract", Doc: "b.md", Seconds: 200, Status: "ok", Calls: 1},
		},
	}
}

func TestAppendRecordCreatesTheLedgerAndItsParentDirectory(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "nested", "runs.jsonl")

	if err := AppendRecord(ledger, sampleRecord()); err != nil {
		t.Fatalf("AppendRecord: %v", err)
	}

	got, err := LoadRecords(ledger)
	if err != nil {
		t.Fatalf("LoadRecords: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("len = %d, want 1", len(got))
	}
	if !reflect.DeepEqual(got[0], sampleRecord()) {
		t.Errorf("round trip changed the record:\n got %+v\nwant %+v", got[0], sampleRecord())
	}
}

func TestAppendRecordKeepsEarlierRuns(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "runs.jsonl")

	for _, model := range []string{"first", "second", "third"} {
		r := sampleRecord()
		r.Model = model
		if err := AppendRecord(ledger, r); err != nil {
			t.Fatalf("AppendRecord %s: %v", model, err)
		}
	}

	got, err := LoadRecords(ledger)
	if err != nil {
		t.Fatalf("LoadRecords: %v", err)
	}
	var models []string
	for _, r := range got {
		models = append(models, r.Model)
	}
	// Order matters: the ledger is a history, and "the previous run" has to be
	// recoverable from it.
	if !reflect.DeepEqual(models, []string{"first", "second", "third"}) {
		t.Errorf("models = %v, want [first second third]", models)
	}
}

func TestAppendRecordWritesOneLinePerRun(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "runs.jsonl")

	for range 3 {
		if err := AppendRecord(ledger, sampleRecord()); err != nil {
			t.Fatalf("AppendRecord: %v", err)
		}
	}

	body, err := os.ReadFile(ledger)
	if err != nil {
		t.Fatalf("read ledger: %v", err)
	}
	// JSONL: exactly one record per line, so the file stays appendable and
	// greppable without a parser.
	lines := strings.Split(strings.TrimRight(string(body), "\n"), "\n")
	if len(lines) != 3 {
		t.Errorf("got %d line(s), want 3", len(lines))
	}
	for i, l := range lines {
		if !strings.HasPrefix(l, "{") || !strings.HasSuffix(l, "}") {
			t.Errorf("line %d is not a single JSON object: %q", i, l)
		}
	}
}

func TestLoadRecordsOnAMissingLedgerIsEmptyNotAnError(t *testing.T) {
	// The first run of a new configuration has no history, and that is normal.
	got, err := LoadRecords(filepath.Join(t.TempDir(), "absent.jsonl"))
	if err != nil {
		t.Fatalf("LoadRecords on a missing file: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("got %d record(s), want 0", len(got))
	}
}

func TestLoadRecordsReportsACorruptLineWithItsNumber(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "runs.jsonl")
	if err := os.WriteFile(ledger, []byte("{\"schema\":1}\nnot json\n"), 0o644); err != nil {
		t.Fatalf("write ledger: %v", err)
	}

	_, err := LoadRecords(ledger)
	if err == nil {
		t.Fatal("LoadRecords on a corrupt ledger returned nil error")
	}
	// Silently dropping the line would make a truncated ledger look like a short
	// history, which reads as "no regression".
	if !strings.Contains(err.Error(), "2") {
		t.Errorf("err = %v, want it to name line 2", err)
	}
}

// A run's measurement costs minutes of model time and cannot be reproduced; the
// history it is compared against is already on disk. So an unreadable history must
// cost the run its comparison and never its record. recordRun relies on that by
// appending before it acts on a LoadRecords failure, which only works because
// appending does not read what is already there — pinned here, because the obvious
// refactor (validate the ledger, then write) would silently reintroduce the loss.
func TestAppendRecordStillRecordsWhenAnEarlierLineIsCorrupt(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "runs.jsonl")
	if err := os.WriteFile(ledger, []byte("{\"schema\":1}\nnot json\n"), 0o644); err != nil {
		t.Fatalf("write ledger: %v", err)
	}
	if _, err := LoadRecords(ledger); err == nil {
		t.Fatal("fixture is not actually corrupt: LoadRecords accepted it")
	}

	run := sampleRecord()
	run.StartedAt = "2026-08-26T12:00:00Z" // distinct from the corrupt lines above
	if err := AppendRecord(ledger, run); err != nil {
		t.Fatalf("AppendRecord onto a corrupt ledger: %v", err)
	}

	body, err := os.ReadFile(ledger)
	if err != nil {
		t.Fatalf("read ledger: %v", err)
	}
	lines := strings.Split(strings.TrimRight(string(body), "\n"), "\n")
	if len(lines) != 3 {
		t.Fatalf("ledger has %d lines, want the 2 corrupt ones plus this run", len(lines))
	}
	var got Record
	if err := json.Unmarshal([]byte(lines[2]), &got); err != nil {
		t.Fatalf("the appended line is not a record: %v", err)
	}
	if got.StartedAt != "2026-08-26T12:00:00Z" {
		t.Errorf("appended StartedAt = %q, want the run we passed", got.StartedAt)
	}
}

func TestLoadRecordsSkipsBlankLines(t *testing.T) {
	ledger := filepath.Join(t.TempDir(), "runs.jsonl")
	if err := os.WriteFile(ledger, []byte("{\"schema\":1}\n\n   \n{\"schema\":1}\n"), 0o644); err != nil {
		t.Fatalf("write ledger: %v", err)
	}

	got, err := LoadRecords(ledger)
	if err != nil {
		t.Fatalf("LoadRecords: %v", err)
	}
	if len(got) != 2 {
		t.Errorf("got %d record(s), want 2", len(got))
	}
}

func TestFingerprintGroupsComparableRunsAndSeparatesTheRest(t *testing.T) {
	base := sampleRecord()

	same := base
	same.StartedAt = "2027-01-01T00:00:00Z"
	same.Phases = []PhaseTiming{{Phase: "extract", Doc: "a.md", Seconds: 999, Status: "ok"}}
	if base.Fingerprint() != same.Fingerprint() {
		t.Error("fingerprint changed when only the timings and the clock changed; " +
			"it must not, or a run can never be compared with its own history")
	}

	for name, mutate := range map[string]func(*Record){
		"model":     func(r *Record) { r.Model = "gemma4:12b-mlx" },
		"workers":   func(r *Record) { r.Workers = 4 },
		"documents": func(r *Record) { r.Documents = 3 },
		"raw bytes": func(r *Record) { r.RawBytes = 9999 },
		"kind":      func(r *Record) { r.Kind = "compile" },
	} {
		other := base
		mutate(&other)
		if other.Fingerprint() == base.Fingerprint() {
			t.Errorf("changing %s did not change the fingerprint; runs that are not "+
				"comparable would be compared", name)
		}
	}
}

func TestSummarizeComputesPercentilesPerPhase(t *testing.T) {
	r := Record{Phases: []PhaseTiming{
		// Deliberately out of order, and one row per phase kept distinct so a
		// summary that mixed phases would show it.
		{Phase: "extract", Doc: "e1", Seconds: 30, Status: "ok"},
		{Phase: "extract", Doc: "e2", Seconds: 10, Status: "ok"},
		{Phase: "extract", Doc: "e3", Seconds: 20, Status: "ok"},
		{Phase: "extract", Doc: "e4", Seconds: 100, Status: "ok"},
		{Phase: "write", Doc: "w1", Seconds: 7, Status: "ok"},
	}}

	got := r.Summarize()

	extract, ok := got["extract"]
	if !ok {
		t.Fatalf("no summary for extract; got phases %v", keysOf(got))
	}
	// n=4 sorted [10 20 30 100]: median is the mean of the two middle values,
	// p90 is nearest-rank ceil(0.9*4)=4 → the 4th value.
	if extract.Count != 4 || extract.Median != 25 || extract.P90 != 100 ||
		extract.Min != 10 || extract.Max != 100 {
		t.Errorf("extract = %+v, want count 4, median 25, p90 100, min 10, max 100", extract)
	}
	if w := got["write"]; w.Count != 1 || w.Median != 7 || w.P90 != 7 {
		t.Errorf("write = %+v, want count 1, median 7, p90 7", w)
	}
}

func TestSummarizeExcludesCachedRowsFromLatency(t *testing.T) {
	r := Record{Phases: []PhaseTiming{
		{Phase: "classify", Doc: "a", Seconds: 100, Status: "ok"},
		{Phase: "classify", Doc: "b", Seconds: 0, Status: "cached"},
		{Phase: "classify", Doc: "c", Seconds: 0, Status: "cached"},
		{Phase: "classify", Doc: "d", Seconds: 0, Status: "cached"},
	}}

	got := r.Summarize()["classify"]

	// A cached row did no LLM work. Averaging its zero in would report 25s for a
	// phase that actually takes 100s, and nothing in the output would say so.
	if got.Count != 1 || got.Median != 100 {
		t.Errorf("classify = %+v, want count 1 and median 100 (cached rows excluded)", got)
	}
	if got.Cached != 3 {
		t.Errorf("Cached = %d, want 3 reported separately", got.Cached)
	}
}

func TestSummarizeCountsRetriesAndTimeouts(t *testing.T) {
	r := Record{Phases: []PhaseTiming{
		{Phase: "extract", Doc: "a", Seconds: 100, Status: "ok"},
		{Phase: "extract", Doc: "b", Seconds: 350, Status: "ok", Retries: 1, TimedOut: true},
		{Phase: "extract", Doc: "c", Seconds: 570, Status: "error", Retries: 2, TimedOut: true},
	}}

	got := r.Summarize()["extract"]

	if got.Retries != 3 {
		t.Errorf("Retries = %d, want 3", got.Retries)
	}
	if got.TimedOutDocs != 2 {
		t.Errorf("TimedOutDocs = %d, want 2", got.TimedOutDocs)
	}
	if got.Errors != 1 {
		t.Errorf("Errors = %d, want 1", got.Errors)
	}
	// An errored row's duration is how long the failure took, not how long the
	// work takes, so it must not enter the latency percentiles.
	if got.Count != 2 || got.Median != 225 {
		t.Errorf("got count %d median %v, want count 2 median 225 (error row excluded)",
			got.Count, got.Median)
	}
}

func TestCompareToBaselineWithNoHistorySaysSo(t *testing.T) {
	latest := sampleRecord()

	res := CompareToBaseline(nil, latest, 0.20)

	if res.HasBaseline {
		t.Error("HasBaseline = true with no history")
	}
	if len(res.Regressions) != 0 {
		t.Errorf("Regressions = %v, want none without a baseline", res.Regressions)
	}
	if res.BaselineRuns != 0 {
		t.Errorf("BaselineRuns = %d, want 0", res.BaselineRuns)
	}
}

func TestCompareToBaselineIgnoresRunsWithADifferentFingerprint(t *testing.T) {
	fast := sampleRecord()
	fast.Model = "some-other-model"
	fast.Phases = []PhaseTiming{{Phase: "extract", Doc: "a.md", Seconds: 1, Status: "ok"}}

	latest := sampleRecord() // median 150s, vastly slower than the other model's 1s

	res := CompareToBaseline([]Record{fast}, latest, 0.20)

	if res.HasBaseline {
		t.Error("a run on a different model was accepted as a baseline; " +
			"that comparison is meaningless and would fire on every model switch")
	}
	if len(res.Regressions) != 0 {
		t.Errorf("Regressions = %v, want none", res.Regressions)
	}
}

func TestCompareToBaselineFlagsASlowerPhase(t *testing.T) {
	before := sampleRecord() // extract median 150
	latest := sampleRecord()
	latest.Phases = []PhaseTiming{
		{Phase: "extract", Doc: "a.md", Seconds: 180, Status: "ok"},
		{Phase: "extract", Doc: "b.md", Seconds: 220, Status: "ok"}, // median 200
	}

	res := CompareToBaseline([]Record{before}, latest, 0.20)

	if !res.HasBaseline || res.BaselineRuns != 1 {
		t.Fatalf("HasBaseline = %v, BaselineRuns = %d, want true and 1", res.HasBaseline, res.BaselineRuns)
	}
	if len(res.Regressions) != 1 {
		t.Fatalf("Regressions = %+v, want exactly one", res.Regressions)
	}
	got := res.Regressions[0]
	// 200 vs 150 is +33%, past the 20% tolerance.
	if got.Phase != "extract" || got.Baseline != 150 || got.Latest != 200 {
		t.Errorf("regression = %+v, want phase extract, baseline 150, latest 200", got)
	}
	if got.Kind != "latency" {
		t.Errorf("Kind = %q, want %q", got.Kind, "latency")
	}
}

func TestCompareToBaselineToleratesNoiseAndImprovement(t *testing.T) {
	before := sampleRecord() // extract median 150

	for name, seconds := range map[string][2]float64{
		"within tolerance": {160, 170}, // median 165, +10%
		"exactly at limit": {170, 190}, // median 180, +20% — not past it
		"faster":           {50, 60},   // median 55
	} {
		latest := sampleRecord()
		latest.Phases = []PhaseTiming{
			{Phase: "extract", Doc: "a.md", Seconds: seconds[0], Status: "ok"},
			{Phase: "extract", Doc: "b.md", Seconds: seconds[1], Status: "ok"},
		}
		res := CompareToBaseline([]Record{before}, latest, 0.20)
		if len(res.Regressions) != 0 {
			t.Errorf("%s: Regressions = %+v, want none", name, res.Regressions)
		}
	}
}

func TestCompareToBaselineUsesTheMedianAcrossSeveralBaselineRuns(t *testing.T) {
	var history []Record
	// Three prior runs with extract medians 100, 150 and 500. The median of those
	// is 150 and their mean is 250 — deliberately different, so that swapping the
	// baseline to a mean makes this test fail instead of passing either way.
	for _, pair := range [][2]float64{{90, 110}, {140, 160}, {490, 510}} {
		r := sampleRecord()
		r.Phases = []PhaseTiming{
			{Phase: "extract", Doc: "a.md", Seconds: pair[0], Status: "ok"},
			{Phase: "extract", Doc: "b.md", Seconds: pair[1], Status: "ok"},
		}
		history = append(history, r)
	}

	latest := sampleRecord()
	latest.Phases = []PhaseTiming{
		{Phase: "extract", Doc: "a.md", Seconds: 200, Status: "ok"},
		{Phase: "extract", Doc: "b.md", Seconds: 220, Status: "ok"}, // median 210 vs 150
	}

	res := CompareToBaseline(history, latest, 0.20)

	if res.BaselineRuns != 3 {
		t.Errorf("BaselineRuns = %d, want 3", res.BaselineRuns)
	}
	if len(res.Regressions) != 1 || res.Regressions[0].Baseline != 150 {
		t.Fatalf("regressions = %+v, want one with baseline 150 (the median of 100/150/500, "+
			"not the mean and not the latest)", res.Regressions)
	}
}

func TestCompareToBaselineFlagsARetryIncreaseOnItsOwn(t *testing.T) {
	before := sampleRecord() // no retries, extract median 150

	latest := sampleRecord()
	latest.Phases = []PhaseTiming{
		// Same median duration as the baseline, but now one document is retrying.
		// Retries lead: they show up before the wall-clock does, and a
		// duration-only check would call this run unchanged.
		{Phase: "extract", Doc: "a.md", Seconds: 100, Status: "ok"},
		{Phase: "extract", Doc: "b.md", Seconds: 200, Status: "ok", Retries: 1, TimedOut: true},
	}

	res := CompareToBaseline([]Record{before}, latest, 0.20)

	if len(res.Regressions) != 1 {
		t.Fatalf("Regressions = %+v, want one for the new retry", res.Regressions)
	}
	if res.Regressions[0].Kind != "retries" {
		t.Errorf("Kind = %q, want %q", res.Regressions[0].Kind, "retries")
	}
}

func TestCompareToBaselineFlagsMoreRetriesThanAnAlreadyRetryingBaseline(t *testing.T) {
	// The baseline already retries 5 times; this run retries 6. The step is
	// deliberately inside a 20% band (5 × 1.2 = 6.0), so a tolerance-based check
	// would stay silent and only a plain "any increase" check reports it. That is
	// the behaviour wanted: a configuration drifting worse retries more often well
	// before its median duration moves, and the baseline is already a median across
	// runs, so one unlucky run cannot move it much on its own.
	before := sampleRecord()
	before.Phases = []PhaseTiming{
		{Phase: "extract", Doc: "a.md", Seconds: 100, Status: "ok", Retries: 2, TimedOut: true},
		{Phase: "extract", Doc: "b.md", Seconds: 200, Status: "ok", Retries: 3, TimedOut: true},
	}

	latest := sampleRecord()
	latest.Phases = []PhaseTiming{
		{Phase: "extract", Doc: "a.md", Seconds: 100, Status: "ok", Retries: 3, TimedOut: true},
		{Phase: "extract", Doc: "b.md", Seconds: 200, Status: "ok", Retries: 3, TimedOut: true},
	}

	res := CompareToBaseline([]Record{before}, latest, 0.20)

	var got *Regression
	for i := range res.Regressions {
		if res.Regressions[i].Kind == "retries" {
			got = &res.Regressions[i]
		}
	}
	if got == nil {
		t.Fatalf("Regressions = %+v, want one of kind retries for 5 → 6", res.Regressions)
	}
	if got.Baseline != 5 || got.Latest != 6 {
		t.Errorf("regression = %+v, want baseline 5 and latest 6", *got)
	}
}

func TestCompareToBaselineIgnoresAPhaseTheBaselineNeverRan(t *testing.T) {
	before := sampleRecord() // extract only

	latest := sampleRecord()
	latest.Phases = append(latest.Phases,
		PhaseTiming{Phase: "write", Doc: "a.md", Seconds: 500, Status: "ok"})

	res := CompareToBaseline([]Record{before}, latest, 0.20)

	// There is nothing to compare a brand-new phase against; inventing a
	// regression for it would train the reader to ignore the output.
	for _, reg := range res.Regressions {
		if reg.Phase == "write" {
			t.Errorf("flagged phase %q that has no baseline: %+v", reg.Phase, reg)
		}
	}
}

func TestLedgerPathFromEnvIsOptional(t *testing.T) {
	t.Setenv("KAAS_LOCALLM_METRICS", "")
	if p := LedgerPath(); p != "" {
		t.Errorf("LedgerPath() = %q, want empty when the env var is unset", p)
	}

	t.Setenv("KAAS_LOCALLM_METRICS", "/tmp/x/runs.jsonl")
	if p := LedgerPath(); p != "/tmp/x/runs.jsonl" {
		t.Errorf("LedgerPath() = %q, want the env value", p)
	}
}

func TestAppendRecordRejectsAnEmptyPath(t *testing.T) {
	err := AppendRecord("", sampleRecord())
	if err == nil {
		t.Fatal("AppendRecord with an empty path returned nil error")
	}
	if !errors.Is(err, ErrNoLedger) {
		t.Errorf("err = %v, want it to wrap ErrNoLedger so a caller can tell "+
			"'not configured' from 'write failed'", err)
	}
}

func keysOf[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
