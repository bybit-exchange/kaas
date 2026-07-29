import { apiFetch } from './client'
import type { ChatSource, ChatUsage } from '../features/chat/StreamHandler'

export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  sources?: ChatSource[]
  usage?: ChatUsage
  created_at: string
}

export async function listSessions(): Promise<Session[]> {
  const res = await apiFetch('/sessions')
  const data = (await res.json()) as { sessions: Session[] }
  return data.sessions
}

export async function createSession(title: string): Promise<Session> {
  const res = await apiFetch('/sessions', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
  return res.json() as Promise<Session>
}

export async function renameSession(id: string, title: string): Promise<Session> {
  const res = await apiFetch(`/sessions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
  return res.json() as Promise<Session>
}

export async function deleteSession(id: string): Promise<void> {
  await apiFetch(`/sessions/${id}`, { method: 'DELETE' })
}

export async function getMessages(sessionId: string): Promise<Message[]> {
  const res = await apiFetch(`/sessions/${sessionId}/messages`)
  const data = (await res.json()) as { messages: Message[] }
  return data.messages
}
