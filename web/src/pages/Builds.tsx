import { useCallback, useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useT } from '@/i18n'
import { listTasks } from '@/api/tasks'
import { listDeriveJobs } from '@/api/derived'
import { StatsBar } from '@/features/builds/StatsBar'
import { TasksTab } from '@/features/builds/TasksTab'
import { DeriveJobsTab } from '@/features/builds/DeriveJobsTab'
import { useAutoPolling } from '@/features/builds/useAutoPolling'
import type { BuildTab, BuildsStats } from '@/features/builds/types'

const VALID_TABS: ReadonlySet<string> = new Set<BuildTab>(['tasks', 'derive'])

export function Builds() {
  const t = useT()
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()

  const activeTab: BuildTab = tab !== undefined && VALID_TABS.has(tab)
    ? (tab as BuildTab)
    : 'tasks'

  const [stats, setStats] = useState<BuildsStats>({
    tasks: { pending: 0, running: 0 },
    derive: { pending: 0, running: 0 },
    loading: true,
  })

  const fetchStats = useCallback(async () => {
    try {
      const [tasksPending, tasksRunning, derivePending, deriveRunning] =
        await Promise.all([
          listTasks({ status: 'pending', limit: 1 }),
          listTasks({ status: 'running', limit: 1 }),
          listDeriveJobs({ status: 'pending', limit: 1 }),
          listDeriveJobs({ status: 'running', limit: 1 }),
        ])
      setStats({
        tasks: {
          pending: tasksPending.total,
          running: tasksRunning.total,
        },
        derive: {
          pending: derivePending.total,
          running: deriveRunning.total,
        },
        loading: false,
      })
    } catch {
      // Keep previous stats on error, just mark not loading
      setStats((prev) => ({ ...prev, loading: false }))
    }
  }, [])

  // Initial fetch
  useEffect(() => {
    void fetchStats()
  }, [fetchStats])

  const hasActiveItems =
    stats.tasks.pending + stats.tasks.running +
    stats.derive.pending + stats.derive.running > 0

  useAutoPolling(fetchStats, hasActiveItems)

  // Redirect invalid tab values — placed after all hooks to maintain hook order
  if (tab !== undefined && !VALID_TABS.has(tab)) {
    return <Navigate to="/builds/tasks" replace />
  }

  function handleTabChange(next: BuildTab) {
    navigate(`/builds/${next}`, { replace: true })
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-4 text-xl font-semibold">{t('builds.title')}</h1>
      <div className="mb-4">
        <StatsBar stats={stats} activeTab={activeTab} onTabChange={handleTabChange} />
      </div>
      {activeTab === 'tasks' ? <TasksTab /> : <DeriveJobsTab />}
    </div>
  )
}
