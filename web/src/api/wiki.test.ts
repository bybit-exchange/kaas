import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listWiki, fetchWikiArticle } from './wiki'

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

describe('listWiki', () => {
  it('calls GET /api/wiki', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tree: [] }))
    await listWiki()
    expect(mockFetch).toHaveBeenCalledWith('/api/wiki', expect.any(Object))
  })

  it('returns {tree: WikiTreeNode[]}', async () => {
    const tree = [{ name: 'b.md', path: 'a/b.md', title: 'Test', isDir: false }]
    mockFetch.mockResolvedValue(makeResponse(200, { tree }))
    const result = await listWiki()
    expect(result.tree).toEqual(tree)
  })

  it('scopes the tree request to a derived kb', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tree: [] }))
    await listWiki('pricing')
    expect(mockFetch.mock.calls[0][0]).toBe('/api/wiki?kb=pricing')
  })

  it('omits kb for the root knowledge base', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { tree: [] }))
    await listWiki(null)
    expect(mockFetch.mock.calls[0][0]).toBe('/api/wiki')
  })
})

describe('fetchWikiArticle', () => {
  it('encodes path and hits /api/wiki/file?path=...', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { path: 'a/b.md', title: 'T', content: 'c' }))
    await fetchWikiArticle('a/b.md')
    const url = mockFetch.mock.calls[0][0] as string
    expect(url).toBe('/api/wiki/file?path=a%2Fb.md')
  })

  it('returns WikiArticle', async () => {
    const article = { path: 'a/b.md', title: 'Title', content: 'Hello' }
    mockFetch.mockResolvedValue(makeResponse(200, article))
    const result = await fetchWikiArticle('a/b.md')
    expect(result.content).toBe('Hello')
  })

  it('scopes the article request to a derived kb', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { path: 'a.md', title: 'A', content: '' }))
    await fetchWikiArticle('concepts/a.md', 'pricing')
    expect(mockFetch.mock.calls[0][0]).toBe('/api/wiki/file?path=concepts%2Fa.md&kb=pricing')
  })

  it('omits kb for the root knowledge base', async () => {
    mockFetch.mockResolvedValue(makeResponse(200, { path: 'a.md', title: 'A', content: '' }))
    await fetchWikiArticle('a.md', null)
    expect(mockFetch.mock.calls[0][0]).toBe('/api/wiki/file?path=a.md')
  })
})
