import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { DeriveJobDetailSheet } from '../DeriveJobDetailSheet'
import type { DeriveJob } from '@/api/derived'

vi.mock('@/api/wiki', () => ({
  listWiki: vi.fn().mockResolvedValue({ tree: [] }),
  fetchWikiArticle: vi.fn().mockResolvedValue({ path: '', title: '', content: '' }),
}))

const { listWiki } = await import('@/api/wiki')
const mockListWiki = vi.mocked(listWiki)

const JOB: DeriveJob = {
  id: 'dj-1',
  slug: 'pricing-fees',
  topic: 'pricing and fees',
  model: 'gpt-4o',
  select_from: 'articles',
  status: 'succeeded',
  stage: 'done',
  created_at: 1704103200000,
  updated_at: 1704103500000,
  result: {
    selected: 5,
    documents: 12,
    bytes: 1024,
    filter_batches: 2,
    compiled: true,
  },
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
  mockListWiki.mockReset()
  mockListWiki.mockResolvedValue({ tree: [] })
})

describe('DeriveJobDetailSheet', () => {
  it('shows loading skeleton when loading is true', () => {
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={null} loading={true} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Derive Job Detail')).toBeInTheDocument()
  })

  it('shows nothing when job is null and not loading', () => {
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={null} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Derive Job Detail')).toBeInTheDocument()
    // No topic/slug should be visible
    expect(within(dialog).queryByText('pricing and fees')).not.toBeInTheDocument()
  })

  it('renders topic, slug, model, and select_from', () => {
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('pricing and fees')).toBeInTheDocument()
    expect(within(dialog).getByText('pricing-fees')).toBeInTheDocument()
    expect(within(dialog).getByText('gpt-4o')).toBeInTheDocument()
    expect(within(dialog).getAllByText('Articles').length).toBeGreaterThanOrEqual(1)
  })

  it('shows em-dash for empty model', () => {
    const job = { ...JOB, model: '' }
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    // Model label followed by em-dash
    expect(dialog.textContent).toContain('Model:')
    expect(dialog.textContent).toContain('—')
  })

  it('shows "Engine default" for empty select_from', () => {
    const job = { ...JOB, select_from: '' }
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Engine default')).toBeInTheDocument()
  })

  it('shows "Documents" for documents select_from', () => {
    const job = { ...JOB, select_from: 'documents' }
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Documents')).toBeInTheDocument()
  })

  it('shows the error section for a failed job', () => {
    const job = { ...JOB, status: 'failed' as const, error: 'LLM rate limit exceeded' }
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Error')).toBeInTheDocument()
    expect(within(dialog).getByText('LLM rate limit exceeded')).toBeInTheDocument()
  })

  it('shows the result JSON for a completed job', () => {
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Result')).toBeInTheDocument()
    expect(dialog.textContent).toContain('"selected": 5')
    expect(dialog.textContent).toContain('"documents": 12')
  })

  it('does not render when open is false', () => {
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={false} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders StatusStageBadge with the job status and stage', () => {
    const runningJob = { ...JOB, status: 'running' as const, stage: 'filter', result: undefined }
    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={runningJob} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    // StatusStageBadge for running shows "Running · Filtering"
    expect(dialog.textContent).toContain('Running')
    expect(dialog.textContent).toContain('Filtering')
  })
})

// ---------------------------------------------------------------------------
// Article table tests
// ---------------------------------------------------------------------------

const mockWikiTree = {
  tree: [
    {
      name: 'concept',
      path: 'concept',
      isDir: true,
      fileCount: 2,
      children: [
        { name: 'trading-fees.md', path: 'concept/trading-fees.md', title: 'Trading Fees', isDir: false, tags: ['fees'] },
        { name: 'margin.md', path: 'concept/margin.md', title: 'Margin Trading', isDir: false, tags: ['margin'] },
      ],
    },
  ],
}

describe('DeriveJobDetailSheet — article table', () => {
  it('shows article titles when job is succeeded', async () => {
    mockListWiki.mockResolvedValue(mockWikiTree)

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')

    await waitFor(() => {
      expect(within(dialog).getByText('Trading Fees')).toBeInTheDocument()
      expect(within(dialog).getByText('Margin Trading')).toBeInTheDocument()
    })

    expect(mockListWiki).toHaveBeenCalledWith('pricing-fees')
  })

  it('does not show articles section or call listWiki for a failed job', () => {
    const failedJob: DeriveJob = { ...JOB, status: 'failed', error: 'boom' }

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={failedJob} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    // The article section heading is a <p> with font-medium class and text "Articles".
    // "Articles" also appears as the select_from label. Check that no article table exists.
    expect(within(dialog).queryByRole('table')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('No articles produced.')).not.toBeInTheDocument()
    expect(mockListWiki).not.toHaveBeenCalled()
  })

  it('does not show articles section for a running job', () => {
    const runningJob: DeriveJob = { ...JOB, status: 'running', stage: 'filter', result: undefined }

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={runningJob} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByRole('table')).not.toBeInTheDocument()
    expect(within(dialog).queryByText('No articles produced.')).not.toBeInTheDocument()
    expect(mockListWiki).not.toHaveBeenCalled()
  })

  it('shows error message when listWiki rejects', async () => {
    mockListWiki.mockRejectedValue(new Error('wiki fetch failed'))

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')

    await waitFor(() => {
      expect(within(dialog).getByText('Failed to load articles')).toBeInTheDocument()
    })
  })

  it('shows empty message when wiki tree has no articles', async () => {
    mockListWiki.mockResolvedValue({ tree: [] })

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')

    await waitFor(() => {
      expect(within(dialog).getByText('No articles produced.')).toBeInTheDocument()
    })
  })

  it('opens DeriveWikiPreviewSheet when clicking article title', async () => {
    mockListWiki.mockResolvedValue(mockWikiTree)
    const user = userEvent.setup()

    render(
      <Wrapper>
        <DeriveJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    // Wait for articles to load
    await waitFor(() => {
      expect(screen.getByText('Trading Fees')).toBeInTheDocument()
    })

    // Click the article title button
    await user.click(screen.getByText('Trading Fees'))

    // The preview sheet opens — Radix renders nested sheets.
    // fetchWikiArticle should be called for the preview sheet.
    const { fetchWikiArticle } = await import('@/api/wiki')
    await waitFor(() => {
      expect(fetchWikiArticle).toHaveBeenCalledWith('concept/trading-fees.md', 'pricing-fees')
    })
  })
})
