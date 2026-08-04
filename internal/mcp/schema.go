package mcp

import "encoding/json"

// askInputSchema is the JSON Schema for the ask tool's input parameters.
var askInputSchema = json.RawMessage(`{
	"type": "object",
	"properties": {
		"query": {
			"type": "string",
			"description": "Natural-language question."
		},
		"paths": {
			"type": "array",
			"items": {"type": "string"},
			"description": "Optional wiki article paths to ground the answer in (skips master-index navigation and reads those pages in full)."
		},
		"model": {
			"type": "string",
			"description": "Optional chat model override."
		},
		"kb": {
			"type": "string",
			"description": "Optional derived knowledge-base slug (a directory under the KB's derived/). Omit to query the root knowledge base."
		}
	},
	"required": ["query"]
}`)

// askToolDefinition is the MCP tool definition returned by tools/list.
var askToolDefinition = Tool{
	Name:        "ask",
	Description: "Ask the compiled KaaS wiki a question; returns a cited answer.",
	InputSchema: askInputSchema,
}
