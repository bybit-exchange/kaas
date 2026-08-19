package fadvise

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadFileAndEvict(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.txt")
	content := []byte("hello world\nline two\n")
	if err := os.WriteFile(path, content, 0644); err != nil {
		t.Fatal(err)
	}

	got, err := ReadFileAndEvict(path)
	if err != nil {
		t.Fatalf("ReadFileAndEvict: %v", err)
	}
	if string(got) != string(content) {
		t.Errorf("got %q, want %q", got, content)
	}
}

func TestReadFileAndEvict_NotFound(t *testing.T) {
	_, err := ReadFileAndEvict("/nonexistent/path/file.txt")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestReadHeadAndEvict_FullRead(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "small.txt")
	content := []byte("short")
	if err := os.WriteFile(path, content, 0644); err != nil {
		t.Fatal(err)
	}

	// maxBytes larger than file — should return full content without error.
	got, err := ReadHeadAndEvict(path, 4096)
	if err != nil {
		t.Fatalf("ReadHeadAndEvict: %v", err)
	}
	if string(got) != string(content) {
		t.Errorf("got %q, want %q", got, content)
	}
}

func TestReadHeadAndEvict_Truncated(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "big.txt")
	content := make([]byte, 8192)
	for i := range content {
		content[i] = byte('A' + (i % 26))
	}
	if err := os.WriteFile(path, content, 0644); err != nil {
		t.Fatal(err)
	}

	got, err := ReadHeadAndEvict(path, 1024)
	if err != nil {
		t.Fatalf("ReadHeadAndEvict: %v", err)
	}
	if len(got) != 1024 {
		t.Errorf("got %d bytes, want 1024", len(got))
	}
	if string(got) != string(content[:1024]) {
		t.Error("truncated content does not match expected prefix")
	}
}

func TestReadHeadAndEvict_EmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "empty.txt")
	if err := os.WriteFile(path, nil, 0644); err != nil {
		t.Fatal(err)
	}

	got, err := ReadHeadAndEvict(path, 4096)
	if err != nil {
		t.Fatalf("ReadHeadAndEvict: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty slice, got %d bytes", len(got))
	}
}

func TestReadHeadAndEvict_NotFound(t *testing.T) {
	_, err := ReadHeadAndEvict("/nonexistent/path/file.txt", 1024)
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestEvictFD_NilSafe(t *testing.T) {
	// On non-Linux (macOS), EvictFD is a no-op so should succeed on any file.
	dir := t.TempDir()
	path := filepath.Join(dir, "evict.txt")
	if err := os.WriteFile(path, []byte("data"), 0644); err != nil {
		t.Fatal(err)
	}

	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()

	if err := EvictFD(f); err != nil {
		t.Fatalf("EvictFD: %v", err)
	}
}
