import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listTasks, getTask, deleteTask, TaskDTO } from './tasks'

const mockFetch = vi.fn()
global.fetch = mockFetch

const sampleTask: TaskDTO = {
  id: 'abc',
  source: 'paste',
  title: 'Test',
  status: 'done',
  stage: 'complete',
  attempts: 1,
  max_attempts: 3,
  created_at: 1704067200000,
  updated_at: 1704067200000,
}

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

describe('listTasks', () => {
  it('defaults limit=20 when params are undefined', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tasks: [], total: 0 }))
    await listTasks()
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/api/tasks')
    expect(url).toContain('limit=20')
  })

  it('builds query string from defined params', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tasks: [], total: 0 }))
    await listTasks({ status: 'done', limit: 10, offset: 20 })
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('status=done')
    expect(url).toContain('limit=10')
    expect(url).toContain('offset=20')
  })

  it('includes q param when provided', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tasks: [], total: 0 }))
    await listTasks({ q: 'hello' })
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('q=hello')
  })

  it('omits undefined params from query string', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tasks: [], total: 0 }))
    await listTasks({ status: 'pending' })
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('status=pending')
    expect(url).not.toContain('offset')
    expect(url).not.toContain('q=')
  })

  it('returns {tasks: TaskDTO[], total: number}', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tasks: [sampleTask], total: 1 }))
    const result = await listTasks()
    expect(result.tasks).toHaveLength(1)
    expect(result.tasks[0].id).toBe('abc')
    expect(result.total).toBe(1)
  })
})

describe('getTask', () => {
  it('hits /api/tasks/{id}', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, sampleTask))
    await getTask('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/tasks/abc', expect.any(Object))
  })

  it('returns the TaskDTO', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, sampleTask))
    const result = await getTask('abc')
    expect(result.id).toBe('abc')
    expect(result.status).toBe('done')
  })
})

describe('deleteTask', () => {
  it('sends DELETE to /api/tasks/{id}', async () => {
    mockFetch.mockResolvedValue(makeResponse(204, null))
    await deleteTask('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/tasks/abc', expect.objectContaining({ method: 'DELETE' }))
  })
})
