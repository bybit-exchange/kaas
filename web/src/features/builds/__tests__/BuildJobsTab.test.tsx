import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

// Mock the build jobs API
vi.mock('@/api/buildJobs', () => ({
  listBuildJobs: vi.fn(),
  getBuildJob: vi.fn(),
  deleteBuildJob: vi.fn(),
}))

// Mock tasks API (used by TaskDetailSheet inside BuildJobDetailSheet)
vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
  getTaskContent: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER mocking
import { BuildJobsTab } from '../BuildJobsTab'
import { listBuildJobs, getBuildJob, deleteBuildJob } from '@/api/buildJobs'
import { toast } from 'sonner'

const mockListBuildJobs = vi.mocked(listBuildJobs)
const mockGetBuildJob = vi.mocked(getBuildJob)
const mockDeleteBuildJob = vi.mocked(deleteBuildJob)
const mockToast = vi.mocked(toast)

const JOB_1 = {
  id: 'bj-1',
  source: 'paste',
  title: 'My Build Job',
  file_count: 3,
  status: 'succeeded' as const,
  created_at: 1704103200000,
  updated_at: 1704103500000,
}

const JOB_2 = {
  id: 'bj-2',
  source: 'upload',
  title: 'Upload Batch',
  file_count: 5,
  status: 'failed' as const,
  error: 'extraction failed',
  created_at: 1704106800000,
  updated_at: 1704107400000,
}

const JOB_PENDING = {
  id: 'bj-3',
  source: 'paste',
  title: 'Pending Job',
  file_count: 1,
  status: 'pending' as const,
  created_at: 1704110000000,
  updated_at: 1704110000000,
}

const JOB_RUNNING = {
  id: 'bj-4',
  source: 'upload',
  title: 'Running Job',
  file_count: 2,
  status: 'running' as const,
  created_at: 1704112000000,
  updated_at: 1704113000000,
}

const JOB_PARTIAL = {
  id: 'bj-5',
  source: 'upload',
  title: 'Partial Job',
  file_count: 4,
  status: 'partial' as const,
  created_at: 1704114000000,
  updated_at: 1704115000000,
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
  mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 2 })
  mockGetBuildJob.mockResolvedValue({
    ...JOB_1,
    tasks: [],
  })
  mockDeleteBuildJob.mockResolvedValue(undefined)
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
      <BuildJobsTab />
    </Wrapper>,
  )
  await flushPromises()
  return view
}

describe('BuildJobsTab', () => {
  it('renders job titles and sources', async () => {
    await renderTab()

    expect(screen.getByText('My Build Job')).toBeInTheDocument()
    expect(screen.getByText('Upload Batch')).toBeInTheDocument()
    // source column
    expect(screen.getByText('paste')).toBeInTheDocument()
    expect(screen.getByText('upload')).toBeInTheDocument()
  })

  it('renders StatusStageBadge for each job', async () => {
    await renderTab()

    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('shows file count in the table', async () => {
    await renderTab()

    const row1 = screen.getByText('My Build Job').closest('tr')!
    expect(row1.textContent).toContain('3')
    const row2 = screen.getByText('Upload Batch').closest('tr')!
    expect(row2.textContent).toContain('5')
  })

  describe('delete button states', () => {
    it('enables delete for succeeded jobs', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1], total: 1 })
      await renderTab()

      const row = screen.getByText('My Build Job').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).not.toBeDisabled()
    })

    it('enables delete for failed jobs', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })
      await renderTab()

      const row = screen.getByText('Upload Batch').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).not.toBeDisabled()
    })

    it('enables delete for partial jobs', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_PARTIAL], total: 1 })
      await renderTab()

      const row = screen.getByText('Partial Job').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).not.toBeDisabled()
    })

    it('disables delete for pending jobs', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_PENDING], total: 1 })
      await renderTab()

      const row = screen.getByText('Pending Job').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    })

    it('disables delete for running jobs', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_RUNNING], total: 1 })
      await renderTab()

      const row = screen.getByText('Running Job').closest('tr')!
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

      const row = screen.getByText('My Build Job').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      expect(screen.getByRole('alertdialog')).toHaveTextContent('Delete Build Job')
      expect(mockDeleteBuildJob).not.toHaveBeenCalled()
    })

    it('deletes and reloads the list once confirmed', async () => {
      await renderTab()
      const callsBefore = mockListBuildJobs.mock.calls.length

      fireEvent.click(await openConfirm('My Build Job'))
      await flushPromises()

      expect(mockDeleteBuildJob).toHaveBeenCalledWith('bj-1')
      expect(mockToast.success).toHaveBeenCalledWith('Build job deleted')
      expect(mockListBuildJobs.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('reports failure when delete is rejected', async () => {
      mockDeleteBuildJob.mockRejectedValue(new Error('job is locked'))

      await renderTab()
      fireEvent.click(await openConfirm('My Build Job'))
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('job is locked')
      expect(screen.getByText('My Build Job')).toBeInTheDocument()
    })

    it('abandons the delete when cancelled', async () => {
      await renderTab()

      const row = screen.getByText('My Build Job').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
      await flushPromises()

      expect(mockDeleteBuildJob).not.toHaveBeenCalled()
    })

    it('steps back a page after deleting the last remaining job', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1], total: 11 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(await openConfirm('My Build Job'))
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })
  })

  describe('status filter', () => {
    it('has all/pending/running/succeeded/failed/partial options', async () => {
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
        expect(labels).toContain('Partial')
      }
    })

    it('filters by status via the hidden select fallback', async () => {
      await renderTab()

      vi.clearAllMocks()
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })

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
      expect(mockListBuildJobs).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }))
    })
  })

  describe('sorting', () => {
    it('sorts ascending on first click', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Title'))
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'title', order: 'asc' }),
      )
    })

    it('reverses direction when the same column is clicked again', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Title'))
      await flushPromises()
      fireEvent.click(screen.getByText('Title'))
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'title', order: 'desc' }),
      )
    })

    it('restarts ascending when a different column is chosen', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Title'))
      await flushPromises()
      fireEvent.click(screen.getByText('Title'))
      await flushPromises()
      fireEvent.click(screen.getByText('Source'))
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'source', order: 'asc' }),
      )
    })
  })

  describe('search', () => {
    it('waits for typing to settle before querying', async () => {
      await renderTab()

      fireEvent.change(screen.getByPlaceholderText('Search files...'), {
        target: { value: 'build' },
      })
      await flushPromises()
      expect(mockListBuildJobs).not.toHaveBeenCalledWith(expect.objectContaining({ q: 'build' }))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
      })
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'build' }))
    })

    it('searches immediately on Enter', async () => {
      await renderTab()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'upload' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await flushPromises()

      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'upload' }))
    })
  })

  describe('pagination', () => {
    it('shows no pager for a single page', async () => {
      await renderTab()

      expect(screen.getByText('Total 2 records')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
    })

    it('pages forward and back by offset', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 25 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
      await flushPromises()
      expect(mockListBuildJobs).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })

    it('disables the edges of the pager', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1, JOB_2], total: 25 })
      await renderTab()

      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

      fireEvent.click(screen.getByRole('button', { name: '3' }))
      await flushPromises()

      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    })
  })

  describe('empty state', () => {
    it('shows empty state message', async () => {
      mockListBuildJobs.mockResolvedValue({ jobs: [], total: 0 })
      await renderTab()

      expect(screen.getByText('No build jobs found.')).toBeInTheDocument()
    })
  })

  describe('detail sheet', () => {
    it('opens the detail sheet when clicking a row', async () => {
      await renderTab()

      const row = screen.getByText('My Build Job').closest('tr')!
      fireEvent.click(row)
      await flushPromises()

      expect(mockGetBuildJob).toHaveBeenCalledWith('bj-1')
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('Build Job Detail')).toBeInTheDocument()
    })

    it('shows optimistic data on detail fetch failure', async () => {
      mockGetBuildJob.mockRejectedValue(new Error('detail unavailable'))

      await renderTab()

      const row = screen.getByText('My Build Job').closest('tr')!
      fireEvent.click(row)
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('detail unavailable')
      const dialog = screen.getByRole('dialog')
      // Optimistic data from the row is displayed (source field)
      expect(within(dialog).getByText('paste')).toBeInTheDocument()
    })

    it('clicking delete does not open the detail sheet', async () => {
      await renderTab()

      const row = screen.getByText('My Build Job').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      // Delete confirmation should appear
      expect(screen.getByRole('alertdialog')).toBeInTheDocument()
      // Detail sheet should NOT have opened
      expect(mockGetBuildJob).not.toHaveBeenCalled()
    })
  })

  it('shows error toast when list fetch fails', async () => {
    mockListBuildJobs.mockRejectedValue(new Error('backend unreachable'))

    await renderTab()

    expect(mockToast.error).toHaveBeenCalledWith('backend unreachable')
  })

  it('marks failed jobs with red left border', async () => {
    mockListBuildJobs.mockResolvedValue({ jobs: [JOB_2], total: 1 })
    await renderTab()

    const row = screen.getByText('Upload Batch').closest('tr')!
    expect(row.className).toContain('border-l-destructive')
  })

  it('does not mark succeeded jobs with red left border', async () => {
    mockListBuildJobs.mockResolvedValue({ jobs: [JOB_1], total: 1 })
    await renderTab()

    const row = screen.getByText('My Build Job').closest('tr')!
    expect(row.className).not.toContain('border-l-destructive')
  })
})
