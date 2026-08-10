import { describe, it, expect, vi, beforeEach } from 'vitest'
import { getDeriveJob, listDerived, startDerive } from './derived'

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

describe('listDerived', () => {
  it('calls GET /api/derived', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { kbs: [] }))
    await listDerived()
    expect(mockFetch).toHaveBeenCalledWith('/api/derived', expect.any(Object))
  })

  it('returns the derived knowledge bases', async () => {
    const kb = {
      slug: 'pricing',
      topic: 'pricing',
      created_at: '2026-08-04T10:00:00',
      article_count: 7,
    }
    mockFetch.mockResolvedValue(makeResponse(200, { kbs: [kb] }))
    const { kbs } = await listDerived()
    expect(kbs).toEqual([kb])
  })
})

describe('startDerive', () => {
  it('POSTs the topic to /api/derive', async () => {
    mockFetch.mockResolvedValue(makeResponse(202, { job_id: 'j1', slug: 'pricing' }))
    const res = await startDerive({ topic: 'pricing' })
    expect(res).toEqual({ job_id: 'j1', slug: 'pricing' })
    expect(mockFetch).toHaveBeenCalledWith('/api/derive', expect.objectContaining({
      method: 'POST',
    }))
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({ topic: 'pricing' })
  })

  it('forwards an explicit slug and model', async () => {
    mockFetch.mockResolvedValue(makeResponse(202, { job_id: 'j1', slug: 'p' }))
    await startDerive({ topic: 'pricing', slug: 'p', model: 'claude-sonnet-4-6' })
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({
      topic: 'pricing',
      slug: 'p',
      model: 'claude-sonnet-4-6',
    })
  })
})

describe('getDeriveJob', () => {
  it('calls GET /api/derive/{id}', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {
      id: 'j1', slug: 'pricing', topic: 'pricing',
      status: 'running', stage: 'compile', created_at: 1, updated_at: 2,
    }))
    const job = await getDeriveJob('j1')
    expect(job.status).toBe('running')
    expect(job.stage).toBe('compile')
    expect(mockFetch.mock.calls[0][0]).toBe('/api/derive/j1')
  })

  it('encodes the job id', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {
      id: 'a/b', slug: 's', topic: 't',
      status: 'failed', stage: 'done', created_at: 1, updated_at: 1,
    }))
    await getDeriveJob('a/b')
    expect(mockFetch.mock.calls[0][0]).toBe('/api/derive/a%2Fb')
  })

  it('exposes the result counts and cost of a finished job', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, {
      id: 'j1', slug: 'pricing', topic: 'pricing',
      status: 'succeeded', stage: 'done', created_at: 1, updated_at: 2,
      result: {
        selected: 12, documents: 30, bytes: 40960,
        filter_batches: 2, compiled: true, cost: { total_cost_usd: 1.5 },
      },
    }))
    const job = await getDeriveJob('j1')
    expect(job.result?.documents).toBe(30)
    expect(job.result?.cost?.total_cost_usd).toBe(1.5)
  })
})
