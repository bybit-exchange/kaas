package api

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/bybit-exchange/kaas/internal/store"
)

// buildMultipart creates a multipart/form-data body with the given files.
// Each entry in files is {name, content}.
func buildMultipart(t *testing.T, files [][2]string) (*bytes.Buffer, string) {
	t.Helper()
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	for _, f := range files {
		part, err := w.CreateFormFile("files", f[0])
		if err != nil {
			t.Fatalf("CreateFormFile: %v", err)
		}
		_, _ = part.Write([]byte(f[1]))
	}
	w.Close()
	return body, w.FormDataContentType()
}

// doMultipart issues a multipart POST /api/submit/files request.
func doMultipart(t *testing.T, s *Server, body *bytes.Buffer, ct string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest("POST", "/api/submit/files", body)
	r.Header.Set("Content-Type", ct)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)
	return rec
}

// makeZip creates an in-memory ZIP containing the given entries.
func makeZip(t *testing.T, entries [][2]string) []byte {
	t.Helper()
	buf := &bytes.Buffer{}
	zw := zip.NewWriter(buf)
	for _, e := range entries {
		fw, err := zw.Create(e[0])
		if err != nil {
			t.Fatalf("zip Create: %v", err)
		}
		_, _ = fw.Write([]byte(e[1]))
	}
	zw.Close()
	return buf.Bytes()
}

// buildMultipartRaw creates a multipart body where one part has raw bytes content.
func buildMultipartRaw(t *testing.T, name string, content []byte) (*bytes.Buffer, string) {
	t.Helper()
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	part, err := w.CreateFormFile("files", name)
	if err != nil {
		t.Fatalf("CreateFormFile: %v", err)
	}
	_, _ = part.Write(content)
	w.Close()
	return body, w.FormDataContentType()
}

// buildMultipartMultiRaw creates a multipart body with multiple parts, some with raw bytes.
func buildMultipartMultiRaw(t *testing.T, files []struct {
	name    string
	content []byte
}) (*bytes.Buffer, string) {
	t.Helper()
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	for _, f := range files {
		part, err := w.CreateFormFile("files", f.name)
		if err != nil {
			t.Fatalf("CreateFormFile: %v", err)
		}
		_, _ = part.Write(f.content)
	}
	w.Close()
	return body, w.FormDataContentType()
}

func TestSubmitFiles_SingleFile(t *testing.T) {
	q := &fakeQueue{}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{{"hello.md", "# Hello World"}})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 1 {
		t.Fatalf("uploaded = %d, want 1", len(resp.Uploaded))
	}
	if resp.Uploaded[0].Name != "hello.md" {
		t.Errorf("name = %q, want hello.md", resp.Uploaded[0].Name)
	}
	if resp.Uploaded[0].ID == "" {
		t.Error("uploaded file ID is empty")
	}
	// Raw file should exist on disk.
	rawPath := filepath.Join(kb, "raw", resp.Uploaded[0].ID+".md")
	if _, err := os.Stat(rawPath); err != nil {
		t.Errorf("raw file not found: %v", err)
	}
}

func TestSubmitFiles_MultipleFiles(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{
		{"a.md", "file a"},
		{"b.txt", "file b"},
		{"c.csv", "col1,col2"},
	})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 3 {
		t.Fatalf("uploaded = %d, want 3", len(resp.Uploaded))
	}
}

func TestSubmitFiles_InvalidExtension(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{{"malware.exe", "MZ..."}})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Reason != "extension not allowed" {
		t.Errorf("reason = %q, want 'extension not allowed'", resp.Failed[0].Reason)
	}
}

func TestSubmitFiles_MixedValid(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{
		{"good1.md", "content1"},
		{"good2.txt", "content2"},
		{"bad.exe", "nope"},
	})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 2 {
		t.Errorf("uploaded = %d, want 2", len(resp.Uploaded))
	}
	if len(resp.Failed) != 1 {
		t.Errorf("failed = %d, want 1", len(resp.Failed))
	}
}

func TestSubmitFiles_FileTooLarge(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	// Create content > 1MB.
	bigContent := bytes.Repeat([]byte("x"), int(testUploadConf().MaxFileSize)+1)
	body, ct := buildMultipartRaw(t, "big.md", bigContent)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Reason != fmt.Sprintf("file too large (max %dMB)", testUploadConf().MaxFileSize>>20) {
		t.Errorf("reason = %q", resp.Failed[0].Reason)
	}
}

func TestSubmitFiles_ZipUpload(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	zipData := makeZip(t, [][2]string{
		{"doc1.md", "# Document 1"},
		{"doc2.md", "# Document 2"},
	})
	body, ct := buildMultipartRaw(t, "archive.zip", zipData)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 2 {
		t.Fatalf("uploaded = %d, want 2; resp=%+v", len(resp.Uploaded), resp)
	}
}

func TestSubmitFiles_NestedZip(t *testing.T) {
	q := &fakeQueue{}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	innerZip := makeZip(t, [][2]string{{"inner.md", "inner content"}})
	outerZip := makeZip(t, [][2]string{
		{"readme.md", "# Top Level"},
		{"nested.zip", string(innerZip)},
	})

	body, ct := buildMultipartRaw(t, "outer.zip", outerZip)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 0 {
		t.Errorf("uploaded = %d, want 0; resp=%+v", len(resp.Uploaded), resp)
	}
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1; resp=%+v", len(resp.Failed), resp)
	}
	if resp.Failed[0].Name != "outer.zip" {
		t.Errorf("failed[0].Name = %q, want \"outer.zip\"", resp.Failed[0].Name)
	}
	if resp.Failed[0].Reason != "extension not allowed" {
		t.Errorf("reason = %q, want 'extension not allowed'", resp.Failed[0].Reason)
	}
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitFiles_DuplicateContent(t *testing.T) {
	q := &fakeQueue{submitErr: store.ErrDuplicate}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{{"dup.md", "duplicate content"}})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Reason != "content already submitted" {
		t.Errorf("reason = %q, want 'content already submitted'", resp.Failed[0].Reason)
	}
	// Raw file should be cleaned up.
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitFiles_SubmitError_CleansRaw(t *testing.T) {
	q := &fakeQueue{submitErr: fmt.Errorf("queue unavailable")}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	body, ct := buildMultipart(t, [][2]string{{"doc.md", "some content"}})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Reason != "enqueue: queue unavailable" {
		t.Errorf("reason = %q", resp.Failed[0].Reason)
	}
	// Raw file must NOT remain on disk.
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("raw file not cleaned up: %d files remain", len(entries))
	}
}

func TestSubmitFiles_TooManyFiles(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	// Create 21 files (exceeds maxFilesPerUpload=20).
	files := make([][2]string, 21)
	for i := range files {
		files[i] = [2]string{fmt.Sprintf("file%d.md", i), fmt.Sprintf("content %d", i)}
	}
	body, ct := buildMultipart(t, files)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	var errResp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("decode error response: %v", err)
	}
	if errResp.Error != fmt.Sprintf("too many files (max %d)", testUploadConf().MaxFilesPerUpload) {
		t.Errorf("error = %q", errResp.Error)
	}
}

func TestSubmitFiles_NoFiles(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	// Send a multipart body with no "files" parts.
	body := &bytes.Buffer{}
	w := multipart.NewWriter(body)
	w.Close()

	r := httptest.NewRequest("POST", "/api/submit/files", body)
	r.Header.Set("Content-Type", w.FormDataContentType())
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, r)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
	var errResp struct {
		Error string `json:"error"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("decode error response: %v", err)
	}
	if errResp.Error != "no files provided" {
		t.Errorf("error = %q, want 'no files provided'", errResp.Error)
	}
}

func TestSubmitFiles_ZipTooLarge(t *testing.T) {
	q := &fakeQueue{}
	s, _ := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	// Create a ZIP > 5MB. Use a compressible payload so the multipart body fits
	// within the 30MB body limit but the reported file size exceeds maxZipFileSize.
	bigContent := bytes.Repeat([]byte("z"), int(testUploadConf().MaxZipFileSize)+1)
	body, ct := buildMultipartRaw(t, "huge.zip", bigContent)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Reason != fmt.Sprintf("zip file too large (max %dMB)", testUploadConf().MaxZipFileSize>>20) {
		t.Errorf("reason = %q", resp.Failed[0].Reason)
	}
}

func TestSubmitFiles_ZipAtomicRollback_InvalidExtension(t *testing.T) {
	q := &fakeQueue{}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	zipData := makeZip(t, [][2]string{
		{"doc1.md", "# Doc 1"},
		{"doc2.md", "# Doc 2"},
		{"script.exe", "MZ..."},
	})
	body, ct := buildMultipartRaw(t, "archive.zip", zipData)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 0 {
		t.Errorf("uploaded = %d, want 0", len(resp.Uploaded))
	}
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Name != "archive.zip" {
		t.Errorf("failed[0].Name = %q, want \"archive.zip\"", resp.Failed[0].Name)
	}
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitFiles_ZipDuplicate_IdempotentSkip(t *testing.T) {
	// Compute hash of "duplicate content" to mark as duplicate.
	dupHash := fmt.Sprintf("%x", sha256.Sum256([]byte("duplicate content")))
	q := &fakeQueue{dupHashes: map[string]bool{dupHash: true}}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	zipData := makeZip(t, [][2]string{
		{"new1.md", "new content 1"},
		{"dup.md", "duplicate content"},
		{"new2.md", "new content 2"},
	})
	body, ct := buildMultipartRaw(t, "archive.zip", zipData)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 2 {
		t.Errorf("uploaded = %d, want 2; resp=%+v", len(resp.Uploaded), resp)
	}
	if len(resp.Failed) != 0 {
		t.Errorf("failed = %d, want 0; resp=%+v", len(resp.Failed), resp)
	}
	// 2 raw files should exist (new ones), duplicate's raw was removed.
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 2 {
		t.Errorf("raw files = %d, want 2", len(entries))
	}
}

func TestSubmitFiles_ZipAllDuplicates(t *testing.T) {
	q := &fakeQueue{submitErr: store.ErrDuplicate}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	zipData := makeZip(t, [][2]string{
		{"doc1.md", "content a"},
		{"doc2.md", "content b"},
	})
	body, ct := buildMultipartRaw(t, "archive.zip", zipData)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 0 {
		t.Errorf("uploaded = %d, want 0", len(resp.Uploaded))
	}
	if len(resp.Failed) != 0 {
		t.Errorf("failed = %d, want 0", len(resp.Failed))
	}
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitFiles_ZipAtomicRollback_SubmitError(t *testing.T) {
	q := &fakeQueue{submitErrAt: 2, submitErrAtErr: fmt.Errorf("db unavailable")}
	s, kb := newTestServer(t, q, &fakeStore{}, &fakeBridge{})

	zipData := makeZip(t, [][2]string{
		{"a.md", "aaa"},
		{"b.md", "bbb"},
		{"c.md", "ccc"},
	})
	body, ct := buildMultipartRaw(t, "archive.zip", zipData)
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want 202; body=%s", rec.Code, rec.Body.String())
	}

	var resp submitFilesResponse
	mustJSON(t, rec, &resp)
	if len(resp.Uploaded) != 0 {
		t.Errorf("uploaded = %d, want 0", len(resp.Uploaded))
	}
	if len(resp.Failed) != 1 {
		t.Fatalf("failed = %d, want 1", len(resp.Failed))
	}
	if resp.Failed[0].Name != "b.md" {
		t.Errorf("failed[0].Name = %q, want \"b.md\"", resp.Failed[0].Name)
	}
	entries, _ := os.ReadDir(filepath.Join(kb, "raw"))
	if len(entries) != 0 {
		t.Errorf("orphan raw files remain: %d", len(entries))
	}
}

func TestSubmitFiles_CustomUploadConfig(t *testing.T) {
	q := &fakeQueue{}
	kb := t.TempDir()
	cfg := Config{KBDir: kb, Model: "test-model", Upload: testUploadConf()}
	cfg.Upload.MaxFilesPerUpload = 2
	s := NewServer(q, &fakeStore{}, nil, &fakeBridge{}, cfg, nil)

	body, ct := buildMultipart(t, [][2]string{
		{"a.md", "1"},
		{"b.md", "2"},
		{"c.md", "3"},
	})
	rec := doMultipart(t, s, body, ct)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400; body=%s", rec.Code, rec.Body.String())
	}
}

func TestHandleUploadConfig(t *testing.T) {
	s, _ := newTestServer(t, &fakeQueue{}, &fakeStore{}, &fakeBridge{})

	rec := do(t, s, "GET", "/api/upload/config", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.Contains(ct, "application/json") {
		t.Fatalf("Content-Type = %q, want application/json", ct)
	}

	var resp uploadConfigResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v", err)
	}

	conf := testUploadConf()
	if resp.MaxFileSize != conf.MaxFileSize {
		t.Errorf("MaxFileSize = %d, want %d", resp.MaxFileSize, conf.MaxFileSize)
	}
	if resp.MaxZipFileSize != conf.MaxZipFileSize {
		t.Errorf("MaxZipFileSize = %d, want %d", resp.MaxZipFileSize, conf.MaxZipFileSize)
	}
	if resp.MaxFilesPerUpload != conf.MaxFilesPerUpload {
		t.Errorf("MaxFilesPerUpload = %d, want %d", resp.MaxFilesPerUpload, conf.MaxFilesPerUpload)
	}

	// Extensions should be sorted.
	for i := 1; i < len(resp.AllowedExtensions); i++ {
		if resp.AllowedExtensions[i-1] >= resp.AllowedExtensions[i] {
			t.Errorf("AllowedExtensions not sorted: %v", resp.AllowedExtensions)
			break
		}
	}

	// Should contain all allowedExtensions keys.
	extSet := map[string]bool{}
	for _, ext := range resp.AllowedExtensions {
		extSet[ext] = true
	}
	for ext := range allowedExtensions {
		if !extSet[ext] {
			t.Errorf("missing extension %q in response", ext)
		}
	}
}
