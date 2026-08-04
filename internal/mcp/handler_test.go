package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
)

// --- mock ChatFunc implementations ---

func mockChatSuccess(_ context.Context, _ bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
	onEvent(json.RawMessage(`{"type":"delta","content":"Hello "}`))
	onEvent(json.RawMessage(`{"type":"delta","content":"world"}`))
	onEvent(json.RawMessage(`{"type":"done","cited_sources":[{"title":"Doc","path":"wiki/doc.md"}],"cost_usd":0.001}`))
	return nil
}

func mockChatError(_ context.Context, _ bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
	// Mirrors the real kb_ai error-event contract: {"type","code","message"}.
	onEvent(json.RawMessage(`{"type":"error","code":"INTERNAL_ERROR","message":"LLM unavailable"}`))
	return nil
}

func mockChatTimeout(ctx context.Context, _ bridge.ChatRequest, _ func(json.RawMessage) error) error {
	<-ctx.Done()
	return ctx.Err()
}

// --- helpers ---

func newHandler(chat ChatFunc, token string, timeout time.Duration) *Handler {
	return NewHandler(chat, "/tmp/kb", "test-model", token, timeout, nil)
}

func doPost(h http.Handler, body []byte, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	return w
}

func rpcBody(id any, method string, params any) []byte {
	m := map[string]any{"jsonrpc": "2.0", "method": method}
	if id != nil {
		m["id"] = id
	}
	if params != nil {
		m["params"] = params
	}
	b, _ := json.Marshal(m)
	return b
}

func parseResponse(t *testing.T, body io.Reader) JSONRPCResponse {
	t.Helper()
	var resp JSONRPCResponse
	if err := json.NewDecoder(body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode JSON-RPC response: %v", err)
	}
	return resp
}

// --- tests ---

func TestHandler_MethodNotAllowed(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	req := httptest.NewRequest(http.MethodGet, "/mcp", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", w.Code)
	}
}

func TestHandler_BearerToken_Valid(t *testing.T) {
	h := newHandler(mockChatSuccess, "secret-token", 5*time.Second)
	body := rpcBody(1, "initialize", nil)
	w := doPost(h, body, map[string]string{"Authorization": "Bearer secret-token"})

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}
}

func TestHandler_BearerToken_Invalid(t *testing.T) {
	h := newHandler(mockChatSuccess, "secret-token", 5*time.Second)
	body := rpcBody(1, "initialize", nil)
	w := doPost(h, body, map[string]string{"Authorization": "Bearer wrong-token"})

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestHandler_BearerToken_Missing(t *testing.T) {
	h := newHandler(mockChatSuccess, "secret-token", 5*time.Second)
	body := rpcBody(1, "initialize", nil)
	w := doPost(h, body, nil)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestHandler_BearerToken_NotConfigured(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	body := rpcBody(1, "initialize", nil)
	w := doPost(h, body, nil)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}
}

func TestHandler_ParseError(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	w := doPost(h, []byte(`{not valid json`), nil)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	resp := parseResponse(t, w.Body)
	if resp.Error == nil {
		t.Fatal("expected error response")
	}
	if resp.Error.Code != -32700 {
		t.Fatalf("expected code -32700, got %d", resp.Error.Code)
	}
	if resp.Error.Message != "Parse error" {
		t.Fatalf("expected message 'Parse error', got %q", resp.Error.Message)
	}
}

func TestHandler_Notification(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	// Notification: no "id" field
	body := rpcBody(nil, "notifications/initialized", nil)
	w := doPost(h, body, nil)

	if w.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Fatalf("expected empty body for notification, got %q", w.Body.String())
	}
}

func TestHandler_MethodNotFound(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	body := rpcBody(1, "nonexistent/method", nil)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error == nil {
		t.Fatal("expected error response")
	}
	if resp.Error.Code != -32601 {
		t.Fatalf("expected code -32601, got %d", resp.Error.Code)
	}
	if resp.Error.Message != "Method not found" {
		t.Fatalf("expected message 'Method not found', got %q", resp.Error.Message)
	}
}

func TestHandler_Initialize(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	body := rpcBody(1, "initialize", nil)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}

	// Decode result into InitializeResult
	resultBytes, _ := json.Marshal(resp.Result)
	var result InitializeResult
	if err := json.Unmarshal(resultBytes, &result); err != nil {
		t.Fatalf("failed to unmarshal result: %v", err)
	}

	if result.ProtocolVersion != "2025-03-26" {
		t.Errorf("protocolVersion = %q, want %q", result.ProtocolVersion, "2025-03-26")
	}
	if result.ServerInfo.Name != "kaas" {
		t.Errorf("serverInfo.name = %q, want %q", result.ServerInfo.Name, "kaas")
	}
	if result.ServerInfo.Version != "1.0.0" {
		t.Errorf("serverInfo.version = %q, want %q", result.ServerInfo.Version, "1.0.0")
	}
	if result.Capabilities.Tools == nil {
		t.Fatal("capabilities.tools is nil")
	}
	if result.Capabilities.Tools.ListChanged != false {
		t.Error("capabilities.tools.listChanged should be false")
	}
}

func TestHandler_ToolsList(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	body := rpcBody(1, "tools/list", nil)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}

	resultBytes, _ := json.Marshal(resp.Result)
	var result ToolsListResult
	if err := json.Unmarshal(resultBytes, &result); err != nil {
		t.Fatalf("failed to unmarshal result: %v", err)
	}

	if len(result.Tools) != 1 {
		t.Fatalf("expected 1 tool, got %d", len(result.Tools))
	}
	tool := result.Tools[0]
	if tool.Name != "ask" {
		t.Errorf("tool.name = %q, want %q", tool.Name, "ask")
	}
	if tool.Description == "" {
		t.Error("tool.description should not be empty")
	}

	// Verify schema has required fields
	var schema map[string]any
	if err := json.Unmarshal(tool.InputSchema, &schema); err != nil {
		t.Fatalf("failed to parse inputSchema: %v", err)
	}
	if schema["type"] != "object" {
		t.Errorf("schema type = %v, want 'object'", schema["type"])
	}
	props, ok := schema["properties"].(map[string]any)
	if !ok {
		t.Fatal("schema.properties is not an object")
	}
	if _, ok := props["query"]; !ok {
		t.Error("schema missing 'query' property")
	}
	if _, ok := props["paths"]; !ok {
		t.Error("schema missing 'paths' property")
	}
	if _, ok := props["model"]; !ok {
		t.Error("schema missing 'model' property")
	}
	required, ok := schema["required"].([]any)
	if !ok {
		t.Fatal("schema.required is not an array")
	}
	if len(required) != 1 || required[0] != "query" {
		t.Errorf("schema.required = %v, want [\"query\"]", required)
	}
}

func TestHandler_ToolsCall_Ask_Success(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	params := map[string]any{
		"name":      "ask",
		"arguments": map[string]any{"query": "What is KaaS?"},
	}
	body := rpcBody(1, "tools/call", params)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected error: %+v", resp.Error)
	}

	resultBytes, _ := json.Marshal(resp.Result)
	var result ToolResult
	if err := json.Unmarshal(resultBytes, &result); err != nil {
		t.Fatalf("failed to unmarshal result: %v", err)
	}

	if result.IsError {
		t.Fatal("result.isError should be false")
	}
	if len(result.Content) != 1 {
		t.Fatalf("expected 1 content block, got %d", len(result.Content))
	}
	if result.Content[0].Type != "text" {
		t.Errorf("content type = %q, want %q", result.Content[0].Type, "text")
	}

	// Parse the inner JSON text
	var inner map[string]any
	if err := json.Unmarshal([]byte(result.Content[0].Text), &inner); err != nil {
		t.Fatalf("failed to parse inner content: %v", err)
	}
	answer, _ := inner["answer"].(string)
	if answer == "" {
		t.Error("answer should not be empty")
	}
	// Check that answer contains the expected text parts
	if !bytes.Contains([]byte(answer), []byte("Hello world")) {
		t.Errorf("answer does not contain 'Hello world': %q", answer)
	}
	// Check sources footer
	if !bytes.Contains([]byte(answer), []byte("Sources:")) {
		t.Errorf("answer does not contain 'Sources:' footer: %q", answer)
	}
	sources, _ := inner["sources"].([]any)
	if len(sources) != 1 {
		t.Fatalf("expected 1 source, got %d", len(sources))
	}
}

func TestHandler_ToolsCall_Ask_MissingQuery(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	params := map[string]any{
		"name":      "ask",
		"arguments": map[string]any{},
	}
	body := rpcBody(1, "tools/call", params)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error == nil {
		t.Fatal("expected error response")
	}
	if resp.Error.Code != -32602 {
		t.Fatalf("expected code -32602, got %d", resp.Error.Code)
	}
	if resp.Error.Message != "Missing required argument: query" {
		t.Fatalf("expected message about missing query, got %q", resp.Error.Message)
	}
}

func TestHandler_ToolsCall_Ask_UnknownTool(t *testing.T) {
	h := newHandler(mockChatSuccess, "", 5*time.Second)
	params := map[string]any{
		"name":      "unknown",
		"arguments": map[string]any{"query": "test"},
	}
	body := rpcBody(1, "tools/call", params)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error == nil {
		t.Fatal("expected error response")
	}
	if resp.Error.Code != -32602 {
		t.Fatalf("expected code -32602, got %d", resp.Error.Code)
	}
	if resp.Error.Message != "Unknown tool: unknown" {
		t.Fatalf("expected 'Unknown tool: unknown', got %q", resp.Error.Message)
	}
}

func TestHandler_ToolsCall_Ask_ChatError(t *testing.T) {
	h := newHandler(mockChatError, "", 5*time.Second)
	params := map[string]any{
		"name":      "ask",
		"arguments": map[string]any{"query": "What is KaaS?"},
	}
	body := rpcBody(1, "tools/call", params)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error != nil {
		t.Fatalf("unexpected JSON-RPC error: %+v", resp.Error)
	}

	resultBytes, _ := json.Marshal(resp.Result)
	var result ToolResult
	if err := json.Unmarshal(resultBytes, &result); err != nil {
		t.Fatalf("failed to unmarshal result: %v", err)
	}

	if !result.IsError {
		t.Fatal("result.isError should be true")
	}
	if len(result.Content) != 1 {
		t.Fatalf("expected 1 content block, got %d", len(result.Content))
	}
	if result.Content[0].Text != "LLM unavailable" {
		t.Errorf("error text = %q, want %q", result.Content[0].Text, "LLM unavailable")
	}
}

// An error event must never yield a successful empty answer, whatever subset of
// {code, message} it carries.
func TestHandler_ToolsCall_Ask_ChatErrorVariants(t *testing.T) {
	tests := []struct {
		name  string
		event string
		want  string
	}{
		{"code and message", `{"type":"error","code":"INTERNAL_ERROR","message":"boom"}`, "boom"},
		{"code only", `{"type":"error","code":"CANCELLED"}`, "CANCELLED"},
		{"neither", `{"type":"error"}`, "chat failed"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			chat := func(_ context.Context, _ bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
				onEvent(json.RawMessage(tt.event))
				return nil
			}
			h := newHandler(chat, "", 5*time.Second)
			params := map[string]any{
				"name":      "ask",
				"arguments": map[string]any{"query": "What is KaaS?"},
			}
			w := doPost(h, rpcBody(1, "tools/call", params), nil)

			resp := parseResponse(t, w.Body)
			if resp.Error != nil {
				t.Fatalf("unexpected JSON-RPC error: %+v", resp.Error)
			}
			resultBytes, _ := json.Marshal(resp.Result)
			var result ToolResult
			if err := json.Unmarshal(resultBytes, &result); err != nil {
				t.Fatalf("failed to unmarshal result: %v", err)
			}
			if !result.IsError {
				t.Fatal("result.isError should be true")
			}
			if len(result.Content) != 1 || result.Content[0].Text != tt.want {
				t.Errorf("error text = %+v, want %q", result.Content, tt.want)
			}
		})
	}
}

func TestHandler_ToolsCall_Ask_Timeout(t *testing.T) {
	h := newHandler(mockChatTimeout, "", 50*time.Millisecond)
	params := map[string]any{
		"name":      "ask",
		"arguments": map[string]any{"query": "What is KaaS?"},
	}
	body := rpcBody(1, "tools/call", params)
	w := doPost(h, body, nil)

	resp := parseResponse(t, w.Body)
	if resp.Error == nil {
		t.Fatal("expected error response")
	}
	if resp.Error.Code != -32603 {
		t.Fatalf("expected code -32603, got %d", resp.Error.Code)
	}
	if resp.Error.Message != "tool call timeout" {
		t.Fatalf("expected message 'tool call timeout', got %q", resp.Error.Message)
	}
}

func TestHandleAskResolvesDerivedKB(t *testing.T) {
	root := t.TempDir()
	derived := filepath.Join(root, "derived", "pricing")
	if err := os.MkdirAll(derived, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(derived, "manifest.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	// Resolve now returns the canonical (symlink-free) path, so the want value
	// must match what EvalSymlinks would return (relevant on macOS where
	// t.TempDir() may sit under a symlinked /tmp -> /private/tmp).
	wantDerived, err := filepath.EvalSymlinks(derived)
	if err != nil {
		t.Fatal(err)
	}

	var gotKBDir string
	chat := func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
		gotKBDir = req.KBDir
		return onEvent(json.RawMessage(`{"type":"done","cost_usd":0}`))
	}
	h := NewHandler(chat, root, "model", "", time.Minute, slog.Default())

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask","arguments":{"query":"q","kb":"pricing"}}}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body)))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	if gotKBDir != wantDerived {
		t.Errorf("KBDir = %q, want %q", gotKBDir, wantDerived)
	}
}

func TestHandleAskRejectsUnknownDerivedKB(t *testing.T) {
	chat := func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
		t.Fatal("chat must not run for an unknown kb")
		return nil
	}
	h := NewHandler(chat, t.TempDir(), "model", "", time.Minute, slog.Default())

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask","arguments":{"query":"q","kb":"nope"}}}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body)))

	resp := parseResponse(t, rec.Body)
	if resp.Error == nil {
		t.Fatal("expected JSON-RPC error for unknown kb, got nil")
	}
	// ask.go maps both ErrInvalidSlug and ErrUnknownKB to -32602 (invalid params).
	// Assert the code so a future regression that switches to -32603 (internal error)
	// or drops the error object entirely would be caught here.
	if resp.Error.Code != -32602 {
		t.Errorf("Error.Code = %d, want -32602", resp.Error.Code)
	}
	if !strings.Contains(resp.Error.Message, "unknown derived knowledge base") {
		t.Errorf("Error.Message = %q, want substring %q", resp.Error.Message, "unknown derived knowledge base")
	}
}

func TestHandleAskDefaultKBDir(t *testing.T) {
	root := t.TempDir()
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}

	var gotKBDir string
	chat := func(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error {
		gotKBDir = req.KBDir
		return onEvent(json.RawMessage(`{"type":"done","cost_usd":0}`))
	}
	h := NewHandler(chat, root, "model", "", time.Minute, slog.Default())

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask","arguments":{"query":"q"}}}`
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body)))

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", rec.Code, rec.Body.String())
	}
	// An ask without a kb argument must reach the handler's own kbDir (the root KB).
	// Resolve returns the resolved (canonical) form of root so both layers agree
	// on the path by string equality (Task 16 stores and compares this string).
	if gotKBDir != resolvedRoot {
		t.Errorf("KBDir = %q, want resolved root %q", gotKBDir, resolvedRoot)
	}
}
