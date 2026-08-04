package bridge

import (
	"encoding/json"
	"fmt"
)

// APIError is a structured error returned by the AI engine ({"ok":false,...}).
type APIError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (e *APIError) Error() string {
	return fmt.Sprintf("bridge: AI engine error %s: %s", e.Code, e.Message)
}

// EventType peeks the "type" field of an SSE event payload (e.g. "delta",
// "done", "error"). Returns "" if absent or unparseable.
func EventType(raw json.RawMessage) string {
	var e struct {
		Type string `json:"type"`
	}
	_ = json.Unmarshal(raw, &e)
	return e.Type
}

// --- Extract ---

// ExtractRequest mirrors the extract command. Strategy is "chunked" (default),
// "summarize", or "auto".
type ExtractRequest struct {
	Content        string `json:"content"`
	Model          string `json:"model,omitempty"`
	Strategy       string `json:"strategy,omitempty"`
	SummarizeModel string `json:"summarize_model,omitempty"`
}

// ExtractResponse holds the opaque extraction plus a cost summary. Extraction
// is passed verbatim into PipelineItem.Extraction.
type ExtractResponse struct {
	Extraction json.RawMessage `json:"extraction"`
	Cost       json.RawMessage `json:"cost"`
}

// --- Pipeline (Classify → Write) ---

// PipelineItem is one extracted unit fed into the classify/write pipeline.
type PipelineItem struct {
	Extraction  json.RawMessage `json:"extraction"`
	ContentHash string          `json:"content_hash,omitempty"`
	SourceRef   string          `json:"source_ref,omitempty"`
}

// PipelineRequest mirrors the pipeline command.
type PipelineRequest struct {
	KBDir                 string          `json:"kb_dir"`
	Items                 []PipelineItem  `json:"items"`
	Model                 string          `json:"model,omitempty"`
	ClassifyModel         string          `json:"classify_model,omitempty"`
	Categories            []string        `json:"categories,omitempty"`
	Workers               int             `json:"workers,omitempty"`
	TopicIndexMinArticles int             `json:"topic_index_min_articles,omitempty"`
	DeadlineSeconds       int             `json:"deadline_seconds,omitempty"`
	People                json.RawMessage `json:"people,omitempty"`
}

// PipelineResponse holds the per-article results plus a cost summary.
type PipelineResponse struct {
	Results json.RawMessage `json:"results"`
	Cost    json.RawMessage `json:"cost"`
}

// --- Index ---

// IndexRequest mirrors the index command (rebuilds the markdown indexes).
type IndexRequest struct {
	KBDir                 string          `json:"kb_dir"`
	TopicIndexMinArticles int             `json:"topic_index_min_articles,omitempty"`
	People                json.RawMessage `json:"people,omitempty"`
}

// --- Chat (SSE) ---

// ChatMessage is one turn of conversation history.
type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequest mirrors the chat command.
type ChatRequest struct {
	Query    string        `json:"query"`
	KBDir    string        `json:"kb_dir"`
	Paths    []string      `json:"paths,omitempty"`
	Messages []ChatMessage `json:"messages,omitempty"`
	Model    string        `json:"model,omitempty"`
	// Temperature is a pointer so an explicit 0 (deterministic output) is sent
	// rather than dropped by omitempty; nil falls back to the server default.
	Temperature *float64 `json:"temperature,omitempty"`
	// IncludeSources defaults to true server-side; set explicitly to disable.
	IncludeSources *bool `json:"include_sources,omitempty"`
}

// --- Misc one-shot endpoints ---

// FetchURLResponse is the readable content extracted from a URL.
type FetchURLResponse struct {
	Title   string `json:"title"`
	Content string `json:"content"`
	Date    string `json:"date"`
	URL     string `json:"url"`
}

// RewriteRequest mirrors the rewrite command (query rewriting for retrieval).
type RewriteRequest struct {
	Query   string          `json:"query"`
	History json.RawMessage `json:"history,omitempty"`
	Model   string          `json:"model,omitempty"`
}

// SuggestRequest mirrors the suggest command (follow-up question suggestions).
type SuggestRequest struct {
	Query  string `json:"query"`
	Answer string `json:"answer"`
	Model  string `json:"model,omitempty"`
}

// --- Derive (topic-scoped knowledge base) ---

// DeriveRequest mirrors the derive command. Non-streaming: progress granularity
// per derive stage is carried by the job row's stage column, not by a stream.
type DeriveRequest struct {
	KBDir string `json:"kb_dir"`
	Topic string `json:"topic"`
	Slug  string `json:"slug,omitempty"`
	Force bool   `json:"force,omitempty"`
	Model string `json:"model,omitempty"`
}

// DeriveResponse mirrors the derive command's success payload. Stored verbatim
// as a derive job's result, so the UI can report counts and cost.
type DeriveResponse struct {
	DerivedKB     string          `json:"derived_kb"`
	Slug          string          `json:"slug"`
	Topic         string          `json:"topic"`
	Selected      int             `json:"selected"`
	Documents     int             `json:"documents"`
	Bytes         int64           `json:"bytes"`
	Offtopic      int             `json:"offtopic"`
	FilterBatches int             `json:"filter_batches"`
	Compiled      bool            `json:"compiled"`
	Compile       json.RawMessage `json:"compile,omitempty"`
	Cost          json.RawMessage `json:"cost,omitempty"`
	Warnings      []string        `json:"warnings,omitempty"`
}
