import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiFetch, ApiError } from './client'

const mockFetch = vi.fn()
global.fetch = mockFetch

function makeResponse(status: number, body: unknown, ok?: boolean) {
  const text = JSON.stringify(body)
  return {
    ok: ok ?? (status >= 200 && status < 300),
    status,
    statusText: 'HTTP ' + status,
    clone() { return this },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
  } as unknown as Response
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('apiFetch', () => {
  it('prefixes /api to path', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {}))
    await apiFetch('/tasks')
    expect(mockFetch).toHaveBeenCalledWith('/api/tasks', expect.any(Object))
  })

  it('does not double-prefix /api', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {}))
    await apiFetch('/api/tasks')
    expect(mockFetch).toHaveBeenCalledWith('/api/tasks', expect.any(Object))
  })

  it('sets Content-Type application/json by default', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {}))
    await apiFetch('/submit', { method: 'POST', body: '{}' })
    const calledInit = mockFetch.mock.calls[0][1] as RequestInit
    expect((calledInit.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('skips Content-Type when body is FormData', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {}))
    const fd = new FormData()
    await apiFetch('/upload', { method: 'POST', body: fd })
    const calledInit = mockFetch.mock.calls[0][1] as RequestInit
    expect((calledInit.headers as Record<string, string>)['Content-Type']).toBeUndefined()
  })

  it('throws ApiError with status and {error} message on 404', async () => {
    mockFetch.mockResolvedValue(makeResponse(404, { error: 'not found' }))
    await expect(apiFetch('/missing')).rejects.toMatchObject({
      status: 404,
      message: 'not found',
    })
  })

  it('throws ApiError with {message} field as fallback', async () => {
    mockFetch.mockResolvedValue(makeResponse(400, { message: 'bad input' }))
    await expect(apiFetch('/bad')).rejects.toMatchObject({
      status: 400,
      message: 'bad input',
    })
  })

  it('falls back to statusText when body has no error/message', async () => {
    mockFetch.mockResolvedValue(makeResponse(500, { foo: 'bar' }))
    await expect(apiFetch('/fail')).rejects.toMatchObject({
      status: 500,
      message: 'HTTP 500',
    })
  })

  it('throws ApiError instance on non-ok', async () => {
    mockFetch.mockResolvedValue(makeResponse(409, { error: 'duplicate' }))
    await expect(apiFetch('/dup')).rejects.toBeInstanceOf(ApiError)
  })

  it('returns Response on ok', async () => {
    const res = makeResponse(200, { ok: true })
    mockFetch.mockResolvedValue(res)
    const result = await apiFetch('/ok')
    expect(result).toBe(res)
  })
})
