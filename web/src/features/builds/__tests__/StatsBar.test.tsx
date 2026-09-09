import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePrefs } from '@/store/prefs'
import { StatsBar } from '../StatsBar'
import type { BuildsStats } from '../types'

function makeStats(overrides?: Partial<BuildsStats>): BuildsStats {
  return {
    tasks: { pending: 0, running: 0 },
    derive: { pending: 0, running: 0 },
    loading: false,
    ...overrides,
  }
}

describe('StatsBar', () => {
  beforeEach(() => {
    usePrefs.setState({ theme: 'light', lang: 'en' })
  })

  it('renders both tab labels', () => {
    render(
      <StatsBar stats={makeStats()} activeTab="tasks" onTabChange={() => {}} />,
    )
    expect(screen.getByText('Normal Tasks')).toBeInTheDocument()
    expect(screen.getByText('Derive Jobs')).toBeInTheDocument()
  })

  it('shows active count badge when tasks have active items', () => {
    render(
      <StatsBar
        stats={makeStats({ tasks: { pending: 1, running: 1 } })}
        activeTab="tasks"
        onTabChange={() => {}}
      />,
    )
    expect(screen.getByText(/●2 active/)).toBeInTheDocument()
  })

  it('shows active count badge for derive tab', () => {
    render(
      <StatsBar
        stats={makeStats({ derive: { pending: 0, running: 3 } })}
        activeTab="tasks"
        onTabChange={() => {}}
      />,
    )
    expect(screen.getByText(/●3 active/)).toBeInTheDocument()
  })

  it('hides badge when counts are 0', () => {
    render(
      <StatsBar stats={makeStats()} activeTab="tasks" onTabChange={() => {}} />,
    )
    expect(screen.queryByText(/active/)).not.toBeInTheDocument()
  })

  it('calls onTabChange when a segment is clicked', async () => {
    const onTabChange = vi.fn()
    render(
      <StatsBar stats={makeStats()} activeTab="tasks" onTabChange={onTabChange} />,
    )
    await userEvent.click(screen.getByText('Derive Jobs'))
    expect(onTabChange).toHaveBeenCalledWith('derive')
  })

  it('calls onTabChange with "tasks" when tasks segment is clicked', async () => {
    const onTabChange = vi.fn()
    render(
      <StatsBar stats={makeStats()} activeTab="derive" onTabChange={onTabChange} />,
    )
    await userEvent.click(screen.getByText('Normal Tasks'))
    expect(onTabChange).toHaveBeenCalledWith('tasks')
  })

  it('highlights the active tab with primary background', () => {
    const { container } = render(
      <StatsBar stats={makeStats()} activeTab="tasks" onTabChange={() => {}} />,
    )
    const buttons = container.querySelectorAll('button')
    // First button (tasks) should have active styles
    expect(buttons[0].className).toContain('bg-primary')
    // Second button (derive) should NOT have active styles
    expect(buttons[1].className).not.toContain('bg-primary')
  })

  it('highlights derive tab when activeTab is derive', () => {
    const { container } = render(
      <StatsBar stats={makeStats()} activeTab="derive" onTabChange={() => {}} />,
    )
    const buttons = container.querySelectorAll('button')
    expect(buttons[0].className).not.toContain('bg-primary')
    expect(buttons[1].className).toContain('bg-primary')
  })
})
