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
	// ErrDerivedJobExists is returned when a derive job for the same slug is
	// already pending or running. Terminal jobs do not block a re-derive.
	ErrDerivedJobExists = errors.New("store: derive job already active for slug")
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
	Attempts    int    // deliveries: ClaimNext spends one, ReleaseTask hands one back
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
	// ReleaseTask is the inverse of ClaimNext: it returns a task the owner holds
	// to pending and hands back the attempt the claim spent, recording no error.
	// Callers use it when the delivery did no work at all, so the task must not
	// be charged a retry. Owner-scoped like SetStage, returning ErrNotFound when
	// the task is gone, no longer running, or held by somebody else.
	ReleaseTask(ctx context.Context, id, owner string, now int64) error
	// RecoverExpired returns running tasks whose lease deadline is <= now to
	// pending so another worker can claim them. Returns the count recovered.
	RecoverExpired(ctx context.Context, now int64) (int, error)

	// Close releases the underlying handle.
	Close() error
}

// Derive job status values.
const (
	DerivedStatusPending   = "pending"
	DerivedStatusRunning   = "running"
	DerivedStatusSucceeded = "succeeded"
	DerivedStatusFailed    = "failed"
)

// Derive job stage values, reported on the job status endpoint. These describe
// one KB-level derive, which is why derive does not reuse Task's per-document
// Stage* values.
//
// The bridge call covers filter → copy → compile → prune in one round trip, so
// compile is the only mid-flight stage the runner can honestly report; there are
// deliberately no copy and prune constants to write.
const (
	DerivedStageQueued  = "queued"
	DerivedStageFilter  = "filter"
	DerivedStageCompile = "compile"
	DerivedStageDone    = "done"
)

// Which catalog a derive filters over. Mirrors SELECT_FROM_* in
// py/src/kb_ai/derive/_types.py; both sides must agree, or a value this side
// accepts fails the engine after the job is already queued.
//
//   - SelectFromArticles: the compiled catalog, then each selected article's
//     sources:. Better and cheaper when the source KB is compiled.
//   - SelectFromDocuments: the raw-document catalog. Reaches documents that
//     produced no article, and works on a KB that was never compiled.
const (
	SelectFromArticles  = "articles"
	SelectFromDocuments = "documents"
)

// DerivedJob is one request to build a topic-scoped knowledge base.
//
// Deliberately not a Task: Task is document-shaped (RawPath, uniquely indexed
// ContentHash) and Worker.Process runs one document through extract → pipeline,
// so re-deriving a topic would collide with ErrDuplicate and every document
// ingestion would pay for a branch it never takes.
type DerivedJob struct {
	ID    string // UUID
	Slug  string // derived/<slug>; unique among pending and running jobs
	Topic string // the topic string handed to the filter
	Model string // optional model override ("" = server default)
	// Which catalog to filter; see SelectFrom* constants. "" = engine default,
	// which is what every row written before this column existed reads back as,
	// so the default is resolved in the engine rather than materialised here.
	SelectFrom string
	Status     string // see DerivedStatus* constants
	Stage      string // see DerivedStage* constants
	Error      string // failure message, empty while healthy
	Result     string // JSON blob: counts and cost, written on success
	CreatedAt  int64  // unix ms
	UpdatedAt  int64  // unix ms
}

// DerivedJobStore persists derive jobs. Kept separate from Store so the compile
// queue's interface is unchanged; sqlite.Store implements both.
type DerivedJobStore interface {
	// CreateDerivedJob inserts a pending job. Returns ErrDerivedJobExists when a
	// pending or running job already holds that slug.
	CreateDerivedJob(ctx context.Context, j *DerivedJob) error
	// GetDerivedJob returns the job by id, or ErrNotFound.
	GetDerivedJob(ctx context.Context, id string) (*DerivedJob, error)
	// ClaimNextDerivedJob marks the oldest pending job running and returns it.
	// Returns (nil, nil) when nothing is pending OR when a job is already
	// running: a derive spends real money and rewrites a directory, so the
	// runner is single-flight by construction.
	ClaimNextDerivedJob(ctx context.Context, now int64) (*DerivedJob, error)
	// SetDerivedJobStage records progress on a running job.
	SetDerivedJobStage(ctx context.Context, id, stage string, now int64) error
	// FinishDerivedJob writes a terminal status with its error or result JSON.
	FinishDerivedJob(ctx context.Context, id, status, errMsg, result string, now int64) error
	// RecoverRunningDerivedJobs fails every job left running by a previous
	// process and returns the count. A derive is not resumable: it may have died
	// mid-compile, and the runner has no lease to pick back up.
	RecoverRunningDerivedJobs(ctx context.Context, now int64) (int, error)
}
