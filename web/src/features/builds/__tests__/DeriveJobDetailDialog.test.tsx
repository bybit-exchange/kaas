import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { DeriveJobDetailDialog } from '../DeriveJobDetailDialog'
import type { DeriveJob } from '@/api/derived'

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
})

describe('DeriveJobDetailDialog', () => {
  it('shows loading skeleton when loading is true', () => {
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={null} loading={true} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Derive Job Detail')).toBeInTheDocument()
  })

  it('shows nothing when job is null and not loading', () => {
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={null} loading={false} />
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
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('pricing and fees')).toBeInTheDocument()
    expect(within(dialog).getByText('pricing-fees')).toBeInTheDocument()
    expect(within(dialog).getByText('gpt-4o')).toBeInTheDocument()
    expect(within(dialog).getByText('Articles')).toBeInTheDocument()
  })

  it('shows em-dash for empty model', () => {
    const job = { ...JOB, model: '' }
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={job} loading={false} />
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
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Engine default')).toBeInTheDocument()
  })

  it('shows "Documents" for documents select_from', () => {
    const job = { ...JOB, select_from: 'documents' }
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Documents')).toBeInTheDocument()
  })

  it('shows the error section for a failed job', () => {
    const job = { ...JOB, status: 'failed' as const, error: 'LLM rate limit exceeded' }
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={job} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Error')).toBeInTheDocument()
    expect(within(dialog).getByText('LLM rate limit exceeded')).toBeInTheDocument()
  })

  it('shows the result JSON for a completed job', () => {
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={JOB} loading={false} />
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
        <DeriveJobDetailDialog open={false} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders StatusStageBadge with the job status and stage', () => {
    const runningJob = { ...JOB, status: 'running' as const, stage: 'filter', result: undefined }
    render(
      <Wrapper>
        <DeriveJobDetailDialog open={true} onOpenChange={() => {}} job={runningJob} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    // StatusStageBadge for running shows "Running · Filtering"
    expect(dialog.textContent).toContain('Running')
    expect(dialog.textContent).toContain('Filtering')
  })
})
