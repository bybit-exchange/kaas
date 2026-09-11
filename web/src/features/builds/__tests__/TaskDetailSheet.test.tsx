import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { usePrefs } from '@/store/prefs'

// Mock the tasks API
vi.mock('@/api/tasks', () => ({
  listTasks: vi.fn(),
  getTask: vi.fn(),
  deleteTask: vi.fn(),
  getTaskContent: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER mocking
import { TaskDetailSheet } from '../TaskDetailSheet'
import { getTask } from '@/api/tasks'
import { toast } from 'sonner'

const mockGetTask = vi.mocked(getTask)
const mockToast = vi.mocked(toast)

const TASK_SUCCEEDED = {
  id: 'task-1',
  source: 'paste',
  title: 'Alpha Task',
  status: 'succeeded',
  stage: 'done',
  attempts: 1,
  max_attempts: 3,
  created_at: 1704103200000,
  updated_at: 1704103500000,
}

const TASK_FAILED = {
  id: 'task-2',
  source: 'url',
  title: 'Beta Task',
  status: 'failed',
  stage: 'extract',
  attempts: 3,
  max_attempts: 3,
  error: 'Connection timeout',
  created_at: 1704106800000,
  updated_at: 1704107400000,
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
  vi.useFakeTimers()
  mockGetTask.mockResolvedValue({ ...TASK_SUCCEEDED, result: { answer: 42 } })
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

describe('TaskDetailSheet', () => {
  it('fetches task detail when opened', async () => {
    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))
  })

  it('shows result JSON with line numbers', async () => {
    mockGetTask.mockResolvedValue({ ...TASK_SUCCEEDED, result: { answer: 42 } })

    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Result')
    expect(dialog.textContent).toContain('"answer": 42')
    // Line numbers are present
    expect(dialog.textContent).toContain('1')
  })

  it('shows status badge in the dialog', async () => {
    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Status')
    expect(dialog.textContent).toContain('Succeeded')
  })

  it('shows error for a failed task', async () => {
    mockGetTask.mockResolvedValue({ ...TASK_FAILED, result: null })

    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-2" />)
    await flushPromises()

    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Error')
    expect(dialog.textContent).toContain('Connection timeout')
  })

  it('shows stage and attempts', async () => {
    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Stage')
    expect(dialog.textContent).toContain('done')
    expect(dialog.textContent).toContain('Attempts')
    expect(dialog.textContent).toContain('1/3')
  })

  it('handles fetch failure gracefully and shows error toast', async () => {
    mockGetTask.mockRejectedValue(new Error('detail unavailable'))

    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    expect(mockToast.error).toHaveBeenCalledWith('detail unavailable')
  })

  it('does not fetch when closed', async () => {
    render(<TaskDetailSheet open={false} onOpenChange={() => {}} taskId="task-1" />)
    await flushPromises()

    expect(mockGetTask).not.toHaveBeenCalled()
  })

  it('does not fetch when taskId is null', async () => {
    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId={null} />)
    await flushPromises()

    expect(mockGetTask).not.toHaveBeenCalled()
  })

  it('shows fallback title when task has not loaded yet', () => {
    // getTask never resolves in this test
    mockGetTask.mockReturnValue(new Promise(() => {}))

    render(<TaskDetailSheet open={true} onOpenChange={() => {}} taskId="task-1" />)

    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('Task Detail')
  })
})
