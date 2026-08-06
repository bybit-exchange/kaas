// Package sqlite is the pure-Go (modernc.org/sqlite, no CGO) implementation of
// store.Store. It backs the compile task queue with a single SQLite file.
package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"strings"

	"github.com/bybit-exchange/kaas/internal/store"
	sqlitedrv "modernc.org/sqlite"
	sqlitelib "modernc.org/sqlite/lib"
)

// Store is a SQLite-backed store.Store.
type Store struct {
	db *sql.DB
}

// taskColumns is the canonical column order for SELECT/RETURNING + scanTask.
const taskColumns = `id, source, title, raw_path, file_title, content_hash, status, stage,
	attempts, max_attempts, error, result, lease_owner, lease_expires_at,
	created_at, updated_at`

// Open opens (creating if needed) a SQLite database at path with WAL mode and a
// busy timeout so concurrent claims retry instead of failing with SQLITE_BUSY.
func Open(path string) (*Store, error) {
	dsn := buildDSN(path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite %q: %w", path, err)
	}
	// Serialize all access through a single connection. For an embedded SQLite
	// task queue this is the standard pattern: contention blocks in-process
	// instead of surfacing SQLITE_BUSY as a non-retryable error, and it keeps a
	// shared-cache :memory: database alive for the handle's lifetime. Throughput
	// for a single-user KaaS instance is nowhere near where this matters.
	db.SetMaxOpenConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping sqlite %q: %w", path, err)
	}
	return &Store{db: db}, nil
}

func buildDSN(path string) string {
	// In-memory databases need a shared cache to survive across connections.
	if path == ":memory:" {
		return "file::memory:?cache=shared&_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
	}
	q := url.Values{}
	q.Add("_pragma", "busy_timeout(5000)")
	q.Add("_pragma", "journal_mode(WAL)")
	q.Add("_pragma", "foreign_keys(ON)")
	return "file:" + path + "?" + q.Encode()
}

// Close releases the database handle.
func (s *Store) Close() error { return s.db.Close() }

const schema = `
CREATE TABLE IF NOT EXISTS tasks (
	id               TEXT PRIMARY KEY,
	source           TEXT NOT NULL,
	title            TEXT NOT NULL DEFAULT '',
	raw_path         TEXT NOT NULL DEFAULT '',
	file_title       TEXT NOT NULL DEFAULT '',
	content_hash     TEXT NOT NULL,
	status           TEXT NOT NULL,
	stage            TEXT NOT NULL,
	attempts         INTEGER NOT NULL DEFAULT 0,
	max_attempts     INTEGER NOT NULL DEFAULT 1,
	error            TEXT NOT NULL DEFAULT '',
	result           TEXT NOT NULL DEFAULT '',
	lease_owner      TEXT NOT NULL DEFAULT '',
	lease_expires_at INTEGER NOT NULL DEFAULT 0,
	created_at       INTEGER NOT NULL,
	updated_at       INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_content_hash ON tasks(content_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at);
`

// Migrate creates the schema if absent.
func (s *Store) Migrate(ctx context.Context) error {
	if _, err := s.db.ExecContext(ctx, schema); err != nil {
		return fmt.Errorf("migrate: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, sessionSchema); err != nil {
		return fmt.Errorf("migrate session schema: %w", err)
	}
	if err := s.migrateSessionSchema(ctx); err != nil {
		return err
	}
	if err := s.migrateFileTitle(ctx); err != nil {
		return err
	}
	if _, err := s.db.ExecContext(ctx, derivedSchema); err != nil {
		return fmt.Errorf("migrate derived schema: %w", err)
	}
	return nil
}

// migrateFileTitle idempotently adds the file_title column to existing databases
// that were created before this column was part of the schema.
func (s *Store) migrateFileTitle(ctx context.Context) error {
	rows, err := s.db.QueryContext(ctx, `PRAGMA table_info(tasks)`)
	if err != nil {
		return fmt.Errorf("migrate file_title: pragma: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull int
		var dflt sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			return fmt.Errorf("migrate file_title: scan pragma: %w", err)
		}
		if name == "file_title" {
			return nil // column already exists
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("migrate file_title: rows: %w", err)
	}

	_, err = s.db.ExecContext(ctx, `ALTER TABLE tasks ADD COLUMN file_title TEXT NOT NULL DEFAULT ''`)
	if err != nil {
		return fmt.Errorf("migrate file_title: alter: %w", err)
	}
	return nil
}

// CreateTask inserts a task, mapping the unique-index violation to ErrDuplicate.
func (s *Store) CreateTask(ctx context.Context, t *store.Task) error {
	const q = `INSERT INTO tasks (` + taskColumns + `)
		VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
	_, err := s.db.ExecContext(ctx, q,
		t.ID, t.Source, t.Title, t.RawPath, t.FileTitle, t.ContentHash, t.Status, t.Stage,
		t.Attempts, t.MaxAttempts, t.Error, t.Result, t.LeaseOwner,
		t.LeaseExpiresAt, t.CreatedAt, t.UpdatedAt,
	)
	if err != nil {
		if isUniqueViolation(err) {
			return store.ErrDuplicate
		}
		return fmt.Errorf("create task: %w", err)
	}
	return nil
}

// GetTask returns the task by id or store.ErrNotFound.
func (s *Store) GetTask(ctx context.Context, id string) (*store.Task, error) {
	const q = `SELECT ` + taskColumns + ` FROM tasks WHERE id = ?`
	t, err := scanTask(s.db.QueryRowContext(ctx, q, id))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, store.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get task: %w", err)
	}
	return t, nil
}

// ListTasks returns tasks matching the filter, newest first.
func (s *Store) ListTasks(ctx context.Context, f store.ListFilter) ([]*store.Task, error) {
	var b strings.Builder
	b.WriteString(`SELECT ` + taskColumns + ` FROM tasks`)
	var args []any
	if f.Status != "" {
		b.WriteString(` WHERE status = ?`)
		args = append(args, f.Status)
	}
	b.WriteString(` ORDER BY created_at DESC, id DESC`)
	if f.Limit > 0 {
		b.WriteString(` LIMIT ?`)
		args = append(args, f.Limit)
		if f.Offset > 0 {
			b.WriteString(` OFFSET ?`)
			args = append(args, f.Offset)
		}
	}
	rows, err := s.db.QueryContext(ctx, b.String(), args...)
	if err != nil {
		return nil, fmt.Errorf("list tasks: %w", err)
	}
	defer rows.Close()

	var out []*store.Task
	for rows.Next() {
		t, err := scanTask(rows)
		if err != nil {
			return nil, fmt.Errorf("list tasks scan: %w", err)
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// ListTasksPaged returns a page of tasks with total count, supporting LIKE search
// on title and file_title fields.
func (s *Store) ListTasksPaged(ctx context.Context, f store.PagedListFilter) (*store.ListResult, error) {
	var where []string
	var args []any

	if f.Status != "" {
		where = append(where, `status = ?`)
		args = append(args, f.Status)
	}
	if f.Query != "" {
		pattern := "%" + f.Query + "%"
		where = append(where, `(title LIKE ? OR file_title LIKE ?)`)
		args = append(args, pattern, pattern)
	}

	var whereClause string
	if len(where) > 0 {
		whereClause = ` WHERE ` + strings.Join(where, ` AND `)
	}

	// Count total matching rows.
	countQ := `SELECT COUNT(*) FROM tasks` + whereClause
	var total int
	if err := s.db.QueryRowContext(ctx, countQ, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("list tasks paged count: %w", err)
	}

	// Determine sort column and direction.
	allowedSort := map[string]string{
		"title":      "title",
		"file_title": "file_title",
		"source":     "source",
		"status":     "status",
		"stage":      "stage",
		"attempts":   "attempts",
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
	selectQ := `SELECT ` + taskColumns + ` FROM tasks` + whereClause + ` ORDER BY ` + sortCol + ` ` + sortDir + `, id DESC`
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
		return nil, fmt.Errorf("list tasks paged: %w", err)
	}
	defer rows.Close()

	var tasks []*store.Task
	for rows.Next() {
		t, err := scanTask(rows)
		if err != nil {
			return nil, fmt.Errorf("list tasks paged scan: %w", err)
		}
		tasks = append(tasks, t)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("list tasks paged rows: %w", err)
	}
	return &store.ListResult{Tasks: tasks, Total: total}, nil
}

// DeleteTask removes a task that is in a terminal status (succeeded/failed/cancelled).
// Returns ErrNotFound if the task does not exist or is not terminal.
func (s *Store) DeleteTask(ctx context.Context, id string) error {
	const q = `DELETE FROM tasks WHERE id = ? AND status IN ('succeeded', 'failed', 'cancelled')`
	res, err := s.db.ExecContext(ctx, q, id)
	if err != nil {
		return fmt.Errorf("delete task: %w", err)
	}
	return requireOneRow(res, "delete task")
}

// ClaimNext atomically claims the oldest pending task for owner.
//
// The single UPDATE...RETURNING with a LIMIT-1 subquery is atomic under
// SQLite's write lock, so two concurrent claimers can never take the same row.
func (s *Store) ClaimNext(ctx context.Context, owner string, now, leaseExpiresAt int64) (*store.Task, error) {
	const q = `
		UPDATE tasks
		SET status = ?, stage = ?, lease_owner = ?, lease_expires_at = ?,
		    attempts = attempts + 1, updated_at = ?
		WHERE id = (
			SELECT id FROM tasks
			WHERE status = ?
			ORDER BY created_at ASC, id ASC
			LIMIT 1
		)
		RETURNING ` + taskColumns
	t, err := scanTask(s.db.QueryRowContext(ctx, q,
		store.StatusRunning, store.StageExtract, owner, leaseExpiresAt, now,
		store.StatusPending,
	))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil // nothing to claim
	}
	if err != nil {
		return nil, fmt.Errorf("claim next: %w", err)
	}
	return t, nil
}

// Heartbeat extends the lease only while owner still holds a running task.
func (s *Store) Heartbeat(ctx context.Context, id, owner string, leaseExpiresAt int64) error {
	const q = `UPDATE tasks SET lease_expires_at = ?, updated_at = ?
		WHERE id = ? AND status = ? AND lease_owner = ?`
	res, err := s.db.ExecContext(ctx, q, leaseExpiresAt, leaseExpiresAt, id, store.StatusRunning, owner)
	if err != nil {
		return fmt.Errorf("heartbeat: %w", err)
	}
	return requireOneRow(res, "heartbeat")
}

// SetStage updates the progress stage of a running task still held by owner.
func (s *Store) SetStage(ctx context.Context, id, owner, stage string, now int64) error {
	const q = `UPDATE tasks SET stage = ?, updated_at = ?
		WHERE id = ? AND status = ? AND lease_owner = ?`
	res, err := s.db.ExecContext(ctx, q, stage, now, id, store.StatusRunning, owner)
	if err != nil {
		return fmt.Errorf("set stage: %w", err)
	}
	return requireOneRow(res, "set stage")
}

// MarkSucceeded transitions a running task to succeeded and clears its lease.
func (s *Store) MarkSucceeded(ctx context.Context, id, result string, now int64) error {
	const q = `UPDATE tasks
		SET status = ?, stage = ?, result = ?, error = '',
		    lease_owner = '', lease_expires_at = 0, updated_at = ?
		WHERE id = ? AND status = ?`
	res, err := s.db.ExecContext(ctx, q, store.StatusSucceeded, store.StageDone, result, now, id, store.StatusRunning)
	if err != nil {
		return fmt.Errorf("mark succeeded: %w", err)
	}
	return requireOneRow(res, "mark succeeded")
}

// MarkFailed re-queues (retry) or fails a running task, clearing its lease.
func (s *Store) MarkFailed(ctx context.Context, id, errMsg string, retry bool, now int64) error {
	status := store.StatusFailed
	stage := store.StageDone
	if retry {
		status = store.StatusPending
		stage = store.StageQueued
	}
	const q = `UPDATE tasks
		SET status = ?, stage = ?, error = ?,
		    lease_owner = '', lease_expires_at = 0, updated_at = ?
		WHERE id = ? AND status = ?`
	res, err := s.db.ExecContext(ctx, q, status, stage, errMsg, now, id, store.StatusRunning)
	if err != nil {
		return fmt.Errorf("mark failed: %w", err)
	}
	return requireOneRow(res, "mark failed")
}

// RecoverExpired returns running tasks with an elapsed lease to pending.
func (s *Store) RecoverExpired(ctx context.Context, now int64) (int, error) {
	const q = `UPDATE tasks
		SET status = ?, stage = ?, lease_owner = '', lease_expires_at = 0, updated_at = ?
		WHERE status = ? AND lease_expires_at > 0 AND lease_expires_at <= ?`
	res, err := s.db.ExecContext(ctx, q, store.StatusPending, store.StageQueued, now, store.StatusRunning, now)
	if err != nil {
		return 0, fmt.Errorf("recover expired: %w", err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("recover expired rows: %w", err)
	}
	return int(n), nil
}

// BackfillFileTitles finds tasks with empty file_title but non-empty raw_path,
// calls readTitle for each to derive the title, and updates the row. It returns
// the number of rows actually updated.
func (s *Store) BackfillFileTitles(ctx context.Context, readTitle func(rawPath string) string) (int, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id, raw_path FROM tasks WHERE file_title = '' AND raw_path != ''`)
	if err != nil {
		return 0, fmt.Errorf("backfill query: %w", err)
	}
	defer rows.Close()
	type row struct{ id, rawPath string }
	var pending []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.id, &r.rawPath); err != nil {
			return 0, err
		}
		pending = append(pending, r)
	}
	if err := rows.Err(); err != nil {
		return 0, err
	}
	var count int
	for _, r := range pending {
		title := readTitle(r.rawPath)
		if title == "" {
			continue
		}
		_, err := s.db.ExecContext(ctx, `UPDATE tasks SET file_title = ? WHERE id = ?`, title, r.id)
		if err != nil {
			return count, fmt.Errorf("backfill update %s: %w", r.id, err)
		}
		count++
	}
	return count, nil
}

// --- helpers ---

type rowScanner interface{ Scan(dest ...any) error }

func scanTask(row rowScanner) (*store.Task, error) {
	var t store.Task
	err := row.Scan(
		&t.ID, &t.Source, &t.Title, &t.RawPath, &t.FileTitle, &t.ContentHash, &t.Status, &t.Stage,
		&t.Attempts, &t.MaxAttempts, &t.Error, &t.Result, &t.LeaseOwner,
		&t.LeaseExpiresAt, &t.CreatedAt, &t.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

// requireOneRow maps a no-op UPDATE (wrong id/owner/status) to ErrNotFound.
func requireOneRow(res sql.Result, op string) error {
	n, err := res.RowsAffected()
	if err != nil {
		return fmt.Errorf("%s rows: %w", op, err)
	}
	if n == 0 {
		return store.ErrNotFound
	}
	return nil
}

func isUniqueViolation(err error) bool {
	// Prefer the typed extended result code modernc.org/sqlite exposes.
	var se *sqlitedrv.Error
	if errors.As(err, &se) {
		switch se.Code() {
		case sqlitelib.SQLITE_CONSTRAINT_UNIQUE, sqlitelib.SQLITE_CONSTRAINT_PRIMARYKEY:
			return true
		}
	}
	// Fallback in case the driver ever changes how it wraps the error.
	msg := err.Error()
	return strings.Contains(msg, "UNIQUE constraint failed") ||
		strings.Contains(msg, "constraint failed: UNIQUE")
}
