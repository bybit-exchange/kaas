import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'
import { BuildJobDetailSheet } from '../BuildJobDetailSheet'
import type { BuildJobDetailDTO } from '@/api/buildJobs'

// Mock tasks API (used by nested TaskDetailSheet and FilePreviewSheet)
vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
  getTaskContent: vi.fn(),
}))

import { getTask } from '@/api/tasks'

const mockGetTask = vi.mocked(getTask)

const TASK_1 = {
  id: 't-1',
  build_job_id: 'bj-1',
  source: 'paste',
  title: 'doc-one.md',
  file_title: 'Document One',
  status: 'succeeded' as const,
  stage: 'done',
  attempts: 1,
  max_attempts: 3,
  created_at: 1704103200000,
  updated_at: 1704103500000,
}

const TASK_2 = {
  id: 't-2',
  build_job_id: 'bj-1',
  source: 'upload',
  title: 'doc-two.md',
  status: 'failed' as const,
  stage: 'extract',
  attempts: 3,
  max_attempts: 3,
  error: 'extraction timeout',
  created_at: 1704106800000,
  updated_at: 1704107400000,
}

const JOB: BuildJobDetailDTO = {
  id: 'bj-1',
  source: 'paste',
  title: 'My Build Job',
  file_count: 2,
  status: 'succeeded',
  created_at: 1704103200000,
  updated_at: 1704103500000,
  tasks: [TASK_1, TASK_2],
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
  vi.clearAllMocks()
  mockGetTask.mockResolvedValue({
    ...TASK_1,
    result: { chunks: 5 },
  })
})

async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('BuildJobDetailSheet', () => {
  it('shows loading skeleton when loading is true', () => {
    render(
      <Wrapper>
        <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={null} loading={true} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Build Job Detail')).toBeInTheDocument()
  })

  it('shows nothing when job is null and not loading', () => {
    render(
      <Wrapper>
        <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={null} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Build Job Detail')).toBeInTheDocument()
    // No job content should be visible
    expect(within(dialog).queryByText('My Build Job')).not.toBeInTheDocument()
  })

  it('renders source, status, and file count', () => {
    render(
      <Wrapper>
        <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('paste')).toBeInTheDocument()
    // Status badge appears for the job and possibly tasks; just check text presence
    expect(dialog.textContent).toContain('Succeeded')
    expect(dialog.textContent).toContain('2')
  })

  it('shows the error section for a failed job', () => {
    const failedJob: BuildJobDetailDTO = {
      ...JOB,
      status: 'failed',
      error: 'all tasks failed',
      tasks: [],
    }
    render(
      <Wrapper>
        <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={failedJob} loading={false} />
      </Wrapper>,
    )

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Error')).toBeInTheDocument()
    expect(within(dialog).getByText('all tasks failed')).toBeInTheDocument()
  })

  it('does not render when open is false', () => {
    render(
      <Wrapper>
        <BuildJobDetailSheet open={false} onOpenChange={() => {}} job={JOB} loading={false} />
      </Wrapper>,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  describe('task list', () => {
    it('renders task table with file titles', () => {
      render(
        <Wrapper>
          <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
        </Wrapper>,
      )

      const dialog = screen.getByRole('dialog')
      // TASK_1 has file_title "Document One"
      expect(within(dialog).getByText('Document One')).toBeInTheDocument()
      // TASK_2 has no file_title, falls back to title "doc-two.md"
      expect(within(dialog).getByText('doc-two.md')).toBeInTheDocument()
    })

    it('shows attempts for each task', () => {
      render(
        <Wrapper>
          <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
        </Wrapper>,
      )

      const dialog = screen.getByRole('dialog')
      expect(dialog.textContent).toContain('1/3')
      expect(dialog.textContent).toContain('3/3')
    })

    it('shows error indicator for failed tasks', () => {
      render(
        <Wrapper>
          <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
        </Wrapper>,
      )

      const dialog = screen.getByRole('dialog')
      // TASK_2 has an error, so there should be an error icon with aria-label
      const errorIndicator = within(dialog).getByLabelText('error')
      expect(errorIndicator).toBeInTheDocument()
      expect(errorIndicator).toHaveAttribute('title', 'extraction timeout')
    })

    it('opens nested TaskDetailSheet when clicking a task row', async () => {
      render(
        <Wrapper>
          <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={JOB} loading={false} />
        </Wrapper>,
      )

      const dialog = screen.getByRole('dialog')
      // Click the task row (not the file name button)
      const taskRow = within(dialog).getByText('Document One').closest('tr')!
      fireEvent.click(taskRow)
      await flushPromises()

      // TaskDetailSheet should be opened — it calls getTask
      expect(mockGetTask).toHaveBeenCalledWith('t-1', expect.any(AbortSignal))
    })

    it('does not show task table when there are no tasks', () => {
      const emptyJob: BuildJobDetailDTO = {
        ...JOB,
        tasks: [],
      }
      render(
        <Wrapper>
          <BuildJobDetailSheet open={true} onOpenChange={() => {}} job={emptyJob} loading={false} />
        </Wrapper>,
      )

      const dialog = screen.getByRole('dialog')
      // No table headers should be present
      expect(within(dialog).queryByText('File')).not.toBeInTheDocument()
    })
  })
})
