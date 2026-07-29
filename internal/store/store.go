// Package store defines the persistence interface for KaaS backend state —
// chiefly the compile task queue — plus the entities it operates on.
//
// The interface exposes atomic queue primitives (ClaimNext, Heartbeat,
// MarkSucceeded/Failed, RecoverExpired) that the queue package composes into a
// lease-based queue. Concrete backends live in sub-packages (sqlite; mysql is a
// future stub). All timestamps are unix-milliseconds so the clock can be
// injected in tests.
package store

import (
	"context"
	"errors"
)

// Sentinel errors returned by Store implementations.
var (
	// ErrNotFound is returned when a task id does not exist.
	ErrNotFound = errors.New("store: task not found")
	// ErrDuplicate is returned when CreateTask hits the content_hash unique index.
	ErrDuplicate = errors.New("store: duplicate content_hash")
)

// Task status values.
const (
	StatusPending   = "pending"
	StatusRunning   = "running"
	StatusSucceeded = "succeeded"
	StatusFailed    = "failed"
	StatusCancelled = "cancelled"
)

// Task stage values (progress reported on the Status page).
const (
	StageQueued   = "queued"
	StageExtract  = "extract"
	StagePipeline = "pipeline"
	StageIndex    = "index"
	StageDone     = "done"
)

// Task is one unit of compile work: a piece of raw content to be run through
// the Extract → Classify → Write → Index pipeline.
type Task struct {
	ID          string // UUID
	Source      string // "paste" | "file" | "url"
	Title       string // optional, human label
	RawPath     string // path to the raw content file under <kb_dir>/raw
	FileTitle   string // original filename (without extension) for file-source tasks
	ContentHash string // sha256 of the raw content; unique (dedup / incremental)
	Status      string // see Status* constants
	Stage       string // see Stage* constants
	Attempts    int    // number of times this task has been claimed and failed
	MaxAttempts int    // retry ceiling
	Error       string // last failure message
	Result      string // JSON blob: cost, article counts, etc.
	LeaseOwner  string // worker id currently holding the lease ("" if none)
	// LeaseExpiresAt is a unix-ms deadline; 0 means no active lease.
	LeaseExpiresAt int64
	CreatedAt      int64 // unix ms
	UpdatedAt      int64 // unix ms
}

// ListFilter narrows ListTasks results. Zero value lists everything (newest first).
type ListFilter struct {
	Status string // optional exact status match
	Limit  int    // 0 = no limit
	Offset int
}

// PagedListFilter narrows ListTasksPaged results with LIKE search and pagination.
type PagedListFilter struct {
	Status  string // optional exact status match
	Query   string // matches title OR file_title via LIKE %q%
	SortBy  string // column to sort by (empty = created_at)
	SortDir string // "asc" or "desc" (empty = desc)
	Limit   int
	Offset  int
}

// ListResult holds a page of tasks plus the total count matching the filter.
type ListResult struct {
	Tasks []*Task
	Total int
}

// Store persists tasks and provides atomic queue primitives.
//
// The queue primitives must be safe under concurrent callers: ClaimNext on two
// goroutines must never hand out the same task.
type Store interface {
	// Migrate creates tables and indexes if absent. Idempotent.
	Migrate(ctx context.Context) error

	// CreateTask inserts a new task. Returns ErrDuplicate on content_hash clash.
	CreateTask(ctx context.Context, t *Task) error
	// GetTask returns the task by id, or ErrNotFound.
	GetTask(ctx context.Context, id string) (*Task, error)
	// ListTasks returns tasks matching the filter, newest first.
	ListTasks(ctx context.Context, f ListFilter) ([]*Task, error)
	// ListTasksPaged returns a page of tasks with total count, supporting LIKE search.
	ListTasksPaged(ctx context.Context, f PagedListFilter) (*ListResult, error)
	// DeleteTask removes a terminal task (succeeded/failed/cancelled). Returns
	// ErrNotFound if the task does not exist or is not in a terminal status.
	DeleteTask(ctx context.Context, id string) error

	// ClaimNext atomically picks the oldest pending task, marks it running, and
	// assigns it to owner with the given lease deadline. Returns (nil, nil) when
	// there is nothing to claim.
	ClaimNext(ctx context.Context, owner string, now, leaseExpiresAt int64) (*Task, error)
	// Heartbeat extends the lease of a task the owner still holds. Returns
	// ErrNotFound if the task is gone or no longer owned by owner.
	Heartbeat(ctx context.Context, id, owner string, leaseExpiresAt int64) error
	// SetStage updates a task's progress stage. It is owner-scoped: it only
	// updates a running task still held by owner, returning ErrNotFound
	// otherwise (the caller has lost its lease and should abandon the task).
	SetStage(ctx context.Context, id, owner, stage string, now int64) error
	// MarkSucceeded transitions a running task to succeeded and clears its lease.
	// Returns ErrNotFound if the task is no longer running (e.g. its lease was
	// recovered and re-claimed by another worker) — the caller has lost its lease.
	MarkSucceeded(ctx context.Context, id, result string, now int64) error
	// MarkFailed records an error and either re-queues the task (retry=true,
	// status back to pending) or marks it failed. Clears the lease either way.
	// Returns ErrNotFound if the task is no longer running (lease lost), same as
	// MarkSucceeded.
	MarkFailed(ctx context.Context, id, errMsg string, retry bool, now int64) error
	// RecoverExpired returns running tasks whose lease deadline is <= now to
	// pending so another worker can claim them. Returns the count recovered.
	RecoverExpired(ctx context.Context, now int64) (int, error)

	// Close releases the underlying handle.
	Close() error
}
