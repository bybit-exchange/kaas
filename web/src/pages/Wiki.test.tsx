import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { useKB } from '@/store/kb'

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
})
