package bridge

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strconv"
	"sync/atomic"
)

// daemonRequest is a JSON command sent to the daemon's stdin.
type daemonRequest struct {
	ID      string          `json:"id"`
	Cmd     string          `json:"cmd"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

// daemonResponse is a single line read from the daemon's stdout.
type daemonResponse struct {
	ID     string          `json:"id"`
	OK     bool            `json:"ok"`
	Stream bool            `json:"stream,omitempty"`
	Final  bool            `json:"final,omitempty"`
	Data   json.RawMessage `json:"data,omitempty"`
	Event  json.RawMessage `json:"event,omitempty"`
	Error  *APIError       `json:"error,omitempty"`
}

// streamEntry tracks a pending streaming request.
type streamEntry struct {
	ch       chan *daemonResponse
	canceled atomic.Bool
}

// readLoop continuously reads JSON responses from stdout and dispatches them
// by ID to the appropriate pending channel. Non-streaming responses go to
// pendingOnce; streaming responses go to pendingStream.
// It must be started as a goroutine after the daemon becomes ready.
// TODO: Start() should launch readLoop after __READY__ signal.
func (d *MultiplexStreamDaemon) readLoop(scanner *bufio.Scanner) {
	defer d.drainAll()

	for scanner.Scan() {
		var resp daemonResponse
		if err := json.Unmarshal(scanner.Bytes(), &resp); err != nil {
			log.Printf("[multiplex-stream] readLoop: invalid JSON: %v", err)
			continue
		}
		if resp.ID == "" {
			continue
		}

		if resp.Stream {
			if val, ok := d.pendingStream.Load(resp.ID); ok {
				entry := val.(*streamEntry)
				if entry.canceled.Load() {
					// Consumer cancelled; discard messages until final arrives for cleanup.
					if resp.Final {
						d.pendingStream.Delete(resp.ID)
						close(entry.ch)
					}
					continue
				}
				entry.ch <- &resp
				if resp.Final {
					d.pendingStream.Delete(resp.ID)
					close(entry.ch)
				}
			}
		} else {
			if val, ok := d.pendingOnce.LoadAndDelete(resp.ID); ok {
				ch := val.(chan *daemonResponse)
				ch <- &resp // cap=1 buffered, won't block
			}
		}
	}
}

// call sends a non-streaming request to the daemon and waits for the response.
// It returns ErrDaemonNotReady if the daemon exits or is drained before responding.
func (d *MultiplexStreamDaemon) call(ctx context.Context, req daemonRequest) (*daemonResponse, error) {
	if d.stopping.Load() || !d.ready.Load() {
		return nil, ErrDaemonNotReady
	}

	// Acquire semaphore.
	select {
	case d.sem <- struct{}{}:
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-d.done:
		return nil, ErrDaemonNotReady
	}
	d.wg.Add(1)
	defer func() { <-d.sem; d.wg.Done() }()

	// Generate unique ID, register cap=1 buffered channel.
	id := strconv.FormatUint(d.nextID.Add(1), 10)
	respCh := make(chan *daemonResponse, 1)
	d.pendingOnce.Store(id, respCh)

	// Post-register double-check against stopping race.
	if d.stopping.Load() {
		d.pendingOnce.Delete(id)
		return nil, ErrDaemonNotReady
	}

	// Write request to stdin.
	req.ID = id
	data, err := json.Marshal(req)
	if err != nil {
		d.pendingOnce.Delete(id)
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}
	data = append(data, '\n')

	d.writerMu.Lock()
	_, writeErr := d.stdin.Write(data)
	d.writerMu.Unlock()

	if writeErr != nil {
		d.pendingOnce.Delete(id)
		d.ready.Store(false)
		return nil, fmt.Errorf("failed to write to stdin: %w", writeErr)
	}

	// Wait for response via select (single read).
	defer d.pendingOnce.Delete(id)
	select {
	case resp := <-respCh:
		if resp == nil {
			return nil, ErrDaemonNotReady
		}
		return resp, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-d.done:
		return nil, ErrDaemonNotReady
	}
}

// stream sends a streaming request and consumes events via the onEvent callback.
// It returns nil when the final event is received, or ctx.Err() if the context is cancelled.
func (d *MultiplexStreamDaemon) stream(ctx context.Context, req daemonRequest, onEvent func(json.RawMessage) error) error {
	if d.stopping.Load() || !d.ready.Load() {
		return ErrDaemonNotReady
	}

	// Acquire semaphore.
	select {
	case d.sem <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	case <-d.done:
		return ErrDaemonNotReady
	}
	d.wg.Add(1)
	defer func() { <-d.sem; d.wg.Done() }()

	// Generate unique ID, create stream entry.
	id := strconv.FormatUint(d.nextID.Add(1), 10)
	entry := &streamEntry{
		ch: make(chan *daemonResponse, 64),
	}
	d.pendingStream.Store(id, entry)

	// Write request to stdin.
	req.ID = id
	data, err := json.Marshal(req)
	if err != nil {
		d.pendingStream.Delete(id)
		return fmt.Errorf("failed to marshal request: %w", err)
	}
	data = append(data, '\n')

	d.writerMu.Lock()
	_, writeErr := d.stdin.Write(data)
	d.writerMu.Unlock()

	if writeErr != nil {
		d.pendingStream.Delete(id)
		d.ready.Store(false)
		return fmt.Errorf("failed to write to stdin: %w", writeErr)
	}

	// Consume streaming events.
	for {
		select {
		case resp, ok := <-entry.ch:
			if !ok {
				// Channel closed by drainAll (daemon crash) or readLoop after final
				// when canceled. In either case the daemon is unavailable.
				return ErrDaemonNotReady
			}
			if resp == nil {
				return ErrDaemonNotReady
			}
			if err := onEvent(resp.Event); err != nil {
				// onEvent error (e.g. HTTP client disconnected):
				// mark canceled and send cancel command.
				entry.canceled.Store(true)
				d.sendCancel(id)
				return err
			}
			if resp.Final {
				return nil
			}

		case <-ctx.Done():
			entry.canceled.Store(true)
			d.sendCancel(id)
			return ctx.Err()

		case <-d.done:
			return ErrDaemonNotReady
		}
	}
}

// drainAll is called when readLoop exits (stdout EOF / daemon crash).
// It notifies all waiting callers that the daemon is no longer available.
func (d *MultiplexStreamDaemon) drainAll() {
	d.ready.Store(false)

	// Drain non-streaming pending: write nil sentinel to buffered channel.
	d.pendingOnce.Range(func(key, val any) bool {
		ch := val.(chan *daemonResponse)
		select {
		case ch <- nil:
		default:
		}
		d.pendingOnce.Delete(key)
		return true
	})

	// Drain streaming pending: close channel so stream() receives ok=false.
	d.pendingStream.Range(func(key, val any) bool {
		entry := val.(*streamEntry)
		close(entry.ch)
		d.pendingStream.Delete(key)
		return true
	})
}

// sendCancel writes a cancel command to stdin targeting the given request ID.
func (d *MultiplexStreamDaemon) sendCancel(targetID string) {
	cancelID := "cancel-" + strconv.FormatUint(d.nextID.Add(1), 10)
	payload, _ := json.Marshal(map[string]string{"target_id": targetID})
	cancelReq := daemonRequest{
		ID:      cancelID,
		Cmd:     "cancel",
		Payload: payload,
	}
	data, _ := json.Marshal(cancelReq)
	data = append(data, '\n')

	d.writerMu.Lock()
	_, _ = d.stdin.Write(data)
	d.writerMu.Unlock()
}
