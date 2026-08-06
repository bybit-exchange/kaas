import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { useKB } from '@/store/kb'
import { ApiError } from '@/api/client'

// Mock the wiki API
vi.mock('@/api/wiki', () => ({
  listWiki: vi.fn().mockResolvedValue({
    tree: [
      { name: 'a.md', path: 'a.md', title: 'Article A', isDir: false },
      { name: 'b.md', path: 'b.md', title: 'Article B', isDir: false },
    ],
  }),
  fetchWikiArticle: vi.fn().mockResolvedValue({
    path: 'a.md',
    title: 'T',
    content: '# T\n\n## Sec',
  }),
}))

// The sidebar's KB selector loads the derived-KB list on mount, and its derive
// dialog starts and polls jobs.
vi.mock('@/api/derived', () => ({
  listDerived: vi.fn().mockResolvedValue({
    kbs: [{ slug: 'pricing', topic: 'pricing', created_at: '2026-08-04', article_count: 1 }],
  }),
  startDerive: vi.fn(),
  getDeriveJob: vi.fn(),
}))

// Mock mermaid to avoid jsdom canvas issues
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }),
  },
}))

// Import after mocking
import { listWiki, fetchWikiArticle } from '@/api/wiki'
import { listDerived, startDerive, getDeriveJob } from '@/api/derived'
import { Wiki } from './Wiki'

function renderWiki(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LangProvider>
        <Routes>
          <Route path="wiki/*" element={<Wiki />} />
        </Routes>
      </LangProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  useKB.setState({ kb: null })
  vi.mocked(listWiki).mockClear()
  vi.mocked(fetchWikiArticle).mockClear()
  vi.mocked(listDerived).mockClear()
})

describe('Wiki page', () => {
  it('renders article title and section heading, and shows index list with both articles', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki/a.md']}>
        <LangProvider>
          <Routes>
            <Route path="wiki/*" element={<Wiki />} />
          </Routes>
        </LangProvider>
      </MemoryRouter>,
    )

    // Index list shows both article titles
    await waitFor(() => {
      expect(screen.getByText('Article A')).toBeInTheDocument()
      expect(screen.getByText('Article B')).toBeInTheDocument()
    })

    // Article title (h1) rendered in meta and markdown, plus section heading (h2)
    await waitFor(() => {
      const headings = screen.getAllByRole('heading', { name: 'T' })
      expect(headings.length).toBeGreaterThanOrEqual(1)
      expect(screen.getByRole('heading', { name: 'Sec' })).toBeInTheDocument()
    })
  })

  it('shows empty state when no path param', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <LangProvider>
          <Routes>
            <Route path="wiki/*" element={<Wiki />} />
          </Routes>
        </LangProvider>
      </MemoryRouter>,
    )

    await waitFor(() => {
      // Should show the index list
      expect(screen.getByText('Article A')).toBeInTheDocument()
    })
    // No article rendered - heading from article content should not be present
    expect(screen.queryByRole('heading', { name: 'T' })).not.toBeInTheDocument()
  })

  it('refetches the tree when the knowledge base changes', async () => {
    renderWiki('/wiki')
    await waitFor(() => expect(listWiki).toHaveBeenCalledWith(null))

    await act(async () => {
      useKB.getState().setKB('pricing')
    })

    await waitFor(() => expect(listWiki).toHaveBeenCalledWith('pricing'))
  })

  it('reloads the knowledge-base list once a derive succeeds', async () => {
    const user = userEvent.setup()
    vi.mocked(startDerive).mockResolvedValue({ job_id: 'j1', slug: 'compliance' })
    vi.mocked(getDeriveJob).mockResolvedValue({
      id: 'j1',
      slug: 'compliance',
      topic: 'compliance',
      status: 'succeeded',
      stage: 'done',
      result: {
        selected: 3, documents: 2, bytes: 10, offtopic: 0, filter_batches: 1, compiled: true,
      },
      created_at: 1,
      updated_at: 2,
    })

    renderWiki('/wiki')
    await waitFor(() => expect(listDerived).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: /derive/i }))
    await user.type(await screen.findByLabelText('Topic'), 'compliance')
    await user.click(screen.getByRole('button', { name: /^start$/i }))

    // The new KB must reach the selector without a page reload.
    await waitFor(() => expect(listDerived).toHaveBeenCalledTimes(2))
  })

  it('scopes the article fetch to the selected knowledge base', async () => {
    useKB.setState({ kb: 'pricing' })
    renderWiki('/wiki/a.md')

    await waitFor(() => expect(fetchWikiArticle).toHaveBeenCalledWith('a.md', 'pricing'))
  })

  // A 404 is the routine case — a stale link into a KB that was re-derived — and
  // must read differently from a backend that is down, so the two are pinned
  // separately.
  it('tells the reader the article is gone when the server answers 404', async () => {
    vi.mocked(fetchWikiArticle).mockRejectedValueOnce(new ApiError(404, 'not found'))

    renderWiki('/wiki/missing.md')

    expect(await screen.findByText('Article not found')).toBeInTheDocument()
  })

  it('reports a load failure for any other error', async () => {
    vi.mocked(fetchWikiArticle).mockRejectedValueOnce(new Error('network down'))

    renderWiki('/wiki/a.md')

    expect(await screen.findByText('Failed to load article')).toBeInTheDocument()
  })

  it('survives a tree that fails to load, leaving the article readable', async () => {
    vi.mocked(listWiki).mockRejectedValueOnce(new Error('tree unavailable'))

    renderWiki('/wiki/a.md')

    // The article pane is driven by a separate request and must not be blocked.
    // The title appears twice: once in the meta header, once from the markdown.
    expect(await screen.findAllByRole('heading', { name: 'T' })).not.toHaveLength(0)
  })

  it('clears the search box from the inline reset button', async () => {
    const user = userEvent.setup()
    renderWiki('/wiki')

    const search = await screen.findByPlaceholderText('Search articles...')
    await user.type(search, 'pricing')
    expect(search).toHaveValue('pricing')

    // The reset button only exists while the query is non-empty.
    const buttons = screen.getAllByRole('button')
    const reset = buttons.find((b) => b.className.includes('absolute'))
    if (!reset) throw new Error('search reset button not rendered')
    await user.click(reset)

    expect(search).toHaveValue('')
  })

  it('shows the containing folders of a nested article', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'concepts/pricing/fees.md',
      title: 'Fees',
      content: '# Fees',
    })

    renderWiki('/wiki/concepts/pricing/fees.md')

    const crumbs = await screen.findByLabelText('Breadcrumb')
    expect(crumbs).toHaveTextContent('concepts')
    expect(crumbs).toHaveTextContent('pricing')
    // The article's own file name is the heading, not a crumb.
    expect(crumbs).not.toHaveTextContent('fees.md')
  })

  it('shows the creation date when the article carries one', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'a.md',
      title: 'T',
      content: '# T',
      created: '2026-08-04',
    })

    renderWiki('/wiki/a.md')

    expect(await screen.findByText('2026-08-04')).toBeInTheDocument()
  })

  // Long tag lists are truncated so the header cannot push the article off
  // screen; the toggle is the only way to see the rest.
  it('collapses a long tag list behind a toggle', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'a.md',
      title: 'T',
      content: '# T',
      tags: ['t1', 't2', 't3', 't4', 't5', 't6', 't7'],
    })
    const user = userEvent.setup()

    renderWiki('/wiki/a.md')

    expect(await screen.findByText('t5')).toBeInTheDocument()
    expect(screen.queryByText('t6')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '+2 more' }))
    expect(screen.getByText('t7')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'collapse' }))
    expect(screen.queryByText('t7')).not.toBeInTheDocument()
  })

  it('shows every tag inline when there are few enough', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'a.md',
      title: 'T',
      content: '# T',
      tags: ['t1', 't2'],
    })

    renderWiki('/wiki/a.md')

    expect(await screen.findByText('t2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument()
  })

  it('lists the source files behind the source count', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'a.md',
      title: 'T',
      content: '# T',
      sources: ['raw/one.md', 'raw/two.md'],
    })
    const user = userEvent.setup()

    renderWiki('/wiki/a.md')

    await user.click(await screen.findByRole('button', { name: '2 sources' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('2 source files contributed to this article.')
    expect(await screen.findByText('raw/one.md')).toBeInTheDocument()
    expect(screen.getByText('raw/two.md')).toBeInTheDocument()
  })

  it('says "source" in the singular for a single contributing file', async () => {
    vi.mocked(fetchWikiArticle).mockResolvedValueOnce({
      path: 'a.md',
      title: 'T',
      content: '# T',
      sources: ['raw/only.md'],
    })

    renderWiki('/wiki/a.md')

    expect(await screen.findByRole('button', { name: '1 source' })).toBeInTheDocument()
  })

  it('offers no source list when the article records none', async () => {
    renderWiki('/wiki/a.md')

    await screen.findAllByRole('heading', { name: 'T' })
    expect(screen.queryByRole('button', { name: /source/ })).not.toBeInTheDocument()
  })
})
