package bridge_test

import (
	"github.com/bybit-exchange/kaas/internal/api"
	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/worker"
)

// Compile-time assertions: DaemonClient satisfies worker.Engine and api.ChatBridge.
var _ worker.Engine = (*bridge.DaemonClient)(nil)
var _ api.ChatBridge = (*bridge.DaemonClient)(nil)
