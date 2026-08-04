package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/bybit-exchange/kaas/internal/store"
)

// derivedJobColumns is the canonical column order for SELECT + scanDerivedJob.
const derivedJobColumns = `id, slug, topic, model, status, stage, error, result,
	created_at, updated_at`

// derivedSchema holds KB-level derive jobs. The partial unique index is the
// whole point of the table: it enforces "one active derive per slug" in the
// database rather than in the runner, while leaving terminal rows as history a
// re-derive can sit alongside.
const derivedSchema = `
CREATE TABLE IF NOT EXISTS derived_jobs (
	id         TEXT PRIMARY KEY,
	slug       TEXT NOT NULL,
	topic      TEXT NOT NULL,
	model      TEXT NOT NULL DEFAULT '',
	status     TEXT NOT NULL,
	stage      TEXT NOT NULL,
	error      TEXT NOT NULL DEFAULT '',
	result     TEXT NOT NULL DEFAULT '',
	created_at INTEGER NOT NULL,
	updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_derived_jobs_active_slug
	ON derived_jobs(slug) WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_derived_jobs_status_created
	ON derived_jobs(status, created_at);
`

func scanDerivedJob(row interface{ Scan(...any) error }) (*store.DerivedJob, error) {
	var j store.DerivedJob
	err := row.Scan(&j.ID, &j.Slug, &j.Topic, &j.Model, &j.Status, &j.Stage,
		&j.Error, &j.Result, &j.CreatedAt, &j.UpdatedAt)
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
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		j.ID, j.Slug, j.Topic, j.Model, j.Status, j.Stage, j.Error, j.Result,
		j.CreatedAt, j.UpdatedAt)
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

// ListDerivedJobs returns the newest jobs first.
func (s *Store) ListDerivedJobs(ctx context.Context, limit int) ([]*store.DerivedJob, error) {
	q := `SELECT ` + derivedJobColumns + ` FROM derived_jobs ORDER BY created_at DESC`
	args := []any{}
	if limit > 0 {
		q += ` LIMIT ?`
		args = append(args, limit)
	}
	rows, err := s.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("list derived jobs: %w", err)
	}
	defer rows.Close()

	var out []*store.DerivedJob
	for rows.Next() {
		j, err := scanDerivedJob(rows)
		if err != nil {
			return nil, fmt.Errorf("list derived jobs: scan: %w", err)
		}
		out = append(out, j)
	}
	return out, rows.Err()
}

// ClaimNextDerivedJob marks the oldest pending job running, but only when no job
// is already running: a derive rewrites a directory and spends money, so
// single-flight is enforced here rather than trusted to the caller.
func (s *Store) ClaimNextDerivedJob(ctx context.Context, now int64) (*store.DerivedJob, error) {
	row := s.db.QueryRowContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, updated_at = ?
		WHERE id = (
			SELECT id FROM derived_jobs WHERE status = ?
			ORDER BY created_at ASC LIMIT 1
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
	if n, _ := res.RowsAffected(); n == 0 {
		return store.ErrNotFound
	}
	return nil
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
	if n, _ := res.RowsAffected(); n == 0 {
		return store.ErrNotFound
	}
	return nil
}

// RecoverRunningDerivedJobs fails every job a previous process left running.
//
// Not requeued: a derive is not resumable. It may have died anywhere between the
// filter and the prune, and re-running it from the start would need --force to
// get past the directory it already created. Failing loudly puts that decision
// back with the operator.
func (s *Store) RecoverRunningDerivedJobs(ctx context.Context, now int64) (int, error) {
	res, err := s.db.ExecContext(ctx, `
		UPDATE derived_jobs SET status = ?, stage = ?, error = ?, updated_at = ?
		WHERE status = ?`,
		store.DerivedStatusFailed, store.DerivedStageDone,
		"interrupted by a backend restart; re-run the derive with force enabled",
		now, store.DerivedStatusRunning)
	if err != nil {
		return 0, fmt.Errorf("recover derived jobs: %w", err)
	}
	n, _ := res.RowsAffected()
	return int(n), nil
}
