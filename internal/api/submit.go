package api

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"

	fmtitle "github.com/bybit-exchange/kaas/internal/frontmatter"
	"github.com/bybit-exchange/kaas/internal/store"
)

// submitRequest is the POST /api/submit body.
//
// source selects the input kind:
//   - "paste"/"file": Content carries the text directly (file uploads are read
//     client-side into Content; Title may hold the filename).
//   - "url": URL is fetched server-side via the AI engine and its readable text
//     becomes the content.
type submitRequest struct {
	Source  string `json:"source"`
	Title   string `json:"title"`
	Content string `json:"content"`
	URL     string `json:"url"`
}

// submitResponse acknowledges an enqueued task.
type submitResponse struct {
	ID     string `json:"id"`
	Status string `json:"status"`
	Stage  string `json:"stage"`
}

// handleSubmit serves POST /api/submit: it resolves the content (fetching URLs
// when needed), writes the raw text under KBDir/raw/<id>.md, and enqueues a
// compile task. Duplicate content (same sha256) is rejected with 409.
func (s *Server) handleSubmit(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req submitRequest
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	req.Source = strings.TrimSpace(req.Source)
	req.Title = strings.TrimSpace(req.Title)

	content, title, err := s.resolveContent(r, &req)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}

	id := uuid.NewString()
	rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
	if err := os.MkdirAll(filepath.Dir(rawPath), 0o755); err != nil {
		writeErr(w, http.StatusInternalServerError, "create raw dir: "+err.Error())
		return
	}
	if err := os.WriteFile(rawPath, []byte(content), 0o644); err != nil {
		writeErr(w, http.StatusInternalServerError, "write raw content: "+err.Error())
		return
	}

	sum := sha256.Sum256([]byte(content))
	task := &store.Task{
		ID:          id,
		Source:      req.Source,
		Title:       title,
		RawPath:     rawPath,
		ContentHash: hex.EncodeToString(sum[:]),
		MaxAttempts: defaultMaxAttempts,
	}
	task.FileTitle = fmtitle.ExtractTitle([]byte(content))

	if err := s.q.Submit(r.Context(), task); err != nil {
		// Remove the orphan raw file we just wrote so it doesn't accumulate.
		_ = os.Remove(rawPath)
		if errors.Is(err, store.ErrDuplicate) {
			writeErr(w, http.StatusConflict, "content already submitted")
			return
		}
		writeErr(w, http.StatusInternalServerError, "enqueue task: "+err.Error())
		return
	}

	writeJSON(w, http.StatusAccepted, submitResponse{
		ID:     task.ID,
		Status: task.Status,
		Stage:  task.Stage,
	})
}

// resolveContent returns the content text and resolved title for a request,
// fetching the URL when source=="url". It validates required fields per source.
func (s *Server) resolveContent(r *http.Request, req *submitRequest) (content, title string, err error) {
	switch req.Source {
	case "url":
		u := strings.TrimSpace(req.URL)
		if u == "" {
			return "", "", errors.New("url is required when source=url")
		}
		fetched, ferr := s.br.FetchURL(r.Context(), u)
		if ferr != nil {
			return "", "", errors.New("fetch url: " + ferr.Error())
		}
		title = req.Title
		if title == "" {
			title = fetched.Title
		}
		return fetched.Content, title, nil
	case "paste", "file":
		if strings.TrimSpace(req.Content) == "" {
			return "", "", errors.New("content is required")
		}
		return req.Content, req.Title, nil
	case "":
		return "", "", errors.New("source is required")
	default:
		return "", "", errors.New("unknown source " + req.Source + " (want paste|file|url)")
	}
}
