// StreamHandler.ts — SSE parser for the KaaS chat event stream
// Backend emits one JSON object per SSE frame: `data: <json>\n\n`

export type ChatSource = { title: string; path: string }

export type ChatUsage = {
  tokens_prompt: number
  tokens_completion: number
  cost_usd: number
}

export type StreamPhase = 'idle' | 'iterating' | 'generating'

export type StatusInfo =
  | { type: 'retrieved'; count: number }
  | { type: 'text'; text: string }

export type StreamEvent =
  | { kind: 'status'; sources: ChatSource[]; statusInfo?: StatusInfo }
  | { kind: 'delta'; content: string }
  | { kind: 'done'; citedSources: ChatSource[]; retrievedSources: ChatSource[]; usage: ChatUsage }
  | { kind: 'error'; message: string }
  | { kind: 'reasoning'; content: string }
  | { kind: 'role' }

// ---------------------------------------------------------------------------
// parseSSEData
// Takes a single decoded `data:` payload (the `data: ` prefix already stripped),
// JSON-parses it, and maps the backend's snake_case `type` field to a camelCase
// `kind` StreamEvent. Returns null for any unknown / unhandled type.
// ---------------------------------------------------------------------------
export function parseSSEData(json: string): StreamEvent | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let obj: any
  try {
    obj = JSON.parse(json)
  } catch {
    return null
  }

  switch (obj.type) {
    case 'status': {
      let statusInfo: StatusInfo | undefined
      if (obj.stage === 'retrieved' && Array.isArray(obj.sources)) {
        statusInfo = { type: 'retrieved', count: obj.sources.length }
      } else if (typeof obj.content === 'string') {
        statusInfo = { type: 'text', text: obj.content }
      }
      return {
        kind: 'status',
        sources: Array.isArray(obj.sources) ? obj.sources : [],
        statusInfo,
      }
    }

    case 'delta':
      return {
        kind: 'delta',
        content: obj.content ?? '',
      }

    case 'done':
      return {
        kind: 'done',
        citedSources: Array.isArray(obj.cited_sources) ? obj.cited_sources : [],
        retrievedSources: Array.isArray(obj.retrieved_sources) ? obj.retrieved_sources : [],
        usage: {
          tokens_prompt: obj.tokens_prompt ?? 0,
          tokens_completion: obj.tokens_completion ?? 0,
          cost_usd: obj.cost_usd ?? 0,
        },
      }

    case 'error':
      return {
        kind: 'error',
        message: obj.message ?? '',
      }

    case 'reasoning':
      if (!obj.content) return null
      return {
        kind: 'reasoning',
        content: obj.content,
      }

    case 'role':
      return { kind: 'role' }

    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// readChatStream
// Reads res.body via getReader(), UTF-8 decodes with streaming mode,
// accumulates into a text buffer, splits on \n\n SSE frame boundaries,
// strips the leading `data: ` prefix from each frame line, and dispatches
// non-null parseSSEData results to onEvent.
// Tolerates a frame being split across multiple reads (partial trailing frame
// is buffered and processed when the rest arrives or the stream ends).
// ---------------------------------------------------------------------------
export async function readChatStream(
  res: Response,
  onEvent: (e: StreamEvent) => void,
): Promise<void> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: false })
  let buffer = ''

  function processBuffer() {
    // Split on double-newline SSE frame boundaries
    const frames = buffer.split('\n\n')
    // The last element is either empty (if buffer ended with \n\n)
    // or an incomplete partial frame — keep it in the buffer.
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      // Each frame may have multiple lines; we only handle the `data:` line.
      // Blank frames and SSE comment lines (starting with `:`) are ignored.
      for (const line of frame.split('\n')) {
        const trimmed = line.trim()
        if (trimmed === '' || trimmed.startsWith(':')) continue
        if (trimmed.startsWith('data: ')) {
          const payload = trimmed.slice('data: '.length)
          const event = parseSSEData(payload)
          if (event !== null) onEvent(event)
        }
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      // Flush any remaining text in the decoder's internal state
      const remaining = decoder.decode(undefined, { stream: false })
      if (remaining) buffer += remaining
      // Process any final complete frame that wasn't terminated by \n\n
      // by appending a synthetic boundary so processBuffer picks it up.
      if (buffer.trim() !== '') {
        buffer += '\n\n'
        processBuffer()
      }
      break
    }
    buffer += decoder.decode(value, { stream: true })
    processBuffer()
  }
}
