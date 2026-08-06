package api

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// --- fakeDerivedJobStore ---

// fakeDerivedJobStore implements store.DerivedJobStore for derive endpoint tests.
// It embeds *fakeStore so the combined type satisfies both TaskStore (via the
// embedded methods) and store.DerivedJobStore — NewServer's type assertion
// therefore wires s.js automatically when one of these is passed as st.
type fakeDerivedJobStore struct {
	*fakeStore
	jobs         []*store.DerivedJob
	createErr    error
	createStored *store.DerivedJob
}

func newFakeDerivedStore() *fakeDerivedJobStore {
	return &fakeDerivedJobStore{fakeStore: &fakeStore{}}
}

func (f *fakeDerivedJobStore) CreateDerivedJob(_ context.Context, j *store.DerivedJob) error {
	if f.createErr != nil {
		return f.createErr
	}
	f.createStored = j
	f.jobs = append(f.jobs, j)
	return nil
}

func (f *fakeDerivedJobStore) GetDerivedJob(_ context.Context, id string) (*store.DerivedJob, error) {
	for _, j := range f.jobs {
		if j.ID == id {
			return j, nil
		}
	}
	return nil, store.ErrNotFound
}

func (f *fakeDerivedJobStore) ClaimNextDerivedJob(_ context.Context, _ int64) (*store.DerivedJob, error) {
	return nil, nil
}

func (f *fakeDerivedJobStore) SetDerivedJobStage(_ context.Context, _, _ string, _ int64) error {
	return nil
}

func (f *fakeDerivedJobStore) FinishDerivedJob(_ context.Context, _, _, _, _ string, _ int64) error {
	return nil
}

func (f *fakeDerivedJobStore) RecoverRunningDerivedJobs(_ context.Context, _ int64) (int, error) {
	return 0, nil
}

// --- test helpers ---

// newDeriveTestServer builds a server whose derive runner is wired, which is what
// POST /api/derive needs to answer anything but 501.
func newDeriveTestServer(t *testing.T, st TaskStore) (*Server, string) {
	t.Helper()
	s, kb := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})
	s.cfg.DeriveEnabled = true
	return s, kb
}

// writeDerivedManifest creates <kb>/derived/<slug>/manifest.json for a KB that
// finished compiling, so that kbpath.ListSlugs and kbpath.Resolve recognise the
// directory as a derived KB and the derive endpoints treat it as complete.
func writeDerivedManifest(t *testing.T, kb, slug, topic, createdAt string) {
	t.Helper()
	writeManifest(t, kb, slug, map[string]any{
		"slug":       slug,
		"topic":      topic,
		"created_at": createdAt,
		"compiled":   true,
	})
}

// writeUncompiledManifest creates the manifest a derive writes before compiling
// (spec E1). A derive that dies after this point leaves exactly this state: a
// directory kbpath.Resolve accepts, with no wiki/ behind it.
func writeUncompiledManifest(t *testing.T, kb, slug, topic string) {
	t.Helper()
	writeManifest(t, kb, slug, map[string]any{
		"slug":     slug,
		"topic":    topic,
		"compiled": false,
	})
}

func writeManifest(t *testing.T, kb, slug string, payload map[string]any) {
	t.Helper()
	dir := filepath.Join(kb, "derived", slug)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

// writeDerivedArticle creates a .md file under <kb>/derived/<slug>/wiki/<rel>,
// used to exercise countWikiArticles in the handleListDerived handler.
func writeDerivedArticle(t *testing.T, kb, slug, rel string) {
	t.Helper()
	full := filepath.Join(kb, "derived", slug, "wiki", rel)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte("# Article\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

// --- POST /api/derive ---

func TestPostDeriveEnqueuesAJob(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		JobID string `json:"job_id"`
		Slug  string `json:"slug"`
	}
	mustJSON(t, rec, &resp)
	if resp.JobID == "" {
		t.Fatal("job_id is empty")
	}
	if resp.Slug != "pricing" {
		t.Errorf("slug = %q, want pricing", resp.Slug)
	}
	if fds.createStored == nil {
		t.Fatal("CreateDerivedJob not called")
	}
	if fds.createStored.Status != store.DerivedStatusPending {
		t.Errorf("stored status = %q, want pending", fds.createStored.Status)
	}
	if fds.createStored.Slug != "pricing" {
		t.Errorf("stored slug = %q, want pricing", fds.createStored.Slug)
	}
	if fds.createStored.Topic != "pricing" {
		t.Errorf("stored topic = %q, want pricing", fds.createStored.Topic)
	}
}

func TestPostDeriveUsesAnExplicitSlug(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing and fees","slug":"pf"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		Slug string `json:"slug"`
	}
	mustJSON(t, rec, &resp)
	if resp.Slug != "pf" {
		t.Errorf("slug = %q, want pf", resp.Slug)
	}
	if fds.createStored == nil {
		t.Fatal("CreateDerivedJob not called")
	}
	if fds.createStored.Slug != "pf" {
		t.Errorf("stored slug = %q, want pf", fds.createStored.Slug)
	}
}

func TestPostDeriveDerivesTheSlugFromTheTopic(t *testing.T) {
	// Slug derivation mirrors normalise_slug in the Python side: lower-cased,
	// runs of non-alphanumeric characters collapsed to a single dash, leading
	// and trailing dashes trimmed, capped at 40 characters.
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"Pricing & Fees!"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		Slug string `json:"slug"`
	}
	mustJSON(t, rec, &resp)
	if resp.Slug != "pricing-fees" {
		t.Errorf("slug = %q, want pricing-fees", resp.Slug)
	}
}

// TestPostDeriveStoresSelectFrom pins the value onto the job row. The runner
// reads it back at claim time, so a value dropped here derives over articles
// while the response still reports 202.
func TestPostDeriveStoresSelectFrom(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing","select_from":"documents"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored == nil {
		t.Fatal("CreateDerivedJob not called")
	}
	if fds.createStored.SelectFrom != store.SelectFromDocuments {
		t.Errorf("stored select_from = %q, want %q",
			fds.createStored.SelectFrom, store.SelectFromDocuments)
	}
}

// TestPostDeriveLeavesAnOmittedSelectFromEmpty keeps the default with the engine.
// Materialising "articles" here would make a job that never asked
// indistinguishable from one that asked for the current default, so a future
// change of default would silently not apply to queued jobs.
func TestPostDeriveLeavesAnOmittedSelectFromEmpty(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored == nil {
		t.Fatal("CreateDerivedJob not called")
	}
	if fds.createStored.SelectFrom != "" {
		t.Errorf("stored select_from = %q, want empty", fds.createStored.SelectFrom)
	}
}

// TestPostDeriveRejectsAnUnknownSelectFrom rejects at the boundary rather than
// letting the engine raise. A queued job that fails on an unknown value costs the
// operator a round trip through the runner to learn about a typo, and burns the
// slug's active-index slot until it goes terminal.
func TestPostDeriveRejectsAnUnknownSelectFrom(t *testing.T) {
	for _, bad := range []string{"Documents", "docs", "raw", " documents"} {
		t.Run(bad, func(t *testing.T) {
			fds := newFakeDerivedStore()
			s, _ := newDeriveTestServer(t, fds)

			body, err := json.Marshal(map[string]string{"topic": "pricing", "select_from": bad})
			if err != nil {
				t.Fatal(err)
			}
			rec := do(t, s, "POST", "/api/derive", string(body))

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
			}
			if fds.createStored != nil {
				t.Error("a job was created for an unknown select_from")
			}
		})
	}
}

func TestPostDeriveRejectsAnEmptyTopic(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"  "}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
}

func TestPostDeriveRejectsAnInvalidSlug(t *testing.T) {
	// An explicit slug that does not pass kbpath.ValidSlug must be rejected before
	// the job is created: the guard is kbpath's slugRe, not new logic in this file.
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"t","slug":"../etc"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored != nil {
		t.Error("CreateDerivedJob must not be called for an invalid slug")
	}
}

func TestPostDeriveRejectsATopicThatNormalisesToNothing(t *testing.T) {
	// Chinese characters collapse entirely to hyphens, which get trimmed away,
	// leaving an empty slug that fails kbpath.ValidSlug.
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"定价"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "invalid slug") {
		t.Errorf("error body should mention slug; got: %s", rec.Body.String())
	}
}

func TestPostDeriveRejectsAnExistingCompiledKB(t *testing.T) {
	// When derived/<slug>/ holds a manifest saying compiled:true the HTTP path
	// answers 409, so a web form cannot overwrite a finished KB with no prompt.
	fds := newFakeDerivedStore()
	s, kb := newDeriveTestServer(t, fds)

	writeDerivedManifest(t, kb, "pricing", "Pricing", "2024-01-01")

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored != nil {
		t.Error("CreateDerivedJob must not be called when a compiled KB already exists")
	}
}

func TestPostDeriveReplacesAnIncompleteDerive(t *testing.T) {
	// The manifest is written before compiling (spec E1), so a derive that dies
	// leaves a directory kbpath.Resolve accepts with compiled:false. Returning 409
	// for it would burn the slug forever: the HTTP API has no force switch and no
	// delete route. An incomplete derive is replaceable; the runner passes force.
	fds := newFakeDerivedStore()
	s, kb := newDeriveTestServer(t, fds)

	writeUncompiledManifest(t, kb, "pricing", "Pricing")

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored == nil {
		t.Error("CreateDerivedJob must be called for an incomplete derive")
	}
}

func TestPostDeriveRejectsAnUnreadableManifest(t *testing.T) {
	// A manifest we cannot parse is not evidence of an incomplete derive. Replacing
	// the KB would destroy compiled articles that were paid for, so this stays a
	// 409 and the operator uses the CLI's --force. The handler logs the parse error.
	fds := newFakeDerivedStore()
	s, kb := newDeriveTestServer(t, fds)

	writeDerivedManifest(t, kb, "pricing", "Pricing", "2024-01-01")
	corrupt := filepath.Join(kb, "derived", "pricing", "manifest.json")
	if err := os.WriteFile(corrupt, []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
}

func TestPostDeriveRejectsAnOverlongTopic(t *testing.T) {
	// The body cap is 10 MiB, so without this check a megabyte-long topic is
	// persisted and shipped to the filter, where the prompt budget goes
	// non-positive and the run fails only after a paid round trip. Counted in runes
	// so a multi-byte topic is not rejected for its byte length.
	tests := []struct {
		name  string
		topic string
		want  int
	}{
		{"at the limit", strings.Repeat("a", topicMaxLen), http.StatusAccepted},
		{"one over the limit", strings.Repeat("a", topicMaxLen+1), http.StatusBadRequest},
		{"multi-byte at the limit", strings.Repeat("定", topicMaxLen), http.StatusAccepted},
		{"multi-byte over the limit", strings.Repeat("定", topicMaxLen+1), http.StatusBadRequest},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			fds := newFakeDerivedStore()
			s, _ := newDeriveTestServer(t, fds)
			// An explicit slug keeps slug derivation out of the assertion: a topic of
			// repeated multi-byte runes normalises to nothing.
			body, err := json.Marshal(deriveRequest{Topic: tc.topic, Slug: "pricing"})
			if err != nil {
				t.Fatal(err)
			}

			rec := do(t, s, "POST", "/api/derive", string(body))

			if rec.Code != tc.want {
				t.Fatalf("status = %d, want %d; body=%s", rec.Code, tc.want, rec.Body.String())
			}
			if tc.want == http.StatusBadRequest && fds.createStored != nil {
				t.Error("CreateDerivedJob must not be called for an overlong topic")
			}
		})
	}
}

func TestPostDeriveWithoutARunner(t *testing.T) {
	// cmd/kaas disables the derive runner when the bridge is not a DaemonClient.
	// Accepting a job nothing will ever claim leaves the UI on "Queued" forever, so
	// the endpoint must say the feature is unavailable instead.
	fds := newFakeDerivedStore()
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{}) // DeriveEnabled stays false

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusNotImplemented {
		t.Fatalf("status = %d, want 501; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored != nil {
		t.Error("CreateDerivedJob must not be called when no runner consumes the queue")
	}
}

func TestPostDeriveRejectsADuplicateActiveSlug(t *testing.T) {
	// When the store returns ErrDerivedJobExists a pending or running job already
	// holds this slug; a second enqueue must answer 409.
	fds := newFakeDerivedStore()
	fds.createErr = store.ErrDerivedJobExists
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
}

// --- GET /api/derive/{id} ---

func TestGetDeriveJob(t *testing.T) {
	fds := newFakeDerivedStore()
	job := &store.DerivedJob{
		ID:        "job1",
		Slug:      "pricing",
		Topic:     "pricing",
		Status:    store.DerivedStatusSucceeded,
		Stage:     store.DerivedStageDone,
		Error:     "",
		Result:    `{"articles":5,"cost_usd":0.01}`,
		CreatedAt: 1000,
		UpdatedAt: 2000,
	}
	fds.jobs = []*store.DerivedJob{job}
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "GET", "/api/derive/job1", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var resp deriveJobResponse
	mustJSON(t, rec, &resp)
	if resp.ID != "job1" {
		t.Errorf("id = %q, want job1", resp.ID)
	}
	if resp.Slug != "pricing" {
		t.Errorf("slug = %q, want pricing", resp.Slug)
	}
	if resp.Topic != "pricing" {
		t.Errorf("topic = %q, want pricing", resp.Topic)
	}
	if resp.Status != store.DerivedStatusSucceeded {
		t.Errorf("status = %q, want succeeded", resp.Status)
	}
	if resp.Stage != store.DerivedStageDone {
		t.Errorf("stage = %q, want done", resp.Stage)
	}
	if resp.CreatedAt != 1000 || resp.UpdatedAt != 2000 {
		t.Errorf("timestamps = %d/%d, want 1000/2000", resp.CreatedAt, resp.UpdatedAt)
	}
	// Result must be forwarded as a JSON object (not a quoted string) so the web
	// client can decode it directly without a second parse.
	var result struct {
		Articles int     `json:"articles"`
		CostUSD  float64 `json:"cost_usd"`
	}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		t.Fatalf("result is not a valid JSON object: %v; got %s", err, resp.Result)
	}
	if result.Articles != 5 {
		t.Errorf("result.articles = %d, want 5", result.Articles)
	}
}

func TestGetDeriveJobNotFound(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newDeriveTestServer(t, fds)

	rec := do(t, s, "GET", "/api/derive/nonexistent", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
}

// --- GET /api/derived ---

func TestListDerivedReadsManifests(t *testing.T) {
	fds := newFakeDerivedStore()
	s, kb := newDeriveTestServer(t, fds)

	// alpha: 1 wiki article; beta: 2 wiki articles. kbpath.ListSlugs returns
	// slugs sorted alphabetically, so alpha always comes first.
	writeDerivedManifest(t, kb, "alpha", "Alpha Topic", "2024-01-01")
	writeDerivedArticle(t, kb, "alpha", "a.md")

	writeDerivedManifest(t, kb, "beta", "Beta Topic", "2024-01-02")
	writeDerivedArticle(t, kb, "beta", "b.md")
	writeDerivedArticle(t, kb, "beta", "c.md")

	rec := do(t, s, "GET", "/api/derived", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		KBs []derivedKBSummary `json:"kbs"`
	}
	mustJSON(t, rec, &out)
	if len(out.KBs) != 2 {
		t.Fatalf("got %d KBs, want 2", len(out.KBs))
	}
	if out.KBs[0].Slug != "alpha" || out.KBs[1].Slug != "beta" {
		t.Errorf("slugs = [%q, %q], want [alpha, beta]", out.KBs[0].Slug, out.KBs[1].Slug)
	}
	if out.KBs[0].Topic != "Alpha Topic" {
		t.Errorf("alpha topic = %q, want Alpha Topic", out.KBs[0].Topic)
	}
	if out.KBs[0].CreatedAt != "2024-01-01" {
		t.Errorf("alpha created_at = %q, want 2024-01-01", out.KBs[0].CreatedAt)
	}
	if out.KBs[0].ArticleCount != 1 {
		t.Errorf("alpha article_count = %d, want 1", out.KBs[0].ArticleCount)
	}
	if out.KBs[1].ArticleCount != 2 {
		t.Errorf("beta article_count = %d, want 2", out.KBs[1].ArticleCount)
	}
}

func TestListDerivedSkipsUncompiledKBs(t *testing.T) {
	// An uncompiled KB has no wiki/ to browse, so listing it can only walk a user
	// into an empty corpus: the selector offers it, article_count reads 0, and chat
	// answers from nothing. It is also the resting state of a declined volume gate
	// (spec F5), which is uncompiled by design and must not show up as a KB.
	fds := newFakeDerivedStore()
	s, kb := newDeriveTestServer(t, fds)

	writeDerivedManifest(t, kb, "done", "Done Topic", "2024-01-01")
	writeDerivedArticle(t, kb, "done", "a.md")
	writeUncompiledManifest(t, kb, "halfway", "Halfway Topic")

	rec := do(t, s, "GET", "/api/derived", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		KBs []derivedKBSummary `json:"kbs"`
	}
	mustJSON(t, rec, &out)
	if len(out.KBs) != 1 {
		t.Fatalf("got %d KBs, want only the compiled one: %+v", len(out.KBs), out.KBs)
	}
	if out.KBs[0].Slug != "done" {
		t.Errorf("slug = %q, want the compiled KB done", out.KBs[0].Slug)
	}
}

func TestListDerivedWithNoDerivedDir(t *testing.T) {
	// An absent derived/ directory must yield {"kbs":[]} not an error.
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/derived", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		KBs []derivedKBSummary `json:"kbs"`
	}
	mustJSON(t, rec, &out)
	if len(out.KBs) != 0 {
		t.Errorf("want empty KB list, got %d entries", len(out.KBs))
	}
}

// --- 501 without a job store ---

func TestDeriveRoutesWithoutAJobStore(t *testing.T) {
	// &fakeStore{} does not implement store.DerivedJobStore, so NewServer leaves
	// s.js nil. The runner is wired here so the 501 can only come from the missing
	// store. The job-dependent routes must answer 501; GET /api/derived reads only
	// the filesystem and must still work.
	s, _ := newDeriveTestServer(t, &fakeStore{})

	rec := do(t, s, "POST", "/api/derive", `{"topic":"anything"}`)
	if rec.Code != http.StatusNotImplemented {
		t.Errorf("POST /api/derive without job store: status = %d, want 501", rec.Code)
	}

	rec = do(t, s, "GET", "/api/derive/someid", "")
	if rec.Code != http.StatusNotImplemented {
		t.Errorf("GET /api/derive/{id} without job store: status = %d, want 501", rec.Code)
	}

	rec = do(t, s, "GET", "/api/derived", "")
	if rec.Code != http.StatusOK {
		t.Errorf("GET /api/derived without job store: status = %d, want 200", rec.Code)
	}
}
