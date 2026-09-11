import type { CSSProperties } from 'react'
import { useT } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'

/** Terminal statuses where we only show the status text, no stage suffix. */
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'partial'])

export interface StatusBadgeStyle {
  color: string
  backgroundColor: string
  borderColor: string
}

/** Returns WCAG AA-compliant inline style colors for a given status. */
export function statusBadgeStyles(status: string): StatusBadgeStyle & CSSProperties {
  switch (status) {
    case 'succeeded':  return { color: '#1a7a3a', backgroundColor: '#e8f5e9', borderColor: '#a5d6a7' }
    case 'failed':     return { color: '#b5302b', backgroundColor: '#ffe8e7', borderColor: '#ef9a9a' }
    case 'cancelled':  return { color: '#a04a1b', backgroundColor: '#fff3e0', borderColor: '#ffcc80' }
    case 'partial':    return { color: '#7a6010', backgroundColor: '#fff8e1', borderColor: '#ffe082' }
    case 'running':    return { color: '#0f5f6d', backgroundColor: '#e0f5f5', borderColor: '#80cbc4' }
    case 'pending':    return { color: '#6a5f10', backgroundColor: '#fdf8e8', borderColor: '#fff59d' }
    default:           return { color: '#4b5563', backgroundColor: '#f3f4f6', borderColor: '#d1d5db' }
  }
}

/**
 * Maps a status string to Tailwind border+text color classes.
 * @deprecated Use {@link statusBadgeStyles} instead for WCAG-compliant inline styles.
 */
export function statusColor(status: string): string {
  switch (status) {
    case 'succeeded':
      return 'border-green-300 text-green-700 dark:border-green-700 dark:text-green-400'
    case 'failed':
      return 'border-red-300 text-red-700 dark:border-red-700 dark:text-red-400'
    case 'cancelled':
      return 'border-orange-300 text-orange-700 dark:border-orange-700 dark:text-orange-400'
    case 'partial':
      return 'border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-400'
    case 'running':
      return 'border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-400'
    case 'pending':
      return 'border-yellow-300 text-yellow-700 dark:border-yellow-700 dark:text-yellow-400'
    default:
      return ''
  }
}

/** Translate a status key to its display label. */
function statusLabel(t: (key: string) => string, status: string): string {
  const key = `status.filter.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

/**
 * Translate a stage key to its display label.
 * Tries `stage.{stage}` first (task stages), then `deriveStage.{stage}` (derive stages).
 * Falls back to the raw stage string if neither key resolves.
 */
function stageLabel(t: (key: string) => string, stage: string): string {
  const taskKey = `stage.${stage}`
  const taskTranslated = t(taskKey)
  if (taskTranslated !== taskKey) return taskTranslated

  const deriveKey = `deriveStage.${stage}`
  const deriveTranslated = t(deriveKey)
  if (deriveTranslated !== deriveKey) return deriveTranslated

  return stage
}

export interface StatusStageBadgeProps {
  status: string
  stage?: string
  className?: string
}

/**
 * Renders a single Badge showing status and (optionally) stage.
 *
 * - Running/pending with a non-terminal stage: "Running · Extracting"
 * - Terminal status (succeeded/failed/cancelled): just "Succeeded"
 */
export function StatusStageBadge({ status, stage, className }: StatusStageBadgeProps) {
  const t = useT()
  const styles = statusBadgeStyles(status)
  const sLabel = statusLabel(t, status)

  let text: string
  if (TERMINAL_STATUSES.has(status) || !stage) {
    text = sLabel
  } else {
    const sgLabel = stageLabel(t, stage)
    text = `${sLabel} · ${sgLabel}`
  }

  return (
    <Badge
      variant="outline"
      className={cn('px-2 py-0.5', className)}
      style={styles}
    >
      {text}
    </Badge>
  )
}
