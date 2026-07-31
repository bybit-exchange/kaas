import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

// Mock the tasks API
vi.mock('@/api/tasks', () => ({
  listTasks: vi.fn(),
  getTask: vi.fn(),
}))

// Import AFTER mocking
import { Tasks } from './Tasks'
import { listTasks, getTask } from '@/api/tasks'

const mockListTasks = vi.mocked(listTasks)
const mockGetTask = vi.mocked(getTask)

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
})
