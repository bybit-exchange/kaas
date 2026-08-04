package mcp

import (
	"encoding/json"
	"testing"
)

func TestAskToolDefinition_MarshalJSON(t *testing.T) {
	data, err := json.Marshal(askToolDefinition)
	if err != nil {
		t.Fatalf("json.Marshal(askToolDefinition): %v", err)
	}

	var got map[string]json.RawMessage
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("unmarshal tool: %v", err)
	}

	// Check top-level fields exist.
	for _, key := range []string{"name", "description", "inputSchema"} {
		if _, ok := got[key]; !ok {
			t.Errorf("missing top-level key %q", key)
		}
	}

	// Verify name.
	var name string
	if err := json.Unmarshal(got["name"], &name); err != nil {
		t.Fatalf("unmarshal name: %v", err)
	}
	if name != "ask" {
		t.Errorf("name = %q, want %q", name, "ask")
	}
}

func TestAskInputSchema_Structure(t *testing.T) {
	var schema struct {
		Type       string                     `json:"type"`
		Properties map[string]json.RawMessage `json:"properties"`
		Required   []string                   `json:"required"`
	}
	if err := json.Unmarshal(askInputSchema, &schema); err != nil {
		t.Fatalf("unmarshal inputSchema: %v", err)
	}

	if schema.Type != "object" {
		t.Errorf("type = %q, want %q", schema.Type, "object")
	}

	// Verify all 3 properties exist.
	for _, prop := range []string{"query", "paths", "model"} {
		if _, ok := schema.Properties[prop]; !ok {
			t.Errorf("missing property %q", prop)
		}
	}

	// Verify required contains only "query".
	if len(schema.Required) != 1 || schema.Required[0] != "query" {
		t.Errorf("required = %v, want [\"query\"]", schema.Required)
	}
}

func TestAskInputSchemaHasKB(t *testing.T) {
	var schema struct {
		Properties map[string]struct {
			Type        string `json:"type"`
			Description string `json:"description"`
		} `json:"properties"`
		Required []string `json:"required"`
	}
	if err := json.Unmarshal(askInputSchema, &schema); err != nil {
		t.Fatalf("unmarshal askInputSchema: %v", err)
	}
	kb, ok := schema.Properties["kb"]
	if !ok {
		t.Fatal("askInputSchema has no kb property")
	}
	if kb.Type != "string" {
		t.Errorf("kb type = %q, want string", kb.Type)
	}
	if kb.Description == "" {
		t.Error("kb property has no description")
	}
	for _, r := range schema.Required {
		if r == "kb" {
			t.Error("kb must not be required")
		}
	}
}
