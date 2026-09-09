import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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
import { TasksTab } from '../TasksTab'
import { listTasks, getTask, deleteTask, getTaskContent } from '@/api/tasks'
import { toast } from 'sonner'

const mockListTasks = vi.mocked(listTasks)
const mockGetTask = vi.mocked(getTask)
const mockDeleteTask = vi.mocked(deleteTask)
const mockGetTaskContent = vi.mocked(getTaskContent)
const mockToast = vi.mocked(toast)

const TASK_1 = {
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

const TASK_2 = {
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

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      {children}
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
  mockListTasks.mockResolvedValue({ tasks: [TASK_1, TASK_2], total: 2 })
  mockGetTask.mockResolvedValue({ ...TASK_1, result: { answer: 42 } })
  mockDeleteTask.mockResolvedValue(undefined)
  mockGetTaskContent.mockResolvedValue({ content: 'file body', size: 9, truncated: false })
})

afterEach(() => {
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

// Flush pending microtasks (resolved promises) without firing any timers
async function flushPromises() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

/** Render the tab and wait for the first task list to land. */
async function renderTab() {
  const view = render(
    <Wrapper>
      <TasksTab />
    </Wrapper>,
  )
  await flushPromises()
  return view
}

describe('TasksTab', () => {
  it('renders task titles with merged StatusStageBadge (no Source column)', async () => {
    await renderTab()

    expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    expect(screen.getByText('Beta Task')).toBeInTheDocument()
    // StatusStageBadge renders "Succeeded" for terminal status
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()

    // Source column should NOT be present
    const headers = screen.getAllByRole('columnheader')
    const headerTexts = headers.map((h) => h.textContent)
    expect(headerTexts).not.toContain(expect.stringContaining('Source'))
  })

  it('does not render a Source column in the table', async () => {
    await renderTab()

    // There should be no "Source" column header
    const headers = screen.getAllByRole('columnheader')
    const headerTexts = headers.map((h) => h.textContent?.trim())
    expect(headerTexts.some((t) => t === 'Source')).toBe(false)

    // Task rows should not contain the source value as a separate cell
    const row = screen.getByText('Alpha Task').closest('tr')!
    const cells = row.querySelectorAll('td')
    // Columns: FileTitle, Status, Attempts, Updated, Actions = 5
    expect(cells).toHaveLength(5)
  })

  it('shows merged status and stage in a single StatusStageBadge column', async () => {
    mockListTasks.mockResolvedValue({
      tasks: [{ ...TASK_1, id: 'running-1', title: 'Running Task', status: 'running', stage: 'extract' }],
      total: 1,
    })

    await renderTab()

    // StatusStageBadge shows "Running · Extracting" for non-terminal
    expect(screen.getByText('Running · Extracting')).toBeInTheDocument()
  })

  it('applies red left border on failed rows', async () => {
    await renderTab()

    const failedRow = screen.getByText('Beta Task').closest('tr')!
    expect(failedRow.className).toContain('border-l-4')
    expect(failedRow.className).toContain('border-destructive')

    // Succeeded row should NOT have the red border
    const successRow = screen.getByText('Alpha Task').closest('tr')!
    expect(successRow.className).not.toContain('border-l-4')
  })

  it('changing filter to "failed" calls listTasks with {status: "failed"}', async () => {
    await renderTab()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()

    vi.clearAllMocks()
    mockListTasks.mockResolvedValue({ tasks: [TASK_2], total: 1 })

    // Directly change the select value via the underlying hidden input
    const hiddenSelect = document.querySelector('select[aria-hidden="true"]') as HTMLSelectElement | null

    if (hiddenSelect) {
      fireEvent.change(hiddenSelect, { target: { value: 'failed' } })
      await flushPromises()
    } else {
      // Fallback: click trigger and select from listbox
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
    expect(mockListTasks).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }))
  })

  it('clicking a row opens TaskDetailSheet and fetches detail', async () => {
    const taskWithResult = { ...TASK_1, result: { answer: 42 } }
    mockGetTask.mockResolvedValue(taskWithResult)

    await renderTab()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()

    const row = screen.getByText('Alpha Task').closest('tr')!
    fireEvent.click(row)

    await flushPromises()

    expect(mockGetTask).toHaveBeenCalledWith('task-1', expect.any(AbortSignal))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Result')).toBeInTheDocument()
    expect(dialog.textContent).toContain('"answer": 42')
  })

  it('clicking the filename opens file preview without opening the detail sheet', async () => {
    await renderTab()

    const filenameBtn = screen.getByRole('button', { name: 'Alpha Task' })
    fireEvent.click(filenameBtn)
    await flushPromises()

    // File preview should open
    expect(mockGetTaskContent).toHaveBeenCalledWith('task-1', expect.anything())
    // Detail sheet should NOT have opened (getTask should not be called)
    expect(mockGetTask).not.toHaveBeenCalled()
  })

  it('clicking delete does not open the detail sheet', async () => {
    await renderTab()

    const row = screen.getByText('Alpha Task').closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
    await flushPromises()

    // Delete confirmation should appear
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    // Detail sheet should NOT have opened
    expect(mockGetTask).not.toHaveBeenCalled()
  })

  // Date formatting fallback
  it('falls back to the raw timestamp when it cannot be formatted', async () => {
    const outOfRange = 8.64e15 + 1
    mockListTasks.mockResolvedValue({
      tasks: [{ ...TASK_1, updated_at: outOfRange }],
      total: 1,
    })

    await renderTab()

    expect(screen.getByText(String(outOfRange))).toBeInTheDocument()
  })

  // Error toast on fetch failure
  it('tells the user when the task list cannot be loaded', async () => {
    mockListTasks.mockRejectedValue(new Error('backend unreachable'))

    await renderTab()

    expect(mockToast.error).toHaveBeenCalledWith('backend unreachable')
  })

  // Empty state with link to /submit
  it('shows actionable empty state with link to /submit', async () => {
    mockListTasks.mockResolvedValue({ tasks: [], total: 0 })

    await renderTab()

    expect(screen.getByText('No tasks found.')).toBeInTheDocument()
    const link = screen.getByText('Submit content to get started')
    expect(link).toBeInTheDocument()
    expect(link.closest('a')).toHaveAttribute('href', '/submit')
  })

  // Error indicator on failed task
  it('marks a task that carries an error', async () => {
    await renderTab()

    const row = screen.getByText('Beta Task').closest('tr')!
    expect(within(row).getByLabelText('error')).toHaveAttribute('title', 'Connection timeout')
  })

  // File preview
  it('opens the file preview from the file name', async () => {
    await renderTab()

    fireEvent.click(screen.getByRole('button', { name: 'Alpha Task' }))
    await flushPromises()

    expect(mockGetTaskContent).toHaveBeenCalledWith('task-1', expect.anything())
    expect(screen.getByText('file body')).toBeInTheDocument()
  })

  describe('deleting a task', () => {
    /** Open the confirm dialog for a row and return the confirm button. */
    async function openConfirm(rowText: string) {
      const row = screen.getByText(rowText).closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      const dialog = screen.getByRole('alertdialog')
      return within(dialog).getByRole('button', { name: 'Delete' })
    }

    it('asks for confirmation before deleting', async () => {
      await renderTab()

      const row = screen.getByText('Alpha Task').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      expect(screen.getByRole('alertdialog')).toHaveTextContent('Confirm Delete')
      expect(mockDeleteTask).not.toHaveBeenCalled()
    })

    it('deletes and reloads the list once confirmed', async () => {
      await renderTab()
      const callsBefore = mockListTasks.mock.calls.length

      fireEvent.click(await openConfirm('Alpha Task'))
      await flushPromises()

      expect(mockDeleteTask).toHaveBeenCalledWith('task-1')
      expect(mockToast.success).toHaveBeenCalledWith('Task deleted')
      expect(mockListTasks.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('keeps the task and reports the failure when the delete is rejected', async () => {
      mockDeleteTask.mockRejectedValue(new Error('task is locked'))

      await renderTab()
      fireEvent.click(await openConfirm('Alpha Task'))
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('task is locked')
      expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    })

    it('abandons the delete when the dialog is cancelled', async () => {
      await renderTab()

      const row = screen.getByText('Alpha Task').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      fireEvent.click(
        within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }),
      )
      await flushPromises()

      expect(mockDeleteTask).not.toHaveBeenCalled()
    })

    it.each(['running'])('offers no delete for a %s task', async (status) => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, status, title: 'Busy Task' }],
        total: 1,
      })

      await renderTab()

      const row = screen.getByText('Busy Task').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    })

    it('steps back a page after deleting its last remaining task', async () => {
      // 11 records over a page size of 10: page 2 holds exactly one task.
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 11 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(await openConfirm('Alpha Task'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })
  })

  describe('sorting', () => {
    it('sorts ascending on the first click of a column', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'attempts', order: 'asc' }),
      )
    })

    it('reverses the direction when the same column is clicked again', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()
      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'attempts', order: 'desc' }),
      )
    })

    it('restarts ascending when a different column is chosen', async () => {
      await renderTab()

      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()
      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()
      fireEvent.click(screen.getByText('Updated'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'updated_at', order: 'asc' }),
      )
    })
  })

  describe('search', () => {
    it('waits for typing to settle before querying', async () => {
      await renderTab()

      fireEvent.change(screen.getByPlaceholderText('Search files...'), {
        target: { value: 'alpha' },
      })
      await flushPromises()
      expect(mockListTasks).not.toHaveBeenCalledWith(expect.objectContaining({ q: 'alpha' }))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300)
      })
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'alpha' }))
    })

    it('searches immediately on Enter instead of waiting out the debounce', async () => {
      await renderTab()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'beta' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'beta' }))
    })

    it('ignores other keys', async () => {
      await renderTab()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'beta' } })
      fireEvent.keyDown(input, { key: 'a' })
      await flushPromises()

      expect(mockListTasks).not.toHaveBeenCalledWith(expect.objectContaining({ q: 'beta' }))
    })
  })

  describe('pagination', () => {
    it('shows no pager for a single page of results', async () => {
      await renderTab()

      expect(screen.getByText('Total 2 records')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
    })

    it('pages forward and back by offset', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1, TASK_2], total: 25 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
      await flushPromises()
      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })

    it('disables the edges of the pager', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1, TASK_2], total: 25 })
      await renderTab()

      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

      fireEvent.click(screen.getByRole('button', { name: '3' }))
      await flushPromises()

      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    })

    it('lists every page while they still fit', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 30 })
      await renderTab()

      for (const n of ['1', '2', '3']) {
        expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
      }
      expect(screen.queryByText('…')).not.toBeInTheDocument()
    })

    it('elides the middle of a long page range', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 200 })
      await renderTab()

      expect(screen.getByRole('button', { name: '20' })).toBeInTheDocument()
      expect(screen.getAllByText('…')).toHaveLength(1)

      fireEvent.click(screen.getByRole('button', { name: '20' }))
      await flushPromises()

      expect(screen.getAllByText('…')).toHaveLength(1)
      expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
    })

    it('elides on both sides when the current page is in the middle', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 200 })
      await renderTab()

      fireEvent.click(screen.getByRole('button', { name: '2' }))
      await flushPromises()
      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()

      expect(screen.getAllByText('…')).toHaveLength(2)
    })
  })
})
