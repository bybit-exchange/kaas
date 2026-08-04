package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/bybit-exchange/kaas/internal/bridge"
	"github.com/bybit-exchange/kaas/internal/kbpath"
)

// askArguments mirrors the ask tool's input parameters.
type askArguments struct {
	Query string   `json:"query"`
	Paths []string `json:"paths"`
	Model string   `json:"model"`
	KB    string   `json:"kb"`
}

func (h *Handler) handleAsk(w http.ResponseWriter, r *http.Request, req *JSONRPCRequest, arguments json.RawMessage) {
	var args askArguments
	if err := json.Unmarshal(arguments, &args); err != nil {
		writeJSONRPCError(w, req.ID, -32602, "Invalid arguments: "+err.Error())
		return
	}
	if args.Query == "" {
		writeJSONRPCError(w, req.ID, -32602, "Missing required argument: query")
		return
	}

	// kb reaches us from an MCP client, so it is untrusted input to a path join.
	kbDir, err := kbpath.Resolve(h.kbDir, args.KB)
	if err != nil {
		writeJSONRPCError(w, req.ID, -32602, "Invalid arguments: "+err.Error())
		return
	}

	// Create context with timeout for the chat call
	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	// Build ChatRequest (ask is one-shot Q&A: no Messages, no Temperature)
	includeSourcesTrue := true
	chatReq := bridge.ChatRequest{
		Query:          args.Query,
		KBDir:          kbDir,
		Paths:          args.Paths,
		Model:          args.Model,
		IncludeSources: &includeSourcesTrue,
	}
	// Use the handler's default model if the tool call didn't specify one
	if chatReq.Model == "" {
		chatReq.Model = h.model
	}

	// Collect streaming events
	var answerParts []string
	var sources []map[string]string
	var costUSD float64
	var chatErr string

	err = h.chat(ctx, chatReq, func(event json.RawMessage) error {
		var ev struct {
			Type             string              `json:"type"`
			Content          string              `json:"content"`
			CitedSources     []map[string]string `json:"cited_sources"`
			RetrievedSources []map[string]string `json:"retrieved_sources"`
			CostUSD          float64             `json:"cost_usd"`
			Code             string              `json:"code"`
			Message          string              `json:"message"`
		}
		if err := json.Unmarshal(event, &ev); err != nil {
			return nil // skip unparseable events
		}
		switch ev.Type {
		case "delta":
			answerParts = append(answerParts, ev.Content)
		case "done":
			sources = ev.CitedSources
			if len(sources) == 0 {
				sources = ev.RetrievedSources
			}
			costUSD = ev.CostUSD
		case "error":
			// kb_ai error events carry {code, message}; the daemon's CANCELLED
			// event carries only code. Never leave chatErr empty on an error
			// event, or the caller silently returns an empty answer as success.
			switch {
			case ev.Message != "":
				chatErr = ev.Message
			case ev.Code != "":
				chatErr = ev.Code
			default:
				chatErr = "chat failed"
			}
		}
		return nil
	})

	// Handle timeout
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			writeJSONRPCError(w, req.ID, -32603, "tool call timeout")
			return
		}
		// Other errors (daemon not ready, etc.)
		writeJSONRPCError(w, req.ID, -32603, "Internal error: "+err.Error())
		return
	}

	// Handle chat-level error event
	if chatErr != "" {
		toolResult := ToolResult{
			Content: []ContentBlock{{Type: "text", Text: chatErr}},
			IsError: true,
		}
		writeJSONRPCResult(w, req.ID, toolResult)
		return
	}

	// Assemble result
	answer := strings.Join(answerParts, "")
	result := map[string]any{
		"answer":   withSourcesFooter(answer, sources),
		"sources":  sources,
		"cost_usd": costUSD,
	}

	resultJSON, _ := json.Marshal(result)
	toolResult := ToolResult{
		Content: []ContentBlock{{Type: "text", Text: string(resultJSON)}},
	}
	writeJSONRPCResult(w, req.ID, toolResult)
}

// withSourcesFooter appends a Sources: markdown list when sources are present.
func withSourcesFooter(answer string, sources []map[string]string) string {
	if len(sources) == 0 {
		return answer
	}
	var lines []string
	for _, s := range sources {
		title := s["title"]
		path := s["path"]
		lines = append(lines, fmt.Sprintf("- [%s](%s)", title, path))
	}
	return answer + "\n\nSources:\n" + strings.Join(lines, "\n")
}
