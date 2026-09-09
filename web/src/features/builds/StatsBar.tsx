import { useT } from '@/i18n'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import type { BuildTab, BuildsStats } from './types'

export interface StatsBarProps {
  stats: BuildsStats
  activeTab: BuildTab
  onTabChange: (tab: BuildTab) => void
}

/**
 * Global stats bar with two clickable segments (Normal Tasks | Derive Jobs).
 * Shows a "●N active" badge on each segment when pending+running > 0.
 * Active tab segment has a highlighted background.
 */
export function StatsBar({ stats, activeTab, onTabChange }: StatsBarProps) {
  const t = useT()

  const tabs: { key: BuildTab; labelKey: string }[] = [
    { key: 'tasks', labelKey: 'builds.tabTasks' },
    { key: 'derive', labelKey: 'builds.tabDerive' },
  ]

  return (
    <Card className="inline-flex flex-row p-1 gap-1">
      {tabs.map(({ key, labelKey }) => {
        const counts = stats[key]
        const activeCount = counts.pending + counts.running
        const isActive = activeTab === key

        return (
          <button
            key={key}
            type="button"
            onClick={() => onTabChange(key)}
            className={cn(
              'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
              'flex items-center justify-center gap-2',
              isActive
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted',
            )}
          >
            {t(labelKey)}
            {activeCount > 0 && (
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
                  isActive
                    ? 'bg-primary-foreground/20 text-primary-foreground'
                    : 'bg-primary/10 text-primary',
                )}
              >
                ●{t('builds.statsActive', { count: activeCount })}
              </span>
            )}
          </button>
        )
      })}
    </Card>
  )
}
