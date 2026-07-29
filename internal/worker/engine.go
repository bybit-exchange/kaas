// Package worker consumes the compile task queue and drives each task through
// the Python AI engine's Extract → Pipeline phases via the bridge client,
// with bounded concurrency, lease heartbeating, and a shared circuit breaker.
package worker

import (
	"context"

	"github.com/bybit-exchange/kaas/internal/bridge"
)

// Engine is the subset of the bridge client the worker needs. *bridge.DaemonClient
// satisfies it; tests inject a fake.
type Engine interface {
	Extract(ctx context.Context, req bridge.ExtractRequest) (*bridge.ExtractResponse, error)
	Pipeline(ctx context.Context, req bridge.PipelineRequest) (*bridge.PipelineResponse, error)
}

// Compile-time assertion that the real client satisfies Engine.
var _ Engine = (*bridge.DaemonClient)(nil)
