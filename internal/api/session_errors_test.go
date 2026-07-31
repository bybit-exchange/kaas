package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// stubSessionStore is a SessionStore whose every call can be forced to fail, so
// the handlers' 400/404/500 mapping can be checked without a database.
type stubSessionStore struct {
	createErr   error
	listErr     error
	getErr      error
	updateErr   error
	deleteErr   error
	messagesErr error

	session  *store.Session
	messages []*store.Message
}

func (s *stubSessionStore) CreateSession(context.Context, *store.Session) error { return s.createErr }

func (s *stubSessionStore) ListSessions(context.Context) ([]*store.Session, error) {
	if s.listErr != nil {
		return nil, s.listErr
	}
	return nil, nil
}

func (s *stubSessionStore) GetSession(context.Context, string) (*store.Session, error) {
	if s.getErr != nil {
		return nil, s.getErr
	}
	if s.session == nil {
		return nil, store.ErrNotFound
	}
	return s.session, nil
}

func (s *stubSessionStore) UpdateSessionTitle(context.Context, string, string, int64) error {
	return s.updateErr
}

func (s *stubSessionStore) DeleteSession(context.Context, string) error { return s.deleteErr }

func (s *stubSessionStore) CreateMessage(context.Context, *store.Message) error { return nil }

func (s *stubSessionStore) ListMessages(context.Context, string) ([]*store.Message, error) {
	if s.messagesErr != nil {
		return nil, s.messagesErr
	}
	return s.messages, nil
}

func (s *stubSessionStore) TouchSession(context.Context, string, int64) error { return nil }

func newStubSessionServer(t *testing.T, ss SessionStore) *Server {
	t.Helper()
	return NewServer(&fakeQueue{}, &fakeStore{}, ss, &fakeBridge{}, Config{KBDir: t.TempDir()}, nil)
}

// TestSessionHandlerErrorMapping pins the HTTP status each store failure produces:
// a broken database must be a 500, a missing row a 404, and a bad payload a 400.
func TestSessionHandlerErrorMapping(t *testing.T) {
	boom := errors.New("database is locked")
	existing := &store.Session{ID: "s1", Title: "t", CreatedAt: 1, UpdatedAt: 1}

	tests := []struct {
		name       string
		ss         *stubSessionStore
		method     string
		target     string
		body       string
		wantStatus int
		wantInBody string
	}{
		{
			name:       "create with a malformed body",
			ss:         &stubSessionStore{},
			method:     http.MethodPost,
			target:     "/api/sessions",
			body:       `{"title":`,
			wantStatus: http.StatusBadRequest,
			wantInBody: "invalid request body",
		},
		{
			name:       "create with an unknown field",
			ss:         &stubSessionStore{},
			method:     http.MethodPost,
			target:     "/api/sessions",
			body:       `{"title":"x","admin":true}`,
			wantStatus: http.StatusBadRequest,
			wantInBody: "invalid request body",
		},
		{
			name:       "create fails in the store",
			ss:         &stubSessionStore{createErr: boom},
			method:     http.MethodPost,
			target:     "/api/sessions",
			body:       `{"title":"x"}`,
			wantStatus: http.StatusInternalServerError,
			wantInBody: "create session",
		},
		{
			name:       "list fails in the store",
			ss:         &stubSessionStore{listErr: boom},
			method:     http.MethodGet,
			target:     "/api/sessions",
			body:       "",
			wantStatus: http.StatusInternalServerError,
			wantInBody: "list sessions",
		},
		{
			name:       "update with a malformed body",
			ss:         &stubSessionStore{session: existing},
			method:     http.MethodPatch,
			target:     "/api/sessions/s1",
			body:       `nope`,
			wantStatus: http.StatusBadRequest,
			wantInBody: "invalid request body",
		},
		{
			name:       "update fails in the store",
			ss:         &stubSessionStore{updateErr: boom},
			method:     http.MethodPatch,
			target:     "/api/sessions/s1",
			body:       `{"title":"x"}`,
			wantStatus: http.StatusInternalServerError,
			wantInBody: "update session",
		},
		{
			name:       "update succeeds but the re-read fails",
			ss:         &stubSessionStore{getErr: boom},
			method:     http.MethodPatch,
			target:     "/api/sessions/s1",
			body:       `{"title":"x"}`,
			wantStatus: http.StatusInternalServerError,
			wantInBody: "get session",
		},
		{
			name:       "delete fails in the store",
			ss:         &stubSessionStore{deleteErr: boom},
			method:     http.MethodDelete,
			target:     "/api/sessions/s1",
			body:       "",
			wantStatus: http.StatusInternalServerError,
			wantInBody: "delete session",
		},
		{
			name:       "messages for an unknown session",
			ss:         &stubSessionStore{},
			method:     http.MethodGet,
			target:     "/api/sessions/s1/messages",
			body:       "",
			wantStatus: http.StatusNotFound,
			wantInBody: "session not found",
		},
		{
			name:       "messages when the session lookup fails",
			ss:         &stubSessionStore{getErr: boom},
			method:     http.MethodGet,
			target:     "/api/sessions/s1/messages",
			body:       "",
			wantStatus: http.StatusInternalServerError,
			wantInBody: "get session",
		},
		{
			name:       "messages when the listing fails",
			ss:         &stubSessionStore{session: existing, messagesErr: boom},
			method:     http.MethodGet,
			target:     "/api/sessions/s1/messages",
			body:       "",
			wantStatus: http.StatusInternalServerError,
			wantInBody: "list messages",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := newStubSessionServer(t, tc.ss)
			rec := do(t, s, tc.method, tc.target, tc.body)
			if rec.Code != tc.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", rec.Code, tc.wantStatus, rec.Body.String())
			}
			var resp struct {
				Error string `json:"error"`
			}
			if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
				t.Fatalf("error body is not JSON: %v (%s)", err, rec.Body.String())
			}
			if !strings.Contains(resp.Error, tc.wantInBody) {
				t.Errorf("error = %q, want it to mention %q", resp.Error, tc.wantInBody)
			}
		})
	}
}

// TestListSessionsEmptyIsArrayNotNull asserts an empty listing serialises as [],
// which the Web UI iterates without a null check.
func TestListSessionsEmptyIsArrayNotNull(t *testing.T) {
	s := newStubSessionServer(t, &stubSessionStore{})
	rec := do(t, s, http.MethodGet, "/api/sessions", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Body.String(); !strings.Contains(got, `"sessions":[]`) {
		t.Errorf("body = %s, want an empty array", got)
	}
}

// TestToMessageDTO pins the JSON shape the Web UI consumes: sources always an
// array (even if the stored blob is junk), usage omitted when absent or empty,
// reasoning omitted when empty, timestamps RFC3339 in UTC.
func TestToMessageDTO(t *testing.T) {
	tests := []struct {
		name        string
		msg         store.Message
		wantSources string
		wantUsage   string // "" → the key must be absent
	}{
		{
			name:        "valid sources and usage pass through",
			msg:         store.Message{Sources: `[{"id":1}]`, Usage: `{"tokens":5}`},
			wantSources: `[{"id":1}]`,
			wantUsage:   `{"tokens":5}`,
		},
		{
			name:        "empty sources become an array",
			msg:         store.Message{},
			wantSources: `[]`,
		},
		{
			name:        "invalid sources JSON becomes an array",
			msg:         store.Message{Sources: `{not json`},
			wantSources: `[]`,
		},
		{
			name:        "empty usage object is dropped",
			msg:         store.Message{Usage: `{}`},
			wantSources: `[]`,
		},
		{
			name:        "invalid usage JSON is dropped",
			msg:         store.Message{Usage: `{oops`},
			wantSources: `[]`,
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			tc.msg.ID = "m1"
			tc.msg.SessionID = "s1"
			tc.msg.Role = "assistant"
			tc.msg.CreatedAt = 1_700_000_000_000

			b, err := json.Marshal(toMessageDTO(&tc.msg))
			if err != nil {
				t.Fatalf("marshal DTO: %v", err)
			}
			var got map[string]json.RawMessage
			if err := json.Unmarshal(b, &got); err != nil {
				t.Fatalf("unmarshal DTO: %v", err)
			}
			if string(got["sources"]) != tc.wantSources {
				t.Errorf("sources = %s, want %s", got["sources"], tc.wantSources)
			}
			if tc.wantUsage == "" {
				if _, ok := got["usage"]; ok {
					t.Errorf("usage = %s, want the key omitted", got["usage"])
				}
			} else if string(got["usage"]) != tc.wantUsage {
				t.Errorf("usage = %s, want %s", got["usage"], tc.wantUsage)
			}
			if _, ok := got["reasoning"]; ok {
				t.Errorf("reasoning = %s, want the key omitted when empty", got["reasoning"])
			}
			if string(got["created_at"]) != `"2023-11-14T22:13:20Z"` {
				t.Errorf("created_at = %s, want the UTC RFC3339 rendering", got["created_at"])
			}
		})
	}
}

// TestToMessageDTOKeepsReasoning asserts a reasoning trace is forwarded verbatim.
func TestToMessageDTOKeepsReasoning(t *testing.T) {
	dto := toMessageDTO(&store.Message{ID: "m1", Reasoning: "step 1\nstep 2"})
	if dto.Reasoning != "step 1\nstep 2" {
		t.Errorf("reasoning = %q, want it preserved", dto.Reasoning)
	}
}
