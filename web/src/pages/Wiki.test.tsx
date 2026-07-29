import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

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

// Mock mermaid to avoid jsdom canvas issues
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }),
  },
}))

// Import after mocking
import { Wiki } from './Wiki'

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
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
})
