// Package api is the KaaS REST/SSE layer: it exposes the compile queue and
// compiled wiki to the Web UI and proxies RAG chat (SSE) from the Python AI
// engine. It is a thin HTTP adapter over the queue, store, and bridge — payload
// assembly lives in those packages.
//
// The server is built on the standard library net/http (Go 1.22+ ServeMux
// method routing). go-zero's rest.Server is intentionally avoided: SSE needs a
// raw ResponseWriter+Flusher with no write deadline, which fights rest.RestConf's
// default request Timeout.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/config"
	"github.com/bybit-exchange/kaas/internal/mcp"
	"github.com/bybit-exchange/kaas/internal/store"
)

// maxBodyBytes caps request bodies (chiefly submit paste content).
const maxBodyBytes = 10 << 20 // 10 MiB

// defaultMaxAttempts is the retry ceiling stamped on submitted tasks. Config has
// no knob for this yet; a small ceiling lets transient LLM failures requeue.
const defaultMaxAttempts = 3

// Queue is the subset of *queue.Queue the API needs (task submission).
type Queue interface {
	Submit(ctx context.Context, t *store.Task) error
}

// TaskStore is the read side: status page queries.
type TaskStore interface {
	GetTask(ctx context.Context, id string) (*store.Task, error)
	ListTasks(ctx context.Context, f store.ListFilter) ([]*store.Task, error)
	ListTasksPaged(ctx context.Context, f store.PagedListFilter) (*store.ListResult, error)
	DeleteTask(ctx context.Context, id string) error
}

// ChatBridge is the subset of *bridge.DaemonClient the API uses: streaming chat
// and one-shot URL fetch (for url-source submissions).
type ChatBridge interface {
	Chat(ctx context.Context, req bridge.ChatRequest, onEvent func(json.RawMessage) error) error
	FetchURL(ctx context.Context, url string) (*bridge.FetchURLResponse, error)
}

// Config holds the API-relevant configuration slice.
type Config struct {
	Addr   string // listen address, e.g. "0.0.0.0:8080"
	KBDir  string // knowledge-base root: raw/ wiki/ index/ live here
	Model  string // default chat model when the request omits one
	WebDir string // built Web UI (web/dist) to serve; empty disables static serving
	// MCPURL is the streamable-http MCP upstream (ai-mcp) reverse-proxied at
	// /mcp. Empty leaves the route unregistered (remote MCP disabled).
	// Deprecated: use MCPEnabled + native handler instead.
	MCPURL string
	Upload config.UploadConf
	// Native MCP handler fields (preferred over MCPURL reverse proxy).
	MCPEnabled    bool
	MCPToken      string
	MCPTimeoutSec int
}

// Server wires the HTTP handlers to their dependencies.
type Server struct {
	q      Queue
	st     TaskStore
	ss     SessionStore
	br     ChatBridge
	js     store.DerivedJobStore // derive jobs; nil when the backing store has none
	cfg    Config
	logger *slog.Logger
	mcpH   http.Handler // native MCP handler, nil if disabled
	wikiC  wikiCache    // in-memory wiki tree cache (stat+TTL invalidation)
}

// NewServer builds a Server. Dependencies are interfaces so tests inject fakes.
func NewServer(q Queue, st TaskStore, ss SessionStore, br ChatBridge, cfg Config, logger *slog.Logger) *Server {
	if logger == nil {
		logger = slog.Default()
	}
	s := &Server{q: q, st: st, ss: ss, br: br, cfg: cfg, logger: logger}
	// The sqlite store implements DerivedJobStore too; a backend that does not
	// simply leaves the derive routes answering 501.
	if js, ok := st.(store.DerivedJobStore); ok {
		s.js = js
	}

	if cfg.MCPEnabled {
		if cfg.MCPURL != "" {
			logger.Warn("both [ai.mcp] enabled=true and KAAS_AI_MCP_URL are set; " +
				"native MCP handler takes precedence, KAAS_AI_MCP_URL is ignored. " +
				"Please remove KAAS_AI_MCP_URL (deprecated, will be removed in a future version).")
		}
		timeout := time.Duration(cfg.MCPTimeoutSec) * time.Second
		s.mcpH = mcp.NewHandler(br.Chat, cfg.KBDir, cfg.Model, cfg.MCPToken, timeout, logger)
	}

	return s
}

// routes builds the request multiplexer. Exposed (unexported) for tests to drive
// via httptest without binding a socket.
func (s *Server) routes() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/submit", s.handleSubmit)
	mux.HandleFunc("POST /api/submit/files", s.handleSubmitFiles)
	mux.HandleFunc("GET /api/upload/config", s.handleUploadConfig)
	mux.HandleFunc("GET /api/tasks", s.handleListTasks)
	mux.HandleFunc("GET /api/tasks/{id}", s.handleGetTask)
	mux.HandleFunc("GET /api/tasks/{id}/content", s.handleTaskContent)
	mux.HandleFunc("DELETE /api/tasks/{id}", s.handleDeleteTask)
	mux.HandleFunc("GET /api/wiki", s.handleListWiki)
	mux.HandleFunc("GET /api/wiki/file", s.handleWikiFile)
	mux.HandleFunc("POST /api/derive", s.handleDerive)
	mux.HandleFunc("GET /api/derive/{id}", s.handleGetDeriveJob)
	mux.HandleFunc("GET /api/derived", s.handleListDerived)
	mux.HandleFunc("POST /api/chat", s.handleChat)
	mux.HandleFunc("GET /api/sessions", s.handleListSessions)
	mux.HandleFunc("POST /api/sessions", s.handleCreateSession)
	mux.HandleFunc("PATCH /api/sessions/{id}", s.handleUpdateSession)
	mux.HandleFunc("DELETE /api/sessions/{id}", s.handleDeleteSession)
	mux.HandleFunc("GET /api/sessions/{id}/messages", s.handleListMessages)
	mux.HandleFunc("GET /healthz", s.handleHealthz)
	// MCP endpoint: prefer native handler, fallback to legacy reverse proxy.
	if handler := s.mcpHandler(); handler != nil {
		mux.Handle("/mcp", handler)
		mux.Handle("/mcp/", handler)
	}
	// Serve the built Web UI as a catch-all. The "/" pattern is the least
	// specific, so every /api/... and /healthz route above takes precedence.
	if s.cfg.WebDir != "" {
		absWebDir, err := filepath.Abs(s.cfg.WebDir)
		if err != nil {
			s.logger.Error("failed to resolve WebDir", "err", err)
		} else {
			fileServer := http.FileServer(http.Dir(absWebDir))
			mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
				serveStatic(w, r, absWebDir, fileServer)
			})
		}
	}
	return mux
}

// mcpHandler returns the native MCP handler if enabled, otherwise falls back to
// the legacy reverse proxy. Returns nil when neither is configured.
func (s *Server) mcpHandler() http.Handler {
	if s.mcpH != nil {
		return s.mcpH
	}
	return s.mcpProxy()
}

// mcpProxy builds a reverse proxy to the configured MCP upstream, or returns
// nil when none is configured (route then stays unregistered). FlushInterval=-1
// flushes each write immediately so the MCP streamable-http (SSE) responses are
// not buffered. The Authorization header is forwarded by the proxy unchanged;
// token validation lives in the Python MCP server, not here.
func (s *Server) mcpProxy() http.Handler {
	if s.cfg.MCPURL == "" {
		return nil
	}
	target, err := url.Parse(s.cfg.MCPURL)
	if err != nil {
		// A misconfigured URL disables the route rather than crashing the
		// server; the rest of the API stays available.
		return nil
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.FlushInterval = -1
	// NewSingleHostReverseProxy rewrites scheme/host but leaves the inbound
	// Host header (the client's). The MCP upstream (uvicorn) does not validate
	// Host, so this is intentionally passed through; revisit if ever fronted by
	// a Host-checking layer.
	return proxy
}

// handleHealthz is a dependency-free liveness probe for container orchestration
// (docker-compose healthcheck). It never touches the store or AI engine.
func (s *Server) handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

// serveStatic serves the built single-page Web UI from absWebDir: real files
// are served via fileServer with appropriate cache headers; any other path
// falls back to index.html so client-side routing works on deep links and
// refreshes. Unmatched /api/ paths must 404 rather than receive the SPA shell.
//
// Security: only GET/HEAD allowed; paths with ".." are rejected; resolved
// absolute paths are checked against absWebDir to prevent directory traversal.
func serveStatic(w http.ResponseWriter, r *http.Request, absWebDir string, fileServer http.Handler) {
	// Method restriction: static files are read-only.
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}

	// Unmatched /api/ paths must 404, never fall through to the SPA shell.
	if strings.HasPrefix(r.URL.Path, "/api/") {
		http.NotFound(w, r)
		return
	}

	// Security: reject paths containing ".." to prevent directory traversal.
	if strings.Contains(r.URL.Path, "..") {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}

	// Resolve the requested path within absWebDir.
	cleaned := path.Clean(r.URL.Path)
	filePath := filepath.Join(absWebDir, filepath.FromSlash(cleaned))

	// Belt-and-suspenders: resolved absolute path must stay within absWebDir.
	absFilePath, err := filepath.Abs(filePath)
	if err != nil {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}
	if !strings.HasPrefix(absFilePath, absWebDir+string(filepath.Separator)) && absFilePath != absWebDir {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}

	// If the file exists and is not a directory, serve it with cache headers.
	if info, err := os.Stat(filePath); err == nil && !info.IsDir() {
		setCacheHeaders(w, r.URL.Path)
		fileServer.ServeHTTP(w, r)
		return
	}

	// SPA fallback: serve index.html for paths that don't match a file.
	indexPath := filepath.Join(absWebDir, "index.html")
	if _, err := os.Stat(indexPath); err != nil {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Cache-Control", "no-cache")
	http.ServeFile(w, r, indexPath)
}

// setCacheHeaders sets Cache-Control headers based on the URL path.
// Assets with content-hashed filenames (under /assets/) get long-lived
// immutable caching; everything else uses no-cache for instant updates.
func setCacheHeaders(w http.ResponseWriter, urlPath string) {
	if strings.HasPrefix(urlPath, "/assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		return
	}
	w.Header().Set("Cache-Control", "no-cache")
}

// Run starts the HTTP server and blocks until ctx is cancelled, then drains
// in-flight requests with a bounded timeout. Returns nil on clean shutdown.
func (s *Server) Run(ctx context.Context) error {
	srv := &http.Server{
		Addr:    s.cfg.Addr,
		Handler: accessLog(s.logger)(s.routes()),
		// No WriteTimeout: SSE streams (chat) outlive any fixed deadline.
		// A header-read timeout still guards against slowloris on the headers.
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Bind the socket before returning control so callers (and the readiness
	// line) reflect a listening server; serving happens in a goroutine.
	ln, err := net.Listen("tcp", srv.Addr)
	if err != nil {
		return err
	}

	errc := make(chan error, 1)
	go func() {
		err := srv.Serve(ln)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		errc <- err
	}()

	select {
	case err := <-errc:
		return err
	case <-ctx.Done():
		shutCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return srv.Shutdown(shutCtx)
	}
}

// queryInt parses a query parameter as int, returning def when absent or invalid.
func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}
