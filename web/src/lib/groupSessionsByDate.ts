import type { Session } from '../api/sessions'

export type DateGroup = 'today' | 'yesterday' | 'last7days' | 'last30days' | 'older'

export interface SessionGroup {
  key: DateGroup
  sessions: Session[]
}

/**
 * Group sessions by date based on updated_at.
 * Returns groups in chronological order (today first, older last).
 * Sessions within each group are sorted by updated_at DESC.
 */
export function groupSessionsByDate(sessions: Session[]): SessionGroup[] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfYesterday = startOfToday - 86400000
  const startOf7DaysAgo = startOfToday - 7 * 86400000
  const startOf30DaysAgo = startOfToday - 30 * 86400000

  const groups: Record<DateGroup, Session[]> = {
    today: [],
    yesterday: [],
    last7days: [],
    last30days: [],
    older: [],
  }

  for (const session of sessions) {
    const ts = new Date(session.updated_at).getTime()
    if (ts >= startOfToday) {
      groups.today.push(session)
    } else if (ts >= startOfYesterday) {
      groups.yesterday.push(session)
    } else if (ts >= startOf7DaysAgo) {
      groups.last7days.push(session)
    } else if (ts >= startOf30DaysAgo) {
      groups.last30days.push(session)
    } else {
      groups.older.push(session)
    }
  }

  // Sort sessions within each group by updated_at DESC
  const sortDesc = (a: Session, b: Session) =>
    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()

  const order: DateGroup[] = ['today', 'yesterday', 'last7days', 'last30days', 'older']
  const result: SessionGroup[] = []

  for (const key of order) {
    if (groups[key].length > 0) {
      groups[key].sort(sortDesc)
      result.push({ key, sessions: groups[key] })
    }
  }

  return result
}
