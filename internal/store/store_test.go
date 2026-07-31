// Package store holds only type, interface and sentinel declarations — there is
// no behaviour to exercise. What it does have is an implicit contract that the
// wiring in cmd/kaas depends on: the sqlite backend must satisfy store.Store
// *and* api.SessionStore, because main.go extracts the session interface from
// the same handle with a comma-ok cast (`ss, _ := st.(api.SessionStore)`). If
// sqlite.Store ever drifts out of api.SessionStore that cast silently yields a
// nil interface and every chat-persistence call panics at runtime instead of
// failing to build. These assertions turn that into a compile error.
package store_test

import (
	"github.com/bybit-exchange/kaas/internal/api"
	"github.com/bybit-exchange/kaas/internal/store"
	"github.com/bybit-exchange/kaas/internal/store/sqlite"
)

var (
	_ store.Store      = (*sqlite.Store)(nil)
	_ api.TaskStore    = (*sqlite.Store)(nil)
	_ api.SessionStore = (*sqlite.Store)(nil)
)
