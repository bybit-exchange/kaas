package api

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/bybit-exchange/kaas/internal/store"
)

const maxContentBytes = 1 << 20 // 1 MiB

// taskDTO is the API view of a task. It omits internal fields (raw_path,
// content_hash, lease_owner, lease_expires_at) the UI has no use for.
type taskDTO struct {
	ID          string          `json:"id"`
	Source      string          `json:"source"`
	Title       string          `json:"title,omitempty"`
	FileTitle   string          `json:"file_title,omitempty"`
	Status      string          `json:"status"`
	Stage       string          `json:"stage"`
	Attempts    int             `json:"attempts"`
	MaxAttempts int             `json:"max_attempts"`
	Error       string          `json:"error,omitempty"`
	Result      json.RawMessage `json:"result,omitempty"`
	CreatedAt   int64           `json:"created_at"`
	UpdatedAt   int64           `json:"updated_at"`
}

// toDTO projects a store.Task to its API view. The stored Result is a JSON
// string blob; it is surfaced as raw JSON (or dropped if empty/invalid).
func toDTO(t *store.Task) taskDTO {
	d := taskDTO{
		ID:          t.ID,
		Source:      t.Source,
		Title:       t.Title,
		FileTitle:   t.FileTitle,
		Status:      t.Status,
		Stage:       t.Stage,
		Attempts:    t.Attempts,
		MaxAttempts: t.MaxAttempts,
		Error:       t.Error,
		CreatedAt:   t.CreatedAt,
		UpdatedAt:   t.UpdatedAt,
	}
	if t.Result != "" && json.Valid([]byte(t.Result)) {
		d.Result = json.RawMessage(t.Result)
	}
	return d
}

// handleListTasks serves GET /api/tasks?status=&q=&limit=&offset=.
func (s *Server) handleListTasks(w http.ResponseWriter, r *http.Request) {
	f := store.PagedListFilter{
		Status:  r.URL.Query().Get("status"),
		Query:   r.URL.Query().Get("q"),
		SortBy:  r.URL.Query().Get("sort"),
		SortDir: r.URL.Query().Get("order"),
		Limit:   queryInt(r, "limit", 20),
		Offset:  queryInt(r, "offset", 0),
	}
	result, err := s.st.ListTasksPaged(r.Context(), f)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list tasks: "+err.Error())
		return
	}
	dtos := make([]taskDTO, 0, len(result.Tasks))
	for _, t := range result.Tasks {
		dtos = append(dtos, toDTO(t))
	}
	writeJSON(w, http.StatusOK, map[string]any{"tasks": dtos, "total": result.Total})
}

// terminalStatuses lists statuses from which a task may be deleted.
var terminalStatuses = map[string]bool{
	store.StatusSucceeded: true,
	store.StatusFailed:    true,
	store.StatusCancelled: true,
}

// handleDeleteTask serves DELETE /api/tasks/{id}. Only terminal tasks may be
// deleted; running/pending tasks return 409.
func (s *Server) handleDeleteTask(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	task, err := s.st.GetTask(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get task: "+err.Error())
		return
	}
	if !terminalStatuses[task.Status] {
		writeErr(w, http.StatusConflict, "task is not in a terminal status")
		return
	}

	// Best-effort removal of the raw file; log but don't fail on error.
	if task.RawPath != "" {
		if err := os.Remove(task.RawPath); err != nil && !os.IsNotExist(err) {
			log.Printf("WARN: failed to remove raw file %s: %v", task.RawPath, err)
		}
	}

	if err := s.st.DeleteTask(r.Context(), id); errors.Is(err, store.ErrNotFound) {
		// TOCTOU: task was deleted or status changed between GetTask and DeleteTask.
		writeErr(w, http.StatusConflict, "task was modified concurrently")
		return
	} else if err != nil {
		writeErr(w, http.StatusInternalServerError, "delete task: "+err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// handleGetTask serves GET /api/tasks/{id}.
func (s *Server) handleGetTask(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	t, err := s.st.GetTask(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get task: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, toDTO(t))
}

// handleTaskContent serves GET /api/tasks/{id}/content. It reads the raw file
// associated with a task, returning up to 1 MiB of UTF-8 content.
func (s *Server) handleTaskContent(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	task, err := s.st.GetTask(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get task: "+err.Error())
		return
	}

	if task.RawPath == "" {
		writeErr(w, http.StatusNotFound, "no raw file")
		return
	}

	// Path traversal protection: resolved path must be under <KBDir>/raw/
	rawDir := filepath.Join(s.cfg.KBDir, "raw")
	absRaw, _ := filepath.Abs(rawDir)
	absFile, _ := filepath.Abs(filepath.Clean(task.RawPath))
	if !strings.HasPrefix(absFile, absRaw+string(filepath.Separator)) {
		writeErr(w, http.StatusForbidden, "path traversal denied")
		return
	}

	f, err := os.Open(absFile)
	if err != nil {
		writeErr(w, http.StatusNotFound, "file not found")
		return
	}
	defer f.Close()

	fi, err := f.Stat()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "stat file: "+err.Error())
		return
	}
	size := fi.Size()

	buf := make([]byte, maxContentBytes)
	n, err := io.ReadFull(f, buf)
	truncated := false
	if err == nil {
		// ReadFull filled the buffer completely — file is larger.
		truncated = true
	} else if err != io.ErrUnexpectedEOF && err != io.EOF {
		writeErr(w, http.StatusInternalServerError, "read file: "+err.Error())
		return
	}
	content := buf[:n]

	// If truncated mid-rune, back off to last valid UTF-8 boundary.
	if truncated {
		for n > 0 && !utf8.Valid(content) {
			n--
			content = buf[:n]
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"content":   string(content),
		"size":      size,
		"truncated": truncated,
	})
}
