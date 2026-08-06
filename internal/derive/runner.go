// Package derive runs knowledge-base-level derive jobs.
//
// Deliberately separate from internal/worker: that package's Task is
// document-shaped and its Process runs one document through extract → pipeline.
// Keeping derive out of it means a derive can neither starve document ingestion
// nor break it, and the derived_jobs unique index gives "one derive per slug"
// without touching the compile queue's hot path.
package derive

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/kbpath"
	"github.com/bybit-exchange/kaas/internal/store"
)

// Bridge is the subset of *bridge.DaemonClient the runner needs.
type Bridge interface {
	Derive(ctx context.Context, req bridge.DeriveRequest) (*bridge.DeriveResponse, error)
}

// Config holds the runner's settings.
type Config struct {
	KBDir        string        // knowledge-base root every derive is relative to
	Model        string        // default model when a job names none
	PollInterval time.Duration // how often to look for a pending job
	Timeout      time.Duration // ceiling for one derive call
}

// Runner claims pending derive jobs one at a time and drives them through the
// bridge. Single-flight: the store's claim refuses to hand out a job while one
// is running, so a slow derive queues rather than overlapping.
//
// One runner per store is assumed, i.e. one kaas process per SQLite file. The
// runner holds no lease on a claimed job: startup recovery fails every running row
// on sight (see RecoverRunningDerivedJobs in internal/store/sqlite), so a second
// process would kill this one's in-flight derive and then be handed the same slug,
// leaving both writing the same derived/<slug>/. Leases are deliberately not
// implemented — a derive is single-flight anyway, so they would guard a queue of
// one — but that makes the assumption a real precondition rather than an
// optimisation, and running two instances against one database breaks derive.
type Runner struct {
	js     store.DerivedJobStore
	br     Bridge
	cfg    Config
	logger *slog.Logger
}

// NewRunner builds a Runner. A nil logger falls back to slog.Default().
func NewRunner(js store.DerivedJobStore, br Bridge, cfg Config, logger *slog.Logger) *Runner {
	if logger == nil {
		logger = slog.Default()
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = 2 * time.Second
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 2 * time.Hour
	}
	return &Runner{js: js, br: br, cfg: cfg, logger: logger}
}

// Run polls for pending jobs until ctx is cancelled. Returns nil on
// context cancellation. Returns a non-nil error only when startup recovery
// fails; the runnable loop in cmd/kaas/main.go treats that as fatal.
//
// It first fails any job a previous process left running: a derive is not
// resumable, so leaving one "running" forever would block its slug behind the
// unique index with no way to clear it from the UI.
func (r *Runner) Run(ctx context.Context) error {
	n, err := r.js.RecoverRunningDerivedJobs(ctx, now())
	if err != nil {
		return fmt.Errorf("derive: recover interrupted jobs: %w", err)
	}
	if n > 0 {
		r.logger.Warn("derive: failed jobs interrupted by a restart", "count", n)
	}

	ticker := time.NewTicker(r.cfg.PollInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			job, err := r.js.ClaimNextDerivedJob(ctx, now())
			if err != nil {
				r.logger.Error("derive: claim job", "err", err)
				continue
			}
			if job == nil {
				continue
			}
			r.process(ctx, job)
		}
	}
}

// process runs one job to a terminal status. Every exit path writes a terminal
// row: a job left running blocks its slug behind the unique index.
func (r *Runner) process(ctx context.Context, job *store.DerivedJob) {
	r.logger.Info("derive: starting", "id", job.ID, "slug", job.Slug, "topic", job.Topic)

	// The bridge call covers filter → copy → compile → prune in one round trip,
	// so this is the only stage the runner can honestly report mid-flight.
	if err := r.js.SetDerivedJobStage(ctx, job.ID, store.DerivedStageCompile, now()); err != nil {
		r.logger.Warn("derive: set stage", "id", job.ID, "err", err)
	}

	model := job.Model
	if model == "" {
		model = r.cfg.Model
	}

	// The bridge call context is derived from the run context rather than
	// context.Background(), so a SIGTERM aborts an in-progress derive. This
	// differs from the dispatcher's Process (which uses context.Background() so
	// shutdown never aborts paid per-document LLM work), but a derive runs
	// inline in the poll loop, so a background context would block shutdown
	// indefinitely. Operators who lose a derive on SIGTERM can force a re-run.
	callCtx, cancel := context.WithTimeout(ctx, r.cfg.Timeout)
	defer cancel()

	resp, err := r.br.Derive(callCtx, bridge.DeriveRequest{
		KBDir: r.cfg.KBDir,
		Topic: job.Topic,
		Slug:  job.Slug,
		// Force only replaces a derive that never finished; the API refused the
		// slug outright if a compiled KB holds it. Decided here, from the
		// directory as it stands at claim time, rather than carried on the job
		// row: the row would record what was true when the request arrived, and
		// a queued job can wait behind a long derive.
		Force: r.replaceable(job.Slug),
		Model: model,
	})
	if err != nil {
		r.logger.Error("derive: failed", "id", job.ID, "slug", job.Slug, "err", err)
		r.finish(job.ID, store.DerivedStatusFailed, err.Error(), "")
		return
	}

	result, mErr := json.Marshal(resp)
	if mErr != nil {
		// The derive itself succeeded; losing the result JSON must not report it
		// as a failure, or the operator re-runs work already paid for.
		r.logger.Error("derive: encode result", "id", job.ID, "err", mErr)
		result = []byte("{}")
	}
	r.logger.Info("derive: done", "id", job.ID, "slug", job.Slug,
		"documents", resp.Documents, "offtopic", resp.Offtopic)
	r.finish(job.ID, store.DerivedStatusSucceeded, "", string(result))
}

// replaceable reports whether derived/<slug> holds an incomplete derive: a
// manifest written before compiling (spec E1) whose compiled flag never became
// true. That is what a derive killed mid-flight leaves behind, and it is the only
// state the engine may overwrite.
//
// False for everything else, deliberately: no directory (the normal case, where
// force would only mask a race with a concurrent CLI run), a compiled KB, and a
// manifest that cannot be parsed — an unreadable manifest is not evidence that
// the articles underneath it are worthless.
func (r *Runner) replaceable(slug string) bool {
	dir, err := kbpath.Resolve(r.cfg.KBDir, slug)
	if err != nil {
		return false
	}
	m, err := kbpath.ReadManifest(dir)
	if err != nil {
		r.logger.Warn("derive: cannot read the existing manifest, not replacing the directory",
			"slug", slug, "err", err)
		return false
	}
	return !m.Compiled
}

// finish writes a terminal row on a fresh context: the run may have ended
// because ctx was cancelled, and the row still has to be recorded.
func (r *Runner) finish(id, status, errMsg, result string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := r.js.FinishDerivedJob(ctx, id, status, errMsg, result, now()); err != nil {
		r.logger.Error("derive: finish job", "id", id, "status", status, "err", err)
	}
}

func now() int64 { return time.Now().UnixMilli() }
