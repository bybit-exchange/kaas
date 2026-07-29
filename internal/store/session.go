package store

// Session represents a chat session (conversation thread).
type Session struct {
	ID        string // UUID
	Title     string
	CreatedAt int64 // unix ms
	UpdatedAt int64 // unix ms
}

// Message represents a single chat message within a session.
type Message struct {
	ID        string // UUID
	SessionID string
	Role      string // "user" | "assistant"
	Content   string
	Reasoning string // accumulated reasoning text (assistant only)
	Sources   string // JSON string
	Usage     string // JSON string
	CreatedAt int64  // unix ms
}
