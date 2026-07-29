package sqlite

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// newStore opens a fresh on-disk SQLite store in a temp dir and migrates it.
// On-disk (not :memory:) so concurrent connections share state.
func newStore(t *testing.T) *Store {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.db")
	s, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	if err := s.Migrate(context.Background()); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	return s
}

func mkTask(id, hash string, created int64) *store.Task {
	return &store.Task{
		ID:          id,
		Source:      "paste",
		ContentHash: hash,
		Status:      store.StatusPending,
		Stage:       store.StageQueued,
		MaxAttempts: 3,
		CreatedAt:   created,
		UpdatedAt:   created,
	}
}

func TestCreateAndGet(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	want := mkTask("t1", "h1", 100)
	want.Title = "hello"
	if err := s.CreateTask(ctx, want); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	got, err := s.GetTask(ctx, "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Title != "hello" || got.ContentHash != "h1" || got.Status != store.StatusPending {
		t.Fatalf("round-trip mismatch: %+v", got)
	}
}

func TestGetNotFound(t *testing.T) {
	s := newStore(t)
	if _, err := s.GetTask(context.Background(), "nope"); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestCreateDuplicateContentHash(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	if err := s.CreateTask(ctx, mkTask("t1", "dup", 1)); err != nil {
		t.Fatalf("first CreateTask: %v", err)
	}
	err := s.CreateTask(ctx, mkTask("t2", "dup", 2))
	if err != store.ErrDuplicate {
		t.Fatalf("want ErrDuplicate, got %v", err)
	}
}

func TestListTasksFilterAndOrder(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	// created ascending; ListTasks returns newest first.
	_ = s.CreateTask(ctx, mkTask("old", "h1", 100))
	_ = s.CreateTask(ctx, mkTask("new", "h2", 200))
	failed := mkTask("bad", "h3", 150)
	failed.Status = store.StatusFailed
	_ = s.CreateTask(ctx, failed)

	all, err := s.ListTasks(ctx, store.ListFilter{})
	if err != nil {
		t.Fatalf("ListTasks: %v", err)
	}
	if len(all) != 3 || all[0].ID != "new" || all[2].ID != "old" {
		t.Fatalf("expected newest-first [new,bad,old], got %v", ids(all))
	}

	only, err := s.ListTasks(ctx, store.ListFilter{Status: store.StatusFailed})
	if err != nil {
		t.Fatalf("ListTasks filtered: %v", err)
	}
	if len(only) != 1 || only[0].ID != "bad" {
		t.Fatalf("status filter failed, got %v", ids(only))
	}
}

func TestClaimNextOrderAndEmpty(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	_ = s.CreateTask(ctx, mkTask("b", "h2", 200))
	_ = s.CreateTask(ctx, mkTask("a", "h1", 100)) // older → claimed first

	got, err := s.ClaimNext(ctx, "w1", 1000, 2000)
	if err != nil {
		t.Fatalf("ClaimNext: %v", err)
	}
	if got == nil || got.ID != "a" {
		t.Fatalf("expected oldest 'a', got %v", got)
	}
	if got.Status != store.StatusRunning || got.LeaseOwner != "w1" ||
		got.LeaseExpiresAt != 2000 || got.Attempts != 1 {
		t.Fatalf("claim did not set running/lease/attempts: %+v", got)
	}

	// claim the second, then the queue is empty.
	if g2, _ := s.ClaimNext(ctx, "w1", 1000, 2000); g2 == nil || g2.ID != "b" {
		t.Fatalf("expected 'b' second, got %v", g2)
	}
	empty, err := s.ClaimNext(ctx, "w1", 1000, 2000)
	if err != nil {
		t.Fatalf("ClaimNext empty: %v", err)
	}
	if empty != nil {
		t.Fatalf("expected nil on empty queue, got %v", empty)
	}
}

// TestClaimNextConcurrentNoDoubleDelivery verifies the atomic claim never hands
// the same task to two workers.
func TestClaimNextConcurrentNoDoubleDelivery(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	const n = 50
	for i := 0; i < n; i++ {
		if err := s.CreateTask(ctx, mkTask(fmt.Sprintf("t%02d", i), fmt.Sprintf("h%02d", i), int64(i))); err != nil {
			t.Fatalf("CreateTask: %v", err)
		}
	}

	var mu sync.Mutex
	seen := map[string]int{}
	var wg sync.WaitGroup
	for w := 0; w < 8; w++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			owner := fmt.Sprintf("w%d", worker)
			for {
				task, err := s.ClaimNext(ctx, owner, 1, 99999)
				if err != nil {
					t.Errorf("ClaimNext: %v", err)
					return
				}
				if task == nil {
					return
				}
				mu.Lock()
				seen[task.ID]++
				mu.Unlock()
			}
		}(w)
	}
	wg.Wait()

	if len(seen) != n {
		t.Fatalf("expected %d distinct tasks claimed, got %d", n, len(seen))
	}
	for id, c := range seen {
		if c != 1 {
			t.Fatalf("task %s delivered %d times (double delivery)", id, c)
		}
	}
}

func TestHeartbeat(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	_ = s.CreateTask(ctx, mkTask("t1", "h1", 1))
	claimed, _ := s.ClaimNext(ctx, "w1", 10, 100)
	_ = claimed

	if err := s.Heartbeat(ctx, "t1", "w1", 500); err != nil {
		t.Fatalf("Heartbeat: %v", err)
	}
	got, _ := s.GetTask(ctx, "t1")
	if got.LeaseExpiresAt != 500 {
		t.Fatalf("lease not extended, got %d", got.LeaseExpiresAt)
	}

	// wrong owner → ErrNotFound, lease unchanged.
	if err := s.Heartbeat(ctx, "t1", "other", 999); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound for wrong owner, got %v", err)
	}
}

func TestMarkSucceeded(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	_ = s.CreateTask(ctx, mkTask("t1", "h1", 1))
	_, _ = s.ClaimNext(ctx, "w1", 10, 100)

	if err := s.MarkSucceeded(ctx, "t1", `{"articles":2}`, 20); err != nil {
		t.Fatalf("MarkSucceeded: %v", err)
	}
	got, _ := s.GetTask(ctx, "t1")
	if got.Status != store.StatusSucceeded || got.Stage != store.StageDone ||
		got.Result != `{"articles":2}` || got.LeaseOwner != "" || got.LeaseExpiresAt != 0 {
		t.Fatalf("succeeded state wrong: %+v", got)
	}
	// not running anymore → second call is a no-op → ErrNotFound.
	if err := s.MarkSucceeded(ctx, "t1", "x", 30); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound on non-running task, got %v", err)
	}
}

func TestMarkFailedRetryAndPermanent(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	_ = s.CreateTask(ctx, mkTask("t1", "h1", 1))
	_, _ = s.ClaimNext(ctx, "w1", 10, 100)

	// retry=true → back to pending.
	if err := s.MarkFailed(ctx, "t1", "boom", true, 20); err != nil {
		t.Fatalf("MarkFailed retry: %v", err)
	}
	got, _ := s.GetTask(ctx, "t1")
	if got.Status != store.StatusPending || got.Stage != store.StageQueued ||
		got.Error != "boom" || got.LeaseOwner != "" {
		t.Fatalf("retry state wrong: %+v", got)
	}

	// claim again, then fail permanently.
	_, _ = s.ClaimNext(ctx, "w1", 30, 200)
	if err := s.MarkFailed(ctx, "t1", "dead", false, 40); err != nil {
		t.Fatalf("MarkFailed permanent: %v", err)
	}
	got, _ = s.GetTask(ctx, "t1")
	if got.Status != store.StatusFailed {
		t.Fatalf("expected failed, got %s", got.Status)
	}
}

func TestRecoverExpired(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	_ = s.CreateTask(ctx, mkTask("expired", "h1", 1))
	_ = s.CreateTask(ctx, mkTask("fresh", "h2", 2))

	// expired: lease deadline 100. fresh: lease deadline 10000.
	_, _ = s.ClaimNext(ctx, "w1", 5, 100)
	_, _ = s.ClaimNext(ctx, "w1", 5, 10000)

	// now=500 → only "expired" recovered.
	n, err := s.RecoverExpired(ctx, 500)
	if err != nil {
		t.Fatalf("RecoverExpired: %v", err)
	}
	if n != 1 {
		t.Fatalf("expected 1 recovered, got %d", n)
	}
	exp, _ := s.GetTask(ctx, "expired")
	if exp.Status != store.StatusPending || exp.LeaseOwner != "" {
		t.Fatalf("expired not recovered: %+v", exp)
	}
	fresh, _ := s.GetTask(ctx, "fresh")
	if fresh.Status != store.StatusRunning {
		t.Fatalf("fresh should stay running: %+v", fresh)
	}
}

func ids(ts []*store.Task) []string {
	out := make([]string, len(ts))
	for i, t := range ts {
		out[i] = t.ID
	}
	return out
}

func TestSetStage(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	task := mkTask("t1", "h1", 100)
	if err := s.CreateTask(ctx, task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	// claim so it is running and owned
	claimed, err := s.ClaimNext(ctx, "w1", 200, 999999)
	if err != nil || claimed == nil {
		t.Fatalf("ClaimNext: task=%v err=%v", claimed, err)
	}
	if err := s.SetStage(ctx, "t1", "w1", store.StagePipeline, 300); err != nil {
		t.Fatalf("SetStage: %v", err)
	}
	got, err := s.GetTask(ctx, "t1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.Stage != store.StagePipeline || got.UpdatedAt != 300 {
		t.Fatalf("stage/updated not applied: %+v", got)
	}
}

func TestMigrateFileTitleIdempotent(t *testing.T) {
	s := newStore(t) // first Migrate already ran
	ctx := context.Background()

	// Second Migrate must not fail (idempotent).
	if err := s.Migrate(ctx); err != nil {
		t.Fatalf("second Migrate: %v", err)
	}

	// Third call for good measure.
	if err := s.Migrate(ctx); err != nil {
		t.Fatalf("third Migrate: %v", err)
	}
}

func TestCreateTaskFileTitle(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	task := mkTask("ft1", "fh1", 100)
	task.FileTitle = "my-document"
	if err := s.CreateTask(ctx, task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	got, err := s.GetTask(ctx, "ft1")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.FileTitle != "my-document" {
		t.Fatalf("FileTitle mismatch: want %q, got %q", "my-document", got.FileTitle)
	}
}

func TestCreateTaskFileTitleEmpty(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	task := mkTask("ft2", "fh2", 200)
	// FileTitle left as zero value
	if err := s.CreateTask(ctx, task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	got, err := s.GetTask(ctx, "ft2")
	if err != nil {
		t.Fatalf("GetTask: %v", err)
	}
	if got.FileTitle != "" {
		t.Fatalf("FileTitle should be empty, got %q", got.FileTitle)
	}
}

func TestListTasksPagedQueryTitle(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	t1 := mkTask("t1", "h1", 100)
	t1.Title = "golang tutorial"
	t2 := mkTask("t2", "h2", 200)
	t2.Title = "rust basics"
	t3 := mkTask("t3", "h3", 300)
	t3.Title = "advanced golang"

	_ = s.CreateTask(ctx, t1)
	_ = s.CreateTask(ctx, t2)
	_ = s.CreateTask(ctx, t3)

	res, err := s.ListTasksPaged(ctx, store.PagedListFilter{Query: "golang"})
	if err != nil {
		t.Fatalf("ListTasksPaged: %v", err)
	}
	if res.Total != 2 {
		t.Fatalf("expected Total=2, got %d", res.Total)
	}
	if len(res.Tasks) != 2 {
		t.Fatalf("expected 2 tasks, got %d", len(res.Tasks))
	}
	// newest first
	if res.Tasks[0].ID != "t3" || res.Tasks[1].ID != "t1" {
		t.Fatalf("unexpected order: %v", ids(res.Tasks))
	}
}

func TestListTasksPagedQueryFileTitle(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	t1 := mkTask("t1", "h1", 100)
	t1.FileTitle = "report-2024"
	t2 := mkTask("t2", "h2", 200)
	t2.FileTitle = "notes-2024"
	t3 := mkTask("t3", "h3", 300)
	t3.Title = "unrelated"

	_ = s.CreateTask(ctx, t1)
	_ = s.CreateTask(ctx, t2)
	_ = s.CreateTask(ctx, t3)

	res, err := s.ListTasksPaged(ctx, store.PagedListFilter{Query: "2024"})
	if err != nil {
		t.Fatalf("ListTasksPaged: %v", err)
	}
	if res.Total != 2 {
		t.Fatalf("expected Total=2, got %d", res.Total)
	}
	if res.Tasks[0].ID != "t2" || res.Tasks[1].ID != "t1" {
		t.Fatalf("unexpected results: %v", ids(res.Tasks))
	}
}

func TestListTasksPagedPagination(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		task := mkTask(fmt.Sprintf("t%d", i), fmt.Sprintf("h%d", i), int64(i*100))
		task.Title = "common"
		_ = s.CreateTask(ctx, task)
	}

	// limit=2, offset=1 → skip newest, get next 2
	res, err := s.ListTasksPaged(ctx, store.PagedListFilter{Query: "common", Limit: 2, Offset: 1})
	if err != nil {
		t.Fatalf("ListTasksPaged: %v", err)
	}
	if res.Total != 5 {
		t.Fatalf("expected Total=5, got %d", res.Total)
	}
	if len(res.Tasks) != 2 {
		t.Fatalf("expected 2 tasks, got %d", len(res.Tasks))
	}
	// ordered newest first: t4(400),t3(300),t2(200),t1(100),t0(0)
	// offset=1 → t3, t2
	if res.Tasks[0].ID != "t3" || res.Tasks[1].ID != "t2" {
		t.Fatalf("unexpected page: %v", ids(res.Tasks))
	}
}

func TestListTasksPagedStatusFilter(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	t1 := mkTask("t1", "h1", 100)
	t1.Title = "match"
	t1.Status = store.StatusSucceeded
	t2 := mkTask("t2", "h2", 200)
	t2.Title = "match"
	t2.Status = store.StatusPending

	_ = s.CreateTask(ctx, t1)
	_ = s.CreateTask(ctx, t2)

	res, err := s.ListTasksPaged(ctx, store.PagedListFilter{Status: store.StatusSucceeded, Query: "match"})
	if err != nil {
		t.Fatalf("ListTasksPaged: %v", err)
	}
	if res.Total != 1 {
		t.Fatalf("expected Total=1, got %d", res.Total)
	}
	if res.Tasks[0].ID != "t1" {
		t.Fatalf("unexpected task: %v", res.Tasks[0].ID)
	}
}

func TestDeleteTaskTerminal(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	for _, status := range []string{store.StatusSucceeded, store.StatusFailed, store.StatusCancelled} {
		task := mkTask("del-"+status, "h-"+status, 100)
		task.Status = status
		if err := s.CreateTask(ctx, task); err != nil {
			t.Fatalf("CreateTask(%s): %v", status, err)
		}
		if err := s.DeleteTask(ctx, "del-"+status); err != nil {
			t.Fatalf("DeleteTask(%s): %v", status, err)
		}
		if _, err := s.GetTask(ctx, "del-"+status); err != store.ErrNotFound {
			t.Fatalf("expected ErrNotFound after delete, got %v", err)
		}
	}
}

func TestDeleteTaskNonTerminal(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	for _, status := range []string{store.StatusPending, store.StatusRunning} {
		task := mkTask("keep-"+status, "h-"+status, 100)
		task.Status = status
		if err := s.CreateTask(ctx, task); err != nil {
			t.Fatalf("CreateTask(%s): %v", status, err)
		}
		if err := s.DeleteTask(ctx, "keep-"+status); err != store.ErrNotFound {
			t.Fatalf("DeleteTask(%s): want ErrNotFound, got %v", status, err)
		}
		// task still exists
		if _, err := s.GetTask(ctx, "keep-"+status); err != nil {
			t.Fatalf("task should still exist after failed delete: %v", err)
		}
	}
}

func TestDeleteTaskNotExist(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()

	if err := s.DeleteTask(ctx, "nonexistent"); err != store.ErrNotFound {
		t.Fatalf("want ErrNotFound for missing task, got %v", err)
	}
}

func TestSetStageWrongOwnerOrMissing(t *testing.T) {
	s := newStore(t)
	ctx := context.Background()
	if err := s.CreateTask(ctx, mkTask("t1", "h1", 100)); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}
	if _, err := s.ClaimNext(ctx, "w1", 200, 999999); err != nil {
		t.Fatalf("ClaimNext: %v", err)
	}
	// wrong owner
	if err := s.SetStage(ctx, "t1", "w2", store.StagePipeline, 300); err != store.ErrNotFound {
		t.Fatalf("wrong owner: want ErrNotFound, got %v", err)
	}
	// missing id
	if err := s.SetStage(ctx, "nope", "w1", store.StagePipeline, 300); err != store.ErrNotFound {
		t.Fatalf("missing id: want ErrNotFound, got %v", err)
	}
}
