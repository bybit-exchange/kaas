package api

import (
	"bufio"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"time"
)

var (
	_ http.ResponseWriter = (*statusRecorder)(nil)
	_ http.Flusher        = (*statusRecorder)(nil)
	_ http.Hijacker       = (*statusRecorder)(nil)
)

type statusRecorder struct {
	http.ResponseWriter
	status      int
	written     int64
	wroteHeader bool
}

func (r *statusRecorder) WriteHeader(code int) {
	if !r.wroteHeader {
		r.status = code
		r.wroteHeader = true
	}
	r.ResponseWriter.WriteHeader(code)
}

func (r *statusRecorder) Write(b []byte) (int, error) {
	if !r.wroteHeader {
		r.WriteHeader(http.StatusOK)
	}
	n, err := r.ResponseWriter.Write(b)
	r.written += int64(n)
	return n, err
}

func (r *statusRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (r *statusRecorder) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	if hj, ok := r.ResponseWriter.(http.Hijacker); ok {
		return hj.Hijack()
	}
	return nil, nil, errors.ErrUnsupported
}

func (r *statusRecorder) Unwrap() http.ResponseWriter {
	return r.ResponseWriter
}

func accessLog(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			ip := clientIP(r)

			logger.LogAttrs(r.Context(), slog.LevelDebug, "request started",
				slog.String("method", r.Method),
				slog.String("path", r.URL.RequestURI()),
				slog.String("client_ip", ip),
			)

			rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			defer func() {
				duration := time.Since(start)
				attrs := []slog.Attr{
					slog.String("method", r.Method),
					slog.String("path", r.URL.RequestURI()),
					slog.Int("status", rec.status),
					slog.Float64("duration_ms", float64(duration.Microseconds())/1000.0),
					slog.String("client_ip", ip),
					slog.Int64("request_bytes", r.ContentLength),
					slog.Int64("response_bytes", rec.written),
					slog.String("user_agent", r.UserAgent()),
				}

				if rec.Header().Get("Content-Type") == "text/event-stream" {
					attrs = append(attrs, slog.Bool("streaming", true))
				}

				if ctxErr := r.Context().Err(); ctxErr != nil {
					attrs = append(attrs, slog.String("error", ctxErr.Error()))
				}

				level := slog.LevelInfo
				switch {
				case rec.status >= 500:
					level = slog.LevelError
				case rec.status >= 400:
					level = slog.LevelWarn
				}

				logger.LogAttrs(r.Context(), level, "http request", attrs...)
			}()

			next.ServeHTTP(rec, r)
		})
	}
}

func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		if i := strings.IndexByte(xff, ','); i > 0 {
			return strings.TrimSpace(xff[:i])
		}
		return strings.TrimSpace(xff)
	}
	if xri := r.Header.Get("X-Real-IP"); xri != "" {
		return xri
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
