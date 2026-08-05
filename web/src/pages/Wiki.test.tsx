import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
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

// The sidebar's KB selector loads the derived-KB list on mount.
vi.mock('@/api/derived', () => ({
  listDerived: vi.fn().mockResolvedValue({
    kbs: [{ slug: 'pricing', topic: 'pricing', created_at: '2026-08-04', article_count: 1 }],
  }),
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

  it('scopes the article fetch to the selected knowledge base', async () => {
    useKB.setState({ kb: 'pricing' })
    renderWiki('/wiki/a.md')

    await waitFor(() => expect(fetchWikiArticle).toHaveBeenCalledWith('a.md', 'pricing'))
  })
})
