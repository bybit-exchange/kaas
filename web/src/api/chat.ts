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
 */
export async function streamChat(
  req: StreamChatRequest,
  signal?: AbortSignal,
): Promise<Response> {
  return apiFetch('/chat', {
    method: 'POST',
    body: JSON.stringify(req),
    headers: { Accept: 'text/event-stream' },
    ...(signal ? { signal } : {}),
  })
}
