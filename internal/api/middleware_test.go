package api

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
)

func testLogger(buf *bytes.Buffer) *slog.Logger {
	return slog.New(slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

func parseLogs(t *testing.T, buf *bytes.Buffer) []map[string]any {
	t.Helper()
	var logs []map[string]any
	dec := json.NewDecoder(buf)
	for dec.More() {
		var m map[string]any
		if err := dec.Decode(&m); err != nil {
			t.Fatalf("parse log JSON: %v", err)
		}
		logs = append(logs, m)
	}
	return logs
}

func TestAccessLogNormalRequest(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("hello"))
	}))

	r := httptest.NewRequest("GET", "/api/tasks?limit=10", nil)
	r.Header.Set("User-Agent", "test-agent")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	if len(logs) < 2 {
		t.Fatalf("expected at least 2 log lines, got %d", len(logs))
	}

	access := logs[len(logs)-1]
	if access["level"] != "INFO" {
		t.Errorf("level = %v, want INFO", access["level"])
	}
	if access["msg"] != "http request" {
		t.Errorf("msg = %v, want 'http request'", access["msg"])
	}
	if access["method"] != "GET" {
		t.Errorf("method = %v, want GET", access["method"])
	}
	if access["path"] != "/api/tasks?limit=10" {
		t.Errorf("path = %v, want /api/tasks?limit=10", access["path"])
	}
	if access["status"] != float64(200) {
		t.Errorf("status = %v, want 200", access["status"])
	}
	if _, ok := access["duration_ms"]; !ok {
		t.Error("duration_ms not present")
	}
	if access["response_bytes"] != float64(5) {
		t.Errorf("response_bytes = %v, want 5", access["response_bytes"])
	}
	if access["user_agent"] != "test-agent" {
		t.Errorf("user_agent = %v, want test-agent", access["user_agent"])
	}
}

func TestAccessLogErrorRequest(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))

	r := httptest.NewRequest("POST", "/api/submit", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	access := logs[len(logs)-1]
	if access["level"] != "ERROR" {
		t.Errorf("level = %v, want ERROR", access["level"])
	}
	if access["status"] != float64(500) {
		t.Errorf("status = %v, want 500", access["status"])
	}
}

func TestAccessLogWarnRequest(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	r := httptest.NewRequest("GET", "/api/missing", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	access := logs[len(logs)-1]
	if access["level"] != "WARN" {
		t.Errorf("level = %v, want WARN", access["level"])
	}
}

func TestAccessLogSSEStreaming(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("data: hello\n\n"))
	}))

	r := httptest.NewRequest("POST", "/api/chat", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	access := logs[len(logs)-1]
	if access["streaming"] != true {
		t.Errorf("streaming = %v, want true", access["streaming"])
	}
	if access["level"] != "INFO" {
		t.Errorf("level = %v, want INFO", access["level"])
	}
}

func TestAccessLogSSEClientDisconnect(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
	}))

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r := httptest.NewRequest("POST", "/api/chat", nil).WithContext(ctx)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	access := logs[len(logs)-1]
	if access["error"] != "context canceled" {
		t.Errorf("error = %v, want 'context canceled'", access["error"])
	}
	if access["level"] != "INFO" {
		t.Errorf("level = %v, want INFO (client disconnect is not server error)", access["level"])
	}
}

func TestAccessLogRequestStartedDebug(t *testing.T) {
	var buf bytes.Buffer
	logger := testLogger(&buf)

	handler := accessLog(logger)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	r := httptest.NewRequest("GET", "/healthz", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)

	logs := parseLogs(t, &buf)
	if len(logs) < 2 {
		t.Fatalf("expected at least 2 log lines (request started + access), got %d", len(logs))
	}
	started := logs[0]
	if started["msg"] != "request started" {
		t.Errorf("first log msg = %v, want 'request started'", started["msg"])
	}
	if started["level"] != "DEBUG" {
		t.Errorf("first log level = %v, want DEBUG", started["level"])
	}
}

func TestClientIPXForwardedFor(t *testing.T) {
	r := httptest.NewRequest("GET", "/", nil)
	r.Header.Set("X-Forwarded-For", "1.2.3.4, 10.0.0.1, 192.168.1.1")
	if got := clientIP(r); got != "1.2.3.4" {
		t.Errorf("clientIP = %q, want 1.2.3.4", got)
	}
}

func TestClientIPXRealIP(t *testing.T) {
	r := httptest.NewRequest("GET", "/", nil)
	r.Header.Set("X-Real-IP", "5.6.7.8")
	if got := clientIP(r); got != "5.6.7.8" {
		t.Errorf("clientIP = %q, want 5.6.7.8", got)
	}
}

func TestClientIPRemoteAddr(t *testing.T) {
	r := httptest.NewRequest("GET", "/", nil)
	r.RemoteAddr = "9.10.11.12:54321"
	if got := clientIP(r); got != "9.10.11.12" {
		t.Errorf("clientIP = %q, want 9.10.11.12", got)
	}
}

func TestStatusRecorderDefaultStatus(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: httptest.NewRecorder(), status: http.StatusOK}
	if rec.status != 200 {
		t.Errorf("default status = %d, want 200", rec.status)
	}
}

type flusherRecorder struct {
	*httptest.ResponseRecorder
	flushed bool
}

func (f *flusherRecorder) Flush() { f.flushed = true }

func TestStatusRecorderFlusher(t *testing.T) {
	inner := &flusherRecorder{ResponseRecorder: httptest.NewRecorder()}
	rec := &statusRecorder{ResponseWriter: inner, status: http.StatusOK}
	rec.Flush()
	if !inner.flushed {
		t.Error("Flush was not delegated to inner writer")
	}
}

func TestStatusRecorderHijackUnsupported(t *testing.T) {
	rec := &statusRecorder{ResponseWriter: httptest.NewRecorder(), status: http.StatusOK}
	_, _, err := rec.Hijack()
	if !errors.Is(err, errors.ErrUnsupported) {
		t.Errorf("Hijack error = %v, want errors.ErrUnsupported", err)
	}
}

type hijackRecorder struct {
	*httptest.ResponseRecorder
	hijacked bool
}

func (h *hijackRecorder) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	h.hijacked = true
	return nil, nil, nil
}

func TestStatusRecorderHijackSupported(t *testing.T) {
	inner := &hijackRecorder{ResponseRecorder: httptest.NewRecorder()}
	rec := &statusRecorder{ResponseWriter: inner, status: http.StatusOK}
	_, _, err := rec.Hijack()
	if err != nil {
		t.Errorf("Hijack returned unexpected error: %v", err)
	}
	if !inner.hijacked {
		t.Error("Hijack was not delegated to inner writer")
	}
}
