package sqlite

import (
	"context"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// mkBuildJob creates a minimal build job for testing.
func mkBuildJob(id, source, title string, fileCount int, created int64) *store.BuildJob {
	return &store.BuildJob{
		ID:        id,
		Source:    source,
		Title:     title,
		FileCount: fileCount,
		Status:    store.StatusPending,
		CreatedAt: created,
		UpdatedAt: created,
	}
}

// mkTaskForJob creates a task linked to a build job.
func mkTaskForJob(id, hash, buildJobID string, status string, created int64) *store.Task {
	t := mkTask(id, hash, created)
	t.BuildJobID = buildJobID
	t.Status = status
	return t
}

// --- CreateBuildJob + GetBuildJob roundtrip ---

func TestBuildJobCreateAndGet(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	want := mkBuildJob("bj1", "file", "docs.zip", 5, 100)
	if err := s.CreateBuildJob(ctx, want); err != nil {
		t.Fatalf("CreateBuildJob: %v", err)
	}

	got, err := s.GetBuildJob(ctx, "bj1")
	if err != nil {
		t.Fatalf("GetBuildJob: %v", err)
	}
	if got.ID != "bj1" || got.Source != "file" || got.Title != "docs.zip" ||
		got.FileCount != 5 || got.Status != store.StatusPending ||
		got.CreatedAt != 100 || got.UpdatedAt != 100 {
		t.Fatalf("round-trip mismatch: %+v", got)
	}
}

func TestBuildJobGetNotFound(t *testing.T) {
	s := newStore(t)
	if _, err := s.GetBuildJob(context.Background(), "nonexistent"); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

// --- ListBuildJobsPaged ---

func TestBuildJobListPagedEmpty(t *testing.T) {
	s := newStore(t)
	result, err := s.ListBuildJobsPaged(context.Background(), store.BuildJobListFilter{})
	if err != nil {
		t.Fatalf("ListBuildJobsPaged: %v", err)
	}
	if result.Total != 0 {
		t.Errorf("total = %d, want 0", result.Total)
	}
	if len(result.Jobs) != 0 {
		t.Errorf("got %d jobs, want 0", len(result.Jobs))
	}
}

func TestBuildJobListPagedStatusFilter(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	j1 := mkBuildJob("bj1", "paste", "a", 1, 100)
	j1.Status = store.StatusSucceeded
	j2 := mkBuildJob("bj2", "file", "b", 2, 200)
	j2.Status = store.StatusPending
	j3 := mkBuildJob("bj3", "url", "c", 1, 300)
	j3.Status = store.StatusSucceeded

	_ = s.CreateBuildJob(ctx, j1)
	_ = s.CreateBuildJob(ctx, j2)
	_ = s.CreateBuildJob(ctx, j3)

	result, err := s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{Status: store.StatusSucceeded})
	if err != nil {
		t.Fatalf("ListBuildJobsPaged: %v", err)
	}
	if result.Total != 2 {
		t.Fatalf("total = %d, want 2", result.Total)
	}
	// Default sort is created_at DESC, so j3 first.
	if result.Jobs[0].ID != "bj3" || result.Jobs[1].ID != "bj1" {
		t.Fatalf("unexpected order: [%s, %s]", result.Jobs[0].ID, result.Jobs[1].ID)
	}
}

func TestBuildJobListPagedQuerySearch(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "golang tutorial", 1, 100))
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj2", "file", "rust basics", 1, 200))
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj3", "paste", "advanced golang", 1, 300))

	result, err := s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{Query: "golang"})
	if err != nil {
		t.Fatalf("ListBuildJobsPaged: %v", err)
	}
	if result.Total != 2 {
		t.Fatalf("total = %d, want 2", result.Total)
	}
	// Newest first: bj3, bj1.
	if result.Jobs[0].ID != "bj3" || result.Jobs[1].ID != "bj1" {
		t.Fatalf("unexpected results: [%s, %s]", result.Jobs[0].ID, result.Jobs[1].ID)
	}
}

func TestBuildJobListPagedSorting(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "alpha", 1, 100))
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj2", "file", "beta", 3, 200))

	// Sort by title ASC.
	result, err := s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{SortBy: "title", SortDir: "asc"})
	if err != nil {
		t.Fatalf("sort title asc: %v", err)
	}
	if result.Jobs[0].Title != "alpha" || result.Jobs[1].Title != "beta" {
		t.Errorf("title asc: [%q, %q]", result.Jobs[0].Title, result.Jobs[1].Title)
	}

	// Sort by title DESC.
	result, err = s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{SortBy: "title", SortDir: "desc"})
	if err != nil {
		t.Fatalf("sort title desc: %v", err)
	}
	if result.Jobs[0].Title != "beta" || result.Jobs[1].Title != "alpha" {
		t.Errorf("title desc: [%q, %q]", result.Jobs[0].Title, result.Jobs[1].Title)
	}

	// Sort by file_count DESC.
	result, err = s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{SortBy: "file_count", SortDir: "desc"})
	if err != nil {
		t.Fatalf("sort file_count desc: %v", err)
	}
	if result.Jobs[0].FileCount != 3 {
		t.Errorf("file_count desc: first job has file_count=%d, want 3", result.Jobs[0].FileCount)
	}

	// Unknown sort column falls back to created_at DESC.
	result, err = s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{SortBy: "unknown_col"})
	if err != nil {
		t.Fatalf("sort unknown: %v", err)
	}
	if result.Jobs[0].ID != "bj2" {
		t.Errorf("unknown sort fallback: first = %q, want bj2 (newest first)", result.Jobs[0].ID)
	}
}

func TestBuildJobListPagedPagination(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		j := mkBuildJob("bj"+string(rune('0'+i)), "paste", "job", 1, int64(i*100))
		_ = s.CreateBuildJob(ctx, j)
	}

	// Page 1: limit=2, offset=0.
	result, err := s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{Limit: 2, Offset: 0})
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
	result, err = s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{Limit: 2, Offset: 2})
	if err != nil {
		t.Fatalf("page 2: %v", err)
	}
	if len(result.Jobs) != 2 {
		t.Errorf("page 2 len = %d, want 2", len(result.Jobs))
	}

	// Page 3: limit=2, offset=4 — only 1 left.
	result, err = s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{Limit: 2, Offset: 4})
	if err != nil {
		t.Fatalf("page 3: %v", err)
	}
	if len(result.Jobs) != 1 {
		t.Errorf("page 3 len = %d, want 1", len(result.Jobs))
	}
}

func TestBuildJobListPagedStatusAndQuery(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	j1 := mkBuildJob("bj1", "paste", "golang notes", 1, 100)
	j1.Status = store.StatusSucceeded
	j2 := mkBuildJob("bj2", "paste", "golang guide", 1, 200)
	j2.Status = store.StatusPending
	j3 := mkBuildJob("bj3", "paste", "rust notes", 1, 300)
	j3.Status = store.StatusSucceeded

	_ = s.CreateBuildJob(ctx, j1)
	_ = s.CreateBuildJob(ctx, j2)
	_ = s.CreateBuildJob(ctx, j3)

	// Filter by status=succeeded AND query="golang" -> only bj1.
	result, err := s.ListBuildJobsPaged(ctx, store.BuildJobListFilter{
		Status: store.StatusSucceeded,
		Query:  "golang",
	})
	if err != nil {
		t.Fatalf("ListBuildJobsPaged: %v", err)
	}
	if result.Total != 1 || result.Jobs[0].ID != "bj1" {
		t.Fatalf("expected 1 result (bj1), got total=%d", result.Total)
	}
}

// --- DeleteBuildJob ---

func TestBuildJobDelete(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 1, 100))

	if err := s.DeleteBuildJob(ctx, "bj1"); err != nil {
		t.Fatalf("DeleteBuildJob: %v", err)
	}

	// Should be gone.
	if _, err := s.GetBuildJob(ctx, "bj1"); err != store.ErrNotFound {
		t.Fatalf("expected ErrNotFound after delete, got %v", err)
	}
}

func TestBuildJobDeleteNotFound(t *testing.T) {
	s := newStore(t)
	if err := s.DeleteBuildJob(context.Background(), "nonexistent"); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

// --- UpdateBuildJobFileCount ---

func TestBuildJobUpdateFileCount(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "file", "docs.zip", 0, 100))

	if err := s.UpdateBuildJobFileCount(ctx, "bj1", 7, 200); err != nil {
		t.Fatalf("UpdateBuildJobFileCount: %v", err)
	}

	got, err := s.GetBuildJob(ctx, "bj1")
	if err != nil {
		t.Fatalf("GetBuildJob: %v", err)
	}
	if got.FileCount != 7 {
		t.Errorf("file_count = %d, want 7", got.FileCount)
	}
	if got.UpdatedAt != 200 {
		t.Errorf("updated_at = %d, want 200", got.UpdatedAt)
	}
	// created_at should be unchanged.
	if got.CreatedAt != 100 {
		t.Errorf("created_at = %d, want 100 (should not change)", got.CreatedAt)
	}
}

func TestBuildJobUpdateFileCountNotFound(t *testing.T) {
	s := newStore(t)
	if err := s.UpdateBuildJobFileCount(context.Background(), "nonexistent", 5, 200); err == nil {
		t.Fatal("expected error for nonexistent job, got nil")
	}
}

// --- RefreshBuildJobStatuses (batch CTE) ---

func TestBuildJobRefreshStatusesPending(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// Build job with all tasks pending -> status should stay "pending".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusPending, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusPending, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusPending {
		t.Errorf("status = %q, want %q", got.Status, store.StatusPending)
	}
}

func TestBuildJobRefreshStatusesRunning(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// One task running -> job status should be "running".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusRunning, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusPending, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusRunning {
		t.Errorf("status = %q, want %q", got.Status, store.StatusRunning)
	}
}

func TestBuildJobRefreshStatusesSucceeded(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// All tasks succeeded -> job status should be "succeeded".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusSucceeded, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusSucceeded {
		t.Errorf("status = %q, want %q", got.Status, store.StatusSucceeded)
	}
	if got.UpdatedAt != 200 {
		t.Errorf("updated_at = %d, want 200", got.UpdatedAt)
	}
}

func TestBuildJobRefreshStatusesFailed(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// All tasks failed -> job status should be "failed".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusFailed, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusFailed, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusFailed {
		t.Errorf("status = %q, want %q", got.Status, store.StatusFailed)
	}
}

func TestBuildJobRefreshStatusesPartial(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// Mix of succeeded and failed -> job status should be "partial".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 3, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusFailed, 102))
	_ = s.CreateTask(ctx, mkTaskForJob("t3", "h3", "bj1", store.StatusSucceeded, 103))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusPartial {
		t.Errorf("status = %q, want %q", got.Status, store.StatusPartial)
	}
}

func TestBuildJobRefreshStatusesSkipsTerminal(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// A succeeded build job should not be changed, even if we call refresh.
	j := mkBuildJob("bj1", "paste", "test", 1, 100)
	j.Status = store.StatusSucceeded
	_ = s.CreateBuildJob(ctx, j)
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusFailed, 101))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusSucceeded {
		t.Errorf("terminal job changed: status = %q, want %q", got.Status, store.StatusSucceeded)
	}
	// updated_at should not change because the job was already terminal.
	if got.UpdatedAt != 100 {
		t.Errorf("terminal job updated_at changed: %d, want 100", got.UpdatedAt)
	}
}

func TestBuildJobRefreshStatusesMultipleJobs(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// Two pending build jobs, each with different child task statuses.
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "job1", 1, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj2", "file", "job2", 2, 200))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj2", store.StatusFailed, 201))
	_ = s.CreateTask(ctx, mkTaskForJob("t3", "h3", "bj2", store.StatusSucceeded, 202))

	if err := s.RefreshBuildJobStatuses(ctx, 300); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got1, _ := s.GetBuildJob(ctx, "bj1")
	if got1.Status != store.StatusSucceeded {
		t.Errorf("bj1 status = %q, want %q", got1.Status, store.StatusSucceeded)
	}

	got2, _ := s.GetBuildJob(ctx, "bj2")
	if got2.Status != store.StatusPartial {
		t.Errorf("bj2 status = %q, want %q", got2.Status, store.StatusPartial)
	}
}

// --- RefreshBuildJobStatus (single job) ---

func TestBuildJobRefreshSingleStatusRunning(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusRunning, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusSucceeded, 102))

	if err := s.RefreshBuildJobStatus(ctx, "bj1", 200); err != nil {
		t.Fatalf("RefreshBuildJobStatus: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusRunning {
		t.Errorf("status = %q, want %q", got.Status, store.StatusRunning)
	}
}

func TestBuildJobRefreshSingleStatusSucceeded(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusSucceeded, 102))

	if err := s.RefreshBuildJobStatus(ctx, "bj1", 200); err != nil {
		t.Fatalf("RefreshBuildJobStatus: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusSucceeded {
		t.Errorf("status = %q, want %q", got.Status, store.StatusSucceeded)
	}
}

func TestBuildJobRefreshSingleStatusPartial(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusFailed, 102))

	if err := s.RefreshBuildJobStatus(ctx, "bj1", 200); err != nil {
		t.Fatalf("RefreshBuildJobStatus: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusPartial {
		t.Errorf("status = %q, want %q", got.Status, store.StatusPartial)
	}
}

func TestBuildJobRefreshSingleStatusFailed(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusFailed, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusCancelled, 102))

	if err := s.RefreshBuildJobStatus(ctx, "bj1", 200); err != nil {
		t.Fatalf("RefreshBuildJobStatus: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusFailed {
		t.Errorf("status = %q, want %q", got.Status, store.StatusFailed)
	}
}

func TestBuildJobRefreshSingleSkipsTerminal(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	j := mkBuildJob("bj1", "paste", "test", 1, 100)
	j.Status = store.StatusFailed
	_ = s.CreateBuildJob(ctx, j)
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))

	if err := s.RefreshBuildJobStatus(ctx, "bj1", 200); err != nil {
		t.Fatalf("RefreshBuildJobStatus: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusFailed {
		t.Errorf("terminal job changed: status = %q, want %q", got.Status, store.StatusFailed)
	}
	if got.UpdatedAt != 100 {
		t.Errorf("terminal job updated_at changed: %d, want 100", got.UpdatedAt)
	}
}

// --- ListTasksByBuildJob ---

func TestBuildJobListTasksOrdered(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "file", "docs.zip", 3, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t3", "h3", "bj1", store.StatusPending, 300))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusRunning, 200))

	tasks, err := s.ListTasksByBuildJob(ctx, "bj1")
	if err != nil {
		t.Fatalf("ListTasksByBuildJob: %v", err)
	}
	if len(tasks) != 3 {
		t.Fatalf("got %d tasks, want 3", len(tasks))
	}
	// Should be ordered by created_at ASC: t1(100), t2(200), t3(300).
	if tasks[0].ID != "t1" || tasks[1].ID != "t2" || tasks[2].ID != "t3" {
		t.Errorf("order mismatch: got [%s, %s, %s], want [t1, t2, t3]",
			tasks[0].ID, tasks[1].ID, tasks[2].ID)
	}
}

func TestBuildJobListTasksEmpty(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 0, 100))

	tasks, err := s.ListTasksByBuildJob(ctx, "bj1")
	if err != nil {
		t.Fatalf("ListTasksByBuildJob: %v", err)
	}
	if len(tasks) != 0 {
		t.Errorf("got %d tasks, want 0", len(tasks))
	}
}

func TestBuildJobListTasksExcludesLegacyTasks(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 1, 100))
	// Task linked to the build job.
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusPending, 101))
	// Legacy task with empty build_job_id.
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "", store.StatusPending, 102))
	// Task linked to a different build job.
	_ = s.CreateTask(ctx, mkTaskForJob("t3", "h3", "bj-other", store.StatusPending, 103))

	tasks, err := s.ListTasksByBuildJob(ctx, "bj1")
	if err != nil {
		t.Fatalf("ListTasksByBuildJob: %v", err)
	}
	if len(tasks) != 1 {
		t.Fatalf("got %d tasks, want 1", len(tasks))
	}
	if tasks[0].ID != "t1" {
		t.Errorf("unexpected task: %s", tasks[0].ID)
	}
}

func TestBuildJobListTasksLegacyEmptyID(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// Create legacy tasks with build_job_id = "".
	_ = s.CreateTask(ctx, mkTask("legacy1", "lh1", 100))
	_ = s.CreateTask(ctx, mkTask("legacy2", "lh2", 200))

	// Querying with empty string should return legacy tasks (this is the SQL behavior),
	// but the API layer should never call ListTasksByBuildJob with an empty ID.
	// Querying with a real build job ID should NOT return legacy tasks.
	tasks, err := s.ListTasksByBuildJob(ctx, "nonexistent-bj")
	if err != nil {
		t.Fatalf("ListTasksByBuildJob: %v", err)
	}
	if len(tasks) != 0 {
		t.Errorf("got %d tasks for nonexistent build job, want 0", len(tasks))
	}
}

// --- RefreshBuildJobStatuses with cancelled tasks ---

func TestBuildJobRefreshStatusesCancelledAndFailed(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// All cancelled + failed, none succeeded -> "failed".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusCancelled, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusFailed, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusFailed {
		t.Errorf("status = %q, want %q", got.Status, store.StatusFailed)
	}
}

func TestBuildJobRefreshStatusesCancelledAndSucceeded(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	// Some cancelled + some succeeded, none pending/running -> "partial".
	_ = s.CreateBuildJob(ctx, mkBuildJob("bj1", "paste", "test", 2, 100))
	_ = s.CreateTask(ctx, mkTaskForJob("t1", "h1", "bj1", store.StatusSucceeded, 101))
	_ = s.CreateTask(ctx, mkTaskForJob("t2", "h2", "bj1", store.StatusCancelled, 102))

	if err := s.RefreshBuildJobStatuses(ctx, 200); err != nil {
		t.Fatalf("RefreshBuildJobStatuses: %v", err)
	}

	got, _ := s.GetBuildJob(ctx, "bj1")
	if got.Status != store.StatusPartial {
		t.Errorf("status = %q, want %q", got.Status, store.StatusPartial)
	}
}
