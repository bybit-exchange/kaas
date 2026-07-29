package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/bybit-exchange/kaas/internal/store"
)

// SessionStore is the API layer's interface for chat session persistence.
// Defined as an independent interface to avoid extending store.Store and
// polluting queue/worker consumers that don't care about sessions.
type SessionStore interface {
	CreateSession(ctx context.Context, s *store.Session) error
	ListSessions(ctx context.Context) ([]*store.Session, error)
	GetSession(ctx context.Context, id string) (*store.Session, error)
	UpdateSessionTitle(ctx context.Context, id, title string, now int64) error
	DeleteSession(ctx context.Context, id string) error
	CreateMessage(ctx context.Context, m *store.Message) error
	ListMessages(ctx context.Context, sessionID string) ([]*store.Message, error)
	TouchSession(ctx context.Context, id string, now int64) error
}

// sessionDTO is the API response view of a chat session.
type sessionDTO struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	CreatedAt string `json:"created_at"` // ISO 8601 (RFC3339)
	UpdatedAt string `json:"updated_at"` // ISO 8601 (RFC3339)
}

// messageDTO is the API response view of a chat message.
type messageDTO struct {
	ID        string          `json:"id"`
	SessionID string          `json:"session_id"`
	Role      string          `json:"role"`
	Content   string          `json:"content"`
	Reasoning string          `json:"reasoning,omitempty"`
	Sources   json.RawMessage `json:"sources"`
	Usage     json.RawMessage `json:"usage,omitempty"`
	CreatedAt string          `json:"created_at"` // ISO 8601 (RFC3339)
}

func toSessionDTO(s *store.Session) sessionDTO {
	return sessionDTO{
		ID:        s.ID,
		Title:     s.Title,
		CreatedAt: time.UnixMilli(s.CreatedAt).UTC().Format(time.RFC3339),
		UpdatedAt: time.UnixMilli(s.UpdatedAt).UTC().Format(time.RFC3339),
	}
}

func toMessageDTO(m *store.Message) messageDTO {
	dto := messageDTO{
		ID:        m.ID,
		SessionID: m.SessionID,
		Role:      m.Role,
		Content:   m.Content,
		Reasoning: m.Reasoning,
		CreatedAt: time.UnixMilli(m.CreatedAt).UTC().Format(time.RFC3339),
	}
	if m.Sources != "" && json.Valid([]byte(m.Sources)) {
		dto.Sources = json.RawMessage(m.Sources)
	} else {
		dto.Sources = json.RawMessage("[]")
	}
	if m.Usage != "" && m.Usage != "{}" && json.Valid([]byte(m.Usage)) {
		dto.Usage = json.RawMessage(m.Usage)
	}
	return dto
}

// handleCreateSession serves POST /api/sessions.
func (s *Server) handleCreateSession(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req struct {
		Title string `json:"title"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	now := time.Now().UnixMilli()
	sess := &store.Session{
		ID:        uuid.NewString(),
		Title:     req.Title,
		CreatedAt: now,
		UpdatedAt: now,
	}
	if err := s.ss.CreateSession(r.Context(), sess); err != nil {
		writeErr(w, http.StatusInternalServerError, "create session: "+err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, toSessionDTO(sess))
}

// handleListSessions serves GET /api/sessions.
func (s *Server) handleListSessions(w http.ResponseWriter, r *http.Request) {
	sessions, err := s.ss.ListSessions(r.Context())
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list sessions: "+err.Error())
		return
	}
	dtos := make([]sessionDTO, 0, len(sessions))
	for _, sess := range sessions {
		dtos = append(dtos, toSessionDTO(sess))
	}
	writeJSON(w, http.StatusOK, map[string]any{"sessions": dtos})
}

// handleUpdateSession serves PATCH /api/sessions/{id}.
func (s *Server) handleUpdateSession(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req struct {
		Title string `json:"title"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}

	now := time.Now().UnixMilli()
	if err := s.ss.UpdateSessionTitle(r.Context(), id, req.Title, now); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeErr(w, http.StatusNotFound, "session not found")
			return
		}
		writeErr(w, http.StatusInternalServerError, "update session: "+err.Error())
		return
	}

	sess, err := s.ss.GetSession(r.Context(), id)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "get session: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, toSessionDTO(sess))
}

// handleDeleteSession serves DELETE /api/sessions/{id}.
func (s *Server) handleDeleteSession(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := s.ss.DeleteSession(r.Context(), id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeErr(w, http.StatusNotFound, "session not found")
			return
		}
		writeErr(w, http.StatusInternalServerError, "delete session: "+err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// handleListMessages serves GET /api/sessions/{id}/messages.
func (s *Server) handleListMessages(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	// Verify session exists first.
	if _, err := s.ss.GetSession(r.Context(), id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeErr(w, http.StatusNotFound, "session not found")
			return
		}
		writeErr(w, http.StatusInternalServerError, "get session: "+err.Error())
		return
	}

	messages, err := s.ss.ListMessages(r.Context(), id)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "list messages: "+err.Error())
		return
	}
	dtos := make([]messageDTO, 0, len(messages))
	for _, m := range messages {
		dtos = append(dtos, toMessageDTO(m))
	}
	writeJSON(w, http.StatusOK, map[string]any{"messages": dtos})
}
