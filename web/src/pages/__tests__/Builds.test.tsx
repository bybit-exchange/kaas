import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

// Mock the API modules
vi.mock('@/api/tasks', () => ({
  listTasks: vi.fn(),
  deleteTask: vi.fn(),
  getTask: vi.fn(),
  getTaskContent: vi.fn(),
}))

vi.mock('@/api/derived', () => ({
  listDeriveJobs: vi.fn(),
  deleteDeriveJob: vi.fn(),
  getDeriveJob: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { Builds } from '../Builds'
import { listTasks } from '@/api/tasks'
import { listDeriveJobs } from '@/api/derived'

const mockListTasks = vi.mocked(listTasks)
const mockListDeriveJobs = vi.mocked(listDeriveJobs)

function emptyTasksResponse() {
  return { tasks: [], total: 0 }
}

function emptyDeriveResponse() {
  return { jobs: [], total: 0 }
}

/**
 * Render the Builds page at a given route, wrapped with the full router
 * context so useParams().tab works correctly.
 */
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LangProvider>
        <Routes>
          <Route path="builds/:tab?" element={<Builds />} />
          {/* Catch redirects: the Navigate inside Builds redirects to /builds/tasks
              which is handled by the builds/:tab? route above. */}
        </Routes>
      </LangProvider>
    </MemoryRouter>,
  )
}

// jsdom does not implement scrollIntoView
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = () => {}
}

beforeEach(() => {
  usePrefs.setState({ theme: 'light', lang: 'en' })
  vi.clearAllMocks()
  vi.useFakeTimers()

  // Default: all stats return 0
  mockListTasks.mockResolvedValue(emptyTasksResponse())
  mockListDeriveJobs.mockResolvedValue(emptyDeriveResponse())
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

describe('Builds page', () => {
  it('renders TasksTab by default when no tab param is given', async () => {
    mockListTasks.mockResolvedValue({
      tasks: [
        {
          id: 't1',
          source: 'paste',
          title: 'My Task',
          status: 'succeeded',
          stage: 'done',
          attempts: 1,
          max_attempts: 3,
          created_at: 1704103200000,
          updated_at: 1704103500000,
        },
      ],
      total: 1,
    })

    renderAt('/builds')
    await flushPromises()

    // The page title should be visible
    expect(screen.getByText('Builds')).toBeInTheDocument()
    // The stats bar should show both tab labels
    expect(screen.getByText('Normal Tasks')).toBeInTheDocument()
    expect(screen.getByText('Derive Jobs')).toBeInTheDocument()
    // TasksTab content should be rendered (the task title)
    expect(screen.getByText('My Task')).toBeInTheDocument()
  })

  it('renders DeriveJobsTab when tab is "derive"', async () => {
    mockListDeriveJobs.mockResolvedValue({
      jobs: [
        {
          id: 'dj1',
          slug: 'test-slug',
          topic: 'Test Topic',
          model: 'gpt-4',
          select_from: 'articles',
          status: 'running',
          stage: 'filter',
          created_at: 1704103200000,
          updated_at: 1704103500000,
        },
      ],
      total: 1,
    })

    renderAt('/builds/derive')
    await flushPromises()

    expect(screen.getByText('Test Topic')).toBeInTheDocument()
  })

  it('redirects an invalid tab to /builds/tasks', async () => {
    renderAt('/builds/invalid-tab')
    await flushPromises()

    // The Navigate component redirects to /builds/tasks which re-matches
    // builds/:tab? with tab="tasks", showing the default tasks page.
    // The page title confirms we ended up at the Builds page.
    expect(screen.getByText('Builds')).toBeInTheDocument()
    expect(screen.getByText('Normal Tasks')).toBeInTheDocument()
  })

  it('fetches stats using 4 limit=1 API calls on mount', async () => {
    mockListTasks.mockImplementation(async (p) => {
      if (p?.status === 'pending') return { tasks: [], total: 2 }
      if (p?.status === 'running') return { tasks: [], total: 1 }
      return { tasks: [], total: 0 }
    })
    mockListDeriveJobs.mockImplementation(async (p) => {
      if (p?.status === 'pending') return { jobs: [], total: 0 }
      if (p?.status === 'running') return { jobs: [], total: 1 }
      return { jobs: [], total: 0 }
    })

    renderAt('/builds')
    await flushPromises()

    // Should have called listTasks with status: pending, limit: 1
    expect(mockListTasks).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending', limit: 1 }),
    )
    expect(mockListTasks).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'running', limit: 1 }),
    )
    // Should have called listDeriveJobs with status: pending, limit: 1
    expect(mockListDeriveJobs).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending', limit: 1 }),
    )
    expect(mockListDeriveJobs).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'running', limit: 1 }),
    )
  })

  it('switches tabs via StatsBar clicks using replace navigation', async () => {
    mockListTasks.mockResolvedValue(emptyTasksResponse())
    mockListDeriveJobs.mockResolvedValue(emptyDeriveResponse())

    renderAt('/builds/tasks')
    await flushPromises()

    // Click the "Derive Jobs" tab in the stats bar using fireEvent to avoid
    // userEvent timer interaction issues with fake timers
    fireEvent.click(screen.getByText('Derive Jobs'))
    await flushPromises()

    // The component should now show derive content. Since DeriveJobsTab renders
    // with empty data, we check its empty state message
    expect(screen.getByText('No derive jobs yet.')).toBeInTheDocument()
  })
})
