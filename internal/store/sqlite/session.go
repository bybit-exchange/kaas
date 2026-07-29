package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"

	"github.com/bybit-exchange/kaas/internal/store"
)

const sessionSchema = `
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON chat_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    sources    TEXT NOT NULL DEFAULT '[]',
    usage      TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at ASC);
`

// migrateSessionSchema applies incremental migrations that ALTER TABLE cannot
// express in CREATE TABLE IF NOT EXISTS. Each migration is idempotent.
func (s *Store) migrateSessionSchema(ctx context.Context) error {
	// Add reasoning column (idempotent: ignore "duplicate column name" error).
	_, err := s.db.ExecContext(ctx,
		`ALTER TABLE chat_messages ADD COLUMN reasoning TEXT NOT NULL DEFAULT ''`)
	if err != nil && !strings.Contains(err.Error(), "duplicate column") {
		return fmt.Errorf("migrate chat_messages add reasoning: %w", err)
	}
	return nil
}

// CreateSession inserts a new chat session.
func (s *Store) CreateSession(ctx context.Context, sess *store.Session) error {
	const q = `INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)`
	_, err := s.db.ExecContext(ctx, q, sess.ID, sess.Title, sess.CreatedAt, sess.UpdatedAt)
	if err != nil {
		return fmt.Errorf("create session: %w", err)
	}
	return nil
}

// ListSessions returns all sessions ordered by updated_at DESC.
func (s *Store) ListSessions(ctx context.Context) ([]*store.Session, error) {
	const q = `SELECT id, title, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC`
	rows, err := s.db.QueryContext(ctx, q)
	if err != nil {
		return nil, fmt.Errorf("list sessions: %w", err)
	}
	defer rows.Close()

	var out []*store.Session
	for rows.Next() {
		var sess store.Session
		if err := rows.Scan(&sess.ID, &sess.Title, &sess.CreatedAt, &sess.UpdatedAt); err != nil {
			return nil, fmt.Errorf("list sessions scan: %w", err)
		}
		out = append(out, &sess)
	}
	return out, rows.Err()
}

// GetSession returns a session by id, or store.ErrNotFound.
func (s *Store) GetSession(ctx context.Context, id string) (*store.Session, error) {
	const q = `SELECT id, title, created_at, updated_at FROM chat_sessions WHERE id = ?`
	var sess store.Session
	err := s.db.QueryRowContext(ctx, q, id).Scan(&sess.ID, &sess.Title, &sess.CreatedAt, &sess.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, store.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("get session: %w", err)
	}
	return &sess, nil
}

// UpdateSessionTitle renames a session, updating updated_at.
func (s *Store) UpdateSessionTitle(ctx context.Context, id, title string, now int64) error {
	const q = `UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?`
	res, err := s.db.ExecContext(ctx, q, title, now, id)
	if err != nil {
		return fmt.Errorf("update session title: %w", err)
	}
	return requireOneRow(res, "update session title")
}

// DeleteSession deletes a session. Messages are cascade-deleted by the DB.
func (s *Store) DeleteSession(ctx context.Context, id string) error {
	const q = `DELETE FROM chat_sessions WHERE id = ?`
	res, err := s.db.ExecContext(ctx, q, id)
	if err != nil {
		return fmt.Errorf("delete session: %w", err)
	}
	return requireOneRow(res, "delete session")
}

// CreateMessage inserts a new message into a session.
func (s *Store) CreateMessage(ctx context.Context, m *store.Message) error {
	const q = `INSERT INTO chat_messages (id, session_id, role, content, reasoning, sources, usage, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
	_, err := s.db.ExecContext(ctx, q, m.ID, m.SessionID, m.Role, m.Content, m.Reasoning, m.Sources, m.Usage, m.CreatedAt)
	if err != nil {
		return fmt.Errorf("create message: %w", err)
	}
	return nil
}

// ListMessages returns all messages for a session, ordered by created_at ASC.
func (s *Store) ListMessages(ctx context.Context, sessionID string) ([]*store.Message, error) {
	const q = `SELECT id, session_id, role, content, reasoning, sources, usage, created_at
		FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC`
	rows, err := s.db.QueryContext(ctx, q, sessionID)
	if err != nil {
		return nil, fmt.Errorf("list messages: %w", err)
	}
	defer rows.Close()

	var out []*store.Message
	for rows.Next() {
		var m store.Message
		if err := rows.Scan(&m.ID, &m.SessionID, &m.Role, &m.Content, &m.Reasoning, &m.Sources, &m.Usage, &m.CreatedAt); err != nil {
			return nil, fmt.Errorf("list messages scan: %w", err)
		}
		out = append(out, &m)
	}
	return out, rows.Err()
}

// TouchSession updates a session's updated_at timestamp.
func (s *Store) TouchSession(ctx context.Context, id string, now int64) error {
	const q = `UPDATE chat_sessions SET updated_at = ? WHERE id = ?`
	res, err := s.db.ExecContext(ctx, q, now, id)
	if err != nil {
		return fmt.Errorf("touch session: %w", err)
	}
	return requireOneRow(res, "touch session")
}
