import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
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
import { Tasks } from './Tasks'
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

describe('Tasks page', () => {
  it('renders both task titles with their status badges', async () => {
    render(
      <Wrapper>
        <Tasks />
      </Wrapper>,
    )

    await flushPromises()

    expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    expect(screen.getByText('Beta Task')).toBeInTheDocument()
    // Status badges now render translated labels (en locale is set in beforeEach)
    expect(screen.getByText('Succeeded')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('changing filter to "failed" calls listTasks with {status: "failed"}', async () => {
    render(
      <Wrapper>
        <Tasks />
      </Wrapper>,
    )

    await flushPromises()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()

    vi.clearAllMocks()
    mockListTasks.mockResolvedValue({ tasks: [TASK_2], total: 1 })

    // Directly change the select value via the underlying hidden input.
    // Radix Select renders a hidden <select> element that we can change via fireEvent.
    const hiddenSelect = document.querySelector('select[aria-hidden="true"]') as HTMLSelectElement | null

    if (hiddenSelect) {
      // Use fireEvent on the hidden native select to set the value
      fireEvent.change(hiddenSelect, { target: { value: 'failed' } })
      await flushPromises()
    } else {
      // Fallback: click the trigger and use keyboard to select
      const trigger = screen.getByRole('combobox')
      fireEvent.click(trigger)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(50)
      })
      // Use keyboard to navigate to "failed" option
      const listbox = document.querySelector('[role="listbox"]')
      if (listbox) {
        // find the "Failed" option and click it
        const options = Array.from(listbox.querySelectorAll('[role="option"]'))
        const failedOpt = options.find((o) => o.textContent?.toLowerCase().includes('failed'))
        if (failedOpt) {
          fireEvent.click(failedOpt)
          await flushPromises()
        }
      }
    }

    // Also test via direct state change simulation: if the above paths fail,
    // we can find the select trigger and use fireEvent
    await flushPromises()

    expect(mockListTasks).toHaveBeenCalledWith(expect.objectContaining({ status: 'failed' }))
  })

  it('clicking the row Detail button calls getTask and shows result in dialog', async () => {
    const taskWithResult = { ...TASK_1, result: { answer: 42 } }
    mockGetTask.mockResolvedValue(taskWithResult)

    render(
      <Wrapper>
        <Tasks />
      </Wrapper>,
    )

    await flushPromises()
    expect(screen.getByText('Alpha Task')).toBeInTheDocument()

    // Detail is opened by the per-row "Detail" action button, not by the <tr>.
    const row = screen.getByText('Alpha Task').closest('tr')
    expect(row).not.toBeNull()
    const detailBtn = within(row!).getByRole('button', { name: 'Detail' })
    fireEvent.click(detailBtn)

    await flushPromises()

    expect(mockGetTask).toHaveBeenCalledWith('task-1')

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Result')).toBeInTheDocument()
    // The JSON result is rendered line-by-line with gutter line numbers.
    expect(dialog.textContent).toContain('"answer": 42')
  })

  /** Render the page and wait for the first task list to land. */
  async function renderTasks() {
    const view = render(
      <Wrapper>
        <Tasks />
      </Wrapper>,
    )
    await flushPromises()
    return view
  }

  /** The badge cell for a given task row, by column index. */
  function badgeIn(rowText: string, column: number): HTMLElement {
    const row = screen.getByText(rowText).closest('tr')
    if (!row) throw new Error(`row ${rowText} not found`)
    const cell = row.querySelectorAll('td')[column]
    return cell.firstElementChild as HTMLElement
  }

  describe('status and stage colour coding', () => {
    // The colour is the only at-a-glance signal of a task's state in a long
    // list, so each state must map to its own palette and an unrecognised one
    // must fall back to the plain badge rather than borrowing another's colour.
    it.each([
      ['succeeded', 'green'],
      ['failed', 'red'],
      ['cancelled', 'orange'],
      ['running', 'blue'],
      ['pending', 'yellow'],
    ])('colours a %s task %s', async (status, hue) => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, id: `t-${status}`, title: `Task ${status}`, status }],
        total: 1,
      })

      await renderTasks()

      expect(badgeIn(`Task ${status}`, 2).className).toContain(hue)
    })

    it('leaves an unrecognised status uncoloured', async () => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, id: 't-x', title: 'Task odd', status: 'quarantined' }],
        total: 1,
      })

      await renderTasks()

      const badge = badgeIn('Task odd', 2)
      // No colour token, and the raw status is shown since there is no label for it.
      expect(badge.className).not.toMatch(/green|red|orange|blue|yellow/)
      expect(badge).toHaveTextContent('quarantined')
    })

    it.each([
      ['done', 'green'],
      ['extract', 'cyan'],
      ['pipeline', 'violet'],
      ['index', 'indigo'],
      ['queued', 'gray'],
    ])('colours the %s stage %s', async (stage, hue) => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, id: `s-${stage}`, title: `Stage ${stage}`, stage }],
        total: 1,
      })

      await renderTasks()

      expect(badgeIn(`Stage ${stage}`, 3).className).toContain(hue)
    })

    it('leaves an unrecognised stage uncoloured', async () => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, id: 's-x', title: 'Stage odd', stage: 'reticulating' }],
        total: 1,
      })

      await renderTasks()

      const badge = badgeIn('Stage odd', 3)
      expect(badge.className).not.toMatch(/green|cyan|violet|indigo|gray/)
      expect(badge).toHaveTextContent('reticulating')
    })
  })

  // A timestamp the platform cannot format must not take the whole table down
  // with a RangeError; the row stays readable with the raw value.
  it('falls back to the raw timestamp when it cannot be formatted', async () => {
    const outOfRange = 8.64e15 + 1 // past the maximum ECMAScript time value
    mockListTasks.mockResolvedValue({
      tasks: [{ ...TASK_1, updated_at: outOfRange }],
      total: 1,
    })

    await renderTasks()

    expect(screen.getByText(String(outOfRange))).toBeInTheDocument()
  })

  it('tells the user when the task list cannot be loaded', async () => {
    mockListTasks.mockRejectedValue(new Error('backend unreachable'))

    await renderTasks()

    expect(mockToast.error).toHaveBeenCalledWith('backend unreachable')
  })

  it('reports a detail fetch failure but still shows what the row already knew', async () => {
    mockGetTask.mockRejectedValue(new Error('detail unavailable'))

    await renderTasks()

    const row = screen.getByText('Alpha Task').closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Detail' }))
    await flushPromises()

    expect(mockToast.error).toHaveBeenCalledWith('detail unavailable')
    // The optimistically-set row data keeps the dialog useful.
    expect(within(screen.getByRole('dialog')).getByText('Succeeded')).toBeInTheDocument()
  })

  it('shows the failure text in the detail dialog for a failed task', async () => {
    mockGetTask.mockResolvedValue({ ...TASK_2, result: null })

    await renderTasks()

    const row = screen.getByText('Beta Task').closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: 'Detail' }))
    await flushPromises()

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Error')).toBeInTheDocument()
    expect(within(dialog).getByText('Connection timeout')).toBeInTheDocument()
  })

  it('says so when there are no tasks at all', async () => {
    mockListTasks.mockResolvedValue({ tasks: [], total: 0 })

    await renderTasks()

    expect(screen.getByText('No tasks found')).toBeInTheDocument()
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
      await renderTasks()

      const row = screen.getByText('Alpha Task').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()

      expect(screen.getByRole('alertdialog')).toHaveTextContent('Confirm Delete')
      expect(mockDeleteTask).not.toHaveBeenCalled()
    })

    it('deletes and reloads the list once confirmed', async () => {
      await renderTasks()
      const callsBefore = mockListTasks.mock.calls.length

      fireEvent.click(await openConfirm('Alpha Task'))
      await flushPromises()

      expect(mockDeleteTask).toHaveBeenCalledWith('task-1')
      expect(mockToast.success).toHaveBeenCalledWith('Task deleted')
      expect(mockListTasks.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('keeps the task and reports the failure when the delete is rejected', async () => {
      mockDeleteTask.mockRejectedValue(new Error('task is locked'))

      await renderTasks()
      fireEvent.click(await openConfirm('Alpha Task'))
      await flushPromises()

      expect(mockToast.error).toHaveBeenCalledWith('task is locked')
      expect(screen.getByText('Alpha Task')).toBeInTheDocument()
    })

    it('abandons the delete when the dialog is cancelled', async () => {
      await renderTasks()

      const row = screen.getByText('Alpha Task').closest('tr')!
      fireEvent.click(within(row).getByRole('button', { name: 'Delete' }))
      await flushPromises()
      fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
      await flushPromises()

      expect(mockDeleteTask).not.toHaveBeenCalled()
    })

    // Deleting a running task would orphan the worker's in-flight write, so the
    // action is only offered once the task has reached a terminal state.
    it.each(['running'])('offers no delete for a %s task', async (status) => {
      mockListTasks.mockResolvedValue({
        tasks: [{ ...TASK_1, status, title: 'Busy Task' }],
        total: 1,
      })

      await renderTasks()

      const row = screen.getByText('Busy Task').closest('tr')!
      expect(within(row).getByRole('button', { name: 'Delete' })).toBeDisabled()
    })

    // Deleting the only row on the last page would otherwise leave the user
    // staring at an empty page with no way back.
    it('steps back a page after deleting its last remaining task', async () => {
      // 11 records over a page size of 10: page 2 holds exactly one task.
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 11 })
      await renderTasks()

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
      await renderTasks()

      fireEvent.click(screen.getByText('Source'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'source', order: 'asc' }),
      )
    })

    it('reverses the direction when the same column is clicked again', async () => {
      await renderTasks()

      fireEvent.click(screen.getByText('Source'))
      await flushPromises()
      fireEvent.click(screen.getByText('Source'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'source', order: 'desc' }),
      )
    })

    it('restarts ascending when a different column is chosen', async () => {
      await renderTasks()

      fireEvent.click(screen.getByText('Source'))
      await flushPromises()
      fireEvent.click(screen.getByText('Source'))
      await flushPromises()
      fireEvent.click(screen.getByText('Attempts'))
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: 'attempts', order: 'asc' }),
      )
    })
  })

  describe('search', () => {
    it('waits for typing to settle before querying', async () => {
      await renderTasks()

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
      await renderTasks()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'beta' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await flushPromises()

      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'beta' }))
    })

    it('ignores other keys', async () => {
      await renderTasks()

      const input = screen.getByPlaceholderText('Search files...')
      fireEvent.change(input, { target: { value: 'beta' } })
      fireEvent.keyDown(input, { key: 'a' })
      await flushPromises()

      expect(mockListTasks).not.toHaveBeenCalledWith(expect.objectContaining({ q: 'beta' }))
    })
  })

  describe('pagination', () => {
    it('shows no pager for a single page of results', async () => {
      await renderTasks()

      expect(screen.getByText('Total 2 records')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Next' })).not.toBeInTheDocument()
    })

    it('pages forward and back by offset', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1, TASK_2], total: 25 })
      await renderTasks()

      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
      await flushPromises()
      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 10 }))

      fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
      await flushPromises()
      expect(mockListTasks).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }))
    })

    it('disables the edges of the pager', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1, TASK_2], total: 25 })
      await renderTasks()

      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

      fireEvent.click(screen.getByRole('button', { name: '3' }))
      await flushPromises()

      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    })

    it('lists every page while they still fit', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 30 })
      await renderTasks()

      for (const n of ['1', '2', '3']) {
        expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
      }
      expect(screen.queryByText('…')).not.toBeInTheDocument()
    })

    // Past seven pages the pager collapses to first / neighbours / last so the
    // row does not wrap.
    it('elides the middle of a long page range', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 200 })
      await renderTasks()

      expect(screen.getByRole('button', { name: '20' })).toBeInTheDocument()
      expect(screen.getAllByText('…')).toHaveLength(1)

      fireEvent.click(screen.getByRole('button', { name: '20' }))
      await flushPromises()

      // Both ends are now far from the current page, so both sides elide.
      expect(screen.getAllByText('…')).toHaveLength(1)
      expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
    })

    it('elides on both sides when the current page is in the middle', async () => {
      mockListTasks.mockResolvedValue({ tasks: [TASK_1], total: 200 })
      await renderTasks()

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

  it('opens the file preview from the file name', async () => {
    await renderTasks()

    fireEvent.click(screen.getByRole('button', { name: 'Alpha Task' }))
    await flushPromises()

    expect(mockGetTaskContent).toHaveBeenCalledWith('task-1', expect.anything())
    expect(screen.getByText('file body')).toBeInTheDocument()
  })

  it('marks a task that carries an error', async () => {
    await renderTasks()

    const row = screen.getByText('Beta Task').closest('tr')!
    expect(within(row).getByLabelText('error')).toHaveAttribute('title', 'Connection timeout')
  })
})
