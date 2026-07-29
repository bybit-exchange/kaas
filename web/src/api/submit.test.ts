import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ApiError } from './client'
import { submit } from './submit'

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
  } as unknown as Response
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('submit', () => {
  it('POSTs to /api/submit with JSON body', async () => {
    mockFetch.mockResolvedValue(makeResponse(202, { id: 'abc', status: 'pending', stage: 'queue' }))
    await submit({ source: 'paste', content: 'hello' })
    expect(mockFetch).toHaveBeenCalledWith('/api/submit', expect.objectContaining({
      method: 'POST',
    }))
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({ source: 'paste', content: 'hello' })
  })

  it('returns {id,status,stage} on 202', async () => {
    mockFetch.mockResolvedValue(makeResponse(202, { id: 'xyz', status: 'pending', stage: 'queue' }))
    const res = await submit({ source: 'url', url: 'https://example.com' })
    expect(res).toEqual({ id: 'xyz', status: 'pending', stage: 'queue' })
  })

  it('rejects with ApiError(409) on duplicate', async () => {
    mockFetch.mockResolvedValue(makeResponse(409, { error: 'duplicate' }))
    await expect(submit({ source: 'paste', content: 'dup' })).rejects.toMatchObject({
      status: 409,
      message: 'duplicate',
    })
    await expect(submit({ source: 'paste', content: 'dup' }).catch(e => e)).resolves.toBeInstanceOf(ApiError)
  })
})
