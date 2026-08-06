package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/bybit-exchange/kaas/internal/store"
)

// Compile-time proof that *Store satisfies the full DerivedJobStore interface.
// A future signature drift in store.DerivedJobStore becomes a build error here
// rather than silently disabling the derive runner at runtime.
var _ store.DerivedJobStore = (*Store)(nil)

// derivedJobColumns is the canonical column order for SELECT + scanDerivedJob.
const derivedJobColumns = `id, slug, topic, model, select_from, status, stage,
	error, result, created_at, updated_at`

// derivedSchema holds KB-level derive jobs. The partial unique index is the
// whole point of the table: it enforces "one active derive per slug" in the
// database rather than in the runner, while leaving terminal rows as history a
// re-derive can sit alongside.
const derivedSchema = `
CREATE TABLE IF NOT EXISTS derived_jobs (
	id          TEXT PRIMARY KEY,
	slug        TEXT NOT NULL,
	topic       TEXT NOT NULL,
	model       TEXT NOT NULL DEFAULT '',
	select_from TEXT NOT NULL DEFAULT '',
	status      TEXT NOT NULL,
	stage       TEXT NOT NULL,
	error       TEXT NOT NULL DEFAULT '',
	result      TEXT NOT NULL DEFAULT '',
	created_at  INTEGER NOT NULL,
	updated_at  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_derived_jobs_active_slug
	ON derived_jobs(slug) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_derived_jobs_status_created
	ON derived_jobs(status, created_at);
`

func scanDerivedJob(row interface{ Scan(...any) error }) (*store.DerivedJob, error) {
	var j store.DerivedJob
	err := row.Scan(&j.ID, &j.Slug, &j.Topic, &j.Model, &j.SelectFrom, &j.Status,
		&j.Stage, &j.Error, &j.Result, &j.CreatedAt, &j.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &j, nil
}

// CreateDerivedJob inserts a pending job, mapping the partial unique index
// violation onto ErrDerivedJobExists.
func (s *Store) CreateDerivedJob(ctx context.Context, j *store.DerivedJob) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO derived_jobs (`+derivedJobColumns+`)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		j.ID, j.Slug, j.Topic, j.Model, j.SelectFrom, j.Status, j.Stage, j.Error,
		j.Result, j.CreatedAt, j.UpdatedAt)
	if err != nil {
		if isUniqueViolation(err) {
			return fmt.Errorf("%w: %q", store.ErrDerivedJobExists, j.Slug)
		}
		return fmt.Errorf("create derived job: %w", err)
	}
	return nil
}

// GetDerivedJob returns the job by id, or store.ErrNotFound.
func (s *Store) GetDerivedJob(ctx context.Context, id string) (*store.DerivedJob, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT `+derivedJobColumns+` FROM derived_jobs WHERE id = ?`, id)
	j, err := scanDerivedJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, store.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get derived job: %w", err)
	}
	return j, nil
}

// ClaimNextDerivedJob marks the oldest pending job running, but only when no job
// is already running: a derive rewrites a directory and spends money, so
// single-flight is enforced here rather than trusted to the caller.
func (s *Store) ClaimNextDerivedJob(ctx context.Context, now int64) (*store.DerivedJob, error) {
	row := s.db.QueryRowContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, updated_at = ?
		WHERE id = (
			SELECT id FROM derived_jobs WHERE status = ?
			ORDER BY created_at ASC, id ASC LIMIT 1
		)
		AND NOT EXISTS (SELECT 1 FROM derived_jobs WHERE status = ?)
		RETURNING `+derivedJobColumns,
		store.DerivedStatusRunning, store.DerivedStageFilter, now,
		store.DerivedStatusPending, store.DerivedStatusRunning)
	j, err := scanDerivedJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("claim derived job: %w", err)
	}
	return j, nil
}

// SetDerivedJobStage records progress on a running job.
func (s *Store) SetDerivedJobStage(ctx context.Context, id, stage string, now int64) error {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET stage = ?, updated_at = ?
		WHERE id = ? AND status = ?`,
		stage, now, id, store.DerivedStatusRunning)
	if err != nil {
		return fmt.Errorf("set derived job stage: %w", err)
	}
	return requireOneRow(res, "set derived job stage")
}

// FinishDerivedJob writes a terminal status. Stage always lands on done, so a
// failed job's last stage is readable from its error rather than from stage.
func (s *Store) FinishDerivedJob(ctx context.Context, id, status, errMsg, result string, now int64) error {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, error = ?, result = ?, updated_at = ?
		WHERE id = ? AND status = ?`,
		status, store.DerivedStageDone, errMsg, result, now, id, store.DerivedStatusRunning)
	if err != nil {
		return fmt.Errorf("finish derived job: %w", err)
	}
	return requireOneRow(res, "finish derived job")
}

// RecoverRunningDerivedJobs fails every job a previous process left running.
//
// Not requeued: a derive is not resumable. It may have died anywhere between the
// filter and the prune, and its directory is already on disk. Failing loudly puts
// the decision back with the operator, who can retry from the UI — the
// interrupted derive left an uncompiled KB, and POST /api/derive replaces one of
// those instead of refusing the slug.
//
// # Single instance
//
// This assumes exactly one kaas process per SQLite file, and it is the one place
// that assumption is load-bearing: every running row is failed unconditionally,
// with no owner id and no lease deadline to tell "mine, crashed" from "another
// process, still working". A second process starting against the same file would
// fail the first one's in-flight derive, and because the row goes terminal it
// stops blocking the partial unique index, so the claim hands the same slug out
// again and two processes write the same derived/<slug>/.
//
// The tasks table in this package does carry lease_owner / lease_expires_at and
// recovers by deadline (RecoverExpired) instead. That deliberately does not carry
// over: tasks are many, short and retryable, so leases buy real throughput,
// whereas a derive is single-flight by construction — the claim refuses to start
// one while another runs — so a lease would only add machinery around a queue
// depth of one. Multi-instance was never in scope (see the spec); if it ever is,
// this function and ClaimNextDerivedJob are what need leases, together.
func (s *Store) RecoverRunningDerivedJobs(ctx context.Context, now int64) (int, error) {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, error = ?, updated_at = ?
		WHERE status = ?`,
		store.DerivedStatusFailed, store.DerivedStageDone,
		"interrupted by a backend restart; the derived knowledge base was left "+
			"incomplete, so retry the derive to replace it",
		now, store.DerivedStatusRunning)
	if err != nil {
		return 0, fmt.Errorf("recover derived jobs: %w", err)
	}
	n, _ := res.RowsAffected()
	return int(n), nil
}
