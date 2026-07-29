package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/store/sqlite"
)

// newSessionTestServer creates a Server backed by a real in-memory SQLite store
// (with schema migrated) and a given ChatBridge. It is used exclusively by
// session integration tests that exercise the full HTTP → store round-trip.
func newSessionTestServer(t *testing.T, br ChatBridge) *Server {
	t.Helper()
	st, err := sqlite.Open(":memory:")
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	t.Cleanup(func() { st.Close() })
	if err := st.Migrate(context.Background()); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	s := NewServer(&fakeQueue{}, st, st, br, Config{KBDir: t.TempDir(), Model: "test-model"}, nil)
	return s
}

// doSession is a convenience wrapper for session tests that uses the shared server.
func doSession(t *testing.T, s *Server, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	return do(t, s, method, target, body)
}

// --- Session CRUD ---

func TestSessionCreate(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})

	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"My Session"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201; body=%s", rec.Code, rec.Body.String())
	}

	var dto sessionDTO
	mustJSON(t, rec, &dto)
	if dto.ID == "" {
		t.Fatal("id is empty")
	}
	if dto.Title != "My Session" {
		t.Errorf("title = %q, want %q", dto.Title, "My Session")
	}
	if dto.CreatedAt == "" || dto.UpdatedAt == "" {
		t.Errorf("timestamps empty: created=%q updated=%q", dto.CreatedAt, dto.UpdatedAt)
	}
	// Verify ISO8601 format.
	if _, err := time.Parse(time.RFC3339, dto.CreatedAt); err != nil {
		t.Errorf("created_at not RFC3339: %v", err)
	}
}

func TestSessionList(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})

	// Create two sessions with a small delay to ensure ordering.
	rec1 := doSession(t, s, "POST", "/api/sessions", `{"title":"First"}`)
	if rec1.Code != http.StatusCreated {
		t.Fatalf("create first: status=%d", rec1.Code)
	}
	// A tiny sleep so updated_at differs.
	time.Sleep(2 * time.Millisecond)
	rec2 := doSession(t, s, "POST", "/api/sessions", `{"title":"Second"}`)
	if rec2.Code != http.StatusCreated {
		t.Fatalf("create second: status=%d", rec2.Code)
	}

	rec := doSession(t, s, "GET", "/api/sessions", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}

	var out struct {
		Sessions []sessionDTO `json:"sessions"`
	}
	mustJSON(t, rec, &out)
	if len(out.Sessions) != 2 {
		t.Fatalf("got %d sessions, want 2", len(out.Sessions))
	}
	// Order by updated_at DESC — Second should be first.
	if out.Sessions[0].Title != "Second" {
		t.Errorf("first session title = %q, want %q (DESC order)", out.Sessions[0].Title, "Second")
	}
	if out.Sessions[1].Title != "First" {
		t.Errorf("second session title = %q, want %q", out.Sessions[1].Title, "First")
	}
}

func TestSessionUpdate(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})

	// Create a session.
	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"Original"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: status=%d", rec.Code)
	}
	var created sessionDTO
	mustJSON(t, rec, &created)

	// Rename it.
	rec = doSession(t, s, "PATCH", "/api/sessions/"+created.ID, `{"title":"Renamed"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("update: status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var updated sessionDTO
	mustJSON(t, rec, &updated)
	if updated.Title != "Renamed" {
		t.Errorf("title = %q, want %q", updated.Title, "Renamed")
	}
	if updated.ID != created.ID {
		t.Errorf("id changed: %q → %q", created.ID, updated.ID)
	}
}

func TestSessionUpdateNotFound(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})
	rec := doSession(t, s, "PATCH", "/api/sessions/nonexistent-id", `{"title":"X"}`)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestSessionDelete(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})

	// Create a session.
	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"ToDelete"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: status=%d", rec.Code)
	}
	var created sessionDTO
	mustJSON(t, rec, &created)

	// Delete it.
	rec = doSession(t, s, "DELETE", "/api/sessions/"+created.ID, "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("delete: status = %d, want 204; body=%s", rec.Code, rec.Body.String())
	}

	// Verify it's gone.
	rec = doSession(t, s, "GET", "/api/sessions", "")
	var out struct {
		Sessions []sessionDTO `json:"sessions"`
	}
	mustJSON(t, rec, &out)
	if len(out.Sessions) != 0 {
		t.Errorf("sessions remain after delete: %d", len(out.Sessions))
	}
}

func TestSessionDeleteNotFound(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})
	rec := doSession(t, s, "DELETE", "/api/sessions/nonexistent-id", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestSessionMessagesEmpty(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})

	// Create a session.
	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"Empty"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: status=%d", rec.Code)
	}
	var created sessionDTO
	mustJSON(t, rec, &created)

	// List messages — should be empty.
	rec = doSession(t, s, "GET", "/api/sessions/"+created.ID+"/messages", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("list messages: status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	var out struct {
		Messages []messageDTO `json:"messages"`
	}
	mustJSON(t, rec, &out)
	if len(out.Messages) != 0 {
		t.Errorf("got %d messages, want 0", len(out.Messages))
	}
}

func TestSessionMessagesNotFound(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})
	rec := doSession(t, s, "GET", "/api/sessions/nonexistent-id/messages", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

// --- Chat with session persistence (full flow) ---

func TestSessionChatPersistence(t *testing.T) {
	// A fake bridge that emits delta events and a done event with sources.
	br := &fakeBridge{
		events: []json.RawMessage{
			json.RawMessage(`{"type":"delta","content":"hello "}`),
			json.RawMessage(`{"type":"delta","content":"world"}`),
			json.RawMessage(`{"type":"done","cited_sources":[{"path":"a.md"}]}`),
		},
	}
	s := newSessionTestServer(t, br)

	// Step 1: Create a session.
	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"Chat Test"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create session: status=%d; body=%s", rec.Code, rec.Body.String())
	}
	var sess sessionDTO
	mustJSON(t, rec, &sess)

	// Step 2: Send a chat request bound to this session.
	chatBody := `{"query":"what is kaas?","session_id":"` + sess.ID + `"}`
	rec = doSession(t, s, "POST", "/api/chat", chatBody)
	if rec.Code != http.StatusOK {
		t.Fatalf("chat: status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("content-type = %q, want text/event-stream", ct)
	}

	// Verify SSE events were streamed.
	events := parseSSEData(t, rec.Body.String())
	if len(events) != 3 {
		t.Fatalf("got %d SSE events, want 3: %q", len(events), rec.Body.String())
	}

	// Step 3: Fetch messages — should contain user + assistant.
	rec = doSession(t, s, "GET", "/api/sessions/"+sess.ID+"/messages", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("list messages: status = %d; body=%s", rec.Code, rec.Body.String())
	}
	var msgOut struct {
		Messages []messageDTO `json:"messages"`
	}
	mustJSON(t, rec, &msgOut)
	if len(msgOut.Messages) != 2 {
		t.Fatalf("got %d messages, want 2 (user+assistant)", len(msgOut.Messages))
	}

	// User message.
	userMsg := msgOut.Messages[0]
	if userMsg.Role != "user" {
		t.Errorf("first message role = %q, want user", userMsg.Role)
	}
	if userMsg.Content != "what is kaas?" {
		t.Errorf("user content = %q", userMsg.Content)
	}
	if userMsg.SessionID != sess.ID {
		t.Errorf("user session_id = %q, want %q", userMsg.SessionID, sess.ID)
	}

	// Assistant message.
	assistMsg := msgOut.Messages[1]
	if assistMsg.Role != "assistant" {
		t.Errorf("second message role = %q, want assistant", assistMsg.Role)
	}
	if assistMsg.Content != "hello world" {
		t.Errorf("assistant content = %q, want %q", assistMsg.Content, "hello world")
	}
	// Sources should contain the cited_sources from the done event.
	if !strings.Contains(string(assistMsg.Sources), "a.md") {
		t.Errorf("assistant sources = %s, want to contain a.md", assistMsg.Sources)
	}
}

// TestSessionChatInvalidSession verifies that chat with a non-existent session_id
// returns HTTP 400 (not a streaming response).
func TestSessionChatInvalidSession(t *testing.T) {
	s := newSessionTestServer(t, &fakeBridge{})
	rec := doSession(t, s, "POST", "/api/chat", `{"query":"hi","session_id":"nonexistent"}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
}

// TestSessionChatWithoutSessionID ensures chat still works when no session_id is
// provided (no persistence, classic stateless mode).
func TestSessionChatWithoutSessionID(t *testing.T) {
	br := &fakeBridge{
		events: []json.RawMessage{
			json.RawMessage(`{"type":"delta","content":"ok"}`),
			json.RawMessage(`{"type":"done","cited_sources":[]}`),
		},
	}
	s := newSessionTestServer(t, br)

	rec := doSession(t, s, "POST", "/api/chat", `{"query":"hi"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	events := parseSSEData(t, rec.Body.String())
	if len(events) != 2 {
		t.Fatalf("got %d events, want 2", len(events))
	}
}

// TestSessionFullLifecycle exercises the complete CRUD + chat persistence flow
// in a single test to verify end-to-end behavior.
func TestSessionFullLifecycle(t *testing.T) {
	br := &fakeBridge{
		events: []json.RawMessage{
			json.RawMessage(`{"type":"delta","content":"answer"}`),
			json.RawMessage(`{"type":"done","cited_sources":[]}`),
		},
	}
	s := newSessionTestServer(t, br)

	// 1. Create session.
	rec := doSession(t, s, "POST", "/api/sessions", `{"title":"Lifecycle"}`)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: %d", rec.Code)
	}
	var sess sessionDTO
	mustJSON(t, rec, &sess)

	// 2. List sessions — should contain exactly one.
	rec = doSession(t, s, "GET", "/api/sessions", "")
	var listOut struct {
		Sessions []sessionDTO `json:"sessions"`
	}
	mustJSON(t, rec, &listOut)
	if len(listOut.Sessions) != 1 || listOut.Sessions[0].ID != sess.ID {
		t.Fatalf("list unexpected: %+v", listOut.Sessions)
	}

	// 3. Rename.
	rec = doSession(t, s, "PATCH", "/api/sessions/"+sess.ID, `{"title":"Renamed"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("rename: %d", rec.Code)
	}

	// 4. Chat with session.
	chatBody := `{"query":"q","session_id":"` + sess.ID + `"}`
	rec = doSession(t, s, "POST", "/api/chat", chatBody)
	if rec.Code != http.StatusOK {
		t.Fatalf("chat: %d", rec.Code)
	}

	// 5. Verify messages persisted.
	rec = doSession(t, s, "GET", "/api/sessions/"+sess.ID+"/messages", "")
	var msgOut struct {
		Messages []messageDTO `json:"messages"`
	}
	mustJSON(t, rec, &msgOut)
	if len(msgOut.Messages) != 2 {
		t.Fatalf("messages = %d, want 2", len(msgOut.Messages))
	}
	if msgOut.Messages[0].Role != "user" || msgOut.Messages[0].Content != "q" {
		t.Errorf("user msg wrong: %+v", msgOut.Messages[0])
	}
	if msgOut.Messages[1].Role != "assistant" || msgOut.Messages[1].Content != "answer" {
		t.Errorf("assistant msg wrong: %+v", msgOut.Messages[1])
	}

	// 6. Delete session.
	rec = doSession(t, s, "DELETE", "/api/sessions/"+sess.ID, "")
	if rec.Code != http.StatusNoContent {
		t.Fatalf("delete: %d", rec.Code)
	}

	// 7. Verify gone.
	rec = doSession(t, s, "GET", "/api/sessions", "")
	mustJSON(t, rec, &listOut)
	if len(listOut.Sessions) != 0 {
		t.Errorf("sessions remain: %d", len(listOut.Sessions))
	}

	// 8. Messages also gone (cascade).
	rec = doSession(t, s, "GET", "/api/sessions/"+sess.ID+"/messages", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("messages after delete: status=%d, want 404", rec.Code)
	}
}
