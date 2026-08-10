package bridge

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

// --- scripted transport ---------------------------------------------------
//
// The DaemonClient methods are thin wrappers over daemon.call / daemon.stream.
// To exercise them without spawning Python, a scriptedDaemon replaces the
// daemon's stdin with an in-memory writer: every request the client writes is
// decoded, recorded, and handed to a handler whose returned lines are fed back
// through readLoop as if the Python process had emitted them on stdout.

// scriptedDaemon is an in-memory stand-in for a running daemon process.
type scriptedDaemon struct {
	daemon *MultiplexStreamDaemon

	mu       sync.Mutex
	requests []daemonRequest

	pw      *io.PipeWriter
	handler func(daemonRequest) []string
	replies sync.WaitGroup
}

// scriptedStdin decodes each request written by the client and asks the
// scriptedDaemon to reply.
type scriptedStdin struct{ sd *scriptedDaemon }

func (s *scriptedStdin) Write(p []byte) (int, error) {
	var req daemonRequest
	if err := json.Unmarshal(bytes.TrimSpace(p), &req); err != nil {
		return 0, err
	}

	s.sd.mu.Lock()
	s.sd.requests = append(s.sd.requests, req)
	s.sd.mu.Unlock()

	lines := s.sd.handler(req)

	// Reply asynchronously: the client holds writerMu across this Write, and a
	// stream consumer may call sendCancel (which also wants writerMu) as soon as
	// it sees an event. Replying inline would deadlock.
	s.sd.replies.Add(1)
	go func() {
		defer s.sd.replies.Done()
		for _, line := range lines {
			if _, err := io.WriteString(s.sd.pw, line+"\n"); err != nil {
				return
			}
		}
	}()
	return len(p), nil
}

func (s *scriptedStdin) Close() error { return nil }

// newScriptedDaemon returns a ready daemon whose responses come from handler.
func newScriptedDaemon(t *testing.T, handler func(daemonRequest) []string) *scriptedDaemon {
	t.Helper()

	pr, pw := io.Pipe()
	sd := &scriptedDaemon{pw: pw, handler: handler}

	d := &MultiplexStreamDaemon{
		command:     "scripted",
		concurrency: 4,
		sem:         make(chan struct{}, 4),
		done:        make(chan struct{}),
	}
	d.stdin = &scriptedStdin{sd: sd}
	d.ready.Store(true)
	sd.daemon = d

	scanner := bufio.NewScanner(pr)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<20)
	loopDone := make(chan struct{})
	go func() {
		defer close(loopDone)
		d.readLoop(scanner)
	}()

	t.Cleanup(func() {
		sd.replies.Wait()
		_ = pw.Close()
		<-loopDone
		_ = pr.Close()
	})
	return sd
}

// newScriptedClient returns a DaemonClient backed by a scripted daemon. No
// supervisor goroutine is started; supervisor behaviour is covered separately.
func newScriptedClient(t *testing.T, handler func(daemonRequest) []string) (*DaemonClient, *scriptedDaemon) {
	t.Helper()

	sd := newScriptedDaemon(t, handler)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)

	c := &DaemonClient{
		daemon: sd.daemon,
		cfg:    DaemonConfig{MaxRestarts: 1, WarmupTimeoutSec: 5},
		llm: LLMConfig{
			APIKey:          "test-key",
			BaseURL:         "http://llm.local/v1",
			Model:           "test-model",
			SummarizeModel:  "test-summarize-model",
			ExtractStrategy: "summarize",
		},
		ctx:    ctx,
		cancel: cancel,
	}
	return c, sd
}

// only returns the single request the client sent, failing otherwise.
func (sd *scriptedDaemon) only(t *testing.T) daemonRequest {
	t.Helper()
	sd.mu.Lock()
	defer sd.mu.Unlock()
	if len(sd.requests) != 1 {
		t.Fatalf("expected exactly 1 request, got %d: %+v", len(sd.requests), sd.requests)
	}
	return sd.requests[0]
}

// commands returns the cmd of every request received, in order.
func (sd *scriptedDaemon) commands() []string {
	sd.mu.Lock()
	defer sd.mu.Unlock()
	out := make([]string, 0, len(sd.requests))
	for _, r := range sd.requests {
		out = append(out, r.Cmd)
	}
	return out
}

// Response line builders mirroring the daemon's stdout protocol.
func okLine(id, data string) string {
	return `{"id":"` + id + `","ok":true,"data":` + data + `}`
}

func errLine(id, code, msg string) string {
	return `{"id":"` + id + `","ok":false,"error":{"code":"` + code + `","message":"` + msg + `"}}`
}

// bareErrLine is a failure response carrying no error detail.
func bareErrLine(id string) string {
	return `{"id":"` + id + `","ok":false}`
}

func streamLine(id, event string, final bool) string {
	line := `{"id":"` + id + `","stream":true,"event":` + event
	if final {
		line += `,"final":true`
	}
	return line + `}`
}

// alwaysOK replies to every request with the given data payload.
func alwaysOK(data string) func(daemonRequest) []string {
	return func(req daemonRequest) []string { return []string{okLine(req.ID, data)} }
}

// --- one-shot commands ----------------------------------------------------

func TestDaemonClientExtract(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{"extraction":{"topics":["kaas"]},"cost":{"total_usd":0.25}}`))

	resp, err := c.Extract(context.Background(), ExtractRequest{
		Content:  "raw article text",
		Strategy: "summarize",
		Model:    "extract-model",
	})
	if err != nil {
		t.Fatalf("Extract: unexpected error: %v", err)
	}

	req := sd.only(t)
	if req.Cmd != "extract" {
		t.Errorf("expected cmd=extract, got %q", req.Cmd)
	}
	var sent ExtractRequest
	if err := json.Unmarshal(req.Payload, &sent); err != nil {
		t.Fatalf("decode sent payload: %v", err)
	}
	if sent.Content != "raw article text" || sent.Strategy != "summarize" || sent.Model != "extract-model" {
		t.Errorf("payload not forwarded verbatim: %+v", sent)
	}

	if string(resp.Extraction) != `{"topics":["kaas"]}` {
		t.Errorf("unexpected extraction: %s", resp.Extraction)
	}
	if string(resp.Cost) != `{"total_usd":0.25}` {
		t.Errorf("unexpected cost: %s", resp.Cost)
	}
}

func TestDaemonClientPipeline(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{"results":[{"path":"a.md"}],"cost":{"total_usd":1}}`))

	resp, err := c.Pipeline(context.Background(), PipelineRequest{
		KBDir:   "/kb",
		Items:   []PipelineItem{{ContentHash: "h1", SourceRef: "src-1"}},
		Workers: 3,
	})
	if err != nil {
		t.Fatalf("Pipeline: unexpected error: %v", err)
	}

	req := sd.only(t)
	if req.Cmd != "pipeline" {
		t.Errorf("expected cmd=pipeline, got %q", req.Cmd)
	}
	var sent PipelineRequest
	if err := json.Unmarshal(req.Payload, &sent); err != nil {
		t.Fatalf("decode sent payload: %v", err)
	}
	if sent.KBDir != "/kb" || sent.Workers != 3 || len(sent.Items) != 1 || sent.Items[0].SourceRef != "src-1" {
		t.Errorf("payload not forwarded verbatim: %+v", sent)
	}

	if string(resp.Results) != `[{"path":"a.md"}]` {
		t.Errorf("unexpected results: %s", resp.Results)
	}
}

func TestDaemonClientFetchURL(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(
		`{"title":"T","content":"body","date":"2026-07-31","url":"http://example.com/a"}`))

	resp, err := c.FetchURL(context.Background(), "http://example.com/a")
	if err != nil {
		t.Fatalf("FetchURL: unexpected error: %v", err)
	}

	req := sd.only(t)
	if req.Cmd != "fetch-url" {
		t.Errorf("expected cmd=fetch-url, got %q", req.Cmd)
	}
	var sent map[string]string
	if err := json.Unmarshal(req.Payload, &sent); err != nil {
		t.Fatalf("decode sent payload: %v", err)
	}
	if sent["url"] != "http://example.com/a" {
		t.Errorf("url not forwarded: %+v", sent)
	}

	if resp.Title != "T" || resp.Content != "body" || resp.Date != "2026-07-31" {
		t.Errorf("unexpected response: %+v", resp)
	}
}

// TestDaemonClientRawDataCommands covers the commands that hand the daemon's
// data field back to the caller untouched.
func TestDaemonClientRawDataCommands(t *testing.T) {
	tests := []struct {
		name    string
		wantCmd string
		data    string
		invoke  func(*DaemonClient) (json.RawMessage, error)
	}{
		{
			name:    "index",
			wantCmd: "index",
			data:    `{"files":12}`,
			invoke: func(c *DaemonClient) (json.RawMessage, error) {
				return c.Index(context.Background(), IndexRequest{KBDir: "/kb"})
			},
		},
		{
			name:    "rewrite",
			wantCmd: "rewrite",
			data:    `{"queries":["a","b"]}`,
			invoke: func(c *DaemonClient) (json.RawMessage, error) {
				return c.Rewrite(context.Background(), RewriteRequest{Query: "q"})
			},
		},
		{
			name:    "suggest",
			wantCmd: "suggest",
			data:    `{"questions":["why?"]}`,
			invoke: func(c *DaemonClient) (json.RawMessage, error) {
				return c.Suggest(context.Background(), SuggestRequest{Query: "q", Answer: "a"})
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, sd := newScriptedClient(t, alwaysOK(tt.data))

			got, err := tt.invoke(c)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if string(got) != tt.data {
				t.Errorf("expected data %s, got %s", tt.data, got)
			}
			if req := sd.only(t); req.Cmd != tt.wantCmd {
				t.Errorf("expected cmd=%s, got %q", tt.wantCmd, req.Cmd)
			}
		})
	}
}

func TestDaemonClientHealth(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{"status":"ok"}`))

	if err := c.Health(context.Background()); err != nil {
		t.Fatalf("Health: unexpected error: %v", err)
	}
	req := sd.only(t)
	if req.Cmd != "ping" {
		t.Errorf("expected cmd=ping, got %q", req.Cmd)
	}
	if len(req.Payload) != 0 {
		t.Errorf("expected empty payload for ping, got %s", req.Payload)
	}
}

func TestDaemonClientReady(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{}`))

	if !c.Ready() {
		t.Error("expected Ready() to be true for a ready daemon")
	}
	sd.daemon.ready.Store(false)
	if c.Ready() {
		t.Error("expected Ready() to be false once the daemon is not ready")
	}
}

// --- error propagation ----------------------------------------------------

// TestDaemonClientAPIErrorPropagation asserts every command surfaces a
// structured {"ok":false,"error":{...}} response as an *APIError.
func TestDaemonClientAPIErrorPropagation(t *testing.T) {
	tests := []struct {
		name   string
		invoke func(*DaemonClient) error
	}{
		{"extract", func(c *DaemonClient) error {
			_, err := c.Extract(context.Background(), ExtractRequest{Content: "x"})
			return err
		}},
		{"pipeline", func(c *DaemonClient) error {
			_, err := c.Pipeline(context.Background(), PipelineRequest{KBDir: "/kb"})
			return err
		}},
		{"fetch-url", func(c *DaemonClient) error {
			_, err := c.FetchURL(context.Background(), "http://example.com")
			return err
		}},
		{"index", func(c *DaemonClient) error {
			_, err := c.Index(context.Background(), IndexRequest{KBDir: "/kb"})
			return err
		}},
		{"rewrite", func(c *DaemonClient) error {
			_, err := c.Rewrite(context.Background(), RewriteRequest{Query: "q"})
			return err
		}},
		{"suggest", func(c *DaemonClient) error {
			_, err := c.Suggest(context.Background(), SuggestRequest{Query: "q", Answer: "a"})
			return err
		}},
		{"health", func(c *DaemonClient) error {
			return c.Health(context.Background())
		}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, _ := newScriptedClient(t, func(req daemonRequest) []string {
				return []string{errLine(req.ID, "LLM_TIMEOUT", "upstream timed out")}
			})

			err := tt.invoke(c)
			if err == nil {
				t.Fatal("expected an error")
			}
			var apiErr *APIError
			if !errors.As(err, &apiErr) {
				t.Fatalf("expected *APIError, got %T: %v", err, err)
			}
			if apiErr.Code != "LLM_TIMEOUT" || apiErr.Message != "upstream timed out" {
				t.Errorf("unexpected APIError: %+v", apiErr)
			}
		})
	}
}

// TestDaemonClientFailureWithoutErrorDetail covers the fallback path when the
// daemon reports failure but omits the error object.
func TestDaemonClientFailureWithoutErrorDetail(t *testing.T) {
	c, _ := newScriptedClient(t, func(req daemonRequest) []string {
		return []string{bareErrLine(req.ID)}
	})

	_, err := c.Extract(context.Background(), ExtractRequest{Content: "x"})
	if err == nil {
		t.Fatal("expected an error")
	}
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		t.Fatalf("expected a generic error, got *APIError: %v", err)
	}
	if !strings.Contains(err.Error(), "no error detail") {
		t.Errorf("unexpected error message: %v", err)
	}
}

// TestDaemonClientDecodeErrors covers responses that are OK but whose data does
// not match the expected shape.
func TestDaemonClientDecodeErrors(t *testing.T) {
	tests := []struct {
		name    string
		wantMsg string
		invoke  func(*DaemonClient) error
	}{
		{"extract", "daemon extract: decode response", func(c *DaemonClient) error {
			_, err := c.Extract(context.Background(), ExtractRequest{Content: "x"})
			return err
		}},
		{"pipeline", "daemon pipeline: decode response", func(c *DaemonClient) error {
			_, err := c.Pipeline(context.Background(), PipelineRequest{KBDir: "/kb"})
			return err
		}},
		{"fetch-url", "daemon fetch_url: decode response", func(c *DaemonClient) error {
			_, err := c.FetchURL(context.Background(), "http://example.com")
			return err
		}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// A JSON string cannot be decoded into the response struct.
			c, _ := newScriptedClient(t, alwaysOK(`"not-an-object"`))

			err := tt.invoke(c)
			if err == nil {
				t.Fatal("expected a decode error")
			}
			if !strings.Contains(err.Error(), tt.wantMsg) {
				t.Errorf("expected error containing %q, got %v", tt.wantMsg, err)
			}
		})
	}
}

// TestDaemonClientNotReady asserts calls fail fast once the daemon is down
// rather than blocking until the context expires.
func TestDaemonClientNotReady(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{}`))
	sd.daemon.ready.Store(false)

	if _, err := c.Extract(context.Background(), ExtractRequest{Content: "x"}); !errors.Is(err, ErrDaemonNotReady) {
		t.Errorf("Extract: expected ErrDaemonNotReady, got %v", err)
	}
	err := c.Chat(context.Background(), ChatRequest{Query: "q"}, func(json.RawMessage) error { return nil })
	if !errors.Is(err, ErrDaemonNotReady) {
		t.Errorf("Chat: expected ErrDaemonNotReady, got %v", err)
	}
	if len(sd.commands()) != 0 {
		t.Errorf("expected no requests to reach a down daemon, got %v", sd.commands())
	}
}

// --- streaming commands ---------------------------------------------------

func TestDaemonClientChatStreamsUntilFinal(t *testing.T) {
	c, sd := newScriptedClient(t, func(req daemonRequest) []string {
		return []string{
			streamLine(req.ID, `{"type":"delta","content":"Hel"}`, false),
			streamLine(req.ID, `{"type":"delta","content":"lo"}`, false),
			streamLine(req.ID, `{"type":"done"}`, true),
		}
	})

	temp := 0.0
	includeSources := false
	var types []string
	err := c.Chat(context.Background(), ChatRequest{
		Query:          "what is kaas?",
		KBDir:          "/kb",
		Temperature:    &temp,
		IncludeSources: &includeSources,
	}, func(raw json.RawMessage) error {
		types = append(types, EventType(raw))
		return nil
	})
	if err != nil {
		t.Fatalf("Chat: unexpected error: %v", err)
	}

	if want := []string{"delta", "delta", "done"}; !equalStrings(types, want) {
		t.Errorf("expected events %v, got %v", want, types)
	}

	req := sd.only(t)
	if req.Cmd != "chat" {
		t.Errorf("expected cmd=chat, got %q", req.Cmd)
	}
	// Temperature and IncludeSources are pointers so an explicit zero/false
	// survives serialisation rather than being dropped by omitempty.
	var sent map[string]any
	if err := json.Unmarshal(req.Payload, &sent); err != nil {
		t.Fatalf("decode sent payload: %v", err)
	}
	if _, ok := sent["temperature"]; !ok {
		t.Error("expected explicit temperature=0 to be sent")
	}
	if _, ok := sent["include_sources"]; !ok {
		t.Error("expected explicit include_sources=false to be sent")
	}
}

func TestDaemonClientPipelineStreamsUntilFinal(t *testing.T) {
	c, sd := newScriptedClient(t, func(req daemonRequest) []string {
		return []string{
			streamLine(req.ID, `{"type":"article","path":"a.md"}`, false),
			streamLine(req.ID, `{"type":"summary"}`, true),
		}
	})

	var types []string
	err := c.PipelineStream(context.Background(), PipelineRequest{KBDir: "/kb"}, func(raw json.RawMessage) error {
		types = append(types, EventType(raw))
		return nil
	})
	if err != nil {
		t.Fatalf("PipelineStream: unexpected error: %v", err)
	}
	if want := []string{"article", "summary"}; !equalStrings(types, want) {
		t.Errorf("expected events %v, got %v", want, types)
	}
	if req := sd.only(t); req.Cmd != "pipeline_stream" {
		t.Errorf("expected cmd=pipeline_stream, got %q", req.Cmd)
	}
}

// TestDaemonClientChatOnEventErrorCancels asserts a consumer error (e.g. the
// HTTP client disconnecting) stops the stream and tells the daemon to cancel.
func TestDaemonClientChatOnEventErrorCancels(t *testing.T) {
	c, sd := newScriptedClient(t, func(req daemonRequest) []string {
		if req.Cmd == "cancel" {
			return nil
		}
		return []string{
			streamLine(req.ID, `{"type":"delta","content":"a"}`, false),
			streamLine(req.ID, `{"type":"delta","content":"b"}`, false),
			streamLine(req.ID, `{"type":"done"}`, true),
		}
	})

	consumerErr := errors.New("client disconnected")
	calls := 0
	err := c.Chat(context.Background(), ChatRequest{Query: "q"}, func(json.RawMessage) error {
		calls++
		return consumerErr
	})
	if !errors.Is(err, consumerErr) {
		t.Fatalf("expected the consumer error to propagate, got %v", err)
	}
	if calls != 1 {
		t.Errorf("expected the consumer to be invoked once, got %d", calls)
	}

	cmds := sd.commands()
	if len(cmds) != 2 || cmds[0] != "chat" || cmds[1] != "cancel" {
		t.Errorf("expected [chat cancel], got %v", cmds)
	}

	// The cancel request must name the stream being abandoned.
	sd.mu.Lock()
	cancelReq := sd.requests[1]
	chatID := sd.requests[0].ID
	sd.mu.Unlock()

	var payload map[string]string
	if err := json.Unmarshal(cancelReq.Payload, &payload); err != nil {
		t.Fatalf("decode cancel payload: %v", err)
	}
	if payload["target_id"] != chatID {
		t.Errorf("expected target_id=%s, got %q", chatID, payload["target_id"])
	}
}

// TestDaemonClientChatContextCancelCancels asserts a cancelled caller context
// aborts the stream and notifies the daemon.
func TestDaemonClientChatContextCancelCancels(t *testing.T) {
	c, sd := newScriptedClient(t, func(req daemonRequest) []string {
		if req.Cmd == "cancel" {
			return nil
		}
		// Never send a final event, so the stream stays open until cancel.
		return []string{streamLine(req.ID, `{"type":"delta","content":"a"}`, false)}
	})

	ctx, cancel := context.WithCancel(context.Background())
	err := c.Chat(ctx, ChatRequest{Query: "q"}, func(json.RawMessage) error {
		cancel() // cancel from inside the consumer, then keep waiting
		return nil
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
	if cmds := sd.commands(); len(cmds) != 2 || cmds[1] != "cancel" {
		t.Errorf("expected a cancel to follow the chat, got %v", cmds)
	}
}

// --- init and shutdown ----------------------------------------------------

func TestSendInitForwardsLLMConfig(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{}`))

	if err := c.sendInit(context.Background(), c.llm); err != nil {
		t.Fatalf("sendInit: unexpected error: %v", err)
	}

	req := sd.only(t)
	if req.Cmd != "init" {
		t.Errorf("expected cmd=init, got %q", req.Cmd)
	}
	var payload struct {
		LLM map[string]string `json:"llm"`
	}
	if err := json.Unmarshal(req.Payload, &payload); err != nil {
		t.Fatalf("decode init payload: %v", err)
	}
	// extract_strategy is forwarded on init as well as per extract call: the
	// derive command compiles a copied extraction layer, and that compile has to
	// compare against the strategy the copies were produced under or it
	// re-extracts every one of them and records a different one.
	want := map[string]string{
		"api_key":          "test-key",
		"base_url":         "http://llm.local/v1",
		"model":            "test-model",
		"summarize_model":  "test-summarize-model",
		"extract_strategy": "summarize",
	}
	for k, v := range want {
		if payload.LLM[k] != v {
			t.Errorf("init payload %s: expected %q, got %q", k, v, payload.LLM[k])
		}
	}
}

func TestSendInitErrors(t *testing.T) {
	tests := []struct {
		name    string
		reply   func(daemonRequest) []string
		wantMsg string
	}{
		{
			name:    "structured error",
			reply:   func(req daemonRequest) []string { return []string{errLine(req.ID, "BAD_KEY", "invalid api key")} },
			wantMsg: "daemon init failed: invalid api key",
		},
		{
			name:    "no error detail",
			reply:   func(req daemonRequest) []string { return []string{bareErrLine(req.ID)} },
			wantMsg: "daemon init failed: unknown error",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, _ := newScriptedClient(t, tt.reply)

			err := c.sendInit(context.Background(), c.llm)
			if err == nil {
				t.Fatal("expected an error")
			}
			if err.Error() != tt.wantMsg {
				t.Errorf("expected %q, got %q", tt.wantMsg, err.Error())
			}
		})
	}
}

// TestSendInitTransportError covers the wrapped-error path when the call itself
// fails rather than the daemon reporting failure.
func TestSendInitTransportError(t *testing.T) {
	c, sd := newScriptedClient(t, alwaysOK(`{}`))
	sd.daemon.ready.Store(false)

	err := c.sendInit(context.Background(), c.llm)
	if !errors.Is(err, ErrDaemonNotReady) {
		t.Fatalf("expected ErrDaemonNotReady to be wrapped, got %v", err)
	}
	if !strings.Contains(err.Error(), "daemon init:") {
		t.Errorf("expected the error to be wrapped with context, got %v", err)
	}
}

// TestDaemonClientStopEndsSupervisor asserts Stop cancels the supervisor
// goroutine and returns rather than leaking it.
func TestDaemonClientStopEndsSupervisor(t *testing.T) {
	sd := newScriptedDaemon(t, alwaysOK(`{}`))
	ctx, cancel := context.WithCancel(context.Background())
	c := &DaemonClient{
		daemon: sd.daemon,
		cfg:    DaemonConfig{MaxRestarts: 1, WarmupTimeoutSec: 5},
		ctx:    ctx,
		cancel: cancel,
	}
	c.supervWg.Add(1)
	go c.supervisorLoop()

	stopped := make(chan struct{})
	go func() {
		c.Stop()
		close(stopped)
	}()

	// Stop() waits on daemon.done, which only a real process closes. Mimic the
	// process exiting after Stop closes stdin — waiting for the stopping flag
	// first is what tells the supervisor this is a graceful stop, not a crash.
	for !sd.daemon.stopping.Load() {
		time.Sleep(time.Millisecond)
	}
	close(sd.daemon.done)

	select {
	case <-stopped:
	case <-time.After(2 * time.Second):
		t.Fatal("Stop did not return; supervisor goroutine likely leaked")
	}

	if c.Ready() {
		t.Error("expected the daemon to be not ready after Stop")
	}
}

// --- daemonRespError ------------------------------------------------------

func TestDaemonRespError(t *testing.T) {
	t.Run("with error detail", func(t *testing.T) {
		err := daemonRespError(&daemonResponse{
			OK:    false,
			Error: &APIError{Code: "E1", Message: "boom"},
		})
		var apiErr *APIError
		if !errors.As(err, &apiErr) {
			t.Fatalf("expected *APIError, got %T", err)
		}
		if apiErr.Code != "E1" || apiErr.Message != "boom" {
			t.Errorf("unexpected APIError: %+v", apiErr)
		}
	})

	t.Run("without error detail", func(t *testing.T) {
		err := daemonRespError(&daemonResponse{OK: false})
		var apiErr *APIError
		if errors.As(err, &apiErr) {
			t.Fatal("expected a generic error, got *APIError")
		}
		if !strings.Contains(err.Error(), "no error detail") {
			t.Errorf("unexpected error message: %v", err)
		}
	})
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// --- fakeDaemon helper -------------------------------------------------------
//
// fakeDaemon is a thin wrapper around newScriptedClient for tests that want to
// preset a single reply and inspect the last request's command and payload,
// rather than writing a full scripted handler.

type fakeDaemon struct {
	mu          sync.Mutex
	reply       daemonResponse
	lastCmd     string
	lastPayload json.RawMessage
}

func newFakeDaemonClient(t *testing.T) (*DaemonClient, *fakeDaemon) {
	t.Helper()
	fake := &fakeDaemon{}
	c, _ := newScriptedClient(t, func(req daemonRequest) []string {
		fake.mu.Lock()
		fake.lastCmd = req.Cmd
		fake.lastPayload = append(json.RawMessage{}, req.Payload...)
		reply := fake.reply
		fake.mu.Unlock()

		out := daemonResponse{
			ID:    req.ID,
			OK:    reply.OK,
			Data:  reply.Data,
			Error: reply.Error,
		}
		data, _ := json.Marshal(out)
		return []string{string(data)}
	})
	return c, fake
}

// --- Derive ------------------------------------------------------------------

func TestDeriveMarshalsTheRequestAndDecodesTheResponse(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: true, Data: json.RawMessage(`{
		"derived_kb": "/kb/derived/pricing",
		"slug": "pricing",
		"topic": "pricing",
		"selected": 4,
		"documents": 3,
		"bytes": 2048,
		"filter_batches": 2,
		"compiled": true,
		"cost": {"total_cost_usd": 1.5}
	}`)}

	got, err := c.Derive(context.Background(), DeriveRequest{
		KBDir: "/kb", Topic: "pricing", Slug: "pricing", Force: true, Model: "m",
	})
	if err != nil {
		t.Fatalf("Derive: %v", err)
	}
	if fake.lastCmd != "derive" {
		t.Errorf("cmd = %q, want derive", fake.lastCmd)
	}
	var sent DeriveRequest
	if err := json.Unmarshal(fake.lastPayload, &sent); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if sent.KBDir != "/kb" || sent.Topic != "pricing" || !sent.Force || sent.Model != "m" {
		t.Errorf("sent = %+v", sent)
	}
	if got.Slug != "pricing" || got.Documents != 3 || !got.Compiled {
		t.Errorf("got = %+v", got)
	}
}

// TestDeriveCarriesSelectFrom pins select_from onto the wire payload. The engine
// defaults an absent key to articles, so a field dropped in marshalling would
// derive over the wrong catalog and still report success.
func TestDeriveCarriesSelectFrom(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: true, Data: json.RawMessage(`{
		"derived_kb": "/kb/derived/pricing",
		"slug": "pricing",
		"topic": "pricing",
		"select_from": "documents",
		"selected": 4,
		"documents": 3,
		"compiled": true
	}`)}

	got, err := c.Derive(context.Background(), DeriveRequest{
		KBDir: "/kb", Topic: "pricing", SelectFrom: "documents",
	})
	if err != nil {
		t.Fatalf("Derive: %v", err)
	}
	var sent DeriveRequest
	if err := json.Unmarshal(fake.lastPayload, &sent); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if sent.SelectFrom != "documents" {
		t.Errorf("sent.SelectFrom = %q, want documents", sent.SelectFrom)
	}
	if got.SelectFrom != "documents" {
		t.Errorf("got.SelectFrom = %q, want documents", got.SelectFrom)
	}
}

// TestDeriveOmitsAnUnsetSelectFrom keeps the default resolved in one place: the
// engine. Sending "" explicitly would work only because the daemon coerces a
// falsy value, so the omission is what the assertion pins.
func TestDeriveOmitsAnUnsetSelectFrom(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: true, Data: json.RawMessage(`{"slug": "pricing"}`)}

	if _, err := c.Derive(context.Background(), DeriveRequest{KBDir: "/kb", Topic: "t"}); err != nil {
		t.Fatalf("Derive: %v", err)
	}
	if bytes.Contains(fake.lastPayload, []byte("select_from")) {
		t.Errorf("payload = %s, want no select_from key", fake.lastPayload)
	}
}

func TestDeriveSurfacesAnEngineError(t *testing.T) {
	c, fake := newFakeDaemonClient(t)
	fake.reply = daemonResponse{OK: false,
		Error: &APIError{Code: "SLUG_EXISTS", Message: "already exists"}}

	_, err := c.Derive(context.Background(), DeriveRequest{KBDir: "/kb", Topic: "t"})
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Code != "SLUG_EXISTS" {
		t.Fatalf("err = %v, want an APIError with SLUG_EXISTS", err)
	}
}
