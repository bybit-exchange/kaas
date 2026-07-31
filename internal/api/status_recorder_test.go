package api

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestStatusRecorderUnwrap asserts the wrapped writer is reachable, which is
// what lets http.ResponseController reach the real writer through the
// middleware chain (e.g. to set deadlines on a streaming chat response).
func TestStatusRecorderUnwrap(t *testing.T) {
	inner := httptest.NewRecorder()
	rec := &statusRecorder{ResponseWriter: inner, status: http.StatusOK}

	if got := rec.Unwrap(); got != http.ResponseWriter(inner) {
		t.Errorf("Unwrap() returned %#v, want the wrapped writer", got)
	}
}

// TestStatusRecorderResponseControllerFlush exercises Unwrap through the
// standard library: ResponseController walks Unwrap to find a Flusher.
func TestStatusRecorderResponseControllerFlush(t *testing.T) {
	inner := &flusherRecorder{ResponseRecorder: httptest.NewRecorder()}
	rec := &statusRecorder{ResponseWriter: inner, status: http.StatusOK}

	if err := http.NewResponseController(rec).Flush(); err != nil {
		t.Fatalf("Flush via ResponseController: %v", err)
	}
	if !inner.flushed {
		t.Error("ResponseController could not reach the inner writer")
	}
}

// TestStatusRecorderFirstStatusWins asserts a duplicate WriteHeader does not
// overwrite the recorded status, so the access log reports what the client
// actually saw.
func TestStatusRecorderFirstStatusWins(t *testing.T) {
	inner := httptest.NewRecorder()
	rec := &statusRecorder{ResponseWriter: inner}

	rec.WriteHeader(http.StatusCreated)
	rec.WriteHeader(http.StatusInternalServerError)

	if rec.status != http.StatusCreated {
		t.Errorf("status = %d, want %d", rec.status, http.StatusCreated)
	}
	if inner.Code != http.StatusCreated {
		t.Errorf("inner status = %d, want %d", inner.Code, http.StatusCreated)
	}
}

// TestStatusRecorderWriteImpliesOK asserts writing a body without an explicit
// WriteHeader records 200 rather than leaving the status at zero.
func TestStatusRecorderWriteImpliesOK(t *testing.T) {
	inner := httptest.NewRecorder()
	rec := &statusRecorder{ResponseWriter: inner}

	n, err := rec.Write([]byte("hello"))
	if err != nil {
		t.Fatalf("Write: %v", err)
	}
	if n != 5 {
		t.Errorf("Write returned n = %d, want 5", n)
	}
	if rec.status != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.status)
	}
	if rec.written != 5 {
		t.Errorf("written = %d, want 5", rec.written)
	}
}

// TestStatusRecorderAccumulatesWrites asserts byte counting spans multiple
// writes, as happens with a streamed SSE response.
func TestStatusRecorderAccumulatesWrites(t *testing.T) {
	inner := httptest.NewRecorder()
	rec := &statusRecorder{ResponseWriter: inner}

	for _, chunk := range []string{"data: a\n\n", "data: bb\n\n", ""} {
		if _, err := rec.Write([]byte(chunk)); err != nil {
			t.Fatalf("Write(%q): %v", chunk, err)
		}
	}

	want := int64(len("data: a\n\n") + len("data: bb\n\n"))
	if rec.written != want {
		t.Errorf("written = %d, want %d", rec.written, want)
	}
	if inner.Body.Len() != int(want) {
		t.Errorf("inner body length = %d, want %d", inner.Body.Len(), want)
	}
}
