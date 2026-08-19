//go:build !linux

package fadvise

import "os"

// EvictFD is a no-op on non-Linux platforms where POSIX_FADVISE is
// unavailable or not meaningful.
func EvictFD(_ *os.File) error {
	return nil
}
