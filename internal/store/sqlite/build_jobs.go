package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	"github.com/bybit-exchange/kaas/internal/store"
)

// Compile-time proof that *Store satisfies the BuildJobStore interface.
var _ store.BuildJobStore = (*Store)(nil)

// buildJobColumns is the canonical column order for SELECT + scanBuildJob.
const buildJobColumns = `id, source, title, file_count, status, error, created_at, updated_at`

// buildJobSchema creates the build_jobs table and its indexes.
const buildJobSchema = `
CREATE TABLE IF NOT EXISTS build_jobs (
	id          TEXT PRIMARY KEY,
	source      TEXT NOT NULL,
	title       TEXT NOT NULL DEFAULT '',
	file_count  INTEGER NOT NULL DEFAULT 1,
	status      TEXT NOT NULL,
	error       TEXT NOT NULL DEFAULT '',
	created_at  INTEGER NOT NULL,
	updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_build_jobs_status_created ON build_jobs(status, created_at);
`

func scanBuildJob(row interface{ Scan(...any) error }) (*store.BuildJob, error) {
	var j store.BuildJob
	err := row.Scan(&j.ID, &j.Source, &j.Title, &j.FileCount, &j.Status,
		&j.Error, &j.CreatedAt, &j.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &j, nil
}

// CreateBuildJob inserts a new build job.
func (s *Store) CreateBuildJob(ctx context.Context, j *store.BuildJob) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO build_jobs (`+buildJobColumns+`)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		j.ID, j.Source, j.Title, j.FileCount, j.Status, j.Error,
		j.CreatedAt, j.UpdatedAt)
	if err != nil {
		return fmt.Errorf("create build job: %w", err)
	}
	return nil
}

// GetBuildJob returns the build job by id, or store.ErrNotFound.
func (s *Store) GetBuildJob(ctx context.Context, id string) (*store.BuildJob, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT `+buildJobColumns+` FROM build_jobs WHERE id = ?`, id)
	j, err := scanBuildJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, store.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get build job: %w", err)
	}
	return j, nil
}

// ListBuildJobsPaged returns a page of build jobs matching the filter.
func (s *Store) ListBuildJobsPaged(ctx context.Context, f store.BuildJobListFilter) (*store.BuildJobListResult, error) {
	var where []string
	var args []any

	if f.Status != "" {
		where = append(where, `status = ?`)
		args = append(args, f.Status)
	}
	if f.Query != "" {
		pattern := "%" + f.Query + "%"
		where = append(where, `title LIKE ?`)
		args = append(args, pattern)
	}

	var whereClause string
	if len(where) > 0 {
		whereClause = ` WHERE ` + strings.Join(where, ` AND `)
	}

	// Count total matching rows.
	countQ := `SELECT COUNT(*) FROM build_jobs` + whereClause
	var total int
	if err := s.db.QueryRowContext(ctx, countQ, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("list build jobs paged count: %w", err)
	}

	// Determine sort column and direction.
	allowedSort := map[string]string{
		"title":      "title",
		"source":     "source",
		"status":     "status",
		"file_count": "file_count",
		"created_at": "created_at",
		"updated_at": "updated_at",
	}
	sortCol := "created_at"
	if col, ok := allowedSort[f.SortBy]; ok {
		sortCol = col
	}
	sortDir := "DESC"
	if f.SortDir == "asc" {
		sortDir = "ASC"
	}

	// Fetch the page.
	selectQ := `SELECT ` + buildJobColumns + ` FROM build_jobs` + whereClause + ` ORDER BY ` + sortCol + ` ` + sortDir + `, id DESC`
	selectArgs := append([]any{}, args...)
	if f.Limit > 0 {
		selectQ += ` LIMIT ?`
		selectArgs = append(selectArgs, f.Limit)
	}
	if f.Offset > 0 {
		selectQ += ` OFFSET ?`
		selectArgs = append(selectArgs, f.Offset)
	}

	rows, err := s.db.QueryContext(ctx, selectQ, selectArgs...)
	if err != nil {
		return nil, fmt.Errorf("list build jobs paged: %w", err)
	}
	defer rows.Close()

	var jobs []*store.BuildJob
	for rows.Next() {
		j, err := scanBuildJob(rows)
		if err != nil {
			return nil, fmt.Errorf("list build jobs paged scan: %w", err)
		}
		jobs = append(jobs, j)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("list build jobs paged rows: %w", err)
	}
	return &store.BuildJobListResult{Jobs: jobs, Total: total}, nil
}

// DeleteBuildJob removes a build job by id.
func (s *Store) DeleteBuildJob(ctx context.Context, id string) error {
	const q = `DELETE FROM build_jobs WHERE id = ?`
	res, err := s.db.ExecContext(ctx, q, id)
	if err != nil {
		return fmt.Errorf("delete build job: %w", err)
	}
	return requireOneRow(res, "delete build job")
}

// UpdateBuildJobFileCount sets the file_count and updated_at for a build job.
func (s *Store) UpdateBuildJobFileCount(ctx context.Context, id string, count int, now int64) error {
	const q = `UPDATE build_jobs SET file_count = ?, updated_at = ? WHERE id = ?`
	res, err := s.db.ExecContext(ctx, q, count, now, id)
	if err != nil {
		return fmt.Errorf("update build job file count: %w", err)
	}
	return requireOneRow(res, "update build job file count")
}

// RefreshBuildJobStatuses recomputes status for all non-terminal build jobs
// from their child tasks using a single CTE-based UPDATE.
func (s *Store) RefreshBuildJobStatuses(ctx context.Context, now int64) error {
	const q = `
WITH job_status AS (
    SELECT
        t.build_job_id,
        CASE
            WHEN SUM(CASE WHEN t.status = 'running' THEN 1 ELSE 0 END) > 0 THEN 'running'
            WHEN SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) > 0 THEN 'pending'
            WHEN COUNT(*) = SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) THEN 'succeeded'
            WHEN SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) > 0 THEN 'partial'
            ELSE 'failed'
        END AS computed_status
    FROM tasks t
    WHERE t.build_job_id IN (
        SELECT id FROM build_jobs WHERE status IN ('pending', 'running')
    )
    GROUP BY t.build_job_id
)
UPDATE build_jobs
SET status = js.computed_status, updated_at = ?
FROM job_status js
WHERE build_jobs.id = js.build_job_id
  AND build_jobs.status != js.computed_status`
	_, err := s.db.ExecContext(ctx, q, now)
	if err != nil {
		return fmt.Errorf("refresh build job statuses: %w", err)
	}
	return nil
}

// RefreshBuildJobStatus recomputes status for a single build job from its
// child tasks. This is the single-row variant used before get/delete.
func (s *Store) RefreshBuildJobStatus(ctx context.Context, id string, now int64) error {
	const q = `
UPDATE build_jobs
SET status = (
    SELECT CASE
        WHEN SUM(CASE WHEN t.status = 'running' THEN 1 ELSE 0 END) > 0 THEN 'running'
        WHEN SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) > 0 THEN 'pending'
        WHEN COUNT(*) = SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) THEN 'succeeded'
        WHEN SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END) > 0 THEN 'partial'
        ELSE 'failed'
    END
    FROM tasks t
    WHERE t.build_job_id = build_jobs.id
), updated_at = ?
WHERE id = ? AND status IN ('pending', 'running')`
	// No requireOneRow: the job might already be terminal (0 rows affected is fine).
	_, err := s.db.ExecContext(ctx, q, now, id)
	if err != nil {
		return fmt.Errorf("refresh build job status: %w", err)
	}
	return nil
}
