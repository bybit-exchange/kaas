package bridge

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"
)

// LLMConfig holds the OpenAI-compatible LLM credentials forwarded to the daemon
// on init. Defined here to avoid circular imports with the config package.
type LLMConfig struct {
	APIKey         string
	BaseURL        string
	Model          string
	SummarizeModel string
}

// DaemonClient talks to the Python AI engine via a long-running daemon process
// using the multiplexed stdin/stdout protocol.
type DaemonClient struct {
	daemon   *MultiplexStreamDaemon
	cfg      DaemonConfig
	llm      LLMConfig
	ctx      context.Context
	cancel   context.CancelFunc
	supervWg sync.WaitGroup
}

// NewDaemonClient spawns the daemon, waits for readiness, and sends an init
// command with the LLM configuration. It returns a ready-to-use client or an
// error if startup or init fails. A supervisor goroutine is started to
// automatically restart the daemon on unexpected crashes.
func NewDaemonClient(ctx context.Context, cfg DaemonConfig, llm LLMConfig) (*DaemonClient, error) {
	d := NewMultiplexStreamDaemon(cfg)
	if err := d.Start(ctx); err != nil {
		return nil, err
	}

	supervisorCtx, cancel := context.WithCancel(context.Background())
	c := &DaemonClient{
		daemon: d,
		cfg:    cfg,
		llm:    llm,
		ctx:    supervisorCtx,
		cancel: cancel,
	}

	if err := c.sendInit(ctx, llm); err != nil {
		cancel()
		d.Stop()
		return nil, err
	}

	c.supervWg.Add(1)
	go c.supervisorLoop()

	return c, nil
}

// sendInit sends the init command with LLM credentials to the daemon.
func (c *DaemonClient) sendInit(ctx context.Context, llm LLMConfig) error {
	initPayload, _ := json.Marshal(map[string]any{"llm": map[string]string{
		"api_key":         llm.APIKey,
		"base_url":        llm.BaseURL,
		"model":           llm.Model,
		"summarize_model": llm.SummarizeModel,
	}})
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "init", Payload: initPayload})
	if err != nil {
		return fmt.Errorf("daemon init: %w", err)
	}
	if !resp.OK {
		if resp.Error != nil {
			return fmt.Errorf("daemon init failed: %s", resp.Error.Message)
		}
		return fmt.Errorf("daemon init failed: unknown error")
	}
	return nil
}

// supervisorLoop monitors the daemon's done channel and restarts it on
// unexpected crashes with exponential backoff, up to MaxRestarts attempts.
func (c *DaemonClient) supervisorLoop() {
	defer c.supervWg.Done()

	restarts := 0
	for {
		select {
		case <-c.ctx.Done():
			return
		case <-c.daemon.done:
			// Check if this was a graceful stop (not a crash).
			if c.daemon.stopping.Load() {
				return
			}

			restarts++
			if restarts > c.cfg.MaxRestarts {
				log.Printf("[supervisor] max restarts (%d) reached, giving up", c.cfg.MaxRestarts)
				return
			}

			// Exponential backoff: 1s, 2s, 4s, ... capped at 30s.
			backoffSec := 1 << (restarts - 1)
			if backoffSec > 30 {
				backoffSec = 30
			}
			log.Printf("[supervisor] daemon crashed, restarting in %ds (attempt %d/%d)", backoffSec, restarts, c.cfg.MaxRestarts)

			select {
			case <-c.ctx.Done():
				return
			case <-time.After(time.Duration(backoffSec) * time.Second):
			}

			// Use warmup timeout for restart context.
			warmupTimeout := time.Duration(c.cfg.WarmupTimeoutSec) * time.Second
			if warmupTimeout == 0 {
				warmupTimeout = 30 * time.Second
			}
			restartCtx, restartCancel := context.WithTimeout(c.ctx, warmupTimeout)
			err := c.daemon.Restart(restartCtx)
			restartCancel()
			if err != nil {
				log.Printf("[supervisor] restart failed: %v", err)
				continue
			}

			if err := c.sendInit(c.ctx, c.llm); err != nil {
				log.Printf("[supervisor] re-init failed: %v", err)
				continue
			}

			log.Printf("[supervisor] daemon recovered (attempt %d/%d)", restarts, c.cfg.MaxRestarts)
		}
	}
}

// Extract runs the extract phase on raw content via the daemon.
func (c *DaemonClient) Extract(ctx context.Context, req ExtractRequest) (*ExtractResponse, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "extract", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	var out ExtractResponse
	if err := json.Unmarshal(resp.Data, &out); err != nil {
		return nil, fmt.Errorf("daemon extract: decode response: %w", err)
	}
	return &out, nil
}

// Pipeline runs Classify → Write and returns all results at once via the daemon.
func (c *DaemonClient) Pipeline(ctx context.Context, req PipelineRequest) (*PipelineResponse, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "pipeline", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	var out PipelineResponse
	if err := json.Unmarshal(resp.Data, &out); err != nil {
		return nil, fmt.Errorf("daemon pipeline: decode response: %w", err)
	}
	return &out, nil
}

// PipelineStream runs Classify → Write, invoking onEvent as each article
// completes, using the daemon's streaming protocol.
func (c *DaemonClient) PipelineStream(ctx context.Context, req PipelineRequest, onEvent func(json.RawMessage) error) error {
	payload, _ := json.Marshal(req)
	return c.daemon.stream(ctx, daemonRequest{Cmd: "pipeline_stream", Payload: payload}, onEvent)
}

// Chat runs streaming RAG chat via the daemon, invoking onEvent per SSE event.
func (c *DaemonClient) Chat(ctx context.Context, req ChatRequest, onEvent func(json.RawMessage) error) error {
	payload, _ := json.Marshal(req)
	return c.daemon.stream(ctx, daemonRequest{Cmd: "chat", Payload: payload}, onEvent)
}

// FetchURL fetches and extracts readable content from a URL via the daemon.
func (c *DaemonClient) FetchURL(ctx context.Context, url string) (*FetchURLResponse, error) {
	payload, _ := json.Marshal(map[string]string{"url": url})
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "fetch-url", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	var out FetchURLResponse
	if err := json.Unmarshal(resp.Data, &out); err != nil {
		return nil, fmt.Errorf("daemon fetch_url: decode response: %w", err)
	}
	return &out, nil
}

// Index rebuilds the markdown indexes via the daemon.
func (c *DaemonClient) Index(ctx context.Context, req IndexRequest) (json.RawMessage, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "index", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	return resp.Data, nil
}

// Derive builds a topic-scoped knowledge base via the daemon.
//
// One call covering filter → copy → compile → prune, so it can run long: the
// caller sets the context deadline. There is no volume gate on this path — it is
// async and there is nobody to prompt (spec H5).
func (c *DaemonClient) Derive(ctx context.Context, req DeriveRequest) (*DeriveResponse, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "derive", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	var out DeriveResponse
	if err := json.Unmarshal(resp.Data, &out); err != nil {
		return nil, fmt.Errorf("daemon derive: decode response: %w", err)
	}
	return &out, nil
}

// Rewrite rewrites a query for retrieval via the daemon.
func (c *DaemonClient) Rewrite(ctx context.Context, req RewriteRequest) (json.RawMessage, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "rewrite", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	return resp.Data, nil
}

// Suggest proposes follow-up questions via the daemon.
func (c *DaemonClient) Suggest(ctx context.Context, req SuggestRequest) (json.RawMessage, error) {
	payload, _ := json.Marshal(req)
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "suggest", Payload: payload})
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, daemonRespError(resp)
	}
	return resp.Data, nil
}

// Health sends a ping command to the daemon and verifies it responds OK.
func (c *DaemonClient) Health(ctx context.Context) error {
	resp, err := c.daemon.call(ctx, daemonRequest{Cmd: "ping"})
	if err != nil {
		return err
	}
	if !resp.OK {
		return daemonRespError(resp)
	}
	return nil
}

// Ready reports whether the daemon process is in a ready state.
func (c *DaemonClient) Ready() bool {
	return c.daemon.Ready()
}

// Stop gracefully shuts down the daemon process and the supervisor goroutine.
func (c *DaemonClient) Stop() {
	c.cancel()
	c.daemon.Stop()
	c.supervWg.Wait()
}

// daemonRespError converts a non-OK daemon response into an appropriate error.
func daemonRespError(resp *daemonResponse) error {
	if resp.Error != nil {
		return &APIError{Code: resp.Error.Code, Message: resp.Error.Message}
	}
	return fmt.Errorf("daemon: request failed with no error detail")
}
