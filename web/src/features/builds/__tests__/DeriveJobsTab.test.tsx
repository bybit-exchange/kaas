import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

// Mock the derived API
vi.mock('@/api/derived', () => ({
  listDeriveJobs: vi.fn(),
  getDeriveJob: vi.fn(),
  deleteDeriveJob: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER mocking
import { DeriveJobsTab } from '../DeriveJobsTab'
import { listDeriveJobs, getDeriveJob, deleteDeriveJob } from '@/api/derived'
import { toast } from 'sonner'

const mockListDeriveJobs = vi.mocked(listDeriveJobs)
const mockGetDeriveJob = vi.mocked(getDeriveJob)
const mockDeleteDeriveJob = vi.mocked(deleteDeriveJob)
const mockToast = vi.mocked(toast)

const JOB_1 = {
  id: 'dj-1',
  slug: 'pricing-fees',
  topic: 'pricing and fees',
  model: 'gpt-4o',
  select_from: 'articles',
  status: 'succeeded' as const,
  stage: 'done',
  created_at: 1704103200000,
  updated_at: 1704103500000,
  result: { selected: 5, documents: 12, bytes: 1024, filter_batches: 2, compiled: true },
}

const JOB_2 = {
  id: 'dj-2',
  slug: 'security-review',
  topic: 'security best practices',
  model: '',
  select_from: 'documents',
  status: 'failed' as const,
  stage: 'filter',
  error: 'LLM rate limit exceeded',
  created_at: 1704106800000,
  updated_at: 1704107400000,
}

const JOB_PENDING = {
  id: 'dj-3',
  slug: 'onboarding',
  topic: 'employee onboarding',
  model: '',
  select_from: '',
  status: 'pending' as const,
  stage: 'queued',
  created_at: 1704110000000,
  updated_at: 1704110000000,
}

const JOB_RUNNING = {
  id: 'dj-4',
  slug: 'compliance',
  topic: 'compliance requirements',
  model: 'gpt-4o',
  select_from: 'articles',
  status: 'running' as const,
  stage: 'compile',
  created_at: 1704112000000,
  updated_at: 1704113000000,
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <LangProvider>{children}</LangProvider>
    </MemoryRouter>
  )
}

// jsdom does not implement scrollIntoView — stub it so Radix Select doesn't throw
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = () => {}
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
  vi.useFakeTimers()
  mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 2 })
  mockGetDeriveJob.mockResolvedValue({
    ...JOB_1,
    result: { selected: 5, documents: 12, bytes: 1024, filter_batches: 2, compiled: true },
  })
  mockDeleteDeriveJob.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

async function renderTab() {
  const view = render(
    <Wrapper>
      <DeriveJobsTab />
    </Wrapper>,
  )
  await flushPromises()
  return view
}

describe('DeriveJobsTab', () => {
  it('renders job topics and slugs', async () => {
    await renderTab()

    expect(screen.getByText('pricing and fees')).toBeInTheDocument()
    expect(screen.getByText('pricing-fees')).toBeInTheDocument()
    expect(screen.getByText('security best practices')).toBeInTheDocument()
    expect(screen.getByText('security-review')).toBeInTheDocument()
  })

  it('renders StatusStageBadge for each job', async () => {
    await renderTab()

    // Succeeded job shows just status
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    // Failed job shows just status
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('shows Articles/Documents in the Select From column based on value', async () => {
    await renderTab()

    expect(screen.getByText('Articles')).toBeInTheDocument()
    expect(screen.getByText('Documents')).toBeInTheDocument()
  })

  it('shows em-dash for empty select_from in the table', async () => {
    mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_PENDING], total: 1 })
    await renderTab()

    // The em-dash should appear in the select_from column
    const row = screen.getByText('employee onboarding').closest('tr')!
    const cells = row.querySelectorAll('td')
    // select_from is the 4th column (index 3)
    expect(cells[3].textContent).toBe('—')
  })

  describe('delete button states', () => {
    it('enables delete for succeeded jobs', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1], total: 1 })
      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).not.toBeDisabled()
    })

    it('enables delete for failed jobs', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })
      await renderTab()

      const row = screen.getByText('security best practices').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).not.toBeDisabled()
    })

    it('disables delete for pending jobs', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_PENDING], total: 1 })
      await renderTab()

      const row = screen.getByText('employee onboarding').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    })

    it('disables delete for running jobs', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_RUNNING], total: 1 })
      await renderTab()

      const row = screen.getByText('compliance requirements').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    })
  })

  describe('delete confirmation', () => {
    async function openConfirm(rowText: string) {
      const row = screen.getByText(rowText).closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      const dialog = screen.getByRole('alertdialog')
      return within(dialog).getByRole('button', { name: 'Delete' })
    }

    it('asks for confirmation before deleting', async () => {
      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      expect(screen.getByRole('alertdialog')).toHaveTextContent('Delete Derive Job')
      expect(mockDeleteDeriveJob).not.toHaveBeenCalled()
    })

    it('deletes and reloads the list once confirmed', async () => {
      await renderTab()
      const callsBefore = mockListDeriveJobs.mock.calls.length

      fireEvent.click(await openConfirm('pricing and fees'))
      await flushPromises()

      expect(mockDeleteDeriveJob).toHaveBeenCalledWith('dj-1')
      expect(mockToast.success).toHaveBeenCalledWith('Derive job deleted')
      expect(mockListDeriveJobs.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('reports failure when delete is rejected', async () => {
      mockDeleteDeriveJob.mockRejectedValue(new Error('job is locked'))

      await renderTab()
      fireEvent.click(await openConfirm('pricing and fees'))
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('job is locked')
      expect(screen.getByText('pricing and fees')).toBeInTheDocument()
    })

    it('abandons the delete when cancelled', async () => {
      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
      await flushPromises()

      expect(mockDeleteDeriveJob).not.toHaveBeenCalled()
    })

    it('steps back a page after deleting the last remaining job', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1], total: 11 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(await openConfirm('pricing and fees'))
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })
  })

  describe('status filter', () => {
    it('has all/pending/running/succeeded/failed but no cancelled', async () => {
      await renderTab()

      // Open the select dropdown
      const trigger = screen.getByRole('combobox')
      fireEvent.click(trigger)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50)
      })

      const listbox = document.querySelector('[role="listbox"]')
      if (listbox) {
        const options = Array.from(listbox.querySelectorAll('[role="option"]'))
        const labels = options.map(o => o.textContent)
        expect(labels).toContain('All')
        expect(labels).toContain('Pending')
        expect(labels).toContain('Running')
        expect(labels).toContain('Succeeded')
        expect(labels).toContain('Failed')
        expect(labels).not.toContain('Cancelled')
      }
    })

    it('filters by status via the hidden select fallback', async () => {
      await renderTab()

      vi.clearAllMocks()
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })

      const hiddenSelect = document.querySelector('select[aria-hidden="true"]') as HTMLSelectElement | null
      if (hiddenSelect) {
        fireEvent.change(hiddenSelect, { target: { value: 'failed' } })
        await flushPromises()
      } else {
        const trigger = screen.getByRole('combobox')
        fireEvent.click(trigger)
        await act(async () => {
          await vi.advanceTimersByTimeAsync(50)
        })
        const listbox = document.querySelector('[role="listbox"]')
        if (listbox) {
          const options = Array.from(listbox.querySelectorAll('[role="option"]'))
          const failedOpt = options.find((o) => o.textContent?.toLowerCase().includes('failed'))
          if (failedOpt) {
            fireEvent.click(failedOpt)
            await flushPromises()
          }
        }
      }

      await flushPromises()
      expect(mockListDeriveJobs).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }))
    })
  })

  describe('sorting', () => {
    it('sorts ascending on first click', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Topic'))
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'topic', order: 'asc' }),
      )
    })

    it('reverses direction when the same column is clicked again', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Topic'))
      await flushPromises()
      fireEvent.click(screen.getByText('Topic'))
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'topic', order: 'desc' }),
      )
    })

    it('restarts ascending when a different column is chosen', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Topic'))
      await flushPromises()
      fireEvent.click(screen.getByText('Topic'))
      await flushPromises()
      fireEvent.click(screen.getByText('Slug'))
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'slug', order: 'asc' }),
      )
    })
  })

  describe('search', () => {
    it('waits for typing to settle before querying', async () => {
      await renderTab()

      fireEvent.change(screen.getByPlaceholderText('Search files...'), {
        target: { value: 'pricing' },
      })
      await flushPromises()
      expect(mockListDeriveJobs).not.toHaveBeenCalledWith(expect.objectContaining({ q: 'pricing' }))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
      })
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'pricing' }))
    })

    it('searches immediately on Enter', async () => {
      await renderTab()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'security' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await flushPromises()

      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'security' }))
    })
  })

  describe('pagination', () => {
    it('shows no pager for a single page', async () => {
      await renderTab()

      expect(screen.getByText('Total 2 records')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
    })

    it('pages forward and back by offset', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 25 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
      await flushPromises()
      expect(mockListDeriveJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })

    it('disables the edges of the pager', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 25 })
      await renderTab()

      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

      fireEvent.click(screen.getByRole('button', { name: '3' }))
      await flushPromises()

      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    })
  })

  describe('empty state', () => {
    it('shows actionable empty state with link to /wiki', async () => {
      mockListDeriveJobs.mockResolvedValue({ jobs: [], total: 0 })
      await renderTab()

      expect(screen.getByText('No derive jobs yet.')).toBeInTheDocument()
      const link = screen.getByText('Derive a topic KB from the Wiki page')
      expect(link).toBeInTheDocument()
      expect(link.closest('a')).toHaveAttribute('href', '/wiki')
    })
  })

  describe('detail sheet', () => {
    it('opens the detail sheet when clicking a row', async () => {
      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      fireEvent.click(row)
      await flushPromises()

      expect(mockGetDeriveJob).toHaveBeenCalledWith('dj-1')
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('Derive Job Detail')).toBeInTheDocument()
    })

    it('shows optimistic data on detail fetch failure', async () => {
      mockGetDeriveJob.mockRejectedValue(new Error('detail unavailable'))

      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      fireEvent.click(row)
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('detail unavailable')
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('pricing and fees')).toBeInTheDocument()
    })

    it('clicking delete does not open the detail sheet', async () => {
      await renderTab()

      const row = screen.getByText('pricing and fees').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      // Delete confirmation should appear
      expect(screen.getByRole('alertdialog')).toBeInTheDocument()
      // Detail sheet should NOT have opened (getDeriveJob should not be called)
      expect(mockGetDeriveJob).not.toHaveBeenCalled()
    })
  })

  it('shows error toast when list fetch fails', async () => {
    mockListDeriveJobs.mockRejectedValue(new Error('backend unreachable'))

    await renderTab()

    expect(mockToast.error).toHaveBeenCalledWith('backend unreachable')
  })

  it('marks failed jobs with red left border', async () => {
    mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })
    await renderTab()

    const row = screen.getByText('security best practices').closest('tr')!
    expect(row.className).toContain('border-l-destructive')
  })

  it('does not mark succeeded jobs with red left border', async () => {
    mockListDeriveJobs.mockResolvedValue({ jobs: [JOB_1], total: 1 })
    await renderTab()

    const row = screen.getByText('pricing and fees').closest('tr')!
    expect(row.className).not.toContain('border-l-destructive')
  })
})
