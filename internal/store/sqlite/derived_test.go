package sqlite

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

func newDerivedStore(t *testing.T) *Store {
	t.Helper()
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return s
}

func TestCreateAndGetDerivedJob(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	job := &store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "pricing and fees", Model: "m",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
		CreatedAt: 100, UpdatedAt: 100,
	}
	if err := s.CreateDerivedJob(ctx, job); err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := s.GetDerivedJob(ctx, "j1")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Slug != "pricing" || got.Topic != "pricing and fees" || got.Model != "m" {
		t.Errorf("round trip mismatch: %+v", got)
	}
	if got.Status != store.DerivedStatusPending || got.Stage != store.DerivedStageQueued {
		t.Errorf("status/stage = %q/%q", got.Status, got.Stage)
	}
}

// TestDerivedJobRoundTripsSelectFrom pins select_from onto the row rather than
// the runner: the runner reads it back at claim time, so a value dropped by the
// INSERT would silently derive over articles after the operator asked for
// documents — a wrong-but-plausible KB, not a visible failure.
func TestDerivedJobRoundTripsSelectFrom(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	job := &store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t", SelectFrom: store.SelectFromDocuments,
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
		CreatedAt: 100, UpdatedAt: 100,
	}
	if err := s.CreateDerivedJob(ctx, job); err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := s.GetDerivedJob(ctx, "j1")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.SelectFrom != store.SelectFromDocuments {
		t.Errorf("SelectFrom = %q, want %q", got.SelectFrom, store.SelectFromDocuments)
	}
}

// TestClaimNextDerivedJobCarriesSelectFrom covers the claim path specifically:
// it SELECTs through its own RETURNING clause, so a column missing from
// derivedJobColumns would round-trip through Get and still be lost here — and
// the claim is the only read the runner performs.
func TestClaimNextDerivedJobCarriesSelectFrom(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	job := &store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t", SelectFrom: store.SelectFromDocuments,
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
		CreatedAt: 100, UpdatedAt: 100,
	}
	if err := s.CreateDerivedJob(ctx, job); err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := s.ClaimNextDerivedJob(ctx, 200)
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	if got == nil {
		t.Fatal("claim returned no job")
	}
	if got.SelectFrom != store.SelectFromDocuments {
		t.Errorf("SelectFrom = %q, want %q", got.SelectFrom, store.SelectFromDocuments)
	}
}

// TestDerivedJobSelectFromDefaultsToEmpty pins that an unset SelectFrom stays
// empty rather than becoming a literal "articles" in the database. Empty is what
// a row written before this column existed reads back as, so the two cases must
// be indistinguishable — the engine resolves the default in one place.
func TestDerivedJobSelectFromDefaultsToEmpty(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	job := &store.DerivedJob{
		ID: "j1", Slug: "pricing", Topic: "t",
		Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued,
		CreatedAt: 100, UpdatedAt: 100,
	}
	if err := s.CreateDerivedJob(ctx, job); err != nil {
		t.Fatalf("create: %v", err)
	}
	got, err := s.GetDerivedJob(ctx, "j1")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.SelectFrom != "" {
		t.Errorf("SelectFrom = %q, want empty", got.SelectFrom)
	}
}

// TestMigrateAddsSelectFromToAnOlderDatabase builds derived_jobs as it stood
// before the column existed, then migrates. Without the ALTER TABLE every derive
// query would name a column the table lacks, so an upgraded install would fail at
// the first derive rather than at startup.
func TestMigrateAddsSelectFromToAnOlderDatabase(t *testing.T) {
	s, err := Open(":memory:")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	ctx := context.Background()

	if _, err := s.db.ExecContext(ctx, `
		CREATE TABLE derived_jobs (
			id         TEXT PRIMARY KEY,
			slug       TEXT NOT NULL,
			topic      TEXT NOT NULL,
			model      TEXT NOT NULL DEFAULT '',
			status     TEXT NOT NULL,
			stage      TEXT NOT NULL,
			error      TEXT NOT NULL DEFAULT '',
			result     TEXT NOT NULL DEFAULT '',
			created_at INTEGER NOT NULL,
			updated_at INTEGER NOT NULL
		)`); err != nil {
		t.Fatalf("plant pre-migration table: %v", err)
	}
	if _, err := s.db.ExecContext(ctx, `
		INSERT INTO derived_jobs (id, slug, topic, status, stage, created_at, updated_at)
		VALUES ('old', 'legacy', 't', ?, ?, 1, 1)`,
		store.DerivedStatusSucceeded, store.DerivedStageDone); err != nil {
		t.Fatalf("plant pre-migration row: %v", err)
	}

	if err := s.Migrate(ctx); err != nil {
		t.Fatalf("migrate: %v", err)
	}

	got, err := s.GetDerivedJob(ctx, "old")
	if err != nil {
		t.Fatalf("get the pre-migration row: %v", err)
	}
	if got.SelectFrom != "" {
		t.Errorf("SelectFrom = %q, want empty for a row that predates the column", got.SelectFrom)
	}
}

func TestGetDerivedJobNotFound(t *testing.T) {
	s := newDerivedStore(t)
	if _, err := s.GetDerivedJob(context.Background(), "nope"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("err = %v, want ErrNotFound", err)
	}
}

func TestCreateDerivedJobRejectsAnActiveDuplicateSlug(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	first := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, first); err != nil {
		t.Fatalf("create first: %v", err)
	}
	second := &store.DerivedJob{ID: "j2", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 2, UpdatedAt: 2}
	if err := s.CreateDerivedJob(ctx, second); !errors.Is(err, store.ErrDerivedJobExists) {
		t.Errorf("err = %v, want ErrDerivedJobExists", err)
	}
}

func TestCreateDerivedJobAllowsTheSameSlugAfterATerminalRun(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	first := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, first); err != nil {
		t.Fatalf("create first: %v", err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatalf("claim: %v", err)
	}
	if err := s.FinishDerivedJob(ctx, "j1", store.DerivedStatusFailed, "boom", "", 3); err != nil {
		t.Fatalf("finish: %v", err)
	}
	second := &store.DerivedJob{ID: "j2", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 4, UpdatedAt: 4}
	if err := s.CreateDerivedJob(ctx, second); err != nil {
		t.Errorf("create after a terminal run: %v", err)
	}
}

func TestClaimNextDerivedJobIsSingleFlight(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for _, id := range []string{"j1", "j2"} {
		j := &store.DerivedJob{ID: id, Slug: id, Topic: "t", Status: store.DerivedStatusPending,
			Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", id, err)
		}
	}
	first, err := s.ClaimNextDerivedJob(ctx, 2)
	if err != nil || first == nil {
		t.Fatalf("first claim = %v, %v", first, err)
	}
	if first.ID != "j1" {
		t.Errorf("claimed %q, want the oldest (j1)", first.ID)
	}
	// A second claim must not hand out a job while one is running.
	second, err := s.ClaimNextDerivedJob(ctx, 3)
	if err != nil {
		t.Fatalf("second claim: %v", err)
	}
	if second != nil {
		t.Errorf("claimed %q while %q was running", second.ID, first.ID)
	}
}

func TestClaimNextDerivedJobEmptyQueue(t *testing.T) {
	s := newDerivedStore(t)
	got, err := s.ClaimNextDerivedJob(context.Background(), 1)
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	if got != nil {
		t.Errorf("claim = %+v, want nil", got)
	}
}

func TestSetDerivedJobStage(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	if err := s.SetDerivedJobStage(ctx, "j1", store.DerivedStageCompile, 3); err != nil {
		t.Fatalf("set stage: %v", err)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Stage != store.DerivedStageCompile || got.UpdatedAt != 3 {
		t.Errorf("job = %+v", got)
	}
}

func TestFinishDerivedJobRecordsTheResult(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	if err := s.FinishDerivedJob(ctx, "j1", store.DerivedStatusSucceeded, "", `{"documents":3}`, 4); err != nil {
		t.Fatalf("finish: %v", err)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Status != store.DerivedStatusSucceeded || got.Stage != store.DerivedStageDone {
		t.Errorf("status/stage = %q/%q", got.Status, got.Stage)
	}
	if got.Result != `{"documents":3}` || got.Error != "" {
		t.Errorf("result = %q, error = %q", got.Result, got.Error)
	}
}

func TestRecoverRunningDerivedJobs(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{ID: "j1", Slug: "pricing", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatal(err)
	}
	// A restart leaves a job stuck in running with nobody driving it.
	n, err := s.RecoverRunningDerivedJobs(ctx, 3)
	if err != nil {
		t.Fatalf("recover: %v", err)
	}
	if n != 1 {
		t.Fatalf("recovered %d, want 1", n)
	}
	got, _ := s.GetDerivedJob(ctx, "j1")
	if got.Status != store.DerivedStatusFailed {
		t.Errorf("status = %q, want failed", got.Status)
	}
	if got.Error == "" {
		t.Error("recovered job carries no error message")
	}
	// The message is the only guidance the operator gets, and it must name an
	// action they can actually take: the HTTP API has no force switch, so a
	// message pointing at one sends them looking for a button that is not there.
	// Retrying works because the interrupted derive left an uncompiled KB, which
	// the API treats as replaceable.
	if strings.Contains(got.Error, "force") {
		t.Errorf("error = %q, want it not to point at a force option no HTTP or UI caller has", got.Error)
	}
	if !strings.Contains(got.Error, "retry") {
		t.Errorf("error = %q, want it to tell the operator to retry the derive", got.Error)
	}
}

// TestClaimDerivedJobConcurrentIsSingleFlight spins up multiple goroutines that
// all race to claim jobs and verifies at most one job is running at any point in
// time. This proves single-flight with real goroutines rather than by reasoning
// about the SQL.
func TestClaimDerivedJobConcurrentIsSingleFlight(t *testing.T) {
	// Use an on-disk store: concurrent goroutines need to share real file locks.
	s := newStore(t)
	ctx := context.Background()

	const numJobs = 5
	for i := 0; i < numJobs; i++ {
		j := &store.DerivedJob{
			ID:        fmt.Sprintf("cj%d", i),
			Slug:      fmt.Sprintf("slug%d", i),
			Topic:     "t",
			Status:    store.DerivedStatusPending,
			Stage:     store.DerivedStageQueued,
			CreatedAt: int64(i + 1),
			UpdatedAt: int64(i + 1),
		}
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create job %d: %v", i, err)
		}
	}

	var (
		mu           sync.Mutex
		maxRunning   int
		totalClaimed int
	)

	const workers = 8
	var wg sync.WaitGroup
	now := int64(100)

	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				j, err := s.ClaimNextDerivedJob(ctx, now)
				if err != nil {
					t.Errorf("ClaimNextDerivedJob: %v", err)
					return
				}
				if j == nil {
					return
				}
				mu.Lock()
				totalClaimed++
				// Count how many jobs are currently running. Queried directly
				// rather than through a store method: there is no list-jobs API,
				// and the assertion is about rows, not about a public surface.
				var running int
				if err := s.db.QueryRowContext(ctx,
					`SELECT COUNT(*) FROM derived_jobs WHERE status = ?`,
					store.DerivedStatusRunning).Scan(&running); err != nil {
					t.Errorf("count running jobs: %v", err)
				}
				if running > maxRunning {
					maxRunning = running
				}
				mu.Unlock()
				// Finish the job so the next one can be claimed.
				_ = s.FinishDerivedJob(ctx, j.ID, store.DerivedStatusSucceeded, "", "{}", now+1)
			}
		}()
	}
	wg.Wait()

	if maxRunning > 1 {
		t.Errorf("max concurrent running jobs = %d, want <= 1 (single-flight)", maxRunning)
	}
	if totalClaimed != numJobs {
		t.Errorf("total claimed = %d, want %d", totalClaimed, numJobs)
	}
}

// --- ListDerivedJobsPaged ---

func TestListDerivedJobsPagedEmpty(t *testing.T) {
	s := newDerivedStore(t)
	result, err := s.ListDerivedJobsPaged(context.Background(), store.DerivedJobListFilter{})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if result.Total != 0 {
		t.Errorf("total = %d, want 0", result.Total)
	}
	if len(result.Jobs) != 0 {
		t.Errorf("got %d jobs, want 0", len(result.Jobs))
	}
}

func TestListDerivedJobsPagedFilterByStatus(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for _, j := range []*store.DerivedJob{
		{ID: "j1", Slug: "a", Topic: "t", Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone, CreatedAt: 1, UpdatedAt: 1},
		{ID: "j2", Slug: "b", Topic: "t", Status: store.DerivedStatusRunning, Stage: store.DerivedStageFilter, CreatedAt: 2, UpdatedAt: 2},
		{ID: "j3", Slug: "c", Topic: "t", Status: store.DerivedStatusPending, Stage: store.DerivedStageQueued, CreatedAt: 3, UpdatedAt: 3},
	} {
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", j.ID, err)
		}
	}
	// Claim j2 so it's actually running (needed because of single-flight constraint)
	// Actually we inserted it as running directly, which is fine for testing the listing.

	result, err := s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Status: "succeeded"})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if result.Total != 1 {
		t.Fatalf("total = %d, want 1", result.Total)
	}
	if result.Jobs[0].ID != "j1" {
		t.Errorf("jobs[0].id = %q, want j1", result.Jobs[0].ID)
	}
}

func TestListDerivedJobsPagedSearchQuery(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for _, j := range []*store.DerivedJob{
		{ID: "j1", Slug: "pricing", Topic: "Pricing and Fees", Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone, CreatedAt: 1, UpdatedAt: 1},
		{ID: "j2", Slug: "rust-basics", Topic: "Rust language", Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone, CreatedAt: 2, UpdatedAt: 2},
	} {
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", j.ID, err)
		}
	}

	// Search by topic.
	result, err := s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Query: "pricing"})
	if err != nil {
		t.Fatalf("list by topic: %v", err)
	}
	if result.Total != 1 || result.Jobs[0].ID != "j1" {
		t.Errorf("topic search: total=%d, jobs=%v", result.Total, result.Jobs)
	}

	// Search by slug.
	result, err = s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Query: "rust"})
	if err != nil {
		t.Fatalf("list by slug: %v", err)
	}
	if result.Total != 1 || result.Jobs[0].ID != "j2" {
		t.Errorf("slug search: total=%d, jobs=%v", result.Total, result.Jobs)
	}
}

func TestListDerivedJobsPagedPagination(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	// Create 5 jobs.
	for i := 0; i < 5; i++ {
		j := &store.DerivedJob{
			ID: fmt.Sprintf("j%d", i), Slug: fmt.Sprintf("s%d", i), Topic: "t",
			Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone,
			CreatedAt: int64(i + 1), UpdatedAt: int64(i + 1),
		}
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", j.ID, err)
		}
	}

	// Page 1: limit=2, offset=0.
	result, err := s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Limit: 2, Offset: 0})
	if err != nil {
		t.Fatalf("page 1: %v", err)
	}
	if result.Total != 5 {
		t.Errorf("total = %d, want 5", result.Total)
	}
	if len(result.Jobs) != 2 {
		t.Errorf("page 1 len = %d, want 2", len(result.Jobs))
	}

	// Page 2: limit=2, offset=2.
	result, err = s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Limit: 2, Offset: 2})
	if err != nil {
		t.Fatalf("page 2: %v", err)
	}
	if result.Total != 5 {
		t.Errorf("total = %d, want 5", result.Total)
	}
	if len(result.Jobs) != 2 {
		t.Errorf("page 2 len = %d, want 2", len(result.Jobs))
	}

	// Page 3: limit=2, offset=4 — only 1 left.
	result, err = s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{Limit: 2, Offset: 4})
	if err != nil {
		t.Fatalf("page 3: %v", err)
	}
	if result.Total != 5 {
		t.Errorf("total = %d, want 5", result.Total)
	}
	if len(result.Jobs) != 1 {
		t.Errorf("page 3 len = %d, want 1", len(result.Jobs))
	}
}

func TestListDerivedJobsPagedSorting(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	for _, j := range []*store.DerivedJob{
		{ID: "j1", Slug: "alpha", Topic: "A", Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone, CreatedAt: 1, UpdatedAt: 1},
		{ID: "j2", Slug: "beta", Topic: "B", Status: store.DerivedStatusSucceeded, Stage: store.DerivedStageDone, CreatedAt: 2, UpdatedAt: 2},
	} {
		if err := s.CreateDerivedJob(ctx, j); err != nil {
			t.Fatalf("create %s: %v", j.ID, err)
		}
	}

	// Sort by slug ASC.
	result, err := s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{SortBy: "slug", SortDir: "asc"})
	if err != nil {
		t.Fatalf("sort slug asc: %v", err)
	}
	if result.Jobs[0].Slug != "alpha" || result.Jobs[1].Slug != "beta" {
		t.Errorf("slug asc: got [%q, %q]", result.Jobs[0].Slug, result.Jobs[1].Slug)
	}

	// Sort by slug DESC.
	result, err = s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{SortBy: "slug", SortDir: "desc"})
	if err != nil {
		t.Fatalf("sort slug desc: %v", err)
	}
	if result.Jobs[0].Slug != "beta" || result.Jobs[1].Slug != "alpha" {
		t.Errorf("slug desc: got [%q, %q]", result.Jobs[0].Slug, result.Jobs[1].Slug)
	}

	// Unknown sort column falls back to created_at (DESC by default).
	result, err = s.ListDerivedJobsPaged(ctx, store.DerivedJobListFilter{SortBy: "unknown_col"})
	if err != nil {
		t.Fatalf("sort unknown: %v", err)
	}
	// Default is created_at DESC, so j2 (created_at=2) comes first.
	if result.Jobs[0].ID != "j2" {
		t.Errorf("unknown sort: first job = %q, want j2 (newest first)", result.Jobs[0].ID)
	}
}

// --- DeleteDerivedJob ---

func TestDeleteDerivedJobTerminal(t *testing.T) {
	for _, status := range []string{store.DerivedStatusSucceeded, store.DerivedStatusFailed} {
		t.Run(status, func(t *testing.T) {
			s := newDerivedStore(t)
			ctx := context.Background()
			j := &store.DerivedJob{
				ID: "j1", Slug: "a", Topic: "t", Status: store.DerivedStatusPending,
				Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1,
			}
			if err := s.CreateDerivedJob(ctx, j); err != nil {
				t.Fatalf("create: %v", err)
			}
			// Move to running then terminal.
			if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
				t.Fatalf("claim: %v", err)
			}
			if err := s.FinishDerivedJob(ctx, "j1", status, "err", "{}", 3); err != nil {
				t.Fatalf("finish: %v", err)
			}

			if err := s.DeleteDerivedJob(ctx, "j1"); err != nil {
				t.Fatalf("delete: %v", err)
			}
			// Verify job is gone.
			if _, err := s.GetDerivedJob(ctx, "j1"); !errors.Is(err, store.ErrNotFound) {
				t.Errorf("get after delete: err = %v, want ErrNotFound", err)
			}
		})
	}
}

func TestDeleteDerivedJobNonTerminal(t *testing.T) {
	s := newDerivedStore(t)
	ctx := context.Background()
	j := &store.DerivedJob{
		ID: "j1", Slug: "a", Topic: "t", Status: store.DerivedStatusPending,
		Stage: store.DerivedStageQueued, CreatedAt: 1, UpdatedAt: 1,
	}
	if err := s.CreateDerivedJob(ctx, j); err != nil {
		t.Fatalf("create: %v", err)
	}
	// Pending is not terminal — delete should return ErrNotFound.
	if err := s.DeleteDerivedJob(ctx, "j1"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("delete pending: err = %v, want ErrNotFound", err)
	}

	// Move to running — also not terminal.
	if _, err := s.ClaimNextDerivedJob(ctx, 2); err != nil {
		t.Fatalf("claim: %v", err)
	}
	if err := s.DeleteDerivedJob(ctx, "j1"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("delete running: err = %v, want ErrNotFound", err)
	}
}

func TestDeleteDerivedJobNotFound(t *testing.T) {
	s := newDerivedStore(t)
	if err := s.DeleteDerivedJob(context.Background(), "nonexistent"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("delete nonexistent: err = %v, want ErrNotFound", err)
	}
}
