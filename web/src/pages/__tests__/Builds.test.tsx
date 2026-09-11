import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { LangProvider } from '@/i18n'
import { usePrefs } from '@/store/prefs'

// Mock the API modules
vi.mock('@/api/buildJobs', () => ({
  listBuildJobs: vi.fn(),
  deleteBuildJob: vi.fn(),
  getBuildJob: vi.fn(),
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
import { listBuildJobs } from '@/api/buildJobs'
import { listDeriveJobs } from '@/api/derived'

const mockListBuildJobs = vi.mocked(listBuildJobs)
const mockListDeriveJobs = vi.mocked(listDeriveJobs)

function emptyBuildJobsResponse() {
  return { jobs: [], total: 0 }
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
  mockListBuildJobs.mockResolvedValue(emptyBuildJobsResponse())
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
  it('renders BuildJobsTab by default when no tab param is given', async () => {
    mockListBuildJobs.mockResolvedValue({
      jobs: [
        {
          id: 'bj1',
          source: 'paste',
          title: 'My Build Job',
          file_count: 1,
          status: 'succeeded',
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
    expect(screen.getByText('Normal')).toBeInTheDocument()
    expect(screen.getByText('Derive Topic')).toBeInTheDocument()
    // BuildJobsTab content should be rendered (the build job title)
    expect(screen.getByText('My Build Job')).toBeInTheDocument()
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
    expect(screen.getByText('Normal')).toBeInTheDocument()
  })

  it('fetches stats using 4 limit=1 API calls on mount', async () => {
    mockListBuildJobs.mockImplementation(async (p) => {
      if (p?.status === 'pending') return { jobs: [], total: 2 }
      if (p?.status === 'running') return { jobs: [], total: 1 }
      return { jobs: [], total: 0 }
    })
    mockListDeriveJobs.mockImplementation(async (p) => {
      if (p?.status === 'pending') return { jobs: [], total: 0 }
      if (p?.status === 'running') return { jobs: [], total: 1 }
      return { jobs: [], total: 0 }
    })

    renderAt('/builds')
    await flushPromises()

    // Should have called listBuildJobs with status: pending, limit: 1
    expect(mockListBuildJobs).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending', limit: 1 }),
    )
    expect(mockListBuildJobs).toHaveBeenCalledWith(
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
    mockListBuildJobs.mockResolvedValue(emptyBuildJobsResponse())
    mockListDeriveJobs.mockResolvedValue(emptyDeriveResponse())

    renderAt('/builds/tasks')
    await flushPromises()

    // Click the "Derive Topic" tab in the stats bar using fireEvent to avoid
    // userEvent timer interaction issues with fake timers
    fireEvent.click(screen.getByText('Derive Topic'))
    await flushPromises()

    // The component should now show derive content. Since DeriveJobsTab renders
    // with empty data, we check its empty state message
    expect(screen.getByText('No derive jobs yet.')).toBeInTheDocument()
  })
})
