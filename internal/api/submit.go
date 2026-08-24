package api

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

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
//
// Date is optional and says when the document was written, not when it was
// submitted: an operator backfilling last quarter's plan needs the writer to
// order it behind this quarter's, which the ingest clock cannot express.
type submitRequest struct {
	Source  string `json:"source"`
	Title   string `json:"title"`
	Content string `json:"content"`
	URL     string `json:"url"`
	Date    string `json:"date"`
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

	// The bytes on disk differ from the bytes submitted, and everything below
	// still measures the submitted ones. raw/<uuid>.md was never the only
	// verbatim copy -- distill already prepends a provenance comment to what it
	// ingests -- but the hash and the file title are load-bearing and must not
	// see the stamp.
	raw, err := rawDocument(content, req.Source, title, req.Date, time.Now())
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
	if err := os.WriteFile(rawPath, raw, 0o644); err != nil {
		writeErr(w, http.StatusInternalServerError, "write raw content: "+err.Error())
		return
	}

	// Hashed as submitted, not as written: tasks.content_hash carries a unique
	// index and is the whole dedup mechanism, so folding a stamp time into it
	// would make every resubmission of one document unique and leave the 409
	// below unreachable.
	sum := sha256.Sum256([]byte(content))
	task := &store.Task{
		ID:          id,
		Source:      req.Source,
		Title:       title,
		RawPath:     rawPath,
		ContentHash: hex.EncodeToString(sum[:]),
		MaxAttempts: defaultMaxAttempts,
	}
	// From the content as submitted, for the same reason: ExtractTitle reads a
	// leading "title:", which rawDocument may have just written, so computing it
	// from raw would echo the request's own title back as the document's.
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

// dateOnlyLayout is an authored day with no time of day. Kept distinct from
// RFC3339 on the way out as well as in: rendering it as a midnight stamp would
// assert a time the submitter never gave.
const dateOnlyLayout = "2006-01-02"

// rawDocument returns the bytes to persist under raw/: the submitted content
// carrying a date the write phase can order it by.
//
// Precedence is caller, then document, then clock:
//
//   - an explicit request date wins outright, including over a date the document
//     declares. It is the one signal a human typed for this ingest.
//   - otherwise a document that may already date itself keeps whatever it has and
//     is stored verbatim. Overwriting an authored date with the ingest clock is the
//     defect this whole change exists to fix, so the stamp must never reach one --
//     which is why "may": frontmatter the writer cannot read counts here too, and
//     such a document reaches the write phase undated rather than misdated (RT10).
//   - otherwise now(), because a document with no date at all is worse for the
//     writer than an approximate one: it has to be told the ordering is unknown.
func rawDocument(content, source, title, date string, now time.Time) ([]byte, error) {
	value, err := normaliseDate(date, now)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(date) == "" && fmtitle.MayHaveDate([]byte(content)) {
		return []byte(content), nil
	}
	return fmtitle.WithDate([]byte(content), value,
		fmtitle.Field{Key: "source", Value: source},
		fmtitle.Field{Key: "title", Value: title}), nil
}

// normaliseDate accepts an authored day or an RFC3339 stamp and returns it in the
// spelling it arrived in, stamping now() when the field is absent. An
// unparseable date is the caller's to fix, so it is an error rather than a
// silent fallback to the clock -- a typo would otherwise be indistinguishable
// from having supplied nothing.
func normaliseDate(date string, now time.Time) (string, error) {
	date = strings.TrimSpace(date)
	if date == "" {
		return now.UTC().Format(time.RFC3339), nil
	}
	for _, layout := range []string{dateOnlyLayout, time.RFC3339} {
		t, err := time.Parse(layout, date)
		if err != nil {
			continue
		}
		// Go parses year zero; PyYAML's timestamp constructor raises ValueError on
		// it, and one such document under raw/ takes the document catalog down for
		// every other document with it. Rejected at the door, where the caller can
		// still fix it.
		if t.Year() < 1 {
			return "", errors.New("date year must be 1 or later")
		}
		return date, nil
	}
	return "", errors.New("date must be YYYY-MM-DD or RFC3339, e.g. 2026-06-01 or 2026-06-01T09:00:00Z")
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
