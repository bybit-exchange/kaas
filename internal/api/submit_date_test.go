package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/store"
)

// The submit route is the one ingest path whose documents carry no date of their
// own, so the writer has nothing to order them by (supersession spec RT1-RT11).
// These tests pin what lands under raw/ and, just as importantly, what does not
// change: the content hash and the file title are still taken from the content as
// submitted, not from the bytes written.

func rawOf(t *testing.T, task *store.Task) string {
	t.Helper()
	b, err := os.ReadFile(task.RawPath)
	if err != nil {
		t.Fatalf("read raw file: %v", err)
	}
	return string(b)
}

func TestSubmitStampsAnAbsentDate(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit",
		`{"source":"paste","title":"Hi","content":"hello world"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	raw := rawOf(t, q.submitted)
	if !strings.HasPrefix(raw, "---\ndate: ") {
		t.Fatalf("raw does not open with a stamped date: %q", raw)
	}
	end := strings.Index(raw, "\nsource:")
	if end < 0 {
		t.Fatalf("raw has no source line to bound the stamp: %q", raw)
	}
	stamp := raw[len("---\ndate: "):end]
	got, err := time.Parse(time.RFC3339, stamp)
	if err != nil {
		t.Fatalf("stamp %q is not RFC3339: %v", stamp, err)
	}
	if d := time.Since(got); d > time.Minute || d < -time.Minute {
		t.Errorf("stamp %s is %s away from now", stamp, d)
	}
	if !strings.Contains(raw, "source: \"paste\"") || !strings.Contains(raw, "title: \"Hi\"") {
		t.Errorf("raw missing the fields already known: %q", raw)
	}
	if !strings.HasSuffix(raw, "\n\nhello world") {
		t.Errorf("raw does not end with the submitted content: %q", raw)
	}
}

func TestSubmitWritesAnExplicitDate(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit",
		`{"source":"paste","content":"v2 of the plan","date":"2026-06-01"}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	if raw := rawOf(t, q.submitted); raw != "---\ndate: 2026-06-01\nsource: \"paste\"\n---\n\nv2 of the plan" {
		t.Errorf("raw = %q", raw)
	}
}

func TestSubmitKeepsAnRFC3339DatesOwnSpelling(t *testing.T) {
	// The offset is preserved rather than converted to UTC: PyYAML resolves
	// either spelling to the same instant, and rewriting a caller's date is a
	// change they did not ask for.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit",
		`{"source":"paste","content":"x","date":"2026-06-01T09:00:00+02:00"}`)

	if raw := rawOf(t, q.submitted); !strings.Contains(raw, "date: 2026-06-01T09:00:00+02:00") {
		t.Errorf("raw = %q", raw)
	}
}

func TestSubmitRejectsAnUnparseableDate(t *testing.T) {
	q := &fakeQueue{}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit",
		`{"source":"paste","content":"x","date":"last Tuesday"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	if q.callCount != 0 {
		t.Errorf("Submit called %d times, want 0", q.callCount)
	}
	// Rejected before anything was written, so there is nothing to clean up.
	if entries, _ := os.ReadDir(filepath.Join(kb, "raw")); len(entries) != 0 {
		t.Errorf("raw files written for a rejected request: %d", len(entries))
	}
}

func TestSubmitAlsoRejectsAnImpossibleCalendarDate(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "POST", "/api/submit",
		`{"source":"paste","content":"x","date":"2026-02-31"}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
}

func TestSubmitRejectsAYearBeforeOne(t *testing.T) {
	// Go's time.Parse accepts year zero; PyYAML's timestamp constructor raises
	// ValueError on it. One such document under raw/ took down the whole
	// document catalog, for every other document with it, and nothing in the
	// product could remove it.
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	for _, date := range []string{"0000-01-01", "0000-12-31T00:00:00Z"} {
		rec := do(t, s, "POST", "/api/submit",
			`{"source":"paste","content":"x","date":"`+date+`"}`)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("date %q: status = %d, want 400; body=%s", date, rec.Code, rec.Body.String())
		}
	}
}

func TestSubmitHashesTheContentAsSubmitted(t *testing.T) {
	// RT4: hashing the written bytes would put the stamp time inside the hash, so
	// tasks.content_hash's unique index would never fire and the 409 duplicate
	// path would become unreachable. Two submissions of one document, dated
	// differently, must still collide.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit", `{"source":"paste","content":"same bytes","date":"2026-06-01"}`)
	first := q.submitted.ContentHash
	do(t, s, "POST", "/api/submit", `{"source":"paste","content":"same bytes","date":"2020-01-01"}`)
	second := q.submitted.ContentHash

	sum := sha256.Sum256([]byte("same bytes"))
	if first != hex.EncodeToString(sum[:]) {
		t.Errorf("ContentHash = %s, want the hash of the content as submitted", first)
	}
	if first != second {
		t.Errorf("hashes differ across dates: %s vs %s", first, second)
	}
}

func TestSubmitTakesTheFileTitleFromTheDocumentNotTheStampedBlock(t *testing.T) {
	// RT8: ExtractTitle reads a leading "title:", which the stamped block now
	// provides. Computed after the stamp it would echo the request's own title
	// back instead of the document's.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit",
		`{"source":"file","title":"upload.md","content":"# Real Heading\n\nbody"}`)

	if q.submitted.FileTitle != "Real Heading" {
		t.Errorf("FileTitle = %q, want %q", q.submitted.FileTitle, "Real Heading")
	}
}

func TestSubmitKeepsADocumentsOwnDate(t *testing.T) {
	// The ingest clock is not authorship time (D3). A document that dated itself
	// is left byte-verbatim, which is also what makes S2 -- backfilling v1 after
	// v2 -- come out in the right order.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})
	content := "---\ntitle: The Plan\ndate: 2020-01-01\n---\n\nbody"
	body, err := json.Marshal(map[string]string{
		"source": "file", "title": "plan.md", "content": content,
	})
	if err != nil {
		t.Fatalf("encode request: %v", err)
	}

	do(t, s, "POST", "/api/submit", string(body))

	if raw := rawOf(t, q.submitted); raw != content {
		t.Errorf("raw = %q, want the submitted bytes unchanged", raw)
	}
}

func TestSubmitExplicitDateOverridesTheDocumentsOwn(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit",
		`{"source":"file","content":"---\ntitle: The Plan\ndate: 2020-01-01\n---\n\nbody","date":"2026-06-01"}`)

	raw := rawOf(t, q.submitted)
	if raw != "---\ntitle: The Plan\ndate: 2026-06-01\n---\n\nbody" {
		t.Errorf("raw = %q", raw)
	}
	if strings.Count(raw, "date:") != 1 {
		t.Errorf("duplicate date key: %q", raw)
	}
}

func TestSubmitDatesADocumentWhoseOwnBlockHasNoDate(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit",
		`{"source":"file","content":"---\ntitle: The Plan\n---\n\nbody","date":"2026-06-01"}`)

	// Inserted into the document's own block, not stacked above it: a second block
	// would leave "title: The Plan" in the body for the catalog to read as prose.
	if raw := rawOf(t, q.submitted); raw != "---\ndate: 2026-06-01\ntitle: The Plan\n---\n\nbody" {
		t.Errorf("raw = %q", raw)
	}
}

func TestSubmitStampsAFetchedURL(t *testing.T) {
	q := &fakeQueue{}
	br := &fakeBridge{fetchResp: &bridge.FetchURLResponse{
		Title:   "Fetched Title",
		Content: "page body",
	}}
	s, _ := newTestServer(t, q, &fakeStore{}, br)

	do(t, s, "POST", "/api/submit", `{"source":"url","url":"https://example.com"}`)

	raw := rawOf(t, q.submitted)
	if !strings.HasPrefix(raw, "---\ndate: ") || !strings.Contains(raw, "source: \"url\"") {
		t.Errorf("raw = %q", raw)
	}
	if !strings.Contains(raw, "title: \"Fetched Title\"") {
		t.Errorf("raw missing the fetched title: %q", raw)
	}
}

func TestRawDocumentStampsTheClockItIsGiven(t *testing.T) {
	// The handler passes time.Now(), which is why the route-level test can only
	// assert "close to now". Calling the seam directly is what pins the exact
	// bytes -- and that the stamp is UTC rather than the host's zone, since the
	// reader resolves an offset-less date as naive.
	at := time.Date(2026, 6, 1, 9, 15, 0, 0, time.FixedZone("CEST", 2*60*60))

	got, err := rawDocument("body", "paste", "", "", at)
	if err != nil {
		t.Fatalf("rawDocument: %v", err)
	}
	want := "---\ndate: 2026-06-01T07:15:00Z\nsource: \"paste\"\n---\n\nbody"
	if string(got) != want {
		t.Errorf("rawDocument() = %q, want %q", got, want)
	}
}

func TestSubmitLeavesFrontmatterItCannotEditUndated(t *testing.T) {
	// A flow mapping is frontmatter the reader parses and the writer cannot edit.
	// Stamping the clock over it would assert an ingest date over the authored one
	// it may be hiding, so the document is stored verbatim and reaches the writer
	// undated -- the S5 path, not a wrong date.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})
	content := "---\n{date: 2020-01-01, title: One}\n---\n\nbody"
	body, err := json.Marshal(map[string]string{
		"source": "file", "title": "plan.md", "content": content,
	})
	if err != nil {
		t.Fatalf("encode request: %v", err)
	}

	do(t, s, "POST", "/api/submit", string(body))

	if raw := rawOf(t, q.submitted); raw != content {
		t.Errorf("raw = %q, want the submitted bytes unchanged", raw)
	}
}

func TestSubmitStacksAnExplicitDateOverFrontmatterItCannotEdit(t *testing.T) {
	// An explicit date outranks the document's own (RT9), so it has to be recorded
	// somewhere the reader will see. Inserting it into a flow mapping would make
	// the block invalid YAML and cost the document every label it had.
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	do(t, s, "POST", "/api/submit",
		`{"source":"file","content":"---\n{date: 2020-01-01, title: One}\n---\n\nbody","date":"2026-06-01"}`)

	raw := rawOf(t, q.submitted)
	want := "---\ndate: 2026-06-01\nsource: \"file\"\n---\n\n---\n{date: 2020-01-01, title: One}\n---\n\nbody"
	if raw != want {
		t.Errorf("raw = %q, want %q", raw, want)
	}
}
