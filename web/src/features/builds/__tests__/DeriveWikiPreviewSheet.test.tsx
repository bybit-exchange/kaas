import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { DeriveWikiPreviewSheet } from '../DeriveWikiPreviewSheet'
import type { WikiArticle } from '@/api/wiki'

vi.mock('@/api/wiki', () => ({
  fetchWikiArticle: vi.fn(),
}))

// Import after mock so we get the mocked version
const { fetchWikiArticle } = await import('@/api/wiki')
const mockFetch = vi.mocked(fetchWikiArticle)

const ARTICLE: WikiArticle = {
  path: 'pricing/fees.md',
  title: 'Pricing and Fees',
  tags: ['billing', 'pricing'],
  sources: ['source-a.pdf', 'source-b.pdf'],
  content: '# Pricing\n\nHere are the fees.',
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <LangProvider>{children}</LangProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  mockFetch.mockReset()
})

describe('DeriveWikiPreviewSheet', () => {
  it('shows loading state when open with a valid articlePath', async () => {
    // Never-resolving promise to keep loading state visible
    mockFetch.mockReturnValue(new Promise(() => {}))

    render(
      <Wrapper>
        <DeriveWikiPreviewSheet
          open={true}
          onOpenChange={() => {}}
          articlePath="pricing/fees.md"
          kb="my-kb"
          displayTitle="Pricing and Fees"
        />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByText('Loading articles…')).toBeInTheDocument()
    })
  })

  it('renders article title, tags, sources, and content on success', async () => {
    mockFetch.mockResolvedValue(ARTICLE)

    render(
      <Wrapper>
        <DeriveWikiPreviewSheet
          open={true}
          onOpenChange={() => {}}
          articlePath="pricing/fees.md"
          kb="my-kb"
          displayTitle="Pricing and Fees"
        />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')

    // Title displayed
    await waitFor(() => {
      expect(within(dialog).getByText('Pricing and Fees')).toBeInTheDocument()
    })

    // Tags
    expect(dialog.textContent).toContain('billing, pricing')

    // Sources
    expect(within(dialog).getByText('source-a.pdf')).toBeInTheDocument()
    expect(within(dialog).getByText('source-b.pdf')).toBeInTheDocument()

    // Content lines rendered
    expect(within(dialog).getByText('# Pricing')).toBeInTheDocument()
    expect(within(dialog).getByText('Here are the fees.')).toBeInTheDocument()

    // fetchWikiArticle called with correct args
    expect(mockFetch).toHaveBeenCalledWith('pricing/fees.md', 'my-kb')
  })

  it('shows error state when fetch fails', async () => {
    mockFetch.mockRejectedValue(new Error('Network timeout'))

    render(
      <Wrapper>
        <DeriveWikiPreviewSheet
          open={true}
          onOpenChange={() => {}}
          articlePath="pricing/fees.md"
          kb="my-kb"
          displayTitle="Pricing and Fees"
        />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    await waitFor(() => {
      expect(within(dialog).getByText('Network timeout')).toBeInTheDocument()
    })
  })

  it('does not render when open is false', () => {
    render(
      <Wrapper>
        <DeriveWikiPreviewSheet
          open={false}
          onOpenChange={() => {}}
          articlePath="pricing/fees.md"
          kb="my-kb"
          displayTitle="Pricing and Fees"
        />
      </Wrapper>,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // fetchWikiArticle should not be called when closed
    expect(mockFetch).not.toHaveBeenCalled()
  })
})
