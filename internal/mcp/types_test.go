package mcp

import (
	"encoding/json"
	"testing"
)

func TestJSONRPCRequest_IsNotification(t *testing.T) {
	tests := []struct {
		name string
		id   json.RawMessage
		want bool
	}{
		{
			name: "nil ID (omitted) is notification",
			id:   nil,
			want: true,
		},
		{
			name: "empty ID is notification",
			id:   json.RawMessage{},
			want: true,
		},
		{
			name: "JSON null is notification",
			id:   json.RawMessage("null"),
			want: true,
		},
		{
			name: "numeric ID is not notification",
			id:   json.RawMessage("1"),
			want: false,
		},
		{
			name: "string ID is not notification",
			id:   json.RawMessage(`"abc"`),
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := &JSONRPCRequest{ID: tt.id}
			if got := r.IsNotification(); got != tt.want {
				t.Errorf("IsNotification() = %v, want %v", got, tt.want)
			}
		})
	}
}
