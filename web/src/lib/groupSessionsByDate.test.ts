import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { groupSessionsByDate } from './groupSessionsByDate'
import type { Session } from '../api/sessions'

// Freeze time mid-day so "start of today" is unambiguous and the boundaries
// below do not shift while the suite runs.
const NOW = new Date('2026-07-31T12:00:00')
const DAY = 86400000

function sessionAt(id: string, updatedAt: Date | string): Session {
  const iso = typeof updatedAt === 'string' ? updatedAt : updatedAt.toISOString()
  return { id, title: `Session ${id}`, created_at: iso, updated_at: iso }
}

/** A local Date offset from the start of today, in days and ms. */
function fromStartOfToday(days: number, ms = 0): Date {
  const startOfToday = new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate()).getTime()
  return new Date(startOfToday + days * DAY + ms)
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('groupSessionsByDate', () => {
  it('returns no groups for no sessions', () => {
    expect(groupSessionsByDate([])).toEqual([])
  })

  it('omits empty groups', () => {
    const groups = groupSessionsByDate([sessionAt('a', NOW)])
    expect(groups).toHaveLength(1)
    expect(groups[0].key).toBe('today')
  })

  it('assigns each session to its date bucket', () => {
    const sessions = [
      sessionAt('today', NOW),
      sessionAt('yesterday', fromStartOfToday(-1)),
      sessionAt('week', fromStartOfToday(-3)),
      sessionAt('month', fromStartOfToday(-15)),
      sessionAt('ancient', fromStartOfToday(-400)),
    ]

    const groups = groupSessionsByDate(sessions)

    expect(groups.map((g) => g.key)).toEqual([
      'today',
      'yesterday',
      'last7days',
      'last30days',
      'older',
    ])
    expect(groups.map((g) => g.sessions[0].id)).toEqual([
      'today',
      'yesterday',
      'week',
      'month',
      'ancient',
    ])
  })

  it('returns groups newest-first regardless of input order', () => {
    const sessions = [
      sessionAt('ancient', fromStartOfToday(-400)),
      sessionAt('today', NOW),
      sessionAt('month', fromStartOfToday(-15)),
    ]

    expect(groupSessionsByDate(sessions).map((g) => g.key)).toEqual([
      'today',
      'last30days',
      'older',
    ])
  })

  it('sorts sessions inside a group by updated_at descending', () => {
    const sessions = [
      sessionAt('morning', new Date('2026-07-31T08:00:00')),
      sessionAt('noon', new Date('2026-07-31T12:00:00')),
      sessionAt('dawn', new Date('2026-07-31T05:00:00')),
    ]

    const [today] = groupSessionsByDate(sessions)

    expect(today.sessions.map((s) => s.id)).toEqual(['noon', 'morning', 'dawn'])
  })

  describe('bucket boundaries', () => {
    it('counts the first instant of today as today', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(0))])
      expect(group.key).toBe('today')
    })

    it('counts one millisecond before today as yesterday', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(0, -1))])
      expect(group.key).toBe('yesterday')
    })

    it('counts the first instant of yesterday as yesterday', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-1))])
      expect(group.key).toBe('yesterday')
    })

    it('counts one millisecond before yesterday as last7days', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-1, -1))])
      expect(group.key).toBe('last7days')
    })

    it('counts exactly 7 days back as last7days', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-7))])
      expect(group.key).toBe('last7days')
    })

    it('counts just before 7 days back as last30days', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-7, -1))])
      expect(group.key).toBe('last30days')
    })

    it('counts exactly 30 days back as last30days', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-30))])
      expect(group.key).toBe('last30days')
    })

    it('counts just before 30 days back as older', () => {
      const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(-30, -1))])
      expect(group.key).toBe('older')
    })
  })

  it('treats a future timestamp as today rather than dropping it', () => {
    const [group] = groupSessionsByDate([sessionAt('a', fromStartOfToday(5))])
    expect(group.key).toBe('today')
    expect(group.sessions).toHaveLength(1)
  })

  it('keeps every session across groups', () => {
    const sessions = [
      sessionAt('a', NOW),
      sessionAt('b', fromStartOfToday(-1)),
      sessionAt('c', fromStartOfToday(-3)),
      sessionAt('d', fromStartOfToday(-3)),
      sessionAt('e', fromStartOfToday(-400)),
    ]

    const total = groupSessionsByDate(sessions).reduce((n, g) => n + g.sessions.length, 0)

    expect(total).toBe(sessions.length)
  })
})
