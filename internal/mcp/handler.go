package mcp

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
)

// ChatFunc abstracts DaemonClient.Chat for testability.
type ChatFunc func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error

// Handler serves MCP streamable-http requests at /mcp.
type Handler struct {
	chat    ChatFunc
	kbDir   string
	model   string
	token   string
	timeout time.Duration
	logger  *slog.Logger
}

// NewHandler creates an MCP handler.
func NewHandler(chat ChatFunc, kbDir, model, token string, timeout time.Duration, logger *slog.Logger) *Handler {
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Handler{chat: chat, kbDir: kbDir, model: model, token: token, timeout: timeout, logger: logger}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Only POST allowed
	if r.Method != http.MethodPost {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}

	// Bearer token validation
	if h.token != "" {
		auth := r.Header.Get("Authorization")
		expected := "Bearer " + h.token
		if subtle.ConstantTimeCompare([]byte(auth), []byte(expected)) != 1 {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
	}

	// Parse JSON-RPC request
	var req JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSONRPCError(w, nil, -32700, "Parse error")
		return
	}

	// Notification handling (no id → 202, no response body)
	if req.IsNotification() {
		h.logger.Debug("received notification", "method", req.Method)
		w.WriteHeader(http.StatusAccepted)
		return
	}

	// Route by method
	switch req.Method {
	case "initialize":
		h.handleInitialize(w, &req)
	case "tools/list":
		h.handleToolsList(w, &req)
	case "tools/call":
		h.handleToolCall(w, r, &req)
	default:
		writeJSONRPCError(w, req.ID, -32601, "Method not found")
	}
}

func (h *Handler) handleInitialize(w http.ResponseWriter, req *JSONRPCRequest) {
	result := InitializeResult{
		ProtocolVersion: "2025-03-26",
		Capabilities:    Capabilities{Tools: &ToolsCap{ListChanged: false}},
		ServerInfo:      ServerInfo{Name: "kaas", Version: "1.0.0"},
	}
	writeJSONRPCResult(w, req.ID, result)
}

func (h *Handler) handleToolsList(w http.ResponseWriter, req *JSONRPCRequest) {
	result := ToolsListResult{Tools: []Tool{askToolDefinition}}
	writeJSONRPCResult(w, req.ID, result)
}

func (h *Handler) handleToolCall(w http.ResponseWriter, r *http.Request, req *JSONRPCRequest) {
	// Parse params to get tool name
	var params ToolCallParams
	if err := json.Unmarshal(req.Params, &params); err != nil {
		writeJSONRPCError(w, req.ID, -32602, "Invalid params")
		return
	}

	switch params.Name {
	case "ask":
		h.handleAsk(w, r, req, params.Arguments)
	default:
		writeJSONRPCError(w, req.ID, -32602, "Unknown tool: "+params.Name)
	}
}

// --- helpers ---

func writeJSONRPCResult(w http.ResponseWriter, id json.RawMessage, result any) {
	resp := JSONRPCResponse{JSONRPC: "2.0", ID: id, Result: result}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func writeJSONRPCError(w http.ResponseWriter, id json.RawMessage, code int, message string) {
	resp := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error:   &RPCError{Code: code, Message: message},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
