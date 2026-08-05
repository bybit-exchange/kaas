package api

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// chatRequest is the POST /api/chat body. It mirrors the fields the UI controls;
// KBDir and Model are filled server-side from config.
//
// Retrieval (selecting which wiki pages to ground the answer in) is NOT done in
// this slice: Paths is left empty, so the engine answers without KB context
// until the LLM-iterative retrieval slice lands.
type chatRequest struct {
	Query    string               `json:"query"`
	Messages []bridge.ChatMessage `json:"messages,omitempty"`
	// Temperature is a pointer so an explicit 0 is forwarded (deterministic),
	// while omission falls back to the engine default.
	Temperature    *float64 `json:"temperature,omitempty"`
	IncludeSources *bool    `json:"include_sources,omitempty"`
	// SessionID, when provided, enables message persistence: user and assistant
	// messages are saved to chat_messages upon stream completion.
	SessionID string `json:"session_id,omitempty"`
}

// handleChat serves POST /api/chat: it forwards a RAG chat request to the Python
// engine and streams the engine's SSE events back to the client verbatim.
func (s *Server) handleChat(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
	var req chatRequest
	if err := decodeJSON(r, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return
	}
	if req.Query == "" {
		writeErr(w, http.StatusBadRequest, "query is required")
		return
	}

	// Resolve the KB directory from ?kb=<slug> before any side effects so that
	// an invalid slug can still return HTTP 400 (once SSE headers are written,
	// errors can only be sent as SSE events).
	kbDir, ok := s.resolveKB(w, r)
	if !ok {
		return
	}

	now := time.Now().UnixMilli()

	// If session_id is provided, validate the session exists and persist the
	// user message BEFORE sending SSE headers (so we can still return HTTP 400).
	if req.SessionID != "" {
		if _, err := s.ss.GetSession(r.Context(), req.SessionID); err != nil {
			writeErr(w, http.StatusBadRequest, "session not found")
			return
		}
		userMsg := &store.Message{
			ID:        uuid.NewString(),
			SessionID: req.SessionID,
			Role:      "user",
			Content:   req.Query,
			Sources:   "[]",
			Usage:     "{}",
			CreatedAt: now,
		}
		if err := s.ss.CreateMessage(r.Context(), userMsg); err != nil {
			log.Printf("chat: failed to persist user message: %v", err)
		}
	}

	flusher, streamable := w.(http.Flusher)
	if !streamable {
		writeErr(w, http.StatusInternalServerError, "streaming unsupported")
		return
	}

	// Commit to an SSE response: once headers are sent, upstream failures are
	// surfaced as SSE error events rather than HTTP error codes.
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no") // disable proxy buffering (nginx)
	w.WriteHeader(http.StatusOK)
	flusher.Flush()

	bridgeReq := bridge.ChatRequest{
		Query:          req.Query,
		KBDir:          kbDir,
		Messages:       req.Messages,
		Model:          s.cfg.Model,
		Temperature:    req.Temperature,
		IncludeSources: req.IncludeSources,
	}

	// Base writeEvent: write raw SSE frame and flush.
	var contentBuf strings.Builder
	var reasoningBuf strings.Builder
	var doneSources string

	baseWriteEvent := func(raw json.RawMessage) error {
		if _, err := fmt.Fprintf(w, "data: %s\n\n", raw); err != nil {
			return err
		}
		flusher.Flush()
		return nil
	}

	writeEvent := baseWriteEvent
	if req.SessionID != "" {
		// Wrap writeEvent to accumulate assistant content for persistence.
		writeEvent = func(raw json.RawMessage) error {
			if err := baseWriteEvent(raw); err != nil {
				return err
			}
			var ev struct {
				Type         string          `json:"type"`
				Content      string          `json:"content"`
				CitedSources json.RawMessage `json:"cited_sources"`
			}
			_ = json.Unmarshal(raw, &ev) // parse failure is non-fatal
			switch ev.Type {
			case "reasoning":
				reasoningBuf.WriteString(ev.Content)
			case "delta":
				contentBuf.WriteString(ev.Content)
			case "done":
				if len(ev.CitedSources) > 0 {
					doneSources = string(ev.CitedSources)
				}
			}
			return nil
		}
	}

	err := s.br.Chat(r.Context(), bridgeReq, writeEvent)
	if err != nil && r.Context().Err() == nil {
		// Upstream failed before/while streaming and the client is still here:
		// emit a terminal error event so the UI can react.
		errEvent, _ := json.Marshal(map[string]string{"type": "error", "message": err.Error()})
		_ = writeEvent(errEvent)
	}

	// Persist assistant message after stream completes, only if session-bound,
	// content was accumulated, and the client did not disconnect mid-stream.
	if req.SessionID != "" && contentBuf.Len() > 0 && r.Context().Err() == nil {
		sources := doneSources
		if sources == "" {
			sources = "[]"
		}
		assistantMsg := &store.Message{
			ID:        uuid.NewString(),
			SessionID: req.SessionID,
			Role:      "assistant",
			Content:   contentBuf.String(),
			Reasoning: reasoningBuf.String(),
			Sources:   sources,
			Usage:     "{}",
			CreatedAt: now,
		}
		if err := s.ss.CreateMessage(r.Context(), assistantMsg); err != nil {
			log.Printf("chat: failed to persist assistant message: %v", err)
		}
		if err := s.ss.TouchSession(r.Context(), req.SessionID, now); err != nil {
			log.Printf("chat: failed to touch session: %v", err)
		}
	}
}
