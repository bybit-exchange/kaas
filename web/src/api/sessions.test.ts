import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  listSessions,
  createSession,
  renameSession,
  deleteSession,
  getMessages,
} from './sessions'
import { ApiError } from './client'
import type { Session, Message } from './sessions'

const mockFetch = vi.fn()
global.fetch = mockFetch

const sampleSession: Session = {
  id: 's1',
  title: 'First chat',
  created_at: '2026-07-30T10:00:00Z',
  updated_at: '2026-07-31T10:00:00Z',
}

const sampleMessage: Message = {
  id: 'm1',
  session_id: 's1',
  role: 'user',
  content: 'hello',
  created_at: '2026-07-31T10:00:00Z',
}

function makeResponse(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'HTTP ' + status,
    clone() {
      return this
    },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
  } as unknown as Response
}

/** The RequestInit the code under test handed to fetch. */
function lastInit(): RequestInit {
  return mockFetch.mock.calls[0][1] as RequestInit
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('listSessions', () => {
  it('unwraps the sessions envelope', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { sessions: [sampleSession] }))

    const sessions = await listSessions()

    expect(sessions).toEqual([sampleSession])
    expect(mockFetch.mock.calls[0][0]).toBe('/api/sessions')
  })

  it('returns an empty list when there are no sessions', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { sessions: [] }))

    await expect(listSessions()).resolves.toEqual([])
  })

  it('surfaces a backend error as ApiError', async () => {
    mockFetch.mockResolvedValue(makeResponse(500, { error: 'store unavailable' }))

    await expect(listSessions()).rejects.toThrow(ApiError)
    await expect(listSessions()).rejects.toThrow('store unavailable')
  })
})

describe('createSession', () => {
  it('POSTs the title as JSON', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, sampleSession))

    const created = await createSession('First chat')

    expect(created).toEqual(sampleSession)
    expect(mockFetch.mock.calls[0][0]).toBe('/api/sessions')
    expect(lastInit().method).toBe('POST')
    expect(JSON.parse(lastInit().body as string)).toEqual({ title: 'First chat' })
  })

  it('sends a JSON content type', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, sampleSession))

    await createSession('x')

    const headers = lastInit().headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('preserves an empty title rather than dropping the field', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, sampleSession))

    await createSession('')

    expect(JSON.parse(lastInit().body as string)).toEqual({ title: '' })
  })
})

describe('renameSession', () => {
  it('PATCHes the session with the new title', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { ...sampleSession, title: 'Renamed' }))

    const renamed = await renameSession('s1', 'Renamed')

    expect(renamed.title).toBe('Renamed')
    expect(mockFetch.mock.calls[0][0]).toBe('/api/sessions/s1')
    expect(lastInit().method).toBe('PATCH')
    expect(JSON.parse(lastInit().body as string)).toEqual({ title: 'Renamed' })
  })

  it('surfaces a missing session as ApiError', async () => {
    mockFetch.mockResolvedValue(makeResponse(404, { error: 'session not found' }))

    await expect(renameSession('ghost', 'x')).rejects.toThrow('session not found')
  })
})

describe('deleteSession', () => {
  it('DELETEs the session', async () => {
    mockFetch.mockResolvedValue(makeResponse(204, {}))

    await expect(deleteSession('s1')).resolves.toBeUndefined()
    expect(mockFetch.mock.calls[0][0]).toBe('/api/sessions/s1')
    expect(lastInit().method).toBe('DELETE')
  })

  it('rejects when the backend refuses', async () => {
    mockFetch.mockResolvedValue(makeResponse(409, { error: 'session is busy' }))

    await expect(deleteSession('s1')).rejects.toThrow('session is busy')
  })
})

describe('getMessages', () => {
  it('unwraps the messages envelope', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { messages: [sampleMessage] }))

    const messages = await getMessages('s1')

    expect(messages).toEqual([sampleMessage])
    expect(mockFetch.mock.calls[0][0]).toBe('/api/sessions/s1/messages')
  })

  it('returns an empty list for a fresh session', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { messages: [] }))

    await expect(getMessages('s1')).resolves.toEqual([])
  })

  it('keeps assistant metadata intact', async () => {
    const assistant: Message = {
      id: 'm2',
      session_id: 's1',
      role: 'assistant',
      content: 'answer',
      reasoning: 'thinking',
      sources: [{ title: 'One', path: 'wiki/one.md' }] as Message['sources'],
      usage: { tokens_prompt: 10, tokens_completion: 5 } as Message['usage'],
      created_at: '2026-07-31T10:01:00Z',
    }
    mockFetch.mockResolvedValue(makeResponse(200, { messages: [assistant] }))

    const [msg] = await getMessages('s1')

    expect(msg.reasoning).toBe('thinking')
    expect(msg.sources).toHaveLength(1)
    expect(msg.usage).toBeDefined()
  })
})
