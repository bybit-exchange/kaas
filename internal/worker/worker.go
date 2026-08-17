package worker

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/circuit"
	"github.com/bybit-exchange/kaas/internal/store"
)

// TaskQueue is the subset of *queue.Queue the worker needs.
type TaskQueue interface {
	Heartbeat(ctx context.Context, id, owner string) error
	SetStage(ctx context.Context, id, owner, stage string) error
	Ack(ctx context.Context, id, result string) error
	Nack(ctx context.Context, task *store.Task, errMsg string) (bool, error)
}

// Config tunes a Worker.
type Config struct {
	KBDir             string        // forwarded as ExtractRequest.KBDir and PipelineRequest.KBDir
	PipelineWorkers   int           // forwarded as PipelineRequest.Workers
	HeartbeatInterval time.Duration // lease renewal cadence (typically leaseTTL/3)
	Model             string        // forwarded as ExtractRequest.Model
	SummarizeModel    string        // forwarded as ExtractRequest.SummarizeModel
	ExtractStrategy   string        // forwarded as ExtractRequest.Strategy
}

// Worker processes a single claimed task end to end.
type Worker struct {
	q     TaskQueue
	eng   Engine
	brk   *circuit.Breaker
	owner string
	cfg   Config
}

// NewWorker builds a Worker.
func NewWorker(q TaskQueue, eng Engine, brk *circuit.Breaker, owner string, cfg Config) *Worker {
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 30 * time.Second
	}
	return &Worker{q: q, eng: eng, brk: brk, owner: owner, cfg: cfg}
}

// Process runs Extract → Pipeline for task and Acks on success. On engine
// failure it Nacks (requeue/fail per attempts). If the lease is lost mid-flight
// (heartbeat or an owner-scoped write returns ErrNotFound) it abandons the task
// without Ack/Nack — RecoverExpired will requeue it.
func (w *Worker) Process(parent context.Context, task *store.Task) {
	ctx, cancel := context.WithCancel(parent)

	// Heartbeat loop keeps the lease alive during long bridge calls.
	var hbWG sync.WaitGroup
	hbWG.Add(1)
	go func() {
		defer hbWG.Done()
		t := time.NewTicker(w.cfg.HeartbeatInterval)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if err := w.q.Heartbeat(ctx, task.ID, w.owner); err != nil {
					cancel() // lost lease or error: abort the work
					return
				}
			}
		}
	}()
	// Cancel the heartbeat BEFORE waiting for it, so Process returns promptly
	// instead of blocking until the goroutine's next tick detects cancellation.
	defer func() {
		cancel()
		hbWG.Wait()
	}()

	// One relative path feeding both requests. It is the extraction file's key
	// and the article's sources: entry, and submit.go builds RawPath by joining
	// an already-absolute KBDir, so forwarding it verbatim used to record an
	// absolute filesystem path in every UI-ingested article.
	sourceRef, err := filepath.Rel(w.cfg.KBDir, task.RawPath)
	if err != nil {
		w.fail(ctx, task, fmt.Sprintf("relative source ref for %q under %q: %v",
			task.RawPath, w.cfg.KBDir, err))
		return
	}

	// Detect rich documents by extension; they are routed via FilePath
	// (the Python daemon converts them) instead of reading binary content.
	fext := strings.ToLower(filepath.Ext(task.RawPath))
	rich := isRichDoc(fext)
	if rich {
		sourceRef = strings.TrimSuffix(sourceRef, fext) + ".md"
	}

	// Build the ExtractRequest: rich docs send FilePath, text files send Content.
	req := bridge.ExtractRequest{
		KBDir:          w.cfg.KBDir,
		Source:         sourceRef,
		Model:          w.cfg.Model,
		Strategy:       w.cfg.ExtractStrategy,
		SummarizeModel: w.cfg.SummarizeModel,
	}
	if rich {
		req.FilePath = task.RawPath
	} else {
		content, readErr := os.ReadFile(task.RawPath)
		if readErr != nil {
			w.fail(ctx, task, fmt.Sprintf("read raw %q: %v", task.RawPath, readErr))
			return
		}
		req.Content = string(content)
	}

	// Extract (Claim already set stage=extract). The engine persists the
	// extraction under <kb>/extraction/<rel> before returning, so a pipeline
	// failure with an attempt left replays the task without paying again.
	var ext *bridge.ExtractResponse
	err = w.brk.Do(func() error {
		var e error
		ext, e = w.eng.Extract(ctx, req)
		return e
	})
	if err != nil {
		w.fail(ctx, task, fmt.Sprintf("extract: %v", err))
		return
	}

	// Advance stage → pipeline (owner-scoped; ErrNotFound means lease lost).
	if err := w.q.SetStage(ctx, task.ID, w.owner, store.StagePipeline); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			log.Printf("worker: %s lost lease before pipeline; abandoning", task.ID)
		} else {
			log.Printf("worker: %s set stage failed (may be transient): %v", task.ID, err)
		}
		return
	}

	// Pipeline (single item; Python builds the markdown index internally).
	var pipe *bridge.PipelineResponse
	err = w.brk.Do(func() error {
		var e error
		pipe, e = w.eng.Pipeline(ctx, bridge.PipelineRequest{
			KBDir:   w.cfg.KBDir,
			Workers: w.cfg.PipelineWorkers,
			Items: []bridge.PipelineItem{{
				ContentHash: task.ContentHash,
				SourceRef:   sourceRef,
			}},
		})
		return e
	})
	if err != nil {
		w.fail(ctx, task, fmt.Sprintf("pipeline: %v", err))
		return
	}

	if ctx.Err() != nil {
		// Lease lost / shutdown between pipeline and ack: abandon (RecoverExpired requeues).
		return
	}
	if err := w.q.Ack(ctx, task.ID, buildResult(ext, pipe)); err != nil {
		// Lease lost at ack (recovered & reclaimed elsewhere): drop.
		log.Printf("worker: %s ack failed (lease lost?): %v", task.ID, err)
	}
}

// fail Nacks the task unless the context was cancelled (lease lost / shutdown),
// in which case the task is left for RecoverExpired to requeue.
func (w *Worker) fail(ctx context.Context, task *store.Task, msg string) {
	if ctx.Err() != nil {
		return
	}
	if _, err := w.q.Nack(ctx, task, msg); err != nil {
		log.Printf("worker: %s nack failed: %v", task.ID, err)
	}
}

// buildResult assembles the task result JSON from the phase cost/result blobs.
func buildResult(ext *bridge.ExtractResponse, pipe *bridge.PipelineResponse) string {
	m := map[string]json.RawMessage{}
	if ext != nil {
		m["extract_cost"] = ext.Cost
	}
	if pipe != nil {
		m["pipeline_results"] = pipe.Results
		m["pipeline_cost"] = pipe.Cost
	}
	b, err := json.Marshal(m)
	if err != nil {
		log.Printf("worker: buildResult marshal error: %v", err)
		return "{}"
	}
	return string(b)
}

// isRichDoc returns true for document extensions that require MarkItDown conversion.
func isRichDoc(ext string) bool {
	switch ext {
	case ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".epub", ".rtf":
		return true
	}
	return false
}

// WorkerID returns a per-process owner id (hostname-pid). The pid changes on
// restart so RecoverExpired reclaims leases orphaned by a crashed instance.
func WorkerID() string {
	h, err := os.Hostname()
	if err != nil || h == "" {
		h = "kaas"
	}
	return fmt.Sprintf("%s-%d", h, os.Getpid())
}
