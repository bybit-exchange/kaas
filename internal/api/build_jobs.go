package api

import (
	"errors"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/bybit-exchange/kaas/internal/store"
)

// buildJobDTO is the API view of a build job for list endpoints.
type buildJobDTO struct {
	ID        string `json:"id"`
	Source    string `json:"source"`
	Title     string `json:"title"`
	FileCount int    `json:"file_count"`
	Status    string `json:"status"`
	Error     string `json:"error,omitempty"`
	CreatedAt int64  `json:"created_at"`
	UpdatedAt int64  `json:"updated_at"`
}

// buildJobDetailDTO extends buildJobDTO with the tasks belonging to the job.
type buildJobDetailDTO struct {
	ID        string    `json:"id"`
	Source    string    `json:"source"`
	Title     string    `json:"title"`
	FileCount int       `json:"file_count"`
	Status    string    `json:"status"`
	Error     string    `json:"error,omitempty"`
	CreatedAt int64     `json:"created_at"`
	UpdatedAt int64     `json:"updated_at"`
	Tasks     []taskDTO `json:"tasks"`
}

// toBuildJobDTO projects a store.BuildJob to its API list view.
func toBuildJobDTO(j *store.BuildJob) buildJobDTO {
	return buildJobDTO{
		ID:        j.ID,
		Source:    j.Source,
		Title:     j.Title,
		FileCount: j.FileCount,
		Status:    j.Status,
		Error:     j.Error,
		CreatedAt: j.CreatedAt,
		UpdatedAt: j.UpdatedAt,
	}
}

// handleListBuildJobs serves GET /api/build-jobs.
func (s *Server) handleListBuildJobs(w http.ResponseWriter, r *http.Request) {
	if s.bjs == nil {
		writeErr(w, http.StatusNotImplemented, "build jobs are not available on this backend")
		return
	}
	now := time.Now().UnixMilli()
	if err := s.bjs.RefreshBuildJobStatuses(r.Context(), now); err != nil {
		writeErr(w, http.StatusInternalServerError, "refresh build job statuses: "+err.Error())
		return
	}
	f := store.BuildJobListFilter{
		Status:  r.URL.Query().Get("status"),
		Query:   r.URL.Query().Get("q"),
		SortBy:  r.URL.Query().Get("sort"),
		SortDir: r.URL.Query().Get("order"),
		Limit:   queryInt(r, "limit", 20),
		Offset:  queryInt(r, "offset", 0),
	}
	result, err := s.bjs.ListBuildJobsPaged(r.Context(), f)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list build jobs: "+err.Error())
		return
	}
	dtos := make([]buildJobDTO, 0, len(result.Jobs))
	for _, j := range result.Jobs {
		dtos = append(dtos, toBuildJobDTO(j))
	}
	writeJSON(w, http.StatusOK, map[string]any{"jobs": dtos, "total": result.Total})
}

// handleGetBuildJob serves GET /api/build-jobs/{id}.
func (s *Server) handleGetBuildJob(w http.ResponseWriter, r *http.Request) {
	if s.bjs == nil {
		writeErr(w, http.StatusNotImplemented, "build jobs are not available on this backend")
		return
	}
	id := r.PathValue("id")
	// Refresh status from child tasks before returning.
	now := time.Now().UnixMilli()
	if err := s.bjs.RefreshBuildJobStatus(r.Context(), id, now); err != nil {
		writeErr(w, http.StatusInternalServerError, "refresh build job status: "+err.Error())
		return
	}
	job, err := s.bjs.GetBuildJob(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "build job not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get build job: "+err.Error())
		return
	}
	tasks, err := s.st.ListTasksByBuildJob(r.Context(), id)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list tasks by build job: "+err.Error())
		return
	}
	taskDTOs := make([]taskDTO, 0, len(tasks))
	for _, t := range tasks {
		taskDTOs = append(taskDTOs, toDTO(t))
	}
	detail := buildJobDetailDTO{
		ID:        job.ID,
		Source:    job.Source,
		Title:     job.Title,
		FileCount: job.FileCount,
		Status:    job.Status,
		Error:     job.Error,
		CreatedAt: job.CreatedAt,
		UpdatedAt: job.UpdatedAt,
		Tasks:     taskDTOs,
	}
	writeJSON(w, http.StatusOK, detail)
}

// buildJobTerminalStatuses lists statuses from which a build job may be deleted.
var buildJobTerminalStatuses = map[string]bool{
	store.StatusSucceeded: true,
	store.StatusFailed:    true,
	store.StatusPartial:   true,
}

// handleDeleteBuildJob serves DELETE /api/build-jobs/{id}.
func (s *Server) handleDeleteBuildJob(w http.ResponseWriter, r *http.Request) {
	if s.bjs == nil {
		writeErr(w, http.StatusNotImplemented, "build jobs are not available on this backend")
		return
	}
	id := r.PathValue("id")

	// Refresh status from child tasks before checking terminal.
	now := time.Now().UnixMilli()
	if err := s.bjs.RefreshBuildJobStatus(r.Context(), id, now); err != nil {
		writeErr(w, http.StatusInternalServerError, "refresh build job status: "+err.Error())
		return
	}
	job, err := s.bjs.GetBuildJob(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "build job not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get build job: "+err.Error())
		return
	}
	if !buildJobTerminalStatuses[job.Status] {
		writeErr(w, http.StatusConflict, "build job is still active")
		return
	}

	// Delete all tasks belonging to this job: remove raw files (best-effort),
	// then delete the task row.
	tasks, err := s.st.ListTasksByBuildJob(r.Context(), id)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list tasks by build job: "+err.Error())
		return
	}
	for _, t := range tasks {
		if t.RawPath != "" {
			if rmErr := os.Remove(t.RawPath); rmErr != nil && !os.IsNotExist(rmErr) {
				log.Printf("WARN: failed to remove raw file %s: %v", t.RawPath, rmErr)
			}
		}
		if delErr := s.st.DeleteTask(r.Context(), t.ID); delErr != nil && !errors.Is(delErr, store.ErrNotFound) {
			log.Printf("WARN: failed to delete task %s: %v", t.ID, delErr)
		}
	}

	if err := s.bjs.DeleteBuildJob(r.Context(), id); errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "build job not found")
		return
	} else if err != nil {
		writeErr(w, http.StatusInternalServerError, "delete build job: "+err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
