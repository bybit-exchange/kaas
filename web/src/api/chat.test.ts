import { describe, it, expect, vi, beforeEach } from 'vitest'
import { streamChat } from './chat'

const mockFetch = vi.fn()
global.fetch = mockFetch

function makeResponse(status: number, body: unknown) {
  const text = JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'HTTP ' + status,
    clone() { return this },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
    body: null,
  } as unknown as Response
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('streamChat', () => {
  it('POSTs to /api/chat with query in body', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, null))
    await streamChat({ query: 'hello?' })
    expect(mockFetch).toHaveBeenCalledWith('/api/chat', expect.objectContaining({
      method: 'POST',
    }))
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string)
    expect(body.query).toBe('hello?')
  })

  it('sets Accept: text/event-stream header', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, null))
    await streamChat({ query: 'hi' })
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['Accept']).toBe('text/event-stream')
  })

  it('includes optional fields when provided', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, null))
    await streamChat({
      query: 'q',
      messages: [{ role: 'user', content: 'prev' }],
      temperature: 0.7,
      include_sources: true,
    })
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string)
    expect(body.messages).toEqual([{ role: 'user', content: 'prev' }])
    expect(body.temperature).toBe(0.7)
    expect(body.include_sources).toBe(true)
  })

  it('forwards AbortSignal', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, null))
    const controller = new AbortController()
    await streamChat({ query: 'q' }, controller.signal)
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.signal).toBe(controller.signal)
  })

  it('returns the raw Response without consuming body', async () => {
    const rawRes = makeResponse(200, null)
    mockFetch.mockResolvedValue(rawRes)
    const result = await streamChat({ query: 'q' })
    expect(result).toBe(rawRes)
  })

  it('does NOT call res.json() or res.text()', async () => {
    const rawRes = makeResponse(200, null)
    rawRes.json = vi.fn()
    rawRes.text = vi.fn()
    mockFetch.mockResolvedValue(rawRes)
    await streamChat({ query: 'q' })
    expect(rawRes.json).not.toHaveBeenCalled()
    expect(rawRes.text).not.toHaveBeenCalled()
  })
})
