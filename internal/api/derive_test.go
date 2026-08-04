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

func (f *fakeDerivedJobStore) ListDerivedJobs(_ context.Context, _ int) ([]*store.DerivedJob, error) {
	return f.jobs, nil
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

// writeDerivedManifest creates <kb>/derived/<slug>/manifest.json so that
// kbpath.ListSlugs and kbpath.Resolve recognise the directory as a derived KB.
func writeDerivedManifest(t *testing.T, kb, slug, topic, createdAt string) {
	t.Helper()
	dir := filepath.Join(kb, "derived", slug)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(map[string]string{
		"slug":       slug,
		"topic":      topic,
		"created_at": createdAt,
	})
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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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

func TestPostDeriveRejectsAnEmptyTopic(t *testing.T) {
	fds := newFakeDerivedStore()
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

	rec := do(t, s, "POST", "/api/derive", `{"topic":"  "}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
}

func TestPostDeriveRejectsAnInvalidSlug(t *testing.T) {
	// An explicit slug that does not pass kbpath.ValidSlug must be rejected before
	// the job is created: the guard is kbpath's slugRe, not new logic in this file.
	fds := newFakeDerivedStore()
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

	rec := do(t, s, "POST", "/api/derive", `{"topic":"定价"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "invalid slug") {
		t.Errorf("error body should mention slug; got: %s", rec.Body.String())
	}
}

func TestPostDeriveRejectsAnExistingDerivedKB(t *testing.T) {
	// When derived/<slug>/manifest.json already exists on disk the HTTP path
	// answers 409 without --force, so accidental overwrites from a web form are
	// prevented. Note that kbpath.Resolve only returns nil when manifest.json is
	// present, so a half-written directory without a manifest is not blocked.
	fds := newFakeDerivedStore()
	s, kb := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

	writeDerivedManifest(t, kb, "pricing", "Pricing", "2024-01-01")

	rec := do(t, s, "POST", "/api/derive", `{"topic":"pricing"}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
	if fds.createStored != nil {
		t.Error("CreateDerivedJob must not be called when the KB already exists on disk")
	}
}

func TestPostDeriveRejectsADuplicateActiveSlug(t *testing.T) {
	// When the store returns ErrDerivedJobExists a pending or running job already
	// holds this slug; a second enqueue must answer 409.
	fds := newFakeDerivedStore()
	fds.createErr = store.ErrDerivedJobExists
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	s, _ := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

	rec := do(t, s, "GET", "/api/derive/nonexistent", "")

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
}

// --- GET /api/derived ---

func TestListDerivedReadsManifests(t *testing.T) {
	fds := newFakeDerivedStore()
	s, kb := newTestServer(t, &fakeQueue{}, fds, &fakeBridge{})

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
	// newTestServer passes &fakeStore{} which does not implement
	// store.DerivedJobStore, so NewServer leaves s.js nil. The job-dependent
	// routes must answer 501; GET /api/derived reads only the filesystem and
	// must still work.
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

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
