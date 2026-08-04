package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/bybit-exchange/kaas/internal/kbpath"
	"github.com/bybit-exchange/kaas/internal/store"
)

// deriveRequest is the POST /api/derive body. KBDir is server-side config, so a
// client cannot point a derive at another directory.
type deriveRequest struct {
	Topic string `json:"topic"`
	Slug  string `json:"slug,omitempty"`
	Model string `json:"model,omitempty"`
}

// derivedKBSummary is one entry of GET /api/derived, read from the KB's manifest.
type derivedKBSummary struct {
	Slug         string `json:"slug"`
	Topic        string `json:"topic"`
	CreatedAt    string `json:"created_at"`
	ArticleCount int    `json:"article_count"`
}

// deriveJobResponse is the GET /api/derive/{id} body. Result is the raw JSON the
// engine returned, forwarded as an object rather than a quoted string.
type deriveJobResponse struct {
	ID        string          `json:"id"`
	Slug      string          `json:"slug"`
	Topic     string          `json:"topic"`
	Status    string          `json:"status"`
	Stage     string          `json:"stage"`
	Error     string          `json:"error,omitempty"`
	Result    json.RawMessage `json:"result,omitempty"`
	CreatedAt int64           `json:"created_at"`
	UpdatedAt int64           `json:"updated_at"`
}

// slugFillerRe collapses runs of non-slug characters, mirroring normalise_slug in
// py/src/kb_ai/derive/_layout.py. Both sides must agree, or a slug the UI shows
// differs from the directory the engine creates.
var slugFillerRe = regexp.MustCompile(`[^a-z0-9]+`)

const slugMaxLen = 40

// slugFromTopic derives a slug from a topic string (spec C2).
func slugFromTopic(topic string) string {
	flat := slugFillerRe.ReplaceAllString(strings.ToLower(topic), "-")
	flat = strings.Trim(flat, "-")
	if len(flat) > slugMaxLen {
		flat = flat[:slugMaxLen]
	}
	return strings.Trim(flat, "-")
}

// handleDerive serves POST /api/derive: it records the job and returns
// immediately. The compile happens in the derive runner, so this never blocks —
// and consequently has no volume gate, since there is nobody to prompt (H5).
func (s *Server) handleDerive(w http.ResponseWriter, r *http.Request) {
	if s.js == nil {
		writeErr(w, http.StatusNotImplemented, "derive is not available on this backend")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req deriveRequest
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}
	if strings.TrimSpace(req.Topic) == "" {
		writeErr(w, http.StatusBadRequest, "topic is required")
		return
	}

	slug := req.Slug
	if slug == "" {
		slug = slugFromTopic(req.Topic)
	}
	if !kbpath.ValidSlug(slug) {
		writeErr(w, http.StatusBadRequest,
			"invalid slug: expected 1-40 lower-case alphanumeric characters or dashes; "+
				"pass an explicit slug for a topic that does not produce one")
		return
	}

	// Refuse a slug whose directory already exists. The HTTP path has no --force:
	// replacing a compiled KB from a web form, with no prompt, is not something
	// to make easy.
	if _, err := kbpath.Resolve(s.cfg.KBDir, slug); err == nil {
		writeErr(w, http.StatusConflict,
			"a derived knowledge base named "+slug+" already exists")
		return
	} else if !errors.Is(err, kbpath.ErrUnknownKB) {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}

	now := time.Now().UnixMilli()
	job := &store.DerivedJob{
		ID:        uuid.NewString(),
		Slug:      slug,
		Topic:     req.Topic,
		Model:     req.Model,
		Status:    store.DerivedStatusPending,
		Stage:     store.DerivedStageQueued,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := s.js.CreateDerivedJob(r.Context(), job); err != nil {
		if errors.Is(err, store.ErrDerivedJobExists) {
			writeErr(w, http.StatusConflict,
				"a derive for "+slug+" is already queued or running")
			return
		}
		writeErr(w, http.StatusInternalServerError, "create derive job: "+err.Error())
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]string{"job_id": job.ID, "slug": slug})
}

// handleGetDeriveJob serves GET /api/derive/{id}.
func (s *Server) handleGetDeriveJob(w http.ResponseWriter, r *http.Request) {
	if s.js == nil {
		writeErr(w, http.StatusNotImplemented, "derive is not available on this backend")
		return
	}
	job, err := s.js.GetDerivedJob(r.Context(), r.PathValue("id"))
	if errors.Is(err, store.ErrNotFound) {
		writeErr(w, http.StatusNotFound, "derive job not found")
		return
	}
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get derive job: "+err.Error())
		return
	}
	resp := deriveJobResponse{
		ID:        job.ID,
		Slug:      job.Slug,
		Topic:     job.Topic,
		Status:    job.Status,
		Stage:     job.Stage,
		Error:     job.Error,
		CreatedAt: job.CreatedAt,
		UpdatedAt: job.UpdatedAt,
	}
	// The stored blob is the engine's own JSON; forward it as an object. A blob
	// that is not valid JSON is dropped rather than breaking the response.
	if job.Result != "" && json.Valid([]byte(job.Result)) {
		resp.Result = json.RawMessage(job.Result)
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleListDerived serves GET /api/derived, reading each derived KB's manifest.
// Filesystem-only, so it works even without a job store.
func (s *Server) handleListDerived(w http.ResponseWriter, r *http.Request) {
	slugs, err := kbpath.ListSlugs(s.cfg.KBDir)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list derived: "+err.Error())
		return
	}
	out := make([]derivedKBSummary, 0, len(slugs))
	for _, slug := range slugs {
		dir := filepath.Join(s.cfg.KBDir, kbpath.DerivedDirName, slug)
		var manifest struct {
			Slug      string `json:"slug"`
			Topic     string `json:"topic"`
			CreatedAt string `json:"created_at"`
		}
		raw, readErr := os.ReadFile(filepath.Join(dir, "manifest.json"))
		if readErr == nil {
			_ = json.Unmarshal(raw, &manifest)
		}
		out = append(out, derivedKBSummary{
			Slug:         slug,
			Topic:        manifest.Topic,
			CreatedAt:    manifest.CreatedAt,
			ArticleCount: countWikiArticles(dir),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"kbs": out})
}

// countWikiArticles counts *.md files under dir/wiki. _offtopic/ lives outside
// wiki/, so it is excluded by construction (D4).
func countWikiArticles(kbDir string) int {
	count := 0
	_ = filepath.WalkDir(filepath.Join(kbDir, "wiki"), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil // an unreadable subtree costs its count, not the response
		}
		if d.Type().IsRegular() && strings.HasSuffix(strings.ToLower(d.Name()), ".md") {
			count++
		}
		return nil
	})
	return count
}
