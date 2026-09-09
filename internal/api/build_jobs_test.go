package api

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// --- handleListBuildJobs ---

func TestListBuildJobs(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Source: "paste", Title: "Job 1", FileCount: 1, Status: store.StatusSucceeded, CreatedAt: 1000, UpdatedAt: 2000},
			{ID: "bj2", Source: "file", Title: "Job 2", FileCount: 3, Status: store.StatusPending, CreatedAt: 3000, UpdatedAt: 4000},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	var out struct {
		Jobs  []buildJobDTO `json:"jobs"`
		Total int           `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 2 {
		t.Fatalf("total = %d, want 2", out.Total)
	}
	if len(out.Jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(out.Jobs))
	}
	if out.Jobs[0].ID != "bj1" || out.Jobs[1].ID != "bj2" {
		t.Errorf("unexpected job order: %+v", out.Jobs)
	}
}

func TestListBuildJobsFilterByStatus(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusSucceeded, Title: "Done"},
			{ID: "bj2", Status: store.StatusPending, Title: "Waiting"},
			{ID: "bj3", Status: store.StatusSucceeded, Title: "Also Done"},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs?status=succeeded", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		Jobs  []buildJobDTO `json:"jobs"`
		Total int           `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 2 {
		t.Fatalf("total = %d, want 2", out.Total)
	}
	if len(out.Jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(out.Jobs))
	}
}

func TestListBuildJobsSearchQuery(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Title: "Golang Guide", Status: store.StatusSucceeded},
			{ID: "bj2", Title: "React Tutorial", Status: store.StatusSucceeded},
			{ID: "bj3", Title: "Go Patterns", Status: store.StatusSucceeded},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs?q=golang", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		Jobs  []buildJobDTO `json:"jobs"`
		Total int           `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 1 {
		t.Fatalf("total = %d, want 1", out.Total)
	}
}

func TestListBuildJobsPagination(t *testing.T) {
	jobs := make([]*store.BuildJob, 5)
	for i := range jobs {
		jobs[i] = &store.BuildJob{ID: string(rune('a' + i)), Status: store.StatusSucceeded, Title: "Job"}
	}
	st := &fakeStore{buildJobs: jobs}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs?limit=2&offset=2", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		Jobs  []buildJobDTO `json:"jobs"`
		Total int           `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 5 {
		t.Fatalf("total = %d, want 5", out.Total)
	}
	if len(out.Jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(out.Jobs))
	}
}

func TestListBuildJobsEmpty(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		Jobs  []buildJobDTO `json:"jobs"`
		Total int           `json:"total"`
	}
	mustJSON(t, rec, &out)
	if out.Total != 0 {
		t.Fatalf("total = %d, want 0", out.Total)
	}
	if len(out.Jobs) != 0 {
		t.Fatalf("got %d jobs, want 0", len(out.Jobs))
	}
}

// --- handleGetBuildJob ---

func TestGetBuildJob(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Source: "file", Title: "My Upload", FileCount: 2, Status: store.StatusSucceeded, CreatedAt: 1000, UpdatedAt: 2000},
		},
		tasks: []*store.Task{
			{ID: "t1", BuildJobID: "bj1", Source: "file", Title: "doc1.md", Status: store.StatusSucceeded, Stage: store.StageDone},
			{ID: "t2", BuildJobID: "bj1", Source: "file", Title: "doc2.md", Status: store.StatusSucceeded, Stage: store.StageDone},
			{ID: "t3", BuildJobID: "other", Source: "file", Title: "unrelated.md", Status: store.StatusPending},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	var detail buildJobDetailDTO
	mustJSON(t, rec, &detail)
	if detail.ID != "bj1" {
		t.Errorf("ID = %q, want bj1", detail.ID)
	}
	if detail.Source != "file" {
		t.Errorf("Source = %q, want file", detail.Source)
	}
	if detail.Title != "My Upload" {
		t.Errorf("Title = %q, want My Upload", detail.Title)
	}
	if detail.FileCount != 2 {
		t.Errorf("FileCount = %d, want 2", detail.FileCount)
	}
	if detail.Status != store.StatusSucceeded {
		t.Errorf("Status = %q, want succeeded", detail.Status)
	}
	if len(detail.Tasks) != 2 {
		t.Fatalf("got %d tasks, want 2", len(detail.Tasks))
	}
	// Verify task IDs are correct (only tasks belonging to this job).
	taskIDs := map[string]bool{}
	for _, td := range detail.Tasks {
		taskIDs[td.ID] = true
	}
	if !taskIDs["t1"] || !taskIDs["t2"] {
		t.Errorf("unexpected task IDs: %v", taskIDs)
	}
	if taskIDs["t3"] {
		t.Error("task t3 should not be included (different build job)")
	}
}

func TestGetBuildJobNotFound(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs/nonexistent", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
}

func TestGetBuildJobIncludesError(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Source: "paste", Title: "Failing", Status: store.StatusFailed, Error: "all tasks failed"},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var detail buildJobDetailDTO
	mustJSON(t, rec, &detail)
	if detail.Error != "all tasks failed" {
		t.Errorf("Error = %q, want 'all tasks failed'", detail.Error)
	}
}

// --- handleDeleteBuildJob ---

func TestDeleteBuildJobSucceeded(t *testing.T) {
	raw := filepath.Join(t.TempDir(), "task.md")
	if err := os.WriteFile(raw, []byte("content"), 0o644); err != nil {
		t.Fatal(err)
	}
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusSucceeded},
		},
		tasks: []*store.Task{
			{ID: "t1", BuildJobID: "bj1", Status: store.StatusSucceeded, RawPath: raw},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
	// Build job should be removed.
	if len(st.buildJobs) != 0 {
		t.Errorf("build job still in store: %+v", st.buildJobs)
	}
	// Task should be removed.
	if len(st.tasks) != 0 {
		t.Errorf("task still in store: %+v", st.tasks)
	}
	// Raw file should be removed.
	if _, err := os.Stat(raw); !os.IsNotExist(err) {
		t.Error("raw file not removed")
	}
}

func TestDeleteBuildJobFailed(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusFailed},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteBuildJobPartial(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusPartial},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteBuildJobActiveReturns409(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusRunning},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteBuildJobPendingReturns409(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusPending},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteBuildJobNotFoundReturns404(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/nonexistent", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404; body=%s", rec.Code, rec.Body.String())
	}
}

func TestDeleteBuildJobCascadesMultipleTasks(t *testing.T) {
	tmpDir := t.TempDir()
	raw1 := filepath.Join(tmpDir, "t1.md")
	raw2 := filepath.Join(tmpDir, "t2.md")
	os.WriteFile(raw1, []byte("c1"), 0o644)
	os.WriteFile(raw2, []byte("c2"), 0o644)

	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Status: store.StatusSucceeded},
		},
		tasks: []*store.Task{
			{ID: "t1", BuildJobID: "bj1", Status: store.StatusSucceeded, RawPath: raw1},
			{ID: "t2", BuildJobID: "bj1", Status: store.StatusSucceeded, RawPath: raw2},
			{ID: "t3", BuildJobID: "other", Status: store.StatusSucceeded},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "DELETE", "/api/build-jobs/bj1", "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}
	// Only t3 should remain (belongs to a different build job).
	if len(st.tasks) != 1 || st.tasks[0].ID != "t3" {
		t.Errorf("tasks after delete: %+v, want only t3", st.tasks)
	}
	// Both raw files should be cleaned up.
	if _, err := os.Stat(raw1); !os.IsNotExist(err) {
		t.Error("raw1 not removed")
	}
	if _, err := os.Stat(raw2); !os.IsNotExist(err) {
		t.Error("raw2 not removed")
	}
}

// --- submit handler tests for build job creation ---

func TestSubmitPasteCreatesBuildJob(t *testing.T) {
	q := &fakeQueue{}
	st := &fakeStore{}
	s, _ := newTestServer(t, q, st, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit", `{"source":"paste","title":"My Note","content":"hello world"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	// A build job should have been created.
	if len(st.createdBuildJobs) != 1 {
		t.Fatalf("createdBuildJobs = %d, want 1", len(st.createdBuildJobs))
	}
	bj := st.createdBuildJobs[0]
	if bj.Source != "paste" {
		t.Errorf("BuildJob.Source = %q, want paste", bj.Source)
	}
	if bj.Title != "My Note" {
		t.Errorf("BuildJob.Title = %q, want My Note", bj.Title)
	}
	if bj.FileCount != 1 {
		t.Errorf("BuildJob.FileCount = %d, want 1", bj.FileCount)
	}
	if bj.Status != store.StatusPending {
		t.Errorf("BuildJob.Status = %q, want pending", bj.Status)
	}
	if bj.ID == "" {
		t.Error("BuildJob.ID is empty")
	}

	// The task should reference the build job.
	if q.submitted == nil {
		t.Fatal("no task submitted")
	}
	if q.submitted.BuildJobID != bj.ID {
		t.Errorf("Task.BuildJobID = %q, want %q", q.submitted.BuildJobID, bj.ID)
	}
}

func TestSubmitURLCreatesBuildJob(t *testing.T) {
	br := &fakeBridge{fetchResp: &bridge.FetchURLResponse{
		Title:   "Fetched Title",
		Content: "page body",
	}}
	q := &fakeQueue{}
	st := &fakeStore{}
	s, _ := newTestServer(t, q, st, br)

	rec := do(t, s, "POST", "/api/submit", `{"source":"url","url":"https://example.com"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	if len(st.createdBuildJobs) != 1 {
		t.Fatalf("createdBuildJobs = %d, want 1", len(st.createdBuildJobs))
	}
	bj := st.createdBuildJobs[0]
	if bj.Source != "url" {
		t.Errorf("BuildJob.Source = %q, want url", bj.Source)
	}
	if bj.Title != "Fetched Title" {
		t.Errorf("BuildJob.Title = %q, want Fetched Title", bj.Title)
	}
	if q.submitted.BuildJobID != bj.ID {
		t.Errorf("Task.BuildJobID = %q, want %q", q.submitted.BuildJobID, bj.ID)
	}
}

func TestSubmitDuplicateCleansBuildJob(t *testing.T) {
	q := &fakeQueue{submitErr: store.ErrDuplicate}
	st := &fakeStore{}
	s, _ := newTestServer(t, q, st, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit", `{"source":"paste","content":"dup"}`)
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409; body=%s", rec.Code, rec.Body.String())
	}

	// Build job should have been created then cleaned up (deleted).
	if len(st.createdBuildJobs) != 1 {
		t.Fatalf("createdBuildJobs = %d, want 1 (was created before submit failed)", len(st.createdBuildJobs))
	}
	// Build job should be deleted from the store on cleanup.
	if len(st.buildJobs) != 0 {
		t.Errorf("buildJobs in store = %d, want 0 (should be cleaned up)", len(st.buildJobs))
	}
}

func TestSubmitFilesCreatesBuildJob(t *testing.T) {
	q := &fakeQueue{}
	st := &fakeStore{}
	s, _ := newTestServer(t, q, st, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{
		{"doc1.md", "# Document 1"},
		{"doc2.md", "# Document 2"},
	})
	rec := doMultipart(t, s, body, ct)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 2 {
		t.Fatalf("uploaded = %d, want 2", len(resp.Uploaded))
	}

	if len(st.createdBuildJobs) != 1 {
		t.Fatalf("createdBuildJobs = %d, want 1", len(st.createdBuildJobs))
	}
	bj := st.createdBuildJobs[0]
	if bj.Source != "file" {
		t.Errorf("BuildJob.Source = %q, want file", bj.Source)
	}
	if bj.FileCount != 2 {
		t.Errorf("BuildJob.FileCount = %d, want 2", bj.FileCount)
	}

	// All submitted tasks should reference the same build job.
	if len(q.allSubmitted) != 2 {
		t.Fatalf("allSubmitted = %d, want 2", len(q.allSubmitted))
	}
	for i, task := range q.allSubmitted {
		if task.BuildJobID != bj.ID {
			t.Errorf("task[%d].BuildJobID = %q, want %q", i, task.BuildJobID, bj.ID)
		}
	}
}

func TestSubmitFilesAllFailDeletesBuildJob(t *testing.T) {
	q := &fakeQueue{submitErr: store.ErrDuplicate}
	st := &fakeStore{}
	s, _ := newTestServer(t, q, st, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{{"dup.md", "duplicate content"}})
	rec := doMultipart(t, s, body, ct)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	// Build job was created but all files failed → should be cleaned up.
	if len(st.createdBuildJobs) != 1 {
		t.Fatalf("createdBuildJobs = %d, want 1", len(st.createdBuildJobs))
	}
	if len(st.buildJobs) != 0 {
		t.Errorf("buildJobs in store = %d, want 0 (should be deleted when all fail)", len(st.buildJobs))
	}
}

// --- list build jobs response shape ---

func TestListBuildJobsResponseShape(t *testing.T) {
	st := &fakeStore{
		buildJobs: []*store.BuildJob{
			{ID: "bj1", Source: "paste", Title: "Test", FileCount: 1, Status: store.StatusPending, Error: "oops", CreatedAt: 100, UpdatedAt: 200},
		},
	}
	s, _ := newTestServer(t, &fakeQueue{}, st, &fakeBridge{})

	rec := do(t, s, "GET", "/api/build-jobs", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	// Parse as raw JSON to verify exact field names.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(rec.Body.Bytes(), &raw); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if _, ok := raw["jobs"]; !ok {
		t.Fatal("response missing 'jobs' key")
	}
	if _, ok := raw["total"]; !ok {
		t.Fatal("response missing 'total' key")
	}

	var out struct {
		Jobs []map[string]json.RawMessage `json:"jobs"`
	}
	mustJSON(t, rec, &out)
	if len(out.Jobs) != 1 {
		t.Fatalf("jobs = %d, want 1", len(out.Jobs))
	}
	job := out.Jobs[0]
	// Check required fields exist.
	for _, field := range []string{"id", "source", "title", "file_count", "status", "error", "created_at", "updated_at"} {
		if _, ok := job[field]; !ok {
			t.Errorf("job missing field %q", field)
		}
	}
}
