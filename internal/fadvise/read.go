// Package fadvise provides file-read helpers that advise the kernel to
// evict pages from the page cache after reading (POSIX_FADVISE FADV_DONTNEED).
// This prevents unbounded page-cache growth in long-running services that
// perform many sequential one-shot reads.
package fadvise

import (
	"io"
	"os"
)

// ReadFileAndEvict reads the entire file at path, advises the kernel to
// evict the pages from cache, then closes the file. It is a drop-in
// replacement for os.ReadFile with added cache eviction.
func ReadFileAndEvict(path string) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	data, err := io.ReadAll(f)
	if err != nil {
		return nil, err
	}

	// Best-effort eviction; ignore errors.
	_ = EvictFD(f)

	return data, nil
}

// ReadHeadAndEvict reads up to maxBytes from the file at path, advises the
// kernel to evict pages, then closes the file. If the file is smaller than
// maxBytes the returned slice will be shorter — this is not an error.
func ReadHeadAndEvict(path string, maxBytes int) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	buf := make([]byte, maxBytes)
	n, err := io.ReadFull(f, buf)
	if err != nil && err != io.ErrUnexpectedEOF && err != io.EOF {
		return nil, err
	}

	// Best-effort eviction; ignore errors.
	_ = EvictFD(f)

	return buf[:n], nil
}
