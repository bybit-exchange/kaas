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
