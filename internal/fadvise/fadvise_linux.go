//go:build linux

package fadvise

import (
	"os"

	"golang.org/x/sys/unix"
)

// EvictFD advises the kernel to evict cached pages for the entire file
// referenced by f. This reduces page-cache pressure in long-running
// services that perform many one-shot reads.
func EvictFD(f *os.File) error {
	// Get file size to advise the full extent.
	info, err := f.Stat()
	if err != nil {
		return err
	}
	return unix.Fadvise(int(f.Fd()), 0, info.Size(), unix.FADV_DONTNEED)
}
