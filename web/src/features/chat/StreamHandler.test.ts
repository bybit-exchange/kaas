import { describe, it, expect } from 'vitest'
import { parseSSEData, readChatStream } from './StreamHandler'
import type { StreamEvent, StreamPhase, StatusInfo } from './StreamHandler'

// ── type-level assertions (compile-time only) ────────────────────────────────
// Ensures the exported types are correctly shaped.
const _phaseCheck: StreamPhase = 'idle' as StreamPhase
const _statusCheck: StatusInfo = { type: 'retrieved', count: 0 } as StatusInfo
void _phaseCheck
void _statusCheck

// ── helpers ──────────────────────────────────────────────────────────────────

function fakeResponse(chunks: string[]): Response {
  const enc = new TextEncoder()
  let i = 0
  const reader = {
    read: async () =>
      i < chunks.length
        ? { done: false, value: enc.encode(chunks[i++]) }
        : { done: true, value: undefined },
  }
  return { body: { getReader: () => reader } } as unknown as Response
}

// ── parseSSEData ──────────────────────────────────────────────────────────────

describe('parseSSEData', () => {
  it('maps type:status to kind:status', () => {
    const raw = JSON.stringify({
      type: 'status',
      stage: 'retrieved',
      sources: [{ title: 'Doc', path: 'doc.md' }],
    })
    expect(parseSSEData(raw)).toEqual({
      kind: 'status',
      sources: [{ title: 'Doc', path: 'doc.md' }],
      statusInfo: { type: 'retrieved', count: 1 },
    })
  })

  it('maps type:delta to kind:delta', () => {
    const raw = JSON.stringify({ type: 'delta', content: 'hello' })
    expect(parseSSEData(raw)).toEqual({ kind: 'delta', content: 'hello' })
  })

  it('maps type:done with snake_case → camelCase + usage packing', () => {
    const raw = JSON.stringify({
      type: 'done',
      cited_sources: [{ title: 'T', path: 'a.md' }],
      retrieved_sources: [],
      cost_usd: 0.01,
      tokens_prompt: 5,
      tokens_completion: 7,
      prompt_id: 'p1',
    })
    expect(parseSSEData(raw)).toEqual({
      kind: 'done',
      citedSources: [{ title: 'T', path: 'a.md' }],
      retrievedSources: [],
      usage: { tokens_prompt: 5, tokens_completion: 7, cost_usd: 0.01 },
    })
  })

  it('maps type:error to kind:error', () => {
    const raw = JSON.stringify({ type: 'error', message: 'something failed' })
    expect(parseSSEData(raw)).toEqual({ kind: 'error', message: 'something failed' })
  })

  it('returns null for unknown type', () => {
    const raw = JSON.stringify({ type: 'unknown_future_event', foo: 'bar' })
    expect(parseSSEData(raw)).toBeNull()
  })

  it('defaults missing arrays to [] for status', () => {
    const raw = JSON.stringify({ type: 'status' })
    expect(parseSSEData(raw)).toEqual({ kind: 'status', sources: [], statusInfo: undefined })
  })

  it('defaults missing arrays to [] for done', () => {
    const raw = JSON.stringify({
      type: 'done',
      cost_usd: 0,
      tokens_prompt: 0,
      tokens_completion: 0,
    })
    expect(parseSSEData(raw)).toEqual({
      kind: 'done',
      citedSources: [],
      retrievedSources: [],
      usage: { tokens_prompt: 0, tokens_completion: 0, cost_usd: 0 },
    })
  })

  // ── reasoning event ──────────────────────────────────────────────────────

  it('maps type:reasoning to kind:reasoning with content', () => {
    const raw = JSON.stringify({ type: 'reasoning', content: 'thinking about it...' })
    expect(parseSSEData(raw)).toEqual({ kind: 'reasoning', content: 'thinking about it...' })
  })

  it('returns null for reasoning event with empty content', () => {
    const raw = JSON.stringify({ type: 'reasoning', content: '' })
    expect(parseSSEData(raw)).toBeNull()
  })

  it('returns null for reasoning event with no content', () => {
    const raw = JSON.stringify({ type: 'reasoning' })
    expect(parseSSEData(raw)).toBeNull()
  })

  // ── role event ───────────────────────────────────────────────────────────

  it('maps type:role to kind:role', () => {
    const raw = JSON.stringify({ type: 'role' })
    expect(parseSSEData(raw)).toEqual({ kind: 'role' })
  })

  // ── status with statusInfo ───────────────────────────────────────────────

  it('sets statusInfo={type:retrieved,count:N} when stage is retrieved', () => {
    const raw = JSON.stringify({
      type: 'status',
      stage: 'retrieved',
      sources: [{ title: 'A', path: 'a.md' }, { title: 'B', path: 'b.md' }],
    })
    expect(parseSSEData(raw)).toEqual({
      kind: 'status',
      sources: [{ title: 'A', path: 'a.md' }, { title: 'B', path: 'b.md' }],
      statusInfo: { type: 'retrieved', count: 2 },
    })
  })

  it('sets statusInfo={type:text,text:...} when content is a string', () => {
    const raw = JSON.stringify({
      type: 'status',
      content: 'Searching knowledge base...',
    })
    expect(parseSSEData(raw)).toEqual({
      kind: 'status',
      sources: [],
      statusInfo: { type: 'text', text: 'Searching knowledge base...' },
    })
  })

  it('statusInfo is undefined for old-format status without content/stage', () => {
    const raw = JSON.stringify({ type: 'status' })
    const result = parseSSEData(raw)
    expect(result).toEqual({ kind: 'status', sources: [], statusInfo: undefined })
  })
})

// ── readChatStream ────────────────────────────────────────────────────────────

describe('readChatStream', () => {
  it('emits one delta event when a frame is split across two reads', async () => {
    const res = fakeResponse([
      'data: {"type":"de',
      'lta","content":"hi"}\n\n',
    ])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toEqual([{ kind: 'delta', content: 'hi' }])
  })

  it('emits all events in order from a multi-frame single chunk', async () => {
    const chunk =
      'data: {"type":"delta","content":"A"}\n\n' +
      'data: {"type":"delta","content":"B"}\n\n' +
      'data: {"type":"done","cited_sources":[],"retrieved_sources":[],"cost_usd":0,"tokens_prompt":1,"tokens_completion":2}\n\n'
    const res = fakeResponse([chunk])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toHaveLength(3)
    expect(events[0]).toEqual({ kind: 'delta', content: 'A' })
    expect(events[1]).toEqual({ kind: 'delta', content: 'B' })
    expect(events[2]).toEqual({
      kind: 'done',
      citedSources: [],
      retrievedSources: [],
      usage: { tokens_prompt: 1, tokens_completion: 2, cost_usd: 0 },
    })
  })

  it('ignores blank lines and SSE comment lines', async () => {
    const chunk = ': keep-alive\n\ndata: {"type":"delta","content":"X"}\n\n\n\n'
    const res = fakeResponse([chunk])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toEqual([{ kind: 'delta', content: 'X' }])
  })

  it('handles a complete frame with trailing double newline', async () => {
    // Frame that ends with \n\n (normal case, no flush needed)
    const res = fakeResponse(['data: {"type":"delta","content":"Z"}\n\n'])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toEqual([{ kind: 'delta', content: 'Z' }])
  })

  it('flushes a trailing frame without double newline on stream end', async () => {
    // Simulate stream that ends with a complete frame but NO trailing \n\n
    // This exercises the synthetic-flush path (lines 116-118 in StreamHandler.ts)
    const res = fakeResponse(['data: {"type":"delta","content":"Z"}'])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toEqual([{ kind: 'delta', content: 'Z' }])
  })

  it('emits nothing for unknown event types', async () => {
    const res = fakeResponse(['data: {"type":"ping"}\n\n'])
    const events: StreamEvent[] = []
    await readChatStream(res, (e) => events.push(e))
    expect(events).toHaveLength(0)
  })
})
