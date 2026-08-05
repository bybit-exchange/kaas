import { apiFetch } from './client'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface StreamChatRequest {
  query: string
  messages?: ChatMessage[]
  temperature?: number
  include_sources?: boolean
  session_id?: string
}

/**
 * POST /api/chat — returns the raw Response with the SSE stream.
 * Callers are responsible for reading the body (Task 4).
 *
 * kb scopes the answer to a derived knowledge base; omit it (or pass null) to
 * answer from the root corpus.
 */
export async function streamChat(
  req: StreamChatRequest,
  signal?: AbortSignal,
  kb?: string | null,
): Promise<Response> {
  return apiFetch(kb ? `/chat?kb=${encodeURIComponent(kb)}` : '/chat', {
    method: 'POST',
    body: JSON.stringify(req),
    headers: { Accept: 'text/event-stream' },
    ...(signal ? { signal } : {}),
  })
}
